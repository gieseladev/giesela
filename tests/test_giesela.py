"""Test Giesela."""

import os

import pytest


@pytest.mark.asyncio
async def test_start():
    """Test whether Giesela starts properly."""
    from giesela import Giesela
    bot = Giesela()
    token = os.getenv("token")

    await bot.login(token)
    await bot.http.close()
    await bot.close()
