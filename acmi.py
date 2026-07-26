"""TacView ACMI 2.2 parsing — kills, launches, ejections, friendly losses."""

from pathlib import Path

# ACMI classification sets
_BVR_MISSILE_NAMES = frozenset({
    "aim-120", "aim-7", "aim-54", "r-77", "r-27", "meteor",
    "mica", "derby", "python",
})
_IR_MISSILE_NAMES = frozenset({
    "aim-9", "r-73", "r-60", "r-73m", "aa-11", "archer",
    "magic", "python-3", "python-4", "python-5",
    "aim-9x", "aim-9m", "aim-9l", "aim-9p",
})
_GUIDED_BOMB_NAMES = frozenset({
    "gbu-12", "gbu-31", "gbu-38", "gbu-10", "gbu-16", "gbu-24",
    "mk-82", "mk-84", "mk-83", "jdam", "paveway",
    "kab-500", "kab-1500",
})
_SAM_NAME_FRAGMENTS = frozenset({
    "sa-2", "sa-3", "sa-6", "sa-8", "sa-10", "sa-11", "sa-12",
    "sa-13", "sa-15", "sa-19", "sa-20", "sa-23", "s-75", "s-125",
    "s-300", "s-400", "patriot", "hawk", "roland", "crotale", "buk",
    "tor", "tunguska", "pantsir", "strela", "igla", "stinger",
    # DCS2ACMI missile names (no hyphens, use internal weapon designations)
    "9m330", "9m331", "9m38", "9m9", "9m96", "5v55", "48n6",
    "sa9m",  # covers SA9M330, SA9M331 variants
})
_FRIENDLY_COALITIONS = frozenset({"allies", "blue", "friend"})
_HOSTILE_COALITIONS = frozenset({"enemies", "red", "enemy"})


def _parse_acmi_props(props_str: str) -> tuple[dict, set]:
    """Split ACMI property string into (key→value dict, standalone-flags set)."""
    props: dict = {}
    flags: set = set()
    for token in props_str.split(","):
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            k, _, v = token.partition("=")
            props[k.strip()] = v.strip()
        else:
            flags.add(token)
    return props, flags


