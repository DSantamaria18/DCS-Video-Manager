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


# ── _video_length_category ────────────────────────────────────────────────────

@pytest.mark.parametrize("seconds,expected", [
    (0,    "short"),
    (300,  "short"),
    (599,  "short"),
    (600,  "medium"),
    (900,  "medium"),
    (1799, "medium"),
    (1800, "long"),
    (3600, "long"),
])
def test_video_length_category(seconds, expected):
    assert dcs_meta._video_length_category(seconds) == expected


# ── build_prompt length-adapted description rules ─────────────────────────────

def test_build_prompt_short_video_uses_quick_breakdown():
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []},
                                   duration_seconds=300)
    assert "quick tactical breakdown" in prompt
    assert "SHORT VIDEO" in prompt


def test_build_prompt_medium_video_uses_full_training():
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []},
                                   duration_seconds=900)
    assert "full training video" in prompt
    assert "MEDIUM VIDEO" in prompt


def test_build_prompt_long_video_uses_complete_debrief():
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []},
                                   duration_seconds=2400)
    assert "complete mission debrief" in prompt
    assert "LONG VIDEO" in prompt


def test_build_prompt_short_video_chapters_rule_says_do_not_include():
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []},
                                   duration_seconds=300)
    assert "Do NOT include chapters" in prompt


def test_build_prompt_long_video_chapters_rule_says_mandatory():
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []},
                                   duration_seconds=2400)
    assert "ALWAYS include chapters" in prompt or "mandatory" in prompt.lower()


def test_build_prompt_no_duration_defaults_to_medium():
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []})
    assert "MEDIUM VIDEO" in prompt or "full training video" in prompt


def test_build_prompt_duration_hint_shows_minutes():
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []},
                                   duration_seconds=900)
    assert "15 min" in prompt


def test_build_prompt_squadron_short_uses_spanish_template():
    prompt = dcs_meta.build_prompt("e111 op", {}, is_squadron=True, memory={"videos": []},
                                   duration_seconds=300)
    assert "quick tactical breakdown" in prompt
    assert "Aeronave" in prompt


def test_build_prompt_squadron_long_uses_spanish_debrief():
    prompt = dcs_meta.build_prompt("e111 op", {}, is_squadron=True, memory={"videos": []},
                                   duration_seconds=2400)
    assert "complete mission debrief" in prompt
    assert "OBLIGATORIO" in prompt


# ── _detect_series ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ctx,expected_campaign,expected_ep", [
    ("A-10C II Outpost Campaign - Mission 3",  "A-10C II Outpost Campaign", 3),
    ("Raven One Campaign - Mission 7",          "Raven One Campaign",        7),
    ("Strike Fighters - Episode 2",             "Strike Fighters",           2),
    ("Op Trueno - Ep. 4",                       "Op Trueno",                 4),
    ("Desert Storm - Part 5",                   "Desert Storm",              5),
])
def test_detect_series_extracts_campaign_and_episode(ctx, expected_campaign, expected_ep):
    result = dcs_meta._detect_series(ctx, {"videos": []})
    assert result is not None
    assert result["campaign"] == expected_campaign
    assert result["episode"] == expected_ep


def test_detect_series_no_episode_marker_returns_none():
    assert dcs_meta._detect_series("F/A-18C Night Strike", {"videos": []}) is None


def test_detect_series_empty_context_returns_none():
    assert dcs_meta._detect_series("", {"videos": []}) is None


def test_detect_series_finds_prev_episodes_in_history():
    history = {"videos": [
        {"title": "DCS | F-18 | Raven One Campaign - Mission 1", "date": "2026-01-01",
         "video_id": ""},
        {"title": "DCS | F-18 | Raven One Campaign - Mission 2", "date": "2026-01-08",
         "video_id": ""},
    ]}
    result = dcs_meta._detect_series("Raven One Campaign - Mission 3", history)
    assert result is not None
    assert len(result["prev_episodes"]) == 2


