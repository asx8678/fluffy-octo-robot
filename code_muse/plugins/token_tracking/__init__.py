"""Token tracking plugin for Muse.

Records every command execution with token counts and provides slash-command
reports for gain, economics, session adoption, and edit efficiency.
"""

from code_muse.plugins.token_tracking.database import TrackingDatabase, get_tracking_db
from code_muse.plugins.token_tracking.edit_analyzer import analyze_replacement
from code_muse.plugins.token_tracking.record import record_command
from code_muse.plugins.token_tracking.reports import (
    cc_economics_report,
    edit_efficiency_report,
    gain_report,
    session_report,
)

__all__ = [
    "TrackingDatabase",
    "analyze_replacement",
    "cc_economics_report",
    "edit_efficiency_report",
    "gain_report",
    "get_tracking_db",
    "record_command",
    "session_report",
]
