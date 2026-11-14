#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一单页收支看板（主交付物 · v3）
================================
v3 新增：
  1) Claude / Anthropic 官网视觉语言的近版（暖米白 + 衬线标题 + 赤陶强调），
     并提供「深色」切换回到原有冷灰蓝主题；选择存 localStorage。
  2) 多年数据维度：年份选择器（默认最新年）、跨年度对比卡、明细按年隔离，
     单 CSV 格式不变，新增 2027-MM 数据会自动出现在选择器里。

布局：读数结论 -> 图表置顶 -> KPI 摘要居中 -> 年度对比 -> 明细置底。

硬约束（验收脚本依赖，勿破坏）：
  - 单文件、零外链、零 CDN、零第三方 JS、离线可开。
  - 5 个 class="tab-panel"；class='dbtn' 用单引号；内嵌 const DATA 供 JSON 解析。
  - 明细不丢字段：bills_parsed.csv 的 8 列全部保留并可下钻。
  - 模板用占位符替换，不用 % / str.format，避免 CSS 花括号冲突（历史坑）。

运行：
  python dashboard.py                              # 默认读 config.json 的 save_dir
  SALARY_DATA_DIR=/path/to/workspace python dashboard.py
"""

import csv
import html
import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app_config import paths
from safe_write import open_write

P = paths()

SALARY_COLUMNS = ["类型", "期间", "税前工资收入", "养老保险", "医疗保险", "失业保险",
                  "住房公积金", "社保合计(税前支出)", "个人所得税(税费支出)", "税后工资"]
BILL_COLUMNS = ["来源", "月份", "应还金额", "最低还款额", "账单周期", "用电量", "状态", "原始文件"]

# 分类色走 CSS 变量，两套主题各自给出可读的一组值
PALETTE_COUNT = 9


def _pal(i):
    return "var(--p%d)" % (i % PALETTE_COUNT + 1)


def _fmt(v):
    return "{:,.2f}".format(v)


def _fmt0(v):
    return "{:,.0f}".format(v)


def _num(s):
    if s is None or str(s).strip() == "":
        return 0.0
    try:
        return float(str(s).replace(",", "").replace("¥", "").replace("￥", "").strip())
    except ValueError:
        return 0.0


def _e(v):
    return html.escape("" if v is None else str(v))


def _year_of(period):
    m = re.match(r"^(\d{4})", str(period))
    return m.group(1) if m else "unknown"


def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.reader(f) if r]


def read_salary():
    out = []
    for r in _read_csv(P["salary_csv"]):
        if len(r) < 10 or r[0] != "月度":
            continue
        out.append({
            "period": r[1], "gross": _num(r[2]),
            "pension": _num(r[3]), "medical": _num(r[4]),
            "unemployment": _num(r[5]), "housing": _num(r[6]),
            "social": _num(r[7]), "tax": _num(r[8]), "net": _num(r[9]),
        })
    return sorted(out, key=lambda x: x["period"])


def read_bills():
    out = []
    for r in _read_csv(P["bills_csv"]):
        if len(r) < 8 or r[0] == "来源":
            continue
        amt_raw = r[2].strip()
        out.append({
            "source": r[0], "period": r[1],
            "amount": _num(amt_raw) if amt_raw else 0.0,
            "min_payment": r[3], "cycle": r[4], "usage": r[5],
            "status": r[6], "file": r[7],
        })
    return sorted(out, key=lambda x: (x["period"], x["source"]))


def _kpi_of(monthly, bills):
    inc = sum(m["income"] for m in monthly)
    exp = sum(m["expense"] for m in monthly)
    return {
        "income": inc, "expense": exp, "balance": inc - exp,
        "savings_rate": (inc - exp) / inc * 100 if inc else 0.0,
        "months": len(monthly), "bills": len(bills),
    }


def build_data(salary, bills):
    income = defaultdict(float)
    for r in salary:
        income[r["period"]] = r["net"]

    expense = defaultdict(lambda: defaultdict(float))
    usage = defaultdict(float)
    for r in bills:
        if r["amount"] > 0:
            expense[r["period"]][r["source"]] += r["amount"]
        u = _num(r["usage"]) if r["usage"] else 0.0
        if u:
            usage[r["period"]] += u

    periods = sorted(set(income) | set(expense))
    monthly = []
    for p in periods:
        inc = income.get(p, 0.0)
        exp = sum(expense.get(p, {}).values())
        monthly.append({
            "period": p, "year": _year_of(p), "income": inc, "expense": exp,
            "balance": inc - exp,
            "usage": usage.get(p) or None,
            "sources": dict(expense.get(p, {})),
            "bill_count": sum(1 for b in bills if b["period"] == p),
        })

    def _sources_of(rows):
        agg = defaultdict(float)
        for r in rows:
            if r["amount"] > 0:
                agg[r["source"]] += r["amount"]
        return [{"label": k, "total": v} for k, v in sorted(agg.items(), key=lambda x: -x[1])]

    years = sorted({_year_of(m["period"]) for m in monthly} - {"unknown"})
    has_unknown = any(_year_of(m["period"]) == "unknown" for m in monthly)
    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "is_dummy": os.path.exists(os.path.join(P["data_dir"], "IS_DUMMY.txt")),
        "range": [periods[0], periods[-1]] if periods else [],
        "years": years,
        "has_unknown": has_unknown,
        "kpi": _kpi_of(monthly, bills),
        "monthly": monthly, "salary": salary, "bills": bills,
        "sources": _sources_of(bills),
        "columns": {"salary": SALARY_COLUMNS, "bills": BILL_COLUMNS},
    }


def slice_scope(data, scope):
    """按年份切出一份独立视图数据。scope='all' 表示全部。"""
    if scope == "all":
        return data

    def keep(p):
        return _year_of(p) == scope

    monthly = [m for m in data["monthly"] if keep(m["period"])]
    bills = [b for b in data["bills"] if keep(b["period"])]
    salary = [s for s in data["salary"] if keep(s["period"])]
    agg = defaultdict(float)
    for b in bills:
        if b["amount"] > 0:
            agg[b["source"]] += b["amount"]
    sources = [{"label": k, "total": v} for k, v in sorted(agg.items(), key=lambda x: -x[1])]
    return {
        "generated": data["generated"], "is_dummy": data["is_dummy"],
        "range": [monthly[0]["period"], monthly[-1]["period"]] if monthly else [],
        "years": data["years"], "has_unknown": data["has_unknown"],
        "kpi": _kpi_of(monthly, bills),
        "monthly": monthly, "salary": salary, "bills": bills, "sources": sources,
        "columns": data["columns"],
    }


# ---------------------------------------------------------------------------
# 图表（自包含 SVG / HTML，颜色全部走 CSS 变量以适配双主题）
# ---------------------------------------------------------------------------
def _bar_chart(monthly, w=880, h=350):
    """双向柱状图：收入向上、支出向下，共用零轴与统一比例尺。
    零轴按 max(收入):max(支出) 分配上下空间，两侧比例尺仍统一但支出侧不被压扁。"""
    if not monthly:
        return ""
    n = len(monthly)
    mt, mr, mb, ml = 34, 24, 58, 76
    cw, ch = w - ml - mr, h - mt - mb
    max_income = max(m["income"] for m in monthly)
    max_expense = max(m["expense"] for m in monthly)
    total_max = max_income + max_expense
    if total_max <= 0:
        total_max = 1.0
    up = ch * (max_income / total_max)
    down = ch - up
    zero = mt + up
    step = cw / n
    bw = min(36.0, step * 0.54)

    parts = ["<svg viewBox='0 0 %d %d' class='chart' xmlns='http://www.w3.org/2000/svg' "
             "role='img' aria-label='收支对比'>" % (w, h)]
    # 上下区各自按可用高度决定刻度数：收入远大于支出时 down 可能只有 30px，
    # 固定画 3 条负刻度会让文字全部叠在零轴附近（实测截图发现的视觉 bug）。
    def _tick_count(height):
        return 3 if height >= 70 else (2 if height >= 45 else 1)

    for side, ticks, height, maximum in (
            ("up", _tick_count(up), up, max_income),
            ("down", _tick_count(down), down, max_expense)):
        for i in range(1, ticks + 1):
            frac = i / float(ticks)
            y = zero - height * frac if side == "up" else zero + height * frac
            parts.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' class='grid'/>" % (
                ml, y, w - mr, y))
            label = _fmt0(maximum * frac)
            if side == "down":
                label = "-" + label
            parts.append("<text x='%d' y='%.1f' class='axis' text-anchor='end'>%s</text>" % (
                ml - 9, y + 3, label))
    parts.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' class='zero'/>" % (ml, zero, w - mr, zero))

    for i, m in enumerate(monthly):
        cx = ml + step * (i + 0.5)
        ih = m["income"] / max_income * up if max_income else 0.0
        eh = m["expense"] / max_expense * down if max_expense else 0.0
        parts.append("<rect x='%.1f' y='%.1f' width='%.1f' height='%.1f' rx='3' fill='var(--income)'>"
                     "<title>%s 收入 ¥%s</title></rect>" % (
                         cx - bw / 2, zero - ih, bw, max(ih, 0.5),
                         _e(m["period"]), _fmt(m["income"])))
        parts.append("<rect x='%.1f' y='%.1f' width='%.1f' height='%.1f' rx='3' fill='var(--expense)'>"
                     "<title>%s 支出 ¥%s</title></rect>" % (
                         cx - bw / 2, zero, bw, max(eh, 0.5),
                         _e(m["period"]), _fmt(m["expense"])))
        parts.append("<text x='%.1f' y='%.1f' class='val income' text-anchor='middle'>%s</text>" % (
            cx, zero - ih - 7, _fmt0(m["income"])))
        parts.append("<text x='%.1f' y='%.1f' class='val expense' text-anchor='middle'>%s</text>" % (
            cx, zero + eh + 15, _fmt0(m["expense"])))
        parts.append("<text x='%.1f' y='%d' class='axis x' text-anchor='middle'>%s</text>" % (
            cx, h - 16, _e(m["period"])))
    parts.append("</svg>")
    return "\n".join(parts)


def _donut_chart(sources, total, size=210):
    if not sources or total <= 0:
        return ""
    r = 72.0
    cx = cy = size / 2.0
    circ = 2 * math.pi * r
    parts = ["<svg viewBox='0 0 %d %d' class='donut' xmlns='http://www.w3.org/2000/svg' "
             "role='img' aria-label='支出构成'>" % (size, size)]
    parts.append("<circle cx='%.1f' cy='%.1f' r='%.1f' class='donut-track'/>" % (cx, cy, r))
    offset = 0.0
    for i, s in enumerate(sources):
        frac = s["total"] / total
        seg = circ * frac
        parts.append(
            "<circle cx='%.1f' cy='%.1f' r='%.1f' fill='none' stroke='%s' stroke-width='22' "
            "stroke-dasharray='%.2f %.2f' stroke-dashoffset='%.2f' "
            "transform='rotate(-90 %.1f %.1f)'><title>%s ¥%s（%.1f%%）</title></circle>" % (
                cx, cy, r, _pal(i), seg, circ - seg, -offset, cx, cy,
                _e(s["label"]), _fmt(s["total"]), frac * 100))
        offset += seg
    parts.append("<text x='%.1f' y='%.1f' class='donut-label' text-anchor='middle'>总支出</text>" % (cx, cy - 4))
    parts.append("<text x='%.1f' y='%.1f' class='donut-value' text-anchor='middle'>¥%s</text>" % (
        cx, cy + 18, _fmt0(total)))
    parts.append("</svg>")
    return "\n".join(parts)


def _legend_html(sources, total):
    items = []
    for i, s in enumerate(sources):
        pct = s["total"] / total * 100 if total else 0
        items.append(
            "<li><span class='dot' style='background:%s'></span>"
            "<span class='lg-name'>%s</span><span class='lg-val'>¥%s</span>"
            "<span class='lg-pct'>%.1f%%</span></li>" % (
                _pal(i), _e(s["label"]), _fmt(s["total"]), pct))
    return "<ul class='legend'>%s</ul>" % "".join(items)


def _hbar_html(sources, total):
    if not sources:
        return "<p class='muted'>暂无支出数据。</p>"
    mx = max(s["total"] for s in sources) or 1.0
    rows = []
    for i, s in enumerate(sources):
        pct = s["total"] / total * 100 if total else 0
        rows.append(
            "<div class='hbar'><span class='hb-name'>%s</span>"
            "<span class='hb-track'><span class='hb-fill' style='width:%.1f%%;background:%s'></span></span>"
            "<span class='hb-val'>¥%s</span><span class='hb-pct'>%.1f%%</span></div>" % (
                _e(s["label"]), s["total"] / mx * 100, _pal(i), _fmt(s["total"]), pct))
    return "".join(rows)


def _table(headers, rows, cls=""):
    h = "".join("<th>%s</th>" % _e(x) for x in headers)
    body = []
    for row in rows:
        cells = []
        for cell in row:
            if isinstance(cell, tuple):
                cells.append("<td class='%s'>%s</td>" % (_e(cell[1]), cell[0]))
            else:
                cells.append("<td>%s</td>" % cell)
        body.append("<tr>%s</tr>" % "".join(cells))
    return "<table class='%s'><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (
        cls, h, "".join(body))


def render_tables(d, scope="all"):
    monthly, bills, sources = d["monthly"], d["bills"], d["sources"]
    tag = re.sub(r"[^0-9A-Za-z]", "", str(scope))[:20] or "scope"

    overview = _table(
        ["月份", "税后收入", "支出合计", "结余", "用电量(kWh)", "账单数"],
        [["<b>%s</b>" % _e(m["period"]),
          (_fmt(m["income"]), "num income"),
          (_fmt(m["expense"]), "num expense"),
          (_fmt(m["balance"]), "num balance"),
          (_e(m["usage"]) if m["usage"] else "—", "num"),
          (str(m["bill_count"]), "num")] for m in monthly])

    income_tbl = _table(
        ["月份", "税前", "养老", "医疗", "失业", "公积金", "社保合计", "个税", "税后"],
        [["<b>%s</b>" % _e(s["period"])] +
         [(_fmt(s[k]), "num") for k in
          ["gross", "pension", "medical", "unemployment", "housing", "social", "tax", "net"]]
         for s in d["salary"]])

    total_src = sum(s["total"] for s in sources) or 1.0
    source_rows = []
    for i, s in enumerate(sources):
        source_rows.append([
            "<span class='dot' style='background:%s'></span>%s" % (_pal(i), _e(s["label"])),
            (_fmt(s["total"]), "num"),
            ("%.1f%%" % (s["total"] / total_src * 100), "num"),
        ])
    source_tbl = _table(["支出来源", "累计金额", "占比"], source_rows)

    labels = [s["label"] for s in sources]
    pivot_rows = []
    for m in monthly:
        row = ["<b>%s</b>" % _e(m["period"])]
        for lb in labels:
            v = m["sources"].get(lb)
            row.append((_fmt(v) if v else "—", "num"))
        row.append((_fmt(m["expense"]), "num expense"))
        pivot_rows.append(row)
    pivot_tbl = _table(["月份"] + [_e(x) for x in labels] + ["合计"], pivot_rows)

    groups = []
    for idx, m in enumerate(monthly):
        month_bills = [b for b in bills if b["period"] == m["period"]]
        rows = []
        for b in month_bills:
            rows.append([
                _e(b["source"]),
                (_fmt(b["amount"]) if b["amount"] else "—", "num expense"),
                _e(b["min_payment"] or "—"), _e(b["cycle"] or "—"),
                _e(b["usage"] or "—"), _e(b["status"] or "—"),
                "<code>%s</code>" % _e(b["file"] or "—"),
            ])
        detail = _table(
            ["来源", "应还金额", "最低还款额", "账单周期", "用电量", "状态", "原始文件"], rows) \
            if rows else "<p class='muted'>本月无账单记录。</p>"
        gid = "%s-detail-%d" % (tag, idx)
        groups.append(
            "<div class='dgroup'>"
            "<button class='dbtn' type='button' aria-expanded='false' "
            "onclick=\"toggleDetail('%s', this)\">"
            "<span class='chev'>&#9656;</span><span class='dmonth'>%s</span>"
            "<span class='tag'>%d 份账单 · ¥%s</span></button>"
            "<div class='dbody' id='%s' hidden>%s</div></div>" %
            (gid, _e(m["period"]), len(month_bills), _fmt(m["expense"]), gid, detail))

    all_rows = [[_e(b["period"]), _e(b["source"]),
                 (_fmt(b["amount"]) if b["amount"] else "—", "num"),
                 _e(b["min_payment"] or "—"), _e(b["cycle"] or "—"),
                 _e(b["usage"] or "—"), _e(b["status"] or "—"),
                 "<code>%s</code>" % _e(b["file"] or "—")] for b in bills]
    all_tbl = _table(
        ["月份", "来源", "应还金额", "最低还款额", "账单周期", "用电量", "状态", "原始文件"], all_rows)

    return {
        "overview": overview, "income": income_tbl,
        "source": source_tbl, "pivot": pivot_tbl,
        "groups": "".join(groups) or "<p class='muted'>暂无支出明细。</p>",
        "all": all_tbl or "<p class='muted'>暂无账单记录。</p>",
    }


def scope_tag(d):
    """用于折叠组 DOM id 去重（不同年份片段的 id 不能重复）。"""
    if not d["monthly"]:
        return "empty"
    return re.sub(r"[^0-9A-Za-z]", "", "-".join(sorted({m["year"] for m in d["monthly"]})))[:24] or "scope"


def _insights(d):
    k, monthly = d["kpi"], d["monthly"]
    out = []
    if monthly:
        last = monthly[-1]
        note = "—"
        if len(monthly) > 1:
            delta = last["balance"] - monthly[-2]["balance"]
            note = "较上月 %s¥%s" % ("+" if delta >= 0 else "-", _fmt0(abs(delta)))
        out.append({"label": "最近月份结余", "value": "%s · ¥%s" % (last["period"], _fmt0(last["balance"])), "note": note})
        out.append({"label": "月均支出", "value": "¥%s" % _fmt0(k["expense"] / len(monthly)),
                    "note": "%d 个月账单平均" % len(monthly)})
    if d["sources"] and k["expense"]:
        top = d["sources"][0]
        out.append({"label": "最大支出来源", "value": top["label"],
                    "note": "¥%s · 占 %.1f%%" % (_fmt0(top["total"]), top["total"] / k["expense"] * 100)})
    out.append({"label": "储蓄率", "value": "%.1f%%" % k["savings_rate"], "note": "结余 / 收入"})
    return out[:4]


def _kpi_html(k, months, bills_n):
    avg_balance = k["balance"] / months if months else 0.0
    items = [
        ("累计收入（税后）", "¥" + _fmt(k["income"]), "%d 个月工资条" % months, "var(--income)"),
        ("累计支出（账单）", "¥" + _fmt(k["expense"]), "%d 份账单" % bills_n, "var(--expense)"),
        ("累计结余", "¥" + _fmt(k["balance"]), "月均结余 ¥" + _fmt0(avg_balance), "var(--balance)"),
        ("储蓄率", "%.1f%%" % k["savings_rate"], "结余 / 收入", "var(--accent)"),
    ]
    return "".join(
        "<div class='kpi' style='--kc:%s'><div class='label'>%s</div>"
        "<div class='value'>%s</div><div class='sub'>%s</div></div>" % (c, _e(l), v, _e(s))
        for l, v, s, c in items)


def _insights_html(items):
    return "".join(
        "<div class='insight'><div class='il'>%s</div><div class='iv'>%s</div>"
        "<div class='in'>%s</div></div>" % (_e(i["label"]), _e(i["value"]), _e(i["note"]))
        for i in items)


def _year_compare_html(data):
    """跨年度对比卡：始终显示，不随年份选择器切换。"""
    years = sorted({m["year"] for m in data["monthly"]})
    if not years:
        return ""
    rows, annual = [], []
    prev_bal = None
    for y in years:
        ms = [m for m in data["monthly"] if m["year"] == y]
        inc = sum(m["income"] for m in ms)
        exp = sum(m["expense"] for m in ms)
        bal = inc - exp
        yoy = ("%+.1f%%" % ((bal - prev_bal) / abs(prev_bal) * 100)) if prev_bal else "—"
        label = y if y != "unknown" else "未归类"
        rows.append([
            "<b>%s</b>" % _e(label), (str(len(ms)), "num"),
            (_fmt(inc), "num income"), (_fmt(exp), "num expense"),
            (_fmt(bal), "num balance"),
            ("%.1f%%" % ((bal / inc * 100) if inc else 0), "num"),
            (yoy, "num"),
        ])
        annual.append({"period": label, "income": inc, "expense": exp})
        prev_bal = bal
    # 只有一个年度时不画对比柱图：一根孤柱占大版面，反而加重「臃肿」感。
    multi = len(years) >= 2
    chart = _bar_chart(annual, w=880, h=250) if multi else ""
    if multi:
        note = "共 %d 个年度；柱图按年汇总，收入向上、支出向下。新增下一年度数据后自动多一行。" % len(years)
    else:
        note = "当前仅 1 个年度，暂不绘制对比柱图；加入下一年度数据后，此处与年份选择器会自动多一项。"
    chart_html = "<div style='margin-top:14px'>%s</div>" % chart if chart else ""
    return (
        "<div class='card'><h2>年度对比</h2><p class='sub'>%s</p>"
        "<div class='table-wrap'>%s</div>%s</div>" % (
            _e(note), _table(["年度", "月份数", "收入", "支出", "结余", "储蓄率", "结余同比"], rows),
            chart_html))


TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body[data-theme="claude"] {
  --bg:#F5F4ED; --surface:#FAF9F5; --surface-2:#F0EEE6; --surface-3:#E8E6DC;
  --border:rgba(31,30,29,.10); --border-strong:rgba(31,30,29,.20);
  --text:#141413; --text-2:#5E5D59; --text-3:#87867F;
  --income:#2E7D5B; --expense:#B53333; --balance:#A67C00;
  --accent:#C96442; --accent-soft:rgba(201,100,66,.10);
  --grid:rgba(31,30,29,.10); --zero:rgba(31,30,29,.30);
  --p1:#C96442; --p2:#2E7D5B; --p3:#7A6A55; --p4:#B53333;
  --p5:#4A6FA5; --p6:#8A6E3E; --p7:#6B7F6E; --p8:#9A6B7A; --p9:#87867F;
}
body[data-theme="dark"] {
  --bg:#0b1220; --surface:#121c2e; --surface-2:#18253b; --surface-3:#1f2f4a;
  --border:rgba(148,163,184,.16); --border-strong:rgba(148,163,184,.30);
  --text:#e6edf7; --text-2:#a9b8cc; --text-3:#7f91ab;
  --income:#34d399; --expense:#fb7185; --balance:#fbbf24;
  --accent:#38bdf8; --accent-soft:rgba(56,189,248,.14);
  --grid:rgba(148,163,184,.10); --zero:rgba(148,163,184,.38);
  --p1:#60a5fa; --p2:#f472b6; --p3:#a78bfa; --p4:#fbbf24;
  --p5:#34d399; --p6:#22d3ee; --p7:#fb923c; --p8:#e879f9; --p9:#94a3b8;
}
body { margin:0; padding:24px 28px 34px; background:var(--bg); color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Arial,sans-serif;
  font-size:14px; line-height:1.6; }
.wrap { max-width:1180px; margin:0 auto; }
header { display:flex; align-items:flex-end; gap:14px; flex-wrap:wrap; margin-bottom:14px; }
h1 { font-family:Georgia,"Songti SC","Noto Serif CJK SC",serif; font-size:27px;
  font-weight:600; letter-spacing:-.01em; margin:0; }
h2 { font-family:Georgia,"Songti SC","Noto Serif CJK SC",serif; font-weight:600; }
.meta { color:var(--text-3); font-size:12px; }
.badge { background:var(--accent-soft); color:var(--accent);
  border:1px solid var(--border-strong); font-size:11px; padding:2px 9px; border-radius:999px; }
.banner { display:flex; gap:10px; align-items:center; background:var(--accent-soft);
  border:1px solid var(--border-strong); color:var(--accent);
  padding:10px 14px; border-radius:12px; font-size:13px; margin-bottom:18px; }
nav { position:sticky; top:0; z-index:20; background:var(--bg);
  display:flex; align-items:center; gap:6px; flex-wrap:wrap;
  padding:12px 0; margin-bottom:20px; border-bottom:1px solid var(--border); }
.tab-btn { background:transparent; color:var(--text-2); border:1px solid transparent;
  border-radius:999px; padding:7px 15px; font-size:13px; cursor:pointer; }
.tab-btn:hover { background:var(--surface-2); color:var(--text); }
.tab-btn.active { background:var(--accent-soft); color:var(--accent); border-color:var(--border-strong); }
.nav-right { margin-left:auto; display:flex; align-items:center; gap:8px; }
.year-sel { background:var(--surface); color:var(--text); border:1px solid var(--border-strong);
  border-radius:999px; padding:7px 14px; font-size:13px; cursor:pointer; }
.insights { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px; }
.insight { background:var(--surface-2); border:1px solid var(--border); border-radius:12px; padding:12px 14px; }
.insight .il { font-size:11px; color:var(--text-3); }
.insight .iv { font-size:16px; font-weight:600; margin:4px 0 2px; letter-spacing:-.01em; }
.insight .in { font-size:11px; color:var(--text-3); font-variant-numeric:tabular-nums; }
.grid { display:grid; grid-template-columns:1.65fr 1fr; gap:16px; margin-bottom:16px; }
.card { background:var(--surface); border:1px solid var(--border); border-radius:14px;
  box-shadow:0 0 0 1px var(--border); padding:20px; margin-bottom:16px; }
.card > h2 { font-size:16px; margin:0 0 4px; }
.card > .sub { color:var(--text-3); font-size:12px; margin:0 0 14px; }
.chart { width:100%; height:auto; display:block; }
.chart .grid { stroke:var(--grid); }
.chart .zero { stroke:var(--zero); }
.chart .axis { fill:var(--text-3); font-size:10px; }
.chart .axis.x { fill:var(--text-2); font-size:10.5px; }
.grid > .card { display:flex; flex-direction:column; }
.chart-legend { margin-top:auto; padding-top:16px; display:flex; flex-wrap:wrap; gap:16px;
  color:var(--text-3); font-size:12px; }
.chart-legend i { display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:6px; }
.chart .val { font-size:9.5px; font-variant-numeric:tabular-nums; }
.chart .val.income { fill:var(--income); }
.chart .val.expense { fill:var(--expense); }
.donut { width:100%; max-width:210px; display:block; margin:0 auto; }
.donut-track { fill:none; stroke:var(--surface-3); stroke-width:22; }
.donut-label { fill:var(--text-3); font-size:11px; }
.donut-value { fill:var(--text); font-size:17px; font-weight:600; font-variant-numeric:tabular-nums; }
.legend { list-style:none; margin:12px 0 0; padding:0; font-size:12px; }
.legend li { display:flex; align-items:center; gap:8px; padding:5px 0; border-bottom:1px dashed var(--border); }
.legend li:last-child { border-bottom:none; }
.lg-name { color:var(--text-2); }
.lg-val { margin-left:auto; font-variant-numeric:tabular-nums; }
.lg-pct { color:var(--text-3); width:46px; text-align:right; font-variant-numeric:tabular-nums; }
.dot { display:inline-block; width:8px; height:8px; border-radius:50%; flex:none; }
.summary { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px; }
.kpi { background:var(--surface); border:1px solid var(--border); border-radius:14px;
  padding:16px 18px; position:relative; overflow:hidden; }
.kpi::before { content:""; position:absolute; left:0; top:0; bottom:0; width:3px; background:var(--kc,var(--accent)); }
.kpi .label { color:var(--text-3); font-size:12px; }
.kpi .value { font-size:27px; font-weight:600; letter-spacing:-.02em;
  font-variant-numeric:tabular-nums; margin:6px 0 2px; color:var(--kc,var(--text)); }
.kpi .sub { color:var(--text-3); font-size:11px; }
.table-wrap { overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th { text-align:left; color:var(--text-3); font-weight:500; font-size:12px; white-space:nowrap;
  padding:9px 8px; background:var(--surface-2); border-bottom:1px solid var(--border-strong); }
th:first-child { border-top-left-radius:8px; }
th:last-child { border-top-right-radius:8px; }
td { padding:9px 8px; border-bottom:1px solid var(--border); }
tbody tr:nth-child(even) { background:var(--surface-2); }
tbody tr:hover { background:var(--accent-soft); }
tbody tr:last-child td { border-bottom:none; }
.num { text-align:right; font-variant-numeric:tabular-nums; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
.income { color:var(--income); }
.expense { color:var(--expense); }
.balance { color:var(--balance); }
code { background:var(--surface-3); padding:2px 5px; border-radius:4px; font-size:12px; }
.hbar { display:flex; align-items:center; gap:12px; padding:9px 0; border-bottom:1px dashed var(--border); }
.hbar:last-child { border-bottom:none; }
.hb-name { width:128px; flex:none; color:var(--text-2); font-size:13px; }
.hb-track { flex:1; height:12px; background:var(--surface-3); border-radius:999px; overflow:hidden; }
.hb-fill { display:block; height:100%; border-radius:999px; }
.hb-val { width:108px; text-align:right; font-variant-numeric:tabular-nums; font-size:13px; }
.hb-pct { width:52px; text-align:right; color:var(--text-3); font-size:12px; font-variant-numeric:tabular-nums; }
.dgroup { border:1px solid var(--border); border-radius:12px; margin-bottom:10px; overflow:hidden; background:var(--surface); }
.dbtn { width:100%; display:flex; align-items:center; gap:10px; background:transparent;
  border:0; color:var(--text); padding:13px 16px; font-size:14px; cursor:pointer; text-align:left; }
.dbtn:hover { background:var(--surface-2); }
.dbtn .chev { color:var(--accent); transition:transform .18s; font-size:12px; }
.dbtn.open .chev { transform:rotate(90deg); }
.dmonth { font-weight:600; font-variant-numeric:tabular-nums; }
.dbtn .tag { margin-left:auto; color:var(--text-3); font-size:12px; font-variant-numeric:tabular-nums; }
.dbody { padding:6px 16px 14px; border-top:1px solid var(--border); background:var(--surface-2); }
.muted { color:var(--text-3); font-size:13px; }
.cols { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.cols ul { margin:6px 0; padding-left:18px; font-size:12px; line-height:1.9; }
footer { color:var(--text-3); font-size:12px; margin-top:22px; border-top:1px solid var(--border); padding-top:14px; }
@media (max-width:900px) { .grid { grid-template-columns:1fr; } .insights,.summary { grid-template-columns:repeat(2,1fr); } }
@media (max-width:560px) { body { padding:14px; } .insights,.summary,.cols { grid-template-columns:1fr; } .hb-name { width:92px; } }
@media print { body { background:#fff; color:#111; } nav,.dbtn,.banner { display:none; } .card,.kpi,.insight,.dgroup { background:#fff; border-color:#ddd; box-shadow:none; } th { background:#f3f4f6; } .scope[hidden] { display:none !important; } }
</style>
</head>
<body data-theme="claude">
<div class="wrap">
<header>
  <h1>__TITLE__</h1>
  __BADGE__
  <span class="meta">__GENERATED__ ｜ __RANGE__ ｜ __COUNT__</span>
</header>
__DUMMY_BANNER__
<nav>
  <button class="tab-btn active" type="button" onclick="showTab('overview', this)">总览</button>
  <button class="tab-btn" type="button" onclick="showTab('income', this)">收入</button>
  <button class="tab-btn" type="button" onclick="showTab('expense', this)">支出</button>
  <button class="tab-btn" type="button" onclick="showTab('detail', this)">支出明细</button>
  <button class="tab-btn" type="button" onclick="showTab('source', this)">数据源</button>
  <span class="nav-right">
    <select class="year-sel" id="yearSel" onchange="changeYear()" aria-label="选择年份">__YEAR_OPTIONS__</select>
    <button class="tab-btn" id="themeBtn" type="button" onclick="toggleTheme()">深色</button>
    <button class="tab-btn" type="button" onclick="exportJSON()">导出数据 JSON</button>
  </span>
</nav>

<div class="tab-panel" id="panel-overview">
  __YEAR_COMPARE__
  __PANEL_OVERVIEW__
</div>
<div class="tab-panel" id="panel-income" hidden>__PANEL_INCOME__</div>
<div class="tab-panel" id="panel-expense" hidden>__PANEL_EXPENSE__</div>
<div class="tab-panel" id="panel-detail" hidden>__PANEL_DETAIL__</div>
<div class="tab-panel" id="panel-source" hidden>
  <div class="card"><h2>输入文件</h2>__DATASOURCE__</div>
  <div class="card"><h2>字段定义</h2><div class="cols">
    <div><b>工资年度汇总.csv（10 列）</b><ul>__SALARY_COLS__</ul></div>
    <div><b>bills_parsed.csv（8 列）</b><ul>__BILL_COLS__</ul></div>
  </div></div>
  <div class="card"><h2>说明</h2><p class="muted">本文件为自包含单页看板，无外链资源，可离线打开。默认展示最新年度，可用顶部年份选择器回溯历史或查看全部年份；新增下一年度数据后选择器自动多一项。页面内嵌完整 JSON 数据。</p></div>
</div>

<footer>由 dashboard.py 生成 ｜ 单文件离线看板 ｜ 数据仅保存在本地</footer>
</div>
<script>
const DATA = __DATA_JSON__;
function showTab(name, btn) {
  var panels = document.querySelectorAll('.tab-panel');
  for (var i = 0; i < panels.length; i++) panels[i].hidden = (panels[i].id !== 'panel-' + name);
  var btns = document.querySelectorAll('.tab-btn');
  for (var j = 0; j < btns.length; j++) btns[j].classList.remove('active');
  if (btn) btn.classList.add('active');
  window.scrollTo(0, 0);
}
function changeYear() {
  var v = document.getElementById('yearSel').value;
  var scopes = document.querySelectorAll('.scope');
  for (var i = 0; i < scopes.length; i++) scopes[i].hidden = (scopes[i].getAttribute('data-scope') !== v);
}
function toggleTheme() {
  var b = document.body;
  var next = b.getAttribute('data-theme') === 'claude' ? 'dark' : 'claude';
  b.setAttribute('data-theme', next);
  document.getElementById('themeBtn').textContent = next === 'claude' ? '深色' : '浅色';
  try { localStorage.setItem('salary-dashboard-theme', next); } catch (e) {}
}
function toggleDetail(id, btn) {
  var el = document.getElementById(id);
  var opening = el.hidden;
  el.hidden = !opening;
  btn.classList.toggle('open', opening);
  btn.setAttribute('aria-expanded', opening ? 'true' : 'false');
}
function toggleAll(opening) {
  var bodies = document.querySelectorAll('.dbody');
  var btns = document.querySelectorAll('.dbtn');
  for (var i = 0; i < bodies.length; i++) bodies[i].hidden = !opening;
  for (var j = 0; j < btns.length; j++) {
    btns[j].classList.toggle('open', opening);
    btns[j].setAttribute('aria-expanded', opening ? 'true' : 'false');
  }
}
function exportJSON() {
  var blob = new Blob([JSON.stringify(DATA, null, 2)], {type: 'application/json'});
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = '看板数据.json';
  a.click();
  URL.revokeObjectURL(a.href);
}
(function () {
  try {
    if (localStorage.getItem('salary-dashboard-theme') === 'dark') {
      document.body.setAttribute('data-theme', 'dark');
      document.getElementById('themeBtn').textContent = '浅色';
    }
  } catch (e) {}
})();
</script>
</body>
</html>
"""


