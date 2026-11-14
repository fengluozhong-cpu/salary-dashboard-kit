---
name: salary-dashboard
description: 从本地工资汇总 CSV 与账单 CSV/HTML 生成单页收支看板；内置首次使用引导，支持按自己的账单改配置来源、用多工作区分别接入邮箱账号（单进程原生多邮箱账号不支持）、把账单解析到 L1（每份账单的最低还款额、账单周期、用电量、状态、原始文件；逐笔交易（日期 / 商户 / 单笔金额 / 消费分类）未解析），看板内嵌 JSON。当用户要求「生成/更新收支看板」「怎么开始」「首次使用」「配置数据源」「接入邮箱」「按我的账单配置来源」「解析账单」「重跑看板」时使用。
---

# 收支看板 Skill

唯一交付物 `data/收支统一看板_DEMO.html`：自包含单页，菜单切换总览 / 收入 / 支出 / 支出明细 / 数据源，支出细节默认收起、双击离线打开。

## 红线（必须先读）

### 🚫 禁止
- 本包**不含任何真实收支数据**，随包 `data/` 全是虚构 dummy 数据；不得把真实数据写回本包、复制进共享位置或上传。
- 不得替用户填写 / 回显 / 记录真实邮箱地址 / IMAP 授权码 / 密码；凭据由用户本地配置或设环境变量。
- 不得把真实凭据贴进聊天、日志或看板。

### ✅ 允许 / 边界
- **默认不需要邮箱账号**：两张 CSV 放进 `data/` 即可生成看板；只有用户选择接入邮箱时才需要凭据。
- **零网络声明（全篇唯一）**：全包仅 `salary_pipeline.py` 在用户显式执行 `fetch`（含 `list` / `run`）时连 IMAP；其余脚本全程本地、不上传，本 Skill 不含同步代码。可执行核验见引导「隐私核验」。
- `data/IS_DUMMY.txt` 存在时看板显示「演示数据」水印；接入真实数据前删除并重跑看板。

## 首次使用引导（Agent 必须先执行）

**触发条件**：满足任一即进入引导 —— 首次调用 / `setup_check.py` 报告仍是 dummy / 用户问「怎么开始」「要配什么」「接邮箱」「加数据源」「多个邮箱怎么办」。

### 铁律
- **先跑 `python setup_check.py`**，不要凭印象把上手清单一次念给用户。
- **每次只问一个问题**；得到答案 → 执行 → 验证 → 再问下一个；一个源验证通过再问「还有别的要接吗？」。
- 不谎称能力：**单进程原生多邮箱账号不支持**，多邮箱走「多工作区」；其他数据源靠整理成 8 列 CSV 接入。
- 失败按「失败分支」处理，**仍失败则停下并报告用户，不进入下一步**。

### 步骤编号（唯一口径，与 `references/上手引导.md` 第 0–6 步完全一致）

完整操作见引导同号步骤，本文件不复述；全篇只用这一套编号：

- 第 0 步 · 查状态 → 失败分支 1
- 第 1 步 · 问用途 → 🔴 CHECKPOINT ①
- 第 2 步 · 问数据来源 → 🔴 CHECKPOINT ②
- 第 3 步 · 逐源接入与验证（含多工作区）→ 🔴 CHECKPOINT ④、失败分支 2 / 3
- 第 4 步 · 合并多份 `bills_parsed.csv` → 失败分支 4
- 第 5 步 · 生成看板并量化核对 → 失败分支 5
- 第 6 步 · 删除 `IS_DUMMY.txt` 后重生成 → 🔴 CHECKPOINT ③

### 四个决策点（未确认时的停留动作）

**① 第 1 步 问用途**

🔴 CHECKPOINT：等待用户明确回答/确认后方可继续

停留动作：只输出「先看演示，还是直接接自己的数据？」；不跑 `python dashboard.py`、不进第 2 步；未回答原地等待，不替用户选。

**② 第 2 步 问数据来源**

🔴 CHECKPOINT：等待用户明确回答/确认后方可继续

停留动作：只列 A 本地 CSV / B 邮箱 IMAP / C 其他数据源三个硬选项等用户勾选；不预填来源、不开始第 3 步；未回答原地等待。凭据硬取值：A 无、B IMAP 授权码、C 无（前提：用户本地把来源导出成 CSV）。

**③ 第 6 步 删除 `IS_DUMMY.txt` 前**

🔴 CHECKPOINT：等待用户明确回答/确认后方可继续

停留动作：先展示第 5 步量化核对结果，问「数值一致，是否现在删 `data/IS_DUMMY.txt` 并重生成？」；未确认不执行 `rm data/IS_DUMMY.txt`、不重跑 `python dashboard.py`。

