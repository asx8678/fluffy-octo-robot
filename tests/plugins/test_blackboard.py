"""Tests for the Blackboard plugin.

Covers:
- Model validation and serialization
- In-memory store: post, get, query, clear, delete, stats
- Scope isolation: no cross-swarm leakage
- Durable JSONL round-trip
- Tool registration shape and fake-agent capture
- Prompt text, help, and slash commands
- Demonstration: planner posts DesignDoc, two specialists query
- Token-saving proxy
"""

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from code_muse.plugins.blackboard.config import set_durable_enabled
from code_muse.plugins.blackboard.durable import (
    durable_clear_scope,
    durable_delete,
    durable_load,
    durable_post,
    durable_rebuild_clean,
)
from code_muse.plugins.blackboard.models import (
    ArtifactKind,
    BlackboardArtifact,
    BlackboardScope,
    BlackboardScopeType,
    make_bug_analysis,
    make_design_doc,
    make_test_plan,
)
from code_muse.plugins.blackboard.store import BlackboardStore, get_store, reset_store

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_store():
    """Reset the singleton store before and after each test."""
    reset_store()
    yield
    reset_store()


@pytest.fixture
def store() -> BlackboardStore:
    """Provide a fresh BlackboardStore."""
    return get_store()


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------


class TestModels:
    """Test Pydantic models for blackboard artifacts."""

    def test_artifact_kind_values(self):
        assert ArtifactKind.design_doc.value == "design_doc"
        assert ArtifactKind.test_plan.value == "test_plan"
        assert ArtifactKind.bug_analysis.value == "bug_analysis"
        assert ArtifactKind.implementation_note.value == "implementation_note"
        assert ArtifactKind.review_verdict.value == "review_verdict"
        assert ArtifactKind.generic.value == "generic"

    def test_scope_type_values(self):
        assert BlackboardScopeType.session.value == "session"
        assert BlackboardScopeType.swarm.value == "swarm"
        assert BlackboardScopeType.global_.value == "global"

    def test_blackboard_scope_key(self):
        scope = BlackboardScope(scope_type=BlackboardScopeType.session, scope_id="abc")
        assert scope.key == "session:abc"

        scope = BlackboardScope(
            scope_type=BlackboardScopeType.swarm, scope_id="planning-1"
        )
        assert scope.key == "swarm:planning-1"

        scope = BlackboardScope(scope_type=BlackboardScopeType.global_)
        assert scope.key == "global"

    def test_artifact_defaults(self):
        artifact = BlackboardArtifact(
            kind=ArtifactKind.generic,
            title="Test",
            content="Body",
        )
        assert artifact.id  # auto-generated
        assert artifact.kind == ArtifactKind.generic
        assert artifact.scope_type == BlackboardScopeType.session
        assert artifact.scope_id == "default"
        assert artifact.author_agent == "unknown"
        assert artifact.tags == []
        assert artifact.parent_artifact_id is None
        assert artifact.created_at is not None
        assert artifact.updated_at is not None

    def test_artifact_scope_key(self):
        artifact = BlackboardArtifact(
            kind=ArtifactKind.generic,
            title="T",
            content="C",
            scope_type=BlackboardScopeType.swarm,
            scope_id="team-a",
        )
        assert artifact.scope_key == "swarm:team-a"

    def test_artifact_compact(self):
        artifact = BlackboardArtifact(
            kind=ArtifactKind.design_doc,
            title="My Design",
            content="A" * 500,
            summary="Short summary",
            tags=["arch"],
            author_agent="planner",
        )
        compact = artifact.compact()
        assert compact["id"] == artifact.id
        assert compact["kind"] == "design_doc"
        assert compact["title"] == "My Design"
        assert compact["summary"] == "Short summary"
        assert "arch" in compact["tags"]
        assert compact["author_agent"] == "planner"

    def test_artifact_compact_no_summary(self):
        artifact = BlackboardArtifact(
            kind=ArtifactKind.generic,
            title="T",
            content="Short",
        )
        compact = artifact.compact()
        # Falls back to truncated content
        assert compact["summary"] == "Short"

    def test_artifact_compact_long_content_no_summary(self):
        artifact = BlackboardArtifact(
            kind=ArtifactKind.generic,
            title="T",
            content="X" * 500,
        )
        compact = artifact.compact()
        assert len(compact["summary"]) <= 203  # truncated with "..."

    def test_make_design_doc(self):
        art = make_design_doc(
            "Architecture",
            "Full content here",
            summary="Arch summary",
            scope_type=BlackboardScopeType.swarm,
            scope_id="team-a",
            author_agent="planner",
        )
        assert art.kind == ArtifactKind.design_doc
        assert art.title == "Architecture"
        assert art.scope_key == "swarm:team-a"
        assert art.author_agent == "planner"

    def test_make_test_plan(self):
        art = make_test_plan(
            "Unit Tests",
            "Test content",
            author_agent="qa",
        )
        assert art.kind == ArtifactKind.test_plan
        assert art.author_agent == "qa"

    def test_make_bug_analysis(self):
        art = make_bug_analysis(
            "NullRef Bug",
            "Stack trace...",
            tags=["critical"],
        )
        assert art.kind == ArtifactKind.bug_analysis
        assert "critical" in art.tags

    def test_artifact_serialization(self):
        artifact = BlackboardArtifact(
            kind=ArtifactKind.design_doc,
            title="Ser",
            content="C",
            summary="S",
            tags=["t1"],
            scope_type=BlackboardScopeType.swarm,
            scope_id="g1",
            author_agent="a1",
            provenance={"depth": 1},
        )
        data = artifact.model_dump(mode="json")
        restored = BlackboardArtifact.model_validate(data)
        assert restored.kind == ArtifactKind.design_doc
        assert restored.scope_key == "swarm:g1"
        assert restored.provenance["depth"] == 1


