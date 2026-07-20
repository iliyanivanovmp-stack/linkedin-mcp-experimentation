# Tool Switching

## Status

Disabled and pending future review.

The signal is not useful enough for production right now. LinkedIn's post
search returns too many unrelated matches, complex Boolean searches return no
results, and the Author Keywords filter is actually an author job-title
filter. Keep the implementation and test evidence for possible future use.

Tracks LinkedIn posts about people leaving or replacing relevant tools.

Verified example: Jeff Tannenbaum publicly said he was leaving HubSpot for
Lightfield.

## Search strategy

The workflow performs one compact LinkedIn search. It searches for the broad
switching term and combines the five tool names with `OR`.

Current phrases:

- `leaving`
- `switching from`
- `moving away from`
- `switching to`
- `moving to`
- `adopting`

Current tools:

- HubSpot
- ClickUp
- Instantly
- Lemlist
- Zapier

The resulting query is:

```text
switching (HubSpot OR ClickUp OR Instantly OR Lemlist OR Zapier)
```

The larger Boolean expressions returned no results in live LinkedIn tests.
This shorter form returned six visible posts in one search.

LinkedIn applies these filters during the single search:

- Content type: Posts
- Date posted: Past month
- Sort: Top match

LinkedIn does not provide a country filter for this search.

## Qualification after the search

The workflow reads the returned result cards and keeps:

- Person-authored posts.
- Authors whose displayed title matches a configured decision-maker or
  operations title.
- Results explicitly showing India as the author's location are excluded.
- The already-returned post text must contain a switching verb and at least
  one configured tool name.

It does not visit every profile or company. It does not check company size,
company technology, first-person language, case studies, client stories,
migration services, or promotional language.

The workflow does not infer nationality from a person's name. If a result does
not expose location, it is not rejected on geography alone.

Text validation happens locally on the returned search cards. It does not open
profiles or create additional LinkedIn actions.

The search source can later be the local LinkedIn MCP or Composio. The
normalization and title filtering remain provider-independent.
