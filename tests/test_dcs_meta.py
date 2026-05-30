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


# ── check_description_seo ─────────────────────────────────────────────────────

SEO_CONFIG = {
    "default_links": {
        "dcs_f18_playlist": "https://youtube.com/playlist?list=F18",
        "dcs_a10c_playlist": "https://youtube.com/playlist?list=A10",
    }
}

GOOD_DESC = (
    "https://youtube.com/playlist?list=F18\n"
    "DCS World | F/A-18C Hornet CAS mission over Caucasus. "
    "Full strike package with JDAMs and AGM-65 Mavericks. "
    "Enemy convoy destroyed in a coordinated CAS run.\n\n"
    "0:00 Intro\n1:30 Takeoff\n5:00 Target area\n12:00 RTB\n"
    "Timestamps included for navigation. Thanks for watching!"
)


def _check(description="", title="", aircraft="", mission_type="", chapters=None, config=None):
    return dcs_meta.check_description_seo(
        description=description,
        title=title,
        tags=[],
        aircraft=aircraft,
        mission_type=mission_type,
        chapters=chapters or [],
        config=config or SEO_CONFIG,
    )


def codes(issues):
    return {i["code"] for i in issues}


def test_seo_clean_description_no_issues():
    issues = _check(description=GOOD_DESC, title="DCS World | F/A-18C CAS",
                    aircraft="F/A-18C Hornet", mission_type="CAS",
                    chapters=[{"time": "0:00", "label": "Intro"}])
    assert issues == []


def test_seo_short_description_flagged():
    issues = _check(description="Short desc.", title="DCS World test")
    assert "SHORT_DESCRIPTION" in codes(issues)


def test_seo_exactly_300_chars_not_flagged():
    desc = "DCS World " + "x" * 290
    issues = _check(description=desc, title="DCS World test")
    assert "SHORT_DESCRIPTION" not in codes(issues)


def test_seo_missing_dcs_world_in_both():
    desc = "F/A-18C Hornet CAS mission. " + "x" * 280
    issues = _check(description=desc, title="CAS Strike")
    assert "MISSING_DCS_WORLD" in codes(issues)


def test_seo_dcs_world_in_title_clears_flag():
    desc = "F/A-18C Hornet CAS mission. " + "x" * 280
    issues = _check(description=desc, title="DCS World CAS Strike")
    assert "MISSING_DCS_WORLD" not in codes(issues)


def test_seo_missing_aircraft_flagged():
    desc = "DCS World CAS mission over Caucasus. " + "x" * 270
    issues = _check(description=desc, title="DCS World", aircraft="F/A-18C Hornet")
    assert "MISSING_AIRCRAFT" in codes(issues)


def test_seo_aircraft_present_not_flagged():
    desc = "DCS World F/A-18C Hornet CAS. " + "x" * 270
    issues = _check(description=desc, title="DCS World", aircraft="F/A-18C Hornet")
    assert "MISSING_AIRCRAFT" not in codes(issues)


def test_seo_missing_mission_type_flagged():
    desc = "DCS World F/A-18C Hornet mission. " + "x" * 270
    issues = _check(description=desc, title="DCS World", mission_type="SEAD")
    assert "MISSING_MISSION_TYPE" in codes(issues)


def test_seo_no_chapters_in_desc_when_chapters_exist():
    desc = "DCS World F/A-18C Hornet CAS. " + "x" * 270
    issues = _check(description=desc, title="DCS World",
                    chapters=[{"time": "0:00", "label": "Intro"}])
    assert "NO_CHAPTERS_IN_DESC" in codes(issues)


def test_seo_chapters_too_late_flagged():
    prefix = "x" * 501
    desc = f"DCS World F/A-18C Hornet CAS. {prefix} 0:00 Intro"
    issues = _check(description=desc, title="DCS World",
                    chapters=[{"time": "0:00", "label": "Intro"}])
    assert "CHAPTERS_TOO_LATE" in codes(issues)


def test_seo_chapters_near_top_not_flagged():
    desc = "DCS World F/A-18C Hornet CAS.\n0:00 Intro\n5:00 Combat\n" + "x" * 270
    issues = _check(description=desc, title="DCS World",
                    chapters=[{"time": "0:00", "label": "Intro"}])
    assert "CHAPTERS_TOO_LATE" not in codes(issues)
    assert "NO_CHAPTERS_IN_DESC" not in codes(issues)


def test_seo_playlist_not_early_flagged():
    desc = "DCS World F/A-18C Hornet CAS. " + "x" * 80 + " https://youtube.com/playlist?list=F18"
    issues = _check(description=desc, title="DCS World")
    assert "PLAYLIST_NOT_EARLY" in codes(issues)


