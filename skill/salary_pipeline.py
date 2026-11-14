#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工资条 / 账单自动处理可复用脚本：抓取 -> 解密解析 -> 年度汇总 -> 自包含 HTML 报表
============================================================================

子命令:
  fetch      从网易 IMAP 抓取附件到本地（遍历全部文件夹，按 sources 多来源匹配，首跑全量/后续增量）
  list       只读列出全部邮件（发件人/主题/附件名），用于核对关键词命中，不下载、不改文件
  discover   列出某个 xls/xlsx 中的文本标签，用于确认/配置字段映射（field_map）
  analyze    解析本地工资条 -> 年度汇总 -> 生成 HTML 报表 + CSV 汇总
  run        fetch 之后紧接 analyze（端到端一键执行）
  self-test  用内置样例验证 解析/汇总/HTML 生成逻辑（不依赖真实数据，不访问网络）

多来源（config.sources）：
  每个来源含 sender_keywords（发件人关键词）、subject_keywords（主题关键词）、
  exclude_keywords（排除关键词）、match_mode（and/or，默认 and）、
  save_subdir（相对 save_dir 的子目录）、extensions（可下载扩展名）。
  默认按 "sender 命中 AND subject 命中" 匹配；电费/南方电网等可设 match_mode="or"；
  命中后下载到对应子目录，文件名按 YYYY-MM.ext（主题解析，回退邮件日期）。
  若邮件无附件但含 text/html 正文（多数电子账单），自动兜底保存为 YYYY-MM-UID.html。

报表布局（analyze / run 产出）:
  1) 可视化（最上）：收入支出泳道整合柱状图 + 支出占比饼图（含自由现金流）
  2) 年度汇总（第二）
  3) 财报式分析（按上市公司利润表口径，含关键比率与 MD&A）
  4) 月度明细（最后）

设计要点:
  - 零三方依赖做网络/抓取（仅标准库 imaplib/email）；解析用 xlrd/openpyxl/msoffcrypto（按需）。
  - 字段抽取是“数据驱动 + 关键词启发式”的，不依赖固定表格版式；可通过 config 的 field_map 覆盖。
  - 解密：若 xls/xlsx 被密码保护，用 msoffcrypto 解密后再读取；密码来自 config.analysis.xls_password
    或环境变量 SALARY_XLS_PASSWORD 或命令行 --password。
  - 报表为单一 HTML 文件，内联 SVG 图表，离线可直接双击打开，也便于任何 Agent 读取。

用法示例:
  python salary_pipeline.py fetch
  python salary_pipeline.py fetch --dry-run
  python salary_pipeline.py list
  python salary_pipeline.py discover "C:/.../2026-07.xls" --password 123456
  python salary_pipeline.py analyze
  python salary_pipeline.py analyze --password 身份证后6位
  python salary_pipeline.py run
  python salary_pipeline.py self-test
