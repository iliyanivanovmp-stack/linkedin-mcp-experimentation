# Pipeline Engine Hiring Outreach — Agent Guide

This folder is the Pipeline Engine hiring-outreach production component inside
the parent `linkedin-mcp-experimentation` repository. The parent repository is
the source of Git policy, LinkedIn session operations, and shared signal-routing
documentation. The Modal runtime bundle remains self-contained so it can deploy
this directory without packaging unrelated sibling systems. Keep Funnel Audit
and Technology-Based Outreach isolated from this runtime.

## Purpose and flow

1. `collect_hiring_signals.py` searches recent LinkedIn jobs for pipeline,
   outbound, sales-operations, RevOps, demand-generation, and growth roles.
2. New `job_id` values are appended to the Google Sheet `Leads` tab, with a
   persistent cap of 10 unique companies per Europe/Sofia calendar day.
   If LinkedIn exposes a reachable hiring contact, the same row stores their
   profile in `poster_linkedin_url`.
3. `prepare_context.py` creates hiring-specific openers and automation angles.
4. `extract_contacts.py` finds at most three decision-makers per company.
5. `enrich_missing_emails.py` uses Lemlist enrichment and Apollo fallback.
6. `feed_lemlist.py` sends email-ready contacts to the email campaign and
   unresolved LinkedIn profiles to the LinkedIn-only campaign.

The combined cap is 30 contacts per Europe/Sofia calendar day.

## Production resources

- Workbook: `1OXRX2OSokVuE6s4ZNFVCSYc97Lbt28SLE96L3GzdcYI`
- Tabs: `Leads`, `Contacts`
- Email campaign: `Pipeline Engine hiring outreach`
  (`cam_7pAgGFbaBpYGw3XQo`)
- LinkedIn-only campaign: `Pipeline Engine hiring outreach - LinkedIn only`
  (`cam_5o7M8GxYwgoMeygfG`)
- Modal app: `pipeline-engine-hiring-outreach`
- Modal secret: `pipeline-engine-hiring-outreach-secrets`
- Dedicated trigger secret: `pipeline-engine-hiring-trigger-secret`
- Dedicated Slack secret: `pipeline-engine-hiring-slack` with
  `SLACK_BOT_TOKEN` and `SLACK_CHANNEL_ID`; Modal posts completion messages
  directly through `chat.postMessage`.
- Job sourcing uses LinkedIn's public guest jobs API and does not mount an
  authenticated LinkedIn browser session. This isolates the pipeline from MCP
  cookie expiry and reauthentication in other systems.
- n8n workflow: `Pipeline Engine Hiring Outreach — Daily`
  (`HoBUmGREhd4uE5F3`), configured for 08:45 and intentionally inactive until
  the launch checklist passes

## Important files

- `run_system.py`: complete orchestrator.
- `modal_app.py`: deployable Modal entrypoint and protected HTTP endpoint.
- `recover_company_domains.py`: website/Apollo recovery for missing domains.
- `config.json`: workbook, title filters, providers, cap, and contact rules.
- `sourcing_config.json`: LinkedIn job search and qualification rules.
- `feeder_config.json`: campaign IDs, routing, custom variables, shared cap.
- `lead_sheet.py`: local shared-sheet helper copied into this folder.
- `setup_workbook.py`: idempotent workbook schema setup.

## Safe commands

```bash
cp .env.example .env
python3 run_system.py --dry-run --company-limit 3 --skip-sourcing
PYTHONPATH=. python3 -m pytest -q
python3 -m compileall -q .
modal deploy modal_app.py
```

`--dry-run` must never mutate local state, Google Sheets, or Lemlist, including
when sourcing is enabled.

Do not run a live pipeline, deploy Modal, edit campaign IDs, change the daily
cap, delete Sheet rows, or remove Lemlist leads unless the user explicitly asks.
Never commit `.env`, credentials, trigger tokens, or LinkedIn session data.
The HTTP trigger accepts the token only through an `Authorization: Bearer` header.
Deploy only after the n8n trigger uses that header.

When changing contact selection, update both `config.json` and the title-matcher
tests. When changing Lemlist variables, update `feeder_config.json` and verify
the exact Sheet column names. Sequences and senders remain controlled in
Lemlist and are outside this codebase.
