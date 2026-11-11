# SPDX-License-Identifier: MIT
"""Record the owner's check of a printed build in config/validated.json.

Run by .github/workflows/validated.yml when an issue made from the "Mark a
build as validated" form is opened or edited. The issue body is untrusted
text: it is read from the event file, never passed through a shell, and
every field is checked before anything is written.

    python scripts/record_validation.py --event "$GITHUB_EVENT_PATH" --outcome outcome.md

Exit status 0 always; the outcome file says what happened and the line
"changed=true" or "changed=false" is appended to --github-output. Standard
library only.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
LABEL = "validated"
RESULTS = {"fits and works": True, "fits with changes": True, "does not fit": False}
PHOTO_HOSTS = ("github.com", "user-images.githubusercontent.com", "private-user-images.githubusercontent.com",
               "objects.githubusercontent.com", "github-production-user-asset-6210df.s3.amazonaws.com")
PHOTO_TYPES = {"image/png": (".png", b"\x89PNG\r\n\x1a\n"), "image/jpeg": (".jpg", b"\xff\xd8\xff")}
PHOTO_LIMIT = 6_000_000
TEXT_LIMIT = 400
FIELDS = {"build id": "build", "part file": "part", "date": "date", "what was checked": "checked", "result": "result",
          "notes on changes made": "notes", "photo": "photo", "remove": "remove"}
NOT_OWNER = "Only the repository owner can record a validation. Nothing was changed."


class Refused(ValueError):
    """The form cannot be recorded; the message goes back to the issue."""


def gate(event: dict) -> str | None:
    """None if the issue is the repository owner's own and carries the label,
    otherwise why not. The workflow repeats the owner test in its own
    condition; this is the second lock."""
    issue = event.get("issue") or {}
    owner = ((event.get("repository") or {}).get("owner") or {}).get("login")
    author = (issue.get("user") or {}).get("login")
    labels = [label.get("name") for label in issue.get("labels") or [] if isinstance(label, dict)]
    if LABEL not in labels:
        return "The issue does not carry the validated label. Nothing was changed."
    if not owner or not author or author != owner or issue.get("author_association") != "OWNER":
        return NOT_OWNER
    return None


def clean(text, limit: int = TEXT_LIMIT) -> str:
    """One line of plain text: control characters out, runs of space closed, capped."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(text))
    text = " ".join(text.split())
    return text[:limit]


def parse(body: str) -> dict:
    """The fields of an issue form: '### Label' headings, each followed by its value."""
    out = {key: "" for key in FIELDS.values()}
    current = None
    lines: dict[str, list[str]] = {}
    for line in str(body).replace("\r\n", "\n").replace("\r", "\n").split("\n")[:400]:
        heading = re.fullmatch(r"###\s+(.{1,80}?)\s*", line)
        if heading:
            label = heading.group(1).strip().lower()
            field = next((name for start, name in FIELDS.items() if label.startswith(start)), None)
            # A heading repeated inside a field is that field's text, not a second field.
            if field is None or field not in lines:
                current = field
                if field is not None:
                    lines[field] = []
                continue
        if current is not None:
            lines.setdefault(current, []).append(line)
    for field, value in lines.items():
        text = "\n".join(value).strip()
        out[field] = "" if text == "_No response_" else text
    return out


def known_builds(root: Path = ROOT) -> list[str]:
    with open(root / "config" / "compat.json", encoding="utf-8") as handle:
        compat = json.load(handle)
    return [f"{row['controller']}-{row['locomotion']}-{row['drive']}" for row in compat["support"]]


def known_parts(root: Path = ROOT) -> list[str]:
    path = root / "stl" / "manifest.json"
    if not path.is_file():
        return []
    with open(path, encoding="utf-8") as handle:
        return [entry["file"] for entry in json.load(handle).get("files", [])]


def photo_url(text: str) -> str | None:
    """The first attachment address in the photo field, if it is on one of
    GitHub's own attachment hosts over https. Anything else is refused."""
    found = re.findall(r"https?://[^\s\"'<>)\]]+", text)
    if not found:
        return None
    url = found[0]
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.port not in (None, 443):
        raise Refused("The photo must be an https attachment on github.com. Nothing was changed.")
    host = (parts.hostname or "").lower()
    if host not in PHOTO_HOSTS or (host == "github.com" and not parts.path.startswith("/user-attachments/")):
        raise Refused("The photo must be a file dropped into the form (a GitHub attachment). Nothing was changed.")
    return url


