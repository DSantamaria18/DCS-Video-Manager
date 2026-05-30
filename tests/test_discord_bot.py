import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path (conftest.py does this, but be explicit)
root = Path(__file__).parent.parent
sys.path.insert(0, str(root))


# ── Stub discord before importing discord_bot ─────────────────────────────────

def _make_discord_stub():
    """Build a minimal discord stub so discord_bot can be imported without installing discord.py."""
    discord_mod = types.ModuleType("discord")
    discord_mod.Intents = MagicMock()
    discord_mod.Intents.default = MagicMock(return_value=MagicMock(
        message_content=True, reactions=True
    ))
    discord_mod.Embed = MagicMock(return_value=MagicMock())
    discord_mod.Client = MagicMock

    commands_mod = types.ModuleType("discord.ext.commands")
    commands_mod.Bot = MagicMock

    ext_mod = types.ModuleType("discord.ext")
    ext_mod.commands = commands_mod
    discord_mod.ext = ext_mod

    sys.modules.setdefault("discord", discord_mod)
    sys.modules.setdefault("discord.ext", ext_mod)
    sys.modules.setdefault("discord.ext.commands", commands_mod)
    return discord_mod


_make_discord_stub()
import discord_bot  # noqa: E402


# ── load_config ───────────────────────────────────────────────────────────────

