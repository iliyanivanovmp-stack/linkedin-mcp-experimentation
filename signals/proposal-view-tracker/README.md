# Proposal View Tracker

Tracks client revisits to generated Google Slides proposals through a Modal redirect URL.

Flow:

1. Proposal generator creates the Google Slides deck.
2. The sender shares the tracked URL instead of the raw Slides URL.
3. The first view is recorded silently.
4. A later reopen triggers one Slack notification after the reopen floor and cooldown rules pass.
5. No automatic email is sent.

Runtime:

- Modal app: `proposal-view-tracker`
- State: Modal Dict `proposal-view-tracker-state`
- Slack secret: `proposal-view-tracker-slack`
- Slack destination: `#operator-daily-briefs`

Defaults:

- Reopen floor: 5 minutes after first view
- Notification cooldown: 60 minutes per proposal
