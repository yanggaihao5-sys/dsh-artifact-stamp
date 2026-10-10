#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 🕒 v1 · 2026-10-10 08:50 · dsh-agent ｜ 变更：首个公开版（脱敏自内部 v8）


r"""artifact_stamp.py — 「手工简化版 git」：给文本产物盖时间戳 + 版本号。

为什么有它
----------
用户要求（2026-09-18）：**所有技能/插件产出的 .md、文本、README，都要带「精确到分钟的时间戳」和「版本指示」**。
没有脚本守的约定一定会漂移，所以这条约定配一个工具 + 一个体检命令。

戳长什么样（可见一行，放在正文最前面；若文件有 YAML frontmatter 则放在 frontmatter 之后；
代码文件则放在 `#!` shebang 与 PEP-263 编码行之后）
------------------------------------------------------------------------
> 🕒 vN · YYYY-MM-DD HH:MM · dsh-agent ｜ 变更：<一句话> ｜ 上一版：vN-1 · YYYY-MM-DD HH:MM

🔴 上面这行是**占位示例，故意不带真日期** —— 带真日期的示例会被 `find_stamp()` 当成真戳
（2026-09-19 实测：本文件 docstring 里的示例让 `new` 报「already stamped」，于是本工具自己一直没有戳）。
**写文档示例一律用 `vN · YYYY-MM-DD HH:MM`。**

命令
----
    python artifact_stamp.py new   <file> --note "初稿"          # 新建时盖 v1
    python artifact_stamp.py bump  <file> --note "补数据"         # 改完后升版（v1→v2→…）
    python artifact_stamp.py show  <file>                        # 看当前戳
    python artifact_stamp.py check <路径...> [--days 30] [--quiet]
        # 体检：① 有戳吗 ② mtime 比戳晚 > 容差 = 「改过但没盖戳」（违规）
        #      ③ 戳太旧（> --days 天）提示 ④ 全库统计
        # 退出码 1 = 有违规

设计约束
--------
* **纯标准库**、无网络、可离线跑；写文件用 UTF-8（Windows 上别用 GBK）。
* **幂等**：同一文件重复 bump 只在 note 变化时升版；`new` 遇到已有戳不覆盖。
* **不破坏 frontmatter**：SKILL.md 这类带 `---` 头的文件，戳插在 frontmatter 之后。
* 戳行可被机器解析（正则固定），供未来的体检/统计用。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta

STAMP_RE = re.compile(
    r"^(?:>|#|//|%|'|<!--)\s*🕒\s*v(?P<ver>\d+)\s*·\s*(?P<when>\d{4}-\d{2}-\d{2} \d{2}:\d{2})"
    r"(?:\s*·\s*(?P<author>[^｜|\n]+?))?"
    r"(?:\s*[｜|]\s*变更：(?P<note>[^｜|\n]+?))?"
    r"(?:\s*[｜|]\s*上一版：v(?P<pver>\d+)\s*·\s*(?P<pwhen>\d{4}-\d{2}-\d{2} \d{2}:\d{2}))?\s*$"
)
DEFAULT_AUTHOR = "dsh-agent"
DEFAULT_NOTE = "内容更新"
TOLERANCE_S = 90          # mtime 比戳晚多少秒才算「改过没盖戳」
STAMP_ARTIFACT = "artifact_stamp.py"


def now_minute() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# 按文件类型选戳前缀 —— 代码文件里插 `> ` 会直接把源码写坏（曾把 .py 戳成 SyntaxError）。
HASH_EXT = {".py", ".ps1", ".sh", ".bash", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".r", ".jl", ".m"}
SLASH_EXT = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".c", ".h", ".cpp", ".hpp", ".java", ".go", ".rs"}
TEXT_EXT = {".md", ".markdown", ".txt", ".rst", ".org"}
# LaTeX / BibTeX 用 `% ` 注释（论文工程多为 .tex/.bib）
PERCENT_EXT = {".tex", ".bib", ".sty", ".cls"}
# VBScript 用 `'` 注释（2026-09-20 加：本机多个 `.vbs` 无窗口启动器要登记）
QUOTE_EXT = {".vbs", ".vba", ".bas"}
# PowerShell 脚本：写进非 ASCII 就必须带 BOM（PS 5.1 否则按 GBK 读）
PS_EXT = {".ps1", ".psm1", ".psd1"}


def stamp_prefix(path: str) -> str:
    """返回该文件类型可用的注释前缀；不支持的类型返回 ''（调用方应拒绝盖戳）。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in HASH_EXT:
        return "# "
    if ext in SLASH_EXT:
        return "// "
    if ext in PERCENT_EXT:
        return "% "
    if ext in QUOTE_EXT:
        return "' "
    if ext in TEXT_EXT or ext == "":
        return "> "
    return ""


