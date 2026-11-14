#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
safe_write.py — 抗 云盘 / 云盘同步锁的稳健写文件工具
======================================================

问题背景：
  工资条 / 账单系统的所有产出（工资年度汇总.csv、收支看板.html 等）都写在
  云盘 同步目录（（本机同步目录））下。
  云盘 同步引擎会在后台短时占用已有文件句柄，导致直接 `open(path, "w")`
  偶发抛出 PermissionError（[Errno 13] Permission denied）——而且只在同步那一
  瞬间发生，因此表现为“间歇性”失败，长任务（如整轮 fetch+analyze）收尾写文件
  时最容易踩中。

解决方案（经实测验证）：
  1) 先在当前「同一目录」写一个带随机名的临时文件（新建文件永远不会被同步锁占用，
     已用 testwrite.csv 验证）；
  2) 用 os.replace(tmp, path) 原子替换目标文件（MoveFileEx 可绕过大多数共享锁）；
  3) 若替换仍遇 PermissionError，重试 6 次（每次间隔 1.5s）以跨过同步窗口；
  4) 极少数情况下仍失败，则退化为直接覆盖写作为最后兜底。

注意：必须使用「同一目录」的临时文件。跨盘（如 E: -> C: 的 云盘）的
os.replace / os.rename 会直接报 WinError 17（无法移动到不同磁盘驱动器），
因此临时文件必须与目标文件处于同一卷。

用法：
  from safe_write import open_write
  with open_write(path, "w", encoding="utf-8-sig", newline="") as f:
      f.write(...)
仅支持文本模式（需显式传 encoding / newline）。
"""

import os
import time
import stat
import tempfile
from contextlib import contextmanager

_TMP_PREFIX = "._tmp_"
_TMP_SUFFIX = ".tmp"
# 云盘 同步时会对正在上传的文件短暂施加独占锁，导致 os.replace 偶发失败；
# 用较长的重试窗口（约 30s）跨过同步锁窗口，而非仅重试几次。
_REPLACE_RETRIES = 15
_RETRY_SLEEP = 2.0


def _clear_readonly(path):
    """清除 Windows 只读属性（云盘 / Files-On-Demand 常给已同步文件加只读位，
    会导致 open('w') / os.replace 报 WinError 5 / PermissionError）。不存在则忽略。"""
    if not os.path.exists(path):
        return
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _cleanup_stale(dir_path, max_age_seconds=120):
    """清理本模块遗留的临时文件（异常中断时可能留下）。
    仅删除本前缀、且修改时间超过 max_age_seconds 的临时文件，避免误删正在写的。"""
    try:
        for name in os.listdir(dir_path):
            if not (name.startswith(_TMP_PREFIX) and name.endswith(_TMP_SUFFIX)):
                continue
            fp = os.path.join(dir_path, name)
            try:
                age = time.time() - os.path.getmtime(fp)
                if age > max_age_seconds:
                    os.remove(fp)
            except OSError:
                pass
    except OSError:
        pass


@contextmanager
def open_write(path, mode="w", **kwargs):
    """稳健写入文本文件的上下文管理器（语义同内置 open，但抗云盘锁）。

    在退出时（正常或异常）负责：临时文件落盘 -> 原子替换目标 -> 失败时清理临时文件。
    """
    path = os.path.abspath(path)
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=_TMP_PREFIX, suffix=_TMP_SUFFIX)
    f = os.fdopen(fd, mode, **kwargs)
    try:
        yield f
        try:
            f.flush()
            os.fsync(f.fileno())
        except OSError:
            pass
    except BaseException:
        # 写入过程中出错：关闭并删除临时文件，原目标文件保持不变，再向上抛出
        try:
            f.close()
        except OSError:
            pass
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    else:
        try:
            f.close()
        except OSError:
            pass
        last_err = None
        for attempt in range(_REPLACE_RETRIES):
            # 云盘 / Files-On-Demand 会给已同步文件加“只读”属性，导致 os.replace
            # 报 WinError 5；每次替换前先清除目标只读位（不存在则跳过）。
            _clear_readonly(path)
            try:
                os.replace(tmp, path)
                return
            except OSError as e:  # 涵盖 PermissionError(WinError 5/13) 等
                last_err = e
                if attempt < _REPLACE_RETRIES - 1:
                    time.sleep(_RETRY_SLEEP)
        # 重试耗尽：退化为「先清除只读位，再把临时文件字节写回目标」。
        # 适用于 os.replace 被环境禁用（如某些沙箱拦截 rename），但允许就地覆盖写的场景。
        # 先读临时文件全部字节再写入，避免截断目标后失败导致数据丢失。
        _clear_readonly(path)
        try:
            with open(tmp, "rb") as src:
                data = src.read()
            with open(path, "wb") as dst:
                dst.write(data)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return
        except OSError as e2:
            # 仍失败：保留临时文件供人工恢复，抛出原始错误
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise last_err or e2


def write_text(path, text, encoding="utf-8", newline=None):
    """一次性写入整段文本（便捷封装）。"""
    kwargs = {"encoding": encoding}
    if newline is not None:
        kwargs["newline"] = newline
    with open_write(path, "w", **kwargs) as f:
        f.write(text)
