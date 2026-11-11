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
import re
import sys
from urllib.parse import quote
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PATHS = ("reports/variants/summary.json", "reports/lego/summary.json")
MANIFEST_PATHS = ("stl/manifest.json", "stl/MANIFEST.json")
PROGRAM_PATHS = ("programs/index.json",)
VALIDATED_PATH = "config/validated.json"
BUILDS_PATH = "config/builds.json"
COMPONENTS_PATH = "config/component_images.json"
SEARCH_DEPTH = 6


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


def design_defaults(compat: dict, root: Path = ROOT) -> dict:
    """The camera, face and feet the design is generated and analysed for by
    default: config/assembly.json, the one switch for the whole repository.
    A value this page does not offer falls back to the first option."""
    config = _load(root / "config" / "assembly.json")
    known = {dim["id"]: [option["id"] for option in dim["options"]] for dim in compat["dimensions"]}
    wanted = {"camera": (config.get("camera") or {}).get("preset"), "face": config.get("face"), "feet": config.get("feet")}
    return {key: value if value in known[key] else known[key][0] for key, value in wanted.items()}


def camera_default(compat: dict, root: Path = ROOT) -> str:
    return design_defaults(compat, root)["camera"]


def coverage(compat: dict, listing: dict, root: Path = ROOT) -> dict:
    """What the reports cover for the servo biped.

    'entries' are matched on controller, camera, head, face and feet:
    - the selected assembly variant (the default head, camera and feet on the
      UNO Q) was also simulated: 'analysed';
    - the other faces and camera presets, the other controllers' decks and
      the turning head went through the digital assembly only:
      'assembly_only'.
    Anything else is not covered and the recipe says so.

    'carried' holds the controllers the reports only placed on the deck as a
    block for a balance figure, with no supported way to drive the servos:
    a note for the "not possible" answer, never a tag.
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
    feet = assembly.get("feet_preset") or compat["defaults"]["feet"]
    faces = assembly.get("faces", {})
    first = faces.get(assembly.get("face_default"), {})
    face = first.get("face", "none")
    by_file = {entry["file"]: entry for entry in listing["files"]}
    entries = []
    done = set()

    def add(controller, cam, head, face_id, status, lines):
        key = (controller, cam, head, face_id)
        if key in done or cam is None:
            return
        done.add(key)
        entries.append({"match": {"controller": controller, "camera": cam, "head": head, "face": face_id, "feet": feet},
                        "status": status, "lines": lines})

    def balance(item):
        return (f"total mass {item['total_g']:g} g, centre of mass {item['stand_margin_mm']:g} mm inside the support polygon "
                f"at the stand pose (thighs {item['stand_thigh_swing_deg']:g} degrees back)")

    simulated = camera.get("name", "default camera")
    used = "The simulation, the joint sweeps and the full findings list used the default head and camera."
    if camera.get("preset") and home in own:
        overlaps = rep.get("neutral_interferences", [])
        add(own[home], camera["preset"], fixed, face, "analysed", [
            f"Simulated with the {camera['name']}, the default head and feet, and the pin holes and studs on the parts.",
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
        ])
    if home in own:
        for item in faces.values():
            where = {"eyes_above": "above", "eyes_below": "below"}.get(item["face"], "beside")
            add(own[home], item["camera_preset"], fixed, item["face"], "assembly_only", [
                f"Digital assembly with the round display as the eyes and the {item['camera_preset']} camera {where} it: "
                f"{balance(item)}, lens {item['lens_height_above_floor_at_stand_mm']:g} mm above the floor.", used])
        stack = assembly.get("stack_camera_forward")
        stack_torso = [entry for entry in listing["files"] if entry["part"] == "torso" and entry.get("face") == "stack_camera_forward"]
        if stack and stack_torso:
            add(own[home], stack_torso[0]["camera"], fixed, "stack_camera_forward", "assembly_only", [
                f"Digital assembly with the display stack and its camera facing forward: {balance(stack)}, "
                f"lens {stack['lens_height_above_floor_at_stand_mm']:g} mm above the floor.", used])
        for short in assembly.get("camera_presets", {}).values():
            cone = "clear" if not short["cone_blocked_at_neutral"] and not short["cone_blocked_at_stand"] else "not clear"
            add(own[home], short["preset"], fixed, "none", "assembly_only", [
                f"Digital assembly in short form with the {short['name']} alone in the fixed mount: {balance(short)}, "
                f"{short['clearance_each_side_mm']:g} mm each side in the mount, view cone {cone} at the neutral and stand poses.", used])
    report_name = compat["report_controller"]
    carried = {}
    for controller, name in report_name.items():
        block = assembly.get("controllers", {}).get(name)
        if block is None:
            continue
        figures = (f"{block['name']}, taken as one block of {block['mass_g']:g} g: {balance(block)}, holding torque "
                   f"{round(block['hip_pitch_torque_fraction'] * 100)} percent of the hip pitch servo limit")
        supported = any(row["controller"] == controller and row["status"] == "report" for row in compat["support"])
        torso = by_file.get(block.get("torso_file"))
        if supported and block.get("has_its_own_torso") and torso is not None:
            clear = "no parts overlap at the neutral pose" if not block["neutral_interferences"] else "parts overlap at the neutral pose"
            add(controller, torso["camera"], fixed, torso.get("face") or "none", "assembly_only", [
                f"Digital assembly, fit and static balance only, with the {figures}; {clear}.",
                f"The simulation and the joint sweeps used the UNO Q torso with the {simulated}."])
        elif not supported:
            carried[controller] = (f"Balance of the servo biped carrying it as a block: {figures}. "
                                   "That is a figure for carrying it; it does not drive the servos.")
    heads = [assembly["turning_head"]] if assembly.get("turning_head") else []
    heads += list(assembly.get("turning_head_with_faces", {}).values())
    for head in heads if home in own else []:
        travel = head["pan_travel_to_the_stops_deg"]
        tilt = head["tilt_free_deg"]
        margins = [pose["stand_margin_mm"] for pose in head["at_the_stand_pose"]]
        clear = "no parts overlap at the neutral pose" if not head["neutral_interferences"] else "parts overlap at the neutral pose"
        lines = [
            f"Digital assembly of the turning head with the {head['camera_preset']} cradle, pan only: {travel[0]:g} to {travel[1]:g} degrees "
            f"between the printed stops, {clear}, total mass {head['total_g']:g} g, "
            f"centre of mass {min(margins):g} to {max(margins):g} mm inside the support polygon at the stand pose across the pan travel.",
            f"Tilt is set by hand: the cradle is free from {tilt[0]:g} to {tilt[1]:g} degrees about its screw and was checked at "
            f"{head['tilt_set_to_deg']:g} degrees.",
            "The head has no joint in the robot description, the simulation or the command format.",
        ]
        for option, name in compat["manifest_map"]["head"].items():
            if name == "pan":
                add(own[home], head["camera_preset"], option, head.get("face") or "none", "assembly_only", lines)
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
                    # A torso or a head cradle without these options is the default controller's fixed mount.
                    body = part in ("torso", "head_cradle")
                    files.append({"file": entry["file"], "what": str(entry.get("what", "")),
                                  "fit": bool(options.get("fit_piece")), "part": part,
                                  "controller": options.get("controller", home if part == "torso" else None),
                                  "head": options.get("head", "fixed" if part == "torso" else None),
                                  "camera": options.get("camera"),
                                  "face": options.get("face", "none" if body else None),
                                  "display": options.get("display"), "feet": options.get("feet"),
                                  "locomotion": options.get("locomotion")})
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
                              "size": size, "note": str(entry.get("print_note") or entry.get("material") or "")}
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
            return entries + _idler_entries(compat, entries)
    return []


def _idler_entries(compat: dict, entries: list[dict]) -> list[dict]:
    """The printed idler is a third support the summary names in its notes
    only. Each roller entry gives an idler entry: the same build with the
    ball tip swapped for the idler parts, tagged Designed, with no numbers
    of its own."""
    swap = compat.get("idler", {})
    if not swap:
        return []
    out = []
    for entry in entries:
        if entry["match"].get("support") != swap["from"]:
            continue
        files = [item for item in entry["files"] if not any(item["file"].endswith(name) or name in item["file"] for name in swap["drop"])]
        files += [dict(item) for item in swap["files"]]
        parts = [item for item in entry["parts"] if not any(word in item["name"].lower() for word in swap["drop_parts"])]
        # The advice carries over; the figures, which are the ball's, do not.
        advice = [line for line in entry["lines"] if not any(ch.isdigit() for ch in line)]
        out.append({"match": dict(entry["match"], support=swap["to"]), "status": "defined", "status_text": "designed",
                    "lines": [swap["line"]] + advice, "files": files, "parts": parts})
    return out


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


def programs(compat: dict, root: Path = ROOT) -> list[dict]:
    """The program files of programs/index.json, one entry per file, with the
    lines a recipe shows for it. Its shape: {"programs": [{"controller",
    "locomotion", "drive", "language", "file", "ports", "what", "load_with":
    {"name", "url", "code_target"}, "alternative"}]}. The site serves each
    file at <site>/programs/<controller>/<build>/<file>.py, which is the
    address Robot Creator's program link needs."""
    for name in PROGRAM_PATHS:
        path = root / name
        if not path.is_file():
            continue
        content = _load(path)
        listed = content.get("programs", []) if isinstance(content, dict) else []
        known = {dim["id"]: [option["id"] for option in dim["options"]] for dim in compat["dimensions"]}
        out = []
        for item in listed:
            if not isinstance(item, dict) or item.get("controller") not in known["controller"]:
                continue
            file = str(item.get("file", "")).replace("\\", "/")
            if not re.fullmatch(r"programs/[a-z0-9_/-]+\.py", file) or not (root / file).is_file():
                continue
            match = {key: item[key] for key in ("controller", "locomotion", "drive") if item.get(key) in known[key]}
            address = compat["site_url"] + file
            lines = [f"Program, {item.get('language', 'Python')}: {address} {str(item.get('what', '')).strip()}".strip()]
            ports = item.get("ports")
            if isinstance(ports, dict) and ports:
                lines.append("Ports: " + "; ".join(f"{key}: {value}" for key, value in ports.items()) + ".")
            load = item.get("load_with")
            target = load.get("code_target") if isinstance(load, dict) else None
            if target in compat["program_targets"]:
                lines.append("Open it in Robot Creator: " + compat["robot_creator"] + "?program=" + quote(address, safe="")
                             + "&target=" + target + " . If the program is not shown there, download the file above and load it from Robot Creator's file or paste box.")
                lines.append(compat["program_targets"][target])
            if isinstance(item.get("alternative"), str) and item["alternative"].strip():
                lines.append(("Without Robot Creator: " if target in compat["program_targets"] else "To run it: ") + item["alternative"].strip())
            out.append({"match": match, "file": file, "lines": lines})
        return out
    return []


