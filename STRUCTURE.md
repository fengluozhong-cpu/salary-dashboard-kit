# 结构与命名规则

## 目录树

```
replica-kit/
├── README.md                 总入口：L0–L4 一键复刻 + 隐私声明
├── STRUCTURE.md              本文件：结构、命名、数据流
├── CONFIG-CHECKLIST.md       配置清单：必改 / 可选 / 勿改
├── LICENSE                   MIT
├── .gitignore                发布仓库用
│
├── skill/                    ① 完整可运行 Skill 包（主体）
│   ├── SKILL.md              Agent 引导（含失败分支 / CHECKPOINT / 反模式）
│   ├── app_config.py         统一路径与配置解析（唯一路径来源）
│   ├── dashboard.py          单页看板渲染器
│   ├── bill_parser.py        账单解析调度
│   ├── generic_parser.py     配置驱动的正则解析器
│   ├── salary_pipeline.py    IMAP 抓取 + 工资条解析 + 年度汇总（净化副本）
│   ├── merge_dashboard.py    旧版看板（可选，dashboard.py 不依赖）
│   ├── safe_write.py         稳健文件写入
│   ├── setup_check.py        首次使用状态检测
│   ├── config.example.json   脱敏配置模板（全占位符）
│   ├── requirements.txt      可选依赖
│   ├── profiles/sources.json 来源与解析规则（L2 要改这里）
│   ├── references/           上手引导 / 数据格式 / 配置指南 / 飞书接入
│   └── data/                 L0 基线：两年 dummy CSV + 72 份账单 HTML + IS_DUMMY.txt
│
├── fixtures/                 ② 分层脱敏数据
│   ├── L1_csv/               换一套 CSV 即可出看板（不同来源名与金额）
│   ├── L2_bills/             新机构账单 HTML + sources.L2.json（练改正则）
│   ├── L3_mail/              模拟邮箱：24 xlsx 工资条 + 72 账单附件 + 邮件清单
│   │   ├── attachments/      工资条/ 与 bills/ 两个子目录
│   │   ├── mailbox_manifest.json      离线抓取清单
│   │   ├── imap.config.example.json  真实接入占位配置
│   │   └── README.md
│   └── L4_pipeline/          field_map.example.json / schedule.example.md / README.md
│
├── scripts/                  ③ 执行器与门禁
│   ├── build_fixtures.py     重建 fixtures（维护用，需 openpyxl）
│   ├── simulate_fetch.py     L3 离线模拟 IMAP 下载
│   ├── run_all.py            L4 一键全链路（含硬隔离与降级）
│   └── verify_replica.py     交付门禁：结构 + 隐私 + 看板产物
│
└── workspace/                ④ 运行时产物（可清空重建，已 gitignore）
    ├── YYYY-MM.xlsx          模拟下载的工资条
    ├── bills/<来源>/YYYY-MM.html
    ├── 工资年度汇总.csv / bills_parsed.csv
    ├── download_index.csv / IS_DUMMY.txt
    └── 收支统一看板_DEMO.html
```

## 命名规则

| 模式 | 含义 |
|---|---|
| `L0` … `L4` | 复刻层级编号，数字越大越接近完整流水线 |
| `L1_csv` / `L2_bills` / `L3_mail` / `L4_pipeline` | 层级名 + 该层的核心数据形态 |
| `*.example.json` / `schedule.example.md` | 模板：复制后替换占位值才用于真实环境 |
| `IS_DUMMY.txt` | 演示标记：存在时看板打水印、输出 `_DEMO.html` |
| `收支统一看板_DEMO.html` | dummy 看板；真实版叫 `收支统一看板.html`，**不同名** |
| `*_DEMO.*` / `dummy` | 一切虚构内容的显式标识 |
| `workspace/` | 唯一允许写入的运行时目录 |

## 数据流

```
fixtures/L3_mail/attachments  ──simulate_fetch.py──▶  workspace/
                                                        │
                          ┌─────────────────────────────┼──────────────────────┐
                          ▼                             ▼                      ▼
              salary_pipeline.py analyze      bill_parser.py            download_index.csv
              (xlsx → 工资年度汇总.csv)      (HTML → bills_parsed.csv)
                          └─────────────────────────────┼──────────────────────┘
                                                        ▼
                                              dashboard.py
                                    （Claude 双主题 + 年份维度单页）
                                                        ▼
                                     workspace/收支统一看板_DEMO.html
                                                        ▼
                                            verify_replica.py 门禁
```

`run_all.py` 把上面整条链一步串起来；缺 `openpyxl` 时工资侧自动降级到 `fixtures/L1_csv/工资年度汇总.csv`，链路不中断。

## 隔离边界

- **写入白名单**：`scripts/*` 只允许写 `<replica-kit>/workspace`，并在写前断言路径在本目录内、不含真实目录特征。
- **配置白名单**：`skill/` 不含 `config.json` / `state.json`；只有 `config.example.json` 占位模板。
- **数据白名单**：`fixtures/` 全部由 `build_fixtures.py` 生成，值来自固定公式，域名 `example.*`。
- **门禁**：`verify_replica.py` 扫描全目录文本，命中个人邮箱 / `C:/Users/` / `OneDrive` / 本机用户名即判 FAIL。

## 文件分类一览

| 类别 | 位置 | 是否随包分发 |
|---|---|---|
| 可执行代码 | `skill/*.py`、`scripts/*.py` | ✅ |
| 配置模板 | `skill/config.example.json`、`fixtures/**/*.example.*` | ✅ |
| 脱敏数据 | `skill/data/`、`fixtures/**` | ✅ |
| 文档 | `README.md`、`STRUCTURE.md`、`CONFIG-CHECKLIST.md`、`skill/references/` | ✅ |
| 运行时产物 | `workspace/` | 🚫 不分发，可重建 |
| 真实凭据 / 真实数据 | **不存在于本目录** | 🚫 |
