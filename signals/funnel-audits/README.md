# Funnel and Email Audits

This directory is the complete standalone system. It contains the upstream
`funnel_audit` browser/monitoring engine, `modal_app.py`, its dependency lock,
the downstream contact pipeline, and a local Lemlist feeder. Run commands from
this directory; no parent-repository runtime files are required.

Start with `AGENTS.md` for architecture, production resources, safe commands,
and change guardrails. See `AUDIT_ENGINE_README.md` for the detailed upstream
audit-engine reference.

This signal is different from event-based LinkedIn signals.

It starts with a website, performs a controlled transaction such as a form
submission or booking, and monitors the resulting pipeline for up to ten
days. A lead is not eligible for outreach until the audit is complete and a
defensible gap is recorded.

## Input

- Company name
- Website or direct funnel URL
- Transparent audit identity
- Dedicated monitored inbox

## Source of truth

Audit state is stored in the native Google Sheet:

https://docs.google.com/spreadsheets/d/1UD1tPrjXy8Hr3l5tAcLALHqa30IJ-AZeO0f4_DbGYAM/edit

The local CSV is no longer used.

The same spreadsheet now has two logical tabs:

- `Leads`: company-level audit inputs, state, and verified opportunities.
- `Contacts`: person-level decision makers extracted from qualified company
  rows. These rows feed the `Pipeline gap detected` Lemlist campaign.

## State flow

1. `queued`
2. `discovery_complete`
3. `awaiting_required_input`
4. `submitted`
5. `monitoring`
6. One terminal result:
   - `opportunity_detected`
   - `no_gap_detected`
   - `manual_review`
   - `audit_failed`
   - `do_not_contact`
7. `outreach_ready` only after an opportunity has evidence and a concise
   outreach reason.

## What is audited

Technical:

- Delayed, scroll-triggered, exit-intent, and mobile popups
- Popup primary and secondary CTA behavior
- Dynamically mounted iframes and embedded widgets
- Calendly, HubSpot Meetings, Typeform, Tally, and similar embedded flows
- Form availability and submission
- Error handling
- Confirmation page or redirect
- Confirmation email
- Delivery speed
- Broken links or attachments
- Follow-up timing
- Calendar and next-step clarity

Marketing:

- Subject clarity
- Whether the promised asset or action is delivered immediately
- Readability and length
- Number and clarity of calls to action
- Relevance of the next step
- Follow-up copy quality

Inbound email is collected once per scheduler cycle and attributed to an audit
using sender-domain, company, and domain evidence. Messages with weak or
ambiguous correlation remain unassigned for review; the system never assigns a
shared-inbox message to whichever audit happens to run first.

Ordinary forms are replayed from the exact discovered form fingerprint. A click
does not count as a submission: monitoring begins only after an authoritative
success message or confirmation redirect is observed.

## Qualification rules

- A verified technical failure can create an opportunity immediately.
- A CTA must not be marked broken merely because the top-level URL does not
  change.
- After every CTA click, inspect new iframes, frames, dialogs, modals, portals,
  shadow DOM hosts, and visible DOM mutations before classifying the result.
- An embedded widget counts as a successful next step only when it is visible,
  loaded, and contains the expected booking or form content.
- Loading states and third-party widgets should receive a reasonable wait
  window before failure classification.
- Copy-only findings require at least two meaningful weaknesses.
- Unobservable CRM or routing problems must not be claimed as facts.
- `no_gap_detected` audits remain stored and never enter outreach.
- Only `outreach_ready` audits may be passed to a sequence.

## Decision-maker extraction

`extract_contacts.py` reads qualified company rows from the company audit tab
and appends up to three decision makers to the `Contacts` tab.

Qualified company rows are rows with `status` or `audit_status` equal to
`outreach_ready` or `opportunity_detected`, unless `do_not_sequence` or
`do_not_contact` is truthy. The legacy local checker's `signal_found=true` also
qualifies a row.

The default provider chain is:

1. Lemlist database by exact company domain.
2. Apollo by exact company domain only when Lemlist returns zero contacts.

Lemlist contacts usually include emails and are inserted with blank `status`,
which makes them feeder-ready. Apollo fallback contacts are enriched only when
needed; contacts without an email are inserted with `status=needs_email` and
`email_status=needs_email`; the Lemlist feeder will skip them until email
discovery is handled.

The default title priority is founder, co-founder, CEO, owner, managing
director, head of operations, and operations lead. Provider searches run
domain-only first and then rank/filter locally so non-standard titles are not
missed.

Usage:

```bash
python3 signals/funnel-audits/prepare_outreach_context.py
python3 signals/funnel-audits/extract_contacts.py
python3 signals/funnel-audits/sync_contact_context.py
```

Dry run:

```bash
python3 signals/funnel-audits/prepare_outreach_context.py --dry-run
python3 signals/funnel-audits/extract_contacts.py --dry-run
python3 signals/funnel-audits/sync_contact_context.py --dry-run
```

`prepare_outreach_context.py` fills missing `opener` and `solution_angle`
values on qualified company rows before contacts are generated. Existing
values are preserved unless `--force` is used.

