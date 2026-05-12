---
id: "024-01"
title: "Critical Python 2-Style except Syntax Fixes (P0)"
status: open
epic: "024"
labels: ["bug", "syntax", "py314", "P0", "critical"]
created: "2026-05-18"
priority: "P0"
---

## Summary

Fix 8 occurrences of Python 2-style `except X, Y:` syntax that will cause **SyntaxError** on Python 3.14+. The comma-separated exception form was removed in Python 3; the correct syntax is `except (X, Y):`.

## Motivation

The project targets `requires-python = ">=3.14,<3.16"` in `pyproject.toml`, yet these 8 locations use syntax that Python 3 rejects at compile time. The application will not start if any of these files are imported.

## Locations (All Confirmed via Source Read)

| # | File | Line | Current | Fix |
|---|------|------|---------|-----|
| 1 | `code_muse/agents/_runtime.py` | 217 | `except UnicodeEncodeError, UnicodeDecodeError:` | `except (UnicodeEncodeError, UnicodeDecodeError):` |
| 2 | `code_muse/session_storage.py` | 123 | `except UnicodeDecodeError, ValueError:` | `except (UnicodeDecodeError, ValueError):` |
| 3 | `code_muse/session_storage.py` | 491 | `except KeyboardInterrupt, EOFError:` | `except (KeyboardInterrupt, EOFError):` |
| 4 | `code_muse/command_line/file_path_completion.py` | 72 | `except PermissionError, FileNotFoundError, OSError:` | `except (PermissionError, FileNotFoundError, OSError):` |
| 5 | `code_muse/config.py` | 173 | `except ValueError, TypeError:` | `except (ValueError, TypeError):` |
| 6 | `code_muse/terminal_utils.py` | 141 | `except subprocess.CalledProcessError, FileNotFoundError:` | `except (subprocess.CalledProcessError, FileNotFoundError):` |
| 7 | `code_muse/gemini_code_assist.py` | 163 | `except TypeError, ValueError:` | `except (TypeError, ValueError):` |
| 8 | `code_muse/cli_runner.py` | 602 | `except KeyboardInterrupt, asyncio.CancelledError:` | `except (KeyboardInterrupt, asyncio.CancelledError):` |

## Deliverables

- [ ] All 8 locations fixed with parenthesized tuple `except (X, Y):` syntax
- [ ] `ruff check` passes on all changed files (E999 syntax errors resolved)
- [ ] No new lint or mypy issues introduced

## Acceptance Criteria

- [ ] `ruff check code_muse/agents/_runtime.py code_muse/session_storage.py code_muse/command_line/file_path_completion.py code_muse/config.py code_muse/terminal_utils.py code_muse/gemini_code_assist.py code_muse/cli_runner.py` passes
- [ ] Application starts successfully
- [ ] All existing tests pass

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~50 lines changed, 20 minutes
