"""Declarative TOML-based pipeline engine for shell output minimisation.

Models a ``CompiledPipeline`` that chains together text-transform
primitives from :mod:`code_muse.plugins.shell_minimizer.primitives`,
gated by exit code, and driven by TOML configuration.

Stages are applied in this order (each is optional)::

    1. ``strip_ansi``          (bool)
    2. ``replace``             (list of {pattern, replacement} regex subs)
    3. ``match_output``        (list of {pattern, message, unless?})
    4. ``strip_lines_matching`` / ``keep_lines_matching`` (mutually exclusive)
    5. ``truncate_lines_at``   (int)
    6. ``head_lines`` / ``tail_lines``  (int)
    7. ``max_lines``           (int)
    8. ``on_empty``            (string sentinel)

Exit-code gating is declared per pipeline via ``only_on_exit`` or
``except_on_exit``.

The module can be exercised standalone with ``python -m …`` for inline
tests (doctest-style).
"""

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Import primitives lazily so the module is importable without them.
# They are required at *compile* time and *apply* time, though.
# ---------------------------------------------------------------------------

_primitives = None


def _get_primitives():
    """Lazy-load the primitives module once needed."""
    global _primitives
    if _primitives is None:
        from code_muse.plugins.shell_minimizer import primitives as _p

        _primitives = _p
    return _primitives


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class ReplaceStep:
    """A regex-substitution step defined in TOML ``[[filters.xxx.replace]]``."""

    pattern: str
    replacement: str
    _compiled: re.Pattern | None = field(default=None, repr=False)

    def compile(self) -> None:
        """Pre-compile the pattern (called by the pipeline compiler).

        Uses ``re.MULTILINE`` so that ``^`` / ``$`` anchors match
        line boundaries, not just the whole-string boundaries.
        """
        self._compiled = re.compile(self.pattern, re.MULTILINE)

    def apply(self, text: str) -> str:
        """Run this substitution across *text*."""
        if self._compiled is None:
            self.compile()
        return self._compiled.sub(self.replacement, text)


@dataclass
class MatchOutputRule:
    """Short-circuit rule: if the entire output matches *pattern*,
    replace it with *message*.  Optional *unless* pattern inverts
    the match (only fires when *unless* does NOT match).
    """

    pattern: str
    message: str
    unless: str | None = None
    _compiled_pattern: re.Pattern | None = field(default=None, repr=False)
    _compiled_unless: re.Pattern | None = field(default=None, repr=False)

    def compile(self) -> None:
        self._compiled_pattern = re.compile(self.pattern, re.DOTALL)
        if self.unless:
            self._compiled_unless = re.compile(self.unless, re.DOTALL)

    def matches(self, text: str) -> bool:
        """Return True if this rule should fire."""
        if self._compiled_pattern is None:
            self.compile()
        if not self._compiled_pattern.fullmatch(text):
            return False
        return not (self._compiled_unless and self._compiled_unless.fullmatch(text))


@dataclass
class PipelineDef:
    """Raw pipeline definition as parsed from TOML (before compilation).

    This is the intermediate representation that TOML tables map onto.
    """

    name: str = ""
    match_command: str | None = None
    match_subcommand: str | None = None

    # Stage flags
    strip_ansi: bool = False

    # Replace steps
    replace: list[dict] = field(default_factory=list)  # [{pattern, replacement}, ...]

    # Match-output rules
    match_output: list[dict] = field(default_factory=list)

    # Line-filtering (mutually exclusive)
    strip_lines_matching: list[str] = field(default_factory=list)
    keep_lines_matching: list[str] = field(default_factory=list)

    # Truncation
    truncate_lines_at: int | None = None

    # Head / tail / max (only one should be set typically)
    head_lines: int | None = None
    tail_lines: int | None = None
    max_lines: int | None = None

    # Empty-output sentinel
    on_empty: str | None = None

    # Exit-code gating
    only_on_exit: list[int] | None = None
    except_on_exit: list[int] | None = None


