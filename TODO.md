# Signal Radar TODO

## LinkedIn Engagement Automation

- [ ] Create a custom fork of the internal LinkedIn MCP.
- [ ] Add a read-only `get_post_comments` tool.
- [ ] Add a read-only `get_post_reactions` tool.
- [ ] Add small result limits and pagination limits.
- [ ] Return names, LinkedIn profile URLs, headlines, evidence text, and source post URL.
- [ ] Add tests that confirm the tools never like, comment, follow, connect, or message.
- [ ] Refresh the LinkedIn login stored on Modal using the valid local session.
- [ ] Deploy the customized MCP to Modal.
- [x] Test comments on Ben AI posts from the last 30 days.
- [x] Test reactions on Ben AI posts from the last 30 days.
- [ ] Connect the tools to an n8n scheduled workflow.
- [ ] Add deduplication by profile URL, post URL, signal type, and detection window.

## Competitor Commenters Script

- [x] Create an independent signal folder.
- [x] Support configurable competitor profile URLs.
- [x] Scan posts from the past 30 days.
- [x] Export commenter name, headline, LinkedIn URL, comment, and source post URL.
- [x] Store exported profile URLs.
- [x] Confirm a second run exports zero duplicates.
- [ ] Move the working browser logic into the custom cloud MCP.
- [x] Add a shared pipeline lead sheet with `signal_type` routing and deduplication.
- [ ] Replace the shared local CSV with the final cloud sheet or database destination.

## Competitor Reactions Script

- [x] Create an independent signal folder.
- [x] Support configurable competitor profile URLs.
- [x] Scan posts from the past 30 days.
- [x] Export reactor name, headline, LinkedIn URL, and source context.
- [x] Append to the same shared sheet as competitor commenters.
- [x] Skip people already exported by either engagement signal.
- [x] Confirm a second run exports zero duplicates.
- [ ] Move the working browser logic into the custom cloud MCP.
- [x] Add a shared pipeline lead sheet with `signal_type` routing and deduplication.
- [ ] Replace the shared local CSV with the final cloud sheet or database destination.

## Signal Refinement

- [x] Add Signal 2 filters to exclude sellers and generic educational posts.
- [x] Define the first narrow search term for Signal 5 tool-switching posts.
- [x] Define public technology detection rules for Signal 6.
- [ ] Add integration compatibility checks to Signal 6.
- [x] Define manual-process phrases for Signal 7 job descriptions.
- [x] Define the first target leadership titles for Signals 8 and 9.
- [x] Define basic broken-funnel checks for Signal 10.
- [ ] Add company and person enrichment to Signals 8 and 9.
- [ ] Connect post-search signal folders to the final cloud search endpoint.
- [x] Add a normalized local shared lead sheet for every working signal.
- [ ] Replace the normalized local sheet with the final cloud database or Google Sheet.
- [ ] Add a scheduler only after each cloud workflow has request caps and retry backoff.