def test_seo_playlist_early_not_flagged():
    desc = "https://youtube.com/playlist?list=F18 DCS World F/A-18C Hornet CAS. " + "x" * 250
    issues = _check(description=desc, title="DCS World")
    assert "PLAYLIST_NOT_EARLY" not in codes(issues)


def test_seo_no_playlist_in_desc_no_flag():
    desc = "DCS World F/A-18C Hornet CAS. " + "x" * 270
    issues = _check(description=desc, title="DCS World")
    assert "PLAYLIST_NOT_EARLY" not in codes(issues)


def test_seo_issue_severities_are_valid():
    issues = _check(description="short", title="no keyword", aircraft="F/A-18C Hornet",
                    mission_type="CAS", chapters=[{"time": "0:00", "label": "Intro"}])
    for issue in issues:
        assert issue["severity"] in {"warning", "info"}
        assert "code" in issue
        assert "message" in issue
        assert "suggestion" in issue


# ── detect_audio_chapters ─────────────────────────────────────────────────────

_SILENCE_DETECT_TEMPLATE = (
    "[silencedetect @ 0xABC] silence_start: 0\n"
    "[silencedetect @ 0xABC] silence_end: {end} | silence_duration: {dur}\n"
)


def _make_stderr(*silence_ends):
    """Build fake ffmpeg stderr with the given silence_end timestamps."""
    lines = []
    for t in silence_ends:
        lines.append(f"[silencedetect @ 0xABC] silence_start: {t - 3.0}")
        lines.append(f"[silencedetect @ 0xABC] silence_end: {t} | silence_duration: 3.0")
    return "\n".join(lines)


def test_detect_audio_chapters_includes_zero(tmp_path, monkeypatch):
    video = tmp_path / "v.mkv"
    video.write_bytes(b"")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: type("R", (), {"stderr": _make_stderr(180.0), "returncode": 0})(),
    )
    result = dcs_meta.detect_audio_chapters(video, duration_seconds=1200.0)
    assert result[0] == "0:00"


def test_detect_audio_chapters_converts_seconds(tmp_path, monkeypatch):
    video = tmp_path / "v.mkv"
    video.write_bytes(b"")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: type("R", (), {"stderr": _make_stderr(135.0), "returncode": 0})(),
    )
    result = dcs_meta.detect_audio_chapters(video, duration_seconds=1200.0)
    assert "2:15" in result


def test_detect_audio_chapters_min_gap_filters_close_silences(tmp_path, monkeypatch):
    video = tmp_path / "v.mkv"
    video.write_bytes(b"")
    # Two silences only 30 s apart — second should be filtered (default min_gap=60)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: type("R", (), {"stderr": _make_stderr(120.0, 150.0), "returncode": 0})(),
    )
    result = dcs_meta.detect_audio_chapters(video, duration_seconds=1200.0)
    assert "2:30" not in result


def test_detect_audio_chapters_tail_cutoff(tmp_path, monkeypatch):
    video = tmp_path / "v.mkv"
    video.write_bytes(b"")
    # Silence at 95% of a 600s video — should be filtered
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: type("R", (), {"stderr": _make_stderr(570.0), "returncode": 0})(),
    )
    result = dcs_meta.detect_audio_chapters(video, duration_seconds=600.0)
    assert len(result) == 1  # only "0:00"


def test_detect_audio_chapters_cap_at_eight(tmp_path, monkeypatch):
    video = tmp_path / "v.mkv"
    video.write_bytes(b"")
    # Generate 15 silences, each 120 s apart (well above min_gap)
    silence_ends = [float(120 * i) for i in range(1, 16)]
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: type("R", (), {"stderr": _make_stderr(*silence_ends), "returncode": 0})(),
    )
    result = dcs_meta.detect_audio_chapters(video, duration_seconds=3600.0)
    assert len(result) <= 8


def test_detect_audio_chapters_no_silences_returns_only_zero(tmp_path, monkeypatch):
    video = tmp_path / "v.mkv"
    video.write_bytes(b"")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: type("R", (), {"stderr": "no silence here", "returncode": 0})(),
    )
    result = dcs_meta.detect_audio_chapters(video, duration_seconds=1200.0)
    assert result == ["0:00"]


def test_detect_audio_chapters_ffmpeg_missing_returns_zero(tmp_path, monkeypatch):
    video = tmp_path / "v.mkv"
    video.write_bytes(b"")
    def raise_fnf(*a, **kw):
        raise FileNotFoundError("ffmpeg not found")
    monkeypatch.setattr("subprocess.run", raise_fnf)
    result = dcs_meta.detect_audio_chapters(video)
    assert result == ["0:00"]


