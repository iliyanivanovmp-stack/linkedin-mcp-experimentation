# Pipeline Engine Hiring Intent

## Purpose

Detect companies actively hiring outbound-sales or pipeline-operations roles.
The open job is the live signal: the company has current urgency and budget for
pipeline capacity.

The offer is the infrastructure around the role, not a claim that automation
fully replaces the employee.

## Signal type

`pipeline_engine_hiring_intent`

## Role families

- `direct_outbound`: SDR, BDR, appointment setter, lead generation, outbound
  sales representative
- `pipeline_operations`: sales operations, revenue operations, CRM and
  marketing operations
- `growth_demand`: demand generation, growth and related business development
  roles

Direct outbound roles receive the highest score.

## Output

Qualified opportunities append to:

- `signals/exports/pipeline_engine_hiring_opportunities.csv`
- `signals/exports/pipeline_leads.csv`

Each hiring event uses `job:<LinkedIn job ID>` as its deduplication key. This
allows the same company to generate a new opportunity when it posts a genuinely
different role, while preventing the same job from being added twice.

For every qualified job, the collector reads LinkedIn's exact company reference
from the job page. It then checks the company's LinkedIn About page and records:

- Company LinkedIn URL
- Official website
- Normalized company domain

If the About page cannot be read, the hiring event is still retained with the
company LinkedIn URL when available. This avoids discarding a valid signal
because enrichment temporarily failed.

The dedicated hiring sheet also stores the complete LinkedIn job description.
When compensation is explicitly stated, it records the original compensation
text and parsed minimum, maximum, currency, and pay period. Compensation fields
remain empty when the listing does not disclose payment.

## Canonical Google Sheet

All production hiring opportunities are written to:

https://docs.google.com/spreadsheets/d/1OXRX2OSokVuE6s4ZNFVCSYc97Lbt28SLE96L3GzdcYI/edit

Tab: `Leads`

The local CSV remains a debugging and recovery mirror. The Google Sheet is the
canonical source for downstream contact finding.

## Safety

- Read-only LinkedIn activity
- No applications, follows, messages, or connections
- Small search and job-detail limits
- Daily scheduling is appropriate

## Status flow

New qualified rows enter as `opportunity_detected`. Company and contact
qualification can later move them to `outreach_ready`.
