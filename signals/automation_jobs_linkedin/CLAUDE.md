# Claude Code Context: Automation Jobs LinkedIn Signal

Read `AGENTS.md` before making changes. This directory is standalone — do not
import from or modify sibling signals (pipeline-engine-hiring-outreach,
technology-based-outreach, funnel-audits).

## What this does

Scrapes LinkedIn daily for AI/automation contract and freelance jobs, deduplicates
against a persistent state file, appends new rows to a Google Sheet, and sends a
Slack notification with the sheet link.

## Production path

`LinkedIn search → job details → profile-based filtering/scoring → global ranking → dedup → Google Sheet → Slack`

## Entry points

- **Local run**: `bash run.sh` (uses `~/.local/share/uv/tools/mcp-server-linkedin/bin/python3`)
- **Cloud run**: `modal run signals/automation_jobs_linkedin/modal_app.py`
- **Production trigger**: authenticated HTTP POST to `https://iliyan-ivanov-mp--automation-jobs-linkedin-run-daily.modal.run/` with `Authorization: Bearer <TRIGGER_TOKEN>` (called by n8n daily at 5 PM Europe/Sofia)
- **Force re-run all jobs**: append `--reset-state` to either command

## Key files

- `track_jobs.py` — scraping, relevance evaluation, ranking, dedup, sheet writing, and Slack logic
- `modal_app.py` — Modal deployment, secret handling, volume mounting
- `config.json` — search lanes, date/job filters, candidate-derived relevance rules
- `candidate_profile.yaml` — human-readable candidate context and confirmed job feedback
- `state/seen_job_ids.json` — local dedup state (Modal uses volume path instead)
- `run.sh` — local runner with `AUTOMATION_JOBS_SHEET_ID` baked in

## Production resources

- Google Sheet: `1GmV-FEfYKEIODbpJanLqxlMDbjMa7DHijNJtnZZpsnk`
- Modal app: `automation-jobs-linkedin`
- Modal secrets: `automation-jobs-linkedin-secrets` (Google/Sheet/Slack) and `automation-jobs-linkedin-trigger` (`TRIGGER_TOKEN`)
- Modal volume: `automation-jobs-linkedin-session` (persistent deduplication state plus the session bundle mirrored on every LinkedIn MCP reauthentication)
- State file in volume: `/automation_jobs_seen.json`
- n8n workflow: triggers daily at 5 PM Europe/Sofia (14:00 UTC summer, 15:00 UTC winter)
- Service account: `n8n-integration@n8n-integration-467109.iam.gserviceaccount.com`

## Default to read-only

Do not deploy Modal, mutate the Sheet, or send Slack messages unless the user
explicitly asks. Never expose secrets or commit credentials.
