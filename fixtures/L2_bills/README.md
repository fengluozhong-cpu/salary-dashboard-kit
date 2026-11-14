# L2 · 新机构账单 + 需自改的正则

`bills/` 下 3 个虚构机构、每个 6 个月共 18 份 HTML，措辞与内置解析器完全不同。

复刻步骤：把 `sources.L2.json` 的内容合并进 `skill/profiles/sources.json`，把 `bills/` 复制到工作区 `data/bills/`，跑 `python skill/bill_parser.py` 验证能解析出金额，再跑 `python skill/dashboard.py`。

若显示「未匹配到金额」，就是正则与自己账单文字不符 —— 这正是 L2 要练的部分。
