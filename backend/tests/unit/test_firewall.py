import pytest

from app.firewall.detectors import find
from app.firewall.scanner import Finding, scan


@pytest.mark.parametrize(
    ("text", "entity"),
    [
        ("mail a.b+c@example.co.in", "EMAIL"),
        ("call +91 98765 43210", "PHONE"),
        ("card 4111 1111 1111 1111", "CREDIT_CARD"),
        ("aadhaar 2341 2341 2346", "IN_AADHAAR"),
        ("PAN ABCPE1234F", "IN_PAN"),
        ("AKIAIOSFODNN7EXAMPLE", "AWS_ACCESS_KEY"),
        ("ghp_" + "a" * 36, "GITHUB_TOKEN"),
        ("xoxb-1234567890-abcdef", "SLACK_TOKEN"),
        ("sk-abcdefghijklmnopqrstuv", "API_KEY"),
        ("sk_live_abcdefghijklmnop", "API_KEY"),
        ("eyJhbGciOi.eyJzdWIiOi.c2lnbmF0dXJl", "JWT"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----", "PRIVATE_KEY"),
    ],
)
def test_detects(text, entity):
    assert [f[0] for f in find(text)] == [entity]


@pytest.mark.parametrize(
    "text",
    ["order 12345 on 2026-11-22", "amount 8000.50", "plain text", "customer 101", "v1.2.3"],
)
def test_ignores_ordinary_text(text):
    assert find(text) == []


def test_checksums_reject_invalid_identifiers():
    assert "CREDIT_CARD" not in [f[0] for f in find("4111 1111 1111 1112")]
    assert "IN_AADHAAR" not in [f[0] for f in find("2341 2341 2341")]


def test_scan_redacts_and_reports_paths_without_values():
    result = scan(
        {"user": {"email": "x@y.io", "tags": ["call 9876543210"]}, "n": 5}, {}, "arguments"
    )
    assert result.data == {
        "user": {"email": "[REDACTED:EMAIL]", "tags": ["call [REDACTED:PHONE]"]},
        "n": 5,
    }
    assert result.findings == [
        Finding("EMAIL", "arguments.user.email", "redact"),
        Finding("PHONE", "arguments.user.tags[0]", "redact"),
    ]
    assert not result.blocked


def test_secret_named_fields_block_whatever_the_value():
    result = scan({"api_key": "sk-example-secret", "Password": "x"}, {}, "arguments")
    assert result.blocked
    assert result.data == {
        "api_key": "[REDACTED:SECRET_FIELD]",
        "Password": "[REDACTED:SECRET_FIELD]",
    }


def test_overrides_change_actions():
    result = scan(
        {"a": "x@y.io", "b": "AKIAIOSFODNN7EXAMPLE"},
        {"EMAIL": "allow", "AWS_ACCESS_KEY": "redact"},
        "r",
    )
    assert result.data == {"a": "x@y.io", "b": "[REDACTED:AWS_ACCESS_KEY]"}
    assert not result.blocked


def test_multiple_matches_in_one_string_redact_in_order():
    result = scan("x@y.io then AKIAIOSFODNN7EXAMPLE then z@w.io", {}, "r")
    assert result.data == "[REDACTED:EMAIL] then [REDACTED:AWS_ACCESS_KEY] then [REDACTED:EMAIL]"
