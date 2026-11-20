# V4Career source catalog correction

This patch is based on the latest uploaded `V4Career_final_version_(4).zip`.

## Replace
- `collectors/source_catalog.py`
- `tests/test_source_catalog.py` (updates stale assertions to the intended 15 + 6 = 21 portal catalog)

## Why
The uploaded project had a source catalog with 21 entries but stale catalog tests expecting a different 25-portal list and a different sidebar allowlist. This patch keeps the 15 portals in the current project, appends the six requested portals, removes the duplicate `DEFAULT_APIFY_ACTORS` declaration, and makes all 21 catalogued portals selectable in the UI.

The five remote boards are identified as one shared multi-board collector group; they are not represented as five independent Actors.

## Apply
Extract this ZIP into the project root and preserve the folder structure. Back up the two existing files first.

## Validate
From the V4Career project directory run:
`python -m pytest tests/test_source_catalog.py -q`

This validates catalog consistency only. It does not prove live Apify Actor access or successful scraping.
