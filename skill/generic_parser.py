#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置驱动的通用账单解析器
==========================
同事接入自己的银行/机构账单时，只需在 profiles/sources.json 里加一段来源、
改几个正则，无需改动任何 Python 代码。

支持 .html（自动探测 utf-8 / gb18030 / gbk）与 .pdf（PyMuPDF 可选）。
输出结构与 bill_parser.py 完全一致，可直接写入 bills_parsed.csv：
    {source, period, amount, min_payment, cycle, usage, status, file}
"""

import html
import os
import re

ENCODING_ALIAS = {"gb2312": "gb18030", "gbk": "gb18030", "utf8": "utf-8"}


def _read_text(path):
    """读成纯文本；HTML 去标签并反转义实体，PDF 逐页提取。"""
    low = path.lower()
    if low.endswith(".pdf"):
        try:
            import fitz
            with fitz.open(path) as doc:
                return "\n".join(page.get_text() for page in doc)
        except ImportError:
            return ""
        except Exception:
            return ""

    raw = open(path, "rb").read()
    declared = None
    m = re.search(br'charset\s*=\s*["\']?([a-zA-Z0-9_-]+)', raw[:4096], re.IGNORECASE)
    if m:
        declared = m.group(1).decode("ascii", "ignore").lower()
    candidates = []
    if declared:
        candidates.append(ENCODING_ALIAS.get(declared, declared))
    candidates += ["utf-8", "gb18030", "gbk", "latin-1"]

    text = ""
    for enc in candidates:
        try:
            t = raw.decode(enc, "replace")
            if enc == "utf-8" and t.count("\ufffd") > max(5, len(t) * 0.001):
                continue
            text = t
            break
        except Exception:
            continue
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _period_from(filename, text):
    """月份优先取文件名 YYYY-MM / YYYYMM，其次从正文账单周期推断。"""
    m = re.search(r"(20\d{2})[-_年]?(0[1-9]|1[0-2])", filename)
    if m:
        return "%s-%s" % (m.group(1), m.group(2))
    m = re.search(r"(20\d{2})[-/年](0?[1-9]|1[0-2])[-/月]", text)
    if m:
        return "%s-%02d" % (m.group(1), int(m.group(2)))
    return "unknown"


def _to_float(s):
    if not s:
        return None
    try:
        return float(str(s).replace(",", "").replace("¥", "").replace("￥", "").strip())
    except (TypeError, ValueError):
        return None


def parse(path, profile):
    """按 profile.parser.patterns 中的正则提取字段，返回一条标准账单记录。"""
    text = _read_text(path)
    patterns = (profile.get("parser") or {}).get("patterns", {}) or {}

    def grab(key):
        pat = patterns.get(key)
        if not pat:
            return None
        try:
            m = re.search(pat, text, re.IGNORECASE)
        except re.error:
            return None
        if not m:
            return None
        value = m.group(1) if m.lastindex else m.group(0)
        return value.strip() if value else None

    amount = _to_float(grab("amount"))
    usage_raw = grab("usage")
    usage = _to_float(usage_raw)
    period_pattern = patterns.get("period")

    period = _period_from(os.path.basename(path), text)
    if period_pattern:
        try:
            m = re.search(period_pattern, text, re.IGNORECASE)
            if m:
                period = (m.group(1) if m.lastindex else m.group(0)).strip()
        except re.error:
            pass

    return {
        "source": profile.get("label") or profile.get("name") or "未命名来源",
        "period": period,
        "amount": amount,
        "min_payment": grab("min_payment"),
        "cycle": grab("cycle"),
        "usage": usage if usage is not None else usage_raw,
        "status": "已提取" if amount is not None else "未匹配到金额（检查正则）",
        "file": os.path.basename(path),
    }
