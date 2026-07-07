from __future__ import annotations

from collections.abc import Iterator

import pytest

from tau.axiom.axiom import get_axiom


@pytest.fixture(autouse=True)
def _disable_external_axiom(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep tests from sending telemetry to a real Axiom dataset."""
    monkeypatch.delenv("AXIOM_TOKEN", raising=False)
    monkeypatch.delenv("AXIOM_DATASET", raising=False)
    get_axiom.cache_clear()
    yield
    get_axiom.cache_clear()
