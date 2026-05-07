"""Python module with async functions for AST fixture testing."""

import asyncio


async def async_fetch(url):
    """Fetch URL asynchronously."""
    await asyncio.sleep(0)
    return url


class AsyncService:
    """Service with async methods."""

    async def process(self, data):
        await asyncio.sleep(0)
        return data

    async def validate(self, item):
        return item is not None

    def sync_helper(self):
        return True
