# Claude Code Context: Pipeline Engine Hiring Outreach

Read `AGENTS.md` before making changes. This directory is a production component
of the parent `linkedin-mcp-experimentation` repository. Use the parent
repository for Git policy, LinkedIn session operations, and shared signal
routing, while keeping Funnel Audit and Technology-Based Outreach out of this
runtime bundle.

The production path is:

`LinkedIn jobs -> Leads -> hiring context -> up to 3 decision-makers -> email enrichment -> Contacts -> dedicated Lemlist email/LinkedIn-only campaigns`

Start with `run_system.py`, `config.json`, `sourcing_config.json`, and
`feeder_config.json`. Cloud execution is defined in `modal_app.py`; n8n workflow
`HoBUmGREhd4uE5F3` remains inactive until launch. Production is capped at 30
total contacts per Europe/Sofia day across both campaigns.

Default to read-only inspection and tests. Use `--dry-run`, never expose
secrets, and do not trigger production, deploy Modal, or mutate Sheets/Lemlist
without explicit user authorization.
