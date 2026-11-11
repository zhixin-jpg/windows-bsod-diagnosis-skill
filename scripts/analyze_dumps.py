#!/usr/bin/env python3
"""Map bugcheck parameters (especially 0x50 P3) to the driver module that owns
the faulting instruction.

Input is the text exported by export_bsv_ui.py, which contains:
  - the BlueScreenView upper-pane crash row (bugcheck + 4 params)
  - lower-pane driver address ranges (mode 1 = all drivers)
  - stack-only drivers (mode 2)

Usage:
    python analyze_dumps.py C:\\path\\bsv_ui.txt
"""

import re
import sys
from collections import OrderedDict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SECTION_RE = re.compile(r"^=====\s+(.+?)\s+LowerPaneMode=(\d+)\s+=====")
BUGCHECK_RE = re.compile(r"^0x[0-9a-fA-F]{8}$")
HEX_RE = re.compile(r"^[0-9a-fA-F`]+$")

ACCESS = {0: "读 (read)", 1: "写 (write)", 2: "执行 (execute)"}

KERNEL_MODULES = {"ntoskrnl.exe", "ntkrnlmp.exe", "hal.dll", "ntkrla57.exe"}

KNOWN = {
    "ace-ssc-drv64.sys": (
        "腾讯 ACE 反作弊 (Tencent Anti-Cheat Expert)",
        "更新游戏客户端；卸载 AntiCheatExpert 后重启游戏重装 ACE；退出/卸载火绒再测；仍崩则带驱动名+偏移报腾讯客服"),
    "ace-core10405.sys": ("腾讯 ACE 反作弊", "同上：更新/重装 ACE，排查安全软件冲突"),
    "ace-core20405.sys": ("腾讯 ACE 反作弊", "同上：更新/重装 ACE，排查安全软件冲突"),
    "ace-core30405.sys": ("腾讯 ACE 反作弊", "同上：更新/重装 ACE，排查安全软件冲突"),
    "ace-boot.sys": ("腾讯 ACE 反作弊（启动期组件）", "更新/重装 ACE"),
    "ace-advt.sys": ("腾讯 ACE 反作弊", "更新/重装 ACE"),
    "ace-game-0.sys": ("腾讯 ACE 反作弊", "更新/重装 ACE"),
    "vgk.sys": ("Riot Vanguard 反作弊",
                "更新无畏契约；确认 TPM2.0/Secure Boot/HVCI；重装 Vanguard；仍崩报 Riot"),
    "sysdiag.sys": ("火绒安全 Huorong",
                    "先退出火绒测试，再临时卸载；尤其与反作弊同装时易冲突"),
    "hrdevmon.sys": ("火绒安全 Huorong", "退出/临时卸载火绒测试"),
    "nfwfp.sys": ("火绒/网络过滤驱动", "退出/临时卸载火绒测试"),
    "nvlddmkm.sys": ("NVIDIA 显卡驱动",
                     "DDU 干净卸载后安装最新 WHQL；结合 Display 4101 判断"),
    "igdkmdn64.sys": ("Intel 核显驱动", "安装 OEM（联想）官方最新核显驱动"),
    "npu_kmd.sys": ("Intel NPU 驱动", "安装 OEM 官方最新驱动"),
    "rtkvhd64.sys": ("Realtek 音频驱动", "更新或暂时禁用音频增强"),
    "nahimicbtlink.sys": ("Nahimic 音频", "更新或暂时禁用 Nahimic"),
    "nahimic_mirroring.sys": ("Nahimic 音频", "更新或暂时禁用 Nahimic"),
    "nahimicxvad.sys": ("Nahimic 音频", "更新或暂时禁用 Nahimic"),
}

WINDOWS_DRIVER_HINT = (
    "崩溃指令落在 Windows 内核/系统驱动上。若栈内也没有第三方驱动，"
    "优先排查内存不稳或硬件；再看加载列表里的反作弊、安全软件等内核钩子。"
)


def parse_hex(value):
    if value is None:
        return None
    text = value.strip().replace("`", "").replace(" ", "")
    if not text or not HEX_RE.fullmatch(text):
        return None
    try:
        return int(text, 16)
    except ValueError:
        return None


