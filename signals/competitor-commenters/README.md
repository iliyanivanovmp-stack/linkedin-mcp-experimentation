# Competitor Commenters Signal

Find new people who commented on a competitor's LinkedIn posts during the configured lookback window.

## Output

Every run appends new rows to:

`signals/exports/competitor_engagement_leads.csv`

The same sheet is also used by the competitor-reactions signal.

Each row contains:

- Competitor name and profile
- Source post URL and age
- Commenter name
- Commenter headline
- Commenter LinkedIn URL
- Comment age
- Full comment text
- Detection time

## Deduplication

`state/exported_profiles.json` stores every commenter LinkedIn URL already exported.

Later runs export only new profiles. A person is not exported again for this signal even if they comment on another monitored post.

The shared CSV is also checked before export, so a person already exported by the reactions signal is not added again.

## Configuration

Edit `config.json` to add competitor profiles and change limits.

## Run

```bash
PLAYWRIGHT_BROWSERS_PATH="$HOME/.linkedin-mcp/patchright-browsers" \
uv run --with mcp-server-linkedin \
python signals/competitor-commenters/track_competitor_commenters.py
```

For a clean test:

```bash
PLAYWRIGHT_BROWSERS_PATH="$HOME/.linkedin-mcp/patchright-browsers" \
uv run --with mcp-server-linkedin \
python signals/competitor-commenters/track_competitor_commenters.py --reset-state
```

## Safety

This script is read-only. It does not like, comment, follow, connect, or send messages.

## Verified Test

Tested on June 20, 2026 against Ben van Sprundel's LinkedIn profile.

- First run: 5 new commenter profiles exported
- Second run: 0 profiles exported
- Deduplication: passed
- Direct source-post URLs: passed
- Comment evidence: passed
