# Claude Code Context: Technology-Based Outreach

Read `AGENTS.md` first. This directory is a standalone downstream outreach
system and must not depend on files in a parent repository.

The production path is:

`technology-sourced Companies -> deterministic context -> up to 3 decision-makers -> email enrichment -> Contacts -> dedicated Lemlist email/LinkedIn-only campaigns`

Start with `run_system.py`, `config.json`, `feeder_config.json`, and
`prepare_context.py`. `modal_app.py` contains the complete cloud entrypoint;
n8n workflow `hrG8M9V0lJhCAhu8` invokes it daily. The shared limit is 30 total
contacts per Europe/Sofia day.

Use dry runs and tests by default. Do not execute production, deploy, change
external resources, or reveal secrets without explicit user authorization.
