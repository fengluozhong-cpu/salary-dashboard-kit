#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重建 fixtures/ 下全部分层脱敏数据（维护用，普通使用者不需要跑）
================================================================
只写 <replica-kit>/fixtures/，不读取也不写入项目其它目录；所有数值、
机构名、邮箱域名均为虚构占位（example.com / example.org）。

分层：
  L1_csv       换一套 CSV 就能出看板
  L2_bills     新机构账单 HTML + 需要自己改的解析正则
  L3_mail      模拟邮箱：脱敏 xlsx 工资条 + 账单附件 + 邮件清单 + IMAP 占位配置
  L4_pipeline  字段映射覆盖、定时任务示例、配置清单

需要 openpyxl 生成 xlsx（仅构建期）；生成的 xlsx 是静态产物。
用法：python scripts/build_fixtures.py
"""

import csv
import json
import os
import shutil
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(KIT, "fixtures")
if os.path.basename(KIT) != "replica-kit":
    raise RuntimeError("隔离失败：脚本必须在 replica-kit/scripts/ 下运行")

YEARS = (2025, 2026)
MONTHS = [(y, "%d-%02d" % (y, m)) for y in YEARS for m in range(1, 13)]

SALARY_COLUMNS = ["类型", "期间", "税前工资收入", "养老保险", "医疗保险", "失业保险",
                  "住房公积金", "社保合计(税前支出)", "个人所得税(税费支出)", "税后工资"]
BILL_COLUMNS = ["来源", "月份", "应还金额", "最低还款额", "账单周期", "用电量", "状态", "原始文件"]

# L1 用与 L0 不同的虚构来源名，验证「换数据不需改代码」
L1_SOURCES = ["示例生活卡", "示例交通卡", "示例水电"]
# L2 用与内置解析器完全不同的机构措辞，演示「改正则接新来源」
L2_SOURCES = [
    ("card_alpha", "示例银行甲", "本月账单合计：¥{amt} 最低还款：¥{min_amt} 账期 {period}-01 至 {period}-31",
     "本月账单合计[^0-9]{0,40}([0-9,]+\\.[0-9]{2})", "最低还款[^0-9]{0,40}([0-9,]+\\.[0-9]{2})"),
    ("card_beta", "示例银行乙", "应还总额 RMB {amt} 最低还款额 RMB {min_amt} 账单周期 {period}",
     "应还总额[^0-9]{0,40}([0-9,]+\\.[0-9]{2})", "最低还款额[^0-9]{0,40}([0-9,]+\\.[0-9]{2})"),
    ("utility_gamma", "示例能源", "价税合计 ¥{amt} 用量 {usage} kWh 计费周期 {period}",
     "价税合计[^0-9]{0,30}([0-9,]+\\.[0-9]{2})", None),
]


# L3 账单附件沿用 skill/profiles/sources.json 的默认来源与措辞，
# 使离线全链路无需改任何配置即可真解析；L2 的新机构用于单独练习改正则。
L3_BILL_SOURCES = [
    ("demo_card", "示例信用卡 A",
     "示例信用卡 A 电子账单（虚构） 本期应还金额：¥{amt} 最低还款额：¥{min_amt} 账单周期 {period}-01 至 {period}-31"),
    ("demo_card_b", "示例信用卡 B",
     "示例信用卡 B 电子账单（虚构） 应还款总额：¥{amt} 最低还款：¥{min_amt} 账单周期 {period}"),
    ("demo_utility", "示例电费",
     "示例电费电子发票（虚构） 价税合计（小写）¥{amt} 用电量 {usage} kWh 计费周期 {period}"),
]


def _money(v):
    return "{:,.2f}".format(v)


def _csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _text(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def gen_l1():
    d = os.path.join(FIX, "L1_csv")
    salary_rows = []
    for y, period in MONTHS:
        i = int(period[5:7]) - 1
        gross = (16500.00 if y == 2025 else 18500.00) + i * 75.00
        social = 3600.00
        tax = round((gross - social - 5000.00) * 0.10 + i * 10.00, 2)
        net = round(gross - social - tax, 2)
        salary_rows.append(["月度", period, _money(gross), _money(1440.00), _money(360.00),
                            _money(90.00), _money(1710.00), _money(social), _money(tax), _money(net)])
    for y in YEARS:
        yr = [r for r in salary_rows if r[1].startswith(str(y))]
        totals = ["年度", str(y)] + [
            _money(sum(float(r[c].replace(",", "")) for r in yr)) for c in range(2, 10)]
        salary_rows.append(totals)
    _csv(os.path.join(d, "工资年度汇总.csv"), SALARY_COLUMNS, salary_rows)

    bill_rows = []
    for y, period in MONTHS:
        i = int(period[5:7]) - 1
        factor = 0.90 if y == 2025 else 1.00
        for idx, name in enumerate(L1_SOURCES):
            amt = round((980.00 + idx * 410.00 + i * 22.50) * factor, 2)
            bill_rows.append([name, period, _money(amt), _money(round(amt * 0.1, 2)),
                              "%s-01 ~ %s-31" % (period, period),
                              str(150 + i * 5) if idx == 2 else "", "已导入（虚构）",
                              "%s-%s.csv" % (period, idx)])
    _csv(os.path.join(d, "bills_parsed.csv"), BILL_COLUMNS, bill_rows)
    _text(os.path.join(d, "README.md"),
          "# L1 · 换一套脱敏 CSV\n\n"
          "把这两个文件复制到工作区覆盖同名文件，删掉 `IS_DUMMY.txt`（可选，保留则继续显示水印），"
          "再跑 `python skill/dashboard.py` 即可看到不同来源名与金额的看板。\n\n"
          "全部数值虚构，来源名为「示例生活卡 / 示例交通卡 / 示例水电」，与 L0 不同。\n")
    return len(salary_rows), len(bill_rows)


def gen_l2():
    d = os.path.join(FIX, "L2_bills")
    profiles = {"_comment": "L2 练习用：措辞与内置解析器完全不同，请照此改正则接入自己的账单。",
                "sources": []}
    n = 0
    for sub, label, template, amt_pat, min_pat in L2_SOURCES:
        patterns = {"amount": amt_pat}
        if min_pat:
            patterns["min_payment"] = min_pat
        if sub == "utility_gamma":
            patterns["usage"] = "([0-9]+\\.?[0-9]*)\\s*kWh"
        profiles["sources"].append({
            "name": sub, "label": label, "save_subdir": "bills/" + sub,
            "extensions": [".html", ".pdf"],
            "parser": {"type": "generic", "patterns": patterns},
        })
        for y, period in MONTHS[:6]:
            i = int(period[5:7]) - 1
            amt = (860.00 + i * 31.25) * (0.9 if y == 2025 else 1.0)
            body = template.format(amt=_money(round(amt, 2)), min_amt=_money(round(amt * 0.1, 2)),
                                   period=period, usage=150 + i * 5)
            _text(os.path.join(d, "bills", sub, period + ".html"),
                  "<!DOCTYPE html><html><head><meta charset='utf-8'><title>dummy</title>"
                  "</head><body>" + body + "</body></html>")
            n += 1
    _json(os.path.join(d, "sources.L2.json"), profiles)
    _text(os.path.join(d, "README.md"),
          "# L2 · 新机构账单 + 需自改的正则\n\n"
          "`bills/` 下 3 个虚构机构、每个 6 个月共 18 份 HTML，措辞与内置解析器完全不同。\n\n"
          "复刻步骤：把 `sources.L2.json` 的内容合并进 `skill/profiles/sources.json`，"
          "把 `bills/` 复制到工作区 `data/bills/`，跑 `python skill/bill_parser.py` 验证能解析出金额，"
          "再跑 `python skill/dashboard.py`。\n\n"
          "若显示「未匹配到金额」，就是正则与自己账单文字不符 —— 这正是 L2 要练的部分。\n")
    return n


def _write_xlsx(path, period, y, i):
    """生成脱敏工资条 xlsx：A 列标签、B 列数值，与 DEFAULT_FIELD_MAP 对齐。"""
    from openpyxl import Workbook
    base = (16500.00 if y == 2025 else 18500.00) + i * 75.00
    gross = round(base, 2)
    social = 3600.00
    tax = round((gross - social - 5000.00) * 0.10 + i * 10.00, 2)
    net = round(gross - social - tax, 2)
    rows = [
        ("示例工资条（虚构数据）", ""),
        ("期间", period),
        ("本期工资", gross),
        ("养老保险", 1440.00),
        ("医疗保险", 360.00),
        ("失业保险", 90.00),
        ("住房公积金", 1710.00),
        ("个人所得税", tax),
        ("实发工资", net),
    ]
    wb = Workbook()
    ws = wb.active
    ws.title = "工资条"
    for r in rows:
        ws.append(list(r))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb.save(path)


def gen_l3():
    d = os.path.join(FIX, "L3_mail")
    att = os.path.join(d, "attachments")
    manifest = []
    n_xlsx = 0
    for y, period in MONTHS:
        i = int(period[5:7]) - 1
        rel = "工资条/%s.xlsx" % period
        _write_xlsx(os.path.join(att, rel), period, y, i)
        n_xlsx += 1
        manifest.append({
            "folder": "INBOX", "from": "hr-notice@example.com",
            "subject": "示例工资条 %s" % period, "attachment": rel,
            "target": "%s.xlsx" % period,
        })

    n_html = 0
    for sub, label, template in L3_BILL_SOURCES:
        for y, period in MONTHS:
            i = int(period[5:7]) - 1
            amt = (860.00 + i * 31.25) * (0.9 if y == 2025 else 1.0)
            body = template.format(amt=_money(round(amt, 2)), min_amt=_money(round(amt * 0.1, 2)),
                                   period=period, usage=150 + i * 5)
            rel = "bills/%s/%s.html" % (sub, period)
            _text(os.path.join(att, rel),
                  "<!DOCTYPE html><html><head><meta charset='utf-8'><title>dummy</title>"
                  "</head><body>" + body + "</body></html>")
            manifest.append({
                "folder": "INBOX", "from": "statement@%s.example.org" % sub,
                "subject": "%s 电子账单 %s" % (label, period), "attachment": rel,
                "target": "bills/%s/%s.html" % (sub, period),
            })
            n_html += 1

    _json(os.path.join(d, "mailbox_manifest.json"), {
        "_comment": "模拟邮箱邮件清单，全部虚构；simulate_fetch.py 依此把附件放进工作区，等价于离线 IMAP 下载。",
        "messages": manifest,
    })
    _json(os.path.join(d, "imap.config.example.json"), {
        "_comment": "接真实邮箱时复制为 config.json 并替换占位值；本包不含任何真实凭据。",
        "email": "<your-email@example.com>", "auth_code": "<app-password>",
        "imap_server": "imap.example.com", "imap_port": 993,
        "save_dir": "workspace", "state_file": "state.json",
        "extensions": [".xls", ".xlsx", ".pdf"],
        "analysis": {"xls_password": "", "field_map": {}},
        "sources": [{"name": "salary", "label": "示例工资条",
                     "sender_keywords": ["hr-notice"], "subject_keywords": ["工资条"],
                     "save_subdir": "", "extensions": [".xls", ".xlsx"]}],
    })
    _text(os.path.join(d, "README.md"),
          "# L3 · 模拟邮箱（离线等价物）\n\n"
          "- `attachments/`：%d 份脱敏 `.xlsx` 工资条 + %d 份账单 HTML\n"
          "- `mailbox_manifest.json`：虚构邮件清单（发件人 / 主题 / 附件 / 落地路径）\n"
          "- `imap.config.example.json`：真实接入时的占位配置，**无任何真实凭据**\n\n"
          "跑 `python scripts/simulate_fetch.py` 等价于「从邮箱下载附件」，但全程离线、不联网。"
          "接真实邮箱时把上面的占位配置复制成 `config.json` 填自己的值，"
          "改用 `python skill/salary_pipeline.py fetch --dry-run` 验证命中后再正式抓取。\n" % (n_xlsx, n_html))
    return n_xlsx, n_html


def gen_l4():
    d = os.path.join(FIX, "L4_pipeline")
    _json(os.path.join(d, "field_map.example.json"), {
        "_comment": "工资条模板不同时，把这段合并进 config.json 的 analysis.field_map 覆盖默认关键词。",
        "gross": ["本期工资", "应发合计"], "pension": ["养老保险"],
        "medical": ["医疗保险"], "unemployment": ["失业保险"],
        "housing": ["住房公积金"], "tax": ["个人所得税"], "net": ["实发工资"],
    })
    _text(os.path.join(d, "schedule.example.md"),
          "# L4 · 定时任务示例（本包不自动注册）\n\n"
          "## Windows 任务计划（示例命令，需自己创建任务）\n"
          "```bat\n"
          "set SALARY_DATA_DIR=<本目录绝对路径>\\workspace\n"
          "python <本目录绝对路径>\\scripts\\run_all.py\n"
          "```\n\n"
          "## Linux / macOS cron（每月 1 日 09:00）\n"
          "```cron\n"
          "0 9 1 * * cd /path/to/replica-kit && SALARY_DATA_DIR=$PWD/workspace python scripts/run_all.py >> workspace/run.log 2>&1\n"
          "```\n\n"
          "说明：`run_all.py` 是离线全链路（模拟抓取 → 工资解析 → 账单解析 → 看板 → 门禁）。"
          "接真实环境时把 `simulate_fetch.py` 换成 `salary_pipeline.py fetch`，并配置 IMAP 凭据。\n")
    _text(os.path.join(d, "README.md"),
          "# L4 · 完整流水线配套\n\n"
          "- `field_map.example.json`：工资条字段映射覆盖示例\n"
          "- `schedule.example.md`：Windows / cron 定时命令示例（**不自动注册任务**）\n"
          "- 顶层 `CONFIG-CHECKLIST.md`：L0–L4 全部必改 / 可选 / 勿改配置清单\n"
          "- 一键复刻：`python scripts/run_all.py`（产物在 `workspace/`）\n\n"
          "流水线形状与真实系统一致，但所有输入都是脱敏 fixtures；"
          "真实邮箱凭据、加密工资条密码、定时调度属于使用者自己的环境，本包不提供也不伪造。\n")
    return 3


def main():
    for sub in ("L1_csv", "L2_bills", "L3_mail", "L4_pipeline"):
        d = os.path.join(FIX, sub)
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d, exist_ok=True)
    s1 = gen_l1()
    n2 = gen_l2()
    s3 = gen_l3()
    n4 = gen_l4()
    print("[fixtures] L1: 工资 %d 行 / 账单 %d 行" % s1)
    print("[fixtures] L2: %d 份新机构账单 HTML" % n2)
    print("[fixtures] L3: %d 份脱敏 xlsx 工资条 + %d 份账单附件" % s3)
    print("[fixtures] L4: %d 个配套文件" % n4)
    print("[隔离] 全部写入", FIX)


if __name__ == "__main__":
    main()
