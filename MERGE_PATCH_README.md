# V4Career delta files: Google Jobs + five remote job boards

This folder is a patch for the existing `V4Career_final_version_(2)` project.
It is NOT a complete project. Copy the contents into the existing project root,
preserving the folder structure and replacing files when Windows asks.

## Files to replace
- `collectors/source_catalog.py`
- `collectors/normalization.py`
- `collectors/repository.py`
- `scripts/run_source_apify.py`
- `database/postgres_schema.sql`
- `database/mysql_schema.sql`

## New files to add
- `scripts/run_remote_multi.py`
- `database/migrations/002_google_jobs_fields.sql`
- `database/migrations/002_google_jobs_fields_mysql.sql`

## Database migration
For an existing Neon/PostgreSQL database, run:
`database/migrations/002_google_jobs_fields.sql`

For an existing MySQL database, run:
`database/migrations/002_google_jobs_fields_mysql.sql`

Do not run both migrations. They add metadata columns and indexes; they do not delete existing job records.
For a brand-new database only, use the updated full schema for the database engine you selected.

## Add these settings to your existing .env (do not overwrite .env)
Keep your existing `APIFY_API_TOKEN`, database URL/credentials, and other settings.
Append and adjust these values after checking the Actor's input schema and your authorization:

```dotenv
APIFY_ACTOR_GOOGLE_JOBS=vncntlabs~google-jobs-scraper
APIFY_ACCESS_APPROVED_GOOGLE_JOBS=false
APIFY_INPUT_GOOGLE_JOBS={"queries":["Software Engineer"],"locations":["India"],"maxJobsPerSearch":30,"includeDescription":true}

APIFY_ACTOR_REMOTE_MULTI=rel8ble/remote-jobs-aggregator
APIFY_ACCESS_APPROVED_REMOTE_MULTI=false
APIFY_INPUT_REMOTE_MULTI={"sources":["remoteok","weworkremotely","jobicy","workingnomads","arbeitnow"]}
```

Keep approval flags `false` until you have reviewed the Actor's terms, data rights,
input schema, and authorization. The five remote portals are collected through one
multi-board Actor; this does not mean five independently tested API integrations.

## Run locally
Google Jobs:
`python scripts/run_source_apify.py --source "Google Jobs" --keyword "Software Engineer" --location "India" --max-results 30`

Five remote portals:
`python scripts/run_remote_multi.py`

The remote runner filters records by IT-related title/category/tags and writes them
through V4Career's existing normalization and database repository.

## Important
- The 15 existing portal entries remain in the catalog; the six requested sources are appended.
- Google Jobs uses the regular single-source Apify runner.
- Remote OK, We Work Remotely, Jobicy, Working Nomads, and Arbeitnow use the new multi-board runner.
- Actual Actor runs have not been performed here. Verify the Actor input schema and test with your own token before enabling collection.
- The existing `.env` is deliberately not included in this patch.
