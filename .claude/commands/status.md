---
description: Show which MCP-GC services/credentials are currently configured
---

Run this to check configured services, then summarize the result for the user:

```bash
cd "$(git rev-parse --show-toplevel)" && uv run python -c "from app_manager.tools import get_system_status; print(get_system_status())"
```
