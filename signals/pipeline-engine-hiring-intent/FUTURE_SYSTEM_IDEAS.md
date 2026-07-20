# Future System Ideas

## Current finished system

The current system finds companies with open roles that indicate active
pipeline-building intent. It searches LinkedIn jobs for SDR, BDR, appointment
setter, lead generation, outbound sales, and related pipeline roles, then fills
the hiring opportunities sheet.

It records:

- Job ID
- Job URL
- Company name
- Company LinkedIn URL
- Company website
- Company domain
- Job title
- Job description
- Compensation when disclosed
- Role family
- Intent score
- Evidence terms
- Offer angle
- Outreach reason
- Status

The current system is a collector and sheet filler. It does not need to send
outreach by itself.

## Future pipeline role

This system should become the front end of a Pipeline Engine outreach pipeline.

The finished pipeline can:

1. Detect companies hiring specific pipeline or outbound roles.
2. Qualify whether the company fits the target ICP.
3. Find the most relevant decision maker.
4. Enrich contact details.
5. Generate outreach based on the open role.
6. Route qualified rows into a campaign.
7. Sync replies and statuses back to the sheet or CRM.

## Future bots

### Hiring Signal Collector

Run the LinkedIn job search on a safe schedule, inspect a limited number of job
descriptions, classify role families, dedupe by LinkedIn job ID, and write new
opportunities to the sheet.

### Company Fit Qualifier

Check whether the company is a good fit before outreach. Preferred targets are
B2B agencies, service companies, lead generation agencies, marketing agencies,
sales or outbound agencies, consulting companies, and operations-heavy small
businesses.

### Decision Maker Finder

Find the best person for outreach, usually founder, co-founder, CEO, owner,
managing director, head of sales, head of growth, or operations/revenue
operations leader.

### Contact Enrichment Bot

Add verified email, LinkedIn profile URL, and any useful contact metadata. Do
not move a row to outreach until a relevant contact is found.

### Role-Based Message Bot

Draft short messages using the open role as the trigger. The angle is the
infrastructure around the hire: targeting, lead sourcing, sequences, follow-up,
CRM updates, attribution, and reporting.

### Sequence Launcher

Move only `outreach_ready` rows into the selected outreach tool. Keep campaign
routing separate from the LinkedIn job collector.

### Reply and Nurture Bot

Watch replies, classify them, draft responses, and create follow-up tasks for
interested or not-now prospects.

### Status Sync Bot

Keep sheet statuses clean across collection, qualification, enrichment,
outreach, replies, and disqualification.

## Future statuses

Recommended status flow:

- `opportunity_detected`
- `company_qualified`
- `not_fit`
- `contact_needed`
- `contact_found`
- `outreach_ready`
- `sequenced`
- `replied`
- `meeting_booked`
- `do_not_contact`

## Outreach rules

- Do not say automation replaces the role they are hiring for.
- Do not imply the company is making a mistake by hiring.
- The offer is the pipeline infrastructure around the role.
- Use the exact job title and job URL as the reason for reaching out.
- Keep the first message focused on one verified signal: the open role.
