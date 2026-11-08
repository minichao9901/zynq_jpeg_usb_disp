# Zynq USB Display（RGB565 + JPEG）

正点原子 Zynq-7020、PS USB3320、PL VDMA 与 800×480 RGB LCD。支持 RGB565 和单扫描 8 位 Baseline JPEG。JPEG 由 PL 解码，经 HP1 写入 DDR 后台帧缓冲，再由 HP0 上的 VDMA 在帧边界切换画面。支持灰度、4:4:4、水平 4:2:2、4:2:0、动态 Huffman 表和重启标记。渐进式 JPEG 会被拒绝。

| 默认 USB 编码 | FPGA bitstream | ARM ELF | 配套文件 |
| --- | --- | --- | --- |
| JPEG | [BIT](prebuilt/jpeg-rtl/usb_display.bit) | [ELF](prebuilt/jpeg-rtl/usb_display.elf) | [SHA-256 清单](prebuilt/jpeg-rtl/manifest.json) |
| RGB565 | [BIT](prebuilt/rgb-rtl/usb_display.bit) | [ELF](prebuilt/rgb-rtl/usb_display.elf) | [SHA-256 清单](prebuilt/rgb-rtl/manifest.json) |

两套使用相同的 PL，ELF 都支持两种帧类型。各目录包含匹配的 HDF 和 PS 初始化脚本。下载使用 JTAG/RAM，断电后需要重新下载。较早的 NEON 版本可通过 `--legacy` 选择，见[产物目录](prebuilt/README.md)。

## 板测与资源

JPEG 版构建 `0x0f724371` 已上板，USB 以 480 Mbps 枚举，Windows 以 800×480、60 Hz 扩展屏运行。HP1 写回从逐笔等待 B 响应改为最多 8 笔在途。单笔模式每帧花约 15.91 ms 等 B，占约 75%；多笔模式阻塞式等待降到 30 个周期。两组各发 128 帧，每批 8 帧，关闭 FNV。

| 相同的 800×480 JPEG | 旧版 → 新版 PL 任务耗时 | 旧版 → 新版端到端解码吞吐 |
| --- | ---: | ---: |
| 4:2:0 彩色渐变，13,889 B/帧 | 21.20 → **6.36 ms** | 42.64 → **117.04 帧/秒** |
| 4:2:0 高熵亮度，260,714 B/帧 | 21.21 → **14.41 ms** | 40.19 → **55.24 帧/秒** |

DDR 回读与旧版、RTL 仿真逐字节一致。四种采样格式、非对齐区域和六种异常帧恢复通过板测，15 项 RTL 仿真通过。吞吐统计到 USB 输入对应的帧解码完成，LCD 扫描约 60 Hz，超过刷新率时会取最新的完整帧。历史 RGB565 板测的三轮中位数为纯接收 41.84 MB/s、转换并显示 41.71 MB/s，见[历史记录](docs/lcd-continuous-scanout.md)。

| XC7Z020 布线后资源 | JPEG 解码器＋DMA | HP1 SmartConnect | 整机 / 器件容量 |
| --- | ---: | ---: | ---: |
| LUT | 6,818 | 3,030 | 13,375 / 53,200（25.1%） |
| FF | 5,518 | 3,876 | 15,602 / 106,400（14.7%） |
| BRAM（按 18 Kb 折算） | 9 | 0 | 19 / 280（6.8%） |
| DSP48 | 37 | 0 | 37 / 220（16.8%） |

100 MHz 布线后最差建立裕量 +0.005 ns，保持裕量 +0.034 ns，DRC 0 错误。原始证据随 Git 保存。[板上 A/B](docs/validation/jpeg-rtl-hp1-20261108/board-ab.json) · [验收](docs/validation/jpeg-rtl-hp1-20261108/board-acceptance.json) · [资源](docs/validation/jpeg-rtl-hp1-20261108/utilization.rpt) · [时序](docs/validation/jpeg-rtl-hp1-20261108/timing_summary.rpt) · [实现与复测](docs/jpeg-rtl.md)

## 克隆与准备

```powershell
git clone https://github.com/minichao9901/zynq_jpeg_usb_disp.git
cd zynq_jpeg_usb_disp
python -m pip install -r requirements.txt
```

