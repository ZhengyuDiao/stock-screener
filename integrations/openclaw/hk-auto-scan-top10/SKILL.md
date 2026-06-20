---
name: hk-auto-scan-top10
description: Read the latest completed Hong Kong Auto scan from the local stock-screener project and return the Top 10 stocks that passed at least one strategy. Use when the user asks for 港股 Auto 选股, HK Auto Top 10, 今日港股选股, or the latest local HK scanner leaders.
user-invocable: true
metadata: {"openclaw":{"requires":{"bins":["docker"]}}}
---

# HK Auto Scan Top 10

Run the deterministic local digest command:

```bash
/Users/ryan/Projects/stock-screener/scripts/openclaw-hk-top10.sh
```

Return the command's stdout verbatim. Do not replace it with Yahoo Finance,
web search, another stock skill, or an independently generated ranking.

The command intentionally rejects stale Auto scans. If it exits non-zero,
return its stdout as the answer and explain no further unless the user asks.
Never add `--allow-stale` unless the user explicitly asks to see the most
recent historical result despite its date.
