# -*- coding: utf-8 -*-
"""BGL 机场反编译器 —— 图形界面 + 命令行。

图形界面：选 BGL（可多选）→ 反编译 → 输出同名 .xml，并显示解析摘要。
命令行  ：BGLAirportDecompiler.exe <文件.bgl> [输出.xml] [--ident=ZGBH] [--quiet]
"""
from __future__ import annotations

import os
import sys

APP_NAME = "BGL 机场反编译器"
APP_VER = "1.4.2"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from bgl2xml_core import (VERSION, BglError, decompile_bytes,  # type: ignore
                          report_text, summarize)
except ImportError:  # 打包后（PyInstaller）模块与主程序同目录
    from bgl2xml_core import VERSION, BglError, decompile_bytes, summarize  # type: ignore


def run_cli(argv):
    args = [a for a in argv if not a.startswith("--")]
    quiet = "--quiet" in argv
    profile = "2020" if ("--msfs2020" in argv or "--2020" in argv) else "2024"
    ident = ""
    for a in argv:
        if a.startswith("--ident="):
            ident = a.split("=", 1)[1].strip().upper()
    if not args:
        return None
    src = args[0]
    if not os.path.isfile(src):
        print("[错误] 找不到文件：%s" % src)
        return 2
    dst = args[1] if len(args) > 1 else os.path.splitext(src)[0] + ("_MSFS2020.xml" if profile == "2020" else ".xml")
    try:
        with open(src, "rb") as fh:
            data = fh.read()
        xml, rep = decompile_bytes(data, source_name=src, ident=ident, profile=profile)
    except BglError as exc:
        print("[错误] %s" % exc)
        return 3
    with open(dst, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(xml)
    if not quiet:
        print(summarize(rep))
        print("已写入: %s (%d 字节)" % (dst, os.path.getsize(dst)))
    return 0


def build_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("%s v%s" % (APP_NAME, VERSION))
    root.geometry("900x640")
    root.minsize(780, 560)

    # ---- 深色主题（与网页版同一套配色）----
    BG, CARD, CARD2, LINE, ACCENT, TXT, MUT = ("#091625", "#102238", "#0b1b2b", "#294762",
                                               "#72c4ff", "#eaf4ff", "#a9bfd2")
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=BG, foreground=TXT, fieldbackground=CARD2,
                    bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TXT)
    style.configure("Head.TLabel", background=BG, foreground=ACCENT, font=("Microsoft YaHei UI", 15, "bold"))
    style.configure("Sub.TLabel", background=BG, foreground=MUT, font=("Microsoft YaHei UI", 9))
    style.configure("TLabelframe", background=BG, bordercolor=LINE, relief="solid")
    style.configure("TLabelframe.Label", background=BG, foreground=ACCENT,
                    font=("Microsoft YaHei UI", 10, "bold"))
    style.configure("TButton", background="#193650", foreground=TXT, borderwidth=1,
                    bordercolor="#355774", relief="solid",
                    focusthickness=0, padding=(14, 8), font=("Microsoft YaHei UI", 9, "bold"))
    style.map("TButton", background=[("active", "#22456a"), ("disabled", CARD2)],
              foreground=[("disabled", "#5d7488")])
    style.configure("Go.TButton", background=ACCENT, foreground="#061522",
                    borderwidth=0, relief="flat",
                    font=("Microsoft YaHei UI", 10, "bold"), padding=(18, 9))
    style.map("Go.TButton", background=[("active", ACCENT), ("disabled", CARD2)])
    style.configure("TCheckbutton", background=BG, foreground=TXT, focuscolor=BG)
    style.map("TCheckbutton", background=[("active", BG)])
    style.configure("TProgressbar", background=ACCENT, troughcolor=CARD2,
                    bordercolor=LINE, lightcolor=ACCENT, darkcolor=ACCENT, thickness=8)

    head = ttk.Frame(root, padding=(14, 12, 14, 0))
    head.pack(fill="x")
    ttk.Label(head, text=APP_NAME, style="Head.TLabel").pack(anchor="w")
    ttk.Label(head, text="MSFS / FSX 机场 BGL → XML · 支持一键反编译为 MSFS2020", style="Sub.TLabel").pack(anchor="w")

    files = []          # 待处理 BGL 列表
    ident_var = tk.StringVar()
    suffix_var = tk.BooleanVar(value=False)
    ms2020_var = tk.BooleanVar(value=False)

    top = ttk.Frame(root, padding=10)
    top.pack(fill="x")

    ttk.Label(top, text="输入 BGL（可多选，或用“添加文件夹”批量加入）",
              font=("Microsoft YaHei UI", 10, "bold")).grid(row=0, column=0, columnspan=4, sticky="w")

    listbox = tk.Listbox(top, height=8, selectmode="extended", font=("Consolas", 9),
                         bg=CARD2, fg=TXT, selectbackground="#193650", selectforeground="#ffffff",
                         highlightthickness=1, highlightbackground=LINE, relief="flat", borderwidth=0)
    listbox.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(6, 4))
    top.columnconfigure(0, weight=1)

    def refresh():
        listbox.delete(0, "end")
        for f in files:
            listbox.insert("end", f)

    def add_files():
        for f in filedialog.askopenfilenames(title="选择 BGL 文件",
                                             filetypes=[("MSFS/FSX BGL", "*.bgl"), ("所有文件", "*.*")]):
            if f not in files:
                files.append(f)
        refresh()

    def add_folder():
        d = filedialog.askdirectory(title="选择包含 BGL 的文件夹")
        if not d:
            return
        for name in sorted(os.listdir(d)):
            if name.lower().endswith(".bgl"):
                p = os.path.join(d, name)
                if p not in files:
                    files.append(p)
        refresh()

    def remove_sel():
        for i in sorted(listbox.curselection(), reverse=True):
            del files[i]
        refresh()

    def clear_all():
        files.clear()
        refresh()

    ttk.Button(top, text="添加文件…", command=add_files).grid(row=2, column=0, sticky="w", pady=2)
    ttk.Button(top, text="添加文件夹…", command=add_folder).grid(row=2, column=1, sticky="w", padx=4)
    ttk.Button(top, text="移除所选", command=remove_sel).grid(row=2, column=2, sticky="w", padx=4)
    ttk.Button(top, text="清空", command=clear_all).grid(row=2, column=3, sticky="w")
    opts = ttk.LabelFrame(root, text="输出选项", padding=8)
    opts.pack(fill="x", padx=10)
    ttk.Label(opts, text="识别码覆盖（可留空，默认用文件名）:").grid(row=0, column=0, sticky="w")
    ttk.Entry(opts, textvariable=ident_var, width=12).grid(row=0, column=1, sticky="w", padx=6)
    ttk.Label(opts, text="例：ZGBH").grid(row=0, column=2, sticky="w")
    ttk.Checkbutton(opts, text="已存在同名 .xml 时自动加 _bglxml 后缀（不覆盖）",
                    variable=suffix_var).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
    ttk.Checkbutton(opts, text="反编译为 MSFS2020",
                    variable=ms2020_var).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

    mid = ttk.Frame(root, padding=(10, 6))
    mid.pack(fill="x")
    progress = ttk.Progressbar(mid, mode="determinate")
    progress.pack(fill="x")

    log_frame = ttk.LabelFrame(root, text="日志", padding=6)
    log_frame.pack(fill="both", expand=True, padx=10, pady=(4, 8))
    log = tk.Text(log_frame, wrap="none", font=("Consolas", 9), height=16,
                  bg="#07111c", fg=TXT, insertbackground=ACCENT, relief="flat",
                  highlightthickness=1, highlightbackground=LINE, borderwidth=0)
    log.pack(side="left", fill="both", expand=True)
    sb = ttk.Scrollbar(log_frame, command=log.yview)
    sb.pack(side="right", fill="y")
    log.configure(yscrollcommand=sb.set)

    def say(msg):
        log.insert("end", msg + "\n")
        log.see("end")
        root.update_idletasks()

    reports = []

    def export_report():
        if not reports:
            messagebox.showinfo(APP_NAME, "还没有反编译结果，先点「开始反编译」。")
            return
        default = os.path.splitext(reports[0][0])[0] + "_report.txt"
        dst = filedialog.asksaveasfilename(title="导出诊断报告", defaultextension=".txt",
                                           initialfile=os.path.basename(default),
                                           filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not dst:
            return
        try:
            with open(dst, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(r[2] for r in reports))
            say("诊断报告 → %s（含 %d 个文件）" % (dst, len(reports)))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_NAME, "报告写入失败：%s" % exc)

    def do_convert():
        if not files:
            messagebox.showinfo(APP_NAME, "请先添加需要反编译的 .bgl 文件。")
            return
        progress.configure(maximum=len(files), value=0)
        del reports[:]
        ok = fail = 0
        use2020 = bool(ms2020_var.get())
        for i, src in enumerate(list(files), 1):
            dst = os.path.splitext(src)[0] + ("_MSFS2020.xml" if use2020 else ".xml")
            if suffix_var.get() and os.path.exists(dst):
                dst = os.path.splitext(src)[0] + "_bglxml.xml"
            say("=" * 72)
            say("[%d/%d] %s%s" % (i, len(files), src, "   →  MSFS 2020 模式" if use2020 else ""))
            try:
                with open(src, "rb") as fh:
                    data = fh.read()
                xml, rep = decompile_bytes(data, source_name=src, ident=ident_var.get().strip().upper(),
                                           profile="2020" if use2020 else "2024")
                with open(dst, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(xml)
                for line in summarize(rep).splitlines():
                    say("   " + line)
                say("   -> %s (%d 字节)" % (dst, os.path.getsize(dst)))
                import hashlib
                import time as _t
                try:
                    info = {
                        "source": src,
                        "size": len(data),
                        "mtime": _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(os.path.getmtime(src))),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "profile": "2020" if use2020 else "2024",
                        "ident": ident_var.get().strip().upper(),
                        "output": dst,
                        "out_size": os.path.getsize(dst),
                        "runtime": "Python %d.%d GUI" % sys.version_info[:2],
                    }
                    reports.append((src, dst, report_text(rep, info)))
                except Exception:  # noqa: BLE001
                    pass
                ok += 1
            except BglError as exc:
                say("   [失败] %s" % exc)
                fail += 1
            except Exception as exc:  # noqa: BLE001
                say("   [失败] %s: %s" % (type(exc).__name__, exc))
                fail += 1
            progress.configure(value=i)
        say("=" * 72)
        say("完成：成功 %d，失败 %d。" % (ok, fail))
        if ok:
            messagebox.showinfo(APP_NAME, "反编译完成：成功 %d，失败 %d。" % (ok, fail))

    bottom = ttk.Frame(root, padding=(10, 0, 10, 10))
    bottom.pack(fill="x")
    ttk.Button(bottom, text="开始反编译", command=do_convert, width=18, style="Go.TButton").pack(side="right")
    ttk.Button(bottom, text="导出错误报告", command=export_report, width=16).pack(side="right", padx=6)
    ttk.Button(bottom, text="退出", command=root.destroy, width=10).pack(side="right", padx=6)

    say("%s v%s —— 把 MSFS/FSX 机场 BGL 反编译成 XML。" % (APP_NAME, VERSION))
    say("用法：添加 .bgl → 点“开始反编译”。XML 输出到 BGL 同目录、同名。")
    say("字段布局已用 ZSFZ.bgl ↔ ZSFZ.xml 真值配对验证；未解码的记录只统计在摘要里，不写入 XML 注释。")
    root.mainloop()
    return 0


def main():
    argv = sys.argv[1:]
    if argv:
        return run_cli(argv)
    try:
        return build_gui()
    except Exception as exc:  # noqa: BLE001
        print("GUI 启动失败：%s" % exc)
        print("可改用命令行：%s <文件.bgl> [输出.xml] [--ident=ZGBH] [--msfs2020] [--quiet]" % os.path.basename(sys.argv[0]))
        return 1


if __name__ == "__main__":
    sys.exit(main())
