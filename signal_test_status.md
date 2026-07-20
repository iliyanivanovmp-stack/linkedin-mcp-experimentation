# Signal Radar Test Status

Last test: 2026-06-22

Test rules used:

- One query, company, profile, post, or job at a time.
- Read-only.
- Pauses between LinkedIn checks.
- No messages, connections, reactions, comments, or follows.
- A zero-result test is valid when the evidence is weak.

| # | Signal | Small test result | Automation status | Main limitation | Folder |
|---|---|---|---|---|---|
| 1 | Competitor complaints | Removed. | Removed | Not needed. | None |
| 2 | Keyword pain conversations | One exact search for “drowning in admin” returned five posts. All five were rejected because they were sellers, educational posts, case studies, or outside the target market. | Automated, but not production-ready | No qualified buyer was found. Search cost and false positives are high. | `signals/keyword-pain-conversations` |
| 3 | Competitor commenters | Ben van Sprundel’s recent posts produced five commenters with names, comments, headlines, profile URLs, and source posts. A second run exported zero duplicates. | Working locally; cloud work remains | The current LinkedIn browser session must be moved to a persistent cloud worker. | `signals/competitor-commenters` |
| 4 | Competitor reactions | The same competitor produced 28 new reactors. They were written to the same sheet as commenters. A second run exported zero duplicates. | Working locally; cloud work remains | Reactions are weaker evidence than comments. Cloud deployment remains. | `signals/competitor-reactions` |
| 5 | Tool adoption or switching | Live tests produced noisy, mostly unrelated results. Complex Boolean searches returned no results, and LinkedIn's Author Keywords filter targets job titles rather than post content. | Disabled; pending future review | Not useful enough for production with the current LinkedIn search capabilities. | `signals/tool-switching` |
| 6 | Technology and integration opportunities | Hybrid tests on `aiessentials.us` and `adstartmedia.com` succeeded. Apollo returned concise exact-company technologies, Lemlist returned broad technology coverage, and website detection verified current public tools. | Reclassified as a skill | This is sourcing/enrichment, not a live signal. Use `$technology-stack-sourcing` in `discover` or `enrich` mode. | `signals/technology-integration-opportunities` |
| 7 | Job descriptions showing manual work | One LinkedIn job was inspected. DecisionPoint’s Operations Manager description contained reports, records, meetings, follow-ups, coordination, and admin duties. | Fully automatable | Company size and ICP must be checked before outreach. | `signals/manual-process-job-postings` |
| 8 | New leader joins | One small-company COO announcement was found in the earlier live test. | Future; not currently active | Not needed for the current pipelines. | `signals/new-leader-joins` |
| 9 | Promotions and job changes | One narrow promotion search worked, but the small test did not produce a strong ICP lead. | Future; not currently active | Similar to new-leader joins and not needed for the current pipelines. | `signals/promotions-job-changes` |
| 10 | Broken website funnels | One company was checked. The homepage worked, two linked funnel pages were tested, and no real broken page was found. | Fully automatable | Full form submission testing needs a cloud browser and safe test data. | `signals/broken-website-funnels` |
| 11 | Disconnected technology stack | Merged into Signal 6. | Covered by Signal 6 | Report only a possible integration opportunity, never a confirmed internal problem. | `signals/technology-integration-opportunities` |
| 12 | Pipeline Engine hiring intent | One Boolean LinkedIn job search returned 12 recent US jobs. Ten details were inspected and all ten qualified as direct SDR/BDR hiring events. A known Operations Manager job was separately tested and correctly rejected. | Working | Company fit and contact enrichment are still required before outreach. | `signals/pipeline-engine-hiring-intent` |

## Current result

| Status | Signals |
|---|---|
| Pipeline-ready logic | 7, 10, 12 |
| Logic works; cloud LinkedIn deployment remains | 3, 4 |
| Still requires configuration | 2 |
| Disabled; pending future review | 5 |
| Future; not currently active | 8, 9 |
| Reclassified as reusable skill | 6 |

The current live-signal pipeline set is Signals 3, 4, 7, 10, and 12. Technology
sourcing and enrichment is handled by `$technology-stack-sourcing`.

## Files produced

- Shared competitor engagement sheet: `signals/exports/competitor_engagement_leads.csv`
- Pipeline routing sheet: `signals/exports/pipeline_leads.csv`
- Technology result: `signals/exports/technology_signals.csv`
- Job result: `signals/exports/job_signals.json`
- Funnel result: `signals/exports/funnel_signals.csv`
- Pipeline Engine hiring opportunities:
  `signals/exports/pipeline_engine_hiring_opportunities.csv`

## Cost

The latest keyword-pain search used one CrustData credit. No more CrustData tests were run because the remaining balance is about two credits. The LinkedIn job test and website tests used no CrustData credits.

## Safe schedule

| Frequency | Signals |
|---|---|
| Every 2 hours | Competitor comments and competitor reactions after cloud deployment |
| Daily | Job descriptions |
| Weekly | Technology stack and website funnel checks |

These should run as separate jobs. LinkedIn jobs should have small limits, delays, retry backoff, and a daily request cap.
