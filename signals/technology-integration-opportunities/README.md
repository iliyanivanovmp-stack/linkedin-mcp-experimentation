# Technology and Integration Opportunities

## Status

Reclassified as the reusable global skill `$technology-stack-sourcing` on
June 22, 2026. This folder retains the legacy public-website detector used by
the skill and historical signal exports.

This is not a live monitoring signal. It supports:

1. Lead generation by finding companies using specified technologies.
2. Lead enrichment by checking technologies used by known companies.

Verified on `deliverables.ai`: Next.js, Netlify, HubSpot, Calendly, Apollo,
Google Analytics, LinkedIn Insight, and Amplitude were detected.

This signal never claims the tools are disconnected. It says they may present
an integration opportunity.

## Skill source order

1. Apollo exact-domain lookup, organization details, and company-name or
   LinkedIn fallback when the domain is stale.
2. Lemlist exact-domain, company-name, or technology-filter lookup for broad
   coverage and discovery.
3. Instantly exact-domain or company technology fallback when the connected
   operation exposes technology output.
4. Current website detection for validation and recently added public tools.
5. Normalize, merge, deduplicate, and remove infrastructure tools that are not
   useful for outreach.

Instantly technology enrichment was tested on two companies and returned no
technology output, but it remains part of the production fallback chain. If it
returns no technologies, the run records that fact and continues with Lemlist,
Apollo, and website evidence.

## Verified hybrid test

`adstartmedia.com` produced strong overlapping results from Apollo and Lemlist,
including Affise, Slack, reporting tools, finance tools, and AWS. The website
scan confirmed the current public framework but was much less complete.

The outreach signal is the detected tool or complementary tool combination.
It does not require proof that the company has a broken integration.

Skill location:

`~/.codex/skills/technology-stack-sourcing`
