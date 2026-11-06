# 两套不限帧率产物与下载 CLI

2026-11-06，Asia/Shanghai。

## 交付目录

| 模式 | 产物目录 | 编译默认类型 | USB 产品串 |
| --- | --- | ---: | --- |
| RGB565 | `prebuilt/rgb/` | 0 | `zynq_R800x480_Ergb16_Ejpg8_Fps999_Bl4096` |
| JPEG | `prebuilt/jpeg/` | 3 | `zynq_R800x480_Ejpg8_Ergb16_Fps999_Bl4096` |

每套都含 `usb_display.bit`、`usb_display.elf`、`ps7_init.tcl`、`system.hdf`、`manifest.json`。
产物目录关闭 Git 换行转换，PS init 的字节和 SHA-256 在 Windows checkout 后保持一致。
两份 bit 完全相同，因为 PL 显示逻辑未随编码改变；ELF 不同，默认编码与构建 ID 编译在程序内。
两套仍都能接收 RGB/JPEG 线协议，区别是启动时向 Windows 声明的优先编码。
源码、两套 bit/ELF 和验证记录一起纳入 Git。原来的基线与 JPEG 首版 tags 保留。

## 不限帧率的含义

- 移除原来固件产品串和主机注册表中的 Fps30。
- 使用 Fps999：参考驱动 `SwapChainProcessor` 在 fps>=50 时绕过低帧率丢帧逻辑，不能用 Fps0（驱动内部还会除以 fps）。
- 正常路径默认 `PROFILE_NO_FNV`，不逐帧计算约 9.9ms 的验收指纹。
- 主机吞吐、RGB/JPEG 回归脚本默认 `--fps 0`，不调用按帧率等待；需要历史对照时才显式传 `--fps 30`。
- 这是去掉人为限速，实际吞吐仍由 USB/CPU/桌面更新/显示时序决定。JPEG 压缩后字节量不能直接当作 USB 极限。

## CLI

在管理员 PowerShell、项目根目录运行：

```powershell
python tools/flash.py rgb
python tools/flash.py jpeg

# 先编译对应模式再下载
python tools/flash.py rgb --build
python tools/flash.py jpeg --build

# 只核对配对与哈希，不碰板卡或注册表
python tools/flash.py rgb --dry-run

# 下载后只保留诊断口，供吞吐测量
python tools/flash.py jpeg --no-display

# 一次重建两套产物
python tools/build.py
```

脚本也可从其他目录用绝对路径调用。兼容入口 `tools/load.ps1 -Mode rgb` / `-Mode jpeg` 会转交该 CLI。
`tools/load.tcl` 接受显式的 `ELF BIT PS_INIT_TCL` 三参数，不再隐式混用另一套文件。

执行顺序：验证模式与不限速配置 → 核对四个文件的 SHA-256 → 备份驱动注册表参数 → 暂停本板 MI_00 →
配置对应产品串 → JTAG/RAM 加载配套 bit/ELF/init → 核对板端默认编码/Fps999/FNV标志/构建 ID →
恢复扩展桌面 → 确认 Windows 实际发送 type=0 或 type=3。

MI_00 操作按父设备序列号限定为本 Zynq，避免暂停另一个同 VID/PID 的 ESP32。
失败时保持 USB 显示接口停用并恢复旧注册表值；日志和备份写入 `build/flash/<时间>/`。
CLI 默认 JTAG/RAM 下载，不写 QSPI，断电后需要重载。

## 本轮验证

- 两套均通过实际 CLI 下载；板端构建 ID 分别匹配各自 manifest，默认编码分别为 0/3，帧率参数 999，FNV 默认关闭。
- Windows IDD 实际发送对应类型；电脑主屏保持 1920×1080，USB 屏保持 800×480 左侧扩展。
- RGB 九项回归及物理 DDR 校验通过；连续流测试不再按 30fps 等待。
- RGB 三轮、不限帧率、128 帧、8帧/次提交：正常处理 41.737 / 41.694 / 41.738 MB/s，中位 **41.737 MB/s**。
- 纯接收三轮中位 **41.927 MB/s**；带 FNV 验收模式约 29.43 MB/s，仅用于验证，不是生产默认。
- JPEG 五类整图、区域更新与异常恢复通过，物理 DDR 对比一致；300 帧渐变 JPEG 不限速处理约 **72.80 帧/s**。
- 六项 CLI 测试验证模式不匹配、受限配置、篡改 ELF、异常文件路径会被拒绝，dry-run 不会下载。
- `--build --dry-run` 重新编译 RGB 后，ELF 与已板验文件字节一致。

测试原始证据在 `docs/validation/unrestricted-20261106/`。
JPEG 约 72.80 是软件解码并提交 VDMA 的处理能力，不是面板刷新率；高熵图像仍可能约 26fps，
其 CPU 解码边界见 [上一轮分析](jpeg-and-throughput.md)。本轮 LCD 仍未接，实体出图质量未验收。

## 问题状态

| 编号 | 状态 | 处理与验证 |
| --- | --- | --- |
| UD-011 | 已实现并板验 | 分别交付不限速 RGB/JPEG 配对，CLI 校验文件、运行模式与构建身份，两个模式均实际下载和接收对应帧。 |
| UD-012 | 已移除人为限制 | Fps30 改为驱动不执行低帧率丢帧的 Fps999，默认测试也取消 30fps 等待；RGB 实测约 42MB/s。 |
| UD-005 / UD-010 | 原边界保留 | 实体 LCD 待接屏；高熵 JPEG 不保证 30fps。不将取消限速表述为任意图像均能跑满 USB。 |