def make_stamp_line(path: str, ver: int, when: str, author: str, note: str,
                    prev_ver=None, prev_when=None) -> str:
    prefix = stamp_prefix(path)
    if prefix == "":
        raise SystemExit(f"拒绝盖戳：不认识的文件类型 {os.path.splitext(path)[1]!r}（{path}）—— 加盖会破坏文件；"
                         f"请把出处写进文件头注释，或扩展 stamp_prefix() 的映射表。")
    s = f"{prefix}🕒 v{ver} · {when} · {author} ｜ 变更：{note}"
    if prev_ver:
        s += f" ｜ 上一版：v{prev_ver} · {prev_when}"
    return s


def read_text(path: str) -> str:
    # utf-8-sig: tolerate a BOM (PowerShell 5.1's `Set-Content -Encoding UTF8` adds one) —
    # a BOM before `---` used to hide the frontmatter from the detector.
    with open(path, encoding="utf-8-sig") as fh:
        return fh.read()


def had_bom(path: str) -> bool:
    """文件原来带 UTF-8 BOM 吗？

    🔴 必须**保留**：Windows PowerShell 5.1 会把「无 BOM 的 .ps1」按 ANSI(GBK) 读，
    含中文的脚本一旦被去掉 BOM，界面文字就会变乱码。
    Markdown 则相反 —— Obsidian 更喜欢无 BOM，所以只在**原来有**时才写回去。
    """
    try:
        with open(path, "rb") as fh:
            return fh.read(3) == b"\xef\xbb\xbf"
    except OSError:
        return False


def write_text(path: str, text: str, bom: bool = False) -> None:
    # 默认写成干净的 UTF-8（无 BOM）—— markdown 工具/Obsidian 更喜欢；bom=True 时保留 BOM。
    # 🔴 自动兜底（2026-09-20）：给 **PowerShell 脚本**写进非 ASCII（例如戳里那句中文变更说明）时必须自带 BOM，
    #    否则 PS 5.1 按 GBK 读 → 乱码/语法错。这一步曾把一个"刻意全 ASCII 的 .ps1"在盖戳之后变成违规文件
    #    （被自己的 check BOM 守卫当场抓到）。
    if not bom:
        if os.path.splitext(path)[1].lower() in PS_EXT and any(ord(c) > 127 for c in text):
            bom = True
    data = text.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    with open(path, "wb") as fh:
        fh.write(data)


def split_frontmatter(lines: list[str]) -> int:
    """返回正文起始下标：有 YAML frontmatter 就跳过它。"""
    if lines and lines[0].strip() == "---":
        for i in range(1, min(len(lines), 80)):
            if lines[i].strip() == "---":
                return i + 1
    return 0


def code_header_end(lines: list[str]) -> int:
    """代码文件的「头注释区」结束下标。

    🔴 **shebang 与 PEP-263 编码行必须留在文件最前**（2026-09-19 事故）：
    `new` 曾把戳插到 `.py` 第 1 行，把 `#!/usr/bin/env python` 顶到第 3 行 ——
    在 Windows 上用 `python x.py` 跑没事，但 `./x.py` 直接执行就废了，且与既有约定不符。
    所以插入位置 = max(frontmatter 之后, shebang/编码行之后)。
    """
    i = 0
    while i < len(lines) and i < 3:
        s = lines[i].strip()
        if s.startswith("#!") or s.lower().startswith("#requires") or re.match(r"^#.*coding[:=]", s):
            i += 1
        else:
            break
    return i


def _fenced(lines: list[str]):
    """标记每一行是否位于 ``` 围栏代码块内（围栏行本身算「内」）。"""
    inside = []
    cur = False
    for l in lines:
        s = l.strip()
        is_fence = s.startswith("```")
        inside.append(cur or is_fence)
        if is_fence:
            cur = not cur
    return inside


def find_stamp(lines: list[str]):
    """-> (行号, 匹配对象) 或 (None, None)

    只认**正文里的**戳：围栏代码块里的示例戳不算（曾因此假绿：规则块里的示例被当成真戳，
    导致 new/bump 以为「已盖戳」而跳过，check 也误判为合规）。
    """
    start = max(split_frontmatter(lines), code_header_end(lines))
    fenced = _fenced(lines)
    for i in range(start, min(len(lines), start + 20)):
        if fenced[i]:
            continue
        m = STAMP_RE.match(lines[i].strip())
        if m:
            return i, m
    return None, None


def make_stamp(ver: int, when: str, author: str, note: str, prev_ver=None, prev_when=None,
               path: str = "") -> str:
    """兼容旧签名；给了 path 就按文件类型选前缀。"""
    if path:
        return make_stamp_line(path, ver, when, author, note, prev_ver, prev_when)
    s = f"> 🕒 v{ver} · {when} · {author} ｜ 变更：{note}"
    if prev_ver:
        s += f" ｜ 上一版：v{prev_ver} · {prev_when}"
    return s