def test_detect_series_includes_youtube_url_when_video_id_set():
    history = {"videos": [
        {"title": "DCS | Raven One Campaign - Mission 1", "date": "2026-01-01",
         "video_id": "abc123"},
    ]}
    result = dcs_meta._detect_series("Raven One Campaign - Mission 2", history)
    assert result["prev_episodes"][0]["url"] == "https://youtu.be/abc123"


def test_detect_series_no_url_when_video_id_empty():
    history = {"videos": [
        {"title": "DCS | Raven One Campaign - Mission 1", "date": "2026-01-01",
         "video_id": ""},
    ]}
    result = dcs_meta._detect_series("Raven One Campaign - Mission 2", history)
    assert "url" not in result["prev_episodes"][0]


def test_detect_series_caps_prev_episodes_at_3():
    videos = [
        {"title": f"DCS | Raven One Campaign - Mission {i}", "date": "2026-01-01",
         "video_id": ""}
        for i in range(1, 10)
    ]
    result = dcs_meta._detect_series("Raven One Campaign - Mission 10", {"videos": videos})
    assert len(result["prev_episodes"]) == 3


# ── _aircraft_series_suggestions ─────────────────────────────────────────────

def test_aircraft_series_suggestions_counts_correctly():
    videos = [{"aircraft": "F/A-18C Hornet"}] * 5 + [{"aircraft": "A-10C Warthog"}] * 2
    result = dcs_meta._aircraft_series_suggestions({"videos": videos})
    assert ("F/A-18C Hornet", 5) in result
    assert all(a != "A-10C Warthog" for a, _ in result)


def test_aircraft_series_suggestions_excludes_below_threshold():
    videos = [{"aircraft": "F-16C Viper"}] * 2
    assert dcs_meta._aircraft_series_suggestions({"videos": videos}) == []


def test_aircraft_series_suggestions_empty_history():
    assert dcs_meta._aircraft_series_suggestions({"videos": []}) == []


def test_aircraft_series_suggestions_ignores_empty_aircraft():
    videos = [{"aircraft": ""}, {"aircraft": "F/A-18C Hornet"}] * 5
    result = dcs_meta._aircraft_series_suggestions({"videos": videos})
    assert all(a for a, _ in result)


# ── build_prompt with series_context ─────────────────────────────────────────

def test_build_prompt_includes_series_block_when_context_provided():
    sc = {"campaign": "Raven One", "episode": 7, "prev_episodes": []}
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []},
                                   series_context=sc)
    assert "SERIES CONTEXT" in prompt
    assert "Raven One" in prompt
    assert "Episode: 7" in prompt


def test_build_prompt_no_series_block_when_none():
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []})
    assert "SERIES CONTEXT" not in prompt


def test_build_prompt_series_includes_prev_episode_url():
    sc = {
        "campaign": "Raven One", "episode": 3,
        "prev_episodes": [{"title": "Ep1", "date": "2026-01-01",
                           "url": "https://youtu.be/abc"}],
    }
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []},
                                   series_context=sc)
    assert "https://youtu.be/abc" in prompt


def test_build_prompt_aircraft_suggestions_block_included():
    prompt = dcs_meta.build_prompt("", {}, is_squadron=False, memory={"videos": []},
                                   aircraft_suggestions=[("F/A-18C Hornet", 10)])
    assert "AIRCRAFT PLAYLIST SUGGESTIONS" in prompt
    assert "F/A-18C Hornet" in prompt


# ── update_memory stores campaign + video_id ──────────────────────────────────

def test_update_memory_stores_campaign_field(tmp_path, monkeypatch):
    monkeypatch.setattr(dcs_meta, "MEMORY_PATH", tmp_path / "history.json")
    meta = {**SAMPLE_META, "campaign": "Raven One"}
    dcs_meta.update_memory(meta, Path("video.mp4"))
    saved = dcs_meta.load_memory()
    assert saved["videos"][0]["campaign"] == "Raven One"


