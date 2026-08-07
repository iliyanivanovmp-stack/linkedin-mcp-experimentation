from enrichment import (
    ApolloCompanyClient,
    LemlistCompanyClient,
    compensation_details,
    domain_from_url,
    enrich_company,
    load_domain_overrides,
)


def test_domain_from_url_handles_public_suffixes_and_rejects_linkedin():
    assert domain_from_url("https://www.example.com/about") == "example.com"
    assert domain_from_url("https://careers.example.co.uk/jobs") == "example.co.uk"
    assert domain_from_url("https://www.linkedin.com/company/example") == ""


def test_compensation_parser_ignores_pipeline_targets():
    parsed = compensation_details(
        "Own a $2M sourced pipeline target.\nThe annual salary is $90,000 to $120,000 per year."
    )
    assert parsed["compensation_min"] == 90000
    assert parsed["compensation_max"] == 120000
    assert parsed["compensation_currency"] == "USD"
    assert parsed["compensation_period"] == "year"


class FakeApollo(ApolloCompanyClient):
    def __init__(self, organizations):
        self.organizations = organizations

    def search(self, company_name):
        return self.organizations


class FakeLemlist(LemlistCompanyClient):
    def __init__(self, companies):
        self.companies = companies

    def search(self, company_name):
        return self.companies


def test_apollo_requires_one_exact_company_match():
    client = FakeApollo([
        {"name": "Acme Inc", "primary_domain": "acme.com"},
        {"name": "Acme Holdings", "primary_domain": "wrong.com"},
    ])
    assert client.find_exact("Acme Inc")["company_domain"] == "acme.com"


def test_apollo_rejects_ambiguous_exact_matches():
    client = FakeApollo([
        {"name": "Acme", "primary_domain": "acme.com"},
        {"name": "Acme", "primary_domain": "acme.ai"},
    ])
    result = client.find_exact("Acme")
    assert result["domain_status"] == "ambiguous"
    assert "company_domain" not in result


def test_lemlist_requires_one_exact_company_match():
    client = FakeLemlist([
        {"company_name": "Acme Inc", "company_domain": "acme.com"},
        {"company_name": "Acme Holdings", "company_domain": "wrong.com"},
    ])
    assert client.find_exact("Acme Inc")["company_domain"] == "acme.com"


def test_enrich_company_prefers_lemlist_before_apollo():
    lemlist = FakeLemlist([{"company_name": "Acme", "company_domain": "acme.com"}])
    apollo = FakeApollo([{"name": "Acme", "primary_domain": "wrong.com"}])

    result = enrich_company("Acme", "", "", lemlist=lemlist, apollo=apollo)

    assert result["company_domain"] == "acme.com"
    assert result["domain_source"] == "lemlist_database_exact_company"


def test_enrich_company_falls_back_to_apollo_after_lemlist_miss():
    lemlist = FakeLemlist([])
    apollo = FakeApollo([{"name": "Acme", "primary_domain": "acme.com"}])

    result = enrich_company("Acme", "", "", lemlist=lemlist, apollo=apollo)

    assert result["company_domain"] == "acme.com"
    assert result["domain_source"] == "apollo_exact_company"


def test_enrich_company_prefers_captured_website_over_apollo():
    client = FakeApollo([{"name": "Acme", "primary_domain": "wrong.com"}])
    result = enrich_company(
        "Acme",
        "https://www.acme.com/careers",
        "Pay range: $50 to $80 per hour",
        "https://www.linkedin.com/company/acme/",
        client,
    )
    assert result["company_domain"] == "acme.com"
    assert result["domain_source"] == "company_website"
    assert result["company_linkedin_url"].endswith("/acme/")
    assert result["compensation_period"] == "hour"


def test_verified_override_precedes_apollo_recovery(tmp_path):
    path = tmp_path / "overrides.json"
    path.write_text('{"Acme Holdings": "https://www.acme.example/about"}')
    overrides = load_domain_overrides(path)
    client = FakeApollo([{"name": "Acme Holdings", "primary_domain": "wrong.com"}])
    result = enrich_company("Acme Holdings", "", "", apollo=client, domain_overrides=overrides)
    assert result["company_domain"] == "acme.example"
    assert result["domain_source"] == "manual_verified_backfill"