def validated(root: Path = ROOT) -> list[dict]:
    """The owner's own checks of printed builds and parts, from
    config/validated.json. Empty until he records one."""
    path = root / VALIDATED_PATH
    if not path.is_file():
        return []
    content = _load(path)
    records = content.get("records", []) if isinstance(content, dict) else content
    out = []
    for record in records if isinstance(records, list) else []:
        if isinstance(record, dict) and isinstance(record.get("id"), str) and isinstance(record.get("date"), str):
            out.append({"id": record["id"], "part": str(record.get("part") or ""), "date": record["date"],
                        "checked": str(record.get("checked", "")), "photo": str(record.get("photo") or ""),
                        "mark": record.get("mark", True) is True})
    return out


def summary_entry(sel: dict, root: Path = ROOT):
    """The entry of the variants summary for a selection, as written there,
    or None. Wheeled entries are also matched on the wheel choices."""
    for name in SUMMARY_PATHS:
        path = root / name
        if not path.is_file():
            continue
        content = _load(path)
        for entry in content.get("entries", []) if isinstance(content, dict) else []:
            keys = ["controller", "locomotion", "drive"] + [key for key in ("wheels", "support", "wheel") if key in entry]
            if all(entry.get(key) == sel[key] for key in keys):
                return entry
    return None