**④ 第 3 步 B 去掉 `--dry-run` 正式抓取前**

🔴 CHECKPOINT：等待用户明确回答/确认后方可继续

停留动作：贴出 `--dry-run` 命中清单与量化结果，问「命中无误，是否去掉 `--dry-run` 正式抓取？」；未确认不再执行任何 `fetch`、不跑 `bill_parser.py`。命中不符走失败分支 3，不进入本确认环节。

## 失败分支（触发条件 / 一线修复 / 仍失败兜底）

通用兜底：一线修复后仍不通过 → **停下并报告用户，不进入下一步**；报告含触发条件、已试修复、当前产物状态。

**1 · `setup_check.py` 入口**
- 触发条件：退出码非 0、报 `ModuleNotFoundError` / `FileNotFoundError`、无输出，或 `python setup_check.py --json` 非合法 JSON。
- 一线修复：确认在本包根目录、`python --version` 可用（必要时换 `python3`）、`app_config.py` 与 `setup_check.py` 同目录；重跑。
- 仍失败兜底：停下并报告用户，不进入第 1 步；不得用记忆里的清单代替状态检测。

**2 · `bill_parser.py` 产出为 0 行**
- 触发条件：`data/bills_parsed.csv` 不存在，或 `python -c "import csv;print(sum(1 for _ in csv.DictReader(open('data/bills_parsed.csv',encoding='utf-8-sig'))))"` 输出 0。
- 一线修复：确认 `data/bills/<来源>/` 下文件名带 `YYYY-MM`、`profiles/sources.json` 的 `save_subdir` 末段与目录名一致、金额 `patterns` 正则匹配账单文字（`references/配置指南.md`）；重跑 `python bill_parser.py`。
- 仍失败兜底：停下并报告用户，不进入第 4 步；不得拿旧 CSV 冒充本次产出。

**3 · `--dry-run` 命中不符**
- 触发条件：`SALARY_EMAIL=<邮箱> SALARY_IMAP_AUTH_CODE=<授权码> python salary_pipeline.py fetch --dry-run > dryrun.log 2>&1` 后，`grep -c '^\[dry-run\]' dryrun.log` 为 0、出现预期外邮件 / 月份，或 `grep -ciE 'error|traceback' dryrun.log` 不为 0。
- 一线修复：逐条比对 `dryrun.log` 的发件人 / 主题 / 月份与 `config.json`（由 `config.example.json` 复制）的 `sources` 关键词；改 `imap_server` / `imap_port` 或收紧关键词后重跑。量化判定（四条全满足才算「确认命中无误」）：`[dry-run]` 行数 ≥ 1、每条对应 `sources` 关键词、无预期外邮件、错误行数为 0。
- 仍失败兜底：停下并报告用户，不进入 CHECKPOINT ④ 放行确认，也不执行正式 `fetch`。

**4 · CSV 合并结果为空**
- 触发条件：第 4 步合并命令打印「合并数据行 = 0」，或 `data/bills_parsed.csv` 只剩表头。
- 一线修复：核对合并命令**显式列出**的输入路径是否为第 3 步 `SALARY_DATA_DIR` 实际产出工作区；逐个 `python -c "import csv;print(len(list(csv.reader(open('<输入文件>',encoding='utf-8-sig'))))-1)"` 确认非空；补齐重跑。**禁用 `glob('data*/bills_parsed.csv')` 通配**——工作区不以 `data` 开头时静默产出空表。
- 仍失败兜底：停下并报告用户，不进入第 5 步；不得生成空看板。

**5 · `dashboard.py` 未生成看板**
- 触发条件：`python dashboard.py` 退出码非 0，或 `data/收支统一看板_DEMO.html` 不存在 / 大小为 0 / 不含内嵌 JSON。
- 一线修复：确认两张 CSV 表头符合 `references/数据格式.md`、`data/` 可写；按失败分支 1 重跑状态检测确认工作区；重跑 `python dashboard.py`。
- 仍失败兜底：停下并报告用户，不进入第 6 步；不得交付旧版 HTML 或声称已生成。

## 量化核验（「核对数值一致 / 确认命中无误」判定）

「核对数值一致」不凭肉眼，执行以下可复制命令（引导第 5 步同一条），退出码 0 且缺失月份为空才算通过：

```bash
python -c "import csv,sys; r=list(csv.DictReader(open('data/bills_parsed.csv',encoding='utf-8-sig'))); m={x['月份'] for x in r if x.get('月份')}; h=open('data/收支统一看板_DEMO.html',encoding='utf-8').read(); miss=[x for x in m if x not in h]; print('去重月份数=',len(m),'缺失=',miss); sys.exit(1 if (not m or miss) else 0)"
```

