# Zynq USB Display（RGB565 + JPEG）

目标硬件：正点原子 Zynq-7020，PS USB3320，PL VDMA + RGB LCD，800×480。
支持 RGB565 和 JPEG，兼容本机已安装的 `xfz1986_usb_graphic` Windows IDD 驱动。
JPEG 在 PL 内解码。64 位 AXI DMA 读取 DDR 中的压缩数据，把 BGR888 写入后台缓冲，再由 VDMA 在帧边界切换画面。

**本分支交付 JPEG 和 RGB565 两套不限帧率的 RTL 版本，验证范围为离线仿真、综合和实现。**

```powershell
python tools/flash.py rgb --dry-run
python tools/flash.py jpeg --dry-run
```

产物分别在 `prebuilt/rgb-rtl/`、`prebuilt/jpeg-rtl/`，两套 ELF 都支持两种 USB 帧类型，区别是默认编码。
硬件支持 8 位单扫描 Baseline JPEG 的灰度、4:4:4、4:2:2（水平）、4:2:0、动态 Huffman 表和重启标记。
渐进式 JPEG 会被拒绝。上板后去掉 `--dry-run` 即可下载，也可用 `--legacy` 选择此前板测过的 NEON 版本。
实现及验证详见 [RTL JPEG 解码](docs/jpeg-rtl.md)。

RGB565 基线提交 `09186d4`，tag 为 `rgb565-baseline-20261106`。
JPEG 首版及 USB 吞吐分析见 [历史板测](docs/jpeg-and-throughput.md)，旧产物见 [不限帧率版本](docs/unrestricted-profiles.md)。
历史连续扫描版无帧率限制的三轮中位数：纯接收 **41.84 MB/s**，RGB565 转换处理 **41.71 MB/s**。
此前 23 MB/s 来自 30fps 主动限速（800×480×2×30=23.04MB/s），不是 USB 上限。

## 构建、下载

在本目录运行，工具链为 `E:/Xilinx/SDK/2018.3` 和 `E:/Xilinx/Vivado/2018.3`。
Python 依赖用 `python -m pip install -r requirements.txt` 安装。离线仿真需要 Icarus Verilog 的 `iverilog` 和 `vvp`。

```powershell
# 先仿真，再从源码构建 PL 和配套固件
python tools/jpeg_rtl_sim.py
python tools/run_vivado.py -mode batch -source fpga/build_jpeg_rtl.tcl -log build/jpeg-rtl-vivado.log
python tools/build.py

# 板子上电、JTAG 与 USB OTG 数据口接好后，选择下载模式
python tools/flash.py rgb
python tools/flash.py jpeg

# 查询枚举、速度、帧计数和 VDMA 状态
python tools/usb_host.py stats

# 在同一固件上切换 Windows IDD 发送格式；脚本保留原主屏
python tools/set_mode.py jpeg
python tools/set_mode.py rgb565
```

`tools/load.tcl` 会处理断电后 hw_server 保留的 DAP 错误状态，执行 PS 初始化，
加载 PL，再启动 Cortex-A9 #0；本应用只向 #0 下载。
`load.ps1` 在下载前暂停 IDD，完成后通过扩展模式恢复，保留原主屏。

重编固件时可复用交付的 bit/HDF，或用 `--bsp` 强制重新生成 BSP。

`reference/` 已从 Git 跟踪及全部历史引用中移除，并加入忽略规则，本地资料保留。
PL 重建必需的 IP、BD Tcl 和约束已保留在 `fpga/`，构建/下载不再依赖该资料目录。
来源与目录说明见 [fpga/README.md](fpga/README.md)。
历史重写后的提交/tag 对照与备份位置见 [Git 历史清理记录](docs/git-history-cleanup.md)。

## Windows 驱动配置

设备为 `303A:2986`，序列号 `ZYNQ-UDISP-RGB-001`。

| 接口 | 功能 | 端点/驱动 |
| --- | --- | --- |
| MI_00 | USB Display | OUT 0x01 / IN 0x81，`xfz1986_usb_graphic` |
| MI_01 | 诊断及测试送帧 | OUT 0x02 / IN 0x82，MS OS 2.0 自动绑定 WinUSB |

JPEG 产品串为 `zynq_R800x480_Ejpg8_Ergb16_Fps999_Bl4096`，RGB 产品串交换两个 E 项的先后顺序。
Fps999 让参考驱动绕过低帧率丢帧逻辑，不要求软件达到 999fps；不再施加 30fps 限速。
`Bl4096` 表示缓冲上限 4096KiB，并非行数。帧头实际长度字段最大为 4MiB−1。
原 ESP32 工程说明中的全局注册表 `udisp` 会覆盖产品串，本次已备份旧值并设置为本产品串：

```powershell
reg query HKLM\SYSTEM\CurrentControlSet\Services\xfz1986_usb_graphic\Parameters /v udisp
```

原值为 `esp32s31_R240x296_Ergb16_Fps30_Bl128`，备份位于 `build/host-backup/idd-parameters.reg`。
以后切回 ESP32 扩展屏时，需恢复为对应产品串。没有安装 IDD 驱动的电脑仍需安装该参考驱动；
MI_01 的 WinUSB 诊断接口可独立使用。

若插入后电脑主屏变黑，本次已确认原因是 Windows 选择了“仅在 USB 屏显示”。
已改为扩展桌面并恢复原主屏；USB 屏位于主屏左侧，800×480。
后续可运行 `python tools/enable_display.py`，它会保留启用前的主屏，并将 USB 屏启用为扩展屏。
该脚本遇到设置失败会自动禁用 USB 显示接口，避免把原主屏留在关闭状态。

`tools/usb_host.py` 使用 PyUSB + libusb。可用 `--dll <libusb-1.0.dll>` 指定库；
本机自动发现路径包含 `E:/zynqlinkPRO/prebuilt/golden/host/openocd/libusb-1.0.dll`。

## 板测

```powershell
# 测试期间暂停本设备 MI_00，结束后恢复，避免 IDD 帧覆盖测试图案
./tools/test.ps1

# 手动送一张色条，IDD 活跃时可能被桌面画面覆盖
python tools/usb_host.py colorbars

# JPEG 图像、异常恢复、物理 DDR 对比及连续 300 帧
./tools/jpeg_test.ps1

# 不限帧率，分别测带 FNV 校验、正常显示和纯接收，默认三轮
./tools/benchmark.ps1
```

测试覆盖整帧、分片头/短包、跨传输帧、区域更新、越界区域拒绝、坏 JPEG 拒绝、中途残留数据后重新同步、
截断帧超时恢复、连续 300 帧不限速发送，以及 MEM-AP0 物理读回整张 BGR888 scanout 帧缓冲逐字节比较。
负向测试会故意增加 `bad`、`rx_timeouts` 等计数；暂停/恢复 IDD 也可能中止其在途帧并增加超时计数。
应比较正常持续流期间的增量，不能把测试后的累计计数当作正常流量故障。
Windows 桌面内容变化和显示刷新决定 IDD 提供帧的速率；需要总线极限时用 `tools/benchmark.ps1` 持续发送测试帧。

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
4. LCD 显示控制、动态时钟与引脚沿用 `19_vdma_lcd`，固定 33MHz 像素时钟和 800×480 时序。
5. 参考工程中的上游版权说明保留在相应源文件；本版未移植 ESP32 的音频功能。

RTL 的 IDCT 来源与许可见 [RTL JPEG 解码](docs/jpeg-rtl.md)。旧 NEON 版本的依赖和许可见 [third_party/README.md](third_party/README.md)。