def build_figures(data: dict, sel: dict, root: Path = ROOT) -> dict:
    """Mass and speed of a finished build for its card, from the reports:
    the variants summary for a walker or a wheeled build, the assembly and
    simulation reports for the biped. Empty when the reports have none."""
    row = _find_row(data["compat"], sel)
    out = {}
    if row is not None and row["status"] == "summary":
        entry = summary_entry(sel, root) or {}
        if isinstance(entry.get("mass_g"), (int, float)):
            out["mass_g"] = entry["mass_g"]
        if isinstance(entry.get("speed_mm_s"), (int, float)):
            out["speed_mm_s"] = entry["speed_mm_s"]
        elif isinstance(entry.get("speed_m_s"), (int, float)):
            out["speed_mm_s"] = round(entry["speed_m_s"] * 1000.0, 1)
    elif row is not None and row["status"] == "report":
        assembly = _load(root / "reports" / "assembly.json")
        sim = _load(root / "reports" / "sim.json")
        out["mass_g"] = assembly["variants"][assembly["selected"]]["mass"]["total_g"]
        speed = (sim.get("gait_best") or sim.get("gait_default") or {}).get("speed_mm_s")
        if isinstance(speed, (int, float)):
            out["speed_mm_s"] = speed
    return out


def builds(data: dict, root: Path = ROOT) -> dict:
    """The finished builds offered as cards at the top of the landing page,
    from config/builds.json, in their order, each with its figures."""
    path = root / BUILDS_PATH
    if not path.is_file():
        return {"default": "", "list": []}
    content = _load(path)
    listed = sorted(content.get("builds", []), key=lambda item: item.get("order", 0))
    out = []
    for item in listed:
        entry = {"id": item["id"], "name": item["name"], "description": item["description"],
                 "selection": dict(item["selection"]), "picture": item["picture"]}
        entry["figures"] = build_figures(data, build_selection(data, entry), root)
        out.append(entry)
    default = content.get("default")
    ids = [item["id"] for item in out]
    return {"default": default if default in ids else (ids[0] if ids else ""), "list": out}


