# PL JPEG 解码与离线验证

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

错误码 1–7 依次代表描述符、JPEG 码流、AXI 读、AXI 写、超时、中止及像素计数。CPU 配置寄存器后启动任务，忙位清除前保留源和目标缓冲。

验证使用 `python tools/jpeg_rtl_sim.py`，通过有反压的 AXI DDR 模型从 JPEG 字节一直检查到 BGR888 帧缓冲。测试包括 800×480 全幅图、奇数尺寸矩形、跨页写入、截断、错误重启标记和总线故障后的恢复。结果保存在 `build/jpeg-rtl-sim/results.json`。Vivado 实现报告在 `build/fpga-jpeg-rtl/`。本次验证范围为离线仿真和构建。

| 800×480 仿真图 | 100 MHz 下的任务时间 | 相对 Pillow 的最大 / 平均通道误差 |
| --- | ---: | ---: |
| 4:2:0 彩色渐变 | 6.78 ms | 5 / 1.1325 |
| 4:2:0 高熵亮度 | 14.41 ms | 2 / 0.5357 |

任务时间包含模拟 DDR 的读写反压，实际 USB、DDR 争用和显示吞吐需上板测量。

Vivado 2018.3 为 XC7Z020CLG400-2 完成综合、布局布线及 bit 生成。布线后物理优化使最差建立裕量达到 +0.014 ns，最差保持裕量为 +0.036 ns，DRC 为 0 错误、83 警告。SDK 2018.3 用同次 HDF 生成 BSP 并链接两套 ARM ELF。JPEG 版 ELF 未链接 libjpeg 或 NEON 解码函数，两套交付包的哈希均通过 `flash.py --dry-run` 校验。

IDCT 的八个 Verilog 文件来自 [Ultra-Embedded core_jpeg](https://github.com/ultraembedded/core_jpeg/tree/bb03cce45d0b7459d395486e9e1db3de1b416bd2/src_v)，采用 [Apache 2.0](../fpga/jpeg/core/LICENSE)。JPEG 码流格式参照 [ITU-T T.81](https://www.w3.org/Graphics/JPEG/itu-t81.pdf)。
