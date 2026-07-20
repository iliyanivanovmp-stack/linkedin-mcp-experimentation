# Competitor Reactions Signal

Find new people who reacted to a competitor's LinkedIn posts during the configured lookback window.

## Shared Export

Every run appends new rows to:

`signals/exports/competitor_engagement_leads.csv`

This is the same CSV sheet used by the competitor-commenters signal.

## Deduplication

`state/exported_profiles.json` stores previously exported reactor LinkedIn URLs.

Later runs export only new reactors for this signal.

The shared CSV is also checked before export, so a person already exported by the commenters signal is not added again.

## Run

```bash
PLAYWRIGHT_BROWSERS_PATH="$HOME/.linkedin-mcp/patchright-browsers" \
uv run --with mcp-server-linkedin \
python signals/competitor-reactions/track_competitor_reactions.py
```

Use `--reset-state` for a clean test.

## Safety

The script is read-only. It never reacts, comments, follows, connects, or sends messages.

## Verified Test

Tested on June 20, 2026 against Ben van Sprundel's recent LinkedIn posts.

- New reactors exported: 28
- Existing commenters skipped globally: passed
- Second reactions run exported: 0
- Deduplication by URL and name: passed
- Shared sheet append: passed
