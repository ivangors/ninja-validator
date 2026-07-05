"""Smart upstream routing for multi-endpoint inference backends.

The provider-side prompt/KV cache lives inside one backend process, so routing every
request round-robin can destroy cache locality. This module keeps the balancing
decision at the solve/conversation level: choose one endpoint, keep the proxy sticky
to it, and remember prompt-prefix affinity for future similar solves.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock
from typing import Any

from .cache import json_sha256

_INFRA_UPSTREAM_STATUSES = frozenset({401, 402, 403, 408, 429})
_PREFIX_MESSAGE_ROLES = frozenset({"system", "developer", "user"})
_MAX_PREFIX_CHARS = 16_000


@dataclass(slots=True)
class _EndpointState:
    in_flight: int = 0
    failures: int = 0
    cooldown_until: float = 0.0
    latency_ewma_ms: float | None = None
    cached_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(slots=True)
class _AffinityEntry:
    base_url: str
    expires_at: float


class SmartUpstreamRouter:
    """Thread-safe sticky router with endpoint health and prompt-prefix affinity."""

    def __init__(
        self,
        *,
        affinity_ttl_seconds: float = 60 * 60,
        cooldown_seconds: float = 60,
        max_affinities: int = 4096,
        affinity_load_slack: int = 1,
    ) -> None:
        self.affinity_ttl_seconds = affinity_ttl_seconds
        self.cooldown_seconds = cooldown_seconds
        self.max_affinities = max_affinities
        self.affinity_load_slack = affinity_load_slack
        self._lock = Lock()
        self._states: dict[str, _EndpointState] = {}
        self._affinities: dict[str, _AffinityEntry] = {}
        self._cursor = 0

    def reset(self) -> None:
        """Clear mutable state. Intended for tests and controlled restarts."""
        with self._lock:
            self._states.clear()
            self._affinities.clear()
            self._cursor = 0

    def acquire(
        self, base_urls: tuple[str, ...], affinity_key: str | None = None
    ) -> str:
        if not base_urls:
            raise ValueError("at least one upstream base URL is required")
        now = time.monotonic()
        with self._lock:
            self._expire_affinities_locked(now)
            candidates = [
                url for url in base_urls if self._state_for(url).cooldown_until <= now
            ] or list(base_urls)
            preferred = self._preferred_locked(
                affinity_key=affinity_key,
                base_urls=base_urls,
                candidates=candidates,
                now=now,
            )
            if preferred is not None:
                selected = preferred
            else:
                selected = self._least_loaded_locked(candidates)
            if affinity_key:
                self._remember_affinity_locked(affinity_key, selected, now)
            self._state_for(selected).in_flight += 1
            return selected

    def release(self, base_url: str) -> None:
        with self._lock:
            state = self._state_for(base_url)
            state.in_flight = max(0, state.in_flight - 1)

    def record_result(
        self,
        base_url: str,
        *,
        status_code: int | None,
        error: str | None,
        latency_ms: int | None,
        cached_tokens: int | None = None,
        cache_write_tokens: int | None = None,
    ) -> None:
        now = time.monotonic()
        with self._lock:
            state = self._state_for(base_url)
            if latency_ms is not None:
                if state.latency_ewma_ms is None:
                    state.latency_ewma_ms = float(latency_ms)
                else:
                    state.latency_ewma_ms = (state.latency_ewma_ms * 0.8) + (
                        float(latency_ms) * 0.2
                    )
            state.cached_tokens += int(cached_tokens or 0)
            state.cache_write_tokens += int(cache_write_tokens or 0)
            if _is_infra_failure(status_code=status_code, error=error):
                state.failures += 1
                state.cooldown_until = now + (
                    self.cooldown_seconds * min(state.failures, 4)
                )
            elif status_code is not None and status_code < 400 and error is None:
                state.failures = 0
                state.cooldown_until = 0.0

    def _preferred_locked(
        self,
        *,
        affinity_key: str | None,
        base_urls: tuple[str, ...],
        candidates: list[str],
        now: float,
    ) -> str | None:
        if not affinity_key:
            return None
        entry = self._affinities.get(affinity_key)
        if (
            entry is None
            or entry.expires_at <= now
            or entry.base_url not in base_urls
            or entry.base_url not in candidates
        ):
            return None
        min_in_flight = min(self._state_for(url).in_flight for url in candidates)
        preferred_state = self._state_for(entry.base_url)
        if preferred_state.in_flight <= min_in_flight + self.affinity_load_slack:
            entry.expires_at = now + self.affinity_ttl_seconds
            return entry.base_url
        return None

    def _least_loaded_locked(self, candidates: list[str]) -> str:
        min_in_flight = min(self._state_for(url).in_flight for url in candidates)
        least_loaded = [
            url for url in candidates if self._state_for(url).in_flight == min_in_flight
        ]
        selected = least_loaded[self._cursor % len(least_loaded)]
        self._cursor += 1
        return selected

    def _remember_affinity_locked(
        self, affinity_key: str, base_url: str, now: float
    ) -> None:
        if len(self._affinities) >= self.max_affinities:
            oldest_key = min(
                self._affinities,
                key=lambda key: self._affinities[key].expires_at,
            )
            self._affinities.pop(oldest_key, None)
        self._affinities[affinity_key] = _AffinityEntry(
            base_url=base_url,
            expires_at=now + self.affinity_ttl_seconds,
        )

    def _expire_affinities_locked(self, now: float) -> None:
        expired = [
            key for key, entry in self._affinities.items() if entry.expires_at <= now
        ]
        for key in expired:
            self._affinities.pop(key, None)

    def _state_for(self, base_url: str) -> _EndpointState:
        state = self._states.get(base_url)
        if state is None:
            state = _EndpointState()
            self._states[base_url] = state
        return state


def request_affinity_key(payload: Any, request_path: str) -> str | None:
    """Return a stable prompt-prefix key for cache-aware routing."""
    if not isinstance(payload, dict):
        return None
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    prefix_messages = _prefix_messages(messages)
    if not prefix_messages:
        return None
    return json_sha256(
        {
            "path": request_path,
            "model": payload.get("model"),
            "tools": payload.get("tools"),
            "response_format": payload.get("response_format"),
            "messages": prefix_messages,
        }
    )


def _prefix_messages(messages: list[Any]) -> list[Any]:
    prefix: list[Any] = []
    char_budget = _MAX_PREFIX_CHARS
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in _PREFIX_MESSAGE_ROLES:
            break
        content = _truncate_content(message.get("content"), char_budget)
        compact = {"role": role, "content": content}
        prefix.append(compact)
        char_budget -= len(str(content))
        if role == "user" or char_budget <= 0:
            break
    return prefix


def _truncate_content(value: Any, char_budget: int) -> Any:
    if isinstance(value, str) and len(value) > char_budget:
        return value[:char_budget]
    return value


def _is_infra_failure(*, status_code: int | None, error: str | None) -> bool:
    if status_code is None:
        return error is not None
    return status_code >= 500 or status_code in _INFRA_UPSTREAM_STATUSES


SMART_UPSTREAM_ROUTER = SmartUpstreamRouter()