# ── build_prompt audio_markers ────────────────────────────────────────────────

def test_build_prompt_includes_audio_markers():
    cfg = {**dcs_meta.DEFAULT_CONFIG}
    mem = {"videos": []}
    markers = ["0:00", "2:15", "12:30"]
    prompt = dcs_meta.build_prompt("", cfg, False, mem, duration_seconds=900.0,
                                   audio_markers=markers)
    assert "2:15" in prompt
    assert "12:30" in prompt
    assert "AUDIO PHASE MARKERS" in prompt


def test_build_prompt_no_audio_markers_when_single():
    cfg = {**dcs_meta.DEFAULT_CONFIG}
    mem = {"videos": []}
    prompt = dcs_meta.build_prompt("", cfg, False, mem, duration_seconds=900.0,
                                   audio_markers=["0:00"])
    assert "AUDIO PHASE MARKERS" not in prompt


def test_build_prompt_no_audio_markers_when_none():
    cfg = {**dcs_meta.DEFAULT_CONFIG}
    mem = {"videos": []}
    prompt = dcs_meta.build_prompt("", cfg, False, mem, duration_seconds=900.0,
                                   audio_markers=None)
    assert "AUDIO PHASE MARKERS" not in prompt


# ── generate_debrief ──────────────────────────────────────────────────────────

_DEBRIEF_META_EN = {
    "aircraft": "F/A-18C Hornet",
    "map": "Caucasus",
    "mission_type": "SEAD",
    "language": "en",
}

_DEBRIEF_META_ES = {
    "aircraft": "F/A-18C Hornet",
    "map": "Caucasus",
    "mission_type": "SEAD",
    "language": "es",
}

_GEMINI_DEBRIEF_RESPONSE = json.dumps({
    "result": "RTB",
    "kills": 2,
    "sam_evasions": 1,
    "max_mach": "0.95",
    "max_altitude": "24000 ft",
    "fuel_remaining": "3200 lb",
    "narrative": "Mission accomplished with two confirmed kills.",
})


def _make_debrief(metadata=None, language="en", gemini_response=None, monkeypatch=None, tmp_path=None):
    """Helper to call generate_debrief with mocked ffprobe/ffmpeg/Gemini."""
    video = tmp_path / "mission.mkv"
    video.write_bytes(b"")
    meta = metadata or (_DEBRIEF_META_ES if language == "es" else _DEBRIEF_META_EN)

    def fake_run(cmd, *a, **kw):
        class R:
            stdout = json.dumps({"format": {"duration": "1800.0"}})
            stderr = ""
            returncode = 0
        return R()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(dcs_meta, "extract_frames", lambda *a, **kw: [])
    response = gemini_response if gemini_response is not None else _GEMINI_DEBRIEF_RESPONSE
    monkeypatch.setattr(dcs_meta, "call_gemini", lambda *a, **kw: response)

    cfg = {**dcs_meta.DEFAULT_CONFIG}
    return dcs_meta.generate_debrief(meta, video, cfg)


