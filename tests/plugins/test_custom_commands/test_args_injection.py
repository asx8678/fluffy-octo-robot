from code_muse.plugins.custom_commands.args_injection import (
    apply_shell_flags,
    auto_flag_shell_command,
    detect_shell_blocks,
    inject_args,
)


class TestInjectArgs:
    def test_replaces_placeholder(self) -> None:
        prompt = "Review this code: {{args}}"
        assert inject_args(prompt, "src/main.py") == "Review this code: src/main.py"

    def test_multiple_placeholders(self) -> None:
        prompt = "{{args}} and {{args}}"
        assert inject_args(prompt, "foo") == "foo and foo"

    def test_empty_args_removes_placeholder(self) -> None:
        prompt = "Fix this: {{args}}"
        assert inject_args(prompt, "") == "Fix this: "

    def test_no_placeholder_unchanged(self) -> None:
        prompt = "Just fix it"
        assert inject_args(prompt, "extra") == "Just fix it"


class TestDetectShellBlocks:
    def test_detects_bash_block(self) -> None:
        assert detect_shell_blocks("Run this:\n```bash\nls\n```")

    def test_detects_shell_block(self) -> None:
        assert detect_shell_blocks("```shell\necho hi\n```")

    def test_detects_agent_run_shell_command(self) -> None:
        assert detect_shell_blocks("Use agent_run_shell_command to run tests")

    def test_no_shell_returns_false(self) -> None:
        assert not detect_shell_blocks("Just review the code please")


class TestAutoFlagShellCommand:
    def test_npm_install_silent(self) -> None:
        assert auto_flag_shell_command("npm install") == "npm install --silent"

    def test_git_no_pager(self) -> None:
        assert auto_flag_shell_command("git log") == "git log --no-pager"

    def test_pnpm_silent(self) -> None:
        assert auto_flag_shell_command("pnpm run build") == "pnpm run build --silent"

    def test_cargo_quiet(self) -> None:
        assert auto_flag_shell_command("cargo test") == "cargo test --quiet"

    def test_pip_install_quiet(self) -> None:
        assert (
            auto_flag_shell_command("pip install requests")
            == "pip install requests --quiet"
        )

    def test_yarn_silent(self) -> None:
        assert auto_flag_shell_command("yarn install") == "yarn install --silent"

    def test_does_not_duplicate_flags(self) -> None:
        assert auto_flag_shell_command("npm install --silent") == "npm install --silent"
        assert auto_flag_shell_command("git --no-pager log") == "git --no-pager log"
        assert auto_flag_shell_command("cargo test --quiet") == "cargo test --quiet"

    def test_unknown_command_unchanged(self) -> None:
        assert auto_flag_shell_command("make build") == "make build"

    def test_empty_string(self) -> None:
        assert auto_flag_shell_command("") == ""

    def test_whitespace_only(self) -> None:
        assert auto_flag_shell_command("   ") == "   "


class TestApplyShellFlags:
    def test_flags_applied_inside_bash_block(self) -> None:
        prompt = "Run tests:\n```bash\nnpm install\ncargo test\n```"
        result = apply_shell_flags(prompt)
        assert "npm install --silent" in result
        assert "cargo test --quiet" in result

    def test_flags_applied_inside_shell_block(self) -> None:
        prompt = "```shell\ngit log\n```"
        result = apply_shell_flags(prompt)
        assert "git log --no-pager" in result

    def test_no_block_unchanged(self) -> None:
        prompt = "Just run make build"
        assert apply_shell_flags(prompt) == prompt

    def test_multiple_blocks(self) -> None:
        prompt = "```bash\nnpm install\n```\nThen:\n```shell\nyarn test\n```"
        result = apply_shell_flags(prompt)
        assert "npm install --silent" in result
        assert "yarn test --silent" in result
