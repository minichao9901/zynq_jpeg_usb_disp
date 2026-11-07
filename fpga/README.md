# 精简 PL 构建输入

RTL JPEG 分支使用 `build_jpeg_rtl.tcl` 生成含解码器的完整 PL 和 HDF。
该脚本复用 LCD BD，并通过 `bd/jpeg_rtl.tcl` 接入 HP1 DMA 和固定像素时钟。
RTL 接口与仿真见 [RTL JPEG 解码](../docs/jpeg-rtl.md)。以下是原参考 PL 的构建说明。

原始 `reference/19_vdma_lcd` 已完成移植参考任务，整个 `reference/` 目录停止 Git 跟踪；
本地文件保留并忽略。这里只保留重建硬件所需的少量源文件，避免提交原工程的缓存、
综合/实现输出、仿真文件及 SDK 中间产物。

| 路径 | 来源与用途 |
| --- | --- |
| `bd/lcd_system.tcl` | 原 `system_bd.tcl`，重建 LCD BD |
| `constraints/lcd.xdc` | 原 LCD 引脚约束 |
| `ip_repo/axi_dynclk_v1_0/` | 动态时钟自定义 IP 的源码、元数据及驱动 |
| `ip_repo/rgb2lcd/` | RGB LCD 自定义 IP 的源码和接口定义 |

这些文件按原字节复制，版权说明保留。原始资料已从所有 Git 历史引用中清除；
如需核对来源，可使用本地忽略的 `reference/` 或历史清理前的完整备份。
备份与提交映射见 `docs/git-history-cleanup.md`。本次未改变 RTL 功能或现有 bit/ELF。

`build.tcl` 使用此处输入建工程、启用 PS USB 并导出 HDF；默认保留已版本管理的
`prebuilt/usb_display.bit`。需要全量 PL 重编译时使用 `-tclargs --rebuild-pl`，
原动态时钟 IP 在本机 Vivado 2018.3 中的综合限制仍保留，见根 README。

`export_reference.tcl` 的旧文件名为兼容已有调用而保留；它不再读取 `reference/`。
正常固件编译和下载依赖 `prebuilt/` 中的 HDF、初始化文件及两套 bit/ELF 配对。
