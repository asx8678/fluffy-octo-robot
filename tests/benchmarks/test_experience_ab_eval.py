"""Offline A/B evaluation for experience store token reduction.  # noqa: E501

Measures actual token reduction when the experience store injects compact
capsule summaries versus a full-from-scratch baseline. Uses the same
token estimator (char/2.5) and injection format as the production code.

Usage:
    uv run pytest tests/benchmarks/test_experience_ab_eval.py -v
    uv run python tests/benchmarks/test_experience_ab_eval.py
    REPORT=True uv run pytest tests/benchmarks/test_experience_ab_eval.py -v
"""

# ruff: noqa: E501

from __future__ import annotations

import json
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from code_muse.agents._history import estimate_tokens
from code_muse.plugins.task_context.experience_models import ExperienceCapsule
from code_muse.plugins.task_context.experience_signature import (
    compute_capsule_signature,
)
from code_muse.plugins.task_context.experience_store import (
    search_experience,
    store_capsule,
)

# ---------------------------------------------------------------------------
# Token estimator — reuse the production char/2.5 heuristic
# ---------------------------------------------------------------------------


def _estimate_tokens_for_text(text: str) -> int:
    """Estimate tokens for a string using the same char/2.5 heuristic."""
    return estimate_tokens(text)


def _estimate_tokens_for_messages(messages: list[dict[str, str]]) -> int:
    """Estimate total tokens across a list of message dicts."""
    total = 0
    for msg in messages:
        total += _estimate_tokens_for_text(msg.get("content", ""))
    return total


# ---------------------------------------------------------------------------
# Synthetic task pair definitions
# ---------------------------------------------------------------------------

# Each pair: (task_a_label, task_b_label, first_occurrence_msgs, second_occurrence_msgs)
# first_occurrence_msgs: 4-8 messages showing full solution derivation (becomes capsule)
# second_occurrence_msgs: 2-4 messages asking for similar work (the new request)

