# Automation Jobs LinkedIn Signal — Agent Guide

Daily signal that finds companies actively hiring for AI/automation contract work
and surfaces them as outreach opportunities.

## Architecture

```
config.json
    └─ AI-first + GTM lanes × four locations, remote/job-type filters, relevance rules
           │
           ▼
track_jobs.py :: collect()
    └─ LinkedInMCPClient → centralized Modal LinkedIn MCP
           ├─ search_jobs
           ├─ get_job_details
           └─ get_company_profile
                   │
                   ▼
           evaluate_job() against candidate_profile.yaml-derived rules
                   ├─ hard role-family exclusions
                   ├─ conditional AI-trainer domain gate
                   └─ positive-fit scoring
                   │
                   ▼
           globally rank accepted jobs by relevance score
                   │
                   ▼
           dedup against seen_job_ids (state file)
                   │
                   ▼
           append_to_sheet()  → Google Sheet
           send_slack()       → Slack webhook
           save_seen()        → state file
```

## Execution mode

Both local and Modal execution call the centralized, authenticated LinkedIn MCP
service. This component never owns cookies or launches a LinkedIn browser.

```bash
bash run.sh                    # normal run
bash run.sh --reset-state      # ignore seen IDs, re-add everything found
```

```bash
modal run signals/automation_jobs_linkedin/modal_app.py
modal run signals/automation_jobs_linkedin/modal_app.py --reset-state
```

## config.json fields

| Field | Default | Effect |
|---|---|---|
| `search_queries` | array of two queries | AI automation/applied AI and GTM/email/pipeline automation lanes |
| `locations` | four explicit locations | Runs every lane for United States, Europe, Sofia/Bulgaria, and Australia |
| `work_type` | `remote` | LinkedIn remote-only filter |
| `remote_policy` | required | Hard-rejects hybrid, on-site, in-office, and mandatory physical-presence language |
| `work_authorization_policy` | required | Hard-rejects jobs requiring existing U.S. work rights or offering no sponsorship |
| `location_eligibility_policy` | required | Hard-rejects remote jobs that still require the candidate to live in the U.S. |
| `job_type` | `contract,part_time,temporary,other` | Limits results to non-permanent engagement types; remote policy remains mandatory |
| `date_posted` | `past_week` | Overlapping recovery window; dedup prevents repeat delivery after missed runs |
| `sort_by` | `date` | `date` or `relevance` |
| `max_pages` | `1` | Pages of search results to fetch (25 jobs/page) |
| `max_jobs_per_run` | `10` | Max new rows written per run |
| `inter_search_delay_min_seconds` | `45` | Minimum pause before each search after the first |
| `inter_search_delay_max_seconds` | `75` | Maximum pause before each search after the first |
| `candidate_fetch_multiplier` | `2` | Per-search candidate inspection pool relative to the final row limit |
| `relevance` | profile-derived rules | Hard exclusions, positive scoring, and AI-trainer domain policy |
| `exclude_title_terms` | title blocklist | Case-insensitive title exclusions |
| `exclude_job_terms` | `["robotics"]` | Case-insensitive whole-post exclusions |

Candidates from all lanes are evaluated with the same matcher, then globally
ranked before the 10-row limit is applied. Rejected and selected reasons appear
in the JSON run audit but the sheet schema remains unchanged. Set
`INTER_SEARCH_DELAY_SECONDS=0` only for local no-write validation.

Applied AI and AI-automation title families receive the strongest relevance
weights. Marketing and GTM automation remain accepted secondary matches, but
should only fill the batch after stronger AI-focused opportunities.

Remote eligibility is fail-closed at configuration time: `work_type` must remain
exactly `remote`. LinkedIn's remote filter supplies the positive workplace signal,
while the complete posting is independently scanned for any hybrid or on-site
language, office days, or other mandatory physical-presence requirements.

Work authorization eligibility is also fail-closed. The full job description,
including employer boilerplate, is scanned before scoring. Jobs requiring existing
U.S. work authorization or explicitly stating that sponsorship is unavailable are
rejected and cannot enter the ranked daily batch. The same hard-rejection behavior
applies when an otherwise remote role requires the worker to be based in the U.S.

`candidate_profile.yaml` is the human-readable source profile. Confirmed job
feedback belongs there first, then must be represented by tested rules in
`config.json`. Hard bans should only be added after explicit feedback.

## State and deduplication

- **Local**: `state/seen_job_ids.json` — list of job IDs already written to the sheet
- **Modal**: `/automation_jobs_seen.json` inside `automation-jobs-linkedin-session` volume
- State persists across runs. Use `--reset-state` to skip dedup for one run.
- To rebuild state from the sheet (e.g. after volume reset):
  extract job IDs from the `job_url` column and upload a new state JSON to the volume.

## Google Sheet schema

Core columns: `detected_at`, `company_name`, `company_website`, `job_title`,
`job_description`, `job_url`, `poster_linkedin_url`, `job_id`, `relevance_score`,
and `relevance_signals`. Feedback columns are appended for `review_status`,
`fit_rating`, `rejection_reason`, `applied`, `response`, `interview`, and `won`.
Outreach enrichment columns are appended after all existing fields for
`company_linkedin_url`, `company_domain`, structured compensation,
`domain_source`, and `domain_status`. The first seven columns must never move,
because the resume generator validates that prefix before processing rows.

