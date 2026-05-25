import json
from pathlib import Path
import pytest
import dcs_meta


# ── is_squadron_video ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("ctx,expected", [
    ("Escuadrón 111 - Operación Trueno - SEAD support", True),
    ("e111 morning strike over Caucasus",               True),
    ("escuadron patrol mission",                        True),
    ("multiplayer session with friends",                True),
    ("squad training flight",                           True),
    ("A-10C II Outpost Campaign - Mission 3",           False),
    ("F/A-18C Night Strike Raven One Campaign",         False),
    ("",                                                False),
])
def test_is_squadron_video(ctx, expected):
    assert dcs_meta.is_squadron_video(ctx) == expected


# ── _recover_json ─────────────────────────────────────────────────────────────

def test_recover_json_clean():
    data = {"title": "DCS World | A-10C", "language": "en"}
    assert dcs_meta._recover_json(json.dumps(data)) == data


def test_recover_json_truncated_missing_brace():
    raw = '{"title": "DCS World", "language": "en"'
    result = dcs_meta._recover_json(raw)
    assert result.get("title") == "DCS World"


def test_recover_json_truncated_missing_bracket():
    raw = '{"tags": ["dcs", "hornet"'
    result = dcs_meta._recover_json(raw)
    assert isinstance(result.get("tags"), list)


def test_recover_json_garbage_returns_empty():
    assert dcs_meta._recover_json("not json at all !!!") == {}


def test_recover_json_truncated_mid_string_does_not_raise():
    result = dcs_meta._recover_json('{"title": "DCS Wor')
    assert isinstance(result, dict)


def test_recover_json_trailing_comma():
    raw = '{"title": "DCS", "tags": ["dcs",}'
    result = dcs_meta._recover_json(raw)
    assert isinstance(result, dict)


# ── format_description ────────────────────────────────────────────────────────

BASE_CONFIG = {
    "default_links": {
        "dcs_a10c_playlist": "https://youtube.com/playlist?list=A10",
        "dcs_huey_playlist": "https://youtube.com/playlist?list=UH1",
        "dcs_f18_playlist":  "https://youtube.com/playlist?list=F18",
        "twitter":           "https://twitter.com/thecylonpilot",
        "twitch":            "https://www.twitch.tv/thecylonpilot",
        "buymeacoffee":      "https://www.buymeacoffee.com/pilotcylon",
        "escuadron111":      "https://www.escuadron111.eu/",
    }
}


@pytest.mark.parametrize("aircraft,expected_url", [
    ("F/A-18C Hornet",  "https://youtube.com/playlist?list=F18"),
    ("hornet vfa-34",   "https://youtube.com/playlist?list=F18"),
    ("f18",             "https://youtube.com/playlist?list=F18"),
    ("A-10C Warthog",   "https://youtube.com/playlist?list=A10"),
    ("a-10c ii",        "https://youtube.com/playlist?list=A10"),
    ("UH-1H Huey",      "https://youtube.com/playlist?list=UH1"),
    ("uh-1h",           "https://youtube.com/playlist?list=UH1"),
])
def test_format_description_playlist_by_aircraft(aircraft, expected_url):
    meta = {"description": "[relevant playlists]", "aircraft": aircraft}
    result = dcs_meta.format_description(meta, BASE_CONFIG)
    assert expected_url in result


def test_format_description_unknown_aircraft_includes_both():
    meta = {"description": "[relevant playlists]", "aircraft": "F-16C Viper"}
    result = dcs_meta.format_description(meta, BASE_CONFIG)
    assert "https://youtube.com/playlist?list=F18" in result
    assert "https://youtube.com/playlist?list=A10" in result


def test_format_description_spanish_placeholder_replaced():
    meta = {"description": "[playlists relevantes]", "aircraft": "F/A-18C Hornet"}
    result = dcs_meta.format_description(meta, BASE_CONFIG)
    assert "https://youtube.com/playlist?list=F18" in result
    assert "[playlists relevantes]" not in result


def test_format_description_english_placeholder_replaced():
    meta = {"description": "[relevant playlists]", "aircraft": "A-10C"}
    result = dcs_meta.format_description(meta, BASE_CONFIG)
    assert "[relevant playlists]" not in result


# ── update_memory ─────────────────────────────────────────────────────────────

SAMPLE_META = {
    "title": "DCS | A-10C | CAS Mission",
    "language": "en",
    "aircraft": "A-10C",
    "map": "Caucasus",
    "mission_type": "CAS",
}


