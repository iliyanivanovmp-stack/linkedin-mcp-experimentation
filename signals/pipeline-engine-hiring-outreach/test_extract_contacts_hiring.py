from extract_contacts import matches_decision_maker_title


TARGETS = [
    "founder",
    "co-founder",
    "owner",
    "ceo",
    "chief executive officer",
    "coo",
    "chief operating officer",
    "cro",
    "chief revenue officer",
    "cmo",
    "chief marketing officer",
    "cto",
    "chief technology officer",
    "cfo",
    "chief financial officer",
    "cso",
    "chief strategy officer",
    "president",
    "managing director",
    "vp",
    "vice president",
    "director",
]


def test_accepts_configured_decision_maker_variants():
    assert matches_decision_maker_title("Co-Founder & CEO", TARGETS)
    assert matches_decision_maker_title("Vice President of Global Sales", TARGETS)
    assert matches_decision_maker_title("Director, Enterprise Sales", TARGETS)
    assert matches_decision_maker_title("Director of Customer Success", TARGETS)
    assert matches_decision_maker_title("VP, Information Technology", TARGETS)
    assert matches_decision_maker_title("Chief Strategy Officer", TARGETS)


def test_rejects_non_decision_maker_titles():
    assert not matches_decision_maker_title("Head of Rev Ops", TARGETS)
    assert not matches_decision_maker_title("Sales Manager", TARGETS)
    assert not matches_decision_maker_title("Senior Product Designer", TARGETS)
    assert not matches_decision_maker_title("Content Manager", TARGETS)
