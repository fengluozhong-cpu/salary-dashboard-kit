#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
首次使用状态检测（只读、零网络）
================================
Agent 调用本 Skill 时**先跑这个脚本**，据真实状态决定从引导的哪一步开始，
不要凭印象把整张上手清单一次念给用户。

用法：
  python setup_check.py          人类可读状态 + 下一步建议
  python setup_check.py --json   机器可读（供 Agent 解析）

隐私：只报告凭据「是否已设置」，绝不打印邮箱地址、授权码或密码的值。
"""

import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from app_config import (ENV_AUTH_CODE, ENV_DATA_DIR, ENV_EMAIL,
                        load_profiles, paths)


def _data_rows(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            rows = [r for r in csv.reader(f) if r]
        return max(len(rows) - 1, 0)
    except Exception:
        return None


def collect():
    p = paths()
    d = p["data_dir"]
    state = {
        "data_dir": d,
        "is_dummy": os.path.exists(os.path.join(d, "IS_DUMMY.txt")),
        "config_exists": os.path.exists(os.path.join(ROOT, "config.json")),
        "salary_rows": _data_rows(p["salary_csv"]),
        "bills_rows": _data_rows(p["bills_csv"]),
        "bill_dirs": {},
        "profile_sources": len(load_profiles()),
        "env_data_dir": bool(os.environ.get(ENV_DATA_DIR)),
        "env_email": bool(os.environ.get(ENV_EMAIL)),
        "env_auth_code": bool(os.environ.get(ENV_AUTH_CODE)),
        "dashboard_exists": os.path.exists(p["dashboard_html"]),
    }
    bills_dir = p["bills_dir"]
    if os.path.isdir(bills_dir):
        for sub in sorted(os.listdir(bills_dir)):
            fp = os.path.join(bills_dir, sub)
            if os.path.isdir(fp):
                state["bill_dirs"][sub] = sum(
                    1 for n in os.listdir(fp)
                    if n.lower().endswith((".html", ".pdf")))

    tips = []
    if state["is_dummy"]:
        tips.append("仍是演示数据：先问用户「只看演示」还是「接入自己的数据」")
        tips.append("接入真实数据前删除 data/IS_DUMMY.txt，否则看板一直带 dummy 水印")
    if not state["config_exists"] and not (state["env_email"] and state["env_auth_code"]):
        tips.append("未配置邮箱凭据：若要邮箱抓取，复制 config.example.json 为 config.json，"
                    "或设置 SALARY_EMAIL / SALARY_IMAP_AUTH_CODE 环境变量")
    if state["salary_rows"] is None:
        tips.append("缺 工资年度汇总.csv：按 references/数据格式.md 的 10 列准备")
    if state["bills_rows"] is None:
        tips.append("缺 bills_parsed.csv：把账单放进 data/bills/<来源>/ 后运行 python bill_parser.py")
    if not state["bill_dirs"]:
        tips.append("暂无账单来源目录：按 profiles/sources.json 的 save_subdir 建对应子目录")
    if not state["dashboard_exists"]:
        tips.append("尚未生成看板：数据齐后运行 python dashboard.py")
    if state["is_dummy"] and state["salary_rows"] and state["bills_rows"]:
        tips.append("演示数据已可跑通：可以先 python dashboard.py 让用户看效果，再决定是否接真实数据")
    state["next_steps"] = tips
    return state


def main():
    s = collect()
    if "--json" in sys.argv:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0

    def yn(v):
        return "是" if v else "否"

    def rows(v):
        return "不存在" if v is None else "%d 行" % v

    print("=== 工作区状态（只读检测，无网络请求）===")
    print("  工作区              :", s["data_dir"])
    print("  仍是 dummy 演示数据 :", yn(s["is_dummy"]))
    print("  私有配置 config.json:", yn(s["config_exists"]))
    print("  工资年度汇总.csv    :", rows(s["salary_rows"]))
    print("  bills_parsed.csv    :", rows(s["bills_rows"]))
    print("  来源配置数量        :", s["profile_sources"])
    print("  账单目录            :", ", ".join(
        "%s(%d 份)" % (k, v) for k, v in s["bill_dirs"].items()) or "无")
    print("  看板已生成          :", yn(s["dashboard_exists"]))
    print("  邮箱凭据环境变量    : SALARY_EMAIL=%s / SALARY_IMAP_AUTH_CODE=%s（不显示值）" % (
        yn(s["env_email"]), yn(s["env_auth_code"])))
    print("  多工作区环境变量    : SALARY_DATA_DIR=%s" % yn(s["env_data_dir"]))

    print("\n=== 下一步建议（按从上到下推进，每次只问用户一个问题）===")
    for i, t in enumerate(s["next_steps"], 1):
        print("  %d. %s" % (i, t))
    if not s["next_steps"]:
        print("  （无明显缺口，可直接运行 python dashboard.py 重生成看板）")
    print("\n详细引导见 SKILL.md「首次使用引导」与 references/上手引导.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