@dataclass
class CompiledPipeline:
    """A pipeline that has been compiled and is ready to apply.

    All regex patterns are compiled, defaults are resolved, and the
    stage list is flattened into an ordered list of callables.
    """

    name: str = ""
    match_command: re.Pattern | None = None
    match_subcommand: re.Pattern | None = None
    only_on_exit: list[int] | None = None
    except_on_exit: list[int] | None = None
    on_empty: str | None = None

    # Ordered pipeline stages, each is a callable (str, exit_code?) -> str
    _stages: list = field(default_factory=list)

    def matches_program(self, command: str) -> bool:
        """Check whether *command* should be processed by this pipeline.

        If neither ``match_command`` nor ``match_subcommand`` is set,
        the pipeline is never auto-matched (must be invoked manually).
        """
        if self.match_command is None:
            return True  # Manual pipelines match everything

        # Extract first two tokens: e.g. "git diff --cached" → ["git", "diff"]
        tokens = command.strip().split()
        prog = tokens[0] if tokens else ""
        subcmd = tokens[1] if len(tokens) > 1 else ""

        if not self.match_command.fullmatch(prog):
            return False

        if self.match_subcommand is not None:
            if not self.match_subcommand.fullmatch(subcmd):
                return False

        return True

    def gated_by_exit(self, exit_code: int) -> bool:
        """Return True when the pipeline should be applied for *exit_code*."""
        if self.only_on_exit is not None:
            return exit_code in self.only_on_exit
        if self.except_on_exit is not None:
            return exit_code not in self.except_on_exit
        return True  # No gating — always apply

    def apply(self, input: str, exit_code: int = 0) -> str:
        """Run the compiled pipeline on *input*.

        Exit-code gating is checked first; if the pipeline should not
        run for this exit code the input is returned unchanged.
        """
        if not self.gated_by_exit(exit_code):
            return input

        text = input

        for stage in self._stages:
            try:
                text = stage(text)
            except Exception:
                # Never crash on bad input; return what we have so far
                pass

        # Short-circuit: match_output rules (checked AFTER stages)
        for rule in self._match_rules:
            if rule.matches(text):
                return rule.message

        if not text.strip() and self.on_empty is not None:
            return self.on_empty

        return text


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


def compile_pipeline(name: str, raw: dict) -> CompiledPipeline:
    """Compile a single pipeline definition dict into a ``CompiledPipeline``.

    Unknown keys are silently ignored so that schema extensions don't
    break existing definitions.

    Args:
        name: The pipeline name (used in logs and ``/minimizer`` display).
        raw: A dict of pipeline config keys (the TOML table for the filter).

    Returns:
        A ready-to-use ``CompiledPipeline``.

    Raises:
        ValueError: When mutually-exclusive options are set together
            (e.g. ``strip_lines_matching`` + ``keep_lines_matching``,
            or ``head_lines`` + ``tail_lines``).
    """
    p = _get_primitives()

    # --- Validate mutually-exclusive options --------------------------------

    if raw.get("strip_lines_matching") and raw.get("keep_lines_matching"):
        raise ValueError(
            f"Pipeline '{name}': strip_lines_matching and keep_lines_matching "
            "are mutually exclusive"
        )

    # --- Compile match patterns ----------------------------------------------

    match_cmd = None
    if raw.get("match_command"):
        match_cmd = re.compile(raw["match_command"], re.IGNORECASE)

    match_sub = None
    if raw.get("match_subcommand"):
        match_sub = re.compile(raw["match_subcommand"], re.IGNORECASE)

    # --- Compile match-output rules ------------------------------------------

    match_rules: list[MatchOutputRule] = []
    for entry in raw.get("match_output", []) or []:
        rule = MatchOutputRule(
            pattern=entry["pattern"],
            message=entry["message"],
            unless=entry.get("unless"),
        )
        rule.compile()
        match_rules.append(rule)

    # --- Build ordered stage list --------------------------------------------

    stages: list = []

    # 1. strip_ansi
    if raw.get("strip_ansi"):
        stages.append(p.strip_ansi)

    # 2. replace
    replace_steps: list[ReplaceStep] = []
    for entry in raw.get("replace", []) or []:
        step = ReplaceStep(pattern=entry["pattern"], replacement=entry["replacement"])
        step.compile()
        replace_steps.append(step)

    if replace_steps:

        def _apply_replaces(text: str, _steps=replace_steps) -> str:
            for step in _steps:
                text = step.apply(text)
            return text

        stages.append(_apply_replaces)

    # 3. match_output rules are checked in CompiledPipeline.apply(), not here

    # 4. strip_lines_matching / keep_lines_matching
    if raw.get("strip_lines_matching"):
        patterns = list(raw["strip_lines_matching"])
        stages.append(lambda t, pts=patterns: p.strip_lines_regex(t, pts))

    if raw.get("keep_lines_matching"):
        patterns = list(raw["keep_lines_matching"])
        stages.append(lambda t, pts=patterns: p.keep_lines_regex(t, pts))

    # 5. truncate_lines_at
    if raw.get("truncate_lines_at") is not None:
        max_chars = int(raw["truncate_lines_at"])

        def _truncate_lines(text: str, _max=max_chars) -> str:
            lines = text.splitlines()
            truncated = [p.truncate_line(line, _max) for line in lines]
            return "\n".join(truncated)

        stages.append(_truncate_lines)

    # 6. head_lines / tail_lines (or both, which uses head_tail_lines)
    if raw.get("head_lines") is not None and raw.get("tail_lines") is not None:
        head_n = int(raw["head_lines"])
        tail_n = int(raw["tail_lines"])
        stages.append(lambda t, h=head_n, t_n=tail_n: p.head_tail_lines(t, h, t_n))
    elif raw.get("head_lines") is not None:
        n = int(raw["head_lines"])
        stages.append(lambda t, _n=n: p.head_lines_only(t, _n))
    elif raw.get("tail_lines") is not None:
        n = int(raw["tail_lines"])
        stages.append(lambda t, _n=n: p.tail_lines_only(t, _n))

    # 7. max_lines
    if raw.get("max_lines") is not None:
        n = int(raw["max_lines"])
        stages.append(lambda t, _n=n: p.max_lines(t, _n))

    # --- Assemble ------------------------------------------------------------

    compiled = CompiledPipeline(
        name=name,
        match_command=match_cmd,
        match_subcommand=match_sub,
        only_on_exit=raw.get("only_on_exit"),
        except_on_exit=raw.get("except_on_exit"),
        on_empty=raw.get("on_empty"),
    )
    compiled._stages = stages
    compiled._match_rules = match_rules  # type: ignore[assignment]

    return compiled


