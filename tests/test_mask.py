from imperal_mcp.mask import defensive_scrub


def test_scrub_email_in_nested():
    out = defensive_scrub({"note": "ping me at john.doe@example.com please", "app_id": "x"})
    assert "john.doe@example.com" not in out["note"]
    assert "[redacted-email]" in out["note"]  # replacement token present, not just deleted
    assert out["app_id"] == "x"  # structural id untouched

def test_scrub_list_of_strings():
    out = defensive_scrub(["call +1-202-555-0147 now", "ok"])
    assert "+1-202-555-0147" not in out[0]
    assert out[1] == "ok"  # non-PII element must be unchanged
