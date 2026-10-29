# -*- coding: utf-8 -*-
"""命令行版：把 MSFS/FSX 机场 BGL 反编译成 XML。

用法：
    bgl2xml-cli.exe <文件.bgl> [输出.xml] [--ident=ZGBH] [--msfs2020] [--quiet]
                    [--report[=报告文件.txt]]

    --msfs2020  输出按 MSFS 2020 的 bglcomp.xsd 生成（EdgeLights 用 preset 且包在
                <ApronEdgeLights> 里、PaintedLine 不带 width、Windsock 不带颜色属性），
                默认输出名变为 <原文件名>_MSFS2020.xml

    --report    额外导出一份诊断报告（源文件指纹 + 机场摘要 + 子记录统计 +
                未解码记录明细），默认写到 <输出文件名>_report.txt，可用
                --report=路径 指定位置

不带参数时打印帮助；多个文件可重复调用或用通配符。
"""
from __future__ import annotations

import glob
import os
import sys
import time


def _setup_console():
    """让 Windows 控制台能正确显示中文（UTF-8）。"""
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv):
    _setup_console()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from bgl2xml_core import (VERSION, BglError, decompile_bytes,  # type: ignore
                              report_text, summarize)

    if not argv or argv[0] in ("-h", "--help", "/?"):
        print(__doc__)
        print("版本 v%s" % VERSION)
        return 0

    quiet = "--quiet" in argv
    want_report = any(a == "--report" or a.startswith("--report=") for a in argv)
    report_path = ""
    for a in argv:
        if a.startswith("--report="):
            report_path = a.split("=", 1)[1].strip()
    ms2020 = "--msfs2020" in argv or "--2020" in argv
    profile = "2020" if ms2020 else "2024"
    ident = ""
    for a in argv:
        if a.startswith("--ident="):
            ident = a.split("=", 1)[1].strip().upper()
    args = [a for a in argv if not a.startswith("-")]
    if not args:
        print("[错误] 未给出输入文件。")
        return 2

    # 支持通配符
    srcs = []
    for a in args[:-1] if len(args) > 1 and args[-1].lower().endswith(".xml") else args:
        hits = glob.glob(a)
        srcs.extend(hits if hits else [a])
    out_override = args[-1] if len(args) > 1 and args[-1].lower().endswith(".xml") else None
    if out_override and len(srcs) > 1:
        print("[错误] 多个输入文件时不能指定单一输出文件。")
        return 2

    rc, ok, fail = 0, 0, 0
    for src in srcs:
        if not os.path.isfile(src):
            print("[错误] 找不到文件：%s" % src)
            rc, fail = 2, fail + 1
            continue
        base = os.path.splitext(src)[0]
        dst = out_override or (base + ("_MSFS2020.xml" if ms2020 else ".xml"))
        try:
            with open(src, "rb") as fh:
                data = fh.read()
            xml, rep = decompile_bytes(data, source_name=src, ident=ident, profile=profile)
            with open(dst, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(xml)
            ok += 1
            if want_report:
                import hashlib
                rp = report_path or (os.path.splitext(dst)[0] + "_report.txt")
                try:
                    info = {
                        "source": src,
                        "size": len(data),
                        "mtime": time.strftime("%Y-%m-%d %H:%M:%S",
                                               time.localtime(os.path.getmtime(src))),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "profile": profile,
                        "ident": ident,
                        "output": dst,
                        "out_size": os.path.getsize(dst),
                        "runtime": "Python %d.%d" % sys.version_info[:2],
                    }
                    with open(rp, "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(report_text(rep, info))
                    if not quiet:
                        print("诊断报告 → %s" % rp)
                except Exception as exc:  # noqa: BLE001
                    print("[警告] 诊断报告写入失败：%s: %s" % (type(exc).__name__, exc))
            if not quiet:
                print("=" * 72)
                print(src)
                print(summarize(rep))
                print("-> %s (%d 字节)" % (dst, os.path.getsize(dst)))
        except BglError as exc:
            print("[失败] %s：%s" % (src, exc))
            rc, fail = 3, fail + 1
        except Exception as exc:  # noqa: BLE001
            print("[失败] %s：%s: %s" % (src, type(exc).__name__, exc))
            rc, fail = 1, fail + 1
    if not quiet and (ok or fail):
        print("=" * 72)
        print("完成：成功 %d，失败 %d。" % (ok, fail))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
