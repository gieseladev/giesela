"""Test Giesela."""

import os
import discord

import pytest


@pytest.mark.asyncio
async def test_start():
    """Test whether Giesela starts properly."""
    from musicbot import bot
    bot = discord.Client()
    token = os.getenv("discord_token")

    await bot.login(token)
    await bot.http.close()
    await bot.aiosession.close()