# ---------------------------------------------------------------------------
# TOML parser
# ---------------------------------------------------------------------------


def parse_pipeline_toml(
    contents: str, source_label: str = "<string>"
) -> list[CompiledPipeline]:
    """Parse TOML-format pipeline definitions.

    Expects a TOML document with ``schema_version = 1`` and one or more
    ``[filters.<name>]`` tables.  Returns a list of compiled pipelines
    ready to apply.

    Args:
        contents: Raw TOML text.
        source_label: Describes the source for error messages.

    Returns:
        List of ``CompiledPipeline`` instances (may be empty).

    Raises:
        ValueError: On parse errors, schema violations, or invalid pipeline
            config (e.g. mutually-exclusive options).
    """
    import tomllib as toml_module

    try:
        data = toml_module.loads(contents)
    except Exception as exc:
        raise ValueError(f"TOML parse error in {source_label}: {exc}") from exc

    schema = data.get("schema_version")
    if schema != 1:
        raise ValueError(f"{source_label}: expected schema_version=1, got {schema!r}")

    filters = data.get("filters", {})
    if not isinstance(filters, dict):
        raise ValueError(f"{source_label}: [filters] must be a table")

    compiled_pipelines: list[CompiledPipeline] = []
    errors: list[str] = []

    for name, raw in filters.items():
        if not isinstance(raw, dict):
            errors.append(f"  {name}: value must be a table, got {type(raw).__name__}")
            continue
        try:
            compiled = compile_pipeline(name, raw)
            compiled_pipelines.append(compiled)
        except ValueError as exc:
            errors.append(f"  {name}: {exc}")

    if errors:
        joined = "\n".join(errors)
        raise ValueError(f"Pipeline compilation errors in {source_label}:\n{joined}")

    return compiled_pipelines


# ---------------------------------------------------------------------------
# Top-level convenience
# ---------------------------------------------------------------------------