`sync_contact_context.py` copies company-level gap context into existing
`Contacts` rows and syncs plugged lead variables back into Lemlist. Use
`--force` when the context template changes and existing contact variables
should be refreshed.

Safe static CSV test mode:

```bash
python3 signals/funnel-audits/extract_contacts.py --static-contacts-csv contacts.csv --dry-run
```

Google Sheets require either `GOOGLE_APPLICATION_CREDENTIALS` or
`GOOGLE_SERVICE_ACCOUNT_JSON`. The script also supports CSV mode for local
testing with `--companies-csv` and `--contacts-csv`.

Provider credentials:

- `LEMLIST_API_KEY`
- `APOLLO_API_KEY` for zero-Lemlist-contact fallback and email enrichment

The script loads repo-level `.env` automatically. This audit contact extraction
step does not automate LinkedIn. It only reads database results and stores
profile URLs when providers return them.

Operational guardrails:

- The company tab is updated with contact-generation fields:
  `contacts_status`, `contacts_generated_at`, `contacts_found_count`,
  `contacts_ready_count`, `contacts_needs_email_count`,
  `contacts_duplicates_skipped`, and `contacts_error`.
- Rows marked `contacts_generated` or `no_new_contacts` are skipped on later
  runs.
- Rows marked `contacts_failed` are skipped unless `--retry-failed` is used.
- `--force` ignores the contact-generation status and reruns qualified rows.
- `--dry-run` does not append contacts or update company guardrail fields.

## Email discovery for Instantly fallback contacts

`enrich_missing_emails.py` processes `Contacts` rows with `status=needs_email`.
It uses Lemlist's bulk enrichment API with `find_email`.

Start enrichment jobs:

```bash
python3 signals/funnel-audits/enrich_missing_emails.py --mode start --dry-run
python3 signals/funnel-audits/enrich_missing_emails.py --mode start
```

Poll enrichment results:

```bash
python3 signals/funnel-audits/enrich_missing_emails.py --mode poll --dry-run
python3 signals/funnel-audits/enrich_missing_emails.py --mode poll
```

Rows that find an email are updated with the email and blank `status`, making
them feeder-ready. Rows where Lemlist cannot find an email become
`email_not_found`.

Apollo fallback for rows where Lemlist did not find an email:

```bash
python3 signals/funnel-audits/enrich_missing_emails.py --mode apollo --dry-run
python3 signals/funnel-audits/enrich_missing_emails.py --mode apollo
```

Rows where Apollo finds an email are also cleared to blank `status`, making
them feeder-ready for the normal `Pipeline gap detected` campaign.

Final LinkedIn-only fallback:

```bash
python3 signals/funnel-audits/enrich_missing_emails.py --mode finalize-linkedin-only --dry-run
python3 signals/funnel-audits/enrich_missing_emails.py --mode finalize-linkedin-only
```

This converts unresolved rows that still have a LinkedIn URL into
LinkedIn-only Lemlist rows. The script generates a deterministic placeholder
email at `pipeline-gap-linkedin-only.invalid`, sets
`email_status=placeholder_linkedin_only`, and routes the row to
`Pipeline gap detected - LinkedIn only`.

This step consumes Lemlist enrichment credits. Run it intentionally, usually
after reviewing how many `needs_email` rows were created.

## Full pipeline runner and monitoring

Run the whole operational chain in one command:

```bash
python3 signals/funnel-audits/run_pipeline_gap_system.py --dry-run --skip-apollo
```

Live run:

```bash
python3 signals/funnel-audits/run_pipeline_gap_system.py
```

In production this runner is mounted into the existing Modal
`funnel-audit-system` app and called from its scheduled dispatcher. That app
runs every two hours.

The runner executes:

1. Prepare outreach context.
2. Extract contacts.
3. Sync contact context and Lemlist variables.
4. Start/poll Lemlist email enrichment.
5. Run Apollo fallback, unless `--skip-apollo` is passed.
6. Finalize LinkedIn-only fallback rows.
7. Feed normal and LinkedIn-only Lemlist campaigns.
8. Print the monitor report.

Standalone monitoring:

```bash
python3 signals/funnel-audits/monitor_pipeline_gap_system.py
```

The monitor reports counts for contact-generation statuses, contact statuses,
email statuses, failed rows, rows still needing email work, contacts missing
gap context, and plugged contacts missing Lemlist lead IDs.

## Current self-test

Target: `https://aiessentials.us`

The homepage has no native inline form. A delayed popup appears after about 30
seconds and offers a Free AI Revenue Leak Report.

Iframe-aware verification:

- The primary `Get My AI Revenue Leak Report` CTA mounts a visible Calendly
  iframe for the correct Free Revenue Leak Report event.
- The user verified that the secondary `Book a Call` CTA opens the same
  embedded booking flow.
- No technical gap is currently verified.

The earlier navigation-only test produced a false positive because embedded
widgets do not change the top-level page URL. The audit now awaits a booking
slot before submission and email monitoring can continue.
