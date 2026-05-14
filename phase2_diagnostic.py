#!/usr/bin/env python3
"""Phase 2 Diagnostic Script — validates the top critical findings from code review.

Goal: Verify whether the five highest-priority issues from issuesclaude.md
are present in the current codebase, producing a pass/fail report with
repro details so fixes can be targeted.

Run: python phase2_diagnostic.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
FILTER_ENGINE = PROJECT_ROOT / "code_muse/plugins/filter_engine"
TOKEN_TRACKING = PROJECT_ROOT / "code_muse/plugins/token_tracking"
SEMANTIC_COMP = PROJECT_ROOT / "code_muse/plugins/semantic_compression"
CALLBACKS_PY = PROJECT_ROOT / "code_muse/callbacks.py"
PLUGINS_INIT = PROJECT_ROOT / "code_muse/plugins/__init__.py"

RESULTS: list[dict] = []


def log(name: str, status: str, detail: str = "") -> None:
    RESULTS.append({"check": name, "status": status, "detail": detail})
    icon = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
    print(f"{icon} {name}: {status}")
    if detail:
        for line in detail.splitlines():
            print(f"   {line}")


# ── Check 1: compress_git_status porcelain-only parser ───────────────
def check_git_status_parser() -> None:
    git_py = FILTER_ENGINE / "strategies/git.pyx"
    source = git_py.read_text()
    # Look for the porcelain-specific checks
    has_porcelain = 'line.startswith("##")' in source or "xy = line[:2]" in source
    has_human_parser = "On branch" in source or "Changes to be committed" in source

    if has_porcelain and not has_human_parser:
        log(
            "1.1 compress_git_status handles plain git status",
            "FAIL",
            f"{git_py.name} only parses porcelain format; plain `git status` "
            "output will silently produce wrong counts (0 for all fields).",
        )
    else:
        log("1.1 compress_git_status handles plain git status", "PASS")


# ── Check 2: TrackingDatabase singleton / per-call migrations ────────
def check_tracking_db_singleton() -> None:
    record_py = TOKEN_TRACKING / "record.py"
    db_py = TOKEN_TRACKING / "database.py"
    record_src = record_py.read_text()
    db_py.read_text()

    # record_command should NOT instantiate TrackingDatabase inline
    instantiates_inline = "TrackingDatabase()" in record_src
    # Database init should NOT run migrations unconditionally
    has_singleton = re.search(r"_DB\s*[:=].*TrackingDatabase", record_src) is not None

    if instantiates_inline and not has_singleton:
        log(
            "1.2 TrackingDatabase singleton",
            "FAIL",
            f"{record_py.name} creates TrackingDatabase() per shell dispatch. "
            "Migrations + cleanup run on every filtered command.",
        )
    else:
        log("1.2 TrackingDatabase singleton", "PASS")


# ── Check 3: semantic compression post_tool_call mutation ──────────
def check_semantic_compression_mutation() -> None:
    reg_py = SEMANTIC_COMP / "register_callbacks.py"
    src = reg_py.read_text()

    has_post_tool = "post_tool_call" in src
    has_mutation = "compress_semantic" in src or "compressor.compress" in src
    # A safe implementation only injects a prompt via load_prompt, never mutates results

    if has_post_tool and has_mutation:
        log(
            "1.3 Semantic compression mutates tool results",
            "FAIL",
            f"{reg_py.name} registers post_tool_call and calls compressor, "
            "rewriting tool return values unconditionally (no tool allow-list, no opt-in).",
        )
    else:
        log("1.3 Semantic compression mutates tool results", "PASS")


# ── Check 4: AST compressor language reach ───────────────────────────
def check_ast_compressor_reach() -> None:
    code_py = FILTER_ENGINE / "strategies/code.pyx"
    FILTER_ENGINE / "strategies/ast_compressor.py"
    code_src = code_py.read_text()

    # _language_str_to_code_language should NOT artificially limit languages
    has_restrictive_map = "_language_str_to_code_language" in code_src
    # compress_ast_code should be called from the generic code path, not just compress_read
    generic_call = re.search(r"compress_ast_code", code_src)
    only_read_call = False
    if generic_call:
        # If the only call is inside compress_read, generic grep/find won't use AST
        only_read_call = (
            re.search(r"def compress_read.*compress_ast_code", code_src, re.DOTALL)
            is not None
            and code_src.count("compress_ast_code") == 1
        )

    if has_restrictive_map or only_read_call:
        log(
            "1.5 AST compressor reach",
            "FAIL",
            f"{code_py.name} limits AST languages via _language_str_to_code_language "
            "or only calls AST compression from compress_read (cat/head/tail). "
            "Rust/Java/C/Ruby/Bash/SQL fall back to regex stripping.",
        )
    else:
        log("1.5 AST compressor reach", "PASS")


# ── Check 5: Callback priority enforcement ───────────────────────────
def check_callback_priority() -> None:
    callbacks_src = CALLBACKS_PY.read_text()
    plugins_src = PLUGINS_INIT.read_text()

    # register_callback should accept a priority parameter
    has_priority_param = (
        re.search(r"register_callback.*priority", callbacks_src) is not None
    )
    # Plugin loader should sort plugins explicitly
    sorts_plugins = "sorted(" in plugins_src and "plugins_dir.iterdir()" in plugins_src

    if not has_priority_param and not sorts_plugins:
        log(
            "2.3 Callback priority enforcement",
            "FAIL",
            f"{CALLBACKS_PY.name} has no priority param; {PLUGINS_INIT.name} loads "
            "plugins via unsorted iterdir(). run_shell_command/post_tool_call order "
            "depends on filesystem order.",
        )
    else:
        log("2.3 Callback priority enforcement", "PASS")


# ── Check 6: ContentTypeDetector CODE double-work ────────────────────
def check_content_type_code_roundtrip() -> None:
    dispatcher_py = FILTER_ENGINE / "dispatcher.py"
    FILTER_ENGINE / "content_detector.py"
    disp_src = dispatcher_py.read_text()

    # If CODE routes back to category 'code', the detector wasted a scan
    code_routes_to_category = "ContentType.CODE" in disp_src and "category" in disp_src
    if code_routes_to_category:
        log(
            "1.6 ContentType.CODE → category roundtrip",
            "WARN",
            f"{dispatcher_py.name} routes CODE back to command category, making "
            "the content-type scan a no-op. Not critical, but wasteful.",
        )
    else:
        log("1.6 ContentType.CODE → category roundtrip", "PASS")


# ── main ─────────────────────────────────────────────────────────────
def main() -> int:
    print("=" * 60)
    print("Phase 2 Diagnostic Script")
    print("Goal: Verify presence of top critical findings from code review")
    print("=" * 60)
    print()

    check_git_status_parser()
    check_tracking_db_singleton()
    check_semantic_compression_mutation()
    check_ast_compressor_reach()
    check_callback_priority()
    check_content_type_code_roundtrip()

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    warned = sum(1 for r in RESULTS if r["status"] == "WARN")
    print(f"PASS: {passed}  FAIL: {failed}  WARN: {warned}")

    if failed:
        print()
        print("Recommended next steps:")
        for r in RESULTS:
            if r["status"] == "FAIL":
                print(f"  • Fix {r['check']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
