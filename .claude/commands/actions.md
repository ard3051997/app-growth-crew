---
description: Suggest the top 5 actions for an app based on all available data (usage- $actions <package_name>)
---

Package name: $ARGUMENTS

Run this to get the exact analysis structure to follow, then execute it using
the domain subagents/MCP tools available in this project:

```bash
cd "$(git rev-parse --show-toplevel)" && uv run python -c "from app_manager.tools import suggest_actions_prompt; print(suggest_actions_prompt('$ARGUMENTS'))"
```
