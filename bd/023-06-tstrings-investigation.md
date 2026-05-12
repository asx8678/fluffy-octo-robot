---
id: "023-06"
title: "Phase 6: PEP 750 t-Strings — Investigation & Audit"
status: open
epic: "023"
labels: ["modernization", "py314", "tstrings", "P2"]
created: "2025-07-16"
priority: "P2"
---

## Summary

Audit all f-string usage across the codebase to identify sites that construct SQL queries, shell commands, HTML markup, or structured log lines. Add `# TODO: PEP 750 t-string` markers at candidate locations. Do NOT perform full migration — `string.templatelib` may not be stable in CPython 3.14.0.

## Motivation

PEP 750 t-strings provide built-in template processing that separates content from interpolation, preventing injection vulnerabilities in SQL/shell/HTML contexts. The `string.templatelib` module is expected in 3.14 but its API may still evolve. This phase marks candidate sites for future migration.

## Deliverables

- Audit f-string usage across all `code_muse/` source files (not tests) for the following categories:
  - **SQL**: `plugins/token_tracking/database.py` — f-string SQL query construction
  - **Shell**: `tools/command_runner.py` — f-string shell command construction, background job log paths
  - **HTML/XML**: `command_line/uc_menu.py`, any Rich markup construction
  - **Logging**: `error_logging.py`, `callbacks.py` — structured log line formatting
  - **API URLs/auth**: `plugins/copilot_auth/utils.py`, `plugins/claude_code_oauth/utils.py`, `plugins/chatgpt_oauth/utils.py` — f-string URL/token construction
- Add `# TODO: PEP 750 t-string — use templatelib when stable` comment above each candidate site
- Document count and locations of marked sites in this issue
- Create a reference note in `docs/` if warranted
- Do NOT change any f-string to t-string — only mark

## Acceptance Criteria

- [ ] Full audit of `code_muse/` tree for f-strings in SQL/shell/HTML/logging/auth contexts complete
- [ ] ~10-15 candidate sites identified and marked with TODO comments
- [ ] Each TODO includes brief note on what template function would apply
- [ ] No functional changes made — all f-strings remain as-is
- [ ] Audit summary recorded in this issue body

## Dependencies

Parent: [Epic 023](023-epic-py314-modernization.md). No other dependencies.

## Estimated Effort

~150 lines (audit + comments), 1 hour
