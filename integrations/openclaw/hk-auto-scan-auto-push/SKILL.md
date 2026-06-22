---
name: hk-auto-scan-auto-push
description: Poll the local HK Auto scan, deliver its overall Top 10 digest to the configured WeChat target exactly once, and stay silent while waiting or after delivery. Use only for the scheduled HK Auto push jobs.
metadata: {"openclaw":{"requires":{"bins":["docker","openclaw","python3"]}}}
---

# HK Auto Scan Automatic Push

Run the deterministic checker requested by the scheduled job:

```bash
python3 /Users/ryan/Projects/stock-screener/scripts/openclaw_hk_auto_push.py check
```

For the 23:00 final check, run `check --final`. Parse the single JSON object
printed by the command. Do not add `--strategy` in scheduled Auto executions.

## Status handling

- `waiting` or `already_sent`: reply with exactly `NO_REPLY`.
- `failed`: send a concise Chinese failure notification only for a final check,
  then reply with exactly `NO_REPLY`.
- `ready`: use the JSON `message` as the sole source for all stocks, ordering,
  numbers, dates, and totals. The checker also writes it to the JSON
  `message_file` path.

For a ready digest, improve company names conservatively before sending:

- Replace an English name only when its official/common Chinese company name is
  confidently known.
- Otherwise keep the original English name; never guess or translate literally.
- Never change symbols, rankings, numeric values, dates, totals, or the Scan ID.

If names change, overwrite only `message_file` with the complete localized
message using the file-writing tool. Do not construct a shell command containing
the message text. Send through the safe delivery command, using only the exact
path, date, and Scan ID supplied by the checker:

```bash
python3 /Users/ryan/Projects/stock-screener/scripts/openclaw_hk_auto_push.py \
  deliver --as-of-date DATE --scan-id SCAN_ID --message-file MESSAGE_FILE
```

The delivery command uses the persistent OpenClaw Gateway, validates its message
receipt, and records success atomically. The WeChat account and target come from
the local delivery config so they cannot be mistyped by an agent. If sending
fails it does not mark the scan sent. End every execution with exactly
`NO_REPLY` so the scheduler does not send a duplicate fallback message.