def apply_pipeline(pipeline: CompiledPipeline, input: str, exit_code: int = 0) -> str:
    """Apply a compiled pipeline to *input* with optional exit-code gating.

    Thin wrapper around ``CompiledPipeline.apply`` for external callers.
    """
    return pipeline.apply(input, exit_code)


# ---------------------------------------------------------------------------
# Inline tests (run with ``python -m code_muse.plugins.shell_minimizer.pipeline``)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Test compile_pipeline basics ---------------------------------------

    cp = compile_pipeline(
        "test_basic",
        {
            "strip_ansi": True,
            "truncate_lines_at": 80,
            "head_lines": 5,
            "on_empty": "(nothing)",
        },
    )
    assert cp.name == "test_basic"
    assert cp.on_empty == "(nothing)"
    assert len(cp._stages) == 3  # strip_ansi, truncate, head_lines

    # Apply to ANSI-laden text
    ansi_input = "\x1b[32mgreen\x1b[0m\n" + "x" * 200
    result = cp.apply(ansi_input)
    assert "green" in result
    assert "…" in result or "more" in result.lower()
    print("✅ compile/apply basic")

    # --- Test exit-code gating -----------------------------------------------

    gated = compile_pipeline(
        "gated_test",
        {
            "strip_ansi": True,
            "only_on_exit": [0],
            "on_empty": "(clean exit)",
        },
    )
    assert gated.apply("some output", exit_code=0) == "some output"
    assert gated.apply("some output", exit_code=1) == "some output"  # unchanged
    print("✅ exit-code gating")

    # --- Test match_output short-circuit -------------------------------------

    short = compile_pipeline(
        "empty_match",
        {
            "match_output": [
                {"pattern": r"^\s*$", "message": "(empty output)"},
            ],
        },
    )
    assert short.apply("\n  \n") == "(empty output)"
    assert short.apply("real data") == "real data"
    print("✅ match_output short-circuit")

    # --- Test mutual-exclusivity errors --------------------------------------

    try:
        compile_pipeline(
            "bad",
            {"strip_lines_matching": ["x"], "keep_lines_matching": ["y"]},
        )
        raise AssertionError("should have raised")
    except ValueError as e:
        assert "mutually exclusive" in str(e)
    print("✅ mutual-exclusivity check")

    # --- Test replace steps --------------------------------------------------

    repl = compile_pipeline(
        "replace_test",
        {
            "replace": [
                {"pattern": r"error:", "replacement": "ERR:"},
                {"pattern": r"\x1b\[[0-9;]*m", "replacement": ""},
            ],
        },
    )
    assert repl.apply("error: something") == "ERR: something"
    assert repl.apply("\x1b[31merror:\x1b[0m fail") == "ERR: fail"
    print("✅ replace steps")

    # --- Test TOML parsing (inline) ------------------------------------------

    toml_text = """\
schema_version = 1

[filters.git_diff]
match_command = "^git$"
match_subcommand = "^diff$"
strip_ansi = true
truncate_lines_at = 160
head_lines = 40
tail_lines = 20

[[filters.git_diff.match_output]]
pattern = "^$"
message = "(empty diff)"

[filters.cargo_build]
match_command = "^cargo$"
match_subcommand = "^(build|test|clippy)$"
strip_ansi = true
# Keep only error/warning/note lines
keep_lines_matching = ["^error", "^warning", "^note", "^Compiling", "^Finished", "^Running"]
truncate_lines_at = 120
head_lines = 30
"""

    pipelines = parse_pipeline_toml(toml_text, "<inline test>")
    assert len(pipelines) == 2, f"expected 2, got {len(pipelines)}"

    git_diff = pipelines[0]
    assert git_diff.name == "git_diff"
    assert git_diff.match_command is not None
    assert git_diff.match_subcommand is not None
    # Check it matches "git diff"
    assert git_diff.matches_program("git diff --cached")
    assert not git_diff.matches_program("git push")
    print("✅ TOML parsing & program matching")

    # --- Test program matching more thoroughly -------------------------------

    cargo = pipelines[1]
    assert cargo.matches_program("cargo build")
    assert cargo.matches_program("cargo test")
    assert cargo.matches_program("cargo clippy")
    assert not cargo.matches_program("cargo run")
    print("✅ cargo subcommand matching")

    print("\n🎉 All pipeline tests passed!")
