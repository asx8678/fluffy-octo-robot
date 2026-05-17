"""Tests for the Context-Aware Code Reader plugin.

Covers:
- register_tools callback returns proper name/register_func structure
- Disabled config returns no tool or no-op
- load_prompt contains strong default-path guidance
- Focus-area extraction from task text (de-dupes, limits results)
- /read-relevant command usage string and mocked successful call path
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

from code_muse.plugins.context_aware_reader.focus import extract_focus_areas

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _FakeAgent:
    """Minimal stub that records calls to ``agent.tool(...)``."""

    def __init__(self) -> None:
        self.registered_tools: list = []

    def tool(self, func) -> None:
        self.registered_tools.append(func)


# ---------------------------------------------------------------------------
# 1. register_tools callback — proper structure
# ---------------------------------------------------------------------------


class TestRegisterToolsCallback:
    """Verify the register_tools callback returns the right shape."""

    @patch(
        "code_muse.plugins.context_aware_reader.register_callbacks.get_context_reader_enabled",
        return_value=True,
    )
    def test_returns_list_of_dicts(self, _mock_enabled):
        from code_muse.plugins.context_aware_reader.register_callbacks import (
            _register_read_relevant_tool,
        )

        result = _register_read_relevant_tool()
        assert isinstance(result, list)
        assert len(result) == 1
        entry = result[0]
        assert "name" in entry
        assert "register_func" in entry
        assert entry["name"] == "read_relevant_code"
        assert callable(entry["register_func"])

    @patch(
        "code_muse.plugins.context_aware_reader.register_callbacks.get_context_reader_enabled",
        return_value=True,
    )
    def test_register_func_registers_tool_on_agent(self, _mock_enabled):
        from code_muse.plugins.context_aware_reader.register_callbacks import (
            _register_read_relevant_tool,
        )

        result = _register_read_relevant_tool()
        register_func = result[0]["register_func"]

        agent = _FakeAgent()
        register_func(agent)

        assert len(agent.registered_tools) == 1
        tool_fn = agent.registered_tools[0]
        # The registered tool should have the expected parameter names
        import inspect

        sig = inspect.signature(tool_fn)
        param_names = list(sig.parameters.keys())
        assert "file_path" in param_names
        assert "focus_areas" in param_names
        assert "task_description" in param_names


# ---------------------------------------------------------------------------
# 2. Disabled config returns no tools
# ---------------------------------------------------------------------------


class TestDisabledConfig:
    """When the plugin is disabled, no tools or prompts should be injected."""

    @patch(
        "code_muse.plugins.context_aware_reader.register_callbacks.get_context_reader_enabled",
        return_value=False,
    )
    def test_disabled_register_tools_returns_empty(self, _mock_enabled):
        from code_muse.plugins.context_aware_reader.register_callbacks import (
            _register_read_relevant_tool_disabled,
        )

        result = _register_read_relevant_tool_disabled()
        assert result == []

    def test_disabled_load_prompt_not_called(self):
        """The load_prompt callback should NOT be registered when disabled.

        We verify by checking that the disabled branch only registers
        register_tools (with a no-op) and nothing else.  We cannot
        easily reload the module (callbacks are already committed), so
        we verify the code structure: the disabled branch only calls
        register_callback for 'register_tools'.
        """
        # Read the source and verify the disabled branch
        import code_muse.plugins.context_aware_reader.register_callbacks as rc

        source = inspect.getsource(rc)
        # Find the `else:` branch (disabled) and check it
        # only has register_callback("register_tools", ...)
        # The module has a clear guard:
        #   if get_context_reader_enabled():
        #       register_callback("register_tools", ...)
        #       register_callback("load_prompt", ...)
        #       register_callback("custom_command", ...)
        #       register_callback("custom_command_help", ...)
        #   else:
        #       register_callback(
        #           "register_tools", ...
        #       )
        # We verify the else branch does NOT contain load_prompt
        lines = source.split("\n")
        in_else = False
        else_branch_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("else:"):
                in_else = True
                continue
            if in_else:
                if (
                    stripped
                    and not stripped.startswith(("#", "register_callback"))
                    and stripped.startswith(("def ", "class ", "if "))
                ):
                    # End of else branch
                    break
                else_branch_lines.append(stripped)
        else_phases = []
        for ln in else_branch_lines:
            if '"load_prompt"' in ln or "'load_prompt'" in ln:
                else_phases.append("load_prompt")
            if '"custom_command"' in ln or "'custom_command'" in ln:
                else_phases.append("custom_command")
        assert "load_prompt" not in else_phases
        assert "custom_command" not in else_phases


# ---------------------------------------------------------------------------
# 3. load_prompt contains strong default-path guidance
# ---------------------------------------------------------------------------


class TestLoadPrompt:
    """Verify the system prompt guidance is strong and mentions key terms."""

    @patch(
        "code_muse.plugins.context_aware_reader.register_callbacks.get_context_reader_enabled",
        return_value=True,
    )
    def test_prompt_contains_key_terms(self, _mock_enabled):
        from code_muse.plugins.context_aware_reader.register_callbacks import (
            _load_context_reader_prompt,
        )

        prompt = _load_context_reader_prompt()
        assert prompt is not None
        prompt_lower = prompt.lower()

        # Must mention the tool name and read_file
        assert "read_relevant_code" in prompt_lower
        assert "read_file" in prompt_lower

        # Must mention focus_areas
        assert "focus_areas" in prompt_lower

        # Must contain default-path guidance language
        assert "prefer" in prompt_lower or "default" in prompt_lower

        # Must mention task_description (for auto-derivation)
        assert "task_description" in prompt_lower

    @patch(
        "code_muse.plugins.context_aware_reader.register_callbacks.get_context_reader_enabled",
        return_value=True,
    )
    def test_prompt_mentions_deriving_focus_areas(self, _mock_enabled):
        from code_muse.plugins.context_aware_reader.register_callbacks import (
            _load_context_reader_prompt,
        )

        prompt = _load_context_reader_prompt()
        assert prompt is not None
        prompt_lower = prompt.lower()
        assert "deriv" in prompt_lower  # "derive" or "deriving"


# ---------------------------------------------------------------------------
# 4. Focus-area extraction
# ---------------------------------------------------------------------------


class TestExtractFocusAreas:
    """Test the deterministic focus-area extractor."""

    def test_empty_input(self):
        assert extract_focus_areas("") == []

    def test_quoted_symbols(self):
        result = extract_focus_areas('Fix the bug in "validate_token" method')
        assert "validate_token" in result

    def test_dotted_names(self):
        result = extract_focus_areas("Update pkg.mod.Class to handle edge case")
        assert "pkg.mod.Class" in result

    def test_pascal_case(self):
        result = extract_focus_areas("Refactor UserService and HTTPServer")
        assert "UserService" in result
        assert "HTTPServer" in result

    def test_camel_case(self):
        result = extract_focus_areas("Fix processRequest and handleInput")
        assert "processRequest" in result
        assert "handleInput" in result

    def test_snake_case(self):
        result = extract_focus_areas("Update process_data and auth_flow")
        assert "process_data" in result
        assert "auth_flow" in result

    def test_error_names(self):
        result = extract_focus_areas("Catch UserNotFoundError in the handler")
        assert "UserNotFoundError" in result

    def test_test_names(self):
        result = extract_focus_areas("Fix test_auth_flow and TestEndpoint")
        assert "test_auth_flow" in result
        assert "TestEndpoint" in result

    def test_upper_snake_constants(self):
        result = extract_focus_areas("Use MAX_RETRIES and ERR_TIMEOUT values")
        assert "MAX_RETRIES" in result
        assert "ERR_TIMEOUT" in result

    def test_deduplication_preserves_order(self):
        result = extract_focus_areas(
            '"UserService" and UserService and UserService again'
        )
        # Should only appear once
        assert result.count("UserService") == 1

    def test_max_areas_limit(self):
        text = " ".join(f'"symbol_{i}"' for i in range(20))
        result = extract_focus_areas(text, max_areas=5)
        assert len(result) == 5

    def test_single_char_filtered(self):
        result = extract_focus_areas('"a" is too short')
        # Single-char tokens should be filtered
        assert "a" not in result

    def test_noise_words_filtered(self):
        result = extract_focus_areas("the and for but not")
        assert result == []

    def test_realistic_task_description(self):
        result = extract_focus_areas(
            "Fix the off-by-one error in UserService.validate_token "
            "when token_type is 'refresh'. See test_validate_refresh_token."
        )
        assert "UserService.validate_token" in result
        assert "validate_token" in result
        assert "token_type" in result
        assert "refresh" in result
        assert "test_validate_refresh_token" in result


# ---------------------------------------------------------------------------
# 5. /read-relevant command
# ---------------------------------------------------------------------------


class TestReadRelevantCommand:
    """Test the /read-relevant slash command handler."""

    @patch(
        "code_muse.plugins.context_aware_reader.register_callbacks.get_context_reader_enabled",
        return_value=True,
    )
    def test_wrong_command_returns_none(self, _mock_enabled):
        from code_muse.plugins.context_aware_reader.register_callbacks import (
            _handle_read_relevant_command,
        )

        result = _handle_read_relevant_command("/other thing", "other")
        assert result is None

    @patch(
        "code_muse.plugins.context_aware_reader.register_callbacks.get_context_reader_enabled",
        return_value=True,
    )
    def test_no_args_returns_usage(self, _mock_enabled):
        from code_muse.plugins.context_aware_reader.register_callbacks import (
            _handle_read_relevant_command,
        )

        result = _handle_read_relevant_command("/read-relevant", "read-relevant")
        assert isinstance(result, str)
        assert "Usage" in result

    @patch(
        "code_muse.plugins.context_aware_reader.register_callbacks.get_context_reader_enabled",
        return_value=True,
    )
    def test_custom_command_help(self, _mock_enabled):
        from code_muse.plugins.context_aware_reader.register_callbacks import (
            _custom_command_help,
        )

        result = _custom_command_help()
        assert isinstance(result, list)
        assert len(result) >= 1
        # Should contain /read-relevant
        names = [entry[0] for entry in result]
        assert "/read-relevant" in names

    @patch(
        "code_muse.plugins.context_aware_reader.register_callbacks.read_relevant_code"
    )
    def test_command_with_focus_areas(self, mock_reader):
        """Calling with focus areas should pass them through."""
        from code_muse.plugins.context_aware_reader.register_callbacks import (
            _handle_read_relevant_command,
        )

        mock_reader.return_value = MagicMock(content="file content here", error=None)

        with patch(
            "code_muse.plugins.context_aware_reader.register_callbacks.emit_info"
        ):
            result = _handle_read_relevant_command(
                "/read-relevant src/foo.py MyClass,do_thing", "read-relevant"
            )
        assert result is True
        mock_reader.assert_called_once_with(
            "src/foo.py", focus_areas=["MyClass", "do_thing"]
        )

    @patch(
        "code_muse.plugins.context_aware_reader.register_callbacks.read_relevant_code"
    )
    def test_command_error_returns_error_string(self, mock_reader):
        """If read_relevant_code returns an error, the command returns a string."""
        from code_muse.plugins.context_aware_reader.register_callbacks import (
            _handle_read_relevant_command,
        )

        mock_reader.return_value = MagicMock(content=None, error="File not found")

        result = _handle_read_relevant_command(
            "/read-relevant nonexistent.py", "read-relevant"
        )
        assert isinstance(result, str)
        assert "Error" in result


# ---------------------------------------------------------------------------
# 6. Tool function auto-derives focus areas from task_description
# ---------------------------------------------------------------------------


class TestToolAutoDerivation:
    """Verify the registered tool auto-derives focus areas
    when only task_description is given."""

    @patch(
        "code_muse.plugins.context_aware_reader.register_callbacks.get_context_reader_enabled",
        return_value=True,
    )
    def test_auto_derive_called(self, _mock_enabled):
        from code_muse.plugins.context_aware_reader.register_callbacks import (
            _register_read_relevant_tool,
        )

        result = _register_read_relevant_tool()
        register_func = result[0]["register_func"]
        agent = _FakeAgent()
        register_func(agent)

        tool_fn = agent.registered_tools[0]

        with patch(
            "code_muse.plugins.context_aware_reader.register_callbacks.read_relevant_code"
        ) as mock_reader:
            mock_reader.return_value = MagicMock(content="ok", error=None)

            # Call with task_description but no focus_areas
            tool_fn(
                context=None,
                file_path="src/foo.py",
                focus_areas=None,
                task_description='Fix the "validate_token" method in UserService',
            )

            # read_relevant_code should be called with auto-derived focus_areas
            call_args = mock_reader.call_args
            focus = call_args.kwargs.get("focus_areas") or call_args[1].get(
                "focus_areas"
            )
            assert focus is not None
            assert len(focus) > 0
            # Should contain at least one derived area
            assert any("validate_token" in a for a in focus)

    @patch(
        "code_muse.plugins.context_aware_reader.register_callbacks.get_context_reader_enabled",
        return_value=True,
    )
    def test_explicit_focus_areas_override_task_description(self, _mock_enabled):
        """When focus_areas is explicitly provided, task_description
        is ignored for derivation."""
        from code_muse.plugins.context_aware_reader.register_callbacks import (
            _register_read_relevant_tool,
        )

        result = _register_read_relevant_tool()
        register_func = result[0]["register_func"]
        agent = _FakeAgent()
        register_func(agent)

        tool_fn = agent.registered_tools[0]

        with patch(
            "code_muse.plugins.context_aware_reader.register_callbacks.read_relevant_code"
        ) as mock_reader:
            mock_reader.return_value = MagicMock(content="ok", error=None)

            tool_fn(
                context=None,
                file_path="src/foo.py",
                focus_areas=["MyClass"],
                task_description="Some other task",
            )

            call_args = mock_reader.call_args
            focus = call_args.kwargs.get("focus_areas") or call_args[1].get(
                "focus_areas"
            )
            assert focus == ["MyClass"]

    @patch(
        "code_muse.plugins.context_aware_reader.register_callbacks.get_context_reader_enabled",
        return_value=True,
    )
    def test_no_focus_no_task_passes_none(self, _mock_enabled):
        """When neither focus_areas nor task_description is given,
        focus_areas is None."""
        from code_muse.plugins.context_aware_reader.register_callbacks import (
            _register_read_relevant_tool,
        )

        result = _register_read_relevant_tool()
        register_func = result[0]["register_func"]
        agent = _FakeAgent()
        register_func(agent)

        tool_fn = agent.registered_tools[0]

        with patch(
            "code_muse.plugins.context_aware_reader.register_callbacks.read_relevant_code"
        ) as mock_reader:
            mock_reader.return_value = MagicMock(content="ok", error=None)

            tool_fn(
                context=None,
                file_path="src/foo.py",
                focus_areas=None,
                task_description=None,
            )

            call_args = mock_reader.call_args
            focus = call_args.kwargs.get("focus_areas") or call_args[1].get(
                "focus_areas"
            )
            assert focus is None
