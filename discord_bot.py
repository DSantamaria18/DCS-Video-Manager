"""Standalone Discord bot for E111 squadron engagement tracking.

Run with: python discord_bot.py
Requires: discord.py (pip install discord.py)
Config keys in config/config.json: discord_bot_token, discord_channel_id
"""

import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config" / "config.json"
# Discord secrets (bot token, channel id) live in a separate gitignored file (SEC-01).
SECRETS_PATH = Path(__file__).parent / "config" / "secrets.json"
MEMORY_PATH = Path(__file__).parent / "memory" / "history.json"
REACTIONS_PATH = Path(__file__).parent / "memory" / "discord_reactions.json"

_reactions_lock = threading.Lock()


def load_config() -> dict:
    """Load config.json merged with secrets.json. Returns empty dict on failure."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        cfg = {}
    try:
        with open(SECRETS_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, json.JSONDecodeError):
        pass
    return cfg


def load_history() -> dict:
    """Load memory/history.json. Returns {"videos": []} if absent or unreadable."""
    try:
        with open(MEMORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"videos": []}


def load_reactions() -> list:
    """Load discord_reactions.json. Returns [] if absent or unreadable."""
    try:
        with open(REACTIONS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def save_reactions(reactions: list) -> None:
    """Persist reactions list to discord_reactions.json in a thread-safe manner."""
    REACTIONS_PATH.parent.mkdir(exist_ok=True)
    with open(REACTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(reactions, f, indent=2, ensure_ascii=False)


def record_reaction(message_id: str, video_title: str, emoji: str, user_id: str) -> None:
    """Append a reaction event to discord_reactions.json. Thread-safe."""
    entry = {
        "message_id": str(message_id),
        "video_title": video_title,
        "emoji": emoji,
        "user_id": str(user_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with _reactions_lock:
        reactions = load_reactions()
        reactions.append(entry)
        save_reactions(reactions)


def get_latest_debrief(history: dict) -> dict | None:
    """Return the most recent history entry that has a non-empty debrief field, or None."""
    for entry in reversed(history.get("videos", [])):
        if entry.get("debrief"):
            return entry
    return None


def build_debrief_embed(entry: dict):
    """Build a discord.Embed from a history entry for the !debrief command.

    Returns the embed object. Caller must have already imported discord.
    """
    import discord

    title = entry.get("title", "Unknown Mission")
    aircraft = entry.get("aircraft", "?")
    map_name = entry.get("map", "?")
    mission_type = entry.get("mission_type", "?")
    debrief_text = (entry.get("debrief") or "").strip()
    if not debrief_text:
        debrief_text = f"Mission completed with {aircraft} over {map_name}."

    embed = discord.Embed(
        title=title,
        color=0x336699,
    )
    embed.add_field(name="Aircraft", value=aircraft, inline=True)
    embed.add_field(name="Map", value=map_name, inline=True)
    embed.add_field(name="Mission type", value=mission_type, inline=True)
    embed.add_field(name="Debrief", value=debrief_text[:1024], inline=False)
    embed.set_footer(text=f"E111 Squadron | {entry.get('date', '')}")
    return embed


def create_bot():
    """Instantiate and configure the discord.ext.commands.Bot with all command and event handlers.

    Returns the configured Bot instance ready for bot.run(token).
    """
    import discord
    from discord.ext import commands

    intents = discord.Intents.default()
    intents.message_content = True
    intents.reactions = True

    bot = commands.Bot(command_prefix="!", intents=intents)
    bot._posted_message_ids: dict[int, str] = {}

    @bot.event
    async def on_ready():
        print(f"[discord_bot] Logged in as {bot.user} (id={bot.user.id})")

    @bot.command(name="debrief")
    async def cmd_debrief(ctx):
        """Post the most recent mission debrief as an embed with reaction buttons."""
        history = load_history()
        entry = get_latest_debrief(history)

        if entry is None:
            fallback = (history.get("videos") or [{}])[-1]
            entry = fallback or {}

        if not entry:
            await ctx.send("No mission history found.")
            return

        embed = build_debrief_embed(entry)
        msg = await ctx.send(embed=embed)

        bot._posted_message_ids[msg.id] = entry.get("title", "")

        for emoji in ("👁️", "✅", "📚"):
            await msg.add_reaction(emoji)

    @bot.command(name="stats")
    async def cmd_stats(ctx):
        """Post a summary of the last 5 videos from history."""
        history = load_history()
        videos = history.get("videos", [])[-5:]
        if not videos:
            await ctx.send("No videos in history yet.")
            return
        lines = ["**Last 5 missions:**"]
        for v in reversed(videos):
            lines.append(
                f"• {v.get('title', 'Unknown')} — {v.get('aircraft', '?')} | {v.get('map', '?')}"
            )
        await ctx.send("\n".join(lines))

    @bot.event
    async def on_raw_reaction_add(payload):
        """Track reactions added to bot-posted messages in discord_reactions.json."""
        if payload.user_id == bot.user.id:
            return
        video_title = bot._posted_message_ids.get(payload.message_id, "")
        record_reaction(
            message_id=payload.message_id,
            video_title=video_title,
            emoji=str(payload.emoji),
            user_id=payload.user_id,
        )

    return bot


def main():
    """Entry point: load config, validate bot token and channel, start the bot."""
    cfg = load_config()
    token = cfg.get("discord_bot_token", "").strip()
    channel_id = cfg.get("discord_channel_id", "").strip()

    if not token:
        print(
            "[discord_bot] ERROR: discord_bot_token is empty in config/config.json.\n"
            "Add your bot token from https://discord.com/developers/applications"
        )
        sys.exit(1)

    if not channel_id:
        print(
            "[discord_bot] ERROR: discord_channel_id is empty in config/config.json.\n"
            "Add the target channel ID (right-click channel → Copy Channel ID)."
        )
        sys.exit(1)

    import importlib.util
    if importlib.util.find_spec("discord") is None:
        print(
            "[discord_bot] ERROR: discord.py is not installed.\n"
            "Run: pip install discord.py>=2.3.0"
        )
        sys.exit(1)

    bot = create_bot()
    print("[discord_bot] Starting bot… (Ctrl+C to stop)")
    bot.run(token)


if __name__ == "__main__":
    main()
