"""Tests for concurrency safety of RoundRobinModel._get_next_model.

FREE-THREADED: _get_next_model is async and uses asyncio.Lock.
These tests verify safe distribution under concurrent async access.
"""

import asyncio
from collections import Counter
from unittest.mock import AsyncMock, MagicMock

from code_muse.round_robin_model import RoundRobinModel


class MockModel:
    def __init__(self, name, settings=None):
        self._name = name
        self._settings = settings
        self.request = AsyncMock(return_value=f"response_from_{name}")
        self.request_stream = MagicMock()
        self.customize_request_parameters = lambda x: x

    @property
    def model_name(self):
        return self._name

    @property
    def settings(self):
        return self._settings

    @property
    def system(self):
        return f"system_{self._name}"

    @property
    def base_url(self):
        return f"https://api.{self._name}.com"

    def model_attributes(self, model):
        return {"model_name": self._name}

    def prepare_request(self, model_settings, model_request_parameters):
        return model_settings, model_request_parameters


async def test_get_next_model_concurrent_safety():
    """Verify _get_next_model distributes evenly under concurrent async access."""
    models = [MockModel(f"model{i}") for i in range(3)]
    rrm = RoundRobinModel(*models)

    results: list[str] = []
    num_workers = 10
    calls_per_worker = 300

    async def worker():
        local = []
        for _ in range(calls_per_worker):
            model = await rrm._get_next_model()
            local.append(model.model_name)
        results.extend(local)

    await asyncio.gather(*[worker() for _ in range(num_workers)])

    total = num_workers * calls_per_worker  # 3000
    assert len(results) == total

    counts = Counter(results)
    expected = total // len(models)  # 1000 each
    # Each model should get exactly 1/3 of requests
    for name, count in counts.items():
        assert count == expected, (
            f"{name} got {count} requests, expected {expected}. "
            f"Distribution: {dict(counts)}"
        )


async def test_get_next_model_concurrent_safety_with_rotate_every():
    """Concurrency safety with rotate_every > 1."""
    models = [MockModel(f"model{i}") for i in range(2)]
    rrm = RoundRobinModel(*models, rotate_every=3)

    results: list[str] = []
    num_workers = 6
    calls_per_worker = 300  # 1800 total, divisible by 6 (rotate_every*num_models)

    async def worker():
        local = []
        for _ in range(calls_per_worker):
            model = await rrm._get_next_model()
            local.append(model.model_name)
        results.extend(local)

    await asyncio.gather(*[worker() for _ in range(num_workers)])

    total = num_workers * calls_per_worker
    assert len(results) == total

    counts = Counter(results)
    # Each model should get exactly half
    expected = total // len(models)
    for name, count in counts.items():
        assert count == expected, (
            f"{name} got {count} requests, expected {expected}. "
            f"Distribution: {dict(counts)}"
        )