# ---------------------------------------------------------------------------
# In-memory store: post, get, query, clear, delete, stats
# ---------------------------------------------------------------------------


class TestStore:
    """Test the in-memory BlackboardStore."""

    def test_post_and_get(self, store: BlackboardStore):
        art = BlackboardArtifact(
            kind=ArtifactKind.generic, title="T", content="C", scope_id="s1"
        )
        store.post(art)
        retrieved = store.get(art.id, scope_id="s1")
        assert retrieved is not None
        assert retrieved.id == art.id
        assert retrieved.content == "C"

    def test_get_wrong_scope_returns_none(self, store: BlackboardStore):
        art = BlackboardArtifact(
            kind=ArtifactKind.generic, title="T", content="C", scope_id="s1"
        )
        store.post(art)
        retrieved = store.get(art.id, scope_id="s2")
        assert retrieved is None

    def test_get_nonexistent_returns_none(self, store: BlackboardStore):
        assert store.get("nope", scope_id="s1") is None

    def test_query_by_kind(self, store: BlackboardStore):
        store.post(
            BlackboardArtifact(kind=ArtifactKind.design_doc, title="D1", content="C")
        )
        store.post(
            BlackboardArtifact(kind=ArtifactKind.test_plan, title="TP", content="C")
        )
        store.post(
            BlackboardArtifact(kind=ArtifactKind.design_doc, title="D2", content="C")
        )

        results = store.query(kind=ArtifactKind.design_doc)
        assert len(results) == 2
        assert all(r.kind == ArtifactKind.design_doc for r in results)

    def test_query_by_tags(self, store: BlackboardStore):
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic, title="T1", content="C", tags=["arch", "v2"]
            )
        )
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic, title="T2", content="C", tags=["arch"]
            )
        )
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic, title="T3", content="C", tags=["perf"]
            )
        )

        results = store.query(tags=["arch"])
        assert len(results) == 2

        results = store.query(tags=["arch", "v2"])
        assert len(results) == 1

    def test_query_by_text(self, store: BlackboardStore):
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic, title="API Design", content="..."
            )
        )
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic, title="Bug Fix", content="..."
            )
        )

        results = store.query(text="api")
        assert len(results) == 1
        assert results[0].title == "API Design"

    def test_query_limit(self, store: BlackboardStore):
        for i in range(10):
            store.post(
                BlackboardArtifact(
                    kind=ArtifactKind.generic, title=f"T{i}", content="C"
                )
            )

        results = store.query(limit=3)
        assert len(results) == 3

    def test_query_respects_scope(self, store: BlackboardStore):
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic,
                title="S1",
                content="C",
                scope_type=BlackboardScopeType.session,
                scope_id="sess-1",
            )
        )
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic,
                title="S2",
                content="C",
                scope_type=BlackboardScopeType.swarm,
                scope_id="swarm-a",
            )
        )
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic,
                title="S3",
                content="C",
                scope_type=BlackboardScopeType.session,
                scope_id="sess-2",
            )
        )

        # Session 1 sees only its own
        results = store.query(scope_type=BlackboardScopeType.session, scope_id="sess-1")
        assert len(results) == 1
        assert results[0].title == "S1"

        # Swarm-a sees only its own
        results = store.query(scope_type=BlackboardScopeType.swarm, scope_id="swarm-a")
        assert len(results) == 1
        assert results[0].title == "S2"

    def test_clear_scope(self, store: BlackboardStore):
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic, title="A", content="C", scope_id="s1"
            )
        )
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic, title="B", content="C", scope_id="s1"
            )
        )
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic, title="C", content="C", scope_id="s2"
            )
        )

        count = store.clear(scope_id="s1")
        assert count == 2

        # s1 is empty
        assert store.query(scope_id="s1") == []
        # s2 still has its artifact
        assert len(store.query(scope_id="s2")) == 1

    def test_delete_artifact(self, store: BlackboardStore):
        art = BlackboardArtifact(kind=ArtifactKind.generic, title="D", content="C")
        store.post(art)

        assert store.delete(art.id) is True
        assert store.get(art.id) is None
        assert store.delete(art.id) is False  # already gone

    def test_stats(self, store: BlackboardStore):
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.design_doc,
                title="D",
                content="A" * 400,
                summary="Short",
                scope_id="s1",
            )
        )
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.test_plan,
                title="T",
                content="B" * 200,
                summary="",
                scope_id="s1",
            )
        )

        stats = store.stats(scope_id="s1")
        assert stats["artifact_count"] == 2
        assert stats["total_content_chars"] == 600  # 400 + 200
        assert stats["by_kind"]["design_doc"] == 1
        assert stats["by_kind"]["test_plan"] == 1
        assert stats["estimated_tokens_saved"] > 0  # summaries save tokens

    def test_all_scope_keys(self, store: BlackboardStore):
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic, title="A", content="C", scope_id="s1"
            )
        )
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic,
                title="B",
                content="C",
                scope_type=BlackboardScopeType.swarm,
                scope_id="sw1",
            )
        )

        keys = store.all_scope_keys()
        assert "session:s1" in keys
        assert "swarm:sw1" in keys

    def test_thread_safety(self, store: BlackboardStore):
        """Smoke test for concurrent access."""
        errors = []

        def poster(n: int):
            try:
                for i in range(20):
                    store.post(
                        BlackboardArtifact(
                            kind=ArtifactKind.generic,
                            title=f"T{n}-{i}",
                            content=f"Content {n}-{i}",
                        )
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=poster, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(store.query(limit=200)) == 100  # 5 * 20

    def test_global_scope(self, store: BlackboardStore):
        art = BlackboardArtifact(
            kind=ArtifactKind.generic,
            title="Global",
            content="C",
            scope_type=BlackboardScopeType.global_,
        )
        store.post(art)

        # Retrieved via global scope
        retrieved = store.get(art.id, scope_type=BlackboardScopeType.global_)
        assert retrieved is not None

        # Not visible via session scope
        assert (
            store.get(art.id, scope_type=BlackboardScopeType.session, scope_id="other")
            is None
        )


# ---------------------------------------------------------------------------
# Scope isolation: no cross-swarm leakage
# ---------------------------------------------------------------------------


class TestScopeIsolation:
    """Scope isolation mandatory: different swarms don't leak."""

    def test_swarm_isolation(self, store: BlackboardStore):
        """swarm:A artifacts are invisible to swarm:B."""
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.design_doc,
                title="Design A",
                content="For A",
                scope_type=BlackboardScopeType.swarm,
                scope_id="swarm-a",
            )
        )
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.test_plan,
                title="Plan A",
                content="For A too",
                scope_type=BlackboardScopeType.swarm,
                scope_id="swarm-a",
            )
        )
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.bug_analysis,
                title="Bug B",
                content="For B",
                scope_type=BlackboardScopeType.swarm,
                scope_id="swarm-b",
            )
        )

        # swarm-a sees its 2 artifacts
        results_a = store.query(
            scope_type=BlackboardScopeType.swarm, scope_id="swarm-a"
        )
        assert len(results_a) == 2

        # swarm-b sees its 1 artifact
        results_b = store.query(
            scope_type=BlackboardScopeType.swarm, scope_id="swarm-b"
        )
        assert len(results_b) == 1
        assert results_b[0].title == "Bug B"

    def test_session_swarm_isolation(self, store: BlackboardStore):
        """Session and swarm scopes are completely separate."""
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic,
                title="Session Art",
                content="C",
                scope_type=BlackboardScopeType.session,
                scope_id="same-id",
            )
        )
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic,
                title="Swarm Art",
                content="C",
                scope_type=BlackboardScopeType.swarm,
                scope_id="same-id",
            )
        )

        sess_results = store.query(
            scope_type=BlackboardScopeType.session, scope_id="same-id"
        )
        assert len(sess_results) == 1
        assert sess_results[0].title == "Session Art"

        swarm_results = store.query(
            scope_type=BlackboardScopeType.swarm, scope_id="same-id"
        )
        assert len(swarm_results) == 1
        assert swarm_results[0].title == "Swarm Art"

    def test_clear_doesnt_affect_other_scopes(self, store: BlackboardStore):
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic,
                title="A",
                content="C",
                scope_type=BlackboardScopeType.swarm,
                scope_id="sw1",
            )
        )
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic,
                title="B",
                content="C",
                scope_type=BlackboardScopeType.swarm,
                scope_id="sw2",
            )
        )

        store.clear(scope_type=BlackboardScopeType.swarm, scope_id="sw1")

        assert (
            len(store.query(scope_type=BlackboardScopeType.swarm, scope_id="sw1")) == 0
        )
        assert (
            len(store.query(scope_type=BlackboardScopeType.swarm, scope_id="sw2")) == 1
        )


