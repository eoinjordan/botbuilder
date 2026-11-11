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
    sim = _load(root / "reports" / "sim.json")
    rep = assembly["variants"][assembly["selected"]]
    size = rep["dimensions"]["size_mm"]
    return {
        "mass_total_g": str(round(rep["mass"]["total_g"])),
        "mass_solid_g": str(round(rep["mass"]["total_if_printed_solid_g"])),
        "size_l_mm": str(round(size[0])),
        "size_w_mm": str(round(size[1])),
        "size_h_mm": str(round(size[2])),
        "stance_mm": str(round(rep["dimensions"]["stance_width_between_foot_centres_mm"])),
        "findings_count": str(len(assembly["findings"])),
        "verdict_stand": sim["verdict"]["stand"],
        "verdict_neutral": sim["verdict"]["neutral"],
        "verdict_gait": sim["verdict"]["gait"],
    }


def manifest(root: Path = ROOT) -> dict:
    """Paths of the STLs under stl/, if another branch has committed a manifest.

    The manifest's layout is not fixed here: every string in it that ends in
    .stl is taken as a path under stl/.
    """
    for name in MANIFEST_PATHS:
        path = root / name
        if path.is_file():
            found: list[str] = []
            _collect_stl_names(_load(path), found)
            return {"present": True, "paths": sorted(set(found))}
    return {"present": False, "paths": []}


def _collect_stl_names(node, found: list[str]) -> None:
    if isinstance(node, str):
        text = node.replace("\\", "/")
        if text.lower().endswith(".stl"):
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
    return {
        "compat": compat,
        "bases": _load(root / "config" / "bases.json"),
        "facts": facts(root),
        "manifest": manifest(root),
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


def _unsupported(compat: dict, sel: dict) -> dict:
    rows = [row for row in compat["support"] if row["controller"] == sel["controller"]]
    offered = "; ".join(_label(compat, "locomotion", row["locomotion"]) + " through " + _label(compat, "drive", row["drive"])
                        for row in rows)
    reasons = [_label(compat, "controller", sel["controller"]) + " is not offered as '"
               + _label(compat, "locomotion", sel["locomotion"]) + "' through '"
               + _label(compat, "drive", sel["drive"]) + "'. Offered for this controller: " + offered + "."]
    for item in compat["why_not"]:
        if _matches(item["when"], sel):
            reasons.append(item["reason"])
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
        blocked = _unsupported(compat, sel)
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
    else:
        status = row["status"]
        if status != "analysed":
            lead.append("Not analysed: no simulation or digital assembly exists for this selection.")
    sections = {name: [] for name in compat["sections"]}
    sections["analysis"].extend(lead)
    settings = {"mechanism": "", "preset": ""}
    rails = {}
    loads = []
    for rule in matched:
        if rule.get("downgrade") and status == "analysed":
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
    files = []
    for item in sections["print"]:
        name = item["file"]
        if item.get("folder") and settings["preset"]:
            name = settings["preset"] + "/" + name
        link = None
        for path in listing["paths"]:
            if path == name or path.endswith("/" + name):
                link = compat["repo_blob"] + "stl/" + path
                break
        files.append({"file": name, "qty": item["qty"], "role": item["role"], "fit": bool(item.get("fit")),
                      "link": link})
    files = [item for item in files if item["fit"]] + [item for item in files if not item["fit"]]
    if not files:
        note = "No printable files are named for this selection yet: the design is in progress on another branch."
    elif listing["present"]:
        note = "Linked files are in the repository's stl/ directory. A name without a link is not in its manifest."
    else:
        note = "File names only: the repository has no STL manifest yet, so nothing is linked."

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
