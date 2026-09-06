---
name: qol
description: >
  Gets the human's attention by speaking a short sentence aloud. Use when blocked
  waiting on the human, CI/build/deploy failed, a long job finished, credentials
  or approval are needed, or any event the human must hear immediately. Trigger
  phrases: "notify me", "get my attention", "speak to the user", "tell me aloud",
  "alert the human", "I'm blocked", "needs input". Do not use for routine log
  output or non-urgent status.
---

# qol

```bash
qol "Blocked — need approval to deploy prod."
qol -d jabra "Quick note in the headset."
echo "3 tests failed on main." | qol
```

**Defaults:** built-in speakers (not headset), voice `onyx`, volume bumped to 80% only if below 79%.

**Rules**
- One short, actionable sentence.
- Urgent human-attention events only — not every success or log line.
- `-d <device>` only when the human asked for a specific sink (`qol devices` lists them).
