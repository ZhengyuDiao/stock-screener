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

Use the command output as the sole source for symbols, ordering, scores,
ratings, strategy counts, RS, stage, prices, dates, and totals. Do not replace
it with Yahoo Finance, another stock skill, or an independently generated
ranking.

Before replying, improve company names conservatively:

- When a symbol has a confidently known or reliably verified official/common
  Chinese company name, replace only the English company name with that
  Chinese name.
- When no reliable Chinese name is available, keep the original English name.
- Never create a literal translation, transliteration, or guessed Chinese name.
- Never change the symbol or any numeric value while localizing a name.
- Keep the compact numbered-list layout suitable for a WeChat conversation.

The command intentionally rejects stale Auto scans. If it exits non-zero,
return its stdout as the answer and explain no further unless the user asks.
Never add `--allow-stale` unless the user explicitly asks to see the most
recent historical result despite its date.
