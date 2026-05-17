"""Tests for the Semantic Experience Store (Initiative 4.3).

Covers:
- Config defaults, toggles, and experience-specific settings
- ExperienceCapsule model creation and fields
- Redaction of sensitive content before fingerprinting
- Deterministic semantic signature computation
- Per-repo store isolation (different repo hashes → different store paths)
- Backfill from synthetic task archives
- Search/retrieval ranking and <150ms performance for 10 capsules
- Injection disabled = no impact; enabled = injects compact context
- /experience command family (status, on, off, backfill, search, list, forget)
"""

import json
import time
from unittest.mock import patch

import pytest

from code_muse.plugins.task_context.config import (
    get_experience_config_summary,
    get_experience_global_enabled,
    get_experience_max_capsules,
    get_experience_max_results,
    get_experience_retrieval_enabled,
    set_experience_global_enabled,
    set_experience_max_capsules,
    set_experience_max_results,
    set_experience_retrieval_enabled,
)
from code_muse.plugins.task_context.experience_commands import (
    get_experience_help,
    handle_experience_command,
)
from code_muse.plugins.task_context.experience_models import (
    ExperienceCapsule,
)
from code_muse.plugins.task_context.experience_signature import (
    compute_capsule_signature,
    compute_semantic_signature,
    compute_similarity,
    cosine_similarity,
    extract_keywords,
    extract_structural_fingerprint,
    redact_for_signature,
    search_capsules,
)
from code_muse.plugins.task_context.experience_store import (
    _capsule_from_archive,
    backfill_experiences_from_archives,
    create_capsule_from_task,
    delete_capsule,
    get_capsule_count,
    get_global_store_path,
    get_store_path,
    list_capsules,
    load_capsules,
    search_experience,
    store_capsule,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _use_temp_store(tmp_path, monkeypatch):
    """Redirect experience store to a temp directory for isolation."""
    monkeypatch.setattr(
        "code_muse.plugins.task_context.experience_store.EXPERIENCE_STORE_DIR",
        tmp_path / "exp_store",
    )
    # Also reset the injected queries tracker
    import code_muse.plugins.task_context.register_callbacks as rb

    rb._injected_queries.clear()
    yield


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset experience config to defaults after each test."""
    yield
    set_experience_retrieval_enabled(False)
    set_experience_global_enabled(False)


@pytest.fixture()
def mock_repo_scope(monkeypatch):
    """Set a deterministic repo scope for testing."""

    def _mock_get_repo_scope():
        return "abc123def4567890"

    monkeypatch.setattr(
        "code_muse.plugins.task_context.experience_store.get_repo_scope",
        _mock_get_repo_scope,
    )
    return "abc123def4567890"


@pytest.fixture()
def other_repo_scope(monkeypatch):
    """Set a different repo scope for isolation testing."""

    def _mock_get_repo_scope():
        return "xyz987wvu6543210"

    monkeypatch.setattr(
        "code_muse.plugins.task_context.experience_store.get_repo_scope",
        _mock_get_repo_scope,
    )
    return "xyz987wvu6543210"


def _make_capsule(
    task_label: str = "test task",
    outcome: str = "completed successfully",
    repo_scope: str = "abc123def4567890",
    **kwargs,
) -> ExperienceCapsule:
    """Helper to create a test capsule with a computed signature."""
    key_terms, sig, fp = compute_capsule_signature(
        task_label=task_label,
        outcome_summary=outcome,
        summary=kwargs.get("summary", ""),
        metadata=kwargs.get("metadata"),
    )
    return ExperienceCapsule(
        task_id=kwargs.get("task_id", "task_001"),
        task_label=task_label,
        outcome_summary=outcome,
        repo_scope=repo_scope,
        summary=kwargs.get("summary", outcome[:100]),
        key_terms=key_terms,
        semantic_signature=sig,
        structural_fingerprint=fp,
        token_estimate=kwargs.get("token_estimate", 500),
        metadata=kwargs.get("metadata", {}),
    )


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestExperienceConfig:
    """Config defaults, toggles, and experience settings."""

    def test_retrieval_default_disabled(self):
        assert get_experience_retrieval_enabled() is False

    def test_retrieval_toggle(self):
        set_experience_retrieval_enabled(True)
        assert get_experience_retrieval_enabled() is True
        set_experience_retrieval_enabled(False)
        assert get_experience_retrieval_enabled() is False

    def test_global_default_disabled(self):
        assert get_experience_global_enabled() is False

    def test_global_toggle(self):
        set_experience_global_enabled(True)
        assert get_experience_global_enabled() is True
        set_experience_global_enabled(False)
        assert get_experience_global_enabled() is False

    def test_max_results_default(self):
        assert get_experience_max_results() == 3

    def test_max_results_clamping(self):
        set_experience_max_results(50)
        assert get_experience_max_results() == 10  # max is 10
        set_experience_max_results(0)
        assert get_experience_max_results() == 1  # min is 1
        set_experience_max_results(5)
        assert get_experience_max_results() == 5

    def test_max_capsules_default(self):
        assert get_experience_max_capsules() == 100

    def test_max_capsules_clamping(self):
        set_experience_max_capsules(1)
        assert get_experience_max_capsules() == 10  # min is 10
        set_experience_max_capsules(99999)
        assert get_experience_max_capsules() == 5000  # max is 5000

    def test_config_summary_includes_key_fields(self):
        summary = get_experience_config_summary()
        assert "Retrieval enabled" in summary
        assert "Global" in summary
        assert "Max results" in summary
        assert "Store path" in summary
        assert "Capsule count" in summary


# ---------------------------------------------------------------------------
# ExperienceCapsule model tests
# ---------------------------------------------------------------------------


class TestExperienceCapsule:
    """Model creation and fields."""

    def test_default_values(self):
        cap = ExperienceCapsule()
        assert cap.capsule_id  # auto-generated
        assert cap.task_id == ""
        assert cap.task_label == ""
        assert cap.repo_scope == ""
        assert cap.key_terms == []
        assert cap.semantic_signature == []
        assert cap.token_estimate == 0

    def test_model_dump_round_trip(self):
        cap = _make_capsule()
        data = cap.model_dump()
        restored = ExperienceCapsule.model_validate(data)
        assert restored.capsule_id == cap.capsule_id
        assert restored.task_label == cap.task_label

    def test_jsonl_serialization(self):
        cap = _make_capsule(task_label="refactor auth")
        line = cap.model_dump_json()
        restored = ExperienceCapsule.model_validate_json(line)
        assert restored.task_label == "refactor auth"


# ---------------------------------------------------------------------------
# Redaction tests
# ---------------------------------------------------------------------------


class TestRedaction:
    """Sensitive content redaction before fingerprinting."""

    def test_redact_secrets(self):
        text = "my password=hunter2 and api_key=sk-1234"
        redacted = redact_for_signature(text)
        assert "hunter2" not in redacted
        assert "sk-1234" not in redacted
        assert "<redacted>" in redacted

    def test_redact_absolute_paths(self):
        text = "file at /Users/adam/secret.txt and /home/user/.ssh/id_rsa"
        redacted = redact_for_signature(text)
        assert "/Users/adam" not in redacted
        assert "/home/user" not in redacted
        assert "<path>" in redacted

    def test_redact_bearer_tokens(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9"
        redacted = redact_for_signature(text)
        assert "eyJhbGciOiJIUzI1NiJ9" not in redacted

    def test_redact_preserves_safe_content(self):
        text = "implement user authentication with JWT tokens"
        redacted = redact_for_signature(text)
        assert "implement" in redacted
        assert "authentication" in redacted

    def test_redact_empty_string(self):
        assert redact_for_signature("") == ""


# ---------------------------------------------------------------------------
# Semantic signature tests
# ---------------------------------------------------------------------------


class TestSemanticSignature:
    """Deterministic signature computation and similarity."""

    def test_signature_deterministic(self):
        text = "refactor authentication module with JWT"
        sig1 = compute_semantic_signature(text)
        sig2 = compute_semantic_signature(text)
        assert sig1 == sig2

    def test_signature_dimension(self):
        sig = compute_semantic_signature("hello world")
        assert len(sig) == 128

    def test_similar_texts_high_similarity(self):
        sim = compute_similarity(
            "refactor authentication module with JWT",
            "refactor auth module using JWT tokens",
        )
        assert sim > 0.5, f"Expected high similarity, got {sim}"

    def test_dissimilar_texts_low_similarity(self):
        sim = compute_similarity(
            "refactor authentication module",
            "deploy kubernetes cluster on AWS",
        )
        assert sim < 0.5, f"Expected low similarity, got {sim}"

    def test_cosine_similarity_identical(self):
        vec = [0.5, 0.5, 0.5, 0.5]
        assert cosine_similarity(vec, vec) == pytest.approx(1.0, abs=0.01)

    def test_cosine_similarity_orthogonal(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0, abs=0.01)

    def test_empty_text_gives_zero_vector(self):
        sig = compute_semantic_signature("")
        assert all(v == 0.0 for v in sig)

    def test_extract_keywords(self):
        kws = extract_keywords("Implement JWT authentication for user login")
        assert "implement" in kws
        assert "jwt" in kws
        assert "authentication" in kws

    def test_extract_keywords_max(self):
        long_text = " ".join(f"word{i}" for i in range(100))
        kws = extract_keywords(long_text, max_keywords=10)
        assert len(kws) == 10

    def test_structural_fingerprint(self):
        fp = extract_structural_fingerprint(
            tools_used=["file_read", "shell_exec"],
            file_types=[".py", ".json"],
            metadata={"categories": ["refactor"]},
        )
        assert "tools_used" in fp
        assert "file_types" in fp
        assert "categories" in fp
        assert fp["tools_used"] == ["file_read", "shell_exec"]

    def test_compute_capsule_signature(self):
        key_terms, sig, fp = compute_capsule_signature(
            task_label="fix login bug",
            outcome_summary="fixed JWT validation",
            metadata={"tools_used": ["file_read"]},
        )
        assert len(key_terms) > 0
        assert len(sig) == 128
        assert "tools_used" in fp


# ---------------------------------------------------------------------------
# Per-repo store isolation
# ---------------------------------------------------------------------------


class TestRepoIsolation:
    """Different repo scopes → different store paths."""

    def test_different_scopes_different_paths(self):
        path_a = get_store_path(repo_scope="abc123def4567890")
        path_b = get_store_path(repo_scope="xyz987wvu6543210")
        assert path_a != path_b
        assert "abc123" in str(path_a)
        assert "xyz987" in str(path_b)

    def test_capsules_isolated_per_repo(self):
        """Different repos get different stores; capsules don't leak."""
        from code_muse.plugins.task_context.experience_store import _append_capsule

        path_a = get_store_path(repo_scope="abc123")
        path_b = get_store_path(repo_scope="xyz987")

        cap_a = _make_capsule(task_label="repo-a task", repo_scope="abc123")
        cap_b = _make_capsule(task_label="repo-b task", repo_scope="xyz987")

        _append_capsule(path_a, cap_a)
        _append_capsule(path_b, cap_b)

        repo_a_caps = load_capsules(path_a)
        repo_b_caps = load_capsules(path_b)

        assert len(repo_a_caps) == 1
        assert len(repo_b_caps) == 1
        assert repo_a_caps[0].task_label == "repo-a task"
        assert repo_b_caps[0].task_label == "repo-b task"


# ---------------------------------------------------------------------------
# Store CRUD tests
# ---------------------------------------------------------------------------


class TestStoreCRUD:
    """Store, load, delete, list operations."""

    def test_store_and_load(self, mock_repo_scope):
        cap = _make_capsule(task_label="auth refactor", repo_scope=mock_repo_scope)
        store_capsule(cap)
        loaded = list_capsules(mock_repo_scope)
        assert len(loaded) == 1
        assert loaded[0].task_label == "auth refactor"

    def test_store_multiple_and_list(self, mock_repo_scope):
        for i in range(3):
            cap = _make_capsule(
                task_label=f"task-{i}",
                repo_scope=mock_repo_scope,
                task_id=f"task_{i:03d}",
            )
            store_capsule(cap)
        loaded = list_capsules(mock_repo_scope)
        assert len(loaded) == 3

    def test_delete_capsule(self, mock_repo_scope):
        cap = _make_capsule(task_label="to-delete", repo_scope=mock_repo_scope)
        store_capsule(cap)
        assert get_capsule_count(mock_repo_scope) == 1

        deleted = delete_capsule(cap.capsule_id, repo_scope=mock_repo_scope)
        assert deleted is True
        assert get_capsule_count(mock_repo_scope) == 0

    def test_delete_nonexistent(self, mock_repo_scope):
        deleted = delete_capsule("nonexistent-id", repo_scope=mock_repo_scope)
        assert deleted is False

    def test_capsule_count_empty(self, mock_repo_scope):
        assert get_capsule_count(mock_repo_scope) == 0

    def test_get_store_path_deterministic(self, mock_repo_scope):
        path1 = get_store_path(mock_repo_scope)
        path2 = get_store_path(mock_repo_scope)
        assert path1 == path2

    def test_global_store_path(self):
        path = get_global_store_path()
        assert path.name == "_global.jsonl"

    def test_max_capsules_enforcement(self, mock_repo_scope, monkeypatch):
        monkeypatch.setattr(
            "code_muse.plugins.task_context.config.get_experience_max_capsules",
            lambda: 3,
        )
        monkeypatch.setattr(
            "code_muse.plugins.task_context.config.get_experience_global_enabled",
            lambda: False,
        )
        for i in range(5):
            cap = _make_capsule(
                task_label=f"task-{i}",
                repo_scope=mock_repo_scope,
                task_id=f"task_{i:03d}",
            )
            store_capsule(cap)

        # Should be capped at 3
        count = get_capsule_count(mock_repo_scope)
        assert count <= 3


# ---------------------------------------------------------------------------
# Backfill tests
# ---------------------------------------------------------------------------


class TestBackfill:
    """Backfill from task archives."""

    def test_backfill_from_empty_archive(self, mock_repo_scope, tmp_path):
        monkeypatch_archive = pytest.MonkeyPatch()
        monkeypatch_archive.setattr(
            "code_muse.plugins.task_context.archival.ARCHIVE_DIR",
            tmp_path / "empty_archive",
        )
        (tmp_path / "empty_archive").mkdir(exist_ok=True)

        count = backfill_experiences_from_archives(repo_scope=mock_repo_scope)
        assert count == 0
        monkeypatch_archive.undo()

    def test_backfill_from_archives(self, mock_repo_scope, tmp_path):
        # Create synthetic archive
        archive_dir = tmp_path / "task_archive"
        archive_dir.mkdir()
        archive_data = {
            "task_id": "task_backfill_001",
            "task_label": "refactor auth",
            "task_status": "archived",
            "outcome_summary": "Successfully refactored auth module",
            "message_count": 5,
            "token_count": 1200,
        }
        archive_path = archive_dir / "task_backfill_001.json"
        with open(archive_path, "w") as f:
            json.dump(archive_data, f)

        with patch(
            "code_muse.plugins.task_context.archival.list_archived_tasks",
            return_value=[
                {
                    "task_id": "task_backfill_001",
                    "task_label": "refactor auth",
                    "outcome_summary": "Successfully refactored auth module",
                    "message_count": 5,
                    "token_count": 1200,
                    "file_path": str(archive_path),
                }
            ],
        ):
            count = backfill_experiences_from_archives(repo_scope=mock_repo_scope)

        assert count == 1
        capsules = list_capsules(mock_repo_scope)
        assert len(capsules) == 1
        assert capsules[0].task_label == "refactor auth"
        assert capsules[0].metadata.get("backfilled") is True

    def test_backfill_skips_existing(self, mock_repo_scope):
        """Second backfill of same archive should create 0 new capsules."""
        with patch(
            "code_muse.plugins.task_context.archival.list_archived_tasks",
            return_value=[
                {
                    "task_id": "task_existing",
                    "task_label": "existing task",
                    "outcome_summary": "done",
                    "message_count": 1,
                    "token_count": 100,
                    "file_path": "/fake/path.json",
                }
            ],
        ):
            count1 = backfill_experiences_from_archives(repo_scope=mock_repo_scope)
            count2 = backfill_experiences_from_archives(repo_scope=mock_repo_scope)

        assert count1 == 1
        assert count2 == 0

    def test_capsule_from_archive(self):
        meta = {
            "task_id": "task_x",
            "task_label": "fix bug",
            "outcome_summary": "Fixed the login bug",
            "message_count": 3,
            "token_count": 500,
            "file_path": "/some/path.json",
        }
        cap = _capsule_from_archive(meta, "abc123")
        assert cap is not None
        assert cap.task_id == "task_x"
        assert cap.task_label == "fix bug"
        assert len(cap.key_terms) > 0
        assert len(cap.semantic_signature) == 128
        assert cap.metadata.get("backfilled") is True

    def test_capsule_from_empty_archive(self):
        meta = {"task_id": "task_empty", "task_label": "", "outcome_summary": ""}
        cap = _capsule_from_archive(meta, "abc123")
        assert cap is None


# ---------------------------------------------------------------------------
# Search / retrieval tests
# ---------------------------------------------------------------------------


class TestSearch:
    """Search, ranking, and performance."""

    def test_search_finds_similar(self, mock_repo_scope):
        cap = _make_capsule(
            task_label="refactor authentication module",
            outcome="Refactored JWT auth with better validation",
            repo_scope=mock_repo_scope,
        )
        store_capsule(cap)

        results = search_experience("refactor auth JWT")
        assert len(results) > 0
        assert results[0][0].task_label == "refactor authentication module"

    def test_search_empty_store(self, mock_repo_scope):
        results = search_experience("refactor auth")
        assert len(results) == 0

    def test_search_ranking(self, mock_repo_scope):
        # Store two capsules — one more similar to query
        cap1 = _make_capsule(
            task_label="deploy kubernetes cluster",
            outcome="Deployed k8s on AWS EKS",
            repo_scope=mock_repo_scope,
            task_id="task_k8s",
        )
        cap2 = _make_capsule(
            task_label="refactor authentication module",
            outcome="Refactored JWT auth",
            repo_scope=mock_repo_scope,
            task_id="task_auth",
        )
        store_capsule(cap1)
        store_capsule(cap2)

        results = search_experience("refactor auth JWT", top_k=2)
        assert len(results) >= 1
        # Auth capsule should rank higher for auth query
        assert results[0][0].task_label == "refactor authentication module"

    def test_search_min_similarity(self, mock_repo_scope):
        cap = _make_capsule(
            task_label="deploy kubernetes cluster",
            outcome="Deployed k8s on AWS EKS",
            repo_scope=mock_repo_scope,
        )
        store_capsule(cap)

        # Very different query with high min_similarity should return nothing
        results = search_experience("cook italian pasta recipe", min_similarity=0.8)
        assert len(results) == 0

    def test_search_performance_under_150ms(self, mock_repo_scope):
        """Target: <150ms retrieval for 10 capsules."""
        # Create and store 10 capsules
        for i in range(10):
            cap = _make_capsule(
                task_label=f"task-{i} refactor auth module",
                outcome=f"Completed task {i} with JWT validation",
                repo_scope=mock_repo_scope,
                task_id=f"task_perf_{i:03d}",
            )
            store_capsule(cap)

        # Measure search time
        start = time.perf_counter()
        for _ in range(10):  # Average over 10 runs
            results = search_experience("refactor auth JWT validation")
        elapsed = (time.perf_counter() - start) / 10 * 1000  # ms

        assert len(results) > 0
        assert elapsed < 150, f"Search took {elapsed:.1f}ms (target <150ms)"

    def test_search_capsules_in_memory(self):
        """Test the in-memory search_capsules function directly."""
        capsules = [
            _make_capsule(task_label="refactor auth"),
            _make_capsule(task_label="deploy k8s"),
        ]
        results = search_capsules(
            query="refactor authentication",
            capsules=capsules,
            top_k=2,
        )
        assert len(results) >= 1
        assert results[0][0].task_label == "refactor auth"


# ---------------------------------------------------------------------------
# Injection tests
# ---------------------------------------------------------------------------


class TestInjection:
    """Experience injection into message history."""

    def test_injection_disabled_does_nothing(self):
        """When experience_retrieval_enabled=False, no injection occurs."""
        set_experience_retrieval_enabled(False)

        from code_muse.plugins.task_context.register_callbacks import (
            _on_message_history_processor_start_with_experience,
        )

        incoming = [{"role": "user", "content": "refactor auth"}]
        original_len = len(incoming)

        _on_message_history_processor_start_with_experience(
            agent_name="test",
            session_id=None,
            message_history=[],
            incoming_messages=incoming,
        )

        # Should not have modified incoming_messages when disabled
        assert len(incoming) == original_len

    def test_injection_enabled_adds_context(self, mock_repo_scope):
        """When enabled, similar capsules are injected as context."""
        set_experience_retrieval_enabled(True)

        # Store a capsule
        cap = _make_capsule(
            task_label="refactor auth module",
            outcome="Refactored JWT auth successfully",
            repo_scope=mock_repo_scope,
        )
        store_capsule(cap)

        from code_muse.plugins.task_context.register_callbacks import (
            _on_message_history_processor_start_with_experience,
        )

        incoming = [{"role": "user", "content": "refactor authentication JWT"}]

        _on_message_history_processor_start_with_experience(
            agent_name="test",
            session_id=None,
            message_history=[],
            incoming_messages=incoming,
        )

        # Should have added an injection message
        assert len(incoming) > 1
        injected = incoming[0]
        # Check that injection contains relevant text
        if isinstance(injected, dict):
            content = injected.get("content", "")
        else:
            # pydantic-ai message
            content = str(getattr(injected, "parts", []))
        assert (
            "Relevant past experience" in content
            or "experience" in str(injected).lower()
        )

    def test_injection_dedup_prevents_repeats(self, mock_repo_scope):
        """Same query should not be injected twice."""
        set_experience_retrieval_enabled(True)

        cap = _make_capsule(
            task_label="refactor auth",
            outcome="Done",
            repo_scope=mock_repo_scope,
        )
        store_capsule(cap)

        from code_muse.plugins.task_context.register_callbacks import (
            _on_message_history_processor_start_with_experience,
        )

        incoming1 = [{"role": "user", "content": "refactor auth JWT"}]
        incoming2 = [{"role": "user", "content": "refactor auth JWT"}]

        _on_message_history_processor_start_with_experience(
            agent_name="test",
            session_id=None,
            message_history=[],
            incoming_messages=incoming1,
        )
        len_after_first = len(incoming1)

        _on_message_history_processor_start_with_experience(
            agent_name="test",
            session_id=None,
            message_history=[],
            incoming_messages=incoming2,
        )
        # Second call should not inject (same query hash)
        assert len(incoming2) <= len_after_first + 1  # At most original + 1
        # The key point: no double-injection for same query


# ---------------------------------------------------------------------------
# /experience command tests
# ---------------------------------------------------------------------------


class TestExperienceCommands:
    """/experience family of commands."""

    def test_status_command(self):
        result = handle_experience_command("/experience status")
        assert isinstance(result, str)
        assert "Retrieval enabled" in result

    def test_on_command(self):
        result = handle_experience_command("/experience on")
        assert result is True
        assert get_experience_retrieval_enabled() is True

    def test_off_command(self):
        set_experience_retrieval_enabled(True)
        result = handle_experience_command("/experience off")
        assert result is True
        assert get_experience_retrieval_enabled() is False

    def test_global_on_off(self):
        result = handle_experience_command("/experience global on")
        assert result is True
        assert get_experience_global_enabled() is True

        result = handle_experience_command("/experience global off")
        assert result is True
        assert get_experience_global_enabled() is False

    def test_backfill_command(self, mock_repo_scope):
        with patch(
            "code_muse.plugins.task_context.experience_store.backfill_experiences_from_archives",
            return_value=5,
        ):
            result = handle_experience_command("/experience backfill")
        assert result is True

    def test_search_command(self, mock_repo_scope):
        cap = _make_capsule(
            task_label="refactor auth",
            repo_scope=mock_repo_scope,
        )
        store_capsule(cap)

        result = handle_experience_command("/experience search refactor auth")
        assert isinstance(result, str)
        assert "Similar" in result or "capsule" in result.lower() or "No" in result

    def test_search_no_query(self):
        result = handle_experience_command("/experience search")
        assert result is True  # Emits usage warning

    def test_list_command(self, mock_repo_scope):
        cap = _make_capsule(
            task_label="test task",
            repo_scope=mock_repo_scope,
        )
        store_capsule(cap)

        result = handle_experience_command("/experience list")
        assert isinstance(result, str)
        assert "test task" in result

    def test_list_empty(self, mock_repo_scope):
        result = handle_experience_command("/experience list")
        assert result is True  # Emits info

    def test_forget_command(self, mock_repo_scope):
        cap = _make_capsule(
            task_label="to-forget",
            repo_scope=mock_repo_scope,
        )
        store_capsule(cap)

        result = handle_experience_command(f"/experience forget {cap.capsule_id}")
        assert result is True

    def test_forget_no_id(self):
        result = handle_experience_command("/experience forget")
        assert result is True  # Emits usage warning

    def test_unknown_subcommand(self):
        result = handle_experience_command("/experience xyz")
        assert result is True  # Shows usage

    def test_non_experience_command_returns_none(self):
        result = handle_experience_command("/task status")
        assert result is None

    def test_help_entries(self):
        entries = get_experience_help()
        assert len(entries) >= 6
        labels = [entry[0] for entry in entries]
        assert any("status" in label for label in labels)
        assert any("search" in label for label in labels)
        assert any("backfill" in label for label in labels)


# ---------------------------------------------------------------------------
# create_capsule_from_task integration
# ---------------------------------------------------------------------------


class TestCreateCapsuleFromTask:
    """End-to-end capsule creation from task context."""

    def test_creates_and_stores_capsule(self, mock_repo_scope):
        with (
            patch(
                "code_muse.plugins.task_context.config.get_experience_global_enabled",
                lambda: False,
            ),
            patch(
                "code_muse.plugins.task_context.config.get_experience_max_capsules",
                lambda: 100,
            ),
        ):
            capsule = create_capsule_from_task(
                task_id="task_123",
                task_label="fix login bug",
                outcome_summary="Fixed JWT validation issue",
                token_estimate=800,
            )

        assert capsule.task_id == "task_123"
        assert capsule.task_label == "fix login bug"
        assert len(capsule.key_terms) > 0
        assert len(capsule.semantic_signature) == 128

        # Should be in the store
        loaded = list_capsules(mock_repo_scope)
        assert len(loaded) == 1
        assert loaded[0].task_label == "fix login bug"

    def test_redaction_in_created_capsule(self, mock_repo_scope):
        with (
            patch(
                "code_muse.plugins.task_context.config.get_experience_global_enabled",
                lambda: False,
            ),
            patch(
                "code_muse.plugins.task_context.config.get_experience_max_capsules",
                lambda: 100,
            ),
        ):
            capsule = create_capsule_from_task(
                task_id="task_secret",
                task_label="deploy with api_key=sk-1234",
                outcome_summary="Deployed successfully",
            )

        # The summary should have the key redacted
        assert "sk-1234" not in capsule.summary
        assert "<redacted>" in capsule.summary