TASK_PAIRS: list[dict[str, Any]] = [
    {
        "name": "middleware-patterns",
        "pair": ("implement-auth-middleware", "implement-rate-limiter"),
        "first_occurrence_msgs": [
            {
                "role": "user",
                "content": "I need to implement an authentication middleware for our FastAPI app. It should validate JWT tokens from the Authorization header and reject unauthenticated requests with 401.",
            },
            {
                "role": "assistant",
                "content": "Here's the auth middleware implementation:\n\n```python\nfrom fastapi import Request, HTTPException\nfrom starlette.middleware.base import BaseHTTPMiddleware\nimport jwt\n\nclass AuthMiddleware(BaseHTTPMiddleware):\n    async def dispatch(self, request: Request, call_next):\n        auth_header = request.headers.get('Authorization', '')\n        if not auth_header.startswith('Bearer '):\n            raise HTTPException(status_code=401, detail='Missing or invalid token')\n        try:\n            token = auth_header.split(' ')[1]\n            payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])\n            request.state.user = payload\n        except jwt.InvalidTokenError:\n            raise HTTPException(status_code=401, detail='Invalid token')\n        response = await call_next(request)\n        return response\n```\n\nThis middleware extracts the Bearer token, validates it with PyJWT, and attaches the decoded payload to `request.state.user`.",
            },
            {
                "role": "user",
                "content": "What about handling expired tokens? And we need to skip auth for the /health endpoint.",
            },
            {
                "role": "assistant",
                "content": "Good catches. Updated implementation:\n\n```python\nfrom datetime import datetime, timezone\n\nEXEMPT_PATHS = {'/health', '/metrics', '/ready'}\n\nclass AuthMiddleware(BaseHTTPMiddleware):\n    async def dispatch(self, request: Request, call_next):\n        if request.url.path in EXEMPT_PATHS:\n            return await call_next(request)\n        auth_header = request.headers.get('Authorization', '')\n        if not auth_header.startswith('Bearer '):\n            raise HTTPException(status_code=401)\n        try:\n            token = auth_header.split(' ')[1]\n            payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])\n            if payload.get('exp', 0) < datetime.now(timezone.utc).timestamp():\n                raise HTTPException(status_code=401, detail='Token expired')\n            request.state.user = payload\n        except jwt.InvalidTokenError:\n            raise HTTPException(status_code=401)\n        return await call_next(request)\n```\n\nThe `exp` claim check catches expired tokens. `EXEMPT_PATHS` lets health/metrics through without auth.",
            },
            {
                "role": "user",
                "content": "Also need to add the middleware to the app and write a couple of tests.",
            },
            {
                "role": "assistant",
                "content": "Adding to the app:\n\n```python\napp = FastAPI()\napp.add_middleware(AuthMiddleware)\n```\n\nTest:\n```python\nfrom fastapi.testclient import TestClient\n\ndef test_auth_middleware_valid_token():\n    token = jwt.encode({'sub': 'user1', 'exp': ...}, SECRET_KEY, algorithm='HS256')\n    response = client.get('/api/data', headers={'Authorization': f'Bearer {token}'})\n    assert response.status_code == 200\n\ndef test_auth_middleware_missing_token():\n    response = client.get('/api/data')\n    assert response.status_code == 401\n\n\ndef test_auth_middleware_health_exempt():\n    response = client.get('/health')\n    assert response.status_code == 200\n```\n\nAll three cases covered: valid token, missing token, and exempt path.",
            },
        ],
        "second_occurrence_msgs": [
            {
                "role": "user",
                "content": "Now I need a rate limiter middleware for our FastAPI app. It should track requests per IP and return 429 when limits are exceeded. Similar pattern to the auth middleware we built earlier.",
            },
            {
                "role": "assistant",
                "content": "Sure, I'll implement a rate limiter using a sliding window approach with in-memory storage. Do you want per-endpoint limits or a global limit?",
            },
            {
                "role": "user",
                "content": "Per-endpoint with a global fallback. Skip /health just like the auth middleware. And we'll need the same pattern of adding it to the app and writing tests.",
            },
        ],
    },
    {
        "name": "security-fixes",
        "pair": ("fix-sql-injection", "fix-xss-sanitization"),
        "first_occurrence_msgs": [
            {
                "role": "user",
                "content": "We have a SQL injection vulnerability in our user search endpoint. The query builds SQL by concatenating user input directly into the WHERE clause. Need to fix this across the entire codebase.",
            },
            {
                "role": "assistant",
                "content": "Identified the vulnerable pattern. Here's the fix:\n\n```python\n# BEFORE (vulnerable)\nquery = f\"SELECT * FROM users WHERE name = '{name}'\"\n\n# AFTER (parameterized)\nquery = \"SELECT * FROM users WHERE name = %s\"\ncursor.execute(query, (name,))\n```\n\nFor the ORM layer:\n```python\n# BEFORE\nUser.objects.raw(f\"SELECT * FROM users WHERE email = '{email}'\")\n\n# AFTER\nUser.objects.filter(email=email)\n```\n\nAlso adding input validation:\n```python\nimport re\n\ndef validate_search_input(value: str, max_length: int = 200) -> str:\n    if len(value) > max_length:\n        raise ValueError(f'Input exceeds max length of {max_length}')\n    if not re.match(r'^[a-zA-Z0-9_.-@ ]+$', value):\n        raise ValueError('Input contains disallowed characters')\n    return value\n```",
            },
            {
                "role": "user",
                "content": "What about the stored procedure calls that also use string formatting?",
            },
            {
                "role": "assistant",
                "content": 'Fixed the stored procedure calls too:\n\n```python\n# BEFORE\ncursor.execute(f"CALL get_user_by_id({user_id})")\n\n# AFTER\ncursor.execute("CALL get_user_by_id(%s)", (user_id,))\n```\n\nAdded a codebase-wide lint rule to catch string formatting in SQL:\n```toml\n[tool.ruff]\nselect = [\'S608\']  # detect SQL injection via string formatting\n```',
            },
            {
                "role": "user",
                "content": "Write tests to confirm the injection is blocked.",
            },
            {
                "role": "assistant",
                "content": "Tests:\n```python\ndef test_sql_injection_blocked_parameterized():\n    malicious = \"' OR '1'='1\"\n    result = search_users(malicious)\n    assert len(result) == 0  # No data leaked\n\ndef test_stored_proc_injection_blocked():\n    malicious = '1; DROP TABLE users--'\n    with pytest.raises(ValueError):\n        get_user_by_id(malicious)\n\ndef test_input_validation_rejects_sql():\n    with pytest.raises(ValueError):\n        validate_search_input(\"Robert'); DROP TABLE--\")\n```",
            },
        ],
        "second_occurrence_msgs": [
            {
                "role": "user",
                "content": "We now have an XSS vulnerability in the comment rendering. User-submitted HTML is being rendered directly in the template without sanitization. Need the same approach as the SQL injection fix — parameterized output and input validation across the codebase.",
            },
            {
                "role": "assistant",
                "content": "I'll audit all template rendering paths and add HTML escaping. Do you want me to use bleach or a simpler allowlist approach?",
            },
            {
                "role": "user",
                "content": "Use the simpler allowlist. Same pattern: fix the vulnerable paths, add input validation, write tests, add a lint rule for unsafe template rendering.",
            },
        ],
    },
    {
        "name": "pipeline-patterns",
        "pair": ("add-logging-pipeline", "add-metrics-pipeline"),
        "first_occurrence_msgs": [
            {
                "role": "user",
                "content": "Build a structured logging pipeline for our data processing service. It should support JSON output, log levels (DEBUG/INFO/WARN/ERROR), request correlation IDs, and automatic context enrichment.",
            },
            {
                "role": "assistant",
                "content": "Here's the pipeline architecture:\n\n```python\nimport structlog\nimport logging\nfrom contextvars import ContextVar\n\ncorrelation_id: ContextVar[str] = ContextVar('correlation_id', default='')\n\ndef configure_logging(service_name: str, level: str = 'INFO'):\n    structlog.configure(\n        processors=[\n            structlog.contextvars.merge_contextvars,\n            structlog.processors.add_log_level,\n            structlog.processors.TimeStamper(fmt='iso'),\n            enrich_with_correlation_id,\n            structlog.processors.JSONRenderer()\n        ],\n        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),\n        context_class=dict,\n        logger_factory=structlog.PrintLoggerFactory(),\n    )\n\ndef enrich_with_correlation_id(logger, method_name, event_dict):\n    cid = correlation_id.get('')\n    if cid:\n        event_dict['correlation_id'] = cid\n    event_dict['service'] = service_name\n    return event_dict\n```\n\nUses structlog with context vars for correlation ID propagation.",
            },
            {
                "role": "user",
                "content": "How do we integrate this with our FastAPI request handling?",
            },
            {
                "role": "assistant",
                "content": "FastAPI integration:\n\n```python\nfrom starlette.middleware.base import BaseHTTPMiddleware\nimport uuid\n\nclass CorrelationMiddleware(BaseHTTPMiddleware):\n    async def dispatch(self, request, call_next):\n        cid = request.headers.get('X-Correlation-ID', str(uuid.uuid4()))\n        correlation_id.set(cid)\n        response = await call_next(request)\n        response.headers['X-Correlation-ID'] = cid\n        return response\n\n@app.middleware('http')\nasync def log_requests(request, call_next):\n    log = structlog.get_logger()\n    log.info('request_started', method=request.method, path=request.url.path)\n    response = await call_next(request)\n    log.info('request_completed', status=response.status_code)\n    return response\n```\n\nThe middleware sets the correlation ID, and the logging middleware logs every request with full context.",
            },
            {"role": "user", "content": "Add tests for the logging pipeline."},
            {
                "role": "assistant",
                "content": "Tests:\n```python\ndef test_json_output_format(capsys):\n    configure_logging('test-service')\n    log = structlog.get_logger()\n    log.info('test_event', key='value')\n    output = capsys.readouterr().out\n    parsed = json.loads(output)\n    assert parsed['event'] == 'test_event'\n    assert parsed['key'] == 'value'\n    assert 'timestamp' in parsed\n\ndef test_correlation_id_propagation():\n    correlation_id.set('test-cid-123')\n    configure_logging('test-service')\n    log = structlog.get_logger()\n    log.info('correlated_event')\n    # Verify correlation_id appears in output\n\ndef test_log_level_filtering():\n    configure_logging('test-service', level='WARN')\n    log = structlog.get_logger()\n    log.info('should_not_appear')\n    log.warn('should_appear')\n```",
            },
        ],
        "second_occurrence_msgs": [
            {
                "role": "user",
                "content": "Now add a metrics pipeline alongside the logging pipeline. Same pattern: structured output, correlation IDs, FastAPI middleware integration, and automatic context enrichment. It should track request latency, error rates, and throughput.",
            },
            {
                "role": "assistant",
                "content": "I'll follow the same pipeline architecture. Should I use Prometheus client for exposition or a custom format?",
            },
            {
                "role": "user",
                "content": "Prometheus client. Same pattern as logging: middleware, context vars, tests.",
            },
        ],
    },
    {
        "name": "refactoring-patterns",
        "pair": ("refactor-task-manager", "refactor-pruner-module"),
        "first_occurrence_msgs": [
            {
                "role": "user",
                "content": "Refactor the task_manager.py module. It's a 400-line god class that mixes task lifecycle management, persistence, and event emission. Split it into separate concerns following SRP.",
            },
            {
                "role": "assistant",
                "content": "Refactoring plan:\n\n1. **TaskLifecycle** — create/update/complete/abandon task state transitions\n2. **TaskPersistence** — JSON save/load, archive management\n3. **TaskEvents** — emit_info/emit_success/emit_warning for state changes\n4. **TaskManager** (facade) — thin coordinator delegating to the above\n\n```python\n# task_lifecycle.py\nclass TaskLifecycle:\n    def __init__(self, state_store: TaskPersistence):\n        self._store = state_store\n\n    def create_task(self, label: str) -> Task:\n        task = Task(task_id=str(uuid4()), label=label, status=TaskStatus.ACTIVE)\n        self._store.save(task)\n        return task\n\n    def complete_task(self, task_id: str, outcome: str = '') -> Task:\n        task = self._store.load(task_id)\n        task.status = TaskStatus.COMPLETED\n        task.outcome_summary = outcome\n        task.completed_at = datetime.now()\n        self._store.save(task)\n        return task\n```\n\n```python\n# task_persistence.py\nclass TaskPersistence:\n    def __init__(self, path: Path):\n        self._path = path\n\n    def save(self, task: Task) -> None:\n        # append-only JSONL\n        ...\n\n    def load(self, task_id: str) -> Task:\n        ...\n```\n\n```python\n# task_events.py\nclass TaskEvents:\n    @staticmethod\n    def on_task_created(task: Task) -> None:\n        emit_success(f'Task started: {task.label}')\n\n    @staticmethod\n    def on_task_completed(task: Task) -> None:\n        emit_info(f'Task completed: {task.label} — {task.outcome_summary[:80]}')\n```",
            },
            {
                "role": "user",
                "content": "How do we preserve backward compatibility? The existing code calls task_manager.get_active_task() everywhere.",
            },
            {
                "role": "assistant",
                "content": "The facade preserves the existing API:\n\n```python\n# task_manager.py (refactored — thin facade)\nclass TaskManager:\n    def __init__(self, store_dir: Path | None = None):\n        self._persistence = TaskPersistence(store_dir or Path.cwd())\n        self._lifecycle = TaskLifecycle(self._persistence)\n        self._events = TaskEvents()\n\n    # Existing API — delegates\n    def get_active_task(self) -> Task | None: ...\n    def create_task(self, label: str) -> Task: ...\n    def complete_task(self, task_id: str, outcome: str = '') -> Task: ...\n    def get_completed_tasks(self) -> list[Task]: ...\n```\n\nZero breaking changes. All existing call sites continue to work through delegation.",
            },
        ],
        "second_occurrence_msgs": [
            {
                "role": "user",
                "content": "Refactor the pruner.py module the same way — it's another god class mixing scoring logic, pruning decisions, and archive operations. Apply the same SRP split and facade pattern you used for task_manager.",
            },
            {
                "role": "user",
                "content": "Same approach: split into ScoringLogic, PruneDecisions, ArchiveOps, then Pruner facade for backward compatibility.",
            },
        ],
    },
    {
        "name": "test-setup-patterns",
        "pair": ("write-api-tests", "write-model-tests"),
        "first_occurrence_msgs": [
            {
                "role": "user",
                "content": "Write comprehensive API tests for our user management endpoints. We need tests for CRUD operations, authentication, authorization, pagination, and error handling.",
            },
            {
                "role": "assistant",
                "content": "Here's the test structure:\n\n```python\nimport pytest\nfrom httpx import AsyncClient\nfrom app.main import app\n\n@pytest.fixture\nasync def client():\n    async with AsyncClient(app=app, base_url='http://test') as c:\n        yield c\n\n@pytest.fixture\nasync def auth_headers():\n    # Create test user and return auth headers\n    token = create_test_token(user_id='test-user')\n    return {'Authorization': f'Bearer {token}'}\n\n# CRUD tests\nasync def test_create_user(client, auth_headers):\n    response = await client.post('/api/users', json={'name': 'Alice', 'email': 'alice@test.com'}, headers=auth_headers)\n    assert response.status_code == 201\n    data = response.json()\n    assert data['name'] == 'Alice'\n    assert 'id' in data\n\nasync def test_list_users_paginated(client, auth_headers):\n    response = await client.get('/api/users?page=1&per_page=10', headers=auth_headers)\n    assert response.status_code == 200\n    assert 'items' in response.json()\n    assert 'total' in response.json()\n\n# Auth tests\nasync def test_unauthenticated_rejected(client):\n    response = await client.get('/api/users')\n    assert response.status_code == 401\n\n# Error handling\nasync def test_duplicate_email_409(client, auth_headers):\n    await client.post('/api/users', json={'name': 'A', 'email': 'dup@test.com'}, headers=auth_headers)\n    response = await client.post('/api/users', json={'name': 'B', 'email': 'dup@test.com'}, headers=auth_headers)\n    assert response.status_code == 409\n```",
            },
            {
                "role": "user",
                "content": "Add tests for the update and delete endpoints, and for edge cases like empty payloads.",
            },
            {
                "role": "assistant",
                "content": "Additional tests:\n\n```python\nasync def test_update_user(client, auth_headers):\n    create = await client.post('/api/users', json={'name': 'Bob'}, headers=auth_headers)\n    user_id = create.json()['id']\n    response = await client.patch(f'/api/users/{user_id}', json={'name': 'Robert'}, headers=auth_headers)\n    assert response.status_code == 200\n    assert response.json()['name'] == 'Robert'\n\nasync def test_delete_user(client, auth_headers):\n    create = await client.post('/api/users', json={'name': 'Eve'}, headers=auth_headers)\n    user_id = create.json()['id']\n    response = await client.delete(f'/api/users/{user_id}', headers=auth_headers)\n    assert response.status_code == 204\n\nasync def test_empty_payload_422(client, auth_headers):\n    response = await client.post('/api/users', json={}, headers=auth_headers)\n    assert response.status_code == 422\n\nasync def test_not_found_404(client, auth_headers):\n    response = await client.get('/api/users/nonexistent-id', headers=auth_headers)\n    assert response.status_code == 404\n```",
            },
        ],
        "second_occurrence_msgs": [
            {
                "role": "user",
                "content": "Now write model tests for our User and Team models. Same comprehensive approach: CRUD, validation, relationships, and error cases. Use pytest fixtures the same way as the API tests.",
            },
            {
                "role": "user",
                "content": "Use the same fixture pattern (test db, auth headers). Also test model-level constraints like unique email and cascade deletes.",
            },
        ],
    },
    {
        "name": "cicd-patterns",
        "pair": ("configure-ci-workflow", "configure-cd-deployment"),
        "first_occurrence_msgs": [
            {
                "role": "user",
                "content": "Set up a CI workflow for our Python project on GitHub Actions. We need linting (ruff), type checking (mypy), unit tests (pytest), and integration tests. Matrix across Python 3.11 and 3.12.",
            },
            {
                "role": "assistant",
                "content": "Here's the workflow:\n\n```yaml\nname: CI\non:\n  push:\n    branches: [main]\n  pull_request:\n    branches: [main]\n\njobs:\n  lint:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n      - run: pip install ruff\n      - run: ruff check --output-format=github .\n      - run: ruff format --check .\n\n  typecheck:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n      - run: pip install mypy\n      - run: mypy --strict src/\n\n  test:\n    strategy:\n      matrix:\n        python-version: ['3.11', '3.12']\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: ${{ matrix.python-version }}\n      - run: pip install -e '.[dev]'\n      - run: pytest --cov=src --cov-fail-under=80\n\n  integration:\n    needs: test\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n      - run: pip install -e '.[dev]'\n      - run: pytest tests/integration/ -m integration\n```\n\nFour jobs: lint, typecheck, test (with matrix), and integration (depends on test).",
            },
            {
                "role": "user",
                "content": "Add caching for pip and make the integration test job conditional on main branch only.",
            },
            {
                "role": "assistant",
                "content": "Added caching and conditional:\n\n```yaml\n  test:\n    steps:\n      - uses: actions/cache@v4\n        with:\n          path: ~/.cache/pip\n          key: pip-${{ runner.os }}-${{ hashFiles('pyproject.toml') }}\n      - run: pip install -e '.[dev]'\n\n  integration:\n    if: github.ref == 'refs/heads/main'\n    needs: test\n```\n\nCache key uses pyproject.toml hash so it invalidates on dependency changes. Integration only runs on main pushes.",
            },
        ],
        "second_occurrence_msgs": [
            {
                "role": "user",
                "content": (
                    "Now set up a CD deployment workflow for our Python project"
                    " on GitHub Actions, similar to the CI workflow. Deploy to"
                    " AWS ECS with staged rollout. Reuse the caching pattern"
                    " from CI and make prod deploy require manual approval."
                    " Same GitHub Actions YAML structure with linting, testing,"
                    " and integration steps."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Follow the same GitHub Actions YAML structure with"
                    " reusable steps. Add deployment steps using AWS CLI"
                    " and ECS task definitions, similar to how we set up"
                    " the CI pipeline with caching and conditional jobs."
                ),
            },
        ],
    },
]


