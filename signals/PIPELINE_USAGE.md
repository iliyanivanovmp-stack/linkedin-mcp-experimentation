# How Signals Feed the Three Pipelines

Last updated: 2026-06-22

All qualified findings are written to:

`signals/exports/pipeline_leads.csv`

Downstream workflows route rows using the exact `signal_type`. Multiple signals
can increase a lead's internal score, but the first outreach message should use
only the strongest verified signal.

## Pipeline 1: Funnel and email audit

Primary signal:

- `broken_website_funnel`

Possible supporting signals:

- `technology_integration_opportunity`
- `competitor_commenter`
- `competitor_reaction`

The current broken-funnel signal checks linked funnel pages for HTTP failures.
It does not currently submit forms or monitor received emails.

The production audit should:

1. Take a company website or funnel URL from the lead sheet.
2. Test popups before normal page CTAs, then find a real public opt-in,
   contact, demo, lead-magnet, or booking form.
3. Record the page, fields, consent language, and expected result.
4. Submit a transparent audit identity once.
5. Record the submission time and resulting page or redirect.
6. Monitor a dedicated audit inbox for confirmation, delivery, and follow-up.
7. Check technical delivery, timing, links, next steps, and email copy.
8. Mark the lead as an opportunity only when a defensible gap is found.
9. Mark leads with no gap as `no_gap_detected` and exclude them from outreach.

This is a stateful audit that may remain active for several days.

Popup coverage must include:

- Immediate popup on page load
- Timed popup after at least 30 seconds
- Scroll-depth popup
- Exit-intent popup
- Mobile viewport popup
- Primary and secondary CTA destinations
- Form fields that appear after the CTA
- Iframes and embedded third-party widgets mounted after the CTA

CTA verification order:

1. Top-level navigation or new tab.
2. Newly visible modal or dialog.
3. New iframe/frame and its loaded URL, title, and visible content.
4. Dynamically inserted form, portal, or shadow-DOM widget.
5. Loading and error states after a reasonable wait.

Do not classify a CTA as broken based only on the lack of a URL change.

Audit state is stored separately from immediate lead signals in the native
Google Sheet:

https://docs.google.com/spreadsheets/d/1UD1tPrjXy8Hr3l5tAcLALHqa30IJ-AZeO0f4_DbGYAM/edit

The sheet contains the submission identity, monitoring timestamps, audit
status, verified gaps, outreach reason, and a `do_not_sequence` gate. The lead
sheet should receive the company only after the audit reaches
`outreach_ready`.

## Pipeline 2: AI Brain and integration opportunities

Primary capability:

- `$technology-stack-sourcing` in `enrich` mode

Strong supporting signal:

- `manual_process_job_posting`

The technology signal identifies public tools on a company's website. It should
generate possible integration opportunities without claiming that internal
systems are disconnected.

The same skill can run in `discover` mode to generate new companies from a
target technology or strict technology combination.

If the same company also has a manual-process job signal, its priority rises
because there is stronger evidence that reporting, coordination, records, or
follow-up work may still require people.

## Pipeline 3: Pipeline Engine from hiring intent

Primary signal:

- `pipeline_engine_hiring_intent`

The job-search configuration can target roles such as:

- SDR or BDR
- Appointment setter
- Lead generation specialist
- Outbound sales representative
- Business development roles
- Demand generation roles
- Revenue or sales operations roles
- CRM and marketing operations roles

The message should not claim that automation fully replaces the employee. The
offer is the outbound infrastructure around the role: targeting, lead sourcing,
sequences, follow-ups, CRM updates, attribution, and reporting.

The collector performs one Boolean LinkedIn job search, constrained to the
United States, the past week, and newest-first sorting. It inspects a limited
number of job descriptions, classifies supported role families, and records
each distinct LinkedIn job ID once.

New rows remain `opportunity_detected`. Company fit and a relevant decision
maker must be established before changing the row to `outreach_ready`.

Canonical hiring-signal sheet:

https://docs.google.com/spreadsheets/d/1OXRX2OSokVuE6s4ZNFVCSYc97Lbt28SLE96L3GzdcYI/edit

The sheet stores the role description and, when present, compensation text,
minimum, maximum, currency, and pay period. Missing compensation remains blank.

## Multi-signal handling

Multiple signals affect:

- Lead score
- Priority
- Offer selection
- Supporting research

They do not all appear in the first message. The initial outreach uses one
verified observation: the strongest, most recent, and easiest-to-prove signal.
Other signals can be introduced after the prospect responds.

## Shared routing states

Recommended pipeline states:

- `queued`
- `in_progress`
- `monitoring`
- `opportunity_detected`
- `no_gap_detected`
- `manual_review`
- `audit_failed`
- `do_not_contact`
- `outreach_ready`

Only `outreach_ready` records should enter an outbound sequence.