def credit_line(entry: dict) -> str:
    """One plain line of credit for a component picture, as the PDF and the
    credits page give it. A picture this project renders needs none."""
    if entry.get("kind") == "photo":
        parts = [f"{entry['name']}: photograph by {entry.get('author', '')}", entry.get("licence", ""), entry.get("origin", "")]
        if entry.get("source_url"):
            parts.append(entry["source_url"])
        if entry.get("changes"):
            parts.append(entry["changes"])
        return ", ".join(part for part in parts if part) + "."
    if entry.get("kind") == "drawing":
        return f"{entry['name']}: {entry.get('origin', 'drawing')}; not a photograph."
    return ""


def components(data: dict, root: Path = ROOT) -> dict:
    """The pictures of the bought components and of every choice in the
    configurator, from config/component_images.json: 'list' in the order
    parts are matched, each with the address of its picture on the site,
    and 'options', the component of each choice."""
    path = root / COMPONENTS_PATH
    if not path.is_file():
        return {"list": [], "options": {}, "not_bought": []}
    content = _load(path)
    listing = data["manifest"]
    pictures = {item["id"]: item["picture"] for item in data.get("builds", {}).get("list", [])}
    out = []
    for entry in content.get("components", []):
        picture = None
        if entry.get("file"):
            picture = "./components/" + entry["file"]
        elif entry.get("stl"):
            picture = listing["info"].get(entry["stl"], {}).get("thumb")
        elif entry.get("manifest"):
            for item in listing["files"]:
                if all(item.get(key) == value for key, value in entry["manifest"].items()):
                    picture = listing["info"].get(item["file"], {}).get("thumb")
                    break
        elif entry.get("build") in pictures:
            picture = "./" + pictures[entry["build"]]
        credit = ""
        if entry.get("kind") == "photo":
            credit = f"Photo: {entry.get('author', '')}, {entry.get('licence', '')}"
        elif entry.get("kind") == "drawing":
            credit = "Drawing"
        out.append({"id": entry["id"], "name": entry["name"], "kind": entry.get("kind", ""), "picture": picture,
                    "credit": credit, "credit_line": credit_line(entry), "match": list(entry.get("match", []))})
    return {"list": out, "options": content.get("options", {}), "not_bought": list(content.get("not_bought", []))}


def component_for(data: dict, name: str):
    """The component whose picture a part of a recipe takes: the first in
    the list with one of its patterns in the part's name. None for a part
    with no picture (a printed part named in the parts list)."""
    low = name.lower()
    if any(low.startswith(prefix) for prefix in data["components"]["not_bought"]):
        return None
    for entry in data["components"]["list"]:
        if any(pattern in low for pattern in entry["match"]):
            return entry
    return None


def bundle(root: Path = ROOT) -> dict:
    """Everything evaluate() needs, as one JSON-serialisable object. The site
    build writes this to site/data/recipe.json for site/build.js."""
    data = _bundle(root)
    data["builds"] = builds(data, root)
    data["components"] = components(data, root)
    return data


