# 收支看板 · 完整复刻包（replica-kit）

**仅依赖本目录，即可复刻 L0–L4 全部层级的看板。** 所有数据均为虚构脱敏样例，不含任何真实工资、账单、姓名、邮箱、凭据或本机路径。

## 🚫 隐私声明（先读）

- 本目录内**没有** `config.json` / `state.json`，也没有真实邮箱授权码、工资条密码。
- 所有金额是 `build_fixtures.py` 用公式生成的规整虚构值；发件人一律 `example.com` / `example.org`；机构名一律「示例…」。
- 所有产物只写 `workspace/`，脚本内有硬隔离断言，绝不会写到真实数据目录。
- 看板带醒目「演示数据（dummy）」水印，输出文件名固定为 `收支统一看板_DEMO.html`。

## 目录速览

| 目录 | 内容 |
|---|---|
| `skill/` | 完整可运行的 Skill 包：全部脚本、默认配置、`SKILL.md`、4 份 references、L0 基线 dummy 数据 |
| `fixtures/` | L1–L4 分层脱敏数据（换 CSV / 新机构账单 / 模拟邮箱 / 流水线配套） |
| `scripts/` | 复刻执行器与门禁：`simulate_fetch.py`、`run_all.py`、`verify_replica.py`、`build_fixtures.py` |
| `workspace/` | 运行时产物（可随时清空重建），已加入 `.gitignore` |

详见 `STRUCTURE.md`（结构与命名规则）与 `CONFIG-CHECKLIST.md`（配置清单）。

## 一键复刻

| 层级 | 想做到 | 命令 | 产物 |
|---|---|---|---|
| **L0** | 直接出演示看板 | `python skill/dashboard.py` | `skill/data/收支统一看板_DEMO.html` |
| **L1** | 换成另一套脱敏数据 | 把 `fixtures/L1_csv/` 两张 CSV 覆盖到工作区 → `SALARY_DATA_DIR=<工作区> python skill/dashboard.py` | 同上看板，来源名与金额不同 |
| **L2** | 练「改正则接新机构」 | 把 `fixtures/L2_bills/sources.L2.json` 合并进 `skill/profiles/sources.json`，复制 `fixtures/L2_bills/bills/` 到工作区 → `python skill/bill_parser.py` | `bills_parsed.csv` 解析出 18 条 |
| **L3** | 模拟邮箱抓取（离线） | `python scripts/simulate_fetch.py` | `workspace/` 下 24 份 xlsx + 72 份账单 + 下载索引 |
| **L4** | 完整流水线一键跑通 | `python scripts/run_all.py` | `workspace/收支统一看板_DEMO.html` + 门禁报告 |

> Windows 用 `set SALARY_DATA_DIR=...`；`run_all.py` 会自动设置，不用手动配。

**最省事的路径**：直接跑 `python scripts/run_all.py`，它会依次完成 L3 模拟抓取 → 工资条解析 → 账单解析 → 看板生成 → 门禁校验，一步覆盖 L0–L4。

## 隔离机制

- `scripts/simulate_fetch.py` 与 `scripts/run_all.py` 都强制 `SALARY_DATA_DIR` 指向 `<本目录>/workspace`，并在写文件前断言目标在本目录内、且不含 `OneDrive` / `Administrator` 特征。
- `skill/` 内只有 `config.example.json`（全占位符），所以即使把本包单独拷走，也只会读占位配置或使用环境变量，不会误连真实目录。
- 运行 `python scripts/verify_replica.py` 可随时复查结构完整性与隐私扫描。

## 诚实边界

| 能做 | 不能做（也不该伪造） |
|---|---|
| ✅ 离线复刻数据管道的完整形状：附件落地、xlsx 工资条解析、HTML 账单解析、汇总、多年看板、QC | 🚫 真连你的 IMAP 邮箱（需要你自己的授权码） |
| ✅ 产出与真实系统同款 Claude 风格 + 年份切换看板 | 🚫 自动注册 Windows 任务计划 / cron（只给示例命令） |
| ✅ 提供接真实环境的全部配置模板与清单 | 🚫 演示加密工资条解密（`msoffcrypto` 属可选依赖，密码是你私人的） |

接真实环境时按 `CONFIG-CHECKLIST.md` 替换凭据与规则即可，**不需要改任何 Python 代码**。

## License

MIT，见 `LICENSE`。
