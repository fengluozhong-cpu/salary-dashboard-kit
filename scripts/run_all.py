#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L4 · 一键离线全链路（复刻完整看板）
=====================================
串联：模拟抓取 -> 工资条 xlsx 解析 -> 账单 HTML 解析 -> 单页看板 -> 交付门禁
所有输入来自 fixtures/，所有产物只写 replica-kit/workspace/，全程离线零凭据。

用法：python scripts/run_all.py
产物：workspace/收支统一看板_DEMO.html

降级：若未安装 openpyxl（工资条 xlsx 解析所需），自动改用 L1 的脱敏工资 CSV，
      仍可完整产出看板，不会中断。
"""

import csv
import os
import shutil
import subprocess
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(KIT, "skill")
SCRIPTS = os.path.join(KIT, "scripts")
WORK = os.path.join(KIT, "workspace")
sys.path.insert(0, SCRIPTS)
import simulate_fetch

ENV = dict(os.environ)
ENV["SALARY_DATA_DIR"] = WORK  # 硬隔离：所有子脚本只写本包工作区


def _norm(p):
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def assert_isolated():
    k, w = _norm(KIT), _norm(WORK)
    if os.path.basename(KIT) != "replica-kit" or not w.startswith(k + os.sep):
        raise RuntimeError("隔离失败：工作区不在 replica-kit 内 -> " + WORK)
    for bad in ("OneDrive", "Administrator"):
        if bad in WORK:
            raise RuntimeError("隔离失败：工作区含真实目录特征 " + bad)


def _exec(path, args=None, label=""):
    cmd = [sys.executable, path] + (args or [])
    r = subprocess.run(cmd, cwd=os.path.dirname(path), env=ENV,
                       capture_output=True, text=True)
    out = (r.stdout or "").strip()
    if out:
        print("  " + out.splitlines()[-1])
    if r.returncode != 0:
        print("  [错误] %s: %s" % (label, (r.stderr or "").strip().splitlines()[-1:]))
    return r.returncode == 0


def _salary_has_rows(path):
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return any(r and r[0] == "月度" for r in csv.reader(f))
    except Exception:
        return False


def main():
    assert_isolated()

    print("=== [1/5] L3 离线模拟抓取 ===")
    simulate_fetch.main(WORK)

    print("=== [2/5] L4 工资条 xlsx 解析（salary_pipeline analyze）===")
    ok = _exec(os.path.join(SKILL, "salary_pipeline.py"), ["analyze"], "salary_pipeline")
    salary_csv = os.path.join(WORK, "工资年度汇总.csv")
    if not ok or not _salary_has_rows(salary_csv):
        shutil.copy2(os.path.join(KIT, "fixtures", "L1_csv", "工资年度汇总.csv"), salary_csv)
        print("  [降级] openpyxl 不可用或 xlsx 解析为空，改用 L1 脱敏工资 CSV，看板仍完整")

    print("=== [3/5] L4 账单解析（bill_parser）===")
    _exec(os.path.join(SKILL, "bill_parser.py"), label="bill_parser")

    print("=== [4/5] L4 生成单页看板（dashboard）===")
    _exec(os.path.join(SKILL, "dashboard.py"), label="dashboard")

    print("=== [5/5] 交付门禁（verify_replica）===")
    ok = _exec(os.path.join(SCRIPTS, "verify_replica.py"), label="verify_replica")

    board = os.path.join(WORK, "收支统一看板_DEMO.html")
    print("\n产物:", board if os.path.exists(board) else "未生成")
    print("门禁:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
