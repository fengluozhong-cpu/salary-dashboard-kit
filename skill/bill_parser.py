#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
账单 HTML 解析器：从各银行/电网内联 HTML 中提取核心支出字段
================================================================
支持自动编码检测（utf-8 / gb18030 / gbk），按来源关键词启发式提取。
产出 bills_parsed.csv（来源, 月份, 应还金额, 最低还款额, 账单周期, 状态, 原始文件）。
"""

import os, re, csv, html, sys
from datetime import datetime

# 确保同目录的 safe_write 可被 import（无论从哪个 cwd 启动）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from safe_write import open_write  # 抗 云盘 同步锁的稳健写

from app_config import paths as _paths
SAVE_DIR = _paths()["data_dir"]
BILLS_DIR = _paths()["bills_dir"]


def _read_html(path):
    """读取 HTML，优先根据 meta charset 声明选择编码，其次按 utf-8 -> gb18030 -> gbk -> latin-1 回退。"""
    raw = open(path, "rb").read()
    # 从 meta/http-equiv 提取 charset
    declared = None
    m = re.search(br'charset\s*=\s*["\']?([a-zA-Z0-9_-]+)', raw[:4096], re.IGNORECASE)
    if m:
        declared = m.group(1).decode("ascii", "ignore").lower()
    if declared:
        # 常见别名统一
        alias = {"gb2312": "gb18030", "gbk": "gb18030", "utf8": "utf-8"}
        enc = alias.get(declared, declared)
        try:
            return raw.decode(enc), enc
        except Exception:
            pass
    # 回退：utf-8 先尝试严格模式，若含大量替换符则视为失败
    for enc in ("utf-8", "gb18030", "gbk", "latin-1"):
        try:
            text = raw.decode(enc, "replace")
            # 启发式：若替换符占比过高，跳过 utf-8（常见 gbk 被误当 utf-8）
            if enc == "utf-8" and text.count('\ufffd') > max(5, len(text) * 0.001):
                continue
            return text, enc
        except Exception:
            continue
    return raw.decode("utf-8", "replace"), "utf-8-fallback"


def _strip_html(text):
    """去标签、去多余空白。

    必须先 html.unescape：银行账单常用 HTML 实体表示金额符号（如 CMB 用 &yen; 表示 ¥）。
    若只按实体占位（如 &yen;）替换成空格而不反转义，会丢失 ¥ 符号，
    导致依赖该符号的金额正则匹配失败。
    """
    t = html.unescape(text)
    t = re.sub(r'<[^>]+>', ' ', t)
    t = re.sub(r'\s+', ' ', t)
    return t.strip()


def _parse_cmb(path):
    """招商银行信用卡：从汇总表提取 信用额度 / 本期应还金额 / 最低还款额 / 到期还款日。

    重要坑：CMB 内联 HTML 中“本期应还金额”字样**只出现在底部“溢缴款”说明 footnote**
    （“若您的…本期应还金额为负数…溢缴款…¥0.00”），而真正的数值在顶部汇总表单元格里，
    附近没有“本期应还金额”文字标签。若按“本期应还金额 附近数字”提取，会误抓到
    footnote 的 ¥0.00 而判为“溢缴款（无需还款）”——这是此前把招行账单错判为 0.00 的根因。

    正确做法：用结构化汇总行（账单周期 + 三个 ¥ 金额 + 到期日）整体匹配，例如线性化后：
        2026/07/19-2026/08/18 ¥ 38,000.00 ¥ 3,408.60 ¥ 3,361.28 2026/09/06
    含义：账单周期 | 信用额度 | 本期应还金额 | 最低还款额 | 到期还款日
    """
    text, enc = _read_html(path)
    plain = _strip_html(text)
    plain = re.sub(r'[ \t]+', ' ', plain)

    fn = os.path.basename(path)
    fm = re.search(r'(\d{4})-(\d{2})', fn)
    period = "%s-%s" % (fm.group(1), fm.group(2)) if fm else "unknown"

    amount = None
    min_payment = None
    cycle = None
    status = "需OCR/图片型"

    # 结构化汇总行：账单周期(起-止) 信用额度 本期应还金额 最低还款额 到期还款日
    m = re.search(
        r'(\d{4}/\d{2}/\d{2})-(\d{4}/\d{2}/\d{2})\s*'
        r'[¥￥]\s*([0-9,]+\.[0-9]{2})\s*'
        r'[¥￥]\s*([0-9,]+\.[0-9]{2})\s*'
        r'[¥￥]\s*([0-9,]+\.[0-9]{2})\s*'
        r'(\d{4}/\d{2}/\d{2})',
        plain)
    if m:
        cycle = "%s ~ %s" % (m.group(1), m.group(2))
        # group(3)=信用额度, (4)=本期应还金额, (5)=最低还款额
        amount = m.group(4)
        min_payment = m.group(5)
        status = "已提取"

    return {
        "source": "招商银行信用卡",
        "period": period,
        "amount": amount,
        "min_payment": min_payment,
        "cycle": cycle,
        "status": status if amount else "需OCR/图片型",
        "file": os.path.basename(path),
    }


def _parse_cgb(path):
    """广发银行信用卡：文本较规范，可精确提取。"""
    text, enc = _read_html(path)
    plain = _strip_html(text)

    fn = os.path.basename(path)
    fm = re.search(r'(\d{4})-(\d{2})', fn)
    period = "%s-%s" % (fm.group(1), fm.group(2)) if fm else "unknown"

    amount = None
    min_payment = None
    cycle = None
    status = "需OCR"

    # 账单周期
    cm = re.search(r'账单周期[:：]\s*(\d{4}/\d{2}/\d{2})\s*-\s*(\d{4}/\d{2}/\d{2})', plain)
    if cm:
        cycle = "%s ~ %s" % (cm.group(1), cm.group(2))

    # 广发格式1: 表格头 "卡号末四位 本期账单金额 最低还款额 最后还款日 入账货币 存款 卡片消费额度 5721 243.77 100.00 ..."
    m = re.search(
        r'卡号末四位.*?本期账单金额.*?最低还款额.*?最后还款日.*?入账货币.*?存款.*?卡片消费额度\s+(\d{4})\s+([0-9,]+\.[0-9]{2})\s+([0-9,]+\.[0-9]{2})',
        plain)
    if m:
        amount = m.group(2)
        min_payment = m.group(3)
    else:
        # fallback: 在"本期账单金额"附近50字符内找第一个合理的金额（排除额度大数字）
        for hit in re.finditer(r'本期账单金额.{0,50}', plain):
            nums = re.findall(r'([0-9,]+\.[0-9]{2})', hit.group())
            for n in nums:
                val = float(n.replace(",", ""))
                if 0 < val < 50000:  # 排除额度
                    amount = n
                    break
            if amount:
                break

    if amount and not min_payment:
        mm = re.search(r'最低还款额[:：]?\s*([0-9,]+\.[0-9]{2})', plain)
        if mm:
            min_payment = mm.group(1)

    if amount:
        status = "已提取"

    return {
        "source": "广发银行信用卡",
        "period": period,
        "amount": amount,
        "min_payment": min_payment,
        "cycle": cycle,
        "status": status,
        "file": os.path.basename(path),
    }


def _parse_citic(path):
    """中信银行信用卡：文本非常规范。"""
    text, enc = _read_html(path)
    plain = _strip_html(text)

    fn = os.path.basename(path)
    fm = re.search(r'(\d{4})-(\d{2})', fn)
    period = "%s-%s" % (fm.group(1), fm.group(2)) if fm else "unknown"

    amount = None
    min_payment = None
    cycle = None
    status = "需OCR"

    # 账单日 / 到期还款日可视为周期锚点
    dm = re.search(r'账单日[:：]?\s*(\d{4}年\d{2}月\d{2}日)', plain)
    dd = re.search(r'到期还款日[:：]?\s*(\d{4}年\d{2}月\d{2}日)', plain)
    if dm and dd:
        cycle = "%s ~ %s" % (dm.group(1), dd.group(1))
    elif dm:
        cycle = dm.group(1)

    # 本期应还款总额
    am = re.search(r'本期应还款总额\s*CNY\s*([0-9,]+\.[0-9]{2})', plain)
    if am:
        amount = am.group(1)
    else:
        am2 = re.search(r'应还款总额[:：]?\s*([0-9,]+\.[0-9]{2})', plain)
        if am2:
            amount = am2.group(1)

    # 最低还款额
    mm = re.search(r'本期最低还款额\s*CNY\s*([0-9,]+\.[0-9]{2})', plain)
    if mm:
        min_payment = mm.group(1)
    else:
        mm2 = re.search(r'最低还款额[:：]?\s*([0-9,]+\.[0-9]{2})', plain)
        if mm2:
            min_payment = mm2.group(1)

    if amount:
        status = "已提取"

    return {
        "source": "中信银行信用卡",
        "period": period,
        "amount": amount,
        "min_payment": min_payment,
        "cycle": cycle,
        "status": status,
        "file": os.path.basename(path),
    }


def _parse_electricity(path):
    """电费账单：多为图片型/base64，文本提取困难。"""
    text, enc = _read_html(path)
    plain = _strip_html(text)

    fn = os.path.basename(path)
    fm = re.search(r'(\d{4})-(\d{2})', fn)
    period = "%s-%s" % (fm.group(1), fm.group(2)) if fm else "unknown"

    # 极少数字文本，尝试搜索
    amount = None
    usage = None
    status = "需OCR/图片型"

    # 若存在文本金额（极少数情况）
    for m in re.finditer(r'.{0,30}(?:电费|金额|合计|总价).{0,30}', plain):
        nums = re.findall(r'[0-9,]+\.[0-9]{2}', m.group())
        if nums:
            amount = nums[0]
            status = "已提取（模糊）"
            break

    # 尝试搜用电量（度/kWh）
    um = re.search(r'(\d+(?:\.\d+)?)\s*(?:度|kWh|千瓦时)', plain)
    if um:
        usage = um.group(1)

    return {
        "source": "电费账单",
        "period": period,
        "amount": amount,
        "min_payment": None,
        "cycle": None,
        "usage": usage,
        "status": status,
        "file": os.path.basename(path),
    }


def _parse_electricity_pdf(path):
    """解析电子发票 PDF，提取电费金额、用电量、计费时段、行码。

    发票文本形如：
      价税合计（大写）... （小写）¥225.83
      *售电*电费（计费时段：20260701-20260731） 居民生活 千瓦时 374.2 0.5264029931 196.98 13% 25.61
    """
    period = None
    fn = os.path.basename(path)
    fm = re.search(r'(\d{4})-(\d{2})', fn)
    if fm:
        period = "%s-%s" % (fm.group(1), fm.group(2))

    amount = None
    usage = None
    cycle = None
    status = "需OCR"

    try:
        import fitz  # PyMuPDF
    except ImportError:
        # 退化：尝试从文件名解析金额（南方电网文件名含金额，如 202607_示例用户_225.83_xxx.pdf）
        m = re.search(r'_([0-9]+\.[0-9]{2})_', fn)
        if m:
            return {
                "source": "电费账单", "period": period or "unknown", "amount": m.group(1),
                "min_payment": None, "cycle": None, "usage": None,
                "status": "已提取（文件名）", "file": fn,
            }
        return {
            "source": "电费账单", "period": period or "unknown", "amount": None,
            "min_payment": None, "cycle": None, "usage": None,
            "status": "缺少 PDF 库(pymupdf)", "file": fn,
        }

    try:
        doc = fitz.open(path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
    except Exception as e:
        return {
            "source": "电费账单", "period": period or "unknown", "amount": None,
            "min_payment": None, "cycle": None, "usage": None,
            "status": "PDF读取失败: %s" % e, "file": fn,
        }

    flat = re.sub(r'\s+', ' ', text)

    # 价税合计（小写）¥225.83
    m = re.search(r'（小写）\s*[¥￥]\s*([0-9,]+\.[0-9]{2})', flat)
    if not m:
        m = re.search(r'价税合计.{0,20}?[¥￥]\s*([0-9,]+\.[0-9]{2})', flat)
    if not m:
        m = re.search(r'本次实收[:：]?\s*([0-9,]+\.[0-9]{2})', flat)
    if m:
        amount = m.group(1)

    # 用电量：数量列 "千瓦时 374.2 0.5264029931"
    m = re.search(r'千瓦时\s+([0-9]+(?:\.[0-9]+)?)', flat)
    if m:
        usage = m.group(1)

    # 计费时段 20260701-20260731 或 20260701-20260731
    m = re.search(r'(\d{8})\s*-\s*(\d{8})', flat)
    if m:
        a, b = m.group(1), m.group(2)
        cycle = "%s-%s-%s ~ %s-%s-%s" % (a[:4], a[4:6], a[6:], b[:4], b[4:6], b[6:])

    if amount:
        status = "已提取"

    return {
        "source": "电费账单",
        "period": period or "unknown",
        "amount": amount,
        "min_payment": None,
        "cycle": cycle,
        "usage": usage,
        "status": status,
        "file": fn,
    }


def _parse_cib_pdf(path):
    """兴业银行信用卡「信用卡历史账单」PDF：一个 PDF 含多期账单（每页一期），返回**多条**记录。

    页面结构（每页独立，空白 flatten 后）：
        账单日 STATEMENT DATE 2026年07月16日
        到期还款日 PAYMENT DUEDATE 2026年08月05日
        本期应还款总额NEW BALANCE RMB 428.49
        最低还款额 MINIMUM PAYMENY RMB 50.00
        ... 兴业银行信用卡对账单 (份) 2026年07月 ...

    坑记录：
      1) 兴业把 MINIMUM PAYMENT 错拼成 "MINIMUM PAYMENY"（少一个 T），正则必须按实际文本写。
      2) 邮件主题形如「兴业银行信用卡[202606-202609]电子账单」是**连续数字区间**，
         文件名只能回退到邮件日期（如 2026-09），真实账单月必须由 PDF 内容决定，不能信文件名。
    """
    fn = os.path.basename(path)

    def _err(status):
        return [{
            "source": "兴业银行信用卡", "period": "unknown", "amount": None,
            "min_payment": None, "cycle": None, "usage": None,
            "status": status, "file": fn,
        }]

    try:
        import fitz  # PyMuPDF
    except ImportError:
        return _err("缺少 PDF 库(pymupdf)")

    try:
        doc = fitz.open(path)
    except Exception as e:
        return _err("PDF读取失败: %s" % e)

    out = []
    for page in doc:
        flat = re.sub(r'\s+', ' ', page.get_text())

        am = re.search(r'本期应还款总额\s*NEW BALANCE\s*RMB\s*([0-9,]+\.[0-9]{2})', flat)
        mm = re.search(r'最低还款额\s*MINIMUM PAYMENY\s*RMB\s*([0-9,]+\.[0-9]{2})', flat)
        sd = re.search(r'账单日\s*STATEMENT DATE\s*(\d{4})年(\d{1,2})月(\d{1,2})日', flat)
        dd = re.search(r'到期还款日\s*PAYMENT DUEDATE\s*(\d{4})年(\d{1,2})月(\d{1,2})日', flat)

        amount = am.group(1) if am else None
        minpay = mm.group(1) if mm else None

        # 账单月优先取账单日所在月；退化取正文「兴业银行信用卡对账单 ... 2026年07月」
        period = None
        if sd:
            period = "%s-%02d" % (sd.group(1), int(sd.group(2)))
        else:
            pm = re.search(r'兴业银行信用卡对账单.{0,12}?(\d{4})年(\d{1,2})月', flat)
            if pm:
                period = "%s-%02d" % (pm.group(1), int(pm.group(2)))

        cycle = None
        if sd and dd:
            cycle = "%s-%s-%s ~ %s-%s-%s" % (sd.group(1), sd.group(2), sd.group(3),
                                             dd.group(1), dd.group(2), dd.group(3))

        if amount is None and period is None:
            continue  # 非账单页（封面/说明页）

        out.append({
            "source": "兴业银行信用卡",
            "period": period or "unknown",
            "amount": amount,
            "min_payment": minpay,
            "cycle": cycle,
            "usage": None,
            "status": "已提取" if amount else "未提取到金额",
            "file": fn,
        })
    doc.close()

    if not out:
        return _err("PDF 中未识别到账单页")
    return out


PARSERS = {
    "cmb": _parse_cmb,
    "cgb": _parse_cgb,
    "citic": _parse_citic,
    "cib": _parse_cib_pdf,
    "electricity": _parse_electricity,
}

# 按扩展名分流（PDF 优先走专门的解析器）
PDF_PARSERS = {
    "electricity": _parse_electricity_pdf,
    "cib": _parse_cib_pdf,
}


def parse_all_bills():
    rows = []
    if not os.path.isdir(BILLS_DIR):
        print("账单目录不存在:", BILLS_DIR)
        return rows

    # 配置驱动来源：profiles/sources.json 中 type=generic 的来源按子目录名匹配。
    # 同事接入自己的账单只需改那份 JSON，不必改本文件。
    from app_config import load_profiles
    from generic_parser import parse as generic_parse
    generic_map = {}
    for prof in load_profiles():
        if (prof.get("parser") or {}).get("type") == "generic":
            key = os.path.basename(os.path.normpath(
                prof.get("save_subdir") or prof.get("name") or ""))
            if key:
                generic_map[key] = prof

    for subdir in os.listdir(BILLS_DIR):
        parser = PARSERS.get(subdir)
        profile = generic_map.get(subdir)
        if not parser and not profile:
            continue
        full_sub = os.path.join(BILLS_DIR, subdir)
        if not os.path.isdir(full_sub):
            continue
        for fn in sorted(os.listdir(full_sub)):
            low = fn.lower()
            if low.endswith(".pdf"):
                # PDF 走专门的解析器（如电子发票）
                pdf_parser = PDF_PARSERS.get(subdir)
                chosen = pdf_parser or parser
            elif low.endswith(".html"):
                chosen = parser
            else:
                continue
            path = os.path.join(full_sub, fn)
            try:
                res = generic_parse(path, profile) if profile else chosen(path)
                # 兴业「历史账单」PDF 一页一期，解析器返回 list；其余解析器返回单个 dict
                recs = res if isinstance(res, list) else [res]
                for rec in recs:
                    rec.setdefault("usage", None)
                    rows.append(rec)
                    extra = (" | 用电量=%s" % rec["usage"]) if rec.get("usage") else ""
                    print("[解析] %s | %s | 金额=%s%s | 状态=%s" % (
                        rec["source"], rec["period"], rec["amount"], extra, rec["status"]))
            except Exception as e:
                print("[错误] %s: %s" % (fn, e))
                rows.append({
                    "source": subdir,
                    "period": "unknown",
                    "amount": None,
                    "min_payment": None,
                    "cycle": None,
                    "usage": None,
                    "status": "解析异常: %s" % e,
                    "file": fn,
                })
    return rows


def dedupe_rows(rows):
    """去重：同一 (来源, 月份) 若已有成功提取的记录，则剔除该组下解析失败的正文/图片型记录。

    典型场景（南方电网）：同一封邮件既有纯文本提示正文（无金额），又有 PDF 电子发票（含金额）。
    两者会被各自解析成一条记录，导致同一笔电费被记两次（一次 None、一次真实金额）。
    """
    ok_keys = set()
    for r in rows:
        if r.get("amount"):
            ok_keys.add((r["source"], r["period"]))
    out = []
    dropped = 0
    for r in rows:
        key = (r["source"], r["period"])
        if not r.get("amount") and key in ok_keys:
            dropped += 1
            continue
        out.append(r)
    if dropped:
        print("（去重）剔除 %d 条同月重复且未提取到金额的记录" % dropped)
    return out


def write_parsed_csv(rows):
    path = os.path.join(SAVE_DIR, "bills_parsed.csv")
    with open_write(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["来源", "月份", "应还金额", "最低还款额", "账单周期", "用电量", "状态", "原始文件"])
        for r in rows:
            w.writerow([
                r["source"], r["period"], r["amount"] or "",
                r["min_payment"] or "", r["cycle"] or "",
                r.get("usage") or "", r["status"], r["file"],
            ])
    print("\n已写入:", path)
    return path


if __name__ == "__main__":
    rows = dedupe_rows(parse_all_bills())
    if rows:
        write_parsed_csv(rows)
    else:
        print("未找到可解析的账单 HTML/PDF。")
