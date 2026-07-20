# Future System Ideas

## Current finished system

Technology finding is a reusable sourcing and enrichment system. It finds
companies by technology use or enriches known companies with their detected
stack, then produces a Google Sheet with company rows, source provenance,
selected outreach tools, and short automation angles.

The production source chain is:

1. Apollo
2. Lemlist
3. Instantly
4. Website evidence

Instantly remains in the fallback chain even though prior tests returned no
technology output. If Instantly returns no technologies, record that as
`instantly_no_technology_output` and continue.

## Future pipeline role

This system should become the front end of an AI Brain and integration
opportunity pipeline.

The finished pipeline can:

1. Discover companies using target tools or tool combinations.
2. Enrich known companies from other signals.
3. Select one to three outreach-relevant tools.
4. Generate short automation angles based on the real tools detected.
5. Route only medium- or high-confidence companies into outreach.

## Future bots

### Tech Discover Bot

Find companies using requested technologies, with strict matching when the user
asks for combinations such as `HubSpot AND Calendly`.

### Tech Enrichment Bot

Take known company domains or LinkedIn company URLs and enrich them with
Apollo, Lemlist, Instantly, and website evidence.

### Technology Normalization Bot

Normalize aliases, remove low-value infrastructure, deduplicate source results,
and preserve source provenance for every detected tool.

### Automation Angle Bot

Create short, benefit-first workflow ideas from the selected tools. The message
should say what the tools could enable together, not claim the company has a
broken integration.

### Outreach Routing Bot

Move companies into a campaign only when the technology evidence is strong
enough and the company matches the intended ICP.

## Future sheet fields

The future sheet should keep at least:

- Company name
- Domain
- LinkedIn company URL
- Company size
- Country
- Industry
- Requested technologies
- Matched technologies
- All technologies
- Selected outreach tools
- Automation angle 1
- Automation angle 2
- Automation angle 3
- Outreach angle
- Source provenance
- Confidence
- Stale domain warning
- Run notes
- Status

## Outreach rules

- Do not say the company has broken, disconnected, or manual systems unless
  another verified signal proves it.
- Technology usage itself is the personalization signal.
- Keep angles short enough to use in a cold email or follow-up.
- Prefer business tools over infrastructure tools.
- Suppress generic frameworks, fonts, DNS, hosting, and analytics unless the
  user explicitly asks for them.
