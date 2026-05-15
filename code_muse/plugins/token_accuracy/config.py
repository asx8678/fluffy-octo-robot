"""Configuration for the token_accuracy plugin."""

from code_muse.config import get_value

_DEFAULT_MODE = "hybrid"


def get_token_accuracy_mode() -> str:
    """Returns the desired token counting mode.

    Values: "hybrid" (preferred when possible), "native", "learned", "heuristic".
    Default: "hybrid".
    """
    val = get_value("token_accuracy_mode")
    if val and val.lower() in ("hybrid", "native", "learned", "heuristic"):
        return val.lower()
    return _DEFAULT_MODE
