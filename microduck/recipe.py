# SPDX-License-Identifier: MIT
"""Build recipes for the "Build yours" configurator.

evaluate(bundle, selection) is a pure function from a selection (controller,
locomotion, actuators and driver, camera, head articulation, LEGO-compatible
features, and the wheel choices) to a recipe: verdict first, then files to
print, parts, wiring, power, software, analysis numbers and assembly steps.

All knowledge is in config/compat.json and config/bases.json. This module
only walks that data, and site/build.js walks it the same way; a test runs
both over every combination and compares the results. Standard library only,
so scripts/build_site.py can import it in the Pages workflow.

    python -m microduck.recipe controller=ev3 locomotion=crank drive=ev3_motors lego=on
"""
from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PATHS = ("reports/variants/summary.json", "reports/lego/summary.json")
MANIFEST_PATHS = ("stl/manifest.json", "stl/MANIFEST.json")
MAX_NEAREST_STEPS = 8


# --- data -------------------------------------------------------------------

def _load(path: Path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def facts(root: Path = ROOT) -> dict:
    """Strings for the {placeholders} in compat.json, from the reports."""
    assembly = _load(root / "reports" / "assembly.json")
    features = assembly["variants"][assembly["selected"]].get("lego_compatible", {})
    return {
        "lego_holes": str(len(features.get("holes", []))),
        "lego_studs": str(len(features.get("studs", []))),
    }


def camera_default(compat: dict, root: Path = ROOT) -> str:
    """The camera preset the design is generated and analysed for by default:
    config/assembly.json camera.preset, the one switch for the whole
    repository. 'none' if that file names a camera this page does not offer."""
    preset = _load(root / "config" / "assembly.json").get("camera", {}).get("preset")
    known = [option["id"] for dim in compat["dimensions"] if dim["id"] == "camera" for option in dim["options"]]
    return preset if preset in known else "none"


def coverage(compat: dict, listing: dict, root: Path = ROOT) -> dict:
    """What the reports cover for the servo biped.

    'entries' are matched on controller, camera and head:
    - the preset of the selected assembly variant on the UNO Q with the fixed
      mount was also simulated: 'analysed';
    - the other camera presets, the other controllers' decks and the turning
      head went through the digital assembly only: 'assembly_only'.
    Anything else is not covered and the recipe says so.

    'carried' holds the controllers the reports only placed on the deck as a
    block for a balance figure, with no supported way to drive the servos:
    a note for the "not possible" answer, never a verdict.
    """
    assembly = _load(root / "reports" / "assembly.json")
    sim = _load(root / "reports" / "sim.json")
    rep = assembly["variants"][assembly["selected"]]
    size = rep["dimensions"]["size_mm"]
    mass = rep["mass"]
    camera = rep.get("camera", {})
    stand = rep["balance"]["stand_pose"]
    fixed = compat["defaults"]["head"]
    home = listing["controller_default"]
    own = {value: key for key, value in compat["manifest_map"]["controller"].items()}
    entries = []
    simulated = camera.get("name", "default camera")
    if camera.get("preset") and home in own:
        overlaps = rep.get("neutral_interferences", [])
        entries.append({"match": {"controller": own[home], "camera": camera["preset"], "head": fixed}, "status": "analysed", "lines": [
            f"Analysed with the {camera['name']} in the mount and the pin holes and studs on the parts.",
            f"Mass {round(mass['total_g'])} g by the model ({round(mass['total_if_printed_solid_g'])} g if printed solid); "
            f"size {round(size[0])} x {round(size[1])} x {round(size[2])} mm; "
            f"feet {round(rep['dimensions']['stance_width_between_foot_centres_mm'])} mm apart.",
            ("No parts overlap at the neutral pose." if not overlaps
             else f"{len(overlaps)} pairs of parts overlap at the neutral pose; see the biped page."),
            f"Static balance at the stand pose (thighs {stand['thigh_swing_deg']:g} degrees back): centre of mass "
            f"{stand['margin_mm']:g} mm inside the support polygon.",
            f"Camera: lens {camera['lens_height_above_floor_at_stand_mm']:g} mm above the floor at the stand pose, "
            f"{camera['tilt_below_level_deg']:g} degrees below level, {camera['clearance_each_side_mm']:g} mm each side in the mount.",
            sim["verdict"]["stand"],
            sim["verdict"]["neutral"],
            sim["verdict"]["gait"],
            f"The assembly test lists {len(assembly['findings'])} findings. They are on the biped page and in reports/assembly.json.",
        ]})
    for preset, short in assembly.get("camera_presets", {}).items():
        if home not in own:
            break
        cone = "clear" if not short["cone_blocked_at_neutral"] and not short["cone_blocked_at_stand"] else "not clear"
        entries.append({"match": {"controller": own[home], "camera": preset, "head": fixed}, "status": "assembly_only", "lines": [
            f"Digital assembly in short form with the {short['name']} and its own torso: total mass {short['total_g']:g} g, "
            f"centre of mass {short['stand_margin_mm']:g} mm inside the support polygon at the stand pose "
            f"(thighs {short['stand_thigh_swing_deg']:g} degrees back), {short['clearance_each_side_mm']:g} mm each side in the mount, "
            f"view cone {cone} at the neutral and stand poses.",
            f"Not simulated: the MuJoCo runs used the {simulated} torso. Joint sweeps and the full findings list were run for that torso only.",
        ]})
    torso_camera = {entry["file"]: entry["camera"] for entry in listing["files"]}
    report_name = compat["report_controller"]
    carried = {}
    for controller, name in report_name.items():
        block = assembly.get("controllers", {}).get(name)
        if block is None:
            continue
        figures = (f"{block['name']}, taken as one block of {block['mass_g']:g} g (assumed): total mass {block['total_g']:g} g, "
                   f"centre of mass {block['stand_margin_mm']:g} mm inside the support polygon at the stand pose "
                   f"(thighs {block['stand_thigh_swing_deg']:g} degrees back), holding torque "
                   f"{round(block['hip_pitch_torque_fraction'] * 100)} percent of the hip pitch servo limit")
        supported = any(row["controller"] == controller and row["status"] == "report" for row in compat["support"])
        if supported and block.get("has_its_own_torso") and torso_camera.get(block["torso_file"]) is not None:
            clear = "no parts overlap at the neutral pose" if not block["neutral_interferences"] else "parts overlap at the neutral pose"
            entries.append({"match": {"controller": controller, "camera": torso_camera[block["torso_file"]], "head": fixed},
                            "status": "assembly_only", "lines": [
                f"Digital assembly, fit and static balance only, with the {figures}; {clear}.",
                f"Not simulated: the MuJoCo runs used the UNO Q torso with the {simulated}. Joint sweeps were not repeated for this torso.",
            ]})
        elif not supported:
            carried[controller] = (f"As a carried block only, the reports checked the servo biped's static balance with the {figures}. "
                                   "That is a balance figure for carrying it. It is not a way to drive the servos, and it makes nothing buildable.")
    head = assembly.get("turning_head")
    if head and home in own:
        travel = head["pan_travel_to_the_stops_deg"]
        tilt = head["tilt_free_deg"]
        margins = [pose["stand_margin_mm"] for pose in head["at_the_stand_pose"]]
        clear = "no parts overlap at the neutral pose" if not head["neutral_interferences"] else "parts overlap at the neutral pose"
        lines = [
            f"Digital assembly of the turning head with the {head['camera_preset']} cradle, pan only: {travel[0]:g} to {travel[1]:g} degrees "
            f"between the printed stops, {clear}, total mass {head['total_g']:g} g of which the head is {head['head_mass_g']:g} g, "
            f"centre of mass {min(margins):g} to {max(margins):g} mm inside the support polygon at the stand pose across the pan travel.",
            f"Tilt is set by hand: the cradle is free from {tilt[0]:g} to {tilt[1]:g} degrees about its screw and was checked at "
            f"{head['tilt_set_to_deg']:g} degrees. At full pan the legs are in the camera's view cone.",
            "Not simulated: the head has no joint in the robot description, the simulation or the command format.",
        ]
        for option, name in compat["manifest_map"]["head"].items():
            if name == "pan":
                entries.append({"match": {"controller": own[home], "camera": head["camera_preset"], "head": option},
                                "status": "assembly_only", "lines": lines})
    return {"entries": entries, "carried": carried}


def manifest(compat: dict, root: Path = ROOT) -> dict:
    """The STLs committed under stl/, from stl/manifest.json.

    Its shape: {"files": [{"file", "what", "options": {...}}]}, where options
    holds "part" (torso, left_hip, ...) or "fit_piece", and where they apply
    "controller", "head" and "camera". A torso with no controller option is
    for the generator's default controller (stl/parameters.json,
    controller_default). Those files are also copied into the site by the
    site build ('served'). Any other string in the manifest that ends in .stl
    is kept as a path too, so files another branch lists differently (the
    walkers' and wheeled parts, which do not exist yet) can still be linked.
    """
    default = camera_default(compat, root)
    for name in MANIFEST_PATHS:
        path = root / name
        if path.is_file():
            content = _load(path)
            home = "unoq"
            parameters = path.with_name("parameters.json")
            if parameters.is_file():
                home = _load(parameters).get("controller_default", home)
            files = []
            entries = content.get("files", []) if isinstance(content, dict) else []
            for entry in entries:
                if isinstance(entry, dict) and str(entry.get("file", "")).lower().endswith(".stl"):
                    options = entry.get("options", {})
                    part = options.get("part")
                    files.append({"file": entry["file"], "what": str(entry.get("what", "")),
                                  "fit": bool(options.get("fit_piece")), "part": part,
                                  "controller": options.get("controller", home if part == "torso" else None),
                                  "head": options.get("head"), "camera": options.get("camera")})
            found: list[str] = []
            _collect_stl_names(content, found)
            # Picture, size and print note of every part, by its path under stl/.
            info = {}
            extras = content.get("thumbnails", {}) if isinstance(content, dict) else {}
            described = [(entry.get("file"), entry) for entry in entries if isinstance(entry, dict)] + list(extras.items())
            for name, entry in described:
                if not isinstance(name, str) or not isinstance(entry, dict):
                    continue
                picture = entry.get("thumbnail", entry) if "thumbnail" in entry or "stl_sha256" in entry else {}
                box = entry.get("bounding_box_mm")
                size = ""
                if isinstance(box, list) and len(box) == 2:
                    size = " x ".join(f"{hi - lo:.0f}" for lo, hi in zip(box[0], box[1])) + " mm"
                info[name] = {"thumb": "./stl/" + picture["file"] if isinstance(picture.get("file"), str) else None,
                              "size": size, "note": str(entry.get("print_note", ""))}
            return {"present": True, "paths": sorted(set(found)), "served": [item["file"] for item in files],
                    "files": files, "info": info, "camera_default": default, "controller_default": home}
    return {"present": False, "paths": [], "served": [], "files": [], "info": {}, "camera_default": default,
            "controller_default": "unoq"}


def _collect_stl_names(node, found: list[str]) -> None:
    if isinstance(node, str):
        text = node.replace("\\", "/")
        if text.lower().endswith(".stl") and " " not in text:
            found.append(text[4:] if text.startswith("stl/") else text.lstrip("./"))
    elif isinstance(node, list):
        for item in node:
            _collect_stl_names(item, found)
    elif isinstance(node, dict):
        for key, value in node.items():
            _collect_stl_names(key, found)
            _collect_stl_names(value, found)


ENTRY_KEYS = ("status", "mass_g", "mass", "verdict", "stability", "stability_verdict")
NAME_KEYS = ("base", "controller", "locomotion", "type", "kind", "drive", "wheel_drive", "name", "id")


def variants(compat: dict, root: Path = ROOT) -> list[dict]:
    """Entries of the variants summary written by the walker and wheeled
    analysis, reduced to what the recipe shows. Empty until that file exists.
    """
    for name in SUMMARY_PATHS:
        path = root / name
        if path.is_file():
            entries: list[dict] = []
            _walk_summary(_load(path), [], compat, entries)
            return entries
    return []


def _walk_summary(node, hints: list[str], compat: dict, entries: list[dict]) -> None:
    if isinstance(node, list):
        for item in node:
            _walk_summary(item, hints, compat, entries)
    elif isinstance(node, dict):
        if any(key in node for key in ENTRY_KEYS):
            entry = _summary_entry(node, hints, compat)
            if entry:
                entries.append(entry)
            return
        for key, value in node.items():
            _walk_summary(value, hints + [str(key)], compat, entries)


def _summary_entry(node: dict, hints: list[str], compat: dict) -> dict | None:
    tokens: list[str] = []
    for text in hints + [node[key] for key in NAME_KEYS if isinstance(node.get(key), str)]:
        for part in str(text).lower().replace(":", "/").replace("__", "/").split("/"):
            tokens.append(part.strip())
    match = {}
    for dim, aliases in compat["summary_aliases"].items():
        # A field named after the dimension wins over hints from the path.
        named = str(node.get(dim, "")).lower()
        order = ([named] if named else []) + tokens
        for token in order:
            hit = [option for option, names in aliases.items() if token in names]
            if hit:
                match[dim] = hit[0]
                break
    if "controller" not in match or "locomotion" not in match:
        return None
    if "drive" not in match:
        # Without a drive the entry is used only where one drive is offered.
        rows = [row for row in compat["support"]
                if row["controller"] == match["controller"] and row["locomotion"] == match["locomotion"]]
        if len(rows) != 1:
            return None
        match["drive"] = rows[0]["drive"]
    options = {dim["id"]: [o["id"] for o in dim["options"]] for dim in compat["dimensions"]}
    for dim in ("wheels", "support", "wheel"):
        if node.get(dim) in options[dim]:
            match[dim] = node[dim]
    text = str(node.get("status", "")).strip()
    low = text.lower()
    if low in ("analysed", "analysed in simulation", "analyzed"):
        status = "analysed"
    elif low.startswith("defined"):
        status = "defined"
    else:
        status = "being_analysed"
    lines = []
    mass = node.get("mass_g", node.get("mass"))
    if isinstance(mass, dict):
        mass = mass.get("total_g")
    if isinstance(mass, (int, float)) and not isinstance(mass, bool):
        lines.append(f"Mass {mass:g} g by the model.")
    for key in ("stability_verdict", "stability", "verdict"):
        value = node.get(key)
        if isinstance(value, dict):
            value = value.get("verdict", value.get("text"))
        if isinstance(value, str) and value.strip():
            lines.append(f"Stability: {value.strip()}")
            break
    if isinstance(node.get("drive_summary"), str):
        lines.append(f"Drive: {node['drive_summary'].strip()}")
    for key in ("lines", "notes", "findings"):
        if isinstance(node.get(key), list):
            lines.extend(str(item) for item in node[key] if isinstance(item, str))
    files = []
    for item in node.get("files", []) if isinstance(node.get("files"), list) else []:
        if isinstance(item, str):
            item = {"file": item}
        name = str(item.get("file", item.get("name", ""))).replace("\\", "/")
        if name.lower().endswith(".stl"):
            qty = item.get("qty", 1)
            files.append({"file": name, "qty": qty if isinstance(qty, int) else 1,
                          "role": str(item.get("role", "from the variants summary")),
                          "fit": bool(item.get("fit", name.rsplit("/", 1)[-1].startswith("fit")))})
    parts = []
    for item in node.get("parts", []) if isinstance(node.get("parts"), list) else []:
        if isinstance(item, str):
            item = {"name": item}
        if item.get("name"):
            qty = item.get("qty")
            parts.append({"name": str(item["name"]), "qty": qty if isinstance(qty, int) else None,
                          "note": str(item.get("note", "from the variants summary"))})
    return {"match": match, "status": status, "status_text": text or "not stated", "lines": lines,
            "files": files, "parts": parts}


def bundle(root: Path = ROOT) -> dict:
    """Everything evaluate() needs, as one JSON-serialisable object. The site
    build writes this to site/data/recipe.json for site/build.js."""
    compat = _load(root / "config" / "compat.json")
    # One switch: the default camera is config/assembly.json camera.preset.
    compat["defaults"]["camera"] = camera_default(compat, root)
    listing = manifest(compat, root)
    return {
        "compat": compat,
        "bases": _load(root / "config" / "bases.json"),
        "facts": facts(root),
        "coverage": coverage(compat, listing, root),
        "manifest": listing,
        "variants": variants(compat, root),
    }


# --- evaluator (mirrored in site/build.js) ----------------------------------

def normalise(compat: dict, selection: dict) -> dict:
    sel = {}
    for dim in compat["dimensions"]:
        value = selection.get(dim["id"])
        ids = [option["id"] for option in dim["options"]]
        sel[dim["id"]] = value if value in ids else compat["defaults"][dim["id"]]
    for dim in compat["dimensions"]:
        if "only_for" in dim and not _matches(dim["only_for"], sel):
            sel[dim["id"]] = compat["defaults"][dim["id"]]
    return sel


def _matches(when: dict, sel: dict) -> bool:
    return all(sel[key] in allowed for key, allowed in when.items())


def _label(compat: dict, dim_id: str, option_id: str) -> str:
    for dim in compat["dimensions"]:
        if dim["id"] == dim_id:
            for option in dim["options"]:
                if option["id"] == option_id:
                    return option["label"]
    return option_id


def query(compat: dict, sel: dict) -> str:
    parts = []
    for dim in compat["dimensions"]:
        if "only_for" in dim and not _matches(dim["only_for"], sel):
            continue
        parts.append(dim["id"] + "=" + sel[dim["id"]])
    return "&".join(parts)


def _amps(ma: int) -> str:
    return f"{ma // 1000}.{(ma % 1000) // 10:02d}"


def _fill(text: str, values: dict) -> str:
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def _find_row(compat: dict, sel: dict):
    for row in compat["support"]:
        if all(row[key] == sel[key] for key in ("controller", "locomotion", "drive")):
            return row
    return None


def _find_variant(entries: list, sel: dict):
    best = None
    for entry in entries:
        match = entry["match"]
        if all(sel[key] == value for key, value in match.items()):
            if best is None or len(match) > len(best["match"]):
                best = entry
    return best


def _why_not(compat: dict, sel: dict):
    rows = [row for row in compat["support"] if row["controller"] == sel["controller"]]
    offered = "; ".join(_label(compat, "locomotion", row["locomotion"]) + " through " + _label(compat, "drive", row["drive"])
                        for row in rows)
    reasons = [_label(compat, "controller", sel["controller"]) + " is not offered as '"
               + _label(compat, "locomotion", sel["locomotion"]) + "' through '"
               + _label(compat, "drive", sel["drive"]) + "'. Offered for this controller: " + offered + "."]
    for item in compat["why_not"]:
        if _matches(item["when"], sel):
            reasons.append(item["reason"])
    return reasons, rows


def _unsupported(data: dict, sel: dict) -> dict:
    compat = data["compat"]
    reasons, rows = _why_not(compat, sel)
    # A controller the reports only carried on the biped as a block: say so, as a note.
    reported = any(row["status"] == "report" and row["locomotion"] == sel["locomotion"] for row in compat["support"])
    if reported and sel["controller"] in data["coverage"]["carried"]:
        reasons.append(data["coverage"]["carried"][sel["controller"]])
    pick = None
    for row in rows:
        if row["locomotion"] == sel["locomotion"]:
            pick = row
            break
    if pick is None:
        for row in rows:
            if row["drive"] == sel["drive"]:
                pick = row
                break
    if pick is None:
        pick = rows[0]
    return {"reasons": reasons, "nearest": {"locomotion": pick["locomotion"], "drive": pick["drive"]}}


def _pass(data: dict, sel: dict) -> dict:
    """One evaluation of a normalised selection, without the nearest search."""
    compat = data["compat"]
    row = _find_row(compat, sel)
    if row is None:
        blocked = _unsupported(data, sel)
        return {"blocked": True, "reasons": blocked["reasons"], "nearest": blocked["nearest"]}
    matched = [rule for rule in compat["rules"] if _matches(rule["when"], sel)]
    blocks = [rule for rule in matched if "block" in rule]
    if blocks:
        nearest = {}
        for rule in blocks:
            nearest.update(rule["nearest"])
        return {"blocked": True, "reasons": [rule["block"] for rule in blocks], "nearest": nearest}

    variant = None
    reasons = [row["reason"]]
    lead = []
    if row["status"] == "summary":
        variant = _find_variant(data["variants"], sel)
        if variant is None:
            status = "being_analysed"
            reasons.append("No analysis summary exists in reports/ yet for this base and locomotion.")
            lead.append("Being analysed: no summary file exists in reports/ yet. No mass, stability or speed figure is given here.")
        else:
            status = variant["status"]
            lead.append("From the variants summary in reports/, status as written there: " + variant["status_text"] + ".")
            lead.extend(variant["lines"])
            if status != "analysed":
                lead.append("Not analysed to a verdict yet: the summary does not report this variant as analysed.")
    elif row["status"] == "report":
        covered = None
        for entry in data["coverage"]["entries"]:
            if all(sel[key] == value for key, value in entry["match"].items()):
                covered = entry
                break
        if covered is None:
            status = "defined"
            lead.append("Not analysed: the reports do not cover this controller, camera and head together.")
        else:
            status = covered["status"]
            lead.extend(covered["lines"])
    else:
        status = row["status"]
        lead.append("Not analysed: no simulation or digital assembly exists for this selection.")
    sections = {name: [] for name in compat["sections"]}
    sections["analysis"].extend(lead)
    settings = {"mechanism": "", "preset": ""}
    rails = {}
    loads = []
    for rule in matched:
        if rule.get("downgrade") and status in ("analysed", "assembly_only"):
            status = "defined"
        if "reason" in rule:
            reasons.append(rule["reason"])
        for key, value in rule.get("set", {}).items():
            settings[key] = value
        for key, value in rule.get("rails", {}).items():
            if key not in rails:
                rails[key] = value
        loads.extend(rule.get("loads", []))
        for name, items in rule.get("add", {}).items():
            sections[name].extend(items)
    if variant is not None:
        sections["print"].extend(variant["files"])
        sections["parts"].extend(variant["parts"])

    # Supply sizing, one line per rail in order of first use.
    sizing = []
    order = []
    for load in loads:
        if load["rail"] not in order:
            order.append(load["rail"])
    for rail_id in order:
        rail = rails[rail_id]
        mine = [load for load in loads if load["rail"] == rail_id]
        known = [load for load in mine if load["stall_ma"] is not None]
        unknown = [load for load in mine if load["stall_ma"] is None]
        total = sum(load["qty"] * load["stall_ma"] for load in known)
        line = rail["label"] + ": "
        if known:
            terms = " + ".join(f"{load['qty']} x {_amps(load['stall_ma'])} A {load['what']}, {load['basis']}" for load in known)
            line += "stalled demand " + _amps(total) + " A (" + terms + ")."
        else:
            line += "stalled demand not known."
        if unknown:
            line += " Not counted, stall current " + "; ".join(
                f"{load['basis']}: {load['qty']} x {load['what']}" for load in unknown) + "."
        if rail["limit_ma"] is not None and known:
            if total > rail["limit_ma"]:
                tenths = total * 10 // rail["limit_ma"]
                line += (f" That is {tenths // 10}.{tenths % 10} times the {rail['limit_label']}, "
                         f"{_amps(rail['limit_ma'])} A: size the supply and wiring for the stall figure, or fuse it.")
            else:
                line += f" Within the {rail['limit_label']}, {_amps(rail['limit_ma'])} A, on these figures."
        sizing.append(line)
    sections["power"] = sizing + sections["power"]

    # Files to print: fit-test pieces first, linked when the manifest has them.
    listing = data["manifest"]
    wanted = []
    no_torso = False
    for item in sections["print"]:
        if not item.get("from_manifest"):
            wanted.append(item)
            continue
        # The committed biped parts, chosen by the option fields the manifest gives each file.
        maps = compat["manifest_map"]
        controller = maps["controller"].get(sel["controller"])
        head = maps["head"].get(sel["head"])
        torsos = [entry for entry in listing["files"]
                  if entry["part"] == "torso" and entry["controller"] == controller and entry["head"] == head]
        known = [entry["camera"] for entry in listing["files"] if entry["camera"] is not None]
        own = False
        torso = None
        if head is None:
            # A fixed mount: the torso of the selected camera, or of the default camera when the
            # selection is not a camera the manifest knows (the mount is then left empty).
            own = sel["camera"] in [entry["camera"] for entry in torsos]
            camera = sel["camera"] if sel["camera"] in known else listing["camera_default"]
            for entry in torsos:
                if entry["camera"] == camera:
                    torso = entry["file"]
                    break
        elif torsos:
            torso = torsos[0]["file"]
        if torso is None:
            no_torso = True
        for entry in listing["files"]:
            general = entry["controller"] is None and entry["head"] is None
            if entry["part"] == "torso":
                take = entry["file"] == torso
            elif general and entry["camera"] is None:
                take = True                                   # legs and the fit pieces every build needs
            elif general and entry["fit"]:
                take = head is None and own and entry["camera"] == sel["camera"]
            elif entry["head"] is not None and entry["controller"] is None:
                take = entry["head"] == head and (entry["camera"] is None or entry["camera"] == sel["camera"])
            else:
                take = False
            if take:
                wanted.append({"file": entry["file"], "qty": 1, "role": entry["what"], "fit": entry["fit"]})
    if no_torso:
        if status in ("analysed", "assembly_only"):
            status = "defined"
        reasons.append("No torso file is committed for this controller with this camera and head. The design's generator "
                       "would have to be run for it (CONTROLLER, CAMERA and the head option in build.py), and that part has not been checked.")
    files = []
    for item in wanted:
        name = item["file"]
        if item.get("folder") and settings["preset"]:
            name = settings["preset"] + "/" + name
        link = None
        about = {"thumb": None, "size": "", "note": ""}
        for path in listing["paths"]:
            if path == name or path.endswith("/" + name):
                # Files the site build copies are linked on the site; others in the repository.
                link = "./stl/" + path if path in listing["served"] else compat["repo_blob"] + "stl/" + path
                about = listing["info"].get(path, about)
                break
        files.append({"file": name, "qty": item["qty"], "role": item["role"], "fit": bool(item.get("fit")),
                      "link": link, "thumb": about["thumb"], "size": about["size"], "note": about["note"]})
    files = [item for item in files if item["fit"]] + [item for item in files if not item["fit"]]
    if not files:
        note = "No printable files are named for this selection yet: the design is in progress on another branch."
    elif listing["present"]:
        note = "Linked files are in the repository's stl/ directory; none has been printed. A name without a link is not in its manifest."
    else:
        note = "File names only: the repository has no STL manifest, so nothing is linked."

    base = data["bases"]["bases"][row["base"]]
    values = data["facts"]
    out = {
        "blocked": False,
        "status": status,
        "reasons": [_fill(text, values) for text in reasons],
        "base": row["base"],
        "base_name": base["name"],
        "sources": base["sources"],
        "mechanism": settings["mechanism"],
        "preset": settings["preset"],
        "print": {"note": note, "files": files},
        "parts": sections["parts"],
    }
    for name in compat["sections"]:
        if name not in ("print", "parts"):
            out[name] = [_fill(text, values) for text in sections[name]]
    return out


def evaluate(data: dict, selection: dict) -> dict:
    """The recipe for a selection. Pure: the same data and selection always
    give the same recipe, and nothing outside the arguments is read."""
    compat = data["compat"]
    sel = normalise(compat, selection)
    first = _pass(data, sel)
    recipe = {
        "selection": sel,
        "labels": {dim["id"]: _label(compat, dim["id"], sel[dim["id"]]) for dim in compat["dimensions"]},
        "query": query(compat, sel),
        "not_built": compat["not_built"],
        "trademarks": compat["trademarks"],
    }
    if not first["blocked"]:
        recipe.update(first)
        del recipe["blocked"]
        recipe["status_label"] = compat["statuses"][recipe["status"]]["label"]
        recipe["headline"] = compat["statuses"][recipe["status"]]["headline"]
        recipe["nearest"] = None
        return recipe

    near = dict(sel)
    result = first
    for _ in range(MAX_NEAREST_STEPS):
        near.update(result["nearest"])
        near = normalise(compat, near)
        result = _pass(data, near)
        if not result["blocked"]:
            break
    if result["blocked"]:
        near = normalise(compat, compat["defaults"])
        result = _pass(data, near)
    changes = [dim["label"] + ": " + _label(compat, dim["id"], near[dim["id"]])
               for dim in compat["dimensions"] if near[dim["id"]] != sel[dim["id"]]]
    recipe.update({
        "status": "not_possible",
        "status_label": compat["statuses"]["not_possible"]["label"],
        "headline": compat["statuses"]["not_possible"]["headline"],
        "reasons": first["reasons"],
        "base": None, "base_name": "", "sources": [], "mechanism": "", "preset": "",
        "print": {"note": "Nothing to print: the selection is not possible.", "files": []},
        "parts": [],
        "nearest": {
            "selection": near,
            "query": query(compat, near),
            "status": result["status"],
            "status_label": compat["statuses"][result["status"]]["label"],
            "changes": changes,
        },
    })
    for name in compat["sections"]:
        if name not in ("print", "parts"):
            recipe[name] = []
    return recipe


def combinations(compat: dict):
    """Every distinct selection: the wheel choices vary only when wheeled."""
    dims = compat["dimensions"]
    seen = set()
    for values in product(*[[option["id"] for option in dim["options"]] for dim in dims]):
        sel = normalise(compat, dict(zip([dim["id"] for dim in dims], values)))
        key = tuple(sel[dim["id"]] for dim in dims)
        if key not in seen:
            seen.add(key)
            yield sel


def main(argv: list[str]) -> int:
    selection = dict(arg.split("=", 1) for arg in argv if "=" in arg)
    json.dump(evaluate(bundle(), selection), sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