def test_update_memory_stores_empty_video_id(tmp_path, monkeypatch):
    monkeypatch.setattr(dcs_meta, "MEMORY_PATH", tmp_path / "history.json")
    dcs_meta.update_memory(SAMPLE_META, Path("video.mp4"))
    saved = dcs_meta.load_memory()
    assert saved["videos"][0]["video_id"] == ""


# ── update_memory_video_id ────────────────────────────────────────────────────

def test_update_memory_video_id_patches_correct_entry(tmp_path, monkeypatch):
    history_file = tmp_path / "history.json"
    history_file.write_text(json.dumps({"videos": [
        {"filename": "video.mp4", "title": "T1", "video_id": ""},
    ]}))
    monkeypatch.setattr(dcs_meta, "MEMORY_PATH", history_file)
    dcs_meta.update_memory_video_id("video.mp4", "xyz789")
    saved = dcs_meta.load_memory()
    assert saved["videos"][0]["video_id"] == "xyz789"


def test_update_memory_video_id_no_match_is_safe(tmp_path, monkeypatch):
    history_file = tmp_path / "history.json"
    history_file.write_text(json.dumps({"videos": [
        {"filename": "other.mp4", "title": "T1", "video_id": ""},
    ]}))
    monkeypatch.setattr(dcs_meta, "MEMORY_PATH", history_file)
    dcs_meta.update_memory_video_id("nonexistent.mp4", "xyz")
    saved = dcs_meta.load_memory()
    assert saved["videos"][0]["video_id"] == ""


# ── _build_description_rules with custom templates ────────────────────────────

def test_build_description_rules_returns_hardcoded_when_no_config():
    result = dcs_meta._build_description_rules(False, "medium")
    assert "full training video" in result


def test_build_description_rules_uses_custom_template_from_config():
    cfg = {"description_templates": {"en_medium": "MY CUSTOM TEMPLATE"}}
    result = dcs_meta._build_description_rules(False, "medium", cfg)
    assert result == "MY CUSTOM TEMPLATE"


def test_build_description_rules_falls_back_when_custom_empty():
    cfg = {"description_templates": {"en_medium": ""}}
    result = dcs_meta._build_description_rules(False, "medium", cfg)
    assert "full training video" in result


def test_build_description_rules_custom_key_mapping():
    """es_long should be used for is_squadron=True, category='long'."""
    cfg = {"description_templates": {"es_long": "CUSTOM LONG SPANISH"}}
    result = dcs_meta._build_description_rules(True, "long", cfg)
    assert result == "CUSTOM LONG SPANISH"


@pytest.mark.parametrize("is_sq,cat,expected_key", [
    (False, "short",  "en_short"),
    (False, "medium", "en_medium"),
    (False, "long",   "en_long"),
    (True,  "short",  "es_short"),
    (True,  "medium", "es_medium"),
    (True,  "long",   "es_long"),
])
def test_build_description_rules_correct_key_for_all_combinations(is_sq, cat, expected_key):
    sentinel = f"SENTINEL_{expected_key}"
    cfg = {"description_templates": {expected_key: sentinel}}
    result = dcs_meta._build_description_rules(is_sq, cat, cfg)
    assert result == sentinel


def test_valid_template_keys_covers_all_combinations():
    assert dcs_meta.VALID_TEMPLATE_KEYS == {
        "en_short", "en_medium", "en_long",
        "es_short", "es_medium", "es_long",
    }


def test_update_memory_video_id_patches_most_recent_matching(tmp_path, monkeypatch):
    history_file = tmp_path / "history.json"
    history_file.write_text(json.dumps({"videos": [
        {"filename": "video.mp4", "title": "old", "video_id": ""},
        {"filename": "video.mp4", "title": "new", "video_id": ""},
    ]}))
    monkeypatch.setattr(dcs_meta, "MEMORY_PATH", history_file)
    dcs_meta.update_memory_video_id("video.mp4", "newid")
    saved = dcs_meta.load_memory()
    assert saved["videos"][1]["video_id"] == "newid"
    assert saved["videos"][0]["video_id"] == ""
