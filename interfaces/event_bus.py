
"""EventBus interface — Kafka in production (partition key = decision_id, per
constraints), an in-memory fake in tests. Same Protocol either way, which is
what makes the integration tests hermetic without a live broker."""
from __future__ import annotations
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

Handler = Callable[[dict[str, Any]], Awaitable[None]]

@runtime_checkable
class EventBus(Protocol):
    async def publish(self, topic: str, key: str, payload: dict[str, Any]) -> None: ...
    async def subscribe(self, topic: str, handler: Handler) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...




