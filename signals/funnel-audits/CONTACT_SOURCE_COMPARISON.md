# Contact Source Comparison: convertibles.dev

Test target:

- Company: Convertibles
- Domain: `convertibles.dev`
- Desired contacts: founders, CEOs, owners, managing directors, operations leads

The second test was rerun with URL/domain targeting rather than company-name
targeting.

## Summary

| Source | Test result | Emails included? | Notes |
| --- | ---: | --- | --- |
| Lemlist database | 2 contacts | Yes | Best result for this test. Exact domain filter worked and returned usable emails. |
| Apollo | 2 contacts | Not in search output | Exact domain filter worked and says emails exist, but actual emails require Apollo enrichment credits. |
| Instantly database | 10 contacts | No | Exact domain targeting works with `domains`, but preview output has no emails. |

## Lemlist Database

Returned 2 contacts for `convertibles.dev`:

| Name | Title | Email | LinkedIn |
| --- | --- | --- | --- |
| Julian S. | Co-founder | `julian@convertibles.dev` | `https://www.linkedin.com/in/juliansamarjiev` |
| Clayton Ferguson | Co-Founder | `clayton@convertibles.dev` | `https://www.linkedin.com/in/ferguson-ross` |

Notes:

- Domain filter: `currentCompanyWebsiteUrl = convertibles.dev`
- Both returned contacts were decision makers.
- Emails were present directly in the search result.
- The Lemlist MCP OAuth path was blocked during the test, but the Lemlist REST API key worked for the database search.

## Apollo

Returned 2 matching discovery contacts:

| Name | Title | Company | Has email | Has phone |
| --- | --- | --- | --- | --- |
| Julian Sa***v | Co-founder | CONVERTIBLES | yes | yes |
| Clayton Fe***n | Co-Founder | CONVERTIBLES | yes | yes |

Notes:

- Domain filter: `q_organization_domains_list = ["convertibles.dev"]`
- Apollo search output obfuscates names and does not return email addresses.
- Apollo enrichment can reveal full names, LinkedIn profiles, emails, and email status.
- Enrichment costs Apollo credits, so it was not run in this test.

## Instantly Database

Corrected domain search returned 10 preview contacts for `convertibles.dev`.
The best three after local ranking were:

| Name | Title | Company | LinkedIn |
| --- | --- | --- | --- |
| Clayton Ferguson | Co-Founder | Convertibles | `linkedin.com/in/ferguson-ross` |
| Maria B. | Operations Manager | Convertibles | `linkedin.com/in/maria-b-154096194` |
| Daiana Rusanzhik | Junior Operations Manager | Convertibles | `linkedin.com/in/daiana-rusanzhik-19b75316a` |

Notes:

- The correct exact-domain filter is `domains: ["convertibles.dev"]`.
- `look_alike` is for similar companies, not exact company targeting.
- The preview API does not return emails.
- Instantly can enrich emails later through its app/enrichment flow, but that costs enrichment credits and was not run in this test.
- The Instantly skill was patched after this test because it was missing the
  official `domains` filter and was previously testing incorrect keys such as
  `domain`, `company_domain`, and `website`.

## Recommendation

For System 1's first production contact-generation path, start with Lemlist
database search scoped by company domain/URL.

Reason:

- It returned the same two real Convertibles decision makers Apollo found.
- It returned usable emails directly.
- It avoids Apollo enrichment credits for this test case.

Apollo should remain the fallback when Lemlist returns fewer than three contacts
or missing emails. Instantly is useful as an additional contact source after the
skill fix, but email discovery still requires Instantly enrichment/import rather
than the preview endpoint.

## Second Domain Test: adstartmedia.com

Test target:

- Company domain: `adstartmedia.com`
- Desired contacts: founders, CEOs, owners, managing directors, operations leads

| Source | Domain/URL targeting | Result | Emails |
| --- | --- | --- | --- |
| Lemlist database | Works: `currentCompanyWebsiteUrl=adstartmedia.com` | 1 correct decision maker | Yes |
| Apollo | Works: `q_organization_domains_list=["adstartmedia.com"]` | 1 correct decision maker | Only after Apollo enrichment |
| Instantly database | Works: `domains=["adstartmedia.com"]` | 16 contacts | No |

### Lemlist Database

Returned 1 contact:

| Name | Title | Email | LinkedIn |
| --- | --- | --- | --- |
| Ivan Galabov | Founder | `ivan@adstartmedia.com` | `https://www.linkedin.com/in/ivangalabov` |

### Apollo

Returned 1 discovery contact:

| Name | Title | Company | Has email | Has phone |
| --- | --- | --- | --- | --- |
| Ivan Ga***v | Founder | AdStart Media | yes | yes |

Apollo again found the same person but did not expose the actual email without
enrichment.

### Instantly Database

Corrected domain search returned 16 preview contacts for `adstartmedia.com`.
The best three after local ranking were:

| Name | Title | Company | LinkedIn |
| --- | --- | --- | --- |
| Ivan Galabov | Founder | Adstart Media | `linkedin.com/in/ivangalabov` |
| Victor Trifonov | Chief Operating Officer | Adstart Media | `linkedin.com/in/victor-trifonov-8369a695` |
| Slavina Proeva | Affiliate Team Lead | Adstart Media | `linkedin.com/in/slavinaproeva` |

The preview endpoint still returned no emails.

### Takeaway

The second domain confirms the same pattern:

- Lemlist database is the strongest primary source for this workflow.
- Apollo is a credible fallback but requires enrichment for emails.
- Instantly preview is now suitable for domain-scoped contact discovery after
  the skill fix, but not for email discovery without a separate enrichment step.