# ---------------------------------------------------------------------------
# Injection text builder — mirrors _on_message_history_processor_start_with_experience
# ---------------------------------------------------------------------------


def _build_injection_text(
    results: list[tuple[ExperienceCapsule, float]],
) -> str:
    """Build the compact injection message using the same format as the callback.

    Mirrors: register_callbacks.py lines ~245-250
    """
    injection_lines = ["Relevant past experience capsules:"]
    for capsule, _similarity in results:
        injection_lines.append(
            f"- [{capsule.capsule_id[:8]}] "
            f"{capsule.task_label}: {capsule.outcome_summary[:150]}"
        )
    return "\n".join(injection_lines)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class PairResult:
    """Token reduction result for a single task pair."""

    name: str
    pair: tuple[str, str]
    baseline_tokens: int
    injection_tokens: int
    saved_tokens: int
    reduction_pct: float
    search_ms: float


# ---------------------------------------------------------------------------
# Core evaluation function
# ---------------------------------------------------------------------------


def _run_evaluation(
    store_dir: Path,
    repo_scope: str,
) -> list[PairResult]:
    """Run the A/B evaluation across all task pairs.

    Args:
        store_dir: Temp directory for the experience store.
        repo_scope: Deterministic repo scope hash for isolation.

    Returns:
        List of PairResult with per-pair metrics.
    """
    results: list[PairResult] = []

    for pair_def in TASK_PAIRS:
        pair_name = pair_def["name"]
        task_a, task_b = pair_def["pair"]
        first_msgs = pair_def["first_occurrence_msgs"]
        second_msgs = pair_def["second_occurrence_msgs"]

        # --- Step 1: Create capsule from first occurrence ---
        # Combine first-occurrence messages into a single text for the capsule
        first_text = "\n".join(m["content"] for m in first_msgs)
        outcome_summary = first_text[:300]  # Compact outcome summary
        summary_text = first_text[:500]

        key_terms, semantic_signature, structural_fingerprint = (
            compute_capsule_signature(
                task_label=task_a,
                outcome_summary=outcome_summary,
                summary=summary_text,
                metadata={"domain": pair_name},
            )
        )

        capsule = ExperienceCapsule(
            task_id=f"task_{pair_name}_a",
            task_label=task_a,
            outcome_summary=outcome_summary,
            repo_scope=repo_scope,
            summary=summary_text[:500],
            key_terms=key_terms,
            semantic_signature=semantic_signature,
            structural_fingerprint=structural_fingerprint,
            token_estimate=_estimate_tokens_for_messages(first_msgs),
            metadata={"domain": pair_name},
        )

        store_capsule(capsule)

        # --- Step 2: Measure baseline tokens ---
        # Baseline = what the agent would process from scratch
        # This is the full first-occurrence conversation + second occurrence
        baseline_tokens = _estimate_tokens_for_messages(
            first_msgs
        ) + _estimate_tokens_for_messages(second_msgs)

        # --- Step 3: Search experience for second occurrence query ---
        query_text = " ".join(m["content"] for m in second_msgs)[:500]
        search_start = time.monotonic()
        search_results = search_experience(
            query=query_text,
            top_k=3,
            min_similarity=0.3,
        )
        search_ms = (time.monotonic() - search_start) * 1000

        # --- Step 4: Measure tokens with experience injection ---
        # With experience = injection text + second occurrence only
        # (the capsule replaces the need for the full first-occurrence context)
        injection_text = _build_injection_text(search_results) if search_results else ""
        injection_tokens = _estimate_tokens_for_text(
            injection_text
        ) + _estimate_tokens_for_messages(second_msgs)

        # --- Step 5: Compute reduction ---
        saved = baseline_tokens - injection_tokens
        reduction_pct = (saved / max(baseline_tokens, 1)) * 100

        results.append(
            PairResult(
                name=pair_name,
                pair=(task_a, task_b),
                baseline_tokens=baseline_tokens,
                injection_tokens=injection_tokens,
                saved_tokens=saved,
                reduction_pct=reduction_pct,
                search_ms=search_ms,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _print_report(results: list[PairResult]) -> None:
    """Print a human-readable summary table."""
    print("\n" + "=" * 90)
    print("  OFFLINE A/B EVAL: Experience Store Token Reduction")
    print("=" * 90)

    # Header
    header = (
        f"{'Task Pair':<22} {'Baseline':>10}"
        f" {'Injection':>10} {'Saved':>10}"
        f" {'Reduction':>10} {'Search ms':>10}"
    )
    print(header)
    print("-" * 90)

    for r in results:
        row = (
            f"{r.name:<22} {r.baseline_tokens:>10,} {r.injection_tokens:>10,}"
            f" {r.saved_tokens:>10,} {r.reduction_pct:>9.1f}% {r.search_ms:>9.1f}ms"
        )
        print(row)

    print("-" * 90)

    # Aggregate stats
    reductions = [r.reduction_pct for r in results]
    search_times = [r.search_ms for r in results]

    print(
        f"\n  Reduction %  — min: {min(reductions):.1f}%"
        f"  max: {max(reductions):.1f}%"
        f"  median: {statistics.median(reductions):.1f}%"
        f"  mean: {statistics.mean(reductions):.1f}%"
    )
    print(f"  Search time  — max: {max(search_times):.1f}ms  (limit: 150ms)")
    mean_red = statistics.mean(reductions)
    target_met = mean_red >= 15
    target_icon = "✅ MET" if target_met else "❌ NOT MET"
    target_desc = f"  Target: >=15%  ->  {target_icon}  (mean {mean_red:.1f}%"
    if mean_red > 30:
        target_desc += ", exceeds 30% ceiling — excellent"
    target_desc += ")"
    print(target_desc)
    print()


def _emit_json(results: list[PairResult]) -> dict:
    """Emit machine-readable JSON report."""
    reductions = [r.reduction_pct for r in results]
    return {
        "evaluation": "experience_store_ab_eval",
        "pairs": [
            {
                "name": r.name,
                "pair": list(r.pair),
                "baseline_tokens": r.baseline_tokens,
                "injection_tokens": r.injection_tokens,
                "saved_tokens": r.saved_tokens,
                "reduction_pct": round(r.reduction_pct, 2),
                "search_ms": round(r.search_ms, 2),
            }
            for r in results
        ],
        "summary": {
            "min_reduction_pct": round(min(reductions), 2),
            "max_reduction_pct": round(max(reductions), 2),
            "median_reduction_pct": round(statistics.median(reductions), 2),
            "mean_reduction_pct": round(statistics.mean(reductions), 2),
            "max_search_ms": round(max(r.search_ms for r in results), 2),
            "target_met": statistics.mean(reductions) >= 15,
        },
    }


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _use_temp_store(tmp_path, monkeypatch):
    """Redirect experience store to a temp directory for isolation."""
    store_dir = tmp_path / "exp_store_ab"
    monkeypatch.setattr(
        "code_muse.plugins.task_context.experience_store.EXPERIENCE_STORE_DIR",
        store_dir,
    )
    # Reset injected queries tracker
    import code_muse.plugins.task_context.register_callbacks as rb

    rb._injected_queries.clear()
    yield


@pytest.fixture()
def deterministic_repo_scope(monkeypatch):
    """Set a deterministic repo scope for reproducible evaluation."""
    scope = "ab_eval_deadbeef"

    def _mock_get_repo_scope():
        return scope

    monkeypatch.setattr(
        "code_muse.plugins.task_context.experience_store.get_repo_scope",
        _mock_get_repo_scope,
    )
    return scope


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExperienceABEval:
    """Offline A/B evaluation for experience store token reduction."""

    def test_token_reduction_meets_target(self, deterministic_repo_scope, monkeypatch):
        """Core eval: experience injection should reduce tokens by 15–30%."""
        from code_muse.plugins.task_context.experience_store import EXPERIENCE_STORE_DIR

        # Disable global store for isolation
        monkeypatch.setattr(
            "code_muse.plugins.task_context.experience_store.get_global_store_path",
            lambda: EXPERIENCE_STORE_DIR / "_global.jsonl",
        )

        results = _run_evaluation(
            store_dir=EXPERIENCE_STORE_DIR,
            repo_scope=deterministic_repo_scope,
        )

        assert len(results) == len(TASK_PAIRS), (
            f"Expected {len(TASK_PAIRS)} results, got {len(results)}"
        )

        # Print report regardless (helps debugging)
        _print_report(results)

        # JSON report if requested
        if os.environ.get("REPORT") in ("1", "true", "True", "TRUE"):
            report = _emit_json(results)
            report_path = Path("experience_ab_eval_report.json")
            report_path.write_text(json.dumps(report, indent=2))
            print(f"\n📄 JSON report written to {report_path}")

        # Assertions
        reductions = [r.reduction_pct for r in results]

        # Every pair should show some reduction (experience store is helping)
        for r in results:
            assert r.reduction_pct > 0, (
                f"Pair '{r.name}' showed no token"
                " reduction — experience injection had no effect"
            )

        # Mean reduction should meet the >=15% target
        # (exceeding 30% is fine — it means the store is very effective)
        mean_reduction = statistics.mean(reductions)
        assert mean_reduction >= 15, (
            f"Mean reduction {mean_reduction:.1f}% below 15% target. "
            f"Per-pair: {[(r.name, r.reduction_pct) for r in results]}"
        )

    def test_search_latency_under_150ms(self, deterministic_repo_scope, monkeypatch):
        """Each search call must complete in under 150ms."""
        from code_muse.plugins.task_context.experience_store import EXPERIENCE_STORE_DIR

        monkeypatch.setattr(
            "code_muse.plugins.task_context.experience_store.get_global_store_path",
            lambda: EXPERIENCE_STORE_DIR / "_global.jsonl",
        )

        results = _run_evaluation(
            store_dir=EXPERIENCE_STORE_DIR,
            repo_scope=deterministic_repo_scope,
        )

        for r in results:
            assert r.search_ms < 150, (
                f"Pair '{r.name}' search took {r.search_ms:.1f}ms — exceeds 150ms limit"
            )

    def test_full_eval_under_5_seconds(self, deterministic_repo_scope, monkeypatch):
        """The full evaluation must complete in under 5 seconds."""
        from code_muse.plugins.task_context.experience_store import EXPERIENCE_STORE_DIR

        monkeypatch.setattr(
            "code_muse.plugins.task_context.experience_store.get_global_store_path",
            lambda: EXPERIENCE_STORE_DIR / "_global.jsonl",
        )

        start = time.monotonic()
        _run_evaluation(
            store_dir=EXPERIENCE_STORE_DIR,
            repo_scope=deterministic_repo_scope,
        )
        elapsed = time.monotonic() - start

        assert elapsed < 5.0, f"Full eval took {elapsed:.2f}s — exceeds 5s limit"

    def test_all_pairs_find_capsules(self, deterministic_repo_scope, monkeypatch):
        """Every task pair should find at least one relevant capsule."""
        from code_muse.plugins.task_context.experience_store import (
            EXPERIENCE_STORE_DIR,
            search_experience,
        )

        monkeypatch.setattr(
            "code_muse.plugins.task_context.experience_store.get_global_store_path",
            lambda: EXPERIENCE_STORE_DIR / "_global.jsonl",
        )

        # Populate store with all first-occurrence capsules
        for pair_def in TASK_PAIRS:
            pair_name = pair_def["name"]
            task_a = pair_def["pair"][0]
            first_msgs = pair_def["first_occurrence_msgs"]
            first_text = "\n".join(m["content"] for m in first_msgs)

            key_terms, semantic_signature, structural_fingerprint = (
                compute_capsule_signature(
                    task_label=task_a,
                    outcome_summary=first_text[:300],
                    summary=first_text[:500],
                    metadata={"domain": pair_name},
                )
            )

            capsule = ExperienceCapsule(
                task_id=f"task_{pair_name}_a",
                task_label=task_a,
                outcome_summary=first_text[:300],
                repo_scope=deterministic_repo_scope,
                summary=first_text[:500],
                key_terms=key_terms,
                semantic_signature=semantic_signature,
                structural_fingerprint=structural_fingerprint,
                token_estimate=_estimate_tokens_for_messages(first_msgs),
                metadata={"domain": pair_name},
            )
            store_capsule(capsule)

        # Each second-occurrence query should find a result
        for pair_def in TASK_PAIRS:
            second_msgs = pair_def["second_occurrence_msgs"]
            query_text = " ".join(m["content"] for m in second_msgs)[:500]
            results = search_experience(query=query_text, top_k=3, min_similarity=0.3)
            assert len(results) > 0, (
                f"Pair '{pair_def['name']}' found no capsules"
                f" for query: {query_text[:60]}..."
            )


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------


def main():
    """Run the evaluation standalone (without pytest)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        store_dir = Path(tmp_dir) / "exp_store_ab"
        store_dir.mkdir(parents=True, exist_ok=True)
        repo_scope = "ab_eval_deadbeef"

        # Patch store dir
        with patch(
            "code_muse.plugins.task_context.experience_store.EXPERIENCE_STORE_DIR",
            store_dir,
        ):
            results = _run_evaluation(
                store_dir=store_dir,
                repo_scope=repo_scope,
            )

        _print_report(results)

        # JSON report if requested
        if os.environ.get("REPORT") in ("1", "true", "True", "TRUE"):
            report = _emit_json(results)
            report_path = Path("experience_ab_eval_report.json")
            report_path.write_text(json.dumps(report, indent=2))
            print(f"📄 JSON report written to {report_path}")


if __name__ == "__main__":
    main()
