# Funnel Audit System

Production-oriented, stateful website funnel auditing.

The system reads queued websites from the existing `Website Pipelines` Google
Sheet, inspects their public funnels in a cloud browser, records evidence,
submits only approved public forms, monitors the audit inbox for ten days, and
marks evidence-backed opportunities as `outreach_ready`.

## Safety default

Deployments start with `LIVE_SUBMISSIONS=false`. Discovery and classification
run normally, but no form is submitted and no booking is created until live
submissions are explicitly enabled.

The system never submits:

- Payment or checkout forms
- Password, login, identity, legal, medical, or financial forms
- CAPTCHA-protected forms
- Forms requiring unsupported or unverifiable claims

Browser routing:

- Playwright Chromium handles discovery and ordinary public forms.
- Composio Browser handles protected calendar and booking flows.
- Modal remains responsible for scheduling, state, Gmail, Sheets, and AI
  classification.

AI classification uses `gpt-5.4-mini` with strict structured outputs. Browser
actions, timing, matching, deduplication, link checks, and state transitions
remain deterministic code.

The browser audits desktop, delayed/scroll behavior, a common exit-intent
gesture, CTA-revealed forms, and a mobile viewport. Discovered forms carry a
fingerprint and reveal context so submission fails closed if the exact flow
cannot be reproduced. Shared-inbox messages are stored once and require
company/domain evidence before they are attached to an audit.

## Operator surfaces

- Input and dashboard:
  https://docs.google.com/spreadsheets/d/1UD1tPrjXy8Hr3l5tAcLALHqa30IJ-AZeO0f4_DbGYAM/edit
- Machine state: SQLite on a persistent Modal Volume
- Evidence: screenshots and JSON events on the same Modal Volume

## Setup

1. Revoke the OpenAI key pasted into chat and create a replacement.
2. Authorize the dedicated audit Google account:

   ```bash
   uv run --with google-auth-oauthlib python scripts/authorize_google.py
   ```

3. Install secrets:

   ```bash
   modal secret create funnel-audit-openai OPENAI_API_KEY=...
   modal secret create funnel-audit-composio COMPOSIO_API_KEY=...
   modal secret create funnel-audit-google GOOGLE_OAUTH_JSON="$(cat .secrets/google-oauth.json)"
   modal secret create funnel-audit-config \
     AUDIT_NAME="Iliyan Ivanov" \
     AUDIT_EMAIL="iliyan.i@aiessentials.us" \
     AUDIT_PHONE="+359889609200" \
     AUDIT_TITLE="Founder" \
     AUDIT_COMPANY="AIessentials" \
     LIVE_SUBMISSIONS="false"
   ```

4. Deploy:

   ```bash
   modal deploy modal_app.py
   ```

## Schedules

- Queue intake, discovery, inbox monitoring, finalization, and cancellation
  checks: every two hours

## Local checks

```bash
uv run --with pytest --with pydantic --with beautifulsoup4 pytest
```
