# JPEG RTL 实板验证记录

2026-11-08，构建 `0x0f724371`。与仓库中的 [JPEG BIT/ELF 清单](../../../prebuilt/jpeg-rtl/manifest.json) 配对。

| 文件 | 内容 |
| --- | --- |
| [board-flash.json](board-flash.json) | JTAG 下载与固件身份校验，含产物 SHA-256 |
| [board-before.json](board-before.json) | 原版 128 帧 × 两张图的基线 |
| [board-ab.json](board-ab.json) | 新版同 bitstream 的 1／8 笔窗口对照，含 HP1 寄存器计数和 DDR 哈希 |
| [board-acceptance.json](board-acceptance.json) / [board-display.json](board-display.json) | JPEG 验收、异常恢复、扩展屏和 VDMA 扫描 |
| [sim-window1.json](sim-window1.json) / [sim-window8.json](sim-window8.json) | 额外 B 响应延迟为 35 周期的 RTL 仿真 |
| [utilization.rpt](utilization.rpt) / [timing_summary.rpt](timing_summary.rpt) / [bus_skew.rpt](bus_skew.rpt) / [drc.rpt](drc.rpt) | Vivado 2018.3 最终布线报告 |
| [fixtures.json](fixtures.json) 与同目录 JPEG | A/B 原始输入和预期 1,152,000 字节 BGR888 的 SHA-256 |

结果摘要和复测命令见 [主页](../../../README.md) 及 [RTL 说明](../../jpeg-rtl.md)。
