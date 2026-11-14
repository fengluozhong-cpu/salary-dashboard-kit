# 配置清单（L0–L4）

标记：**必改** = 接自己的数据/环境时必须替换；**可选** = 按需调整；**勿改** = 改动会破坏复刻链路。

## L0 · 直接出演示看板

| 配置项 | 标记 | 默认 | 说明 |
|---|---|---|---|
| 任何配置 | — | 无需配置 | `python skill/dashboard.py` 直接出 `skill/data/收支统一看板_DEMO.html` |
| `SALARY_DATA_DIR` | 可选 | `skill/data` | 想换工作区时设；`run_all.py` 会自动设成 `workspace/` |

## L1 · 换一套数据

| 配置项 | 标记 | 默认 | 说明 |
|---|---|---|---|
| `工资年度汇总.csv` | **必改** | `fixtures/L1_csv/` 的虚构 10 列 | 只认「月度」行，固定列索引，期间格式 `YYYY-MM` |
| `bills_parsed.csv` | **必改** | `fixtures/L1_csv/` 的虚构 8 列 | 列名/顺序见 `skill/references/数据格式.md` |
| `IS_DUMMY.txt` | 可选 | 存在 | 删掉后水印消失、输出改回 `收支统一看板.html`；演示阶段建议保留 |
| 来源名 | 可选 | 示例生活卡 / 示例交通卡 / 示例水电 | 看板自动按 CSV 里的「来源」聚合，无需改代码 |

## L2 · 接入新机构账单

| 配置项 | 标记 | 默认 | 说明 |
|---|---|---|---|
| `skill/profiles/sources.json` 的 `patterns` | **必改** | `fixtures/L2_bills/sources.L2.json` 示例 | 每条正则用第 1 个捕获组取目标值；JSON 里反斜杠写两次 |
| `save_subdir` 末段 | **必改** | `bills/card_alpha` 等 | 必须与磁盘目录名完全一致，否则该来源被静默跳过 |
| `parser.type` | 可选 | `generic` | `builtin` 仅适合内置 5 家历史排版，换机构一律用 `generic` |
| `PyMuPDF` | 可选 | `requirements.txt` 列出 | 解析 PDF 账单需要；扫描件取不到文字，需人工补 CSV |

## L3 · 邮箱抓取

| 配置项 | 标记 | 默认 | 说明 |
|---|---|---|---|
| 离线等价物 | — | `scripts/simulate_fetch.py` | 本包默认走这条，零凭据、零网络 |
| `config.json` | **必改（仅接真实邮箱时）** | 不存在 | 从 `fixtures/L3_mail/imap.config.example.json` 复制，替换 `<your-email@example.com>` / `<app-password>` / `imap_server` |
| 环境变量 `SALARY_EMAIL` / `SALARY_IMAP_AUTH_CODE` | 可选 | 未设 | 优先级高于 `config.json`，推荐用环境变量避免明文 |
| `sources[].sender_keywords` / `subject_keywords` | **必改** | 示例 `hr-notice` / `工资条` | 换成自己单位发件人与主题关键词 |
| 验证顺序 | **必改** | — | 先 `python skill/salary_pipeline.py fetch --dry-run`，命中无误再去掉 `--dry-run` |
| 多邮箱 | 可选 | 单工作区 | 用 `SALARY_DATA_DIR` 分工作区 + 各自环境变量分别抓，再合并 `bills_parsed.csv` |

## L4 · 完整流水线

| 配置项 | 标记 | 默认 | 说明 |
|---|---|---|---|
| `scripts/run_all.py` | — | 一键运行 | 强制把工作区锁到 `<本目录>/workspace`，无需手动配置 |
| `requirements.txt` 的 `openpyxl` | 可选 | 建议安装 | 解析 xlsx 工资条；缺失时 `run_all.py` 自动降级用 L1 脱敏 CSV，链路不中断 |
| `analysis.field_map` | **必改（工资条模板不同时）** | `fixtures/L4_pipeline/field_map.example.json` | 覆盖工资条关键词，如「应发合计 / 实发工资」 |
| `analysis.xls_password` | **必改（加密工资条时）** | 空 | 也可设环境变量 `SALARY_XLS_PASSWORD`；需 `msoffcrypto-tool` |
| 定时调度 | **必改（接真实环境时）** | `fixtures/L4_pipeline/schedule.example.md` | 本包不自动注册任务，只给 Windows 任务计划 / cron 示例命令 |
| 输出目录 | 勿改 | `workspace/` | 硬隔离断言依赖此目录 |
| `scripts/verify_replica.py` | 可选 | 自动在 `run_all.py` 末尾运行 | 也可单独跑，检查结构 + 隐私 + 看板产物 |

## 🚫 勿改清单

| 文件 | 原因 |
|---|---|
| `app_config.py` | 唯一路径来源；改动会破坏隔离与多工作区逻辑 |
| `dashboard.py` 的数据读取与占位符契约 | 验收脚本依赖 5 个 `tab-panel`、`class='dbtn'` 单引号、内嵌 `const DATA` |
| `IS_DUMMY.txt` 的**文件名** | 看板据此决定水印与 `_DEMO.html` 输出名 |
| `skill/` 内不要新建 `config.json` 再提交 | 那是使用者私有文件，发布仓库应始终排除 |

## 接真实环境的最小替换集

1. 复制 `imap.config.example.json` → 自己的 `config.json`（或改用环境变量）
2. 改 `sender_keywords` / `subject_keywords` / `save_subdir`
3. 按自己账单文字改 `profiles/sources.json` 的正则
4. 按自己工资条模板改 `analysis.field_map`，加密则填密码
5. 把 `simulate_fetch.py` 换成 `salary_pipeline.py fetch`，先 `--dry-run`
6. 删 `IS_DUMMY.txt`，按 `schedule.example.md` 设定时任务

**以上全部是配置替换，不需要改 Python 代码。** 详见 `skill/references/上手引导.md` 与 `配置指南.md`。