"""

import argparse
import csv
import datetime as _dt
import email
import imaplib
import io
import json
import math
import os
import re
import xml.sax.saxutils as _xml


# ----------------------------------------------------------------------------
# 文件写入辅助：复用 safe_write 的抗 云盘/云盘同步锁稳健写（temp + os.replace）
# ----------------------------------------------------------------------------
from safe_write import open_write as _open_write, _cleanup_stale  # 同目录模块；原子替换可绕过同步锁

# ----------------------------------------------------------------------------
# 默认字段映射：label 关键词 -> 规范字段。命中规则：单元格文本包含任一关键词即视为该字段标签，
# 然后在其右侧同行（优先）或同列下方寻找关联数值。可在 config.analysis.field_map 中覆盖/扩展。
# ----------------------------------------------------------------------------
DEFAULT_FIELD_MAP = {
    "gross":        ["本期工资", "税前工资", "应发工资", "应发合计", "税前收入", "工资总额", "应发金额"],
    "pension":      ["养老保险", "养老", "养老金", "养老保险费"],
    "medical":      ["医疗保险", "医疗", "医保", "医疗保险费"],
    "unemployment": ["失业保险", "失业", "失业险"],
    "housing":      ["住房公积金", "公积金", "住房", "住房公积金费"],
    "tax":          ["个人所得税", "个税", "税额", "代扣税", "代扣代缴税"],
    "net":          ["实发工资", "税后工资", "实发合计", "实发", "到手", "实发金额"],
}

# 配色（图表与表格共用）
COLORS = {
    "gross":        "#2f80ed",
    "pension":      "#eb5757",
    "medical":      "#27ae60",
    "unemployment": "#f2994a",
    "housing":      "#9b51e0",
    "tax":          "#828282",
    "net":          "#219653",
    "social":       "#2d9cdb",
}

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


# ============================================================================
# 配置
# ============================================================================
def load_config(path=CONFIG_PATH):
    if not os.path.exists(path):
        from app_config import config_path
        path = config_path()
    with open(path, "r",  encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("analysis", {})
    cfg["analysis"].setdefault("field_map", {})
    # field_map 为空时用默认；非空时与默认合并（用户只写覆盖项）
    fm = dict(DEFAULT_FIELD_MAP)
    fm.update(cfg["analysis"].get("field_map", {}))
    cfg["analysis"]["field_map"] = fm
    # 统一路径/凭据解析：消除散落的绝对路径，并让环境变量覆盖明文凭据
    from app_config import apply_runtime_paths
    return apply_runtime_paths(cfg)


def resolve_password(cfg, cli_password):
    return cli_password or os.environ.get("SALARY_XLS_PASSWORD") or cfg["analysis"].get("xls_password", "")


# ============================================================================
# IMAP 抓取（遍历全部文件夹 + 跨文件夹 UID 去重）
# ============================================================================
def _decode_header_val(val):
    if not val:
        return ""
    out = []
    for data, enc in email.header.decode_header(val):
        if isinstance(data, bytes):
            # 网易邮箱中文头常标为 unknown-8bit（实为 GB2312/GBK），
            # 直接按 latin-1/utf-8 解码会乱码；依次尝试中文编码兜底。
            cands = []
            if enc and enc.lower() not in ("unknown-8bit", "default"):
                cands.append(enc)
            cands += ["utf-8", "gb18030", "latin-1"]
            text = None
            for c in cands:
                try:
                    text = data.decode(c)
                    break
                except Exception:
                    continue
            out.append(text if text is not None else data.decode("latin-1", "replace"))
        else:
            out.append(str(data))
    return "".join(out)


def _imap_connect(cfg):
    mail = imaplib.IMAP4_SSL(cfg["imap_server"], int(cfg.get("imap_port", 993)), timeout=60)
    mail.login(cfg["email"], cfg["auth_code"])
    # 网易要求 SELECT 前先发 ID 命令，否则报 "Unsafe Login"
    try:
        mail.xatom("ID", '("name" "WorkBuddyFetcher" "version" "1.0" "vendor" "NetEase")')
    except Exception:
        pass
    return mail


def _iter_all_folders(mail):
    """返回所有可读文件夹名（含系统文件夹，但跳过无法 select 的）。"""
    typ, raw = mail.list()
    names = []
    if typ != "OK" or not raw:
        return names
    for line in raw:
        if not line:
            continue
        s = line.decode("utf-8", "replace")
        m = re.search(r'"([^"]*)"\s+"([^"]*)"\s*$', s) or re.search(r'"([^"]*)"\s+([^\s].*?)\s*$', s)
        if m:
            name = m.group(2) if m.group(2) else m.group(1)
            names.append(name.strip().strip('"'))
        else:
            q = re.findall(r'"([^"]*)"', s)
            if q:
                names.append(q[-1])
    return names


def _period_from_subject(subject):
    """从主题解析工资所属年月，例如 '示例-2026年7月工资条' -> (2026, 7)。"""
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", subject)
    if m:
        return int(m.group(1)), int(m.group(2))
    # 注意：必须加数字边界 (?<!\d) / (?!\d)。
    # 否则兴业银行主题「[202606-202609]」这类"连续数字区间"会被误匹配成 (2606, 20)，
    # 生成 "2606-20.pdf" 这种脏文件名。加边界后这类文本不匹配，安全回退到邮件日期。
    m = re.search(r"(?<!\d)(\d{4})[-/](\d{1,2})(?!\d)", subject)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return y, mo
    return None, None


def _build_sources(cfg):
    """统一 sources 格式；兼容旧版顶层 sender/subject_keywords。"""
    if cfg.get("sources"):
        out = []
        for s in cfg["sources"]:
            out.append({
                "name": s.get("name", "default"),
                "label": s.get("label", s.get("name", "default")),
                "sender_keywords": [k.lower() for k in s.get("sender_keywords", [])],
                "subject_keywords": s.get("subject_keywords", []),
                "exclude_keywords": [k.lower() for k in s.get("exclude_keywords", [])],
                "match_mode": s.get("match_mode", "and"),
                "save_subdir": s.get("save_subdir", ""),
                "extensions": [e.lower() for e in s.get("extensions", cfg.get("extensions", [".xls", ".xlsx"]))],
            })
        return out
    return [{
        "name": "salary",
        "label": "工资条",
        "sender_keywords": [k.lower() for k in cfg.get("sender_keywords", [])],
        "subject_keywords": cfg.get("subject_keywords", []),
        "exclude_keywords": [],
        "match_mode": "and",
        "save_subdir": "",
        "extensions": [e.lower() for e in cfg.get("extensions", [".xls", ".xlsx"])],
    }]


def _match_source(frm, subj, sources):
    """按顺序返回第一个命中。
    match_mode='and'（默认）：sender 关键词 AND subject 关键词 同时命中（某维度关键词为空则跳过该维度）。
    match_mode='or'：sender 命中 或 subject 命中 其一即可（用于电费等按发件人/主题任一即可识别的账单）。
    """
    for s in sources:
        sk = s["sender_keywords"]
        sk_sub = s["subject_keywords"]
        ex = s.get("exclude_keywords", [])
        if ex and any(k in (frm + " " + subj).lower() for k in ex):
            continue
        s_ok = (not sk) or any(k in frm.lower() for k in sk)
        sub_ok = (not sk_sub) or any(k in subj for k in sk_sub)
        if s["match_mode"] == "or":
            if s_ok or sub_ok:
                return s
        else:
            if s_ok and sub_ok:
                return s
    return None


def _write_download_index(cfg, rows):
    """rows: [(label, period, filename, orig_name, sender, subject, email_date)]；按 (来源,文件名) 去重写 download_index.csv。

    保留"原始文件名"很关键：电子发票的文件名形如
    "202607_示例用户_225.83_示例编号.pdf"，金额 225.83 直接编码在文件名里，
    重命名成 YYYY-MM.pdf 会丢失该信息。
    """
    path = os.path.join(cfg["save_dir"], "download_index.csv")
    existing = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                for r in csv.reader(f):
                    if r and r[0] != "来源":
                        # 兼容旧格式（7列，无"原始文件名"）：在第4列补空
                        if len(r) == 7:
                            r = [r[0], r[1], r[2], "", r[3], r[4], r[5], r[6]]
                        existing[(r[0], r[2])] = r
        except Exception:
            existing = {}
    for r in rows:
        existing[(r[0], r[2])] = [
            r[0], r[1], r[2], r[3], r[4], r[5], r[6],
            _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        ]
    try:
        with _open_write(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["来源", "期间", "文件名", "原始文件名", "发件人", "主题", "邮件日期", "下载时间"])
            for r in sorted(existing.values(), key=lambda x: (x[0], x[1], x[2])):
                w.writerow(r)
        return path
    except (PermissionError, OSError) as e:
        print("[警告] download_index.csv 无法写入（可能被云盘同步占用）:%s，本次跳过下载索引更新。" % e)
        return path


def fetch_emails(cfg, dry_run=False, verbose=True):
    save_dir = cfg["save_dir"]
    os.makedirs(save_dir, exist_ok=True)
    state_file = cfg.get("state_file", "state.json")
    state = _load_state(state_file)
    seen = state.setdefault("seen_uids", {})
    sources = _build_sources(cfg)

    mail = _imap_connect(cfg)
    folders = _iter_all_folders(mail)
    downloaded = []
    index_rows = []
    per_source_hits = {s["name"]: 0 for s in sources}

    for fname in folders:
        try:
            r, _ = mail.select('"%s"' % fname.replace('"', '\\"'))
        except Exception:
            r = "NO"
        if r != "OK":
            continue
        try:
            t, data = mail.uid("SEARCH", None, "ALL")
        except Exception:
            continue
        if t != "OK" or not data or not data[0]:
            continue
        uids = [u.decode() for u in data[0].split()]
        folder_seen = set(seen.get(fname, []))
        for uid in uids:
            try:
                t2, d2 = mail.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            except Exception:
                continue
            if t2 != "OK" or not d2 or not d2[0] or d2[0][1] is None:
                continue
            msg = email.message_from_bytes(d2[0][1])
            frm = _decode_header_val(msg.get("From"))
            subj = _decode_header_val(msg.get("Subject"))
            date = msg.get("Date", "")
            src = _match_source(frm, subj, sources)
            if src is None:
                continue
            per_source_hits[src["name"]] += 1
            year, month = _period_from_subject(subj)
            if year is None:
                try:
                    dt = email.utils.parsedate_to_datetime(date)
                    if dt:
                        year, month = dt.year, dt.month
                except Exception:
                    pass
                if year is None:
                    dm = re.search(r"(\d{4})-(\d{2})", date)
                    if dm:
                        year, month = int(dm.group(1)), int(dm.group(2))
            subdir = src["save_subdir"]
            target_dir = os.path.join(save_dir, subdir) if subdir else save_dir
            os.makedirs(target_dir, exist_ok=True)
            t3, d3 = mail.uid("FETCH", uid, "(RFC822)")
            if t3 != "OK" or not d3 or not d3[0] or d3[0][1] is None:
                continue
            full = email.message_from_bytes(d3[0][1])
            att_count = 0
            saved_any = False
            for part in full.walk():
                fn = part.get_filename()
                if not fn:
                    continue
                # 关键修复：附件文件名常为 RFC2047/MIME 编码（如 =?gb2312?Q?...=2Epdf?=），
                # 必须先解码再取扩展名。否则 splitext 拿到的是编码串尾部（如 "?="),
                # 导致 ext 永远不匹配 -> PDF/OFD 等附件被静默跳过（电子发票即此坑）。
                fn = _decode_header_val(fn)
                ext = os.path.splitext(fn)[1].lower()
                if ext not in src["extensions"]:
                    continue
                att_count += 1
                if year is None or month is None:
                    ym = "unknown"
                else:
                    ym = "%04d-%02d" % (year, month)
                base_name = ("%s%s" % (ym, ext)) if att_count == 1 else ("%s-%d%s" % (ym, att_count, ext))
                target = os.path.join(target_dir, base_name)
                # 去重依据改为“本地文件是否存在”：文件被手动删除则重新下载，
                # 不再仅依赖 seen 集合（修复删除后无法自动重抓的陷阱）
                if os.path.exists(target):
                    if dry_run and verbose:
                        print("[dry-run] 已存在(跳过): [%s] %s" % (src["label"], os.path.basename(target)))
                    saved_any = True
                    continue
                if dry_run:
                    if verbose:
                        print("[dry-run] 将下载: [%s] 主题=%s | 附件=%s -> %s"
                              % (src["label"], subj, os.path.basename(fn), target))
                else:
                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue
                    with open(target, "wb") as wf:
                        wf.write(payload)
                    downloaded.append((src["name"], target))
                    index_rows.append((src["label"], ym, os.path.basename(target), fn, frm, subj, date))
                    saved_any = True
                    if verbose:
                        print("已下载: [%s] %s (UID=%s)" % (src["label"], target, uid))
            # 兜底：匹配来源但无（符合扩展名的）附件时，保存 HTML 正文（多数电子账单是内联 HTML）
            if not saved_any and year is not None:
                for part in full.walk():
                    if part.get_content_type() == "text/html":
                        payload = part.get_payload(decode=True)
                        if not payload:
                            continue
                        ym = "%04d-%02d" % (year, month)
                        target = os.path.join(target_dir, "%s-%s.html" % (ym, uid))
                        if os.path.exists(target):
                            if dry_run and verbose:
                                print("[dry-run] 已存在(跳过): [%s] %s" % (src["label"], os.path.basename(target)))
                            break
                        if dry_run:
                            if verbose:
                                print("[dry-run] 将保存正文HTML: [%s] 主题=%s -> %s" % (src["label"], subj, target))
                        else:
                            with open(target, "wb") as wf:
                                wf.write(payload)
                            downloaded.append((src["name"], target))
                            index_rows.append((src["label"], ym, os.path.basename(target), "", frm, subj, date))
                            if verbose:
                                print("已保存正文: [%s] %s (UID=%s)" % (src["label"], target, uid))
                        break
            folder_seen.add(uid)
        seen[fname] = list(folder_seen)

    if not dry_run:
        _save_state(state_file, state)
        _write_download_index(cfg, index_rows)
    try:
        mail.logout()
    except Exception as e:
        # IMAP 连接可能在长时间运行后被服务端关闭，logout 失败不影响已完成的抓取
        if verbose:
            print("[警告] IMAP logout 时连接已关闭（可忽略）:%s" % e)
    if verbose:
        print("抓取完成：命中 %s；本次新下载 %d 个附件。" % (per_source_hits, len(downloaded)))
    return downloaded


def list_emails(cfg, verbose=True):
    """只读列出全部文件夹的邮件（发件人/主题/日期/附件扩展名），用于核对关键词是否命中。不下载、不改文件。"""
    sources = _build_sources(cfg)
    mail = _imap_connect(cfg)
    folders = _iter_all_folders(mail)
    count = 0
    for fname in folders:
        try:
            r, _ = mail.select('"%s"' % fname.replace('"', '\\"'))
        except Exception:
            r = "NO"
        if r != "OK":
            continue
        try:
            t, data = mail.uid("SEARCH", None, "ALL")
        except Exception:
            continue
        if t != "OK" or not data or not data[0]:
            continue
        uids = [u.decode() for u in data[0].split()]
        for uid in uids:
            try:
                t2, d2 = mail.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            except Exception:
                continue
            if t2 != "OK" or not d2 or not d2[0] or d2[0][1] is None:
                continue
            msg = email.message_from_bytes(d2[0][1])
            frm = _decode_header_val(msg.get("From"))
            subj = _decode_header_val(msg.get("Subject"))
            date = msg.get("Date", "")
            t3, d3 = mail.uid("FETCH", uid, "(RFC822)")
            atts = []
            if t3 == "OK" and d3 and d3[0] and d3[0][1]:
                full = email.message_from_bytes(d3[0][1])
                for part in full.walk():
                    fn = part.get_filename()
                    if fn:
                        atts.append(os.path.splitext(fn)[1].lower())
            matched = _match_source(frm, subj, sources)
            tag = ("命中[%s]" % matched["label"]) if matched else "—"
            if verbose:
                print("%s | 文件夹:%s | 发件人:%s | 主题:%s | 日期:%s | 附件:%s"
                      % (tag, fname, frm, subj, date, ",".join(atts) or "无"))
            count += 1
    try:
        mail.logout()
    except Exception:
        pass
    if verbose:
        print("共列出 %d 封邮件。" % count)
    return count


def _load_state(state_file):
    if os.path.exists(state_file):
        with open(state_file, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                pass
    return {"seen_uids": {}}  # folder -> [uid,...]


def _save_state(state_file, state):
    """保存 UID 去重状态；若文件被占用/无写权限，打印警告后继续（当前去重主要依赖本地文件是否存在，state 为辅助）。"""
    try:
        with _open_write(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except (PermissionError, OSError) as e:
        print("[警告] state.json 无法写入（可能被其他进程占用）:%s，本次跳过状态持久化。" % e)


# ============================================================================
# 解析 xls/xlsx（支持密码解密）
# ============================================================================
def _open_salary_file(path, password):
    """返回 (kind, workbook) —— kind in {'xlrd','openpyxl'}。加密文件自动解密。"""
    with open(path, "rb") as f:
        raw = f.read()
    is_xlsx = path.lower().endswith(".xlsx")
    if password:
        try:
            import msoffcrypto
            buf = io.BytesIO()
            office = msoffcrypto.OfficeFile(io.BytesIO(raw))
            office.load_key(password=password)
            office.decrypt(buf)
            raw = buf.getvalue()
        except Exception as e:
            raise RuntimeError("解密失败（密码错误或文件非 Office 加密）: %s" % e)
    if is_xlsx:
        import openpyxl
        return "openpyxl", openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
    else:
        import xlrd
        try:
            return "xlrd", xlrd.open_workbook(file_contents=raw)
        except Exception as e:
            if "encrypted" in str(e).lower() or "password" in str(e).lower():
                raise RuntimeError("文件已加密，请在 config/--password 提供打开密码")
            raise


def _iter_cells(kind, wb):
    """统一产出 (row, col, value)，行/列从 1 开始。"""
    if kind == "openpyxl":
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is not None and str(cell.value).strip() != "":
                        yield cell.row, cell.column, cell.value
    else:
        for sh in wb.sheets():
            for r in range(sh.nrows):
                for c in range(sh.ncols):
                    v = sh.cell_value(r, c)
                    if v is not None and str(v).strip() != "":
                        yield r + 1, c + 1, v


def extract_record(path, password, field_map):
    """从单个工资条文件抽取规范字段。返回 dict（字段->float 或 None）。"""
    kind, wb = _open_salary_file(path, password)
    cells = list(_iter_cells(kind, wb))
    text_cells = []
    num_pos = {}
    for r, c, v in cells:
        if isinstance(v, bool):
            continue
        if isinstance(v, str):
            text_cells.append((r, c, v.strip()))
        elif isinstance(v, (int, float)):
            num_pos[(r, c)] = float(v)

    record = {}
    for field, kws in field_map.items():
        best = None
        for r, c, t in text_cells:
            for kw in kws:
                if kw and kw in t:
                    if best is None or len(t) < len(best[2]):
                        best = (r, c, t)
                    break
        if best is None:
            record[field] = None
            continue
        r, c, _t = best
        val = None
        for cc in range(c + 1, c + 10):
            if (r, cc) in num_pos:
                val = num_pos[(r, cc)]
                break
        if val is None:
            for rr in range(r + 1, r + 6):
                if (rr, c) in num_pos:
                    val = num_pos[(rr, c)]
                    break
        record[field] = val
    return record


def discover_file(path, password):
    """列出文件中的去重文本标签，帮助确认 field_map。"""
    kind, wb = _open_salary_file(path, password)
    texts = set()
    for _r, _c, v in _iter_cells(kind, wb):
        if isinstance(v, str) and v.strip():
            texts.add(v.strip())
    return sorted(texts)


# ============================================================================
# 汇总
# ============================================================================
def period_from_filename(path):
    base = os.path.basename(path)
    m = re.match(r"(\d{4})-(\d{2})", base)
    if m:
        return "%s-%s" % (m.group(1), m.group(2))
    return None


def analyze_local(cfg, password, verbose=True):
    save_dir = cfg["save_dir"]
    field_map = cfg["analysis"]["field_map"]
    exts = tuple(cfg.get("extensions", [".xls", ".xlsx"]))
    records = {}
    errors = []

    for fn in sorted(os.listdir(save_dir)):
        if not fn.lower().endswith(exts):
            continue
        if fn.lower() in ("salary_index.csv", "download_index.csv"):
            continue
        period = period_from_filename(fn)
        path = os.path.join(save_dir, fn)
        try:
            rec = extract_record(path, password, field_map)
            if period is None:
                period = fn
            records[period] = rec
            if verbose:
                print("解析成功: %s -> %s" % (fn, rec))
        except Exception as e:
            errors.append((fn, str(e)))
            if verbose:
                print("解析失败: %s -> %s" % (fn, e))

    monthly = build_monthly(records)
    annual = build_annual(monthly)
    return monthly, annual, errors


def _num(v):
    return float(v) if isinstance(v, (int, float)) else 0.0


def build_monthly(records):
    monthly = []
    for period in sorted(records.keys()):
        rec = records[period]
        gross = _num(rec.get("gross"))
        pension = _num(rec.get("pension"))
        medical = _num(rec.get("medical"))
        unemployment = _num(rec.get("unemployment"))
        housing = _num(rec.get("housing"))
        tax = _num(rec.get("tax"))
        net = _num(rec.get("net"))
        if rec.get("social_total") is not None:
            social = _num(rec.get("social_total"))
        else:
            social = pension + medical + unemployment + housing
        monthly.append({
            "period": period,
            "gross": gross,
            "pension": pension,
            "medical": medical,
            "unemployment": unemployment,
            "housing": housing,
            "social": social,
            "tax": tax,
            "net": net,
        })
    return monthly


def build_annual(monthly):
    annual = {}
    for m in monthly:
        year = m["period"][:4]
        a = annual.setdefault(year, {
            "year": year, "gross": 0.0, "pension": 0.0, "medical": 0.0,
            "unemployment": 0.0, "housing": 0.0, "social": 0.0, "tax": 0.0, "net": 0.0,
            "months": 0,
        })
        for k in ("gross", "pension", "medical", "unemployment", "housing", "social", "tax", "net"):
            a[k] += m[k]
        a["months"] += 1
    return [annual[y] for y in sorted(annual.keys())]


# ============================================================================
# 输出：CSV 汇总
# ============================================================================
def write_csv(cfg, monthly, annual):
    path = cfg["analysis"].get("summary_csv", "")
    if not path:
        return None
    with _open_write(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["类型", "期间", "税前工资收入", "养老保险", "医疗保险", "失业保险",
                    "住房公积金", "社保合计(税前支出)", "个人所得税(税费支出)", "税后工资"])
        for m in monthly:
            w.writerow(["月度", m["period"], _r2(m["gross"]), _r2(m["pension"]), _r2(m["medical"]),
                        _r2(m["unemployment"]), _r2(m["housing"]), _r2(m["social"]),
                        _r2(m["tax"]), _r2(m["net"])])
        for a in annual:
            w.writerow(["年度", a["year"], _r2(a["gross"]), _r2(a["pension"]), _r2(a["medical"]),
                        _r2(a["unemployment"]), _r2(a["housing"]), _r2(a["social"]),
                        _r2(a["tax"]), _r2(a["net"])])
    return path


def _r2(v):
    return round(v, 2)


# ============================================================================
# 输出：HTML 报表（内联 SVG，离线可用）
# ============================================================================
def _esc(s):
    return _xml.escape(str(s))


def _fmt_money(v):
    try:
        return "{:,.2f}".format(float(v))
    except Exception:
        return str(v)


def _fmt_short(v):
    v = float(v)
    if abs(v) >= 10000:
        return "%.1f万" % (v / 10000)
    if abs(v) >= 1000:
        return "%.0f" % v
    return "%.0f" % v


# ---- 可视化：收入支出泳道整合柱状图 -----------------------------------------
def svg_swimlane(title, rows):
    if not rows:
        return "<p class='nodata'>无数据</p>"
    w = 760
    row_h = 46
    pad_t = 44
    pad_b = 26
    h = pad_t + len(rows) * row_h + pad_b
    x0 = 96          # 月份标签右边界
    x1 = 720         # 条形右边界
    bar_w = x1 - x0
    maxv = max(r["gross"] for r in rows) or 1
    scale = bar_w / maxv
    seg_defs = [
        ("pension", "养老保险", COLORS["pension"]),
        ("medical", "医疗保险", COLORS["medical"]),
        ("unemployment", "失业保险", COLORS["unemployment"]),
        ("housing", "住房公积金", COLORS["housing"]),
        ("tax", "个人所得税", COLORS["tax"]),
        ("net", "税后/自由现金流", COLORS["net"]),
    ]
    parts = ["<svg viewBox='0 0 %d %d' class='chart' xmlns='http://www.w3.org/2000/svg'>" % (w, h)]
    parts.append("<text x='%d' y='24' class='ctitle'>%s</text>" % (x0, _esc(title)))
    parts.append("<line x1='%d' y1='%d' x2='%d' y2='%d' class='grid'/>" % (x0, pad_t - 8, x0, h - pad_b))
    for i, r in enumerate(rows):
        yc = pad_t + i * row_h + row_h / 2
        ytop = yc - 13
        bar_h = 26
        parts.append("<text x='%d' y='%.1f' class='xlabel' text-anchor='end'>%s</text>" % (x0 - 8, yc + 4, _esc(r["period"])))
        cx = x0
        above_count = 0
        for key, label, color in seg_defs:
            v = r.get(key, 0)
            if v <= 0:
                continue
            sw = v * scale
            parts.append("<rect x='%.1f' y='%.1f' width='%.1f' height='%d' fill='%s'/>" % (cx, ytop, sw, bar_h, color))
            txt = _fmt_money(v)
            est = len(txt) * 5.4
            if sw >= est + 4:
                # 段足够宽：金额标注在段内（白字）
                parts.append("<text x='%.1f' y='%.1f' class='barval' text-anchor='middle'>%s</text>" % (cx + sw / 2, yc + 4, txt))
            else:
                # 段太窄：标注在段上方（深色字，避免白底白字不可见），相邻窄段自动错开防重叠
                yoff = 5 + (above_count % 2) * 11
                parts.append("<text x='%.1f' y='%.1f' class='barval-out' text-anchor='middle'>%s</text>" % (cx + sw / 2, ytop - yoff, txt))
                above_count += 1
            cx += sw
    # 图例
    ly = h - 8
    lx = x0
    for key, label, color in seg_defs:
        parts.append("<rect x='%d' y='%d' width='12' height='12' fill='%s'/>" % (lx, ly - 10, color))
        parts.append("<text x='%d' y='%d' class='legend'>%s</text>" % (lx + 16, ly, _esc(label)))
        lx += 22 + len(_esc(label)) * 13
    parts.append("</svg>")
    return "".join(parts)


# ---- 可视化：支出占比饼图（含自由现金流） -----------------------------------
def svg_pie(title, items):
    total = sum(v for _, v, _ in items) or 1
    if total <= 0:
        return "<p class='nodata'>无数据</p>"
    w, h = 760, 340
    cx, cy, r = 190, 170, 130
    parts = ["<svg viewBox='0 0 %d %d' class='chart' xmlns='http://www.w3.org/2000/svg'>" % (w, h)]
    parts.append("<text x='%d' y='24' class='ctitle'>%s</text>" % (cx, _esc(title)))
    a = -math.pi / 2
    for label, val, color in items:
        if val <= 0:
            continue
        frac = val / total
        a1 = a + 2 * math.pi * frac
        x0 = cx + r * math.cos(a)
        y0 = cy + r * math.sin(a)
        x1 = cx + r * math.cos(a1)
        y1 = cy + r * math.sin(a1)
        large = 1 if (a1 - a) > math.pi else 0
        parts.append("<path d='M%.1f,%.1f L%.1f,%.1f A%.1f,%.1f 0 %d 1 %.1f,%.1f Z' fill='%s'/>"
                     % (cx, cy, x0, y0, r, r, large, x1, y1, color))
        mid = (a + a1) / 2
        lx = cx + (r * 0.6) * math.cos(mid)
        ly = cy + (r * 0.6) * math.sin(mid)
        parts.append("<text x='%.1f' y='%.1f' class='pielbl'>%.1f%%</text>" % (lx, ly + 4, frac * 100))
        a = a1
    parts.append("<text x='%d' y='%d' class='donutcenter'>总收入 %s</text>" % (cx, cy + 4, _fmt_short(total)))
    # 图例（右侧）
    lx = 410
    ly = 70
    for label, val, color in items:
        pctv = 100.0 * val / total
        parts.append("<rect x='%d' y='%d' width='14' height='14' fill='%s'/>" % (lx, ly, color))
        parts.append("<text x='%d' y='%d' class='legend'>%s  %.1f%%  (%s)</text>" % (lx + 20, ly + 12, _esc(label), pctv, _fmt_money(val)))
        ly += 30
    parts.append("</svg>")
    return "".join(parts)


# ---- 财报式分析（按上市公司利润表口径） -------------------------------------
def render_financial_report(annual):
    years = [a["year"] for a in annual]
    overall = {k: sum(a[k] for a in annual) for k in
               ("gross", "social", "tax", "net", "pension", "medical", "unemployment", "housing")}
    by_year = {a["year"]: a for a in annual}
    get = lambda y, k: by_year[y][k] if y in by_year else 0
    col = _fmt_money
    pct = lambda n, d: ("%.1f%%" % (100.0 * n / d)) if d else "-"

    line_items = [
        ("营业收入（税前工资）", "gross", False),
        ("减：营业总成本（社保·公积金）", "social", False),
        ("　其中：养老保险", "pension", True),
        ("　其中：医疗保险", "medical", True),
        ("　其中：失业保险", "unemployment", True),
        ("　其中：住房公积金", "housing", True),
        ("减：所得税费用（个人所得税）", "tax", False),
        ("净利润（税后到手 / 自由现金流）", "net", False),
    ]
    head = "<tr><th>利润表项目</th>" + "".join("<th class='num'>%s</th>" % y for y in years) + "<th class='num'>合计</th></tr>"
    body = ""
    for label, key, sub in line_items:
        cells = "".join("<td class='num'>%s</td>" % col(get(y, key)) for y in years)
        cells += "<td class='num strong'>%s</td>" % col(overall[key])
        cls = " class='sub'" if sub else ""
        body += "<tr%s><td%s>%s</td>%s</tr>" % (cls, cls, _esc(label), cells)

    ratios = [
        ("社保负担率（社保/税前）", pct(overall["social"], overall["gross"])),
        ("综合费用率（(社保+个税)/税前）", pct(overall["social"] + overall["tax"], overall["gross"])),
        ("净利率 / 到手率（税后/税前）", pct(overall["net"], overall["gross"])),
        ("自由现金流比率（税后/税前）", pct(overall["net"], overall["gross"])),
    ]
    rrows = "".join("<tr><td>%s</td><td class='num strong'>%s</td></tr>" % (k, v) for k, v in ratios)

    g, s, t, n = overall["gross"], overall["social"], overall["tax"], overall["net"]
    mda = ("报告期内，个人薪酬业务实现营业总收入（税前工资）<b>%s</b> 元；发生营业总成本"
           "（社保及住房公积金等）<b>%s</b> 元、所得税费用（个人所得税）<b>%s</b> 元；"
           "实现净利润（税后到手，即自由现金流）<b>%s</b> 元，整体到手率（净利率）<b>%s</b>。"
           "其中社保与个税合计占税前收入 <b>%s</b>，建议保持稳健的现金留存，"
           "自由现金流可用于投资或储备。") % (col(g), col(s), col(t), col(n), pct(n, g), pct(s + t, g))

    return """
    <div class="card">
      <h2>财报式分析（按上市公司利润表口径）</h2>
      <p class="mda">%s</p>
      <div class="table-wrap">
        <table>%s<tbody>%s</tbody></table>
      </div>
      <h3>关键财务比率</h3>
      <div class="table-wrap">
        <table class="ratios"><thead><tr><th>指标</th><th class="num">数值</th></tr></thead><tbody>%s</tbody></table>
      </div>
      <p class="note">说明：个人工资按“企业”视角映射——税前工资≈营业收入，社保公积金≈营业总成本，个税≈所得税费用，税后到手≈净利润/自由现金流。仅供个人财务体检参考。</p>
    </div>
    """ % (mda, head, body, rrows)


def _delta_cell(prev_val, cur_val, good_when_up):
    """环比单元格：prev_val 为 None 表示无上月对照；good_when_up 定义该项的“好”方向。"""
    if prev_val is None:
        return "<td class='num delta-zero'>—</td>"
    d = (cur_val or 0.0) - (prev_val or 0.0)
    if abs(d) < 0.005:
        return "<td class='num delta-zero'>—</td>"
    up = d > 0
    good = (up == good_when_up)
    cls = "delta-pos" if good else "delta-neg"
    arrow = "▲" if up else "▼"
    return "<td class='num %s'>%s%s</td>" % (cls, arrow, _fmt_money(abs(d)))


def _prev_month_map(monthly_sorted):
    """返回 {period: 上一自然月记录 或 None}。仅当确为相邻自然月才配对（跨年不误配）。"""
    prev_map = {}
    for i, m in enumerate(monthly_sorted):
        if i == 0:
            prev_map[m["period"]] = None
            continue
        pm = monthly_sorted[i - 1]
        y, mo = int(m["period"][:4]), int(m["period"][5:7])
        py, pmo = int(pm["period"][:4]), int(pm["period"][5:7])
        consecutive = (y == py and mo == pmo + 1) or (pmo == 12 and mo == 1 and y == py + 1)
        prev_map[m["period"]] = pm if consecutive else None
    return prev_map


def _delta_callout(monthly_sorted, prev_map):
    """针对最新一个有上月的月份，生成“环比速览”一句话（带颜色）。"""
    if not monthly_sorted:
        return ""
    last = monthly_sorted[-1]
    prev = prev_map.get(last["period"])
    if prev is None:
        return ""
    def span(label, cur, pv, good_up):
        d = (cur or 0.0) - (pv or 0.0)
        if abs(d) < 0.005:
            return "%s 持平" % label
        up = d > 0
        good = (up == good_up)
        cls = "delta-pos" if good else "delta-neg"
        arrow = "▲" if up else "▼"
        return "%s <span class='%s'>%s%s</span>" % (label, cls, arrow, _fmt_money(abs(d)))
    return ("<div class='callout'>环比速览：<b>%s</b> 较 %s ｜ %s ｜ %s ｜ %s ｜ %s</div>") % (
        last["period"], prev["period"],
        span("到手(税后)", last["net"], prev["net"], True),
        span("税前", last["gross"], prev["gross"], True),
        span("社保", last["social"], prev["social"], False),
        span("个税", last["tax"], prev["tax"], False),
    )


def render_html(cfg, monthly, annual, errors, output_path):
    gen = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    # 饼图数据（跨年合计）：支出各项 + 自由现金流，均占总收入的百分比
    tot = {k: sum(a[k] for a in annual) for k in ("pension", "medical", "unemployment", "housing", "tax", "net")}
    pie_items = [
        ("养老保险", tot["pension"], COLORS["pension"]),
        ("医疗保险", tot["medical"], COLORS["medical"]),
        ("失业保险", tot["unemployment"], COLORS["unemployment"]),
        ("住房公积金", tot["housing"], COLORS["housing"]),
        ("个人所得税", tot["tax"], COLORS["tax"]),
        ("自由现金流(税后)", tot["net"], COLORS["net"]),
    ]

    # 月度明细表（含环比高亮）
    monthly_sorted = sorted(monthly, key=lambda m: m["period"])
    prev_map = _prev_month_map(monthly_sorted)
    latest_period = monthly_sorted[-1]["period"] if monthly_sorted else None
    mrows = []
    for m in monthly_sorted:
        prev = prev_map.get(m["period"])
        row_cls = " class='latest'" if m["period"] == latest_period else ""
        d_gross = _delta_cell(prev["gross"] if prev else None, m["gross"], True)
        d_social = _delta_cell(prev["social"] if prev else None, m["social"], False)
        d_tax = _delta_cell(prev["tax"] if prev else None, m["tax"], False)
        d_net = _delta_cell(prev["net"] if prev else None, m["net"], True)
        mrows.append(
            "<tr%s><td>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
            "<td class='num'>%s</td><td class='num'>%s</td><td class='num strong'>%s</td>"
            "<td class='num'>%s</td><td class='num'>%s</td>%s%s%s%s</tr>"
            % (row_cls, m["period"], _fmt_money(m["gross"]), _fmt_money(m["pension"]), _fmt_money(m["medical"]),
               _fmt_money(m["unemployment"]), _fmt_money(m["housing"]), _fmt_money(m["social"]),
               _fmt_money(m["tax"]), _fmt_money(m["net"]),
               d_gross, d_social, d_tax, d_net))
    callout = _delta_callout(monthly_sorted, prev_map)
    # 年度汇总表
    arows = []
    for a in annual:
        arows.append(
            "<tr><td class='strong'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
            "<td class='num'>%s</td><td class='num'>%s</td><td class='num strong'>%s</td>"
            "<td class='num'>%s</td><td class='num'>%s</td></tr>"
            % (a["year"], _fmt_money(a["gross"]), _fmt_money(a["pension"]), _fmt_money(a["medical"]),
               _fmt_money(a["unemployment"]), _fmt_money(a["housing"]), _fmt_money(a["social"]),
               _fmt_money(a["tax"]), _fmt_money(a["net"])))

    err_html = ""
    if errors:
        err_html = "<div class='warn'><b>解析异常（%d 个文件）：</b><ul>%s</ul>" \
                   "如需解密请在 config.analysis.xls_password 或 --password 提供打开密码。</div>" \
                   % (len(errors), "".join("<li>%s: %s</li>" % (_esc(f), _esc(e)) for f, e in errors))

    nodata = ""
    if not monthly:
        nodata = "<div class='warn'>当前目录下没有可解析的工资条文件（或均因加密/格式无法解析）。"
        nodata += "请先运行 <code>fetch</code> 下载，并在 config 中填入 xls 打开密码后重试。</div>"

    fin_html = render_financial_report(annual) if annual else ""

    html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>工资条年度报表</title>
<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;margin:0;background:#f5f7fa;color:#1f2937;}
  .wrap{max-width:980px;margin:0 auto;padding:28px 20px 60px;}
  h1{font-size:24px;margin:0 0 4px;}
  .sub{color:#6b7280;font-size:13px;margin-bottom:20px;}
  .card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.04);}
  h2{font-size:17px;margin:0 0 14px;border-left:4px solid #2f80ed;padding-left:10px;}
  h3{font-size:14px;margin:18px 0 8px;color:#374151;}
  table{width:100%%;border-collapse:collapse;font-size:13px;min-width:640px;}
  th,td{border-bottom:1px solid #eef0f3;padding:8px 10px;text-align:left;vertical-align:top;}
  th{background:#f9fafb;color:#374151;font-weight:600;white-space:nowrap;}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;}
  tr:hover td{background:#fafbff;}
  tr.sub td{color:#6b7280;background:#fcfcfd;}
  .strong{font-weight:700;color:#111827;}
  .table-wrap{width:100%%;overflow-x:auto;-webkit-overflow-scrolling:touch;border-radius:8px;}
  .charts{display:flex;flex-direction:column;gap:16px;}
  .chart{width:100%%;background:#fff;border:1px solid #eef0f3;border-radius:10px;overflow:hidden;}
  .chart svg{display:block;width:100%%;height:auto;}
  .ctitle{font-size:14px;font-weight:600;fill:#374151;}
  .grid{stroke:#eef0f3;stroke-width:1;}
  .ytick{font-size:10px;fill:#9ca3af;text-anchor:end;}
  .xlabel{font-size:12px;fill:#374151;text-anchor:middle;}
  .barval{font-size:11px;fill:#fff;font-weight:600;}
  .barval-out{font-size:9px;fill:#374151;font-weight:600;}
  .pielbl{font-size:11px;fill:#fff;font-weight:600;text-anchor:middle;}
  .legend{font-size:12px;fill:#6b7280;}
  .donutcenter{font-size:14px;font-weight:700;fill:#111827;text-anchor:middle;}
  .warn{background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;padding:12px 14px;border-radius:10px;font-size:13px;margin-bottom:16px;}
  .warn code{background:#fde9d3;padding:1px 5px;border-radius:4px;}
  .nodata{color:#9ca3af;font-size:13px;}
  .mda{background:#f0f7ff;border:1px solid #dbeafe;color:#1e40af;padding:12px 14px;border-radius:10px;font-size:13px;line-height:1.7;margin:0 0 16px;}
  .mda b{color:#1d4ed8;}
  .note{color:#9ca3af;font-size:12px;margin-top:12px;line-height:1.6;}
  .delta-pos{color:#16a34a;font-weight:600;}
  .delta-neg{color:#dc2626;font-weight:600;}
  .delta-zero{color:#9ca3af;}
  .callout{background:#f0f7ff;border:1px solid #dbeafe;color:#1e40af;padding:10px 12px;border-radius:10px;font-size:13px;line-height:1.7;margin:0 0 14px;}
  .callout b{color:#1d4ed8;}
  tr.latest td{background:#fffbeb;}
  tr.latest:hover td{background:#fff3cd;}
  table.ratios{max-width:520px;}
  .foot{color:#9ca3af;font-size:12px;text-align:center;margin-top:10px;}
  @media (max-width:640px){
    .wrap{padding:16px 12px 40px;}
    h1{font-size:20px;}
    h2{font-size:15px;margin:0 0 10px;}
    .card{padding:14px;margin-bottom:14px;border-radius:10px;}
    .sub{font-size:12px;margin-bottom:14px;}
    table{font-size:12px;min-width:640px;}
    th,td{padding:6px 8px;}
    .mda{font-size:12px;padding:10px 12px;line-height:1.65;}
    .note{font-size:11px;}
    .ctitle{font-size:12px;}
    .ytick{font-size:9px;}
    .xlabel{font-size:10px;}
    .barval,.barval-out{font-size:9px;}
    .pielbl{font-size:9px;}
    .legend{font-size:10px;}
    .donutcenter{font-size:12px;}
  }
</style></head>
<body><div class="wrap">
  <h1>工资条年度汇总报表</h1>
  <div class="sub">自动生成时间：%s ｜ 数据来源：%s</div>
  %s
  <div class="card">
    <h2>可视化</h2>
    <div class="charts">
      %s
      %s
    </div>
  </div>
  <div class="card">
    <h2>年度汇总（收入与支出项）</h2>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>年度</th><th class="num">税前工资<br>收入合计</th><th class="num">养老<br>合计</th><th class="num">医疗<br>合计</th>
          <th class="num">失业<br>合计</th><th class="num">公积金<br>合计</th><th class="num">社保合计<br>(税前支出)</th>
          <th class="num">税费<br>合计</th><th class="num">税后工资<br>合计</th>
        </tr></thead>
        <tbody>%s</tbody>
      </table>
    </div>
  </div>
  %s
  <div class="card">
    <h2>月度明细（当月收入与支出）</h2>
    %s
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>月份</th><th class="num">税前工资<br>收入</th><th class="num">养老<br>保险</th><th class="num">医疗<br>保险</th>
          <th class="num">失业<br>保险</th><th class="num">住房<br>公积金</th><th class="num">社保合计<br>(税前支出)</th>
          <th class="num">个税<br>(税费)</th><th class="num">税后<br>工资</th>
          <th class="num">税前<br>环比</th><th class="num">社保<br>环比</th><th class="num">个税<br>环比</th><th class="num">税后<br>环比</th>
        </tr></thead>
        <tbody>%s</tbody>
      </table>
    </div>
  </div>
  <div class="foot">由 salary_pipeline.py 自动生成 ｜ 单文件离线报表</div>
</div></body></html>
""" % (gen, _esc(cfg["save_dir"]), nodata + err_html,
       svg_swimlane("收入支出泳道图（每段标注金额，税后=自由现金流）", monthly),
       svg_pie("支出项占总收入百分比（结余为自由现金流）", pie_items),
       "".join(arows) or "<tr><td colspan='9' class='nodata'>无数据</td></tr>",
       fin_html,
       callout,
       "".join(mrows) or "<tr><td colspan='13' class='nodata'>无数据</td></tr>")

    with _open_write(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


# ============================================================================
# self-test：用内置样例验证 解析/汇总/HTML 生成（不依赖真实文件）
# ============================================================================
def self_test():
    print("=== self-test 开始 ===")
    sample = {
        "2025-05": {"gross": 24000, "pension": 1900, "medical": 480, "unemployment": 96,
                    "housing":  2880, "social_total": None, "tax": 1400, "net": 17244},
        "2026-06": {"gross": 25000, "pension": 2000, "medical": 500, "unemployment": 100,
                    "housing": 3000, "social_total": None, "tax": 1500, "net": 18400},
        "2026-07": {"gross": 26000, "pension": 2080, "medical": 520, "unemployment": 104,
                    "housing": 3120, "social_total": None, "tax": 1600, "net": 19176},
    }
    monthly = build_monthly(sample)
    annual = build_annual(monthly)
    print("月度条数:", len(monthly), "| 年度条数:", len(annual))
    for a in annual:
        print("  %s: 税前=%s 社保=%s 税费=%s 税后=%s" % (a["year"], _fmt_money(a["gross"]),
              _fmt_money(a["social"]), _fmt_money(a["tax"]), _fmt_money(a["net"])))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "selftest_report.html")
    render_html({"save_dir": "（self-test 样例数据）"}, monthly, annual, [], out)
    print("self-test 报表已生成:", out)
    print("=== self-test 通过 ===")
    return True


