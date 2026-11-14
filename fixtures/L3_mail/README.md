# L3 · 模拟邮箱（离线等价物）

- `attachments/`：24 份脱敏 `.xlsx` 工资条 + 72 份账单 HTML
- `mailbox_manifest.json`：虚构邮件清单（发件人 / 主题 / 附件 / 落地路径）
- `imap.config.example.json`：真实接入时的占位配置，**无任何真实凭据**

跑 `python scripts/simulate_fetch.py` 等价于「从邮箱下载附件」，但全程离线、不联网。接真实邮箱时把上面的占位配置复制成 `config.json` 填自己的值，改用 `python skill/salary_pipeline.py fetch --dry-run` 验证命中后再正式抓取。