Use `backfill_enrichment.py` to reconcile historical rows. It retries the public
company reference already attached to each job, then uses an exact-company
Apollo lookup when a website is still unavailable. Ambiguous Apollo matches stay
unresolved. The command is non-mutating with `--dry-run`.

Older sheets may still have `short_description` as the column E header. The
writer upgrades that legacy header to `job_description` before appending rows.

The sheet is append-only. Before each batch write, the writer checks existing
`job_id` and `job_url` values, so retrying after an interrupted state update does
not duplicate rows. New rows are written to an explicit `A:<last header column>`
range; never use implicit Sheets append-table detection because manual notes or
downstream resume columns can cause Google to start a second table to the right.
IDs are persisted only after the Sheet confirms delivery. A run without
credentials is a preview and does not mutate state. Never delete rows manually
— the state file is the primary source of truth and Sheet IDs/URLs provide the
secondary idempotency layer.

Use the read-only feedback report after rating jobs and recording outcomes:
```bash
AUTOMATION_JOBS_SHEET_ID="..." python3 analyze_feedback.py \
  --credentials ../../credentials.json
```
It reports fit precision, average rating, application/response/interview/win
rates, and the most common rejection reasons.

## Modal infrastructure

### Secrets (`automation-jobs-linkedin-secrets`)
- `GOOGLE_CREDENTIALS_B64` — service account JSON, base64-encoded (avoids shell-escaping issues)
- `AUTOMATION_JOBS_SHEET_ID` — target spreadsheet ID
- `SLACK_WEBHOOK_URL` — incoming webhook for run notifications
- `TRIGGER_TOKEN` — required bearer token for the n8n HTTP trigger

The Modal functions also attach `pipeline-engine-hiring-outreach-secrets` to
reuse its existing `APOLLO_API_KEY` for exact-company domain recovery. Do not
copy or rotate the Apollo credential into the Automation Jobs secret.

`TRIGGER_TOKEN` is stored separately in the Modal secret
`automation-jobs-linkedin-trigger`, so rotating it cannot overwrite the Google
or Slack values in `automation-jobs-linkedin-secrets`.

To update credentials:
```bash
B64=$(base64 -i /path/to/credentials.json)
modal secret create automation-jobs-linkedin-secrets \
  GOOGLE_CREDENTIALS_B64="$B64" \
  AUTOMATION_JOBS_SHEET_ID="1GmV-FEfYKEIODbpJanLqxlMDbjMa7DHijNJtnZZpsnk" \
  SLACK_WEBHOOK_URL="https://hooks.slack.com/..." \
  --force

modal secret create automation-jobs-linkedin-trigger \
  TRIGGER_TOKEN="<long-random-token>" --force
```

### Volume (`automation-jobs-linkedin-session`)
The volume stores only `automation_jobs_seen.json`. Never upload LinkedIn cookies
or browser profiles here. Authentication belongs only to the centralized
`linkedin-mcp-vol` volume.

### Schedule
No Modal cron (free plan limit reached). n8n triggers the HTTP endpoint daily.
- Endpoint: `POST https://iliyan-ivanov-mp--automation-jobs-linkedin-run-daily.modal.run/`
- Required header: `Authorization: Bearer <TRIGGER_TOKEN>`
- The HTTP endpoint cannot reset state; reset is available only through the manual Modal entrypoint.
- Schedule: 5 PM Europe/Sofia → `0 14 * * *` (summer, EEST=UTC+3) / `0 15 * * *` (winter, EET=UTC+2)

## Safe commands

```bash
# Inspect without writing
~/.local/share/uv/tools/mcp-server-linkedin/bin/python3 track_jobs.py \
  --credentials /tmp/no-such-file.json \
  --state /tmp/automation_jobs_test_seen.json \
  --reset-state 2>/dev/null

# Local full run
bash run.sh

# Modal test run
modal run signals/automation_jobs_linkedin/modal_app.py

# Deploy
modal deploy signals/automation_jobs_linkedin/modal_app.py

# Check sheet row count
python3 -c "
import gspread; from google.oauth2.service_account import Credentials
creds = Credentials.from_service_account_file('../../credentials.json',
  scopes=['https://www.googleapis.com/auth/spreadsheets'])
ws = gspread.authorize(creds).open_by_key('1GmV-FEfYKEIODbpJanLqxlMDbjMa7DHijNJtnZZpsnk').sheet1
print(len(ws.get_all_values()), 'rows')"
```

## What NOT to do

- Do not delete or overwrite sheet rows (breaks historical record)
- Do not run with `--reset-state` on production unless the user asks (will re-add already-seen jobs)
- Do not add a `schedule=` to `modal_app.py` without removing another scheduled function first (free plan caps at 5)
- Do not store raw credentials JSON in shell variables — always use base64
- Do not import from sibling signals or the parent `linkedin-mcp-experimentation` repo