def _scope_panels(d, key):
    """生成一个年份片段内 4 个可切换 Tab 的内容。"""
    k, monthly, bills, sources = d["kpi"], d["monthly"], d["bills"], d["sources"]
    t = render_tables(d, key)
    total_expense = k["expense"]

    overview = (
        "<div class='insights'>%s</div>"
        "<div class='grid'>"
        "<div class='card'><h2>月度收支对比</h2><p class='sub'>上柱为收入，下柱为支出，共用零轴与统一比例尺。</p>%s"
        "<div class='chart-legend'><span><i style='background:var(--income)'></i>收入（向上）</span>"
        "<span><i style='background:var(--expense)'></i>支出（向下）</span>"
        "<span>零轴上下共用同一比例尺</span></div></div>"
        "<div class='card'><h2>支出构成</h2><p class='sub'>按来源归集的全期占比</p>%s%s</div>"
        "</div><div class='summary'>%s</div>"
        "<div class='card'><h2>月度汇总</h2><div class='table-wrap'>%s</div>"
        "<p class='muted' style='margin-top:10px'>支出为 0.00 的月份表示当期无账单记录，不代表实际没有消费。</p></div>" % (
            _insights_html(_insights(d)),
            _bar_chart(monthly) or "<p class='muted'>暂无月度数据。</p>",
            _donut_chart(sources, total_expense) or "<p class='muted'>暂无支出数据。</p>",
            _legend_html(sources, total_expense) if sources else "",
            _kpi_html(k, k["months"], k["bills"]), t["overview"]))

    income = ("<div class='card'><h2>工资条月度明细</h2><p class='sub'>税前 → 社保四项 → 个税 → 税后，单位：元</p>"
              "<div class='table-wrap'>%s</div></div>" % t["income"])

    expense = (
        "<div class='card'><h2>支出来源（归一化）</h2><p class='sub'>条长按最大来源归一化，右侧为实际金额与占比</p>%s</div>"
        "<div class='grid'><div class='card'><h2>来源汇总</h2>%s</div>"
        "<div class='card'><h2>支出构成</h2>%s%s</div></div>"
        "<div class='card'><h2>月份 × 来源透视</h2><div class='table-wrap'>%s</div></div>" % (
            _hbar_html(sources, total_expense), t["source"],
            _donut_chart(sources, total_expense) or "<p class='muted'>暂无支出数据。</p>",
            _legend_html(sources, total_expense) if sources else "", t["pivot"]))

    detail = (
        "<div class='card'><h2>支出明细（L1：按月展开）</h2>"
        "<p class='sub'>点月份展开该月每份账单的最低还款额、账单周期、用电量、状态与原始文件；逐笔交易明细当前未解析。</p>"
        "<button class='tab-btn' type='button' onclick=\"toggleAll(true)\">全部展开</button>"
        "<button class='tab-btn' type='button' onclick=\"toggleAll(false)\">全部收起</button>"
        "<div style='margin-top:14px'>%s</div></div>"
        "<div class='card'><h2>全部账单记录</h2><div class='table-wrap'>%s</div></div>" % (
            t["groups"], t["all"]))

    return {"overview": overview, "income": income, "expense": expense, "detail": detail}


