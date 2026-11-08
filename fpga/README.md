# 精简 PL 构建输入

当前版本使用 `build_jpeg_rtl.tcl` 生成含解码器的完整 PL 和 HDF，输出位于 `build/fpga-jpeg-rtl/`。
传入 `-tclargs --handoff-only` 可验证 BD 和 IP 生成，输出暂存 HDF `next_system.hdf`，供检查使用。
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
备份与提交映射见 [Git 历史清理记录](../docs/git-history-cleanup.md)。

`build.tcl`、`resume.tcl` 和 `export_reference.tcl` 是历史 LCD 工程入口，输出统一放在
`build/fpga/`。当前硬件构建、固件重编和下载命令见 [主页](../README.md)。