def _bundle(root: Path) -> dict:
    compat = _load(root / "config" / "compat.json")
    # One switch: the default camera is config/assembly.json camera.preset.
    compat["defaults"].update(design_defaults(compat, root))
    listing = manifest(compat, root)
    return {
        "compat": compat,
        "bases": _load(root / "config" / "bases.json"),
        "facts": facts(root),
        "coverage": coverage(compat, listing, root),
        "manifest": listing,
        "variants": variants(compat, root),
        "programs": programs(compat, root),
        "validated": validated(root),
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


def build_id(sel: dict) -> str:
    """The id of a build: one row of the support table."""
    return sel["controller"] + "-" + sel["locomotion"] + "-" + sel["drive"]


def _find_row(compat: dict, sel: dict):
    for row in compat["support"]:
        if all(row[key] == sel[key] for key in ("controller", "locomotion", "drive")):
            return row
    return None


def _most_specific(entries: list, sel: dict):
    best = None
    for entry in entries:
        match = entry["match"]
        if all(sel[key] == value for key, value in match.items()):
            if best is None or len(match) > len(best["match"]):
                best = entry
    return best


def _unsupported(data: dict, sel: dict) -> dict:
    compat = data["compat"]
    rows = [row for row in compat["support"] if row["controller"] == sel["controller"]]
    matched = [item for item in compat["why_not"] if _matches(item["when"], sel)]
    reasons = [item["reason"] for item in matched]
    # A controller the reports only carried on the biped as a block: say so, as a note.
    reported = any(row["status"] == "report" and row["locomotion"] == sel["locomotion"] for row in compat["support"])
    if reported and sel["controller"] in data["coverage"]["carried"]:
        reasons.append(data["coverage"]["carried"][sel["controller"]])
    reasons.append("With this controller: " + "; ".join(
        _label(compat, "locomotion", row["locomotion"]) + " through " + _label(compat, "drive", row["drive"]) for row in rows) + ".")
    # The rows this controller does have, nearest first: same locomotion, then same drive, then the rest.
    order = ([row for row in rows if row["locomotion"] == sel["locomotion"]]
             + [row for row in rows if row["locomotion"] != sel["locomotion"] and row["drive"] == sel["drive"]]
             + [row for row in rows if row["locomotion"] != sel["locomotion"] and row["drive"] != sel["drive"]])
    return {"blocked": True, "reasons": reasons,
            "alternatives": [{"locomotion": row["locomotion"], "drive": row["drive"]} for row in order],
            "codes": [item["code"] for item in matched] or ["not-offered"],
            "short": matched[0]["short"] if matched else "Not available with this controller",
            "details": [{"dims": list(item["when"]), "short": item["short"]} for item in matched],
            "needs": bool(matched) and all(item.get("needs") for item in matched)}


def _refusal(data: dict, sel: dict):
    """Why a normalised selection is refused, or None if it is possible.
    Cheap: the search for a neighbour calls it for every candidate."""
    compat = data["compat"]
    if _find_row(compat, sel) is None:
        return _unsupported(data, sel)
    blocks = [rule for rule in compat["rules"] if "block" in rule and _matches(rule["when"], sel)]
    if blocks:
        alternatives = []
        for rule in blocks:
            alternatives.extend(rule["alternatives"])
        return {"blocked": True, "reasons": [rule["block"] for rule in blocks], "alternatives": alternatives,
                "codes": [rule["code"] for rule in blocks], "short": blocks[0]["short"],
                "details": [{"dims": list(rule["when"]), "short": rule["short"]} for rule in blocks],
                "needs": all(rule.get("needs") for rule in blocks)}
    return None


def _pass(data: dict, sel: dict) -> dict:
    """One evaluation of a normalised selection, without the search for a
    possible neighbour."""
    compat = data["compat"]
    refused = _refusal(data, sel)
    if refused is not None:
        return refused
    row = _find_row(compat, sel)
    matched = [rule for rule in compat["rules"] if _matches(rule["when"], sel)]

    variant = None
    reasons = [row["reason"]]
    lead = []
    if row["status"] == "summary":
        variant = _most_specific(data["variants"], sel)
        if variant is None:
            status = "being_analysed"
            lead.append("In analysis: mass, stability and speed appear here when the summary is ready.")
        else:
            status = variant["status"]
            lead.append("From the variants summary, status as written there: " + variant["status_text"] + ".")
            lead.extend(variant["lines"])
    elif row["status"] == "report":
        covered = None
        for entry in data["coverage"]["entries"]:
            if all(sel[key] == value for key, value in entry["match"].items()):
                covered = entry
                break
        if covered is None:
            status = "defined"
            lead.append("No analysis numbers for this controller, camera and head together.")
        else:
            status = covered["status"]
            lead.extend(covered["lines"])
    else:
        status = row["status"]
        lead.append("No analysis numbers for this selection.")
    written = [entry for entry in data["programs"] if all(sel[key] == value for key, value in entry["match"].items())]
    program = written[0] if written else None
    sections = {name: [] for name in compat["sections"]}
    sections["analysis"].extend(lead)
    for entry in written:
        sections["firmware"].extend(entry["lines"])
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
            # A summary entry lists the whole build; the rules then add only what it does not
            # know about (the camera and head chosen here).
            if variant is not None and name in ("print", "parts") and not rule.get("extra"):
                continue
            sections[name].extend(items)
        if program is None:
            for name, items in rule.get("without_program", {}).items():
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
            terms = " + ".join(f"{load['qty']} x {_amps(load['stall_ma'])} A {load['what']}" for load in known)
            line += "stalled demand " + _amps(total) + " A (" + terms + ")."
        else:
            line += "size it for the stall current of what it feeds."
        if unknown:
            line += " Add the stall current of: " + "; ".join(f"{load['qty']} x {load['what']}" for load in unknown) + "."
        if rail["limit_ma"] is not None and known:
            if total > rail["limit_ma"]:
                tenths = total * 10 // rail["limit_ma"]
                line += (f" That is {tenths // 10}.{tenths % 10} times the {rail['limit_label']}, "
                         f"{_amps(rail['limit_ma'])} A: size the supply and wiring for the stall figure, or fuse it.")
            else:
                line += f" Within the {rail['limit_label']}, {_amps(rail['limit_ma'])} A."
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
        # The committed biped parts, chosen by the option fields the manifest gives each file:
        # controller, head, face, camera and feet. Its own files have no locomotion option.
        maps = compat["manifest_map"]
        controller = maps["controller"].get(sel["controller"])
        head = maps["head"].get(sel["head"], compat["defaults"]["head"])
        own_files = [entry for entry in listing["files"] if entry["locomotion"] is None]
        known = [entry["camera"] for entry in own_files if entry["part"] == "torso" and entry["camera"] not in (None, "any")]
        # A selection that is not a camera a torso is made for leaves the mount empty: the default camera's torso.
        camera = sel["camera"] if sel["camera"] in known else listing["camera_default"]
        torso = None
        for entry in own_files:
            if (entry["part"] == "torso" and entry["controller"] == controller and entry["head"] == head
                    and entry["face"] in (sel["face"], "any") and entry["camera"] in (camera, "any")):
                torso = entry
                break
        if torso is None:
            no_torso = True
        # The display a fit piece is for: the one in the torso, or in the cradle of a turning head.
        cradle = [entry for entry in own_files if entry["part"] == "head_cradle" and entry["head"] == head
                  and entry["controller"] is None and entry["face"] == sel["face"] and entry["camera"] == sel["camera"]]
        display = cradle[0]["display"] if cradle else (torso["display"] if torso is not None else None)
        for entry in own_files:
            if entry["part"] == "torso":
                take = torso is not None and entry["file"] == torso["file"]
            elif entry["part"] == "camera_plate":
                take = False                                  # named by the camera's own rule
            elif entry["feet"] is not None:
                take = entry["feet"] == sel["feet"]
            elif entry["controller"] is not None:
                take = False                                  # another body's part (a walker's head or chassis)
            elif entry["head"] is not None:
                # Parts of the turning head: the platform, its fit piece, and the cradle of this face and camera.
                take = entry["head"] == head and (entry["part"] != "head_cradle"
                                                  or (entry["face"] == sel["face"] and entry["camera"] == sel["camera"]))
            elif entry["display"] is not None:
                take = display == entry["display"]
            elif entry["camera"] is not None:
                take = entry["fit"] and head == compat["defaults"]["head"] and torso is not None and entry["camera"] == sel["camera"] == torso["camera"]
            else:
                take = True                                   # the legs and the fit pieces every build needs
            if take:
                wanted.append({"file": entry["file"], "qty": 1, "role": entry["what"], "fit": entry["fit"]})
    if no_torso:
        if status in ("analysed", "assembly_only"):
            status = "defined"
        reasons.append("No torso file is in stl/ for this controller with this camera and head. The design's generator "
                       "makes one (CONTROLLER, CAMERA and the head option in build.py).")
    marks = {record["part"]: record["date"] for record in data["validated"] if record["part"] and record["mark"]}
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
                      "link": link, "thumb": about["thumb"], "size": about["size"], "note": about["note"],
                      "validated": marks.get(name, "")})
    files = [item for item in files if item["fit"]] + [item for item in files if not item["fit"]]
    if not files:
        note = "No printable files are in stl/ for this selection yet."
    elif listing["present"]:
        note = "Linked files are in the repository's stl/ directory. A name without a link is not there yet."
    else:
        note = "File names only."

    base = data["bases"]["bases"][row["base"]]
    values = dict(data["facts"], robot_creator=compat["robot_creator"])
    mark = None
    for record in data["validated"]:
        if record["id"] == build_id(sel) and not record["part"] and record["mark"]:
            mark = {"date": record["date"], "checked": record["checked"], "photo": record["photo"]}
    out = {
        "blocked": False,
        "status": status,
        "reasons": [_fill(text, values) for text in reasons],
        "base": row["base"],
        "build": build_id(sel),
        "validated": mark,
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


def search(data: dict, selection: dict, pinned: list) -> dict | None:
    """The nearest possible selection, keeping the pinned choices as they
    are: follow the alternatives each block offers, depth first, and stop at
    the first selection that is not blocked. None if the pinned choices
    cannot be part of any possible selection."""
    compat = data["compat"]
    start = normalise(compat, selection)
    order = [dim["id"] for dim in compat["dimensions"]]
    seen = set()

    def walk(current: dict, depth: int):
        result = _refusal(data, current)
        if result is None:
            return current
        if depth == 0:
            return None
        for alternative in result["alternatives"]:
            if any(key in pinned and start[key] != value for key, value in alternative.items()):
                continue
            merged = dict(current)
            merged.update(alternative)
            following = normalise(compat, merged)
            key = "|".join(following[name] for name in order)
            if key in seen:
                continue
            seen.add(key)
            found = walk(following, depth - 1)
            if found is not None:
                return found
        return None

    return walk(start, SEARCH_DEPTH)


def build_selection(data: dict, entry: dict) -> dict:
    """The full selection of a finished build: the fields its entry names
    are kept, the rest take the defaults and then compatible values."""
    start = normalise(data["compat"], entry["selection"])
    found = search(data, start, list(entry["selection"]))
    return start if found is None else found


def option_state(data: dict, selection: dict, dim_id: str, option_id: str) -> dict:
    """Whether an option can be chosen with the current controller, and what
    the selection becomes if it is. Not possible: the short reason."""
    candidate = dict(normalise(data["compat"], selection))
    candidate[dim_id] = option_id
    found = search(data, candidate, ["controller", dim_id])
    if found is not None:
        return {"enabled": True, "selection": found, "short": ""}
    result = _pass(data, normalise(data["compat"], candidate))
    about = [item["short"] for item in result["details"] if dim_id in item["dims"]]
    return {"enabled": False, "selection": None, "short": about[0] if about else result["short"]}


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
        "trademarks": compat["trademarks"],
    }
    if not first["blocked"]:
        recipe.update(first)
        del recipe["blocked"]
        recipe["status_label"] = compat["statuses"][recipe["status"]]["label"]
        recipe["headline"] = compat["statuses"][recipe["status"]]["headline"]
        recipe["refusal"] = []
        recipe["nearest"] = None
        return recipe

    near = search(data, sel, ["controller"])
    if near is None:
        near = search(data, sel, [])
    if near is None:
        near = normalise(compat, compat["defaults"])
    result = _pass(data, near)
    status = "needs_part" if first["needs"] else "not_possible"
    changes = [dim["label"] + ": " + _label(compat, dim["id"], near[dim["id"]])
               for dim in compat["dimensions"] if near[dim["id"]] != sel[dim["id"]]]
    recipe.update({
        "status": status,
        "status_label": compat["statuses"][status]["label"],
        "headline": compat["statuses"][status]["headline"],
        "reasons": first["reasons"],
        "refusal": first["codes"],
        "base": None, "build": build_id(sel), "validated": None, "sources": [], "mechanism": "", "preset": "",
        "print": {"note": "", "files": []},
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
