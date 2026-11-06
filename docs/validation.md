# RGB565 首版板测记录

本文记录 `rgb565-baseline-20261106` 的历史基线；当前 JPEG 固件及最新产物身份见 [jpeg-and-throughput.md](jpeg-and-throughput.md)。

日期：2026-11-06，Asia/Shanghai。目标：Zynq-7020 / 800×480 USB Display。
用户确认本轮未接 LCD，USB OTG 数据口已接本机。

## 结果

PS 固件编译通过；USB 高速枚举、Windows IDD 送帧、诊断送帧、像素转换、VDMA 地址配置、
整幅物理 DDR 内容比较均通过。实际 LCD 出图仍待接屏确认。JPEG 未实现，已验证安全拒绝非 RGB565 数据。

| 验证项 | 结果 | 证据 |
| --- | --- | --- |
| USB 枚举 | 303A:2986，480Mbps，MI_00/MI_01 状态 OK | `validation/pnp.json` |
| Windows IDD | xfz1986_usb_graphic 1.2.25.2，800×480 | `validation/windows-display.json` |
| 9 项协议/显示测试 | 全部通过 | `validation/report.json` |
| 持续合成流 | 300 帧 / 10.01127s = 29.9662fps，23.0145MB/s | `validation/report.json` 的 stream |
| 持续流错误增量 | bad=0、display_errors=0、rx_timeouts=0 | 流测试前后快照 |
| 物理帧缓冲 | 1,152,000 字节 BGR888，与预期逐字节相等 | report 的 physical_ddr |
| VDMA 物理寄存器 | 运行中，无错误，地址/尺寸/stride 与测试帧相符 | `validation/vdma-report.json` |
| 首轮恢复 IDD 后的真实桌面流 | 10s 内 12 帧，坏帧/显示错误/超时增量均为 0 | `validation/idd-live.json` |
| 修正黑屏后的最终布局 | 1920×1080 主屏 + 800×480 扩展屏；5s 静态桌面检查无新增坏帧、超时或显示错误 | `validation/idd-live-final.json` |

真实桌面流是本次桌面内容下的观测；桌面变化少时 IDD 不会持续发送 30fps。
300 帧测试使用 MI_01 的合成图案，不能将其当作所有 Windows 桌面场景的帧率。
测试程序暂停 MI_00 以避免 IDD 覆盖图案，结束后已恢复该接口。

9 项测试包含：整帧 RGB565 色条；分片帧头及短 USB 传输；非对齐矩形区域；同一传输拼接两帧；
拒绝越界区域；拒绝非 RGB 类型；截断帧头后超时及下一帧恢复；2049 字节残留数据后的帧头重新同步；持续定速传帧。
拒绝/超时测试故意增加错误统计。暂停/恢复 IDD 也可能中止其在途帧并触发超时；报告保留累计值及初始快照。

VDMA 物理读取使用 APU 的 MEM-AP0，绕过 Cortex-A9 数据缓存：

| 寄存器 | 读回值 |
| --- | --- |
| MM2S_DMACR | 0x00010001 |
| MM2S_DMASR | 0x00011000，halted=0，错误位 0xFF0 均为 0 |
| VSIZE | 480 |
| HSIZE / STRIDE | 2400 / 2400 字节 |
| START_ADDRESS | 0x02000000，与已验证 BGR888 缓冲地址相等 |

物理帧缓冲 SHA-256：
`4157cf00a454dc2618ceafc4d386af7996bf068de96afdad91eb8fb2bf70e508`。

下图直接从物理 DDR 的 BGR888 字节生成，不是屏幕拍照：

![MEM-AP0 读回的色条](validation/scanout.png)

## 实际配对与构建范围

- ELF：`prebuilt/usb_display.elf`
  - SHA-256：`8c0e4a570a560b141d15eede6010a42cc71ad2bf58cfe06c3f3c73c4a1a22590`
- BIT：`prebuilt/usb_display.bit`
  - SHA-256：`73f50f93bf252401125aa6ca734237304ebf4090c4d5e1b3398fe4e7f94397ae`
  - 与所附 LCD 参考例程 `vdma_lcd.runs/impl_1/system_wrapper.bit` 字节一致，未宣称重新综合通过。
- 初始化：`prebuilt/ps7_init.tcl`，硬件描述 `prebuilt/system.hdf`。
- 完整源码/BSP/产物哈希：`prebuilt/manifest.json`，本次验收快照 `validation/tested-manifest.json`。
- 编译器：SDK 2018.3 GCC 7.3.1，Cortex-A9，hard-float，O3；最终应用编译无 warning。

