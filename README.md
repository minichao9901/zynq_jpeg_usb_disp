# Zynq USB Display（RGB565 首版）

目标硬件：正点原子 Zynq-7020，PS USB3320，PL VDMA + RGB LCD，800×480。
本版实现 RGB565，兼容本机已安装的 `xfz1986_usb_graphic` Windows IDD 驱动。
JPEG 的类型字段保留；当前收到非 RGB565 帧会完整丢弃并计数，不进行 JPEG 解码。

## 当前交付与验证

- `prebuilt/usb_display.bit`：直接复用 `reference/19_vdma_lcd` 提供的 LCD bitstream，PL 未改动。
- `prebuilt/usb_display.elf`：本工程重新编译的 PS USB Display 固件。
- `prebuilt/system.hdf`、`prebuilt/ps7_init.tcl`：增加 PS USB 的硬件描述与初始化文件。
- `prebuilt/manifest.json`：源码、BSP 库、bit/ELF/HDF/初始化文件的 SHA-256。
- 板测结果见 [docs/validation.md](docs/validation.md)，机器可读证据在 `docs/validation/`。

屏幕目前未接；已验证 USB、Windows 驱动、RGB565 转换、VDMA 运行及物理 DDR 内容。
实际 LCD 的颜色、方向、同步稳定性和停止/重启 VDMA 时的观感，需接屏后验收。
当前采用 JTAG/RAM 下载，断电后需重载；本工程没有写 QSPI。

## 构建、下载

在本目录运行，工具链为 `E:/Xilinx/SDK/2018.3` 和 `E:/Xilinx/Vivado/2018.3`。
Python 依赖：`python -m pip install -r requirements.txt`。

```powershell
# 已有配套 BSP 时仅重新编译固件
python tools/build.py

# 从交付 HDF 重新生成并编译 BSP、固件
python tools/build.py --bsp

# 板子上电、JTAG 与 USB OTG 数据口接好后，下载 bit + ELF
./tools/load.ps1

# 查询枚举、速度、帧计数和 VDMA 状态
python tools/usb_host.py stats
```

`tools/load.tcl` 会处理断电后 hw_server 保留的 DAP 错误状态，执行 PS 初始化，
加载 PL，再启动 Cortex-A9 #0；本应用只向 #0 下载。
`load.ps1` 在下载前暂停 IDD，完成后通过扩展模式恢复，保留原主屏。

若需要从 LCD 参考工程重新导出 PS 配置：

```powershell
python tools/run_vivado.py -mode batch -source fpga/build.tcl -log build/hardware.log
python tools/build.py --bsp
```

默认复用已提供的 LCD bit，只生成 PS 硬件描述。`-tclargs --rebuild-pl` 可要求重新综合整个 PL；
本机 Vivado 2018.3 对原动态时钟 IP 综合发生 `EXCEPTION_ACCESS_VIOLATION`，因此全量 PL 重编译未通过。
该限制不影响已交付参考 bit 与本次 PS ELF 的板测。

## Windows 驱动配置

设备为 `303A:2986`，序列号 `ZYNQ-UDISP-RGB-001`。

| 接口 | 功能 | 端点/驱动 |
| --- | --- | --- |
| MI_00 | USB Display | OUT 0x01 / IN 0x81，`xfz1986_usb_graphic` |
| MI_01 | 诊断及测试送帧 | OUT 0x02 / IN 0x82，MS OS 2.0 自动绑定 WinUSB |

产品串为 `zynq_R800x480_Ergb16_Fps30_Bl128`。
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
```

测试覆盖整帧、分片头/短包、跨传输帧、区域更新、越界区域拒绝、非 RGB 类型拒绝、中途残留数据后重新同步、
截断帧超时恢复、连续 300 帧 30fps，以及 MEM-AP0 物理读回整张 BGR888 scanout 帧缓冲逐字节比较。
负向测试会故意使 `bad`、`unsupported`、`rx_timeouts` 各增加 1；暂停/恢复 IDD 也可能中止其在途帧并增加超时计数。
应比较正常持续流期间的增量，不能把测试后的累计计数当作正常流量故障。
Windows 桌面本身的内容变化决定 IDD 发送帧率；合成流测试的 30fps 不能代替所有桌面场景的测量。

## 数据链路与协议

`USB HS bulk OUT → 32×16KiB DMA 环 → 主循环流解析 → RGB565 LE 转 BGR888 → DDR → VDMA → RGB LCD`。
中断仅处理控制请求；大块收帧、像素转换与显示更新都在主循环，接收环满时由 USB NAK 施加反压。

16 字节帧头与 ESP32 参考实现一致，所有整数为小端，不依赖 C 位域布局：

| 偏移 | 长度 | 内容 |
| --- | --- | --- |
| 0 | 2 | crc16，按参考实现接收但未校验 |
| 2 | 1 | type，0=RGB565，其他值当前不解码 |
| 3 | 1 | cmd，保留 |
| 4,6 | 各2 | x,y |
| 8,10 | 各2 | width,height |
| 12 | 4 | frame_id 在低10位，payload_total 在高22位 |

RGB565 负载必须为 `width*height*2`，区域必须落在 800×480 内。
接收支持任意 USB 传输分片及连续帧，不把短包当作图像结束标志。
接收中断超过 500ms 后重置未完成帧；无帧魔数，复位/残留数据后按类型、尺寸、长度关系逐字节寻找合理帧头。
已验证跳过 2049 字节残留数据后恢复下一帧；没有魔数或强制 CRC，仍不宣称任意损坏均能无歧义恢复。
诊断接口 vendor OUT 请求 `0x32`（wIndex=1）可清理流解析状态；USB 重配置也会清理状态。

VDMA 仍为参考 PL 的一个硬件帧槽。软件使用 0x02000000、0x02200000、0x02400000 三个 BGR888 缓冲；
先在后台缓冲完成转换并 flush cache，再停 MM2S、等待 halted、切换地址并重启。
区域更新先复制原画面以保留区域外内容。每次完成显示更新后计算 FNV-1a 指纹供诊断验证。

诊断 vendor IN `0x30`（bmRequestType=0xC1,wIndex=1）返回 32 个小端 uint32，字段顺序见
`firmware/usb_display.h` 和 `tools/usb_host.py`。`frame_fnv` 为 FNV-1a，非线协议 CRC。

## 移植要点

1. 保留 ESP32 的 VID/PID、接口 0、两个 bulk 端点及产品串格式，改为 800×480 RGB565。
2. 使用 Zynq DAPLink 的 XUsbPs 配置、缓存处理和端点 DATA0 重置方式。
3. USB3320 的 MIO28..39 使用 1.8V，MIO8 为低有效复位。固件在初始化 USB 前显式设置并释放 PHY。
4. LCD 显示控制、动态时钟与引脚沿用 `19_vdma_lcd`，固定 33MHz 像素时钟和 800×480 时序。
5. 参考工程中的上游版权说明保留在相应源文件；本版未移植 ESP32 的音频功能。
