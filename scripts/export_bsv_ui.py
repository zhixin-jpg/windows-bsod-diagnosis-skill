#!/usr/bin/env python3
"""Export BlueScreenView crash rows and driver address ranges via UI automation.

BlueScreenView requires administrator privileges (its manifest demands elevation),
so run this script elevated as well, e.g.:

    Start-Process -FilePath python -ArgumentList @(
      "export_bsv_ui.py", "--dumps", "C:\\path\\a.dmp",
      "--exe", "C:\\path\\BlueScreenView.exe", "--out", "C:\\path\\bsv_ui.txt"
    ) -Verb RunAs -Wait

The output is parsed by analyze_dumps.py.
"""

import argparse
import ctypes
import os
import subprocess
import sys
import time


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def find_exe(hint):
    if hint:
        return os.path.abspath(hint)
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "BlueScreenView.exe"),
        os.path.join(os.path.expanduser("~"), "Desktop", "BSOD_Tools",
                     "BlueScreenView", "BlueScreenView.exe"),
        os.path.join(os.path.expanduser("~"), "Desktop", "修电脑工具",
                     "BlueScreenView", "BlueScreenView.exe"),
        r"C:\Tools\BlueScreenView\BlueScreenView.exe",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    sys.exit("BlueScreenView.exe not found. Pass --exe <path>.")


def connect_window(exe, timeout=20):
    from pywinauto import Application

    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            app = Application(backend="win32").connect(path=exe)
            return app.top_window()
        except Exception as exc:  # window not ready yet
            last = exc
            time.sleep(1)
    raise RuntimeError("cannot connect to BlueScreenView window: %r" % (last,))


def dump_listviews(dlg):
    lines = []
    lists = dlg.descendants(class_name="SysListView32")
    if lists:
        try:
            lists[0].select(0)
        except Exception:
            pass
        time.sleep(0.5)
    for li, lv in enumerate(lists):
        try:
            cols = [c.get("text", "") for c in lv.columns()]
        except Exception as exc:
            cols = ["COLERR %r" % (exc,)]
        try:
            count = lv.item_count()
        except Exception:
            count = -1
        lines.append("  LV%d columns(%d)=%s count=%s"
                     % (li, len(cols), " | ".join(cols), count))
        if not count or count <= 0:
            continue
        ncols = len(cols) if cols and not cols[0].startswith("COLERR") else 8
        for i in range(min(count, 500)):
            row = []
            for sub in range(ncols):
                try:
                    row.append(lv.get_item(i, sub).text())
                except Exception as exc:
                    row.append("ERR%r" % (exc,))
            lines.append("    " + " | ".join(row))
    return lines


def run_one(exe, dmp, mode, wait):
    try:
        proc = subprocess.Popen(
            [exe, "/LoadFrom", "3", "/SingleDumpFile", dmp,
             "/LowerPaneMode", str(mode)])
    except OSError as exc:
        if getattr(exc, "winerror", None) == 740:
            sys.exit("BlueScreenView requires elevation. Re-run this script "
                     "as administrator (Start-Process -Verb RunAs).")
        raise
    try:
        time.sleep(wait)
        dlg = connect_window(exe)
        return dump_listviews(dlg)
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dumps", nargs="+", required=True)
    parser.add_argument("--exe", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--modes", default="1,2",
                        help="LowerPaneMode list; 1=all drivers, 2=stack only")
    parser.add_argument("--wait", type=float, default=5.0,
                        help="seconds to wait for BlueScreenView to load")
    args = parser.parse_args()

    try:
        import pywinauto  # noqa: F401
    except ImportError:
        sys.exit("Missing dependency: pip install pywinauto")

    if not is_admin():
        print("WARNING: not elevated; BlueScreenView will refuse to start.",
              file=sys.stderr)

    exe = find_exe(args.exe)
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    out_path = args.out
    if not out_path:
        out_path = os.path.join(os.path.dirname(os.path.abspath(args.dumps[0])),
                                "bsv_ui.txt")

    lines = []
    for dmp in args.dumps:
        dmp = os.path.abspath(dmp)
        for mode in modes:
            print("exporting %s mode=%s" % (dmp, mode), file=sys.stderr)
            lines.append("")
            lines.append("===== %s  LowerPaneMode=%s ====="
                         % (os.path.basename(dmp), mode))
            try:
                lines.extend(run_one(exe, dmp, int(mode), args.wait))
            except Exception as exc:
                lines.append("FATAL: %r" % (exc,))

    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    print("written: %s" % out_path)


if __name__ == "__main__":
    main()