class _SameHosts(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urlsplit(newurl)
        if parts.scheme != "https" or (parts.hostname or "").lower() not in PHOTO_HOSTS:
            raise urllib.error.HTTPError(newurl, code, "redirect to a host that is not GitHub's", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str) -> tuple[str, bytes]:
    """Content type and bytes of an attachment, at most PHOTO_LIMIT + 1 bytes."""
    opener = urllib.request.build_opener(_SameHosts)
    with opener.open(urllib.request.Request(url, headers={"User-Agent": "botbuilder-validated"}), timeout=30) as reply:
        return reply.headers.get_content_type(), reply.read(PHOTO_LIMIT + 1)


def record_from(fields: dict, root: Path = ROOT, fetch=download, author: str = "") -> tuple[dict, bool, tuple | None]:
    """A checked record from the parsed form, whether it is a removal, and
    the photo to save as (name, bytes) or None. Raises Refused."""
    build = clean(fields["build"], 80)
    if build not in known_builds(root):
        raise Refused("The build id is not one this site knows. Use the Mark validated button on the Admin page. Nothing was changed.")
    part = clean(fields["part"], 200)
    if part and part not in known_parts(root):
        raise Refused("The part file is not in stl/manifest.json. Nothing was changed.")
    date = clean(fields["date"], 20)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise Refused("The date must be written as YYYY-MM-DD. Nothing was changed.")
    try:
        day = datetime.date.fromisoformat(date)
    except ValueError:
        raise Refused("The date is not a real date. Nothing was changed.") from None
    if not datetime.date(2024, 1, 1) <= day <= datetime.date.today() + datetime.timedelta(days=1):
        raise Refused("The date is outside the range this form accepts. Nothing was changed.")
    remove = bool(re.search(r"-\s*\[[xX]\]", fields["remove"]))
    if remove:
        return {"id": build, "part": part}, True, None
    result = clean(fields["result"], 40).lower()
    if result not in RESULTS:
        raise Refused("The result must be one of the three choices of the form. Nothing was changed.")
    record = {"id": build, "part": part, "date": date, "checked": clean(fields["checked"]), "result": result,
              "notes": clean(fields["notes"]), "photo": "", "by": clean(author, 40), "mark": RESULTS[result]}
    saved = None
    url = photo_url(fields["photo"])
    if url:
        try:
            kind, data = fetch(url)
        except (OSError, ValueError) as error:
            raise Refused(f"The photo could not be fetched ({clean(error, 80)}). Nothing was changed.") from None
        if kind not in PHOTO_TYPES or not data.startswith(PHOTO_TYPES[kind][1]):
            raise Refused("The photo must be a PNG or JPEG image. Nothing was changed.")
        if len(data) > PHOTO_LIMIT:
            raise Refused("The photo is larger than 6 MB. Nothing was changed.")
        name = f"{build}-{date}-{hashlib.sha256(data).hexdigest()[:10]}{PHOTO_TYPES[kind][0]}"
        record["photo"] = "docs/validated/" + name
        saved = (name, data)
    return record, False, saved


def apply(records: list, record: dict, remove: bool) -> tuple[list, str]:
    """The records with this one put in place of any earlier one for the same
    build and part, or taken out."""
    same = lambda item: item.get("id") == record["id"] and (item.get("part") or "") == record["part"]
    kept = [item for item in records if not same(item)]
    what = record["id"] + (f", part {record['part']}" if record["part"] else "")
    if remove:
        if len(kept) == len(records):
            return records, f"There was no mark for {what}. Nothing was changed."
        return kept, f"Removed the mark for {what}."
    kept.append(record)
    if record["mark"]:
        return kept, f"Recorded: {what} printed and checked on {record['date']}. The mark appears on the site after the next Pages build."
    return kept, f"Recorded as a note without a mark: {what} did not fit on {record['date']}."


def run(event: dict, root: Path = ROOT, fetch=download) -> tuple[bool, str]:
    """Do the whole thing for one event. Returns (files changed, message)."""
    refused = gate(event)
    if refused:
        return False, refused
    issue = event["issue"]
    try:
        record, remove, photo = record_from(parse(issue.get("body") or ""), root, fetch, issue["user"]["login"])
    except Refused as error:
        return False, str(error)
    path = root / "config" / "validated.json"
    content = {"records": []}
    if path.is_file():
        with open(path, encoding="utf-8") as handle:
            content = json.load(handle)
    before = json.dumps(content, sort_keys=True)
    if not remove:
        record["issue"] = issue.get("number") if isinstance(issue.get("number"), int) else None
    content["records"], message = apply(content.get("records", []), record, remove)
    if json.dumps(content, sort_keys=True) == before:
        return False, message
    if photo:
        folder = root / "docs" / "validated"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / photo[0]).write_bytes(photo[1])
    path.write_text(json.dumps(content, indent=1) + "\n", encoding="utf-8", newline="\n")
    return True, message


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--outcome", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    try:
        with open(args.event, encoding="utf-8") as handle:
            changed, message = run(json.load(handle))
    except Exception as error:                                # the issue still gets an answer
        changed, message = False, f"The form could not be read ({type(error).__name__}). Nothing was changed."
    args.outcome.write_text(message + "\n", encoding="utf-8", newline="\n")
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"changed={'true' if changed else 'false'}\n")
    print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
