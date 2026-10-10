# DriveMate map data: quick start for Claude

- Public repo, so Actions minutes are free. The real cost is Claude tokens, so keep sessions short.
- `.github/workflows/map-data.yml` builds UK map files weekly (about 1–4 h) and uploads them to the `map-data-uk` release. `scripts/*.py` are its processing steps.
- `.github/workflows/junction-diag.yml` is a temporary one-off diagnostic. Read its output from the Actions log, and delete the file when you're done with it.
- Never download or open the release files (`drivemate.pmtiles`, `places-*.json.gz`, `lanes-*.json`). They are huge. Use `gh release view map-data-uk` for sizes and names.
- When checking a run, read only the failing step's log. The map build is long, so check it rarely (about every 30 minutes), not every minute.
- Push each change as one commit. A push to `main` touching `scripts/**` or `map-data.yml` restarts the multi-hour build.
