# Pipeline Gap Detected: Next Steps

System 1 is now wired from a qualified company opportunity to Lemlist campaign
ingestion. The remaining work is mostly around contact generation, email
discovery, and operationalizing the flow.

## 1. Contact Generation Source

Decide how each qualified company gets three decision-maker contacts.

Near-term option:

- Use an upload/static CSV flow to populate the `Contacts` tab safely.

Later options:

- Apollo
- Other B2B contact databases
- Internal/manual research workflow
- Provider-specific exports imported into the `Contacts` tab

This is tightly connected to email discovery because some contact sources return
verified emails directly, while others only return names/titles/profile URLs and
need a separate email-finding step.

## 2. Email Discovery And Enrichment Strategy

The Lemlist feeder currently requires an email before it can insert a lead.

Decide the cheapest reliable way to attach usable emails to the three generated
decision makers.

Options to review later:

- Apollo email data
- Dedicated email finder tools
- Lemlist enrichment
- Instantly database
- Lemlist database
- Hybrid flow: contact source first, email verifier/finder second

For now, enrichment remains disabled in Lemlist. Rows should arrive in
`Contacts` with emails already present.

## 3. Contact Extraction Production Mode

`extract_contacts.py` already exists, but it intentionally fails closed unless a
safe non-LinkedIn provider or static contacts CSV is provided.

Next implementation target:

- Make the upload/static CSV path the first production-safe contact source.
- Append up to three contacts per qualified company into `Contacts`.
- Preserve all opportunity context from the company row.
- Avoid duplicate contacts and duplicate company processing.

## 4. Lemlist Campaign Sequence

The `Pipeline gap detected` campaign exists and accepts leads, but the actual
outbound sequence is not built yet.

The sequence should use the custom variables now stored on each Lemlist lead:

- `{{opener}}`
- `{{gapReason}}`
- `{{outreachReason}}`
- `{{icebreaker}}`
- `{{evidence}}`
- `{{sourceUrl}}`
- `{{auditCompanyKey}}`

Later decision:

- Universal sequence using variables
- AI-generated unique emails per lead
- Hybrid: static structure plus AI-personalized snippets

## 5. Operational Guardrails

Add checks and reporting before this is treated as production.

Needed guardrails:

- Skip `do_not_sequence` companies.
- Skip companies without verified opportunities.
- Prevent duplicate companies from generating duplicate contact batches.
- Prevent duplicate contacts from being inserted into Lemlist.
- Flag contacts missing email.
- Track failed rows with clear error messages.
- Keep test rows isolated from real outreach.

## 6. Automation Schedule

The scripts currently work manually. The final system needs scheduled execution.

Target flow:

1. Audit writes qualified company opportunities to `Website Pipelines`.
2. Contact generation/upload creates three decision makers.
3. Contacts are written to the `Contacts` tab.
4. Lemlist feeder runs on blank-status contact rows.
5. Successful rows are marked `plugged`.
6. Failed rows are marked `failed` with a reason.

Possible schedulers:

- n8n
- cron/local runner
- Modal
- Another lightweight job runner

## Immediate Next Step

Start with point 1:

Design and implement the upload/static CSV contact generation path, while
accounting for point 2 by requiring or clearly marking whether uploaded contacts
already include verified emails.
