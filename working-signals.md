# Working Signals and Pipeline Handoff

Last updated: 2026-06-22

## Pipeline-ready signals

| Signal type | Status | Current evidence | Production work remaining |
|---|---|---|---|
| `competitor_commenter` | Working locally | Live test returned 5 commenters with names, headlines, profile URLs, comments, and source posts. A second run exported no duplicates. | Move the authenticated LinkedIn browser to a persistent cloud worker and schedule it. |
| `competitor_reaction` | Working locally | Live test returned 28 reactors with names, headlines, profile URLs, and source context. A second run exported no duplicates. | Move the authenticated LinkedIn browser to a persistent cloud worker and schedule it. |
| `manual_process_job_posting` | Working | Live LinkedIn test found an Operations Manager job containing reporting, records, meetings, follow-ups, coordination, and administrative work. | Schedule small read-only searches and add later ICP qualification if required by a pipeline. |
| `pipeline_engine_hiring_intent` | Working | A live one-search test found 12 recent US jobs. The first 10 inspected were correctly classified as SDR/BDR hiring opportunities and written with job-level deduplication. | Add company/contact enrichment before converting `opportunity_detected` rows to `outreach_ready`. |
| `broken_website_funnel` | Working | Live test checked the homepage and 2 funnel pages. The checker correctly produced no lead because nothing was broken. | Feed target domains into the checker. Full form submission testing remains out of scope. |

These signals are sufficient to start building downstream pipelines. Commenter
and reaction collection still runs locally until the cloud LinkedIn worker is
deployed.

## Reusable sourcing and enrichment skill

Technology detection is no longer classified as a live signal. It is available
as the global Codex skill:

`$technology-stack-sourcing`

Modes:

- `discover`: find companies using specified technologies.
- `enrich`: check technologies used by known companies.

The skill uses Apollo, Lemlist, and current website evidence. Existing rows
with `technology_integration_opportunity` remain valid historical data, but new
technology work should run through the skill.

## Disabled or future signals

| Signal | Status | Reason |
|---|---|---|
| Tool switching | Disabled; pending future review | LinkedIn post search was too noisy. Complex Boolean searches returned no results, while broad searches returned unrelated posts. |
| New leader joins | Future | Not needed for the current pipelines. |
| Promotions and job changes | Future | Similar to new-leader signals and not needed for the current pipelines. |

## Signal still requiring configuration

| Signal | Remaining work |
|---|---|
| Keyword pain conversations | Replace the paid social-post search endpoint with a reliable LinkedIn-only discovery method, then retest result quality. |

## Shared lead sheet

All pipeline-ready signals now append qualified findings to:

`signals/exports/pipeline_leads.csv`

Required routing column:

- `signal_type`

Supported values:

- `competitor_commenter`
- `competitor_reaction`
- `manual_process_job_posting`
- `pipeline_engine_hiring_intent`
- `broken_website_funnel`

Downstream pipelines should select rows by exact `signal_type`.

The shared schema also includes:

- Person and company identity fields
- Company LinkedIn URL, official website, and normalized domain
- LinkedIn profile or company domain
- Source URL
- Evidence
- Detection timestamp
- JSON metadata
- A stable internal `lead_key`

## Duplicate handling

Duplicates are rejected using:

1. An explicit event key when the signal provides one. Hiring intent uses
   `job:<LinkedIn job ID>`, allowing different jobs from the same company.
2. LinkedIn profile URL for person leads.
3. Company domain for company leads.
4. Company name when no domain is available.
5. Source URL as the final fallback.

Deduplication is scoped to `signal_type + lead_key`. This prevents the same
lead from being inserted repeatedly for the same signal while preserving a
different valid signal for the same person or company.

Signal-specific exports remain available for debugging. The shared lead sheet
is the source intended for downstream pipeline routing.

Stateful funnel tests use a separate audit sheet:

https://docs.google.com/spreadsheets/d/1UD1tPrjXy8Hr3l5tAcLALHqa30IJ-AZeO0f4_DbGYAM/edit

They enter `pipeline_leads.csv` only after a verified gap is marked
`outreach_ready`.

Pipeline Engine hiring opportunities use this canonical Google Sheet:

https://docs.google.com/spreadsheets/d/1OXRX2OSokVuE6s4ZNFVCSYc97Lbt28SLE96L3GzdcYI/edit

It includes company identifiers, the job URL and description, compensation
when disclosed, evidence, scoring, and routing status.
