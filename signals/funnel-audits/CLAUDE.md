# Claude Code Context: Funnel Audit System

Read `AGENTS.md` before working. This directory now contains both halves of the
standalone production system: the `funnel_audit` audit engine and the
downstream Sheet/contact/Lemlist pipeline.

The production path is:

`Website Pipelines -> browser audit and monitored evidence -> detected gap -> outreach context -> up to 3 decision-makers -> email enrichment -> Contacts -> dedicated Lemlist email/LinkedIn-only campaigns`

`modal_app.py` is the authoritative cloud definition. It mounts the persistent
`funnel-audit-data` volume, uses five named Modal secrets, and dispatches the
full system every two hours. The local Lemlist feeder is `feeder.py`; there is
no dependency on a parent `lemlist-feeder` directory.

Treat live browser submissions and external mutations as high risk. Keep
`LIVE_SUBMISSIONS=false` for tests, prefer dry runs, and do not deploy or invoke
production without explicit authorization. Never reveal or commit secrets.
