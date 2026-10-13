# Frontend

- `web_app/`: web UI served by `eregion.api.main` at `/apply`.
- `chrome_extension/`: unpacked Eregion Lens extension. If previously loaded from
  the root directory, select this new folder in Chrome's extension management page.
- `site/`: public product website; the Pages workflow publishes this directory.

Run browser-side unit tests from the repository root with `node --test "tests/*.mjs"`.
