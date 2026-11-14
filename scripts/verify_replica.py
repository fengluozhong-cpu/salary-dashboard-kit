#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交付门禁：结构完整性 + 隐私扫描 + 看板产物校验
================================================
用法：python scripts/verify_replica.py
退出码 0 = 全部通过，1 = 存在 FAIL。
"""

import json
import os
import re
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(KIT, "skill")
FIX = os.path.join(KIT, "fixtures")
WORK = os.path.join(KIT, "workspace")

TEXT_EXT = {".py", ".md", ".txt", ".json", ".csv", ".html", ".htm"}
DATA_EXT = {".csv", ".json", ".html", ".htm", ".txt"}
# 数据 / 配置文件：严格扫描，任何真实特征都不允许
BAD_DATA = [
    (r"@(?:163|126|qq|gmail|outlook|foxmail)\.com", "个人邮箱"),
    (r"C:/Users/", "本机用户目录"),
    (r"OneDrive", "云盘真实路径"),
    (r"Administrator", "本机用户名"),
    (r"fengluozhong", "个人信息"),
]
# 代码 / 文档：这些词会正当出现在「隔离规则描述」与断言条件里（元陈述），
# 只检查真实值特征，避免把规则本身误判为泄露。
BAD_DOC = [
    (r"@(?:163|126|qq|gmail|outlook|foxmail)\.com", "个人邮箱"),
    (r"C:/Users/[A-Za-z0-9._-]+/", "真实本机绝对路径"),
    (r"OneDrive/[^\s`]*[\u4e00-\u9fff]", "真实云盘中文路径"),
]

REQUIRED_FILES = [
    "README.md", "STRUCTURE.md", "CONFIG-CHECKLIST.md", "LICENSE",
    "skill/SKILL.md", "skill/dashboard.py", "skill/bill_parser.py",
    "skill/generic_parser.py", "skill/salary_pipeline.py",
    "skill/app_config.py", "skill/profiles/sources.json",
    "skill/config.example.json", "skill/requirements.txt",
    "skill/references/上手引导.md", "skill/references/数据格式.md",
    "skill/references/配置指南.md", "skill/references/飞书接入.md",
    "fixtures/L1_csv/工资年度汇总.csv", "fixtures/L1_csv/bills_parsed.csv",
    "fixtures/L2_bills/sources.L2.json", "fixtures/L3_mail/mailbox_manifest.json",
    "fixtures/L3_mail/imap.config.example.json",
    "fixtures/L4_pipeline/field_map.example.json",
    "fixtures/L4_pipeline/schedule.example.md",
    "scripts/build_fixtures.py", "scripts/simulate_fetch.py",
    "scripts/run_all.py", "scripts/verify_replica.py",
]

results = []


def check(name, ok, extra=""):
    results.append((name, bool(ok), extra))


def structure():
    for rel in REQUIRED_FILES:
        check("存在 " + rel, os.path.exists(os.path.join(KIT, rel)))
    check("skill/ 无 config.json", not os.path.exists(os.path.join(SKILL, "config.json")))
    check("skill/ 无 state.json", not os.path.exists(os.path.join(SKILL, "state.json")))
    for layer in ("L1_csv", "L2_bills", "L3_mail", "L4_pipeline"):
        check("fixtures 分层 " + layer, os.path.isdir(os.path.join(FIX, layer)))
    n_xlsx = sum(1 for b, _, fs in os.walk(os.path.join(FIX, "L3_mail", "attachments"))
                 for f in fs if f.endswith(".xlsx"))
    check("L3 脱敏 xlsx 工资条 >= 12", n_xlsx >= 12, "%d 份" % n_xlsx)


def privacy():
    hits = []
    scanned = 0
    for base, dirs, names in os.walk(KIT):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for n in names:
            ext = os.path.splitext(n)[1].lower()
            if ext not in TEXT_EXT:
                continue
            p = os.path.join(base, n)
            try:
                t = open(p, "r", encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            scanned += 1
            for pat, label in (BAD_DATA if ext in DATA_EXT else BAD_DOC):
                if re.search(pat, t, re.I):
                    hits.append((os.path.relpath(p, KIT), label))
    check("隐私扫描（%d 个文本文件；数据严格 / 文档元陈述豁免）" % scanned, not hits,
          "命中 %d 处" % len(hits) if hits else "零命中")
    for h in hits[:8]:
        print("   [FAIL] %s -> %s" % h)


def board():
    p = os.path.join(WORK, "收支统一看板_DEMO.html")
    if not os.path.exists(p):
        check("看板产物（未运行时可跳过）", True, "尚未生成")
        return
    t = open(p, "r", encoding="utf-8").read()
    check("看板 5 个菜单面板", t.count('class="tab-panel"') == 5)
    check("看板 dummy 水印", "演示数据（dummy）" in t)
    check("看板内嵌 JSON 可解析", _json_ok(t))
    check("看板无外链资源", "<script src" not in t and "<link" not in t)
    years = _years_of(t)
    check("看板含多个年度", len(years) >= 2, str(years))


def _json_ok(t):
    try:
        blob = t.split("const DATA = ", 1)[1].split(";\nfunction showTab", 1)[0]
        return bool(json.loads(blob).get("monthly"))
    except Exception:
        return False


def _years_of(t):
    try:
        blob = t.split("const DATA = ", 1)[1].split(";\nfunction showTab", 1)[0]
        return json.loads(blob).get("years", [])
    except Exception:
        return []


def main():
    structure()
    privacy()
    board()
    print("=== 复刻包交付门禁 ===")
    for name, ok, extra in results:
        print("  [%s] %s %s" % ("PASS" if ok else "FAIL", name, extra))
    bad = [r for r in results if not r[1]]
    print("\n结论:", "全部通过" if not bad else "%d 项 FAIL" % len(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
