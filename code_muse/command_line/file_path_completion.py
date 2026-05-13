import glob
import os
from collections.abc import Iterable
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document


class FilePathCompleter(Completer):
    """A simple file path completer that works with a trigger symbol."""

    def __init__(self, symbol: str = "@"):
        self.symbol = symbol

    def get_completions(
        self, document: Document, complete_event
    ) -> Iterable[Completion]:
        text = document.text
        cursor_position = document.cursor_position
        text_before_cursor = text[:cursor_position]
        if self.symbol not in text_before_cursor:
            return
        symbol_pos = text_before_cursor.rfind(self.symbol)
        text_after_symbol = text_before_cursor[symbol_pos + len(self.symbol) :]
        start_position = -(len(text_after_symbol))
        try:
            pattern = text_after_symbol + "*"
            if not pattern.strip("*") or pattern.strip("*").endswith("/"):
                base_path = pattern.strip("*")
                if not base_path:
                    base_path = "."
                if base_path.startswith("~"):
                    base_path = Path(base_path).expanduser()
                if Path(base_path).is_dir():
                    paths = [
                        str(Path(base_path) / f)
                        for f in os.listdir(base_path)
                        if not f.startswith(".") or text_after_symbol.endswith(".")
                    ]
                else:
                    paths = []
            else:
                paths = glob.glob(pattern)
                if not pattern.startswith(".") and not pattern.startswith("*/."):
                    paths = [p for p in paths if not Path(p).name.startswith(".")]
            paths.sort()
            for path in paths:
                p = Path(path)
                is_dir = p.is_dir()
                display = p.name
                if p.is_absolute():
                    display_path = path
                else:
                    if text_after_symbol.startswith("/"):
                        display_path = str(p.resolve())
                    elif text_after_symbol.startswith("~"):
                        home = Path.home()
                        if path.startswith(str(home)):
                            display_path = "~" + path[len(str(home)) :]
                        else:
                            display_path = path
                    else:
                        display_path = path
                display_meta = "Directory" if is_dir else "File"
                yield Completion(
                    display_path,
                    start_position=start_position,
                    display=display,
                    display_meta=display_meta,
                )
        except (OSError, RuntimeError):
            pass
