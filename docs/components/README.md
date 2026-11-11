# Pictures of the bought components

The pictures the configurator and the recipes show for bought parts:
openly licensed photographs from Wikimedia Commons, and drawings made from
the dimensions this repository holds. `config/component_images.json` lists
each with its origin, author and licence; `site/credits.html` is generated
from it.

## Using your own photograph

1. Put the photograph in this folder, 4:3, as a PNG or JPEG of about
   320 x 240 and under 30 kB (an 8-bit PNG also appears in the PDF).
2. In `config/component_images.json` set that component's entry to
   `"kind": "photo"`, `"file"` to the file's name, `"origin": "own photograph"`,
   `"author"` to your name and `"licence"` to the licence you give it; remove
   `"title"`. Then run `python -m microduck.componentpics --credits`.

## The other commands

    python scripts/fetch_component_photos.py     fetch the Commons photographs named by "title"
    python -m microduck.componentpics            draw the drawings and rewrite site/credits.html

The fetch script reads each file's own page on Commons, takes only CC0,
public domain, CC BY and CC BY-SA files, and writes the author, licence and
address it finds there into the data file. Photographs under a share-alike
licence are cropped, resized and reduced to a small palette, nothing else,
and stay under their own licence.
