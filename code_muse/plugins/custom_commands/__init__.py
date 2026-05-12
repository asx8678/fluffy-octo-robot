"""Custom commands plugin — TOML-defined shortcuts with {{args}} injection."""

from code_muse.plugins.custom_commands.command_discovery import (
    CommandDef as CommandDef,
)
from code_muse.plugins.custom_commands.command_discovery import (
    discover_commands as discover_commands,
)
from code_muse.plugins.custom_commands.command_toml_schema import (
    parse_command_toml as parse_command_toml,
)
from code_muse.plugins.custom_commands.register_callbacks import (
    CustomCommandResult as CustomCommandResult,
)
