# Windows 蓝屏诊断 Skill (windows-bsod-diagnosis)

一个给 [Claude Code](https://claude.com/claude-code) 用的技能包：从「电脑老重启」这句话出发，用事件日志和真实 dmp 文件定位到具体驱动，顺带覆盖远程帮朋友/家人修电脑的完整流程。

不是猜「可能是内存」，而是把 BlueScreenView 的崩溃参数映射到驱动地址表，直接指出 `ACE-SSC-DRV64.sys +0x23dcba` 这种级别的结论。

## 安装

```powershell
git clone https://github.com/zhixin-jpg/windows-bsod-diagnosis-skill "$env:USERPROFILE\.claude\skills\windows-bsod-diagnosis"
```

（github.com 直连不通时，把仓库打包下载后解压到 `~/.claude/skills/windows-bsod-diagnosis` 即可。）

Claude Code 启动时会自动加载 `SKILL.md`。之后直接说「帮我看看这个蓝屏」「电脑老是重启」就会触发。

## 快速开始

```powershell
# 1. 管理员终端：收集证据（dmp、事件日志、驱动版本）
powershell -ExecutionPolicy Bypass -File scripts\collect_evidence.ps1

# 2. 管理员终端：让 BlueScreenView 吐出崩溃参数 + 完整驱动地址表
Start-Process -FilePath python -ArgumentList @(
  "$env:USERPROFILE\.claude\skills\windows-bsod-diagnosis\scripts\export_bsv_ui.py",
  "--dumps", "C:\path\a.dmp", "C:\path\b.dmp",
  "--exe", "C:\path\BlueScreenView.exe",
  "--out", "C:\path\bsv_ui.txt"
) -Verb RunAs -Wait

# 3. 映射 P3，得到元凶驱动
python scripts\analyze_dumps.py C:\path\bsv_ui.txt
```

输出示例：

```
Dump: 111126-16078-01.dmp
  崩溃: 2026/11/11 21:48:09  0x00000050  PAGE_FAULT_IN_NONPAGED_AREA
  P1 (被访问地址) = 0xffffc58b4f9d1928
  P2 (访问类型)   = 0 读 (read)
  P3 (指令地址)   = 0xfffff8076d23dcba
  P3 所属驱动: ACE-SSC-DRV64.sys +0x23dcba  [0xfffff8076d000000 - ...]
  已知驱动: 腾讯 ACE 反作弊 (Tencent Anti-Cheat Expert)
```

## 核心原理：为什么不能直接信 BlueScreenView

- 小型转储（`MDMP`）里 BlueScreenView 的 `Caused By Driver` 基本可用。
- 内核/完整转储（`PAGEDU64`）因 KASLR 映射问题，经常把所有崩溃都算到 `ntoskrnl.exe` 头上——**这是错的**。WhoCrashed 免费版也会因此报「没有第三方驱动」。
- 真正可靠的是 bugcheck 参数。以 `0x50 PAGE_FAULT_IN_NONPAGED_AREA` 为例：

| 参数 | 含义 |
|---|---|
| P1 | 被访问的非法内存地址 |
| P2 | 访问类型：0=读，1=写，2=执行 |
| P3 | **触发访问的指令地址 ← 定位驱动的关键** |
| P4 | 地址所在区域标志 |

把 P3 和崩溃时刻的驱动加载表（BlueScreenView 下半窗 All Drivers 的 From/To）对比，落在哪个 `[From, To)` 区间，崩溃就发生在哪个驱动里。多次崩溃偏移不同、但都落在同一个第三方驱动，基本可以锁定它。

## 目录

| 文件 | 作用 |
|---|---|
| `SKILL.md` | 诊断流程全文（触发条件、铁律、分类、参数表、元凶处置表） |
| `CASE-STUDY.md` | 一次真实的 0x50 排查复盘（已脱敏） |
| `scripts/collect_evidence.ps1` | 复制 minidump、导出系统错误日志、汇总第三方驱动版本、打 zip |
| `scripts/export_bsv_ui.py` | UI 自动化读取 BlueScreenView 的崩溃参数和驱动地址表 |
| `scripts/analyze_dumps.py` | 解析导出文本，把 P1/P3 映射到驱动区间并给出结论 |

## 覆盖的元凶

腾讯 ACE（无畏契约/三角洲/CF）、Riot Vanguard、火绒安全、NVIDIA/Intel 显卡、Realtek/Nahimic 音频、网卡/蓝牙，以及 `0x124 WHEA`、`Kernel-Power 41`、`0x1A/0x50 连发`、`0x116/0x117` 等代码的处置方向。

## 限制

- 只在 Windows 上跑；BlueScreenView 需要管理员提权（会弹 UAC，必须本机用户确认）。
- 依赖 `pywinauto`（`pip install pywinauto`），BlueScreenView 需自行下载（脚本会按常见路径查找）。
- 反作弊/安全软件冲突类问题，最终处置往往需要玩家本人操作游戏客户端，远程只做诊断。

## 案例

见 [CASE-STUDY.md](CASE-STUDY.md)：两次 `0x50` 内核转储，BlueScreenView 归因 `ntoskrnl.exe`，实际 P3 均落在 `ACE-SSC-DRV64.sys`。

## License

MIT
