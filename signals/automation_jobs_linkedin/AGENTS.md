# Automation Jobs LinkedIn Signal — Agent Guide

Daily signal that finds companies actively hiring for AI/automation contract work
and surfaces them as outreach opportunities.

## Architecture

```
config.json
    └─ three search lanes, remote/job-type filters, relevance rules
           │
           ▼
track_jobs.py :: collect()
    ├─ tries get_or_create_browser() (full browser path, local)
    │       └─ on AuthenticationError → falls back to collect_guest_api()
    └─ collect_guest_api()  ← always used on Modal (no browser auth)
           ├─ _guest_search()       → /jobs-guest/jobs/api/seeMoreJobPostings/search
           └─ _guest_job_details()  → /jobs-guest/jobs/api/jobPosting/{id}
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

## Two execution modes

### Local (full browser)
Uses `mcp-server-linkedin` Patchright browser with the persisted LinkedIn session.
Gets company website and poster LinkedIn URL when LinkedIn renders the hiring card.

```bash
bash run.sh                    # normal run
bash run.sh --reset-state      # ignore seen IDs, re-add everything found
```

### Modal (guest API fallback)
Browser auth fails on fresh containers (LinkedIn anti-bot). `collect()` catches
`AuthenticationError` and automatically delegates to `collect_guest_api()`, which
uses LinkedIn's unauthenticated `/jobs-guest/` endpoints — no cookies required.
It enriches `company_website` from the public LinkedIn company page when the
external website is visible there. It also extracts `poster_linkedin_url` when
the guest job page exposes a hiring-team card; otherwise that field stays empty.

```bash
modal run signals/automation_jobs_linkedin/modal_app.py
modal run signals/automation_jobs_linkedin/modal_app.py --reset-state
```

## config.json fields

| Field | Default | Effect |
|---|---|---|
| `search_queries` | array of three queries | AI automation, GTM automation, and domain-gated AI trainer lanes |
| `work_type` | `remote` | LinkedIn remote-only filter |
| `remote_policy` | required | Hard-rejects hybrid, on-site, in-office, and mandatory physical-presence language |
| `job_type` | `contract,part_time,full_time,temporary,other` | Allows any requested engagement type; remote policy remains mandatory |
| `date_posted` | `past_week` | Overlapping recovery window; dedup prevents repeat delivery after missed runs |
| `sort_by` | `date` | `date` or `relevance` |
| `max_pages` | `1` | Pages of search results to fetch (25 jobs/page) |
| `max_jobs_per_run` | `10` | Max new rows written per run |
| `inter_search_delay_min_seconds` | `180` | Minimum pause before each search after the first |
| `inter_search_delay_max_seconds` | `300` | Maximum pause before each search after the first |
| `candidate_fetch_multiplier` | `5` | Candidate inspection pool relative to the final row limit |
| `relevance` | profile-derived rules | Hard exclusions, positive scoring, and AI-trainer domain policy |
| `exclude_title_terms` | title blocklist | Case-insensitive title exclusions |
| `exclude_job_terms` | `["robotics"]` | Case-insensitive whole-post exclusions |

Candidates from all lanes are evaluated with the same matcher, then globally
ranked before the 10-row limit is applied. Rejected and selected reasons appear
in the JSON run audit but the sheet schema remains unchanged. Set
`INTER_SEARCH_DELAY_SECONDS=0` only for local no-write validation.

Remote eligibility is fail-closed at configuration time: `work_type` must remain
exactly `remote`. LinkedIn's remote filter supplies the positive workplace signal,
while the job title and description are independently scanned for contradictory
hybrid, on-site, office-day, or other mandatory physical-presence requirements.

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

Older sheets may still have `short_description` as the column E header. The
writer upgrades that legacy header to `job_description` before appending rows.

The sheet is append-only. Rows are batch-appended, and IDs are persisted only
after the Sheet confirms delivery. A run without credentials is a preview and
does not mutate state. Never delete rows manually — the state file is the
primary source of truth and `job_id` is the secondary idempotency key.

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
Production uses the guest API and needs no LinkedIn cookies or browser profile.
The volume persists `automation_jobs_seen.json`; older browser-session files may
remain but are no longer used by this workflow.

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