def cmd_new(args) -> int:
    path = args.file
    lines = read_text(path).splitlines() if os.path.exists(path) else []
    i, m = find_stamp(lines)
    if m:
        print(f"already stamped: {path} -> v{m.group('ver')} @ {m.group('when')}")
        return 0
    stamp = make_stamp(1, now_minute(), args.author, args.note, path=args.file)
    idx = max(split_frontmatter(lines), code_header_end(lines))
    head = [""] if split_frontmatter(lines) > 0 else []   # 代码文件（shebang/编码行）后不留空行
    lines = lines[:idx] + head + [stamp, ""] + lines[idx:]
    write_text(path, "\n".join(lines) + "\n", bom=had_bom(path))
    print(f"stamped v1: {path}")
    return 0


def cmd_bump(args) -> int:
    path = args.file
    lines = read_text(path).splitlines()
    i, m = find_stamp(lines)
    when = now_minute()
    if not m:
        stamp = make_stamp(1, when, args.author, args.note, path=args.file)
        idx = max(split_frontmatter(lines), code_header_end(lines))
        head = [""] if split_frontmatter(lines) > 0 else []   # 代码文件（shebang/编码行）后不留空行
        lines = lines[:idx] + head + [stamp, ""] + lines[idx:]
        write_text(path, "\n".join(lines) + "\n", bom=had_bom(path))
        print(f"no previous stamp -> created v1: {path}")
        return 0
    old_note = (m.group("note") or "").strip()
    if old_note == args.note.strip() and not args.force:
        print(f"note unchanged ({old_note!r}) -> version kept at v{m.group('ver')} (use --force to bump anyway)")
        return 0
    ver = int(m.group("ver")) + 1
    stamp = make_stamp(ver, when, args.author or (m.group("author") or DEFAULT_AUTHOR).strip(),
                       args.note, m.group("ver"), m.group("when"), path=args.file)
    lines[i] = stamp
    write_text(path, "\n".join(lines) + "\n", bom=had_bom(path))
    print(f"bumped: {path} -> v{ver} @ {when}")
    return 0


def cmd_show(args) -> int:
    lines = read_text(args.file).splitlines()
    i, m = find_stamp(lines)
    if not m:
        print(f"NO STAMP: {args.file}")
        return 1
    print(f"{args.file}\n  version=v{m.group('ver')} updated={m.group('when')} "
          f"author={(m.group('author') or '').strip()} note={(m.group('note') or '').strip()}")
    return 0


def iter_text_files(paths, exts=(".md", ".txt", ".rst")):
    for p in paths:
        if os.path.isfile(p):
            yield p
            continue
        for dp, dirs, files in os.walk(p):
            # ⚠️ `backups` 必须跳过：它是**历史快照**（`~/.dsh/backups/<时间戳>-<操作>/`），
            #    快照里的文件**就该保持原样**，给它们盖戳等于篡改历史。
            #    不跳的后果实测过：`check <home>` 会永远报出上百条违规、退出码恒为 1
            #    —— 检查器天天喊狼来了，人就会开始无视它，比没有检查更糟。
            dirs[:] = [d for d in dirs if d not in
                       {".git", ".venv", "node_modules", "site-packages", "__pycache__",
                        "_归档", "backups"}]
            for f in files:
                if f.lower().endswith(exts) and f != STAMP_ARTIFACT:
                    yield os.path.join(dp, f)


