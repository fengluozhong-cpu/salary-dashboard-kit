# 工作区（dummy 演示数据 · 2025 + 2026）

- `工资年度汇总.csv`：10 列，24 条月度行 + 2 条年度行
- `bills_parsed.csv`：由 `bill_parser.py` 解析 `bills/` 下 72 份虚构账单生成，8 列
- `bills/<来源>/`：示例账单 HTML，正则在 `profiles/sources.json` 中配置
- `IS_DUMMY.txt`：演示标记，看板据此打水印并输出 `_DEMO.html`
- `收支统一看板_DEMO.html`：最终单页看板（文件名带 DEMO，与真实版区分）

**所有金额均为虚构，不含任何真实数据；真实数据在别处，本脚本永不写入。**
