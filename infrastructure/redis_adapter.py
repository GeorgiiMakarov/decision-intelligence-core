
"""Real ProjectionStore adapter over Redis. See kafka_adapter.py's note:
written against the same Protocol as memory_adapters.MemoryProjectionStore,
not executed in the environment that generated this repo (redis package not
installed, no network to fetch it, no broker reachable)."""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis

class RedisProjectionStore:
    def __init__(self, url: str) -> None:
        self._client = redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> dict[str, Any] | None:
        raw = await self._client.get(key)
        return json.loads(raw) if raw is not None else None

    async def set(self, key: str, value: dict[str, Any]) -> None:
        await self._client.set(key, json.dumps(value))

    async def get_many(self, prefix: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        async for key in self._client.scan_iter(match=f"{prefix}*"):
            raw = await self._client.get(key)
            if raw is not None:
                out[key] = json.loads(raw)
        return out