def cmd_check(args) -> int:
    tol = args.tolerance
    stale_before = datetime.now() - timedelta(days=args.days)
    total = stamped = nostamp = drift = stale = 0
    problems = []
    encoding_notes = []
    bom_problems = 0
    exts = (".md", ".txt", ".rst", ".json") if getattr(args, "include_json", False) else (".md", ".txt", ".rst")
    if getattr(args, "include_code", False):
        exts = tuple(exts) + tuple(sorted(HASH_EXT | SLASH_EXT))
    for f in iter_text_files(args.paths, exts=exts):
        total += 1
        try:
            lines = read_text(f).splitlines()
        except UnicodeDecodeError:
            # 非 UTF-8（如 PowerShell 重定向出来的 UTF-16 .txt）→ 跳过、只提示，不判违规：
            # 盖戳会改编码，那不是本工具的职责。
            encoding_notes.append(f)
            continue
        except Exception as e:
            problems.append((f, f"读不了: {e}"))
            continue
        _, m = find_stamp(lines)
        # 🔴 BOM 守卫（2026-09-20 加）：Windows PowerShell 5.1 会把**无 BOM 的 .ps1** 按 ANSI(GBK) 读，
        #    含中文的脚本一去掉 BOM，界面文字就变乱码，严重时连语法都过不去。
        #    起因：编辑工具重写文件会剥掉 BOM，而本工具的写回只保证"不主动去 BOM"。
        if os.path.splitext(f)[1].lower() in (".ps1", ".psm1", ".psd1") and not had_bom(f):
            try:
                raw = open(f, "rb").read()
                if any(b > 0x7F for b in raw):
                    bom_problems += 1
                    problems.append((f, "缺 UTF-8 BOM（PowerShell 5.1 会把中文按 GBK 读 → 乱码/语法错）；"
                                        "修：python -c \"p=r'<file>';d=open(p,'rb').read();open(p,'wb').write(b'\\xef\\xbb\\xbf'+d)\""))
            except OSError:
                pass
        if not m:
            nostamp += 1
            problems.append((f, "缺时间戳/版本戳"))
            continue
        stamped += 1
        try:
            stamp_dt = datetime.strptime(m.group("when"), "%Y-%m-%d %H:%M")
        except Exception:
            problems.append((f, "戳时间无法解析"))
            continue
        mtime = datetime.fromtimestamp(os.path.getmtime(f))
        if (mtime - stamp_dt).total_seconds() > tol:
            drift += 1
            problems.append((f, f"改过没盖戳：文件 mtime={mtime:%Y-%m-%d %H:%M}，戳={stamp_dt:%Y-%m-%d %H:%M}（v{m.group('ver')}）"))
        if stamp_dt < stale_before:
            stale += 1
    if not args.quiet:
        for f, why in problems[:args.limit]:
            print(f"  ✗ {why}\n      {f}")
        if len(problems) > args.limit:
            print(f"  …还有 {len(problems) - args.limit} 条")
    if encoding_notes and not args.quiet:
        for f in encoding_notes[:5]:
            print(f"  ~ 跳过（非 UTF-8，不算违规）: {f}")
    print(f"\n统计：文本文件 {total} · 有戳 {stamped} · 缺戳 {nostamp} · 改过没盖戳 {drift} · 戳超过 {args.days} 天 {stale} · 非UTF8跳过 {len(encoding_notes)} · PS无BOM {bom_problems}")
    if problems:
        print("判定：有违规（退出码 1）。修复：`artifact_stamp.py new <file>` 或 `bump <file> --note \"...\"`")
        return 1
    print("判定：全部合规 ✅")
    return 0


def cmd_strip(args) -> int:
    """回滚：删掉由 new/bump 插入的戳行（一键撤销批量盖戳）。"""
    exts = (".md", ".txt", ".rst", ".json") if getattr(args, "include_json", False) else (".md", ".txt", ".rst")
    n = 0
    for f in iter_text_files(args.paths, exts=exts):
        try:
            lines = read_text(f).splitlines()
        except Exception:
            continue
        keep = [l for l in lines if not STAMP_RE.match(l.strip())]
        if len(keep) != len(lines):
            if args.dry_run:
                print("  would strip:", f)
            else:
                out = []
                for l in keep:
                    if l == "" and out and out[-1] == "":
                        continue
                    out.append(l)
                write_text(f, "\n".join(out) + "\n", bom=had_bom(f))
            n += 1
    print(("DRYRUN: " if args.dry_run else "") + f"stripped {n} file(s)")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="给文本产物盖时间戳+版本戳（手工简化版 git）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("new", cmd_new), ("bump", cmd_bump), ("show", cmd_show)):
        p = sub.add_parser(name)
        p.add_argument("file")
        p.add_argument("--note", default=DEFAULT_NOTE, help="本次变更说明（一句话）")
        if name != "show":
            p.add_argument("--author", default=DEFAULT_AUTHOR)
        if name == "bump":
            p.add_argument("--force", action="store_true", help="note 没变也强制升版")
        p.set_defaults(func=fn)
    p = sub.add_parser("check", help="体检：缺戳 / 改过没盖戳 / 戳过期")
    p.add_argument("paths", nargs="+")
    p.add_argument("--days", type=int, default=30, help="戳超过多少天算旧（默认 30）")
    p.add_argument("--tolerance", type=int, default=TOLERANCE_S, help="mtime 比戳晚多少秒算漂移（默认 90）")
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--include-json", action="store_true", help="连 .json 也纳入体检（默认豁免数据文件）")
    p.add_argument("--include-code", action="store_true", help="连 .py/.ps1/.js 等代码文件也纳入体检")
    p.set_defaults(func=cmd_check)
    ps = sub.add_parser("strip", help="回滚：删除所有戳行")
    ps.add_argument("paths", nargs="+")
    ps.add_argument("--dry-run", action="store_true")
    ps.add_argument("--include-json", action="store_true")
    ps.set_defaults(func=cmd_strip)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