# ---------------------------------------------------------------------------
# Durable JSONL round-trip
# ---------------------------------------------------------------------------


class TestDurable:
    """Test JSONL persistence backend."""

    def test_post_and_load(self, tmp_path: Path):
        path = tmp_path / "test.jsonl"
        art = BlackboardArtifact(
            kind=ArtifactKind.design_doc,
            title="Persisted",
            content="Body",
            summary="Sum",
            scope_type=BlackboardScopeType.swarm,
            scope_id="sw1",
        )

        durable_post(art, path=path)

        artifacts, deleted, cleared = durable_load(path=path)
        assert len(artifacts) == 1
        assert artifacts[0].title == "Persisted"
        assert artifacts[0].scope_key == "swarm:sw1"
        assert len(deleted) == 0
        assert len(cleared) == 0

    def test_tombstone_deletion(self, tmp_path: Path):
        path = tmp_path / "test.jsonl"
        art = BlackboardArtifact(kind=ArtifactKind.generic, title="Del", content="C")
        durable_post(art, path=path)
        durable_delete(art.id, path=path)

        artifacts, deleted, cleared = durable_load(path=path)
        assert len(artifacts) == 0
        assert art.id in deleted

    def test_scope_clear_tombstone(self, tmp_path: Path):
        path = tmp_path / "test.jsonl"
        art = BlackboardArtifact(
            kind=ArtifactKind.generic,
            title="A",
            content="C",
            scope_type=BlackboardScopeType.swarm,
            scope_id="sw1",
        )
        durable_post(art, path=path)
        durable_clear_scope("swarm:sw1", path=path)

        artifacts, deleted, cleared = durable_load(path=path)
        assert len(artifacts) == 0
        assert "swarm:sw1" in cleared

    def test_rebuild_clean(self, tmp_path: Path):
        path = tmp_path / "test.jsonl"
        art1 = BlackboardArtifact(kind=ArtifactKind.generic, title="Keep", content="C")
        art2 = BlackboardArtifact(kind=ArtifactKind.generic, title="Del", content="C")
        durable_post(art1, path=path)
        durable_post(art2, path=path)
        durable_delete(art2.id, path=path)

        # Rebuild with only surviving
        durable_rebuild_clean([art1], path=path)

        artifacts, _, _ = durable_load(path=path)
        assert len(artifacts) == 1
        assert artifacts[0].title == "Keep"

    def test_scope_in_records(self, tmp_path: Path):
        """Durable records include scope info to prevent cross-scope leakage."""
        path = tmp_path / "test.jsonl"
        art = BlackboardArtifact(
            kind=ArtifactKind.generic,
            title="Scoped",
            content="C",
            scope_type=BlackboardScopeType.swarm,
            scope_id="sw-x",
        )
        durable_post(art, path=path)

        with open(path) as f:
            record = json.loads(f.readline())
        assert record["scope_type"] == "swarm"
        assert record["scope_id"] == "sw-x"

    def test_load_empty_file(self, tmp_path: Path):
        path = tmp_path / "empty.jsonl"
        artifacts, deleted, cleared = durable_load(path=path)
        assert artifacts == []
        assert deleted == set()
        assert cleared == set()

    def test_load_nonexistent_file(self, tmp_path: Path):
        path = tmp_path / "nope.jsonl"
        artifacts, deleted, cleared = durable_load(path=path)
        assert artifacts == []
        assert deleted == set()

    def test_load_invalid_json_line(self, tmp_path: Path):
        path = tmp_path / "bad.jsonl"
        path.write_text("not json\n")
        artifacts, _, _ = durable_load(path=path)
        assert artifacts == []


