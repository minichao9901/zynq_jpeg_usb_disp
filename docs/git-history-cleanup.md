# reference 历史清理

日期：2026-11-06，Asia/Shanghai。用户明确要求从旧提交中清除 `reference/`。

## 结果

- 所有分支和 tag 的历史已移除根目录 `reference/`。
- 额外处理内部树快照引用：保留其余条目，只移除 `reference` 条目，避免旧对象仍被引用。
- 清理 reflog 并回收不可达对象后，`git count-objects -vH` 显示对象占用由约 43.94MiB 变为约 2.44MiB。
- 本地忽略的 `reference/` 仍保留 1032 个文件，未删除。
- `prebuilt/` 中所有文件 SHA-256 与清理前一致，两套 RGB/JPEG bit+ELF 及其初始化文件保留。
- `fpga/` 的精简重建输入保留，构建与下载不依赖已移除的资料目录。
- 没有配置远端，本轮没有执行 push，也没有改动板卡。

## 提交映射

| 清理前 | 清理后 | 内容 |
| --- | --- | --- |
| ad341fa | 09186d4 | RGB565 基线 |
| ff91398 | a71c698 | JPEG Neon 与吞吐分析 |
| b00d4f1 | acdfdc4 | 两套不限速产物及 CLI |
| cb18082 | c411fcf | 停止跟踪 reference，保留精简 PL 输入 |

Tag 名称保留，目标提交更新：

| Tag | 当前目标提交 |
| --- | --- |
| rgb565-baseline-20261106 | 09186d4 |
| jpeg-neon-20261106 | a71c698 |
| usb-display-unrestricted-20261106 | acdfdc4 |

提交与 tag 的对象 ID 因历史重写而改变；固件文件、实际构建身份和板测证据的文件哈希未变。

## 仓库外备份

完整 bundle：

`E:/zynq_jpeg_usb_disp-git-backup-20261106-191740/before-reference-cleanup.bundle`

该 bundle 已执行 `git bundle verify`，包含清理前的完整可达历史、三个 tag 和内部快照引用。
同目录保存 `refs-before.txt` 和 Git 配置。备份不在当前仓库中，不会重新把旧对象带入当前历史。

如需查看旧资料，应在另一个目录从 bundle 建独立仓库；不要向已清理仓库导入旧 refs，
否则旧对象可能再次变为可达。当前仓库只保留必要的精简源码和已验证交付产物。