参考 PL 的 VDMA 为一个硬件帧槽。本次未改变 PL，PS 采用后台 DDR 缓冲转换，
等待 MM2S halted 后更新地址并重启。合成流与 VDMA 数据验证通过，实体屏上停止/重启造成的画面间隙尚未验证。
重新综合参考动态时钟 IP 时，Vivado 2018.3 在不同并发/层次设置下均出现异常退出；
尝试三硬件帧槽的构建未完成，已回到参考 PL 的一个硬件帧槽。
记录中的 bit 是明确复用的参考产物，ELF 是本次新构建产物。

## 已处理的问题及剩余项

| 编号 | 状态 | 说明及验证 |
| --- | --- | --- |
| UD-001 | 已修复并板验 | 新增 USB 时默认 ULPI IO 电气设置与 DAPLink 不同，导致不能枚举；MIO28..39 改为 1.8V 后，高速枚举及持续传输通过。 |
| UD-002 | 已修复并板验 | 导出的 PS init 未包含 PHY 释放，MIO8 默认输入；固件在控制器初始化前显式配置并复位 USB3320。 |
| UD-003 | 已修复并板验 | 未接屏时 LCD ID 浮空导致初始化退出；按用户要求固定 800×480，USB 与 VDMA 均正常启动。 |
| UD-004 | 构建限制 | 本机 Vivado 2018.3 动态时钟 IP 综合异常；交付复用 LCD bit，全量 PL 重编译未通过。失败日志保留于 build/vivado*.log 及各 run 目录。 |
| UD-005 | 待接屏验证 | 800×480 实体 LCD 的颜色、方向、同步、画面间隙。 |
| UD-006 | 后续阶段 | JPEG 解码未实现；产品串只声明 Ergb16，非 RGB 数据只排空并计数。 |

本轮全部加载为 JTAG/RAM，未写 QSPI。用户中途插拔电源后，已恢复 DAP 并重新下载。
最后状态：Cortex-A9 #0 运行本次 ELF；本应用只向 #0 下载。MI_00/MI_01 已启用，Windows 显示接口恢复正常，原主屏 1920×1080 保持主屏，USB 屏 800×480 位于左侧 (-800,0)。用户确认修正后未再黑屏。
Windows 全局 udisp 参数已改为本项目 800×480 产品串，旧值备份位置见 README。
没有本任务启动的 Vivado、持续测试或采集后台进程；既有共享 hw_server 保留。


## 主屏黑屏问题与修正

用户反馈插入 USB 后电脑主屏黑、鼠标仍正常，拔出恢复。10 秒自动回退测试直接读回：
启用前 AMD 主屏 1920×1080、primary=1；启用后仅 xfz1986 USB 屏 800×480、primary=1，AMD 路径不再 active。
这是 Windows 的“仅 USB 屏显示”布局。事件日志中虽有较早的 DWM 崩溃记录，本次复现没有新增同类事件，不能据此前日志将根因归于 DWM。

通过 SetDisplayConfig 的 EXTEND 模式恢复双屏，再保留 AMD 为主屏并选择 USB 原生 800×480 模式。
用户确认修正后的观察中主屏正常。随后再停用/启用一次，应用修正函数之前的 on_attach 快照也已保留双屏布局，说明本轮模式保存已生效。
证据：`validation/idd-topology-probe.json`、`validation/display-enabled.json`。
后续使用 `tools/enable_display.py` 保留原主屏；下载入口 `tools/load.ps1`、测试入口 `tools/test.ps1` 已接入该恢复方式。

同时修复独立的插拔恢复问题：两方向 DMA flush 改为显式掩码并等待完成，清除 dTD/QH 残留状态；
不合理帧头改为逐字节寻找下一个合理帧头。新增残留数据恢复测试通过，正常 300 帧流期间没有新增坏帧或超时。
JPEG 类型编号按已有 P4 核心例程确认为 3，当前只排空并记录 unsupported。

| 编号 | 状态 | 说明 |
| --- | --- | --- |
| UD-007 | 已修正并由用户确认 | Windows 切成仅 USB 屏显示导致主屏黑；改扩展布局，恢复原主屏，停用/启用后保持正确布局。 |
| UD-008 | 已修复，协议板测通过 | USB 重置后的残留 DMA 状态与流失步；修正端点重建和流扫描，2049 字节残留后恢复及持续流通过。反复实体插拔的长时间压力测试未做。 |
