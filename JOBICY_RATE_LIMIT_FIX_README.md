# Jobicy rate-limit fix

Replace your current:
`scripts/run_six_portals.py`

with the file in this patch.

What changed:
- Jobicy now makes at most two broad feed requests per run (APAC and Anywhere), instead of six geo/industry combinations.
- Filters IT roles locally after fetching.
- Retries HTTP 429 and temporary 5xx responses with bounded exponential backoff.
- Respects `Retry-After` when provided.
- If one geographic feed remains unavailable, it logs a warning and continues with the other feed.
- The other five source collectors are unchanged.

Run only Jobicy first:
```powershell
python scripts/run_six_portals.py --source jobicy --max-results 100
```

If Jobicy still returns 429 after the bounded retries, stop retrying for now. It means the provider is still throttling the public endpoint; wait before trying again. Do not loop the command repeatedly.

This patch does not change database schema, `.env`, or the existing 15 portals.
