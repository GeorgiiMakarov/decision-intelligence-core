
from __future__ import annotations

import pytest

from infrastructure.memory_adapters import MemoryTsa

@pytest.mark.asyncio
async def test_timestamp_token_verifies():
    tsa = MemoryTsa(authority_id="test-tsa")
    digest = b"x" * 32
    token = await tsa.timestamp(digest)
    assert tsa.verify(digest, token)

@pytest.mark.asyncio
async def test_token_does_not_verify_for_different_digest():
    tsa = MemoryTsa(authority_id="test-tsa")
    token = await tsa.timestamp(b"a" * 32)
    assert not tsa.verify(b"b" * 32, token)




