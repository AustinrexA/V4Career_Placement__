# V4Career – Fresh scraping for the six additional sources

This patch is based on the latest uploaded V4Career project. It adds a dedicated
collector for the six requested sources while leaving the existing 15 portal
collectors, dashboard, filters, database repository, and old remote collector intact.

## Collection approach

| Source | Method | Credential |
|---|---|---|
| Google Jobs | Apify Actor `themineworks~google-jobs-scraper` | Reuses existing `APIFY_API_TOKEN_COLLECTOR1` by default |
| Jobicy | Public JSON API | None |
| Arbeitnow | Public JSON API | None |
| We Work Remotely | Official programming/devops RSS feeds | None |
| Remote OK | Public JSON feed | None |
| Working Nomads | Public exposed jobs feed | None |

The public API/RSS sources do not require additional API keys. Working Nomads'
exposed endpoint is not a documented developer API, so it is treated as best-effort.
The Google Jobs Actor is paid. Its public listing currently states pay-per-job
pricing; review the live price in Apify before enabling it.

## Geographic and job filters

The collector is configured for IT-related roles. It accepts:
- Jobs explicitly located in India or APAC.
- Remote jobs explicitly marked Anywhere, Worldwide, Global, or with no stated
  geographic restriction on the remote-only feeds.
- It rejects postings explicitly restricted to regions such as US-only, Canada-only,
  UK-only, or Europe-only.

This keeps the existing India-focused collection policy while allowing remote roles
that are genuinely open to applicants from anywhere. Some providers do not expose
work-eligibility regions consistently; review source records and adjust the filter
if a provider changes its feed structure.

Jobicy's public API feed covers recent listings (last seven days) and uses cursors.
The script makes a limited number of calls per run. Avoid scheduling it more than
once per hour. Arbeitnow has no server-side keyword/location filters, so filtering
is performed locally after fetching a small number of pages.

## Files changed or added

### Replace
- `collectors/source_catalog.py`
- `scripts/run_source_apify.py`

### Add
- `scripts/run_six_portals.py`
- `tests/test_six_portal_collector.py`
- `ENV_SIX_PORTALS_APPEND.txt`
- `SIX_PORTALS_SCRAPING_GUIDE.md`

No existing `.env` file is included in this patch because it contains database and
API credentials. Append the three non-secret settings from `ENV_SIX_PORTALS_APPEND.txt`
to your existing `.env`. The existing Collector 1 Apify token is reused; do not paste
or share the token in chat.

## Commands (PowerShell)

From your V4Career project root:

1. Install/confirm dependencies:
```powershell
pip install requests beautifulsoup4 python-dotenv apify-client
```

2. First run the five public API/RSS sources (no Apify charge):
```powershell
python scripts/run_six_portals.py --source all --max-results 100
```

This `all` command intentionally runs the five public sources only unless
`--include-google` is supplied.

3. To include Google Jobs, first review the current Actor pricing, then change
`APIFY_ACCESS_APPROVED_GOOGLE_JOBS=false` to `true` in `.env`, and run:
```powershell
python scripts/run_six_portals.py --source all --max-results 100 --include-google
```

The Google Actor defaults to 10 jobs per role query across eight IT role queries
(up to roughly 80 job rows before de-duplication). Change `GOOGLE_JOBS_MAX_ITEMS`
only if you intentionally want a larger, potentially more expensive run.

4. Run one source individually:
```powershell
python scripts/run_six_portals.py --source jobicy --max-results 100
python scripts/run_six_portals.py --source arbeitnow --max-results 100
python scripts/run_six_portals.py --source we-work-remotely --max-results 100
python scripts/run_six_portals.py --source remote-ok --max-results 100
python scripts/run_six_portals.py --source working-nomads --max-results 100
```

Google Jobs individually (after setting approval to true):
```powershell
python scripts/run_six_portals.py --source google-jobs --max-results 10 --include-google
```

5. Verify saved counts in PostgreSQL:
```sql
SELECT s.name, COUNT(j.id) AS jobs_count
FROM sources s
LEFT JOIN jobs j ON j.source_id = s.id
WHERE s.name IN (
  'Google Jobs', 'Jobicy', 'Arbeitnow',
  'We Work Remotely', 'Remote OK', 'Working Nomads'
)
GROUP BY s.name
ORDER BY s.name;
```

## Safety / expected behavior

- Jobs are normalized with the existing `collectors.normalization.normalize_job`.
- Jobs are saved with the existing `collectors.repository.save_jobs`.
- URL hashes are used for per-source duplicate detection/updating.
- Each source writes collection run status through the existing repository.
- No rows are deleted and no schema migration is required for this script.
- The script does not change the existing 15 portal scraping commands.
- Google Jobs uses an explicit `--include-google` switch and an additional `.env`
  approval flag to avoid accidental paid runs.
- The first live API/Actor execution must be tested in your local environment;
  this environment cannot access your Neon DB or your Apify account.