def build_html(data):
    years = data["years"]
    scopes = ["all"] + years + (["unknown"] if data["has_unknown"] else [])
    default = years[-1] if years else ("unknown" if data["has_unknown"] else "all")

    panels = {"overview": [], "income": [], "expense": [], "detail": []}
    for s in scopes:
        d = slice_scope(data, s)
        c = _scope_panels(d, s)
        hidden = "" if s == default else " hidden"
        for tab in panels:
            panels[tab].append(
                "<div class='scope' data-scope='%s'%s>%s</div>" % (_e(s), hidden, c[tab]))

    opts = []
    for s in scopes:
        label = "全部年份" if s == "all" else ("未归类" if s == "unknown" else s + " 年")
        sel = " selected" if s == default else ""
        opts.append("<option value='%s'%s>%s</option>" % (_e(s), sel, _e(label)))

    banner = ("<div class='banner'><b>演示数据（dummy）</b><span>本页全部金额为虚构示例，"
              "不是任何人的真实收支，请勿当作真实报表对外转发。</span></div>"
              if data["is_dummy"] else "")
    badge = "<span class='badge'>dummy</span>" if data["is_dummy"] else ""
    rng = " ~ ".join(data["range"]) if data["range"] else "—"
    count = "%d 个月 · %d 份账单 · %d 个年度" % (
        data["kpi"]["months"], data["kpi"]["bills"], len(years))
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    ds_rows = [
        ["工资年度汇总.csv", _e(P["salary_csv"]), str(len(data["salary"]))],
        ["bills_parsed.csv", _e(P["bills_csv"]), str(len(data["bills"]))],
        ["统一单页看板", _e(P["dashboard_html"]), "1"],
        ["工作区目录", _e(P["data_dir"]), "—"],
    ]

    repl = {
        "__TITLE__": "收支统一看板",
        "__BADGE__": badge,
        "__GENERATED__": _e(data["generated"]),
        "__RANGE__": _e(rng),
        "__COUNT__": _e(count),
        "__DUMMY_BANNER__": banner,
        "__YEAR_OPTIONS__": "".join(opts),
        "__YEAR_COMPARE__": _year_compare_html(data),
        "__PANEL_OVERVIEW__": "".join(panels["overview"]),
        "__PANEL_INCOME__": "".join(panels["income"]),
        "__PANEL_EXPENSE__": "".join(panels["expense"]),
        "__PANEL_DETAIL__": "".join(panels["detail"]),
        "__DATASOURCE__": _table(["数据源", "路径", "记录数"], ds_rows),
        "__SALARY_COLS__": "".join("<li><code>%s</code></li>" % _e(c) for c in SALARY_COLUMNS),
        "__BILL_COLS__": "".join("<li><code>%s</code></li>" % _e(c) for c in BILL_COLUMNS),
        "__DATA_JSON__": payload,
    }
    out = TEMPLATE
    for key, val in repl.items():
        out = out.replace(key, val)
    return out


def main():
    salary, bills = read_salary(), read_bills()
    if not salary and not bills:
        print("[警告] 未读到数据：%s 与 %s" % (P["salary_csv"], P["bills_csv"]))
    data = build_data(salary, bills)
    content = build_html(data)
    os.makedirs(P["data_dir"], exist_ok=True)
    with open_write(P["dashboard_html"], "w", encoding="utf-8") as f:
        f.write(content)
    print("统一单页看板已生成:", P["dashboard_html"])
    print("数据范围:", data["range"], "| 月份:", data["kpi"]["months"],
          "| 账单:", data["kpi"]["bills"], "| 年度:", data["years"],
          "| unknown:", data["has_unknown"], "| dummy:", data["is_dummy"])


if __name__ == "__main__":
    main()
