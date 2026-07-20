# Technology-Based Outreach — Agent Guide

This folder is a standalone production workflow. It begins after company and
technology sourcing. The separate `technology-stack-sourcing` skill writes
qualified companies into this workbook; this folder owns everything from the
company row onward.

## Purpose and flow

1. Read qualified rows from `Companies`.
2. `prepare_context.py` turns detected technologies into a short opener,
   three automation opportunities, and an outreach angle.
3. `extract_contacts.py` finds up to three decision-makers per company.
4. `enrich_missing_emails.py` uses Lemlist and Apollo for missing emails.
5. `feed_lemlist.py` routes email-ready and LinkedIn-only contacts to separate
   dedicated campaigns with technology-specific custom variables.

Both sourcing modes use the same workbook and campaigns. The combined cap is
30 contacts per Europe/Sofia calendar day.

## Production resources

- Workbook: `1TVUzhRrX0OPJps6OqwV9yD7Bth5k0OV7NhOQjkqp3vQ`
- Tabs: `Companies`, `Contacts`
- Email campaign: `Technology-based outreach` (`cam_rQA2i9v5GjYdGHJtR`)
- LinkedIn-only campaign: `Technology-based outreach - LinkedIn only`
  (`cam_rKrkfj9P3hihTw9oF`)
- Modal app: `technology-based-outreach`
- Modal secret: `technology-outreach-secrets`
- n8n workflow: `Technology-Based Outreach — Daily`
  (`hrG8M9V0lJhCAhu8`), active daily at 08:15

## Important files

- `run_system.py`: complete downstream orchestrator.
- `modal_app.py`: Modal functions and protected n8n HTTP endpoint.
- `config.json`: workbook, qualification, providers, and title rules.
- `feeder_config.json`: campaign routing, variables, and daily cap.
- `prepare_context.py`: deterministic technology personalization.
- `setup_workbook.py`: idempotent workbook schema setup.

## Safe commands

```bash
cp .env.example .env
python3 run_system.py --dry-run --company-limit 3
PYTHONPATH=. python3 -m pytest -q
python3 -m compileall -q .
modal deploy modal_app.py
```

Do not change the sourcing skill, production campaigns, Sheet rows, n8n
schedule, Modal deployment, or 30-contact cap without explicit authorization.
Do not connect this workflow to Funnel Audit or Hiring Outreach. Never commit
credentials or `.env`. Lemlist sequences and senders are managed in Lemlist.
