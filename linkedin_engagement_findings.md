# LinkedIn Engagement Findings

## Result

Competitor comments and reactions are available through the internal LinkedIn MCP browser.

The released MCP does not expose them as tools yet, but its authenticated browser can read them.

## Live Read-Only Test

Target:

- Ben van Sprundel
- Founder of Ben AI
- LinkedIn recent activity page

### Comments

The test opened the comments on a recent post and returned:

- Comment text
- Commenter name
- Commenter LinkedIn profile URL
- Commenter headline

One example found:

- Marc Soummer
- Founder at Silverline Growth
- LinkedIn: `https://www.linkedin.com/in/marc-soummer-958baa295`
- His full comment text was available

### Reactions

The test opened the reaction list and returned:

- Reactor name
- Reactor LinkedIn profile URL
- Reactor headline

The first visible batch contained 10 profiles.

## What Is Missing

The current MCP package does not expose:

- `get_post_comments`
- `get_post_reactions`

The browser logic works. We need to package it as read-only MCP tools.

## Cloud Design

1. Run a customized fork of the LinkedIn MCP in the cloud.
2. Keep one persistent authenticated browser profile.
3. Find recent posts from the selected competitor profile or company.
4. Open posts with comments or reactions.
5. Extract the first small batch of people.
6. Filter by country, title, company type, and company size.
7. Save only matching leads.
8. Close or reuse the browser safely.

## Safety Limits

- Read-only tools only
- No likes, comments, messages, follows, or connection requests
- One browser session
- Small result limits
- Slow scheduled runs
- Deduplicate by profile URL, post URL, and signal type

## Important Cloud Issue

The current Modal deployment has an expired LinkedIn session.

The local session is valid. The cloud profile must be refreshed before scheduled tests can work.

An open upstream pull request also proposes remote browser support through Chrome DevTools Protocol. It is not merged yet, but it may provide a cleaner cloud session model later.
