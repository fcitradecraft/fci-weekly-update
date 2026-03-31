# FCI Weekly Update (Beginner Guide)

This project builds a weekly HTML update page from a list of sources.

## What this project does

1. Reads source definitions from `sources.json`
2. Creates sample update items (placeholder content for now)
3. Groups items by category and calculates report stats
4. Renders a polished HTML briefing using `templates/weekly_update.html`
5. Writes the final page to `output/index.html`

## Project structure

- `collector.py`: main script
- `sources.json`: list of sources and categories
- `templates/weekly_update.html`: HTML template
- `output/index.html`: generated page
- `requirements.txt`: Python dependencies
- `data/`: reserved for future data files
- `venv/`: virtual environment

## Setup (first time)

From the `fci-weekly-update` folder:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run the project

From the `fci-weekly-update` folder:

```bash
source venv/bin/activate
python collector.py
```

Expected terminal message:

```text
Weekly update page created: .../fci-weekly-update/output/index.html
```

## View the result

Open this file in your browser:

- `output/index.html`

## Current output features

- A briefing-style header with issue date and report totals
- Category summary cards for quick scanning
- Ordered sections for Regulatory, News, and Industry Commentary
- Cleaner source cards that are ready for real summaries later

## Common beginner issues

- `ModuleNotFoundError`: activate the virtual environment and install requirements.
- `No sources found in sources.json`: make sure `sources.json` includes a top-level `sources` list.
- Template error: confirm `templates/weekly_update.html` exists.

## Next improvement ideas

1. Replace placeholder items with real article collection.
2. Save collected items into `data/` so each issue can be archived.
3. Add tests for source loading, ordering, and HTML rendering.
