# Marking a build as printed and checked

For the repository owner. The site's Admin page (`site/admin.html`, linked
from every footer) lists every build and every printable part with its mark.

1. Press "Mark validated" beside the build or part. GitHub opens the "Mark a
   build as validated" form in a new tab with the build id and today's date
   filled in. You are signed in there with your own GitHub login.
2. Say what was checked, choose the result, drag a photo into the photo box
   if you like, and submit.
3. The "Record a validated build" workflow reads the form, updates
   `config/validated.json`, saves the photo under `docs/validated/`, commits,
   answers on the issue and closes it. The Pages build follows, and the mark
   "Printed and checked on <date>" appears on that recipe and part a few
   minutes later.

A result of "does not fit" is recorded as a note and shows no mark. To take a
mark away, press "Change or remove" and tick "Remove this mark" on the form.

## Who can do it

Anyone can look at the Admin page; it changes nothing by itself and holds no
token and no login code. Anyone can also open the form, but the workflow
applies a submission only when the issue's author is the repository owner
(the login equals the owner and GitHub reports the association OWNER).
For anyone else it comments "Only the repository owner can record a
validation" and stops.

The form's text is treated as untrusted: the workflow never puts it on a
command line. `scripts/record_validation.py` reads it from the event file,
accepts only a build id from `config/compat.json`, a part from
`stl/manifest.json`, a date written YYYY-MM-DD, short plain text, and a photo
that is a PNG or JPEG of at most 6 MB on one of GitHub's own attachment
hosts over https.

A full "sign in with GitHub" inside the page would need a small server to
hold an OAuth client secret. The site is static, so it uses the login you
already have on github.com instead.

## The data

`config/validated.json` holds `{"records": [...]}`. A record:

| Field | Meaning |
|---|---|
| `id` | The build: controller, locomotion and drive, as in the address of its recipe (`unoq-biped-braccio_shield`). |
| `part` | Empty for the whole build, or one file of `stl/manifest.json`. |
| `date` | The day it was checked. |
| `checked` | What was checked, one line. |
| `result` | fits and works, fits with changes, or does not fit. |
| `notes` | Changes that were made. |
| `photo` | A path under `docs/validated/`, or empty. |
| `by` | The GitHub login that submitted it. |
| `mark` | False for "does not fit": kept as a note, no mark shown. |

The file can also be edited by hand. The workflow has not been run from
this working copy: it runs on GitHub when the form is submitted.
