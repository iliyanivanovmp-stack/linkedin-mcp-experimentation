# Pipeline Engine Hiring Outreach

Independent production system for detecting companies hiring pipeline roles and routing decision makers into dedicated Lemlist campaigns.

Flow:

1. Search recent LinkedIn jobs and append at most 10 unique company signals per Europe/Sofia day to `Leads`.
2. Generate hiring-specific outreach context from the verified job.
3. Find up to three decision makers per company.
4. Enrich missing emails through Lemlist with Apollo fallback.
5. Route email-ready contacts to `Pipeline Engine hiring outreach`.
6. Route unresolved contacts with LinkedIn profiles to `Pipeline Engine hiring outreach - LinkedIn only`.

Both routes share a persistent maximum of 30 contacts per Europe/Sofia calendar day.
The sourcing stage separately enforces a persistent maximum of 10 unique companies per Europe/Sofia calendar day, including retries and manual runs.

The collector may inspect up to 60 job details to fill the 10-company target;
rejected or duplicate jobs do not consume accepted-company capacity. Contact
fallbacks fill up to three role-relevant decision makers per company. Transient
contact and Lemlist delivery failures are retried with bounded attempts.

Before context generation, `recover_company_domains.py` derives missing domains
from known websites and uses Apollo company matching as a fallback.

## Production trigger and monitoring

The Modal HTTP endpoint requires the trigger secret in the request header:

```text
Authorization: Bearer <PIPELINE_ENGINE_HIRING_TRIGGER_TOKEN>
```

Do not place the token in the URL or query string. When
`PIPELINE_ENGINE_HIRING_RESULT_WEBHOOK_URL` is present in the Modal secret, the
orchestrator posts a structured completion or failure report containing company,
contact, Lemlist, timing, and step-level results.

`modal_app.py` is the only canonical Modal deployment entrypoint.
The trigger token is isolated in the Modal secret
`pipeline-engine-hiring-trigger-secret`; provider and Google credentials remain
in `pipeline-engine-hiring-outreach-secrets`.

Workbook: https://docs.google.com/spreadsheets/d/1OXRX2OSokVuE6s4ZNFVCSYc97Lbt28SLE96L3GzdcYI/edit

The system owns its scripts, feeder configuration, Modal deployment, secret, and daily n8n workflow. It has no runtime or scheduling dependency on Funnel Audit or Technology-Based Outreach.

## Standalone operation

Run all commands from this directory:

```bash
cp .env.example .env
python3 run_system.py --dry-run --company-limit 3 --skip-sourcing
PYTHONPATH=. python3 -m pytest -q
modal deploy modal_app.py
```

`modal_app.py`, `lead_sheet.py`, all configs, and all runtime scripts are local
to this folder. Production credentials are supplied through the Modal secret,
not committed files.
