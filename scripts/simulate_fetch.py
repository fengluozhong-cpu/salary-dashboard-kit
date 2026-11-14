#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L3 · 离线模拟邮箱抓取（真实 IMAP 的等价物）
============================================
读 fixtures/L3_mail/mailbox_manifest.json，把 attachments/ 下的脱敏附件
按清单落地到 workspace/，产出与「IMAP 下载附件」完全相同的目录结构：
  workspace/YYYY-MM.xlsx              工资条（salary_pipeline analyze 读）
  workspace/bills/<来源>/YYYY-MM.html 账单（bill_parser 读）
  workspace/download_index.csv       模拟下载索引
  workspace/IS_DUMMY.txt             演示标记

全程离线、零凭据、零网络。接真实邮箱时改用 skill/salary_pipeline.py fetch。
"""

import csv
import json
import os
import shutil

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(KIT, "workspace")
ATT = os.path.join(KIT, "fixtures", "L3_mail", "attachments")
MANIFEST = os.path.join(KIT, "fixtures", "L3_mail", "mailbox_manifest.json")


def _norm(p):
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def assert_isolated(target):
    """硬隔离：只允许写 replica-kit/workspace，绝不碰真实数据目录。"""
    if os.path.basename(KIT) != "replica-kit":
        raise RuntimeError("隔离失败：脚本不在 replica-kit 下")
    k, t = _norm(KIT), _norm(target)
    if not t.startswith(k + os.sep):
        raise RuntimeError("隔离失败：目标越出复刻包 -> %s" % target)
    for bad in ("OneDrive", "Administrator"):
        if bad in target:
            raise RuntimeError("隔离失败：目标含真实目录特征 %s" % bad)


def main(target=None):
    work = target or WORK
    assert_isolated(work)

    if os.path.isdir(work):
        for name in os.listdir(work):
            p = os.path.join(work, name)
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
    os.makedirs(work, exist_ok=True)

    with open(MANIFEST, "r", encoding="utf-8") as f:
        messages = json.load(f)["messages"]

    index = []
    for m in messages:
        src = os.path.join(ATT, m["attachment"])
        dst = os.path.join(work, m["target"])
        if not os.path.exists(src):
            raise FileNotFoundError("清单里的附件缺失: " + src)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        index.append([m["folder"], m["from"], m["subject"], m["attachment"], m["target"]])

    with open(os.path.join(work, "download_index.csv"), "w",
              encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["文件夹", "发件人", "主题", "原始附件", "落地路径"])
        w.writerows(index)

    with open(os.path.join(work, "IS_DUMMY.txt"), "w", encoding="utf-8") as f:
        f.write("本工作区由离线模拟抓取生成，全部数据为虚构 fixtures，不含任何真实收支。\n"
                "dashboard.py 检测本文件后会在看板顶部显示演示水印，并输出 _DEMO.html。\n")

    print("[L3 模拟抓取] 邮件 %d 封 | 附件落地 %d 份 | 工作区 %s" % (
        len(messages), len(index), work))
    return work


if __name__ == "__main__":
    main()
