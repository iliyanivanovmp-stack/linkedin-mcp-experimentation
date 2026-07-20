# Signal Testing Workflow

## Test Limits

- Test one lead or one company at a time.
- Use read-only actions only.
- Do not send messages or connection requests.
- Stop after one verified candidate is found.
- Do not treat engagement alone as buying intent.
- Every final signal workflow must run without manual review.
- Every final workflow must run in the cloud without the user's computer being turned on.
- The target schedule is one run every two hours.
- If a tool cannot return required evidence, use an automated fallback.
- A signal that still needs a person to open LinkedIn or inspect comments fails the project requirement.

## Tool Order

Use the cheapest safe tool that can provide the required evidence.

1. Local LinkedIn MCP
   - Company and people search
   - Company posts
   - Profile posts
   - Jobs and LinkedIn-native discovery

2. Composio LinkedIn
   - Known-post content
   - Reactions on a known post
   - API-based LinkedIn data available to the connected account

3. Cloud-hosted automated LinkedIn browser fallback
   - Open the known company page or post.
   - Read visible comments and load more comments when needed.
   - Extract only the first relevant person and evidence.
   - Keep all actions read-only.
   - Do not use a browser running on the user's computer.

4. CrustData
   - Use only when the LinkedIn options cannot discover or verify the signal.
   - State the expected credit cost before a paid test when possible.

## Evidence Rules

A candidate is valid only when:

- The source shows a real problem, question, complaint, or clear business event.
- The person can be identified.
- The person's company can be identified.
- The company fits or may fit the target profile.
- A source URL or exact LinkedIn location can be preserved.

Do not count broad likes, generic praise, promotional comments, or keyword matches without context as buying signals.

## Competitor Signal Separation

### Signal 1: Competitor complaint or problem question

The person clearly describes a problem with Ben AI, asks a serious question about a limitation, or shows dissatisfaction or difficulty.

This is the strongest competitor-page signal.

### Signal 3: Competitor page commenter

The person comments on a Ben AI post but does not necessarily complain. The comment must still show useful context or interest.

This is weaker than Signal 1 and requires qualification.

### Signal 4: Competitor page reaction

The person reacts to a Ben AI post. This shows awareness only, not pain or buying intent.

Use it only when the person is a strong ICP match and combine it with other evidence.

## Signal 1 Workflow

1. Confirm the exact competitor page: `linkedin.com/company/bens-ai`.
2. Use the Local LinkedIn MCP to retrieve the company page and recent posts.
3. Prefer posts that discuss a service, product, workflow, or implementation and have comments.
4. Try to inspect comments or questions through available LinkedIn tools.
5. If comment text is unavailable, use automated browser navigation to read the comments.
6. Use Composio LinkedIn only when a post identifier is available.
7. Use CrustData only if LinkedIn cannot provide enough evidence and a paid fallback is approved.
8. Return one verified candidate or clearly state that no candidate was verified.

## Required Final Classification

Only these final results are acceptable:

- Fully automatable
- Not reliably available

“Automatable with fallback” is acceptable only when the fallback is also fully automated.
“Manual/semi-automated” is not acceptable for the final system.

## Current Signal Status

### Signal 1: Competitor complaint or problem question

- Status: Removed
- Reason: This signal is no longer needed.

### Signal 2: Keyword pain conversation

- Test status: No verified candidate from the first two small searches
- Automation status: Technically fully automatable through CrustData keyword search plus strict filtering
- Main problem: Most matches are automation sellers describing a problem, not buyers describing their own problem
- False-positive risk: High without first-person pain checks, role checks, location checks, and seller exclusion
- Current cost: About 1 CrustData credit per search
- Two-hour schedule cost: About 12 credits per day for one query
- Current viability: Do not schedule every two hours yet. Improve the query and filtering rules first, then test whether fewer daily runs are enough.

Required filters for future tests:

- Author is in the United States or Canada
- Author is a founder, owner, CEO, managing director, or operations leader
- Company is a small B2B agency or service business
- Author describes their own current problem
- Exclude automation consultants, AI agencies, software sellers, recruiters, and generic educational posts
- Preserve the exact post URL and evidence text

### Signal 3: Competitor page commenter

- Test status: Live read-only browser test succeeded
- Evidence returned: Comment text, commenter name, LinkedIn profile URL, and headline
- Current status: Feasible after adding a read-only MCP tool
- Required tool: `get_post_comments`
- Cloud requirement: Run the LinkedIn MCP with a persistent authenticated cloud browser

### Signal 4: Competitor page reaction

- Test status: Live read-only browser test succeeded
- Evidence returned: Reactor name, LinkedIn profile URL, and headline
- Current status: Feasible after adding a read-only MCP tool
- Required tool: `get_post_reactions`
- Qualification rule: A reaction alone is weak. Keep only people who match the ICP or have another signal.

### Signal 6 and Signal 11

- Signal 11 is merged into Signal 6.
- Detect public tools used by the company.
- Check whether the tools support direct integrations, APIs, webhooks, n8n, or Zapier.
- Describe the result as an integration opportunity.
- Do not claim the company's internal stack is disconnected unless direct evidence exists.

## Full Test Results

See `signal_test_status.md` for the status table covering all 11 signals.
