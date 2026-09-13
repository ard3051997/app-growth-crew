---
description: Generate a comprehensive daily app health report (usage- $report <package_name>)
---

Package name: $ARGUMENTS

Run this to get the exact report structure to follow, then execute it using the
domain subagents/MCP tools available in this project (`.claude/agents/`):

```bash
cd "$(git rev-parse --show-toplevel)" && uv run python -c "from app_manager.tools import generate_daily_report_prompt; print(generate_daily_report_prompt('$ARGUMENTS'))"
```
