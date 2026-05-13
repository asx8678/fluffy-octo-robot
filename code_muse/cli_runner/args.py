"""CLI argument parsing for Muse."""

import argparse

from code_muse import __version__


def build_parser():
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(description="Muse - A code generation agent")
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version=f"{__version__}",
        help="Show version and exit",
    )
    parser.add_argument(
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity level (use -v for --version). "
        "Specify once for VERBOSE, twice for VERY_VERBOSE, thrice for RAW",
    )
    parser.add_argument(
        "--ultra-compact",
        "-u",
        action="store_true",
        help="Ultra-compact mode — single-line summaries only",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Run in interactive mode",
    )
    parser.add_argument(
        "--prompt",
        "-p",
        type=str,
        help="Execute a single prompt and exit (no interactive mode)",
    )
    parser.add_argument(
        "--agent",
        "-a",
        type=str,
        help="Specify which agent to use (e.g., --agent muse)",
    )
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        help="Specify which model to use (e.g., --model gpt-5)",
    )
    parser.add_argument(
        "--resume",
        "-r",
        type=str,
        metavar="PATH",
        help=(
            "Resume a saved session from a .json file (e.g. ~/.muse/contexts/foo.json)"
        ),
    )
    parser.add_argument(
        "--import-legacy-pickle-session",
        action="store_true",
        help=(
            "DANGER: allow loading a legacy .pkl session file "
            "(pickle can execute arbitrary code)"
        ),
    )
    parser.add_argument(
        "command", nargs="*", help="Run a single command (deprecated, use -p instead)"
    )
    return parser
