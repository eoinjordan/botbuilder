# SPDX-License-Identifier: MIT
"""The parts every page of the site shares, in one place: the icon and
link-preview tags of the head, the masthead with its tabs, and the footer
links and notices.

Each page under site/ keeps three marked regions,

    <!-- shared:head --> ... <!-- /shared:head -->
    <!-- shared:masthead --> ... <!-- /shared:masthead -->
    <!-- shared:footer --> ... <!-- /shared:footer -->

and this module rewrites what is between the marks. Change the masthead or
the footer here, run it, and every page follows; a test fails for a page
that differs from what this writes.

    python -m microduck.sitechrome

Standard library only.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
SITE_URL = "https://eoinjordan.github.io/botbuilder/"
REPO_URL = "https://github.com/eoinjordan/botbuilder"
# The tabs, in order: address, text.
TABS = (("./", "Build yours"), ("./biped.html", "Biped"), ("./wheeled.html", "Two-wheeled"), ("./walkers.html", "Walkers"),
        ("./flash.html", "Flash"), ("./control.html", "Control"))
# The notice every recipe carries: one wording, in config/compat.json.
TRADEMARKS = json.loads((ROOT / "config" / "compat.json").read_text(encoding="utf-8"))["trademarks"]


def head(title: str, description: str) -> str:
    return f"""  <link rel="icon" href="./assets/favicon.svg" type="image/svg+xml">
  <link rel="icon" href="./assets/favicon-32.png" sizes="32x32" type="image/png">
  <link rel="apple-touch-icon" href="./assets/apple-touch-icon.png">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="Botbuilder">
  <meta property="og:title" content="{html.escape(title, quote=True)}">
  <meta property="og:description" content="{html.escape(description, quote=True)}">
  <meta property="og:image" content="{SITE_URL}assets/social-preview.png">
  <meta name="twitter:card" content="summary_large_image">
"""


def masthead(name: str) -> str:
    here = "./" if name == "index.html" else f"./{name}"
    tabs = "".join(f'<a href="{href}"{" aria-current=" + chr(34) + "page" + chr(34) if href == here else ""}>{text}</a>'
                   for href, text in TABS)
    return f"""  <a class="skip-link" href="#content">Skip to content</a>
  <header class="masthead">
    <a class="brand" href="./"><img class="brand-icon" src="./assets/logo-mark-light.svg" alt="" width="44" height="44"><span>Bot<b>builder</b></span></a>
    <nav id="site-nav" aria-label="Site">
      {tabs}
      <a class="out" href="https://eoinjordan.github.io/unoq-braccio-sketchbot/" target="_blank" rel="noopener" aria-label="Arms: Sketchbot, opens in a new tab" title="Sketchbot, the robot arm project: opens in a new tab">Arms</a>
      <a href="{REPO_URL}" rel="noopener noreferrer">Source</a>
    </nav>
  </header>
"""


def footer() -> str:
    return f"""    <nav class="foot-links" aria-label="About this site">
      <a href="./?tour=1" data-tour>Take the tour</a>
      <a href="./about.html">About</a>
      <a href="{REPO_URL}/blob/main/docs/status.md" rel="noopener noreferrer">Status and assumptions</a>
      <a href="./credits.html">Picture credits</a>
      <a href="./admin.html">Admin</a>
      <a href="{REPO_URL}" rel="noopener noreferrer">Source</a>
      <a href="{REPO_URL}/issues" rel="noopener noreferrer">Report a problem</a>
    </nav>
    <p class="foot-legal">Code and printable parts under the MIT licence; pictures as on the credits page. Fonts: Space Grotesk, SIL Open Font
      License (<a href="./assets/licenses/space-grotesk.txt">text</a>). <span id="trademarks">{html.escape(TRADEMARKS)}</span></p>
"""


def _between(text: str, mark: str, body: str, indent: str) -> str:
    pattern = re.compile(rf"{indent}<!-- shared:{mark} -->\n.*?{indent}<!-- /shared:{mark} -->\n", re.S)
    if len(pattern.findall(text)) != 1:
        raise ValueError(f"the page needs exactly one shared:{mark} region")
    return pattern.sub(lambda _: f"{indent}<!-- shared:{mark} -->\n{body}{indent}<!-- /shared:{mark} -->\n", text)


def apply(text: str, name: str) -> str:
    """The page with its three shared regions as this module writes them."""
    title = html.unescape(re.search(r"<title>(.*?)</title>", text, re.S).group(1).strip())
    description = html.unescape(re.search(r'<meta name="description" content="([^"]*)">', text).group(1))
    text = _between(text, "head", head(title, description), "  ")
    text = _between(text, "masthead", masthead(name), "  ")
    return _between(text, "footer", footer(), "    ")


def pages(site: Path = SITE) -> list:
    return sorted(site.glob("*.html"))


def main(argv=None) -> int:
    changed = 0
    for path in pages():
        before = path.read_text(encoding="utf-8")
        after = apply(before, path.name)
        if after != before:
            path.write_text(after, encoding="utf-8", newline="\n")
            changed += 1
    print(f"{len(pages())} pages, {changed} rewritten")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