# ---------------------------------------------------------------------------
# Tool registration shape and fake-agent capture
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Test that tool registration returns the expected shape."""

    def test_register_tools_returns_list(self):
        from code_muse.plugins.blackboard.register_callbacks import (
            _register_blackboard_tools,
        )

        tools = _register_blackboard_tools()
        assert isinstance(tools, list)
        assert len(tools) == 4

        names = {t["name"] for t in tools}
        assert names == {
            "post_blackboard_artifact",
            "query_blackboard",
            "get_blackboard_artifact",
            "clear_blackboard_scope",
        }

        for t in tools:
            assert "name" in t
            assert "register_func" in t
            assert callable(t["register_func"])

    def test_tool_registration_captures_agent(self):
        """Verify register_func can be called with a mock agent."""
        from code_muse.plugins.blackboard.register_callbacks import (
            _register_blackboard_tools,
        )

        tools = _register_blackboard_tools()
        mock_agent = MagicMock()

        for tool_def in tools:
            # Should not raise
            tool_def["register_func"](mock_agent)

        # Each register_func adds one @agent.tool method
        assert mock_agent.tool.call_count == 4


# ---------------------------------------------------------------------------
# Prompt text, help, and slash commands
# ---------------------------------------------------------------------------


class TestPromptsAndCommands:
    """Test load_prompt, custom_command_help, and slash commands."""

    def test_load_prompt_returns_text(self):
        from code_muse.plugins.blackboard.register_callbacks import _on_load_prompt

        prompt = _on_load_prompt()
        assert prompt is not None
        assert "blackboard" in prompt.lower()
        assert "post_blackboard_artifact" in prompt
        assert "query_blackboard" in prompt
        assert "get_blackboard_artifact" in prompt
        assert "clear_blackboard_scope" in prompt

    def test_help_entries(self):
        from code_muse.plugins.blackboard.register_callbacks import (
            _on_custom_command_help,
        )

        entries = _on_custom_command_help()
        assert isinstance(entries, list)
        assert len(entries) >= 4
        names = [e[0] for e in entries]
        assert "blackboard status" in names
        assert "blackboard list" in names
        assert "blackboard clear" in names
        assert "blackboard durable on|off" in names

    def test_custom_command_wrong_name(self):
        from code_muse.plugins.blackboard.register_callbacks import _on_custom_command

        result = _on_custom_command("/other status", "other")
        assert result is None

    def test_custom_command_status(self):
        from code_muse.plugins.blackboard.register_callbacks import _on_custom_command

        result = _on_custom_command("/blackboard status", "blackboard")
        assert result is True

    def test_custom_command_durable_toggle(self):
        from code_muse.plugins.blackboard.register_callbacks import _on_custom_command

        result = _on_custom_command("/blackboard durable on", "blackboard")
        assert result is True
        assert set_durable_enabled.__module__  # just checking it's importable

    def test_custom_command_unknown_subcommand(self):
        from code_muse.plugins.blackboard.register_callbacks import _on_custom_command

        result = _on_custom_command("/blackboard xyz", "blackboard")
        assert result is True  # shows usage


# ---------------------------------------------------------------------------
# Demonstration: planner posts DesignDoc, two specialists query
# ---------------------------------------------------------------------------


class TestPlannerSpecialistDemo:
    """Demonstrate the planner → specialist blackboard workflow.

    A planner posts a design_doc in scope 'swarm:A'. Two specialist
    agents query the same scope and find it. A different swarm 'B'
    cannot see it.
    """

    def test_planner_specialist_workflow(self, store: BlackboardStore):
        # Planner posts a design doc
        design = make_design_doc(
            title="Refactor Auth Module",
            content=(
                "# Design\n\nWe will split auth.py into auth_core.py, auth_oauth.py..."
            ),
            summary="Split auth.py into 3 modules for SOC",
            scope_type=BlackboardScopeType.swarm,
            scope_id="planning-2025-05",
            author_agent="planner",
        )
        store.post(design)

        # Specialist 1 queries for design docs
        results = store.query(
            kind=ArtifactKind.design_doc,
            scope_type=BlackboardScopeType.swarm,
            scope_id="planning-2025-05",
        )
        assert len(results) == 1
        spec1_artifact = results[0]
        assert spec1_artifact.title == "Refactor Auth Module"
        # Specialist 1 gets full content by id
        full = store.get(
            spec1_artifact.id,
            scope_type=BlackboardScopeType.swarm,
            scope_id="planning-2025-05",
        )
        assert "auth_core.py" in full.content

        # Specialist 2 queries and finds it too
        results2 = store.query(
            kind=ArtifactKind.design_doc,
            scope_type=BlackboardScopeType.swarm,
            scope_id="planning-2025-05",
        )
        assert len(results2) == 1

        # Swarm B cannot see it
        results_b = store.query(
            kind=ArtifactKind.design_doc,
            scope_type=BlackboardScopeType.swarm,
            scope_id="other-swarm",
        )
        assert results_b == []

    def test_compact_query_saves_tokens(self, store: BlackboardStore):
        """When specialists query, they get compact summaries, not full content."""
        long_content = "A" * 2000
        design = make_design_doc(
            title="Big Design",
            content=long_content,
            summary="Compact 50-char summary.",
            scope_type=BlackboardScopeType.swarm,
            scope_id="sw1",
            author_agent="planner",
        )
        store.post(design)

        results = store.query(scope_type=BlackboardScopeType.swarm, scope_id="sw1")
        compact = results[0].compact()

        # Compact uses summary, not 2000-char content
        assert len(compact["summary"]) < 100
        assert compact["summary"] == "Compact 50-char summary."

        # Full content still accessible by id
        full = store.get(
            design.id, scope_type=BlackboardScopeType.swarm, scope_id="sw1"
        )
        assert len(full.content) == 2000


# ---------------------------------------------------------------------------
# Token-saving proxy
# ---------------------------------------------------------------------------


class TestTokenSavingProxy:
    """Test the token-saving estimation in stats."""

    def test_stats_estimate_tokens_saved(self, store: BlackboardStore):
        """When summaries are used instead of full content, tokens are saved."""
        # Post artifacts with large content and short summaries
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.design_doc,
                title="D1",
                content="X" * 1000,
                summary="Short1",
                scope_id="tok-test",
            )
        )
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.test_plan,
                title="T1",
                content="Y" * 800,
                summary="Short2",
                scope_id="tok-test",
            )
        )

        stats = store.stats(scope_id="tok-test")
        # Content = 1800 chars, summaries ~12 chars
        # -> ~1788 chars saved / ~4 = ~447 tokens
        assert stats["total_content_chars"] == 1800
        assert stats["estimated_tokens_saved"] > 300

    def test_stats_no_summary_fallback(self, store: BlackboardStore):
        """Artifacts without summary use truncated content (200 chars max)."""
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.generic,
                title="NoSummary",
                content="Z" * 500,
                scope_id="no-sum",
            )
        )

        stats = store.stats(scope_id="no-sum")
        # Content 500 chars, fallback summary 200 chars -> 300 saved
        assert stats["total_content_chars"] == 500
        assert stats["estimated_tokens_saved"] > 0

    def test_stats_empty_scope(self, store: BlackboardStore):
        stats = store.stats(scope_id="empty")
        assert stats["artifact_count"] == 0
        assert stats["estimated_tokens_saved"] == 0


# ---------------------------------------------------------------------------
# Provenance from subagent/session context
# ---------------------------------------------------------------------------


class TestProvenance:
    """Test that tools use subagent context for provenance defaults."""

    def test_resolve_scope_id_uses_session(self):
        from code_muse.plugins.blackboard.register_callbacks import _resolve_scope_id

        with patch(
            "code_muse.plugins.blackboard.register_callbacks._get_current_session_id",
            return_value="sess-42",
        ):
            result = _resolve_scope_id(None, BlackboardScopeType.session)
            assert result == "sess-42"

    def test_resolve_scope_id_explicit(self):
        from code_muse.plugins.blackboard.register_callbacks import _resolve_scope_id

        result = _resolve_scope_id("explicit", BlackboardScopeType.swarm)
        assert result == "explicit"

    def test_resolve_scope_id_none_swarm(self):
        from code_muse.plugins.blackboard.register_callbacks import _resolve_scope_id

        result = _resolve_scope_id(None, BlackboardScopeType.swarm)
        assert result == "default"

    def test_invoke_agent_hook_posts_artifact(self, store: BlackboardStore):
        from code_muse.plugins.blackboard.register_callbacks import _on_invoke_agent

        _on_invoke_agent(agent_name="specialist-1")

        # Should have posted an implementation_note
        results = store.query(kind=ArtifactKind.implementation_note)
        assert len(results) == 1
        assert "specialist-1" in results[0].title

    def test_invoke_agent_hook_no_crash(self, store: BlackboardStore):
        """invoke_agent hook must never crash the app."""
        from code_muse.plugins.blackboard.register_callbacks import _on_invoke_agent

        # Even with no args it shouldn't raise
        _on_invoke_agent()
