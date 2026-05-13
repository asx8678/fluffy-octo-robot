---
id: "025-06"
title: "Fix plugin trust chicken-and-egg at startup (P2)"
status: open
epic: "025"
labels: ["ux", "plugins", "P2"]
created: "2026-05-18"
priority: "P2"
---

## Summary

User plugins are fail-closed at startup. If a plugin provides essential initialization (e.g., custom AI provider, auth backend), the user gets a warning telling them to run `/plugin trust plugin_name` — but they may not reach the REPL if the plugin is required for startup.

## Motivation

The plugin trust system is security-conscious (good), but it creates a bootstrap problem: to trust a plugin you need the REPL, but to get the REPL you may need the plugin. Adding a mechanism to pre-establish trust before startup (via environment variable or config file) solves this without compromising security.

## Solution

Add a `MUSE_TRUST_PLUGIN` environment variable that accepts comma-separated plugin names to pre-trust on startup. This is already partially supported via `MUSE_TRUST_ALL_USER_PLUGINS=1` but that's too broad. A targeted pre-trust env var allows:

```
MUSE_TRUST_PLUGIN=my_custom_provider,my_auth_backend muse -i
```

## Deliverables

- [ ] Add `MUSE_TRUST_PLUGIN` env var support (comma-separated names)
- [ ] Document in SECURITY.md and plugin docs
- [ ] Update trust warning message to mention the env var option
- [ ] All existing tests pass

## Dependencies

Parent: [Epic 025](025-epic-code-review-remediation.md)

## Estimated Effort

~20 lines changed, 30 minutes
