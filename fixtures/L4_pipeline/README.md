# L4 · 完整流水线配套

- `field_map.example.json`：工资条字段映射覆盖示例
- `schedule.example.md`：Windows / cron 定时命令示例（**不自动注册任务**）
- 顶层 `CONFIG-CHECKLIST.md`：L0–L4 全部必改 / 可选 / 勿改配置清单
- 一键复刻：`python scripts/run_all.py`（产物在 `workspace/`）

流水线形状与真实系统一致，但所有输入都是脱敏 fixtures；真实邮箱凭据、加密工资条密码、定时调度属于使用者自己的环境，本包不提供也不伪造。