# ============================================================================
# CLI
# ============================================================================
def main(argv=None):
    p = argparse.ArgumentParser(description="工资条 / 账单自动处理可复用脚本")
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("fetch", help="抓取附件（工资条/账单，按 sources）")
    pf.add_argument("--dry-run", action="store_true", help="只列出命中邮件，不下载")

    pl = sub.add_parser("list", help="只读列出全部邮件（核对关键词命中），不下载")
    pd_ = sub.add_parser("discover", help="列出文件文本标签以配置 field_map")
    pd_.add_argument("file", help="xls/xlsx 路径")
    pd_.add_argument("--password", default="")

    pa = sub.add_parser("analyze", help="解析本地工资条并生成报表")
    pa.add_argument("--password", default="")

    pr = sub.add_parser("run", help="fetch + analyze")
    pr.add_argument("--dry-run", action="store_true")
    pr.add_argument("--password", default="")

    sub.add_parser("self-test", help="内置样例自测")

    args = p.parse_args(argv)
    cfg = load_config()

    if args.cmd == "fetch":
        fetch_emails(cfg, dry_run=args.dry_run)
    elif args.cmd == "list":
        list_emails(cfg)
    elif args.cmd == "discover":
        pw = resolve_password(cfg, args.password)
        try:
            labels = discover_file(args.file, pw)
            print("文件标签（去重，%d 个）：" % len(labels))
            for t in labels:
                print("  -", t)
        except Exception as e:
            print("无法读取:", e)
    elif args.cmd == "analyze":
        pw = resolve_password(cfg, args.password)
        monthly, annual, errors = analyze_local(cfg, pw)
        write_csv(cfg, monthly, annual)
        out = render_html(cfg, monthly, annual, errors, cfg["analysis"]["report_html"])
        print("报表已生成:", out)
        if errors:
            print("注意：有 %d 个文件解析异常（多为加密未提供密码）。" % len(errors))
    elif args.cmd == "run":
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # 清理上次中断可能遗留的临时文件（避免 云盘 目录里堆积 ._tmp_*.tmp）
        _cleanup_stale(cfg["save_dir"])
        _cleanup_stale(script_dir)
        fetch_emails(cfg, dry_run=args.dry_run)
        if not args.dry_run:
            pw = resolve_password(cfg, args.password)
            monthly, annual, errors = analyze_local(cfg, pw)
            write_csv(cfg, monthly, annual)
            out = render_html(cfg, monthly, annual, errors, cfg["analysis"]["report_html"])
            print("报表已生成:", out)
            # 扩展：解析账单 HTML 并生成收支合并看板
            try:
                import subprocess, sys
                py = sys.executable
                script_dir = os.path.dirname(os.path.abspath(__file__))
                # 用绝对路径 + 显式 cwd 调用，确保同目录的 safe_write 等模块可被 import
                bp = os.path.join(script_dir, "bill_parser.py")
                md = os.path.join(script_dir, "merge_dashboard.py")
                db = os.path.join(script_dir, "dashboard.py")
                print("\n--- 开始解析账单 HTML ---")
                r1 = subprocess.run([py, bp], capture_output=True, text=True, cwd=script_dir)
                print(r1.stdout)
                if r1.returncode != 0:
                    print("bill_parser.py 错误:", r1.stderr)
                print("--- 开始生成收支看板（旧版，兼容保留）---")
                r2 = subprocess.run([py, md], capture_output=True, text=True, cwd=script_dir)
                print(r2.stdout)
                if r2.returncode != 0:
                    print("merge_dashboard.py 错误:", r2.stderr)
                print("--- 开始生成统一单页看板（主交付物）---")
                r3 = subprocess.run([py, db], capture_output=True, text=True, cwd=script_dir)
                print(r3.stdout)
                if r3.returncode != 0:
                    print("dashboard.py 错误:", r3.stderr)
            except Exception as e:
                print("账单/看板扩展流程失败:", e)
    elif args.cmd == "self-test":
        self_test()


if __name__ == "__main__":
    main()
