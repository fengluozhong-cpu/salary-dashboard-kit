#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一配置与路径解析（可分发层）
================================
设计目标：代码目录与数据目录物理分离，真实数据永不进入分发包。

数据目录优先级：
  1. 环境变量 SALARY_DATA_DIR  —— 显式指定工作区（验证 / 多套数据切换）
  2. config.json 的 save_dir    —— 本机私有配置，不进分发包
  3. <脚本目录>/data            —— 分发包默认工作区（只放 dummy 数据）

凭据优先级：环境变量 > config.json。config.json 明文仅供本机使用；
分发包里只有 config.example.json（全占位符，不含任何真实凭据）。

环境变量一览：
  SALARY_DATA_DIR       工作区目录
  SALARY_EMAIL          IMAP 登录账号
  SALARY_IMAP_AUTH_CODE IMAP 授权码
  SALARY_XLS_PASSWORD   工资条 xls 打开密码
"""

import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_NAME = "config.json"
EXAMPLE_CONFIG_NAME = "config.example.json"
PROFILES_REL = os.path.join("profiles", "sources.json")
STATE_NAME = "state.json"

ENV_DATA_DIR = "SALARY_DATA_DIR"
ENV_EMAIL = "SALARY_EMAIL"
ENV_AUTH_CODE = "SALARY_IMAP_AUTH_CODE"
ENV_XLS_PASSWORD = "SALARY_XLS_PASSWORD"

SALARY_CSV_NAME = "工资年度汇总.csv"
BILLS_CSV_NAME = "bills_parsed.csv"
DASHBOARD_NAME = "收支统一看板.html"


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def config_path():
    """本机优先读 config.json；分发包没有它时回退到脱敏模板。"""
    p = os.path.join(ROOT, CONFIG_NAME)
    if os.path.exists(p):
        return p
    ex = os.path.join(ROOT, EXAMPLE_CONFIG_NAME)
    if os.path.exists(ex):
        return ex
    raise FileNotFoundError("缺少 config.json 与 config.example.json")


def load_raw_config():
    return read_json(config_path())


def resolve_data_dir(cfg=None):
    env = os.environ.get(ENV_DATA_DIR)
    if env:
        return os.path.abspath(os.path.expanduser(env))
    # cfg 未显式传入时自动读本机配置；否则 bill_parser / merge_dashboard /
    # dashboard 等独立启动的脚本会误落到 <ROOT>/data（dummy 工作区），
    # 与 salary_pipeline 写入的真实目录错配。
    if cfg is None:
        try:
            cfg = load_raw_config()
        except FileNotFoundError:
            cfg = {}
    raw = (cfg or {}).get("save_dir") or ""
    if raw and raw not in ("data", "__DATA_DIR__", "__SAVE_DIR__"):
        return os.path.abspath(os.path.expanduser(raw))
    return os.path.join(ROOT, "data")


def apply_runtime_paths(cfg):
    """给一份已读入的 cfg 加上运行时解析后的路径与凭据覆盖（不改动原对象）。"""
    out = dict(cfg)
    analysis = dict(out.get("analysis") or {})
    out["analysis"] = analysis

    # 凭据：环境变量优先；config.json 明文只是本机兜底
    out["email"] = os.environ.get(ENV_EMAIL, out.get("email", ""))
    out["auth_code"] = os.environ.get(ENV_AUTH_CODE, out.get("auth_code", ""))
    analysis["xls_password"] = os.environ.get(
        ENV_XLS_PASSWORD, analysis.get("xls_password", ""))

    d = resolve_data_dir(out)
    out["data_dir"] = d
    out["save_dir"] = d

    # state 定位：
    #  - 显式设置了 SALARY_DATA_DIR（多工作区 / 多邮箱场景）→ state 跟随该工作区，
    #    避免不同邮箱共用一份 UID 去重状态而互相串数据；
    #  - 否则保持脚本目录，本机原有行为不变（现有月度自动化不受影响）。
    sf = out.get("state_file") or STATE_NAME
    if not os.path.isabs(sf):
        base = d if os.environ.get(ENV_DATA_DIR) else ROOT
        sf = os.path.join(base, sf)
    out["state_file"] = sf

    # 产物统一跟随 data_dir，杜绝散落的绝对路径
    analysis["report_html"] = os.path.join(d, "工资年度报表.html")
    analysis["summary_csv"] = os.path.join(d, SALARY_CSV_NAME)
    return out


def load_config():
    return apply_runtime_paths(load_raw_config())


def paths(cfg=None):
    """所有脚本共用的产物路径表；不再各自写死绝对路径。

    dummy 工作区（存在 IS_DUMMY.txt）的看板输出带 _DEMO 后缀，
    与真实数据目录下的「收支统一看板.html」不同名，避免预览/分发时混淆。
    """
    d = resolve_data_dir(cfg)
    is_dummy = os.path.exists(os.path.join(d, "IS_DUMMY.txt"))
    dashboard_name = "收支统一看板_DEMO.html" if is_dummy else DASHBOARD_NAME
    return {
        "data_dir": d,
        "salary_csv": os.path.join(d, SALARY_CSV_NAME),
        "bills_csv": os.path.join(d, BILLS_CSV_NAME),
        "bills_dir": os.path.join(d, "bills"),
        "dashboard_html": os.path.join(d, dashboard_name),
        "legacy_dashboard_html": os.path.join(d, "收支看板.html"),
        "annual_bill_csv": os.path.join(d, "账单年度汇总.csv"),
        "annual_bill_html": os.path.join(d, "账单年度汇总.html"),
        "download_index": os.path.join(d, "download_index.csv"),
    }


def profiles_path():
    return os.path.join(ROOT, PROFILES_REL)


def load_profiles():
    """读取可配置的来源 / 解析器定义；文件不存在时返回空列表。"""
    p = profiles_path()
    if not os.path.exists(p):
        return []
    data = read_json(p)
    return data.get("sources", []) if isinstance(data, dict) else data


def ensure_data_dir(cfg=None):
    d = resolve_data_dir(cfg)
    os.makedirs(d, exist_ok=True)
    os.makedirs(os.path.join(d, "bills"), exist_ok=True)
    return d


if __name__ == "__main__":
    p = paths()
    print("配置来源:", config_path())
    for k, v in p.items():
        print("  %-24s %s" % (k, v))
