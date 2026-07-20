# Lemlist Feeder

Shared final step for the three outreach systems.

The feeder reads configured lead sheets, selects rows with a blank `status`,
adds person-level leads to the mapped Lemlist campaign, and writes the result
back to the same row.

When a campaign ID is blank, the feeder resolves it from the exact campaign
name at runtime. Ambiguous or missing names fail closed.

## Campaigns

- `Technology-based outreach`
- `Pipeline gap detected`
- `LinkedIn job signals`

The technology campaign is configured in the personal `Iliyan Ivanov's Team`
workspace through the official Lemlist MCP. Other campaign sources retain their
independently configured IDs.

The hiring and pipeline-gap Google Sheet IDs were already documented in this
repo. The pipeline-gap feeder source reads the `Contacts` tab, not the company
audit tab. Technology sourcing uses its dedicated production workbook and
reads person-level rows from its `Contacts` tab.

The feeder is one shared engine, but custom variables are source-specific.
Each source may define a `custom_variables` mapping, `daily_limit`, and
`timezone` in `config.json`. This prevents variables from one campaign leaking
into another while preserving shared validation, deduplication, and Lemlist API
handling.

## Required Columns

The feeder ensures these output columns exist:

- `status`
- `lemlist_campaign`
- `lemlist_campaign_id`
- `lemlist_lead_id`
- `plugged_at`
- `lemlist_error`

Rows are considered ready when `status` is blank. Successful rows become
`plugged`; failed rows become `failed`.

## Required Lead Data

Each ready row must contain:

- a person name, or first and last name
- company name
- company domain or website
- email
- source URL or evidence
- an icebreaker/personalization/outreach reason

The feeder accepts common column aliases such as `person_name`, `firstName`,
`email`, `company_domain`, `person_linkedin_url`, `source_url`, `evidence`,
`outreach_reason`, and `icebreaker`.

## Usage

Dry run:

```bash
python3 signals/lemlist-feeder/feeder.py --dry-run
```

Live run:

```bash
python3 signals/lemlist-feeder/feeder.py
```

The feeder automatically loads `LEMLIST_API_KEY` from the repo-level `.env`
file when present. An exported environment variable still takes precedence.

Google Sheets require `gspread` and `google-auth`, plus either:

- `GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json`
- `GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'`

CSV sources work without Google credentials.

## Lemlist Custom Variables

The feeder sends sheet context into Lemlist through the lead variables endpoint.
Campaign copy can reference these variables:

- `{{icebreaker}}`
- `{{gapReason}}`
- `{{outreachReason}}`
- `{{opener}}`
- `{{solutionAngle}}`
- `{{evidence}}`
- `{{sourceUrl}}`
- `{{auditCompanyKey}}`
- `{{detectedAt}}`
- `{{companyWebsite}}`
- `{{companyDomain}}`
- `{{jobTitle}}`

Common sheet aliases are accepted, including `gap_reason`, `detected_gap`,
`outreach_reason`, `opportunity_reason`, `opener`, `email_opener`,
`solution_angle`, and `recommended_solution`.

The technology source sends only:

- `{{technologies}}`
- `{{opener}}`
- `{{automationOpportunity1}}`
- `{{automationOpportunity2}}`
- `{{automationOpportunity3}}`
- `{{outreachAngle}}`
- company and source fields

Its configured daily limit is 30 contacts in `Europe/Sofia`. The feeder counts
contacts already plugged today, so repeated scheduled runs cannot exceed the
daily cap.