- Windows 10/11 64 位，Python 3.10 或更新版本。Python 依赖已包含 Windows 用的 libusb，可通过 `ZYNQ_LIBUSB_DLL` 或 `usb_host.py --dll` 指定其他 DLL。
- 上板下载需要 Xilinx SDK 2018.3 和已安装的 JTAG cable driver。重新综合需要 Vivado 2018.3，RTL 仿真需要 PATH 上的 Icarus Verilog（`iverilog`、`vvp`）。
- 工具默认位于 `E:/Xilinx/SDK/2018.3` 与 `E:/Xilinx/Vivado/2018.3`。其他安装位置在当前 PowerShell 设置 `$env:XILINX_SDK` 和 `$env:XILINX_VIVADO`。运行时 DLL 缓存、Vivado 输出和本机日志在 Git 忽略的 `build/` 中。
- Windows 扩展显示需要安装 [xfz1986 USB IDD 驱动](https://github.com/chuanjinpang/win10_idd_xfz1986_usb_graphic_driver_display)，控制 IDD 与修改注册表需管理员 PowerShell。USB 诊断接口 MI_01 可独立使用。

仓库包含完整 RTL、固件、Vivado IP 元数据、验证样本与可直接下载的 bit/ELF。无需原 `reference/`、其他工程目录或 Git 子模块。Xilinx 工具和 Windows 驱动需要另行安装。

## CLI

```powershell
# 离线校验四套下载包
python tools/flash.py jpeg --dry-run
python tools/flash.py rgb --dry-run
python tools/flash.py jpeg --legacy --dry-run
python tools/flash.py rgb --legacy --dry-run

# JTAG/RAM 下载，选择默认 JPEG 或 RGB565
python tools/flash.py jpeg
python tools/flash.py rgb
# 仅下载，保持 MI_00 暂停，便于独立板测
python tools/flash.py jpeg --no-display
# 先重编所选固件，再下载配套 bit/ELF
python tools/flash.py jpeg --build

# USB 枚举/帧统计、固件 ID、VDMA 发布状态、PL 解码周期
python tools/usb_host.py stats
python tools/usb_host.py info
python tools/usb_host.py display
python tools/usb_host.py profile

# 恢复扩展屏，或在同一固件上切换 Windows 发送格式
python tools/enable_display.py
python tools/set_mode.py jpeg --quality 8
python tools/set_mode.py rgb565

# RTL 仿真，及带额外 B 响应延迟的仿真
python tools/jpeg_rtl_sim.py
python tools/jpeg_rtl_sim.py --quick --b-latency 35 --out build/jpeg-sim-latency

# 从已交付的 HDF/bit 重编固件；--bsp 可强制重建 BSP
python tools/build.py --mode all
# 完整重建 PL，随后使用新的 bit/HDF 编译固件
python tools/run_vivado.py -mode batch -source fpga/build_jpeg_rtl.tcl -log build/jpeg-rtl-vivado.log
python tools/build.py --bsp

# 自动暂停 IDD、测试并恢复扩展屏
./tools/test.ps1 -Frames 300
./tools/jpeg_test.ps1
./tools/benchmark.ps1 -Repeat 3 -Frames 128
python tools/jpeg_dma_benchmark.py --window 1 --window 8 --out build/jpeg-hp1-retest

# MI_00 暂停时发送 RGB 色条，或开启 FNV 后验证一帧
python tools/usb_host.py colorbars
python tools/usb_host.py test

# 本地 CLI/包校验回归
python -m unittest discover -s tools/tests
```

`flash.py` 校验包哈希后初始化 PS、下载 bit 和 ELF，并检查运行构建 ID 和 VDMA。正常模式会恢复物理主屏与扩展屏。若 Windows 已把 USB 屏设为主屏，先在显示设置选回物理主屏，再运行 `enable_display.py`。板测脚本的负向用例会故意增加错误计数，正常吞吐应比较测试前后的增量。

## Windows USB 接口

设备 `303A:2986`，序列号 `ZYNQ-UDISP-RGB-001`。

| 接口 | 功能 | 端点/驱动 |
| --- | --- | --- |
| MI_00 | USB Display | OUT 0x01 / IN 0x81，`xfz1986_usb_graphic` |
| MI_01 | 诊断及测试送帧 | OUT 0x02 / IN 0x82，MS OS 2.0 自动绑定 WinUSB |

JPEG 产品串为 `zynq_R800x480_Ejpg8_Ergb16_Fps999_Bl4096`，RGB 产品串交换两个 E 项的顺序。`Fps999` 让驱动绕过低帧率丢帧逻辑，`Bl4096` 为缓冲上限 4096 KiB。Windows 驱动注册表值 `udisp` 优先于 USB 产品串，下载和模式切换脚本会写入对应值，并在 `build/` 保存修改前的设置。

## 数据链路与协议

`USB HS bulk OUT → 32×16KiB DMA 环 → 主循环流解析 → RGB565 LE 转 BGR888 → DDR → VDMA → RGB LCD`。
JPEG 路径为 `USB → DDR 压缩缓冲 → HP1 → PL JPEG 解码 → HP1 → DDR 后台 BGR888 → HP0 VDMA`。
中断仅处理控制请求；大块收帧、像素转换与显示更新都在主循环，接收环满时由 USB NAK 施加反压。

16 字节帧头与 ESP32 参考实现一致，所有整数为小端，不依赖 C 位域布局：

| 偏移 | 长度 | 内容 |
| --- | --- | --- |
| 0 | 2 | crc16，按参考实现接收但未校验 |
| 2 | 1 | type，0=RGB565，3=JPEG；其他编码排空并计数 |
| 3 | 1 | cmd，保留 |
| 4,6 | 各2 | x,y |
| 8,10 | 各2 | width,height |
| 12 | 4 | frame_id 在低10位，payload_total 在高22位 |

RGB565 负载必须为 `width*height*2`，区域必须落在 800×480 内。
JPEG 内部尺寸必须与帧头相同。RTL 接受 8 位、1 或 3 分量的单扫描 Baseline JPEG。
渐进式、算术编码、CMYK、非 8 位和损坏或截断的码流会被拒绝，保留上一幅已提交画面。
接收支持任意 USB 传输分片及连续帧，不把短包当作图像结束标志。
接收中断超过 500ms 后重置未完成帧；无帧魔数，复位/残留数据后按类型、尺寸、长度关系逐字节寻找合理帧头。
已验证跳过 2049 字节残留数据后恢复下一帧；没有魔数或强制 CRC，仍不宣称任意损坏均能无歧义恢复。
诊断接口 vendor OUT 请求 `0x32`（wIndex=1）可清理流解析状态；USB 重配置也会清理状态。

VDMA 仍为参考 PL 的一个硬件帧槽，启动后持续运行，不再为每次换图停启 MM2S。
软件使用从 0x02000000 起、间隔 0x00200000 的五个 BGR888 缓冲：保护已编程帧及延迟回收的旧读缓冲，
另设待发布帧和绘制帧。后台完成转换并 flush 后，按 PG020 动态更新 START_ADDRESS、最后写 VSIZE，在帧边界生效。
生产者快于显示时，替换尚未发布的旧完整帧；不会为追求接收计数而中断 LCD 扫描。
区域更新先复制原画面以保留区域外内容。生产路径默认关闭整帧 FNV-1a；板测显式启用后进行指纹验证。
原每帧 FNV 约耗时 9.9ms，是无节流 RGB 链路约 29.4MB/s 的主要附加开销。

诊断 vendor IN `0x30`（bmRequestType=0xC1,wIndex=1）返回 32 个小端 uint32，字段顺序见
`firmware/usb_display.h` 和 `tools/usb_host.py`。`frame_fnv` 为 FNV-1a，非线协议 CRC。
该字段只在 FNV 验证模式下更新，正常模式下可能保留旧值。
FNV 对应最新完成解码的画面；物理 DDR 校验会通过 `wait_display()` 等待最终画面发布并跨过保护帧边界。

诊断 IN `0x31` 返回耗时统计，OUT `0x33` 的 wValue 选择模式：0=显示+FNV，1=纯接收，2=正常显示不算 FNV（默认）。
索引见 `firmware/profile.h`，累计耗时单位为微秒。仅在暂停 IDD、无在途测试帧时切换诊断模式。
诊断 IN `0x35` 返回连续扫描状态：帧边界事件、已发布/最新地址、待发布/绘制地址、旧读缓冲保护掩码、
已解码/已发布/被替换计数、停止/错误观测和运行位。CLI 也检查视频帧边界正在前进，避免只验 USB 收包。

历史 NEON 板测中，JPEG 渐变图连续 300 帧不限速约 72.8 次解码/提交每秒，高熵噪声图约 26.2fps。
这些数字表示接收/解码处理能力，不是面板刷新率；LCD 按视频时序显示，较旧的待发布帧可能被较新完整帧替换。

## 移植要点

1. 保留 ESP32 的 VID/PID、接口 0、两个 bulk 端点及产品串格式，改为 800×480 RGB565。
2. 使用 Zynq DAPLink 的 XUsbPs 配置、缓存处理和端点 DATA0 重置方式。
3. USB3320 的 MIO28..39 使用 1.8V，MIO8 为低有效复位。固件在初始化 USB 前显式设置并释放 PHY。
4. LCD 显示控制和引脚沿用 `19_vdma_lcd`，Clocking Wizard 提供固定 33 MHz 像素时钟。
5. 参考工程中的上游版权说明保留在相应源文件；本版未移植 ESP32 的音频功能。

RTL 的 IDCT 来源与许可见 [RTL JPEG 解码](docs/jpeg-rtl.md)。旧 NEON 版本的依赖和许可见 [third_party/README.md](third_party/README.md)。