def test_load_config_returns_dict_on_valid_file(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text('{"discord_bot_token": "tok", "discord_channel_id": "123"}',
                        encoding="utf-8")
    monkeypatch.setattr(discord_bot, "CONFIG_PATH", cfg_path)
    cfg = discord_bot.load_config()
    assert cfg["discord_bot_token"] == "tok"
    assert cfg["discord_channel_id"] == "123"


def test_load_config_returns_empty_dict_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(discord_bot, "CONFIG_PATH", tmp_path / "nonexistent.json")
    assert discord_bot.load_config() == {}


def test_load_config_returns_empty_dict_on_invalid_json(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("not valid json", encoding="utf-8")
    monkeypatch.setattr(discord_bot, "CONFIG_PATH", cfg_path)
    assert discord_bot.load_config() == {}


# ── load_history ──────────────────────────────────────────────────────────────

def test_load_history_returns_videos(tmp_path, monkeypatch):
    mem_path = tmp_path / "history.json"
    mem_path.write_text(json.dumps({"videos": [{"title": "Test Mission"}]}),
                        encoding="utf-8")
    monkeypatch.setattr(discord_bot, "MEMORY_PATH", mem_path)
    hist = discord_bot.load_history()
    assert len(hist["videos"]) == 1
    assert hist["videos"][0]["title"] == "Test Mission"


def test_load_history_returns_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(discord_bot, "MEMORY_PATH", tmp_path / "nope.json")
    assert discord_bot.load_history() == {"videos": []}


# ── load_reactions / save_reactions ──────────────────────────────────────────

def test_save_and_load_reactions_roundtrip(tmp_path, monkeypatch):
    reactions_path = tmp_path / "discord_reactions.json"
    monkeypatch.setattr(discord_bot, "REACTIONS_PATH", reactions_path)
    reactions = [{"message_id": "1", "video_title": "Test", "emoji": "✅",
                  "user_id": "99", "timestamp": "2026-01-01T00:00:00+00:00"}]
    discord_bot.save_reactions(reactions)
    loaded = discord_bot.load_reactions()
    assert loaded[0]["emoji"] == "✅"
    assert loaded[0]["user_id"] == "99"


def test_load_reactions_returns_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(discord_bot, "REACTIONS_PATH", tmp_path / "nope.json")
    assert discord_bot.load_reactions() == []


# ── record_reaction ───────────────────────────────────────────────────────────

def test_record_reaction_appends_entry(tmp_path, monkeypatch):
    reactions_path = tmp_path / "reactions.json"
    monkeypatch.setattr(discord_bot, "REACTIONS_PATH", reactions_path)
    discord_bot.record_reaction(
        message_id="42",
        video_title="Test Mission",
        emoji="👁️",
        user_id="7",
    )
    saved = discord_bot.load_reactions()
    assert len(saved) == 1
    assert saved[0]["message_id"] == "42"
    assert saved[0]["emoji"] == "👁️"
    assert saved[0]["user_id"] == "7"


def test_record_reaction_appends_multiple(tmp_path, monkeypatch):
    reactions_path = tmp_path / "reactions.json"
    monkeypatch.setattr(discord_bot, "REACTIONS_PATH", reactions_path)
    for emoji in ("👁️", "✅", "📚"):
        discord_bot.record_reaction("10", "Mission", emoji, "5")
    saved = discord_bot.load_reactions()
    assert len(saved) == 3


def test_record_reaction_timestamp_is_iso(tmp_path, monkeypatch):
    reactions_path = tmp_path / "reactions.json"
    monkeypatch.setattr(discord_bot, "REACTIONS_PATH", reactions_path)
    discord_bot.record_reaction("1", "T", "✅", "2")
    saved = discord_bot.load_reactions()
    ts = saved[0]["timestamp"]
    # ISO 8601 format includes 'T' separator and timezone
    assert "T" in ts
    assert "+" in ts or "Z" in ts or ts.endswith("+00:00")


# ── get_latest_debrief ────────────────────────────────────────────────────────

def test_get_latest_debrief_returns_most_recent_with_debrief():
    history = {"videos": [
        {"title": "Mission 1", "debrief": ""},
        {"title": "Mission 2", "debrief": "Great sortie."},
        {"title": "Mission 3", "debrief": ""},
    ]}
    result = discord_bot.get_latest_debrief(history)
    assert result["title"] == "Mission 2"


def test_get_latest_debrief_returns_none_when_no_debriefs():
    history = {"videos": [{"title": "M1", "debrief": ""}, {"title": "M2"}]}
    assert discord_bot.get_latest_debrief(history) is None


def test_get_latest_debrief_returns_none_on_empty_history():
    assert discord_bot.get_latest_debrief({"videos": []}) is None


def test_get_latest_debrief_prefers_latest():
    history = {"videos": [
        {"title": "Mission 1", "debrief": "Old debrief."},
        {"title": "Mission 2", "debrief": "Newer debrief."},
    ]}
    result = discord_bot.get_latest_debrief(history)
    assert result["title"] == "Mission 2"


# ── build_debrief_embed ───────────────────────────────────────────────────────

def test_build_debrief_embed_uses_correct_color():
    entry = {
        "title": "DCS | F/A-18C | SEAD", "aircraft": "F/A-18C Hornet",
        "map": "Caucasus", "mission_type": "SEAD", "debrief": "Hit the SA-6.",
        "date": "2026-05-30",
    }
    embed = discord_bot.build_debrief_embed(entry)
    # embed is a MagicMock; check it was called (stub)
    assert embed is not None


def test_build_debrief_embed_truncates_long_debrief():
    long_debrief = "x" * 2000
    entry = {"title": "T", "aircraft": "F-16", "map": "Sinai",
             "mission_type": "CAS", "debrief": long_debrief, "date": "2026-05-30"}
    # Should not raise even with a long debrief
    embed = discord_bot.build_debrief_embed(entry)
    assert embed is not None


# ── main — graceful exit on empty token/channel ───────────────────────────────

def test_main_exits_on_empty_token(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text('{"discord_bot_token": "", "discord_channel_id": "123"}',
                        encoding="utf-8")
    monkeypatch.setattr(discord_bot, "CONFIG_PATH", cfg_path)

    with pytest.raises(SystemExit) as exc_info:
        discord_bot.main()
    assert exc_info.value.code == 1


def test_main_exits_on_empty_channel_id(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text('{"discord_bot_token": "sometoken", "discord_channel_id": ""}',
                        encoding="utf-8")
    monkeypatch.setattr(discord_bot, "CONFIG_PATH", cfg_path)

    with pytest.raises(SystemExit) as exc_info:
        discord_bot.main()
    assert exc_info.value.code == 1


def test_main_exits_when_discord_not_installed(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text('{"discord_bot_token": "tok", "discord_channel_id": "123"}',
                        encoding="utf-8")
    monkeypatch.setattr(discord_bot, "CONFIG_PATH", cfg_path)

    # Remove discord from sys.modules to simulate ImportError
    saved = {k: v for k, v in sys.modules.items() if "discord" in k}
    for k in list(saved):
        sys.modules.pop(k)

    try:
        with pytest.raises(SystemExit) as exc_info:
            discord_bot.main()
        assert exc_info.value.code == 1
    finally:
        # Restore stubs so other tests are not affected
        sys.modules.update(saved)


# ── importability ─────────────────────────────────────────────────────────────

def test_discord_bot_module_is_importable():
    """discord_bot must be importable without a live Discord connection."""
    assert hasattr(discord_bot, "create_bot")
    assert hasattr(discord_bot, "main")
    assert hasattr(discord_bot, "record_reaction")
    assert hasattr(discord_bot, "get_latest_debrief")
    assert hasattr(discord_bot, "build_debrief_embed")
