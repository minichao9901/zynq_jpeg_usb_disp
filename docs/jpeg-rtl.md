# PL JPEG 解码与验证

JPEG 型 USB 帧到齐后，Cortex-A9 将压缩缓冲写回 DDR，通过 GP0 配置 `0x43c10000` 上的 JPEG 外设。外设经 64 位 HP1 读取码流，在 PL 完成标记解析、Huffman 解码、反量化、IDCT、色度上采样和 BGR888 转换，再经 HP1 写回后台显示缓冲。CPU 等待 AXI 写响应后失效对应的缓存行，并沿用帧边界发布逻辑。LCD 仍由 HP0 上的 VDMA 持续扫描。像素时钟改用固定 33 MHz Clocking Wizard。

`jpeg_entropy.v` 按单扫描 Baseline 处理灰度和 YCbCr 4:4:4、水平 4:2:2、4:2:0，支持 8 位量化表、动态 Huffman 表及 DRI/RST。它校验 SOF 尺寸、表定义、重启顺序、尾部填充及 EOI。渐进式、多扫描、CMYK、算术编码和其他采样布局不在支持范围。色度使用最近邻上采样，定点 IDCT 舍入也与旧 NEON 版有差异。

`jpeg_dma.v` 在 4 KiB 边界拆分写 burst，以 byte strobe 保护非对齐矩形外的像素。解码失败时，固件等待已发出的 AXI 请求排空并丢弃后台画面。如果总线无法排空，固件隔离该缓冲并停止继续提交 JPEG 任务。RGB565 继续走原 CPU 转换路径。JPEG 诊断中 `neon` 为 0，`jpeg_rtl` 报告外设是否可用，`jpeg_hw_status` 和 `jpeg_hw_cycles` 记录最近一次任务。

| 偏移 | 含义 |
| --- | --- |
| 0x00 | 读出 ABI 标识 `0x4a504701`，写 bit 0 启动、bit 1 中止 |
| 0x04 | bit 0 忙、bit 1 完成、bit 2 错误、bits 15:8 错误码 |
| 0x08 / 0x0c | 64 字节对齐的 DDR 源地址、码流字节数 |
| 0x10 / 0x14 | 目标矩形首像素地址、尺寸（高 16 位为高度、低 16 位为宽度），固定行跨度 2400 字节 |
| 0x18 / 0x1c | 任务周期数、已接收的输出像素数 |
| 0x20 / 0x24 / 0x28 | 写 burst 数、AW 握手等待周期、W 握手等待周期 |
| 0x2c | 等待 B 响应且无法继续发写或结束任务的周期 |
| 0x30 / 0x34 | 像素输出受反压、JPEG 输入 FIFO 为空的周期 |
| 0x38 / 0x3c | 在途写峰值、在途写窗口（1～8，复位为 8，仅空闲时可改） |

错误码 1–7 依次代表描述符、JPEG 码流、AXI 读、AXI 写、超时、中止及像素计数。CPU 配置寄存器后启动任务，忙位清除前保留源和目标缓冲。

写端在发完一个 burst 的 W 数据后即可继续发下一笔。地址握手消耗一个在途写名额，收到 B 响应后归还。成功、失败和中止都等已发出的写请求排空后才清除忙位。等待计数按帧清零，各阶段可以同时等待，因此这些计数不能直接相加。

验证使用 `python tools/jpeg_rtl_sim.py`，通过有反压的 AXI DDR 模型从 JPEG 字节一直检查到 BGR888 帧缓冲。测试包括 800×480 全幅图、奇数尺寸矩形、跨页写入、截断、错误重启标记和总线故障后的恢复。结果保存在 `build/jpeg-rtl-sim/results.json`。Vivado 实现报告在 `build/fpga-jpeg-rtl/`。

| 800×480 仿真图 | 100 MHz 下的任务时间 | 相对 Pillow 的最大 / 平均通道误差 |
| --- | ---: | ---: |
| 4:2:0 彩色渐变 | 6.78 ms | 5 / 1.1325 |
| 4:2:0 高熵亮度 | 14.41 ms | 2 / 0.5357 |

表中的任务时间来自初版仿真，模型的额外 B 响应延迟只有 0～3 周期。

Vivado 2018.3 为 XC7Z020CLG400-2 完成综合、布局布线及 bit 生成。当前版在 100 MHz 下的最差建立裕量为 +0.005 ns，最差保持裕量为 +0.034 ns，DRC 为 0 错误。相较初版，整机多用 109 个 LUT 和 173 个 FF。SDK 2018.3 用同次 HDF 生成 BSP 并链接两套 ARM ELF。

## HP1 板测对比

初版把每行的八个像素打成 24 字节写 burst，一笔 B 响应返回后才发下一笔。800×480 每帧实测发出 48,188 笔，其中包含跨 4 KiB 边界拆出的 burst。新版用同一个 bitstream 切换 1 和 8 笔在途窗口。单笔模式复现了初版的 21.20 ms，B 响应等待约 1,590,800 周期，占任务时间约 75%。两种模式的 AW 等待均为 0，W 等待均为 95,624 周期。8 笔窗口实测峰值为 5 笔在途，只在收尾阻塞等 B 30 周期。写响应路径参见 [AMD UG585](https://docs.amd.com/r/en-US/ug585-zynq-7000-SoC-TRM/Performance-Optimization-Summary)。

| 相同的 800×480 输入 | 初版 PL 任务 | 新版 PL 任务 | USB 发帧到板端解码完成 |
| --- | ---: | ---: | ---: |
| 4:2:0 彩色渐变，13,889 B | 21.20 ms | 6.36 ms | 42.64 → 117.04 帧/秒 |
| 4:2:0 高熵亮度，260,714 B | 21.21 ms | 14.41 ms | 40.19 → 55.24 帧/秒 |

每轮发 128 帧，每批 8 帧，关闭 FNV 计算。相同输入的 DDR 回读在初版、两种写窗口和 RTL 仿真之间逐字节一致。新版通过四种采样格式、非对齐区域和六种异常帧的板测，包含已开始写回后遇到提前 EOI 的恢复检查。渐变图解码超过 LCD 刷新时，VDMA 以约 60 Hz 取最新的可用帧。

原始板测、仿真、资源和时序记录随 [验证归档](validation/jpeg-rtl-hp1-20261108/) 一起保存。运行 `python tools/jpeg_dma_benchmark.py --window 1 --window 8 --out build/jpeg-hp1-retest` 可直接使用归档中的两张 JPEG 和预期 BGR 哈希复测。也可用 `--fixtures build/jpeg-rtl-sim` 选择本次仿真生成的 JPEG 和参考 BGR。脚本结束后恢复写窗口和 Windows 扩展显示状态。

IDCT 的八个 Verilog 文件来自 [Ultra-Embedded core_jpeg](https://github.com/ultraembedded/core_jpeg/tree/bb03cce45d0b7459d395486e9e1db3de1b416bd2/src_v)，采用 [Apache 2.0](../fpga/jpeg/core/LICENSE)。JPEG 码流格式参照 [ITU-T T.81](https://www.w3.org/Graphics/JPEG/itu-t81.pdf)。
