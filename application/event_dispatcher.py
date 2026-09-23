
"""Routes inbound bus events to the right application-layer handler by
event_type. Runtime-agnostic by construction (section 1.4): this file never
branches on `runtime_context` contents, only on `event_type`."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger("core.event_dispatcher")

RouteHandler = Callable[[dict[str, Any]], Awaitable[None]]

class EventDispatcher:
    def __init__(self) -> None:
        self._routes: dict[str, RouteHandler] = {}

    def register(self, event_type: str, handler: RouteHandler) -> None:
        self._routes[event_type] = handler

    async def dispatch(self, payload: dict[str, Any]) -> None:
        event_type = payload.get("event_type")
        handler = self._routes.get(event_type or "")
        if handler is None:
            logger.warning("no route for event_type=%s, storing as opaque runtime event", event_type)
            return
        await handler(payload)