def parse_sections(path):
    dumps = OrderedDict()
    current = None
    with open(path, encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.rstrip("\n").strip()
            match = SECTION_RE.match(line)
            if match:
                current = {
                    "name": match.group(1),
                    "mode": int(match.group(2)),
                    "crash": None,
                    "modules": [],
                    "stack": [],
                }
                dumps.setdefault(current["name"], []).append(current)
                continue
            if current is None or " | " not in line:
                continue
            fields = [part.strip() for part in line.split(" | ")]

            # Crash row: Dump File | Crash Time | Bug Check String | Bug Check Code | P1..P4 | ...
            if len(fields) >= 9 and BUGCHECK_RE.match(fields[3]):
                params = [parse_hex(v) for v in fields[4:8]]
                if all(v is not None for v in params):
                    current["crash"] = {
                        "time": fields[1],
                        "string": fields[2],
                        "code": fields[3],
                        "params": params,
                        "caused": fields[8] if len(fields) > 8 else "",
                    }
                continue

            # Driver row: Filename | Address In Stack | From | To | Size | ...
            if len(fields) >= 4:
                start = parse_hex(fields[2])
                end = parse_hex(fields[3])
                if start is None or end is None or end <= start:
                    continue
                entry = (fields[0], start, end)
                if current["mode"] == 1:
                    current["modules"].append(entry)
                elif current["mode"] == 2:
                    current["stack"].append(entry)
    return dumps


def locate(address, modules):
    hits = [m for m in modules if m[1] <= address < m[2]]
    if not hits:
        return None
    return min(hits, key=lambda m: m[2] - m[1])


def hex_addr(value):
    return "0x%x" % value


def analyze(name, sections):
    crash = next((s["crash"] for s in sections if s["crash"]), None)
    module_section = max(sections, key=lambda s: len(s["modules"]))
    modules = module_section["modules"]
    stack_section = next((s for s in sections if s["mode"] == 2), None)
    stack = stack_section["stack"] if stack_section else []

    print("=" * 72)
    print("Dump: %s" % name)
    if not crash:
        print("  未找到崩溃信息")
        return None

    params = crash["params"]
    print("  崩溃: %s  %s %s" % (crash["time"], crash["code"], crash["string"]))
    print("  P1 (被访问地址) = %s" % hex_addr(params[0]))
    print("  P2 (访问类型)   = %s" % ACCESS.get(params[1], "未知(%s)" % params[1]))
    print("  P3 (指令地址)   = %s" % hex_addr(params[2]))
    print("  P4              = 0x%x" % params[3])
    if crash["caused"]:
        print("  BlueScreenView 归因: %s（内核转储下可能不准）" % crash["caused"])

    culprit = locate(params[2], modules)
    verdict = None
    if culprit:
        fname, start, end = culprit
        offset = params[2] - start
        print("  P3 所属驱动: %s + 0x%x  [%s - %s]"
              % (fname, offset, hex_addr(start), hex_addr(end)))
        key = fname.lower()
        if key in KNOWN:
            source, advice = KNOWN[key]
            print("  已知驱动: %s" % source)
            print("  处置建议: %s" % advice)
            verdict = fname
        elif key in KERNEL_MODULES:
            print("  " + WINDOWS_DRIVER_HINT)
        else:
            print("  厂商: 未识别，重点怀疑该驱动或它的调用方")
            verdict = fname
    else:
        print("  P3 未落在任何已知驱动区间内")

    if stack:
        print("  栈内驱动: %s" % ", ".join(m[0] for m in stack))
    else:
        print("  栈内驱动: (无第三方)")

    referenced = locate(params[0], modules)
    if referenced:
        print("  P1 所属驱动: %s + 0x%x"
              % (referenced[0], params[0] - referenced[1]))
    return verdict


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python analyze_dumps.py <bsv_ui.txt>")
    dumps = parse_sections(sys.argv[1])
    if not dumps:
        sys.exit("no sections parsed; check the export format")
    verdicts = []
    for name, sections in dumps.items():
        verdict = analyze(name, sections)
        if verdict:
            verdicts.append((name, verdict))
    if len(verdicts) >= 2:
        names = {v.lower() for _, v in verdicts}
        if len(names) == 1:
            print("\n" + "!" * 72)
            print("结论: %d 次崩溃的出错指令都落在同一个驱动 %s —— 基本可锁定它。"
                  % (len(verdicts), verdicts[0][1]))
            print("!" * 72)
        else:
            print("\n注意: 多次崩溃落在不同驱动，先排查内存/系统层。")


if __name__ == "__main__":
    main()
