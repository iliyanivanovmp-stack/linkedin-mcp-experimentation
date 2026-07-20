# Claude Code Context: Pipeline Engine Hiring Outreach

Read `AGENTS.md` before making changes. This directory is intentionally
standalone and must remain independent from Funnel Audit, Technology-Based
Outreach, and any parent repository.

The production path is:

`LinkedIn jobs -> Leads -> hiring context -> up to 3 decision-makers -> email enrichment -> Contacts -> dedicated Lemlist email/LinkedIn-only campaigns`

Start with `run_system.py`, `config.json`, `sourcing_config.json`, and
`feeder_config.json`. Cloud execution is defined entirely in `modal_app.py` and
scheduled by n8n workflow `HoBUmGREhd4uE5F3`. Production is capped at 30 total
contacts per Europe/Sofia day across both campaigns.

Default to read-only inspection and tests. Use `--dry-run`, never expose
secrets, and do not trigger production, deploy Modal, or mutate Sheets/Lemlist
without explicit user authorization.
