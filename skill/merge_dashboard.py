#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
收入-支出合并看板生成器
========================
读取工资年度汇总.csv + bills_parsed.csv，按月份合并收入与支出，
生成自包含 HTML 看板（内联 SVG 图表）。
"""

import os, re, csv, html, math, sys
from collections import defaultdict
from datetime import datetime

# 确保同目录的 safe_write 可被 import（无论从哪个 cwd 启动）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from safe_write import open_write  # 抗 云盘 同步锁的稳健写

from app_config import paths as _paths
SAVE_DIR = _paths()["data_dir"]
SALARY_CSV = _paths()["salary_csv"]
BILLS_CSV = _paths()["bills_csv"]
OUT_HTML = _paths()["legacy_dashboard_html"]


def _read_salary():
    """读取工资月度数据，返回 {period: {income, tax, social, net}}。"""
    rows = []
    if not os.path.exists(SALARY_CSV):
        return rows
    with open(SALARY_CSV, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.reader(f):
            if not r or r[0] != "月度":
                continue
            rows.append({
                "period": r[1],
                "gross": float(r[2].replace(",", "")) if r[2] else 0,
                "social": float(r[7].replace(",", "")) if r[7] else 0,
                "tax": float(r[8].replace(",", "")) if r[8] else 0,
                "net": float(r[9].replace(",", "")) if r[9] else 0,
            })
    return rows


def _read_bills():
    """读取账单解析结果，返回 {period: [amount, ...]}。"""
    rows = []
    if not os.path.exists(BILLS_CSV):
        return rows
    with open(BILLS_CSV, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.reader(f):
            if not r or r[0] == "来源":
                continue
            amt = r[2].replace(",", "") if len(r) > 2 and r[2] else ""
            rows.append({
                "source": r[0],
                "period": r[1],
                "amount": float(amt) if amt else 0.0,
                # 列顺序: 来源,月份,应还金额,最低还款额,账单周期,用电量,状态,原始文件
                "usage": r[5] if len(r) > 5 else "",
                "status": r[6] if len(r) > 6 else "",
            })
    return rows


def _fmt(v):
    return "{:,.2f}".format(v)


def _bar_chart(data, w=640, h=280):
    """生成收入/支出并列柱状图 SVG。data: [(period, income, expense), ...]。"""
    if not data:
        return ""
    n = len(data)
    margin = {"top": 30, "right": 20, "bottom": 60, "left": 60}
    cw = w - margin["left"] - margin["right"]
    ch = h - margin["top"] - margin["bottom"]
    max_val = max(max(i, e) for _, i, e in data) * 1.1
    if max_val == 0:
        max_val = 1

    bar_w = cw / (n * 2.5)
    gap = bar_w * 0.5

    parts = ["<svg viewBox='0 0 %d %d' class='chart' xmlns='http://www.w3.org/2000/svg'>" % (w, h)]
    # 背景
    parts.append("<rect width='%d' height='%d' fill='#1e293b' rx='8'/>" % (w, h))

    # Y轴网格线
    for i in range(6):
        y = margin["top"] + ch * i / 5
        val = max_val * (5 - i) / 5
        parts.append("<line x1='%d' y1='%d' x2='%d' y2='%d' stroke='#334155' stroke-width='1'/>" % (
            margin["left"], int(y), w - margin["right"], int(y)))
        parts.append("<text x='%d' y='%d' fill='#94a3b8' font-size='10' text-anchor='end'>%s</text>" % (
            margin["left"] - 6, int(y) + 4, _fmt(val)))

    # 柱子
    colors = {"income": "#34d399", "expense": "#f87171"}
    for idx, (period, income, expense) in enumerate(data):
        x0 = margin["left"] + gap / 2 + idx * (bar_w * 2 + gap)
        # 收入柱
        ih = income / max_val * ch
        iy = margin["top"] + ch - ih
        parts.append("<rect x='%d' y='%d' width='%d' height='%d' fill='%s' rx='3'/>" % (
            int(x0), int(iy), int(bar_w), int(ih), colors["income"]))
        # 收入标签
        if ih > 18:
            parts.append("<text x='%d' y='%d' fill='#0f172a' font-size='10' text-anchor='middle' font-weight='600'>%s</text>" % (
                int(x0 + bar_w / 2), int(iy + 14), _fmt(income)))
        else:
            parts.append("<text x='%d' y='%d' fill='#34d399' font-size='10' text-anchor='middle' font-weight='600'>%s</text>" % (
                int(x0 + bar_w / 2), int(iy) - 4, _fmt(income)))

        # 支出柱
        eh = expense / max_val * ch
        ey = margin["top"] + ch - eh
        parts.append("<rect x='%d' y='%d' width='%d' height='%d' fill='%s' rx='3'/>" % (
            int(x0 + bar_w), int(ey), int(bar_w), int(eh), colors["expense"]))
        if eh > 18:
            parts.append("<text x='%d' y='%d' fill='#0f172a' font-size='10' text-anchor='middle' font-weight='600'>%s</text>" % (
                int(x0 + bar_w * 1.5), int(ey + 14), _fmt(expense)))
        else:
            parts.append("<text x='%d' y='%d' fill='#f87171' font-size='10' text-anchor='middle' font-weight='600'>%s</text>" % (
                int(x0 + bar_w * 1.5), int(ey) - 4, _fmt(expense)))

        # X轴标签
        parts.append("<text x='%d' y='%d' fill='#cbd5e1' font-size='11' text-anchor='middle'>%s</text>" % (
            int(x0 + bar_w), h - 20, period))

    # 图例
    parts.append("<rect x='%d' y='%d' width='12' height='12' fill='%s' rx='2'/>" % (w - 140, 10, colors["income"]))
    parts.append("<text x='%d' y='%d' fill='#e2e8f0' font-size='11'>收入（税后工资）</text>" % (w - 124, 21))
    parts.append("<rect x='%d' y='%d' width='12' height='12' fill='%s' rx='2'/>" % (w - 140, 26, colors["expense"]))
    parts.append("<text x='%d' y='%d' fill='#e2e8f0' font-size='11'>支出（信用卡+电费）</text>" % (w - 124, 37))

    parts.append("</svg>")
    return "\n".join(parts)


def _pie_chart(items, w=320, h=280):
    """支出构成饼图。items: [(label, value, color), ...]。"""
    if not items:
        return ""
    total = sum(v for _, v, _ in items)
    if total <= 0:
        return ""
    cx, cy = w // 2, h // 2 + 10
    r = min(cx, cy) - 30
    parts = ["<svg viewBox='0 0 %d %d' class='chart' xmlns='http://www.w3.org/2000/svg'>" % (w, h)]
    parts.append("<rect width='%d' height='%d' fill='#1e293b' rx='8'/>" % (w, h))
    start = 0
    for label, value, color in items:
        angle = value / total * 360
        if angle > 0:
            x1 = cx + r * math.cos(math.radians(start))
            y1 = cy + r * math.sin(math.radians(start))
            x2 = cx + r * math.cos(math.radians(start + angle))
            y2 = cy + r * math.sin(math.radians(start + angle))
            large = 1 if angle > 180 else 0
            path = "M %d %d L %d %d A %d %d 0 %d 1 %d %d Z" % (cx, cy, x1, y1, r, r, large, x2, y2)
            parts.append("<path d='%s' fill='%s' stroke='#1e293b' stroke-width='2'/>" % (path, color))
            # 标签
            mid = start + angle / 2
            lx = cx + (r * 0.65) * math.cos(math.radians(mid))
            ly = cy + (r * 0.65) * math.sin(math.radians(mid))
            parts.append("<text x='%d' y='%d' fill='#fff' font-size='10' text-anchor='middle' font-weight='600'>%s%%</text>" % (
                int(lx), int(ly) + 4, int(value / total * 100)))
            start += angle
    # 图例
    y0 = 16
    for label, value, color in items:
        parts.append("<rect x='12' y='%d' width='10' height='10' fill='%s' rx='2'/>" % (y0, color))
        parts.append("<text x='28' y='%d' fill='#cbd5e1' font-size='11'>%s %s</text>" % (y0 + 9, label, _fmt(value)))
        y0 += 18
    parts.append("</svg>")
    return "\n".join(parts)


def _build_note(bill_rows):
    """根据 bills_parsed.csv 的状态生成数据驱动的脚注，避免硬编码'招行溢缴款'这类会过时的文案。"""
    parts = ["税后收入来自 工资条汇总；信用卡/电费支出来自邮箱抓取的电子账单 HTML/PDF 自动解析"]
    pending = []
    for r in bill_rows:
        if r["status"].startswith("需OCR") or "溢缴款" in r["status"]:
            pending.append("%s（%s）" % (r["source"], r["status"]))
    if pending:
        parts.append("；待确认项：%s" % "，".join(pending))
    parts.append("；用电量来自电子发票 PDF 自动解析")
    return "注：" + "".join(parts) + "。"


def _render_dashboard(salary_rows, bill_rows):
    # 合并数据
    all_periods = set()
    for r in salary_rows:
        all_periods.add(r["period"])
    for r in bill_rows:
        all_periods.add(r["period"])

    # 收入按期间汇总
    income_by_period = defaultdict(float)
    for r in salary_rows:
        income_by_period[r["period"]] = r["net"]

    # 支出按期间/来源汇总
    expense_by_period = defaultdict(lambda: defaultdict(float))
    usage_by_period = {}
    for r in bill_rows:
        if r["amount"] > 0:
            expense_by_period[r["period"]][r["source"]] += r["amount"]
        # 记录用电量（电费账单）
        if r.get("usage"):
            try:
                usage_by_period[r["period"]] = float(r["usage"])
            except (TypeError, ValueError):
                pass

    periods = sorted(all_periods)
    merged = []
    for p in periods:
        inc = income_by_period.get(p, 0.0)
        exp_dict = expense_by_period.get(p, {})
        exp = sum(exp_dict.values())
        merged.append({
            "period": p,
            "income": inc,
            "expense": exp,
            "balance": inc - exp,
            "sources": exp_dict,
            "usage": usage_by_period.get(p),
        })

    # 图表数据
    chart_data = [(m["period"], m["income"], m["expense"]) for m in merged]

    # 支出构成（全期汇总）
    total_by_source = defaultdict(float)
    for r in bill_rows:
        if r["amount"] > 0:
            total_by_source[r["source"]] += r["amount"]
    pie_colors = {"招商银行信用卡": "#60a5fa", "广发银行信用卡": "#f472b6", "中信银行信用卡": "#a78bfa", "电费账单": "#fbbf24"}
    pie_items = []
    for src, val in sorted(total_by_source.items(), key=lambda x: -x[1]):
        pie_items.append((src, val, pie_colors.get(src, "#94a3b8")))

    # 年度汇总
    total_income = sum(m["income"] for m in merged)
    total_expense = sum(m["expense"] for m in merged)
    total_balance = total_income - total_expense
    savings_rate = (total_balance / total_income * 100) if total_income > 0 else 0

    # HTML 组装
    head = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>收入-支出看板</title>
<style>
:root {{ color-scheme: dark light; }}
body {{ font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif; margin:20px; background:#0f172a; color:#e2e8f0; }}
h1 {{ font-size:22px; margin-bottom:6px; }}
.meta {{ color:#94a3b8; font-size:13px; margin-bottom:18px; }}
.grid {{ display:grid; grid-template-columns: 1.6fr 1fr; gap:16px; margin-bottom:16px; }}
@media (max-width:720px) {{ .grid {{ grid-template-columns: 1fr; }} }}
.card {{ background:#1e293b; border-radius:12px; padding:16px; }}
.card h2 {{ font-size:16px; margin:0 0 12px; color:#38bdf8; }}
.chart {{ width:100%; height:auto; display:block; }}
.summary {{ display:grid; grid-template-columns: repeat(3, 1fr); gap:12px; margin-bottom:16px; }}
@media (max-width:640px) {{ .summary {{ grid-template-columns: 1fr; }} }}
.kpi {{ background:#1e293b; border-radius:12px; padding:16px; text-align:center; }}
.kpi .label {{ color:#94a3b8; font-size:12px; margin-bottom:6px; }}
.kpi .value {{ font-size:22px; font-weight:700; }}
.kpi.pos {{ border-left:4px solid #34d399; }}
.kpi.neg {{ border-left:4px solid #f87171; }}
.kpi.neu {{ border-left:4px solid #60a5fa; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ text-align:left; color:#94a3b8; font-weight:600; padding:8px 4px; border-bottom:1px solid #334155; }}
td {{ padding:8px 4px; border-bottom:1px solid #334155; }}
tr:last-child td {{ border-bottom:none; }}
.num {{ text-align:right; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
.income {{ color:#34d399; }}
.expense {{ color:#f87171; }}
.balance {{ color:#fbbf24; }}
.note {{ color:#94a3b8; font-size:12px; margin-top:8px; }}
</style>
</head>
<body>
<h1>收入-支出看板</h1>
<div class="meta">生成时间: {ts} | 数据范围: {periods}</div>
""".format(ts=datetime.now().strftime("%Y-%m-%d %H:%M"), periods=" ~ ".join([periods[0], periods[-1]]) if periods else "-")

    parts = [head]

    # 核心指标
    parts.append("<div class='summary'>")
    parts.append("<div class='kpi pos'><div class='label'>累计收入（税后）</div><div class='value income'>¥%s</div></div>" % _fmt(total_income))
    parts.append("<div class='kpi neg'><div class='label'>累计支出（账单）</div><div class='value expense'>¥%s</div></div>" % _fmt(total_expense))
    parts.append("<div class='kpi neu'><div class='label'>结余 / 储蓄率</div><div class='value balance'>¥%s (%.1f%%)</div></div>" % (_fmt(total_balance), savings_rate))
    parts.append("</div>")

    # 可视化
    parts.append("<div class='grid'>")
    parts.append("<div class='card'><h2>月度收支对比</h2>%s</div>" % _bar_chart(chart_data))
    import math
    parts.append("<div class='card'><h2>支出构成</h2>%s</div>" % _pie_chart(pie_items))
    parts.append("</div>")

    # 明细表
    parts.append("<div class='card'><h2>月度明细</h2>")
    parts.append("<div class='table-wrap'><table><tr><th>月份</th><th class='num'>税后收入</th><th class='num'>信用卡/电费支出</th><th class='num'>结余</th><th class='num'>用电量(kWh)</th><th>支出明细</th></tr>")
    for m in merged:
        src_str = "; ".join(["%s ¥%s" % (s, _fmt(v)) for s, v in sorted(m["sources"].items())]) or "—"
        usage_str = m.get("usage") or "—"
        parts.append("<tr><td>%s</td><td class='num income'>%s</td><td class='num expense'>%s</td><td class='num balance'>%s</td><td class='num'>%s</td><td>%s</td></tr>" % (
            m["period"], _fmt(m["income"]) if m["income"] else "—",
            _fmt(m["expense"]) if m["expense"] else "—",
            _fmt(m["balance"]), html.escape(str(usage_str)), html.escape(src_str)))
    parts.append("</table></div>")
    parts.append("<div class='note'>%s</div>" % html.escape(_build_note(bill_rows)))
    parts.append("</div>")

    parts.append("</body></html>")
    return "\n".join(parts)


def main():
    salary = _read_salary()
    bills = _read_bills()
    html_content = _render_dashboard(salary, bills)
    with open_write(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)
    print("看板已生成:", OUT_HTML)
    print("收入月份:", [r["period"] for r in salary])
    print("账单记录:", [(r["source"], r["period"], r["amount"], r["status"]) for r in bills])


if __name__ == "__main__":
    main()