def parse_acmi_events(acmi_path: Path) -> dict:
    """Parse a Tacview ACMI 2.2 file and return kills, SAM/IR/bomb launches, BVR launches, and ejections.

    Returns a dict with keys kills, sam_launches, bvr_launches, ir_launches, bomb_releases,
    friendly_losses, ejection_events, events_text, duration_s.
    Returns empty dict on any parse or IO failure.
    """
    # Deferred import: avoids a circular import until TEC-01c moves this helper out of
    # dcs_meta.py into its own media module (see BACKLOG.md TEC-01c).
    from dcs_meta import _seconds_to_chapter_time

    objects: dict = {}
    current_time_s = 0.0
    max_time_s = 0.0
    kills: list = []
    sam_launches: list = []
    bvr_launches: list = []
    ir_launches: list = []
    bomb_releases: list = []
    friendly_losses: list = []
    ejection_events: list = []

    try:
        import io as _io
        import zipfile

        acmi_path = Path(acmi_path)
        if zipfile.is_zipfile(acmi_path):
            with zipfile.ZipFile(acmi_path) as zf:
                inner = next((n for n in zf.namelist() if n.lower().endswith(".acmi")), zf.namelist()[0])
                raw_bytes = zf.read(inner)
            _lines_src = _io.TextIOWrapper(_io.BytesIO(raw_bytes), encoding="utf-8-sig", errors="replace")
        else:
            # _lines_src must stay open across the for-loop below, shared with the zip
            # branch above (a TextIOWrapper, not a real file handle); wrapping the whole
            # parse loop in a `with` would mean re-indenting ~150 lines for a resource
            # that's already released on function return either way.
            _lines_src = open(acmi_path, encoding="utf-8-sig", errors="replace")  # noqa: SIM115

        for raw_line in _lines_src:
            line = raw_line.rstrip("\r\n")
            if not line or line.startswith(("//", "FileType", "FileVersion")):
                continue

            if line.startswith("#"):
                try:
                    current_time_s = float(line[1:])
                    max_time_s = max(max_time_s, current_time_s)
                except ValueError:
                    pass
                continue

            # DCS2ACMI records object destruction as "-{id}" removal lines.
            # These are the only reliable kill/loss signals in this format.
            if line.startswith("-"):
                removed_id = line[1:].strip()
                obj = objects.get(removed_id)
                if obj:
                    t = obj.get("type", "")
                    color = obj.get("color", "")
                    coal = obj.get("coalition", "")
                    # Color field is reliable; Coalition is the fallback for older recorders
                    is_rem_hostile = color == "red" or (not color and coal in _HOSTILE_COALITIONS)
                    is_rem_friendly = color == "blue" or (not color and coal in _FRIENDLY_COALITIONS)
                    if "weapon" not in t:
                        if is_rem_hostile and ("air" in t or "ground" in t):
                            kills.append({
                                "time_s": current_time_s,
                                "time": _seconds_to_chapter_time(current_time_s),
                                "name": obj.get("name", "unknown"),
                            })
                        elif is_rem_friendly and "air" in t:
                            friendly_losses.append({
                                "time_s": current_time_s,
                                "time": _seconds_to_chapter_time(current_time_s),
                                "name": obj.get("name", "friendly aircraft"),
                            })
                continue

            comma_pos = line.find(",")
            if comma_pos < 0:
                continue
            obj_id = line[:comma_pos]
            if obj_id == "0":
                continue

            is_new = obj_id not in objects
            if is_new:
                objects[obj_id] = {"type": "", "name": "", "color": "", "coalition": "", "parent": "", "tags": ""}
            obj = objects[obj_id]

            props, _flags = _parse_acmi_props(line[comma_pos + 1:])
            if "Type" in props:
                obj["type"] = props["Type"].lower()
            if "Name" in props:
                obj["name"] = props["Name"]
            if "Color" in props:
                obj["color"] = props["Color"].lower()
            if "Coalition" in props:
                obj["coalition"] = props["Coalition"].lower()
            if "Parent" in props:
                obj["parent"] = props["Parent"]
            if "Tags" in props:
                obj["tags"] = props["Tags"].lower()

            t = obj.get("type", "")
            name_lower = obj.get("name", "").lower()
            # Use Color (reliable) with Coalition as fallback for weapon-side detection
            color = obj.get("color", "") or objects.get(obj.get("parent", ""), {}).get("color", "")
            coal = obj.get("coalition", "") or objects.get(obj.get("parent", ""), {}).get("coalition", "")

            # Ejection: new friendly pilot/parachute object appearing
            obj_tags = obj.get("tags", "")
            if (is_new and (color == "blue" or coal in _FRIENDLY_COALITIONS)
                    and ("pilot" in obj_tags or "ejected" in obj_tags or "parachut" in obj_tags)):
                ejection_events.append({
                    "time_s": current_time_s,
                    "time": _seconds_to_chapter_time(current_time_s),
                    "name": obj.get("name", "friendly pilot"),
                })

            # New weapon object → classify launch type using Color first, Coalition as fallback
            if is_new and "weapon" in t:
                is_friendly = color == "blue" or coal in _FRIENDLY_COALITIONS
                is_hostile = color == "red" or coal in _HOSTILE_COALITIONS
                if "missile" in t:
                    if is_friendly and any(m in name_lower for m in _BVR_MISSILE_NAMES):
                        bvr_launches.append({
                            "time_s": current_time_s,
                            "time": _seconds_to_chapter_time(current_time_s),
                            "name": obj.get("name", "BVR missile"),
                        })
                    elif is_friendly and any(m in name_lower for m in _IR_MISSILE_NAMES):
                        ir_launches.append({
                            "time_s": current_time_s,
                            "time": _seconds_to_chapter_time(current_time_s),
                            "name": obj.get("name", "IR missile"),
                        })
                    elif is_hostile and any(frag in name_lower for frag in _SAM_NAME_FRAGMENTS):
                        sam_launches.append({
                            "time_s": current_time_s,
                            "time": _seconds_to_chapter_time(current_time_s),
                            "name": obj.get("name", "SAM"),
                        })
                elif is_friendly and ("bomb" in t or "shell" in t or any(b in name_lower for b in _GUIDED_BOMB_NAMES)):
                    bomb_releases.append({
                        "time_s": current_time_s,
                        "time": _seconds_to_chapter_time(current_time_s),
                        "name": obj.get("name", "guided bomb"),
                    })

    except OSError:
        return {}

    parts = []
    if kills:
        parts.append(f"{len(kills)} kill(s): {', '.join(k['name'] + ' at ' + k['time'] for k in kills[:5])}")
    if sam_launches:
        parts.append(f"{len(sam_launches)} SAM launch(es) at {', '.join(s['time'] for s in sam_launches[:4])}")
    if bvr_launches:
        parts.append(f"{len(bvr_launches)} BVR missile(s) fired at {', '.join(b['time'] for b in bvr_launches[:4])}")
    if ir_launches:
        parts.append(f"{len(ir_launches)} IR missile(s) fired at {', '.join(m['time'] for m in ir_launches[:4])}")
    if bomb_releases:
        parts.append(f"{len(bomb_releases)} guided bomb(s) released at {', '.join(b['time'] for b in bomb_releases[:4])}")
    if friendly_losses:
        parts.append(f"{len(friendly_losses)} friendly aircraft lost at {', '.join(l['time'] for l in friendly_losses[:3])}")
    if ejection_events:
        parts.append(f"{len(ejection_events)} ejection(s) at {', '.join(e['time'] for e in ejection_events[:3])}")

    return {
        "duration_s": max_time_s,
        "kills": kills,
        "sam_launches": sam_launches,
        "bvr_launches": bvr_launches,
        "ir_launches": ir_launches,
        "bomb_releases": bomb_releases,
        "friendly_losses": friendly_losses,
        "ejection_events": ejection_events,
        "events_text": "; ".join(parts) if parts else "",
    }
