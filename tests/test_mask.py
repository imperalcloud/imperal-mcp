from imperal_mcp.mask import defensive_scrub, mask_pii_in_obj, apply_pii_redaction, PIIRedactionLevel, ALLOWLIST_KEYS


# --- alias identity ----------------------------------------------------------

def test_alias_identity():
    """server.py imports defensive_scrub; it must be the exact same object."""
    assert defensive_scrub is mask_pii_in_obj


# --- email -------------------------------------------------------------------

def test_scrub_email_in_nested():
    out = mask_pii_in_obj({"note": "ping me at john.doe@example.com please", "app_id": "x"})
    assert "john.doe@example.com" not in out["note"]
    assert "<EMAIL>" in out["note"]          # strong token, not deleted
    assert out["app_id"] == "x"             # ALLOWLIST_KEYS: structural id untouched


def test_scrub_email_non_allowlisted_key():
    out = mask_pii_in_obj({"contact": "reach user@domain.io for help"})
    assert "<EMAIL>" in out["contact"]
    assert "user@domain.io" not in out["contact"]


# --- phone -------------------------------------------------------------------

def test_scrub_phone_in_list():
    out = mask_pii_in_obj(["call +1-202-555-0147 now", "ok"])
    assert "+1-202-555-0147" not in out[0]
    assert "<PHONE>" in out[0]
    assert out[1] == "ok"                   # non-PII element unchanged


# --- SSN & credit-card -------------------------------------------------------

def test_scrub_ssn():
    out = mask_pii_in_obj({"info": "SSN is 123-45-6789 for that user"})
    assert "123-45-6789" not in out["info"]
    assert "<SSN>" in out["info"]


def test_scrub_credit_card():
    out = mask_pii_in_obj({"payment": "card 4111 1111 1111 1111 accepted"})
    assert "4111 1111 1111 1111" not in out["payment"]
    assert "<CARD>" in out["payment"]


# --- ALLOWLIST preserves values that look like PII ---------------------------

def test_allowlist_key_not_mangled():
    """A user_id that looks like a phone number must not be redacted."""
    out = mask_pii_in_obj({"user_id": "12345678901"})
    assert out["user_id"] == "12345678901"


def test_allowlist_keys_exported():
    """ALLOWLIST_KEYS must be a frozenset with the expected structural ids."""
    assert isinstance(ALLOWLIST_KEYS, frozenset)
    for key in ("id", "app_id", "imperal_id", "user_id", "tenant_id"):
        assert key in ALLOWLIST_KEYS


# --- apply_pii_redaction levels ----------------------------------------------

def test_level_none_passthrough():
    assert apply_pii_redaction("user@example.com", PIIRedactionLevel.NONE) == "user@example.com"


def test_level_full_redact():
    assert apply_pii_redaction("user@example.com", PIIRedactionLevel.FULL_REDACT) == "<redacted>"


def test_level_mask_pii_email():
    assert apply_pii_redaction("user@example.com", PIIRedactionLevel.MASK_PII) == "<EMAIL>"


def test_apply_pii_none_input():
    assert apply_pii_redaction(None, PIIRedactionLevel.MASK_PII) is None


def test_apply_pii_empty_string():
    assert apply_pii_redaction("", PIIRedactionLevel.MASK_PII) == ""
