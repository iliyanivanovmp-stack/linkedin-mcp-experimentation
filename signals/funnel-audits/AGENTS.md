# Funnel Audit System — Agent Guide

This folder contains the complete standalone Funnel Audit system: the upstream
browser/audit engine, persistent Modal scheduler, downstream contact pipeline,
email enrichment, Lemlist feeder, monitoring, tests, and deployment entrypoint.
It must remain independent from Hiring Outreach and Technology-Based Outreach.

## Purpose and flow

1. The `funnel_audit` package reads companies from `Website Pipelines`.
2. It discovers lead magnets, forms, booking flows, and other funnel entry
   points, performs only authorized submissions, and stores evidence/state in
   the `funnel-audit-data` Modal volume.
3. Gmail monitoring and finalization determine whether a real pipeline gap was
   detected. Only qualified rows become outreach-ready.
4. `prepare_outreach_context.py` creates gap-specific personalization.
5. `extract_contacts.py` finds up to three decision-makers per company.
6. `sync_contact_context.py` copies company context to contact rows and can
   synchronize variables for already-plugged Lemlist leads.
7. `enrich_missing_emails.py` performs Lemlist enrichment and Apollo fallback.
8. Local `feeder.py` sends contacts to the email or LinkedIn-only campaign.
9. `monitor_pipeline_gap_system.py` reports failures and attention states.

## Production resources

- Workbook: `1UD1tPrjXy8Hr3l5tAcLALHqa30IJ-AZeO0f4_DbGYAM`
- Tabs: `Website Pipelines`, `Contacts`
- Email campaign: `Pipeline gap detected` (`cam_8LG46LcGQq84uymSH`)
- LinkedIn-only campaign: `Pipeline gap detected - LinkedIn only`
  (`cam_visJbtfNqYwGtRtwx`)
- Modal app: `funnel-audit-system`
- Modal volume: `funnel-audit-data`
- Modal schedule: `0 */2 * * *` (every two hours)
- Modal secrets: `funnel-audit-openai`, `funnel-audit-google`,
  `funnel-audit-config`, `funnel-audit-composio`,
  `pipeline-gap-downstream-secrets`

The audit engine processes at most 10 new audits per cycle and monitors an
audit for up to 10 days. `LIVE_SUBMISSIONS` is a safety-critical setting.

## Important files

- `modal_app.py`: complete Modal image, functions, schedule, volume, secrets,
  and downstream dispatcher.
- `funnel_audit/`: upstream discovery, browser, AI, Google, database, models,
  and orchestration code.
- `run_pipeline_gap_system.py`: downstream start-to-finish orchestrator.
- `contact_extraction_config.json`: contact providers, Sheet tabs, and titles.
- `feeder.py` / `feeder_config.json`: local Lemlist routing implementation.
- `AUDIT_ENGINE_README.md`: detailed upstream setup and behavior.
- `README.md`: downstream contact and enrichment reference.
- `scripts/authorize_google.py`: one-time local Google OAuth authorization.

## Safe commands

```bash
cp .env.example .env
uv sync --extra dev
uv run pytest -q
python3 -m compileall -q .
python3 run_pipeline_gap_system.py --dry-run --skip-apollo --no-slack-alerts
modal deploy modal_app.py
```

Default to `LIVE_SUBMISSIONS=false`. Do not submit forms, book meetings, cancel
bookings, update the Modal database, deploy, invoke production functions,
change campaign IDs, or remove leads without explicit user authorization.
Never commit `.env`, Google OAuth JSON, service-account credentials, API keys,
browser artifacts, or database/evidence files.

When changing the upstream audit state machine, update `tests/test_core.py`.
When changing downstream routing, verify both `feeder_config.json` sources and
the exact `Contacts` columns. Lemlist sequences remain outside this codebase.
