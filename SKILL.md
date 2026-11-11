---
name: windows-bsod-diagnosis
description: Diagnose Windows blue screens (BSOD) and unexpected reboots from real crash dumps, including remote evidence collection. Use when the user mentions 蓝屏 / 蓝屏重启 / 电脑老重启 / BSOD / dmp / 0x50 / PAGE_FAULT_IN_NONPAGED_AREA / Kernel-Power 41 / WHEA, wants to remotely fix a friend's or family PC, or asks how to interpret WhoCrashed / BlueScreenView / WinDbg output. Covers minidump vs kernel dump, mapping bugcheck parameters to the guilty driver module, and fix playbooks for anti-cheat, security software, GPU drivers, and unstable RAM.
metadata:
  author: zhixin-jpg
  version: "1.0.0"
---

# Windows 蓝屏 / 自动重启诊断

目标：从「电脑老重启」这句话出发，用事件日志和真实的 dmp 文件定位到具体驱动或硬件，而不是猜。
先收集证据，再下结论；永远不要因为「像内存」就跳过 dmp 分析。

## 0. 铁律

- **证据优先**：没有 BugCheck 事件或 dmp 就当「硬重启」处理，先查 Kernel-Power 41。
- **不要卸载远程工具**：如果正用 ToDesk/向日葵 排障，卸载它就断了连接，先升级版本而不是卸载。
- **不要改系统目录权限**：`C:\Windows\Minidump` 没权限就用管理员终端复制出来，不要 takeown/icacls。
- **不要配「完整内存转储」**：16–32GB 机器会写几十 GB 文件，小/内核转储足够定位驱动。
- **远程打反作弊游戏有风险**：让本机用户自己启动游戏，你只看日志，别远程操作游戏进程。
- **公开分享前脱敏**：dmp、日志里可能有计算机名、用户名、远程控制码，案例要打码。

## 1. 先分类：真蓝屏 / 硬重启 / 显卡 TDR

在目标机（管理员终端）执行，或运行 `scripts/collect_evidence.ps1`：

```powershell
$cut = (Get-Date).AddDays(-14)
Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=$cut} -ErrorAction SilentlyContinue |
  Where-Object { $_.LevelDisplayName -in '错误','严重' } |
  Sort-Object TimeCreated |
  Format-List TimeCreated, Id, ProviderName, Message |
  Out-File "$env:USERPROFILE\Desktop\eventlog.txt" -Encoding utf8
```

| 事件 | 含义 |
|---|---|
| `BugCheck` (ID 1001) | 真蓝屏，有 dmp；消息里有 0x 代码和四个参数 |
| `Kernel-Power` (ID 41) + `EventLog` (ID 6008) | 没有蓝屏的硬重启 → 电源/过热/内存/硬件 |
| `Display` (ID 4101) | 显卡驱动 TDR，常表现为游戏闪退 |
| `WHEA-Logger` (17/18/19/47) | 硬件报错：CPU / PCIe / 内存 |
| `Windows Error Reporting` 的 LiveKernelEvent 141 | 显卡/驱动挂起，多为闪退而非蓝屏 |

问用户三个问题，能迅速分流：
1. 是**蓝屏一闪**还是**直接黑屏重启**？
2. 在**跑游戏/满载**时发生，还是**闲置**也发生？
3. 最近有没有**装新游戏、更新驱动、装安全软件**？

## 2. 收集 dmp

- 小型转储：`C:\Windows\Minidump\*.dmp`，通常 1–15 MB。
- 内核/完整转储：`C:\Windows\MEMORY.DMP`，可能几百 MB 到数 GB。
- 注意文件头：前 8 字节 `MDMP` = minidump；`PAGEDU64` = 内核转储。**内核转储会让 BlueScreenView 的「Caused By Driver」算错**，必须用第 5 节的参数映射法。

没权限时，让对面在管理员终端复制，不要改 ACL：