量化判定：`bills_parsed.csv` 去重月份数 = 看板月度表行数（每个月份都出现在看板 HTML）；去重月份数 0、缺失月份非空、退出码非 0，任一即判「数值不一致」→ 失败分支 5。「确认命中无误」判定见失败分支 3。

## 标准工作流（已熟悉后使用）

直接用 `references/上手引导.md` 第 0–6 步，编号与本文件一致，不另起一套。

- **跳过条件（硬触发）**：当且仅当 `data/工资年度汇总.csv` 与 `data/bills_parsed.csv` 两张 CSV 已齐备、且本次不解析账单 HTML/PDF 时，跳过第 3 步的 `python bill_parser.py` 与第 4 步合并，直接进第 5 步；其余一律不跳过。
- **第 5 步验收为必做项**：5 个菜单面板、按月折叠按钮、内嵌 JSON 都在；`grep -ciE '<script[^>]+src=|<link[^>]+href=' data/收支统一看板_DEMO.html` 必须为 0；再跑上方量化核验命令。

## 目录结构

`SKILL.md`（本文件）、`setup_check.py`（状态检测，只读，Agent 先跑它）、`app_config.py`（路径/配置解析）、`dashboard.py`（看板渲染主入口）、`bill_parser.py`（账单解析调度）、`generic_parser.py`（正则解析器）、`salary_pipeline.py`（唯一可联网脚本：IMAP 抓取）、`merge_dashboard.py`（旧版生成器，不参与主流程）、`safe_write.py`（稳健写入）、`config.example.json`（脱敏模板，接邮箱时复制为 `config.json`）、`requirements.txt`（只填两张 CSV 时零依赖；接 IMAP 时按此安装）、`profiles/sources.json`（来源与解析规则）、`data/`（工作区：输入 CSV、账单 HTML、dummy 标记、输出看板）、`references/`（四份文档，何时读见下）。

**参考文档 · 何时读 / 解决什么问题**
- `references/上手引导.md`：首次使用或任一步卡住时读；第 0–6 步完整命令、选项表、合并脚本、FAQ、隐私核验。
- `references/数据格式.md`：表头对不上 / 看板为空时读；列定义。
- `references/配置指南.md`：新机构、金额「未匹配」、月份 `unknown` 时读；正则改法。
- `references/飞书接入.md`：用户说「我要接飞书」「同步到多维表格」「怎么连飞书」时读；字段映射与分步接入清单，明确本轮不含同步代码。

## 数据目录优先级（`SALARY_DATA_DIR` 全篇唯一规则出处）

1. 环境变量 `SALARY_DATA_DIR`
2. `config.json` 里的 `save_dir`（本包不含 config.json，故通常跳过）
3. 默认 `<本包目录>/data`

设置该变量时，输入 CSV、账单目录、`state.json`、输出看板、dummy 标记全部跟随该工作区，多工作区 UID 去重状态互不串；不设置则单工作区。换数据、多邮箱分别抓取、合并 CSV 都只改这一个变量。命令见引导第 3.4 / 第 4 步。

凭据环境变量：`SALARY_EMAIL` / `SALARY_IMAP_AUTH_CODE` / `SALARY_XLS_PASSWORD`，优先级高于 `config.json`。

## 反模式 / 不要做什么

| 反模式 → 后果 |
|---|
| 不跑 `setup_check.py`、凭印象把整张清单一次念给用户 → 口径与实际状态不符，用户在 dummy 上白做一遍，可能误删 / 误配 |
| 一次铺开多个数据源 / 多个邮箱 → 验证点互相遮蔽、出错定位不到；且原生多邮箱不支持，会串 `state.json` |
| 声称看板有逐笔交易明细（日期 / 商户 / 单笔金额 / 消费分类）→ 与 L1 口径不符，虚报能力，用户按不存在的明细做决策 |
| 把真实邮箱 / 授权码 / 密码贴进聊天、回显或写进日志 → 凭据泄露；本包不记录，也不应经聊天传输 |
| 用 `glob('data*/bills_parsed.csv')` 通配或拿旧产物冒充、打包转发 `config.json` / 真实 CSV / 看板 HTML → 静默空表、错误数据当最终结果交付、真实数据外泄 |

## 支出明细口径

当前只到 **L1**：每份账单的最低还款额、账单周期、用电量、状态、原始文件。
**逐笔交易（日期 / 商户 / 单笔金额 / 消费分类）未解析**，看板上不要声称有这类数据。单进程原生多邮箱账号不支持，多邮箱走「多工作区」路径。

## 常见问题

问答统一放在 `references/上手引导.md`「红线与常见问答」，本文件不复述（水印、账单目录、金额为空、月份 `unknown`、看板为空、多工作区、换数据、隐私核验）。
