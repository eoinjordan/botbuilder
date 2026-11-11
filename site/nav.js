// SPDX-License-Identifier: MIT
// Shared navigation. Links to pages that other branches add (marked with
// data-page and hidden in the HTML) are shown only when the site build found
// the page, so there is never a dead link. scripts/build_site.py writes the
// list to data/pages.json.

async function showBuiltPages() {
  let pages = [];
  try {
    const response = await fetch("./data/pages.json");
    if (response.ok) pages = await response.json();
  } catch (error) {
    return;
  }
  for (const link of document.querySelectorAll("#site-nav a[data-page]")) {
    if (pages.includes(link.dataset.page)) link.hidden = false;
  }
}

showBuiltPages();
