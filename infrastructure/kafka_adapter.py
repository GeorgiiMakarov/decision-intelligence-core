
"""
Real EventBus adapter over Kafka (aiokafka). Partition key = decision_id
(constraints: 'Event Sourcing через Kafka, partition key = decision_id') so
all events for one decision land on one partition and are processed in order.

NOTE for whoever runs this: this file needs `aiokafka` from requirements.txt
and a reachable broker (see docker-compose.yml). It was written against the
same EventBus Protocol as infrastructure/memory_adapters.py and was NOT
executed in the environment that generated this repo (no network / no Kafka
broker available there) — run `make test-integration-kafka` after
`docker-compose up -d kafka` to exercise this adapter for real before relying
on it in production.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

logger = logging.getLogger("core.infrastructure.kafka")

class KafkaEventBus:
    def __init__(self, bootstrap_servers: str, consumer_group: str) -> None:
        self._bootstrap = bootstrap_servers
        self._group = consumer_group
        self._producer: AIOKafkaProducer | None = None
        self._consumers: list[AIOKafkaConsumer] = []
        self._subscriptions: dict[str, list] = {}

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        await self._producer.start()

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
        for c in self._consumers:
            await c.stop()

    async def publish(self, topic: str, key: str, payload: dict[str, Any]) -> None:
        assert self._producer is not None, "call start() before publish()"
        # key = decision_id -> guarantees single-partition ordering per decision.
        await self._producer.send_and_wait(topic, value=payload, key=key)

    async def subscribe(self, topic: str, handler) -> None:
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=self._bootstrap,
            group_id=self._group,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            enable_auto_commit=False,
        )
        await consumer.start()
        self._consumers.append(consumer)

        async def _loop() -> None:
            async for msg in consumer:
                try:
                    await handler(msg.value)
                    await consumer.commit()
                except Exception:  # noqa: BLE001 - log and keep consuming
                    logger.exception("handler failed for topic=%s offset=%s", topic, msg.offset)

        import asyncio
        asyncio.create_task(_loop())