def test_debrief_english_contains_aircraft(tmp_path, monkeypatch):
    report = _make_debrief(language="en", monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert "F/A-18C Hornet" in report


def test_debrief_english_header(tmp_path, monkeypatch):
    report = _make_debrief(language="en", monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert "MISSION DEBRIEF" in report


def test_debrief_spanish_header(tmp_path, monkeypatch):
    report = _make_debrief(language="es", monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert "ESCUADRÓN 111" in report


def test_debrief_rtb_icon(tmp_path, monkeypatch):
    report = _make_debrief(language="en", monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert "✓ RTB" in report


def test_debrief_kills_shown(tmp_path, monkeypatch):
    report = _make_debrief(language="en", monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert "2" in report


def test_debrief_narrative_included(tmp_path, monkeypatch):
    report = _make_debrief(language="en", monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert "Mission accomplished" in report


def test_debrief_duration_shown(tmp_path, monkeypatch):
    report = _make_debrief(language="en", monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert "30:00" in report


def test_debrief_graceful_on_bad_gemini_json(tmp_path, monkeypatch):
    report = _make_debrief(language="en", gemini_response="not json !!",
                           monkeypatch=monkeypatch, tmp_path=tmp_path)
    # Must still produce a report with basic metadata even without Gemini stats
    assert "F/A-18C Hornet" in report
    assert "MISSION DEBRIEF" in report


def test_debrief_null_kills_shows_dash(tmp_path, monkeypatch):
    response = json.dumps({"result": "RTB", "kills": None, "sam_evasions": None,
                           "max_mach": "--", "max_altitude": "--",
                           "fuel_remaining": "--", "narrative": ""})
    report = _make_debrief(language="en", gemini_response=response,
                           monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert "--" in report


def test_format_debrief_duration_under_one_hour():
    assert dcs_meta._format_debrief_duration(2537.0) == "42:17"


def test_format_debrief_duration_over_one_hour():
    assert dcs_meta._format_debrief_duration(3665.0) == "01:01:05"


def test_debrief_eject_icon_in_result_map():
    assert dcs_meta._DEBRIEF_RESULT_ICON["EJECT"] == "✗ EJECT"


def test_debrief_eject_result_shown_in_report(tmp_path, monkeypatch):
    response = json.dumps({
        "result": "EJECT", "kills": 1, "sam_evasions": 1,
        "max_mach": "0.88", "max_altitude": "18000 ft",
        "fuel_remaining": "0 lb", "narrative": "Pilot ejected after SA-15 hit."
    })
    report = _make_debrief(language="en", gemini_response=response,
                           monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert "✗ EJECT" in report


def test_debrief_eject_result_shown_in_spanish_report(tmp_path, monkeypatch):
    response = json.dumps({
        "result": "EJECT", "kills": 0, "sam_evasions": 0,
        "max_mach": "--", "max_altitude": "--",
        "fuel_remaining": "--", "narrative": "El piloto eyectó tras ser derribado."
    })
    report = _make_debrief(language="es", gemini_response=response,
                           monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert "✗ EJECT" in report


def test_debrief_prompt_includes_eject_option(tmp_path, monkeypatch):
    captured = {}

    def fake_call_gemini(frames, prompt, model):
        captured["prompt"] = prompt
        return json.dumps({"result": "RTB", "kills": 0, "sam_evasions": 0,
                           "max_mach": "--", "max_altitude": "--",
                           "fuel_remaining": "--", "narrative": ""})

    video = tmp_path / "mission.mkv"
    video.write_bytes(b"")
    monkeypatch.setattr(dcs_meta, "extract_frames", lambda *a, **kw: [])
    monkeypatch.setattr(dcs_meta, "_get_video_duration", lambda *a: 1800.0)
    monkeypatch.setattr(dcs_meta, "call_gemini", fake_call_gemini)
    dcs_meta.generate_debrief(_DEBRIEF_META_EN, video, {**dcs_meta.DEFAULT_CONFIG})
    assert "EJECT" in captured["prompt"]


# ── parse_acmi_events ──────────────────────────────────────────────────────────

def _write_acmi(tmp_path, lines):
    """Write a minimal ACMI file and return its Path."""
    f = tmp_path / "mission.acmi"
    header = "FileType=text/acmi/tacview\nFileVersion=2.2\n0,ReferenceTime=2023-01-01T00:00:00Z\n"
    f.write_text(header + "\n".join(lines), encoding="utf-8")
    return f


def test_parse_acmi_events_empty_file(tmp_path):
    f = tmp_path / "empty.acmi"
    f.write_text("FileType=text/acmi/tacview\nFileVersion=2.2\n", encoding="utf-8")
    result = dcs_meta.parse_acmi_events(f)
    assert result["kills"] == []
    assert result["sam_launches"] == []
    assert result["bvr_launches"] == []


def test_parse_acmi_events_kill_on_enemy_air(tmp_path):
    lines = [
        "#0",
        "A001,Type=FixedWing+Air+FixedWing,Name=MiG-29,Coalition=Enemies",
        "#135",
        "-A001",
    ]
    result = dcs_meta.parse_acmi_events(_write_acmi(tmp_path, lines))
    assert len(result["kills"]) == 1
    assert result["kills"][0]["name"] == "MiG-29"
    assert result["kills"][0]["time"] == "2:15"


def test_parse_acmi_events_kill_time_recorded(tmp_path):
    lines = [
        "#0",
        "A001,Type=FixedWing+Air+FixedWing,Name=Su-27,Coalition=Enemies",
        "#300",
        "-A001",
    ]
    result = dcs_meta.parse_acmi_events(_write_acmi(tmp_path, lines))
    assert result["kills"][0]["time_s"] == 300.0


def test_parse_acmi_events_friendly_not_counted_as_kill(tmp_path):
    lines = [
        "#0",
        "B001,Type=FixedWing+Air+FixedWing,Name=F-16C,Coalition=Allies",
        "#200",
        "-B001",
    ]
    result = dcs_meta.parse_acmi_events(_write_acmi(tmp_path, lines))
    assert result["kills"] == []


def test_parse_acmi_events_detects_sam_launch(tmp_path):
    lines = [
        "#0",
        "C001,Type=Ground+AntiAircraft+SAM,Name=SA-6 Battery,Coalition=Enemies",
        "#180",
        "D001,Type=Weapon+Missile+SAM,Name=SA-6 Gainful,Coalition=Enemies,Parent=C001",
    ]
    result = dcs_meta.parse_acmi_events(_write_acmi(tmp_path, lines))
    assert len(result["sam_launches"]) == 1
    assert "SA-6" in result["sam_launches"][0]["name"]


def test_parse_acmi_events_detects_bvr_launch(tmp_path):
    lines = [
        "#0",
        "P001,Type=FixedWing+Air+FixedWing,Name=F/A-18C,Coalition=Allies",
        "#287",
        "M001,Type=Weapon+Missile+AAM,Name=AIM-120C,Coalition=Allies,Parent=P001",
    ]
    result = dcs_meta.parse_acmi_events(_write_acmi(tmp_path, lines))
    assert len(result["bvr_launches"]) == 1
    assert result["bvr_launches"][0]["name"] == "AIM-120C"
    assert result["bvr_launches"][0]["time"] == "4:47"


def test_parse_acmi_events_non_bvr_missile_not_counted(tmp_path):
    lines = [
        "#0",
        "P001,Type=FixedWing+Air+FixedWing,Name=F/A-18C,Coalition=Allies",
        "#100",
        "M001,Type=Weapon+Missile+AAM,Name=AIM-9X,Coalition=Allies,Parent=P001",
    ]
    result = dcs_meta.parse_acmi_events(_write_acmi(tmp_path, lines))
    assert result["bvr_launches"] == []


def test_parse_acmi_events_events_text_populated(tmp_path):
    lines = [
        "#0",
        "A001,Type=FixedWing+Air+FixedWing,Name=MiG-21,Coalition=Enemies",
        "#90",
        "-A001",
    ]
    result = dcs_meta.parse_acmi_events(_write_acmi(tmp_path, lines))
    assert "kill" in result["events_text"]
    assert "MiG-21" in result["events_text"]


def test_parse_acmi_events_empty_text_when_no_events(tmp_path):
    lines = ["#0", "P001,Type=FixedWing+Air+FixedWing,Name=F/A-18C,Coalition=Allies"]
    result = dcs_meta.parse_acmi_events(_write_acmi(tmp_path, lines))
    assert result["events_text"] == ""


def test_parse_acmi_events_missing_file_returns_empty():
    result = dcs_meta.parse_acmi_events(Path("/nonexistent/mission.acmi"))
    assert result == {}


def test_parse_acmi_events_zip_acmi(tmp_path):
    import zipfile
    # Build a plain ACMI in memory and wrap it in a zip — mimics TacView's .zip.acmi format
    header = "FileType=text/acmi/tacview\nFileVersion=2.2\n0,ReferenceTime=2023-01-01T00:00:00Z\n"
    inner_content = (
        header
        + "#0\n"
        + "A001,Type=FixedWing+Air+FixedWing,Name=MiG-29,Coalition=Enemies\n"
        + "#135\n"
        + "-A001\n"
    )
    zip_path = tmp_path / "mission.zip.acmi"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mission.acmi", inner_content)
    result = dcs_meta.parse_acmi_events(zip_path)
    assert len(result["kills"]) == 1
    assert result["kills"][0]["name"] == "MiG-29"


def test_parse_acmi_events_duration_tracked(tmp_path):
    lines = ["#0", "P001,T=0|0|1000", "#1800", "P001,T=0.1|0.1|2000"]
    result = dcs_meta.parse_acmi_events(_write_acmi(tmp_path, lines))
    assert result["duration_s"] == 1800.0


def test_parse_acmi_props_key_value():
    props, flags = dcs_meta._parse_acmi_props("Type=FixedWing+Air,Name=MiG-29,Coalition=Enemies")
    assert props["Type"] == "FixedWing+Air"
    assert props["Name"] == "MiG-29"
    assert flags == set()


def test_parse_acmi_props_standalone_flag():
    props, flags = dcs_meta._parse_acmi_props("T=0|0|1000,Destroyed")
    assert "Destroyed" in flags
    assert "T" in props


def test_build_prompt_with_acmi_events():
    cfg = {**dcs_meta.DEFAULT_CONFIG}
    mem = {"videos": []}
    events = {
        "events_text": "1 kill(s): MiG-29 at 2:15; 1 SAM launch(es) at 5:30",
        "kills": [{"time_s": 135.0, "time": "2:15", "name": "MiG-29"}],
        "sam_launches": [{"time_s": 330.0, "time": "5:30", "name": "SA-6"}],
        "bvr_launches": [],
    }
    prompt = dcs_meta.build_prompt("", cfg, False, mem, duration_seconds=1200.0,
                                   acmi_events=events)
    assert "TACVIEW ACMI DATA" in prompt
    assert "MiG-29 at 2:15" in prompt
    assert "SAM launch" in prompt


def test_build_prompt_no_acmi_block_when_none():
    cfg = {**dcs_meta.DEFAULT_CONFIG}
    mem = {"videos": []}
    prompt = dcs_meta.build_prompt("", cfg, False, mem, acmi_events=None)
    assert "TACVIEW ACMI DATA" not in prompt


def test_build_prompt_no_acmi_block_when_empty_text():
    cfg = {**dcs_meta.DEFAULT_CONFIG}
    mem = {"videos": []}
    events = {"events_text": "", "kills": [], "sam_launches": [], "bvr_launches": []}
    prompt = dcs_meta.build_prompt("", cfg, False, mem, acmi_events=events)
    assert "TACVIEW ACMI DATA" not in prompt


# ── Bug fixes ─────────────────────────────────────────────────────────────────

def test_load_config_reads_utf8_characters(tmp_path, monkeypatch):
    """load_config() must decode non-ASCII characters correctly on Windows (Bug #4)."""
    cfg_path = tmp_path / "config" / "config.json"
    cfg_path.parent.mkdir()
    cfg_path.write_text('{"channel_name": "EscuadrÓn 111"}', encoding="utf-8")
    monkeypatch.setattr(dcs_meta, "CONFIG_PATH", cfg_path)
    cfg = dcs_meta.load_config()
    assert cfg["channel_name"] == "EscuadrÓn 111"


def test_save_and_reload_memory_preserves_utf8(tmp_path, monkeypatch):
    """save_memory/load_memory must round-trip non-ASCII strings correctly (Bug #4)."""
    mem_path = tmp_path / "memory" / "history.json"
    mem_path.parent.mkdir()
    monkeypatch.setattr(dcs_meta, "MEMORY_PATH", mem_path)
    memory = {"videos": [{"title": "Operación Trueno — SEAD"}]}
    dcs_meta.save_memory(memory)
    loaded = dcs_meta.load_memory()
    assert loaded["videos"][0]["title"] == "Operación Trueno — SEAD"


def test_build_prompt_substitutes_social_links(monkeypatch):
    """build_prompt() must replace [link] tokens with actual config URLs (Bug #5)."""
    cfg = {
        **dcs_meta.DEFAULT_CONFIG,
        "default_links": {
            "twitter": "https://twitter.com/testuser",
            "twitch": "https://www.twitch.tv/testuser",
            "buymeacoffee": "https://www.buymeacoffee.com/testuser",
            "escuadron111": "https://example.com",
            "dcs_f18_playlist": "",
            "dcs_a10c_playlist": "",
            "dcs_huey_playlist": "",
        },
    }
    mem = {"videos": []}
    prompt = dcs_meta.build_prompt("", cfg, is_squadron=False, memory=mem)
    assert "[link]" not in prompt
    assert "https://twitter.com/testuser" in prompt
    assert "https://www.twitch.tv/testuser" in prompt
    assert "https://www.buymeacoffee.com/testuser" in prompt
    assert "Buy Me a Coffee:" in prompt


def test_build_prompt_no_patreon_hallucination(monkeypatch):
    """Gemini prompt must not contain a Patreon placeholder after link substitution (Bug #5)."""
    cfg = {**dcs_meta.DEFAULT_CONFIG}
    mem = {"videos": []}
    prompt = dcs_meta.build_prompt("", cfg, is_squadron=False, memory=mem)
    assert "patreon" not in prompt.lower()
    assert "[link]" not in prompt


# ── generate_short_metadata ───────────────────────────────────────────────────

_BASE_META_FOR_SHORTS = {
    "title": "DCS World | F/A-18C | SEAD Mission",
    "description": "This is a great SEAD mission over the Caucasus with lots of action and SAM evasion.",
    "tags": ["dcs", "fa18", "hornet", "sead", "caucasus", "f18", "sim", "gaming", "jet", "military"],
    "aircraft": "F/A-18C Hornet",
}

_SAMPLE_CLIP = {
    "hook": "This kill 🔥",
    "score": 10,
    "start_sec": 45.0,
    "duration_sec": 60.0,
    "clip_path": "/output/shorts/test_short_1.mp4",
}


def test_generate_short_metadata_title_contains_hook():
    result = dcs_meta.generate_short_metadata(_SAMPLE_CLIP, _BASE_META_FOR_SHORTS, {})
    assert "This kill" in result["title"]


def test_generate_short_metadata_title_contains_shorts_hashtag():
    result = dcs_meta.generate_short_metadata(_SAMPLE_CLIP, _BASE_META_FOR_SHORTS, {})
    assert "#Shorts" in result["title"]


def test_generate_short_metadata_title_within_100_chars():
    result = dcs_meta.generate_short_metadata(_SAMPLE_CLIP, _BASE_META_FOR_SHORTS, {})
    assert len(result["title"]) <= 100


def test_generate_short_metadata_title_contains_aircraft():
    result = dcs_meta.generate_short_metadata(_SAMPLE_CLIP, _BASE_META_FOR_SHORTS, {})
    assert "F/A-18C Hornet" in result["title"]


def test_generate_short_metadata_description_contains_shorts():
    result = dcs_meta.generate_short_metadata(_SAMPLE_CLIP, _BASE_META_FOR_SHORTS, {})
    assert "#Shorts" in result["description"]


def test_generate_short_metadata_description_contains_dcsworld():
    result = dcs_meta.generate_short_metadata(_SAMPLE_CLIP, _BASE_META_FOR_SHORTS, {})
    assert "#DCSWorld" in result["description"]


def test_generate_short_metadata_description_contains_base_text():
    result = dcs_meta.generate_short_metadata(_SAMPLE_CLIP, _BASE_META_FOR_SHORTS, {})
    assert "SEAD mission" in result["description"]


def test_generate_short_metadata_tags_include_shorts():
    result = dcs_meta.generate_short_metadata(_SAMPLE_CLIP, _BASE_META_FOR_SHORTS, {})
    assert "Shorts" in result["tags"]
    assert "DCSWorld" in result["tags"]
    assert "YouTube Shorts" in result["tags"]


def test_generate_short_metadata_tags_include_base_tags():
    result = dcs_meta.generate_short_metadata(_SAMPLE_CLIP, _BASE_META_FOR_SHORTS, {})
    assert "dcs" in result["tags"]
    assert "fa18" in result["tags"]


def test_generate_short_metadata_base_tags_capped_at_10():
    long_meta = {**_BASE_META_FOR_SHORTS, "tags": [f"tag{i}" for i in range(20)]}
    result = dcs_meta.generate_short_metadata(_SAMPLE_CLIP, long_meta, {})
    base_tags = [t for t in result["tags"] if t not in ("Shorts", "DCSWorld", "YouTube Shorts")]
    assert len(base_tags) <= 10


def test_generate_short_metadata_title_very_long_aircraft_truncated():
    long_aircraft = "F/A-18C Hornet Super Lot II Very Long Name That Goes On And On"
    clip = {**_SAMPLE_CLIP, "hook": "Precision strike 💣"}
    meta = {**_BASE_META_FOR_SHORTS, "aircraft": long_aircraft}
    result = dcs_meta.generate_short_metadata(clip, meta, {})
    assert len(result["title"]) <= 100


# ── detect_short_clips ────────────────────────────────────────────────────────

def _make_fake_process(returncode=0):
    """Return a mock subprocess.CompletedProcess."""
    return type("Proc", (), {"returncode": returncode, "stdout": "", "stderr": ""})()


def test_detect_short_clips_returns_list_with_acmi_kill(tmp_path, monkeypatch):
    video = tmp_path / "mission.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(dcs_meta, "_get_video_duration", lambda *a: 300.0)
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: _make_fake_process())
    acmi = {"kills": [{"time_s": 60.0}], "sam_launches": [], "bvr_launches": [],
            "ejection_events": [], "guided_bomb_drops": []}
    clips = dcs_meta.detect_short_clips(video, acmi, {})
    assert isinstance(clips, list)
    assert len(clips) >= 1
    assert clips[0]["hook"] == "This kill 🔥"
    assert clips[0]["score"] == 10


def test_detect_short_clips_sorted_by_score_desc(tmp_path, monkeypatch):
    video = tmp_path / "mission.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(dcs_meta, "_get_video_duration", lambda *a: 600.0)
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: _make_fake_process())
    acmi = {
        "kills": [{"time_s": 100.0}],
        "sam_launches": [{"time_s": 200.0}],
        "bvr_launches": [],
        "ejection_events": [],
        "guided_bomb_drops": [],
    }
    clips = dcs_meta.detect_short_clips(video, acmi, {})
    scores = [c["score"] for c in clips]
    assert scores == sorted(scores, reverse=True)


def test_detect_short_clips_caps_at_five(tmp_path, monkeypatch):
    video = tmp_path / "mission.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(dcs_meta, "_get_video_duration", lambda *a: 3600.0)
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: _make_fake_process())
    many_kills = [{"time_s": float(i * 120)} for i in range(10)]
    acmi = {"kills": many_kills, "sam_launches": [], "bvr_launches": [],
            "ejection_events": [], "guided_bomb_drops": []}
    clips = dcs_meta.detect_short_clips(video, acmi, {})
    assert len(clips) <= 5


def test_detect_short_clips_empty_acmi_falls_back_to_audio(tmp_path, monkeypatch):
    video = tmp_path / "mission.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(dcs_meta, "_get_video_duration", lambda *a: 300.0)
    call_log = []

    def fake_run(args, *a, **kw):
        call_log.append(args)
        return _make_fake_process()

    monkeypatch.setattr("subprocess.run", fake_run)
    acmi = {"kills": [], "sam_launches": [], "bvr_launches": [],
            "ejection_events": [], "guided_bomb_drops": []}
    dcs_meta.detect_short_clips(video, acmi, {})
    # At least one ffmpeg call for audio peak detection should happen
    assert any("astats" in " ".join(str(a) for a in cmd) for cmd in call_log)


def test_detect_short_clips_clip_path_in_shorts_dir(tmp_path, monkeypatch):
    video = tmp_path / "mission.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(dcs_meta, "_get_video_duration", lambda *a: 300.0)
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: _make_fake_process())
    monkeypatch.setattr(dcs_meta, "OUTPUT_PATH", tmp_path / "output")
    acmi = {"kills": [{"time_s": 60.0}], "sam_launches": [], "bvr_launches": [],
            "ejection_events": [], "guided_bomb_drops": []}
    clips = dcs_meta.detect_short_clips(video, acmi, {})
    if clips:
        assert "shorts" in clips[0]["clip_path"]


def test_detect_short_clips_deduplicates_nearby_timestamps(tmp_path, monkeypatch):
    video = tmp_path / "mission.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(dcs_meta, "_get_video_duration", lambda *a: 600.0)
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: _make_fake_process())
    acmi = {
        "kills": [{"time_s": 100.0}, {"time_s": 115.0}],
        "sam_launches": [], "bvr_launches": [],
        "ejection_events": [], "guided_bomb_drops": [],
    }
    clips = dcs_meta.detect_short_clips(video, acmi, {})
    # Two timestamps within 30s should be deduplicated to 1
    assert len(clips) == 1


def test_detect_short_clips_ffmpeg_failure_skips_clip(tmp_path, monkeypatch):
    import subprocess as _sp

    video = tmp_path / "mission.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(dcs_meta, "_get_video_duration", lambda *a: 300.0)

    def failing_run(args, *a, **kw):
        if "crop" in " ".join(str(a) for a in args):
            raise _sp.CalledProcessError(1, args)
        return _make_fake_process()

    monkeypatch.setattr("subprocess.run", failing_run)
    acmi = {"kills": [{"time_s": 60.0}], "sam_launches": [], "bvr_launches": [],
            "ejection_events": [], "guided_bomb_drops": []}
    clips = dcs_meta.detect_short_clips(video, acmi, {})
    # Failed clip extraction returns empty list (clip skipped)
    assert clips == []


# ── _deduplicate_candidates ───────────────────────────────────────────────────

def test_deduplicate_keeps_higher_priority_event():
    candidates = [(100.0, "bvr"), (110.0, "kill")]
    result = dcs_meta._deduplicate_candidates(candidates)
    assert len(result) == 1
    assert result[0][1] == "kill"


def test_deduplicate_keeps_both_when_far_apart():
    candidates = [(100.0, "kill"), (200.0, "kill")]
    result = dcs_meta._deduplicate_candidates(candidates)
    assert len(result) == 2


# ── _parse_audio_peaks ────────────────────────────────────────────────────────

def test_parse_audio_peaks_detects_above_threshold():
    stderr = "pts_time:30.0\nlavfi.astats.Overall.RMS_level=-15.0\n"
    peaks = dcs_meta._parse_audio_peaks(stderr, threshold_db=-20.0)
    assert 30.0 in peaks


def test_parse_audio_peaks_ignores_below_threshold():
    stderr = "pts_time:30.0\nlavfi.astats.Overall.RMS_level=-25.0\n"
    peaks = dcs_meta._parse_audio_peaks(stderr, threshold_db=-20.0)
    assert peaks == []
