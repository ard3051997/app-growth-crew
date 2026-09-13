---
description: Compare subscription vs ad revenue over N days (usage- $revenue <package_name> [days])
---

Arguments: $ARGUMENTS (package_name, optional days — default 30)

Run this to get the exact comparison structure to follow, then execute it using
the `revenuecat`, `admob`, and `analytics` subagents/MCP tools:

```bash
cd "$(git rev-parse --show-toplevel)" && uv run python -c "
import sys
from app_manager.tools import compare_revenue_prompt
args = '''$ARGUMENTS'''.split()
package = args[0]
days = int(args[1]) if len(args) > 1 else 30
print(compare_revenue_prompt(package, days))
"
```