def test_update_memory_adds_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(dcs_meta, "MEMORY_PATH", tmp_path / "history.json")
    dcs_meta.update_memory(SAMPLE_META, Path("video.mp4"))
    saved = dcs_meta.load_memory()
    assert len(saved["videos"]) == 1
    assert saved["videos"][0]["title"] == SAMPLE_META["title"]
    assert saved["videos"][0]["aircraft"] == "A-10C"


def test_update_memory_caps_at_50(tmp_path, monkeypatch):
    history_file = tmp_path / "history.json"
    history_file.write_text(json.dumps({"videos": [{"title": f"v{i}"} for i in range(55)]}))
    monkeypatch.setattr(dcs_meta, "MEMORY_PATH", history_file)
    dcs_meta.update_memory(SAMPLE_META, Path("video.mp4"))
    saved = dcs_meta.load_memory()
    assert len(saved["videos"]) == 50


def test_update_memory_persists_to_disk(tmp_path, monkeypatch):
    history_file = tmp_path / "history.json"
    monkeypatch.setattr(dcs_meta, "MEMORY_PATH", history_file)
    dcs_meta.update_memory(SAMPLE_META, Path("video.mp4"))
    saved = json.loads(history_file.read_text())
    assert saved["videos"][0]["title"] == SAMPLE_META["title"]


# ── build_prompt ──────────────────────────────────────────────────────────────

def test_build_prompt_squadron_uses_spanish():
    prompt = dcs_meta.build_prompt("e111 mission", {}, is_squadron=True, memory={"videos": []})
    assert "Spanish" in prompt


def test_build_prompt_squadron_mentions_e111():
    prompt = dcs_meta.build_prompt("e111 mission", {}, is_squadron=True, memory={"videos": []})
    assert "Escuadrón 111" in prompt


def test_build_prompt_solo_uses_english():
    prompt = dcs_meta.build_prompt("A-10C campaign", {}, is_squadron=False, memory={"videos": []})
    assert "English" in prompt


def test_build_prompt_includes_user_context():
    ctx = "Raven One Campaign - Mission 7"
    prompt = dcs_meta.build_prompt(ctx, {}, is_squadron=False, memory={"videos": []})
    assert ctx in prompt


def test_build_prompt_includes_memory_when_present():
    memory = {"videos": [{"date": "2026-01-01", "title": "DCS | Hornet strike", "language": "en"}]}
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory=memory)
    assert "DCS | Hornet strike" in prompt


def test_build_prompt_no_memory_block_when_empty():
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []})
    assert "RECENT VIDEOS" not in prompt


def test_build_prompt_returns_valid_json_schema_hint():
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []})
    assert '"title"' in prompt
    assert '"tags"' in prompt
    assert '"language"' in prompt


# ── MODULE_PROFILES / module guide ────────────────────────────────────────────

def test_module_profiles_contains_all_expected_modules():
    expected = {"F/A-18C Hornet", "F-16C Viper", "F-14 Tomcat", "UH-1H Huey",
                "A-10C Warthog", "C-130J Hercules", "AH-64D Apache"}
    assert expected == set(dcs_meta.MODULE_PROFILES.keys())


def test_module_profiles_each_has_required_keys():
    for module, data in dcs_meta.MODULE_PROFILES.items():
        for key in ("cockpit", "missions", "weapons", "tags"):
            assert key in data, f"{module} missing '{key}'"
        assert isinstance(data["tags"], list)
        assert len(data["tags"]) >= 2


@pytest.mark.parametrize("module_name", [
    "F-14 Tomcat", "UH-1H Huey", "A-10C Warthog", "C-130J Hercules", "AH-64D Apache",
])
def test_build_prompt_includes_module_in_guide(module_name):
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []})
    assert module_name in prompt


def test_build_prompt_includes_module_identification_guide_header():
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []})
    assert "MODULE IDENTIFICATION GUIDE" in prompt


def test_build_prompt_guide_includes_cockpit_field():
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []})
    assert "cockpit=" in prompt


def test_build_prompt_channel_identity_includes_c130j_and_apache():
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []})
    assert "C-130J" in prompt
    assert "AH-64D Apache" in prompt


# ── format_description — new aircraft fall through to generic ─────────────────

@pytest.mark.parametrize("aircraft", ["F-14B Tomcat", "AH-64D Apache", "C-130J Super Hercules"])
def test_format_description_new_aircraft_falls_through_to_generic(aircraft):
    meta = {"description": "[relevant playlists]", "aircraft": aircraft}
    result = dcs_meta.format_description(meta, BASE_CONFIG)
    assert "https://youtube.com/playlist?list=F18" in result
    assert "https://youtube.com/playlist?list=A10" in result