```powershell
$dst = "$env:USERPROFILE\Desktop\BSOD_Evidence\dumps"
New-Item -ItemType Directory -Path $dst -Force | Out-Null
Copy-Item "C:\Windows\Minidump\*.dmp" $dst -Force
Compress-Archive -Path "$dst\*.dmp" -DestinationPath "$env:USERPROFILE\Desktop\BSOD_Evidence\dumps.zip" -Force
```

微信可能拦 `.dmp`，**先压成 zip 再传**。ToDesk 文件传输若报没权限，说明传输进程未提权，先点「请求管理员权限」。

若 Minidump 为空，开启转储：系统属性 → 高级 → 启动和故障恢复 → 写入调试信息选「小内存转储」，并取消「自动重新启动」。

## 3. 工具与国内网络

- WhoCrashed 免费版：`https://www.resplendence.com/download/whocrashedSetup.exe`（国内可达）。它的「No offending third party drivers」只代表免费版没有符号，不代表没有元凶。
- BlueScreenView：Nirsoft 官网常被墙，用 MajorGeeks 页面下载：`https://www.majorgeeks.com/files/details/bluescreenview.html`。免安装。
- WinDbg：`winget install Microsoft.WinDbg` 在国内可能 403（`windbg.download.prss.microsoft.com`）。拿不到就走 BlueScreenView + 参数映射，不必卡在 WinDbg。
- Python 侧：`pip install pywinauto`（必要时加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`）。

BlueScreenView 命令行快速导出崩溃摘要：

```powershell
BlueScreenView.exe /LoadFrom 3 /SingleDumpFile "C:\path\x.dmp" /stext "C:\path\x.txt"
```

## 4. 核心：0x50 等参数怎么看

以 `0x50 PAGE_FAULT_IN_NONPAGED_AREA` 为例：

| 参数 | 含义 |
|---|---|
| P1 | 被访问的非法内存地址 |
| P2 | 访问类型：0=读，1=写，2=执行 |
| P3 | **触发访问的指令地址** ← 定位驱动的关键 |
| P4 | 地址所在区域标志 |

**P3 落在哪个驱动的 `[From, To)` 地址区间里，崩溃就发生在这个驱动的代码中。** 即使两次蓝屏的偏移不同，只要都落在同一个第三方驱动里，就基本可以锁定它。

如果 P3 落在 `ntoskrnl.exe`，再看「栈内驱动」列表；栈内也只剩内核时，才考虑内存/硬件损坏。

## 5. 内核转储的驱动定位流程

`Caused By Driver: ntoskrnl.exe` 在 PAGEDU64 转储里经常是错的（KASLR 映射问题），不要据此收工。

1. 以管理员运行导出脚本（BlueScreenView 要求提权，会弹 UAC）：

```powershell
Start-Process -FilePath python -ArgumentList @(
  "C:\Users\<you>\.claude\skills\windows-bsod-diagnosis\scripts\export_bsv_ui.py",
  "--dumps", "C:\path\a.dmp", "C:\path\b.dmp",
  "--exe", "C:\path\BlueScreenView.exe",
  "--out", "C:\path\bsv_ui.txt"
) -Verb RunAs -Wait
```

2. 解析并映射 P3：

```bash
python scripts/analyze_dumps.py C:\path\bsv_ui.txt
```

输出会给出每个 dmp 的 bugcheck、P1/P2/P3、P3 所属驱动 + 偏移，以及对已知驱动的标注。

3. 手动复核：把 P3 与 BlueScreenView 下半窗「All Drivers」里的 From/To 对比。下半窗粉色高亮 = 参与崩溃栈的驱动；可切到 `Options → Lower Pane Mode → Only Drivers Found In Stack` 缩小范围。

4. 判断：
   - 两次崩溃 P3 都落在同一第三方驱动 → 该驱动是元凶，按第 6 节处理。
   - P3 落在内核且没有任何第三方栈 → 内存不稳定/硬件嫌疑上升，做内存测试。
   - 两次 P3 不同驱动 → 先怀疑内存/系统层，再逐个排除第三方驱动。

## 6. 已知元凶与处置

| 驱动 | 来源 | 处置 |
|---|---|---|
| `ACE-SSC-DRV64.sys`、`ACE-CORE*.sys`、`ACE-BOOT.sys`、`ace-game-0.sys` | 腾讯 ACE 反作弊（无畏契约国服、三角洲、CF 等） | 更新游戏客户端；控制面板卸载 AntiCheatExpert 后重新启动游戏重装 ACE；退出/卸载火绒后测试；更新显卡驱动和 BIOS；仍崩则带驱动名+偏移报腾讯客服 |
| `vgk.sys` | Riot Vanguard | 更新游戏；确认 TPM 2.0/Secure Boot/HVCI；重装 Vanguard；仍崩报 Riot |
| `sysdiag.sys`、`hrdevmon.sys`、`nfwfp.sys` | 火绒安全 | 最易与反作弊冲突：先退出，再临时卸载测试 |
| `nvlddmkm.sys` | NVIDIA 显卡驱动 | DDU 干净卸载后装最新 WHQL；配合 Display 4101 判断 |
| `igdkmdn64.sys`、`npu_kmd.sys` | Intel 核显 / NPU | 用联想等 OEM 官方最新驱动 |
| `RTKVHD64.sys`、`Nahimic*.sys` | Realtek / Nahimic 音频 | 更新或暂时禁用音频增强 |
| `e2fn.sys`、`mtkwecx.sys`、`mtkbtfilterx.sys` | 网卡 / 蓝牙 | 更新 OEM 驱动；少见但可致 0x50 |
| ToDesk | 远程控制 | 只有当它的内核驱动出现在崩溃时加载列表才怀疑；虚拟网卡问题多为网络层，不是 0x50 常见元凶 |

其它代码：
- `0x124 WHEA_UNCORRECTABLE_ERROR` → 硬件/供电/过热，优先查散热、电源、BIOS。
- `Kernel-Power 41`（无蓝屏）→ 台式机查电源功率/老化，笔记本查适配器/散热；内存 XMP/EXPO 先关掉。
- `0x1A MEMORY_MANAGEMENT`、`0x50` 连续同码 → 内存条不稳，MemTest86 过夜。
- `0x116/0x117 VIDEO_TDR_*` → 显卡驱动/显卡本体。

## 7. 硬件与系统检查

- 温度：HWiNFO64 开「记录到文件」，打游戏复现后看重启前最后几行，CPU/GPU 冲 100°C 即散热问题。
- 内存：`mdsched.exe` 快速测；MemTest86 过夜；有条件先关 XMP/EXPO 跑几天。
- 磁盘：`chkdsk C: /f`（需重启）、SMART 状态。
- 系统文件：`sfc /scannow`、`DISM /Online /Cleanup-Image /RestoreHealth`。
- 重置超频/降压工具（ThrottleStop、厂商超频模式、显卡超频）。

## 8. 远程支持要点

- ToDesk：对方装好后给「设备代码 + 临时密码」，你输入即可；连上先点「请求管理员权限」，对方点「是」。
- 开启「重启后自动连接」，避免硬重启后重新要密码。
- 全程挂语音；硬重启会断线，教对方重新打开 ToDesk。
- 远程只做诊断、部署工具、看日志；游戏由本机用户自己启动。
- UAC 必须由本机用户确认，不要尝试绕过。

## 9. 输出报告模板

```
症状：蓝屏 X 次 / 硬重启 X 次，时间点……
证据：BugCheck 1001 代码 0x50，P3=0x... → 驱动名+偏移
结论：XX 驱动 bug（或内存/硬件）
处理：1) ... 2) ... 3) ...
验证：打同一款游戏观察 N 天；再崩就把新 dmp 发回分析
```

## 10. 随附脚本

- `scripts/collect_evidence.ps1`：管理员运行，复制 dmp、导出系统错误日志、汇总驱动版本、打 zip。
- `scripts/export_bsv_ui.py`：管理员运行，调用 BlueScreenView GUI，读取崩溃参数和完整驱动地址表，输出结构化文本。
- `scripts/analyze_dumps.py`：解析上述文本，把 P1/P3 映射到驱动区间，输出元凶和已知驱动说明。
