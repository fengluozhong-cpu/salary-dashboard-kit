# L4 · 定时任务示例（本包不自动注册）

## Windows 任务计划（示例命令，需自己创建任务）
```bat
set SALARY_DATA_DIR=<本目录绝对路径>\workspace
python <本目录绝对路径>\scripts\run_all.py
```

## Linux / macOS cron（每月 1 日 09:00）
```cron
0 9 1 * * cd /path/to/replica-kit && SALARY_DATA_DIR=$PWD/workspace python scripts/run_all.py >> workspace/run.log 2>&1
```

说明：`run_all.py` 是离线全链路（模拟抓取 → 工资解析 → 账单解析 → 看板 → 门禁）。接真实环境时把 `simulate_fetch.py` 换成 `salary_pipeline.py fetch`，并配置 IMAP 凭据。
