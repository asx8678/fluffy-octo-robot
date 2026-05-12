"""Tests for the secret scanner."""

from code_muse.plugins.autonomous_memory.secret_scanner import (
    SCAN_PATTERNS,
    scan_for_secrets,
)


def test_aws_access_key() -> None:
    text = "key = AKIAIOSFODNN7EXAMPLE"
    matches = scan_for_secrets(text)
    assert any(m.pattern_name == "aws_access_key" for m in matches)


def test_github_token() -> None:
    text = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    matches = scan_for_secrets(text)
    assert any(m.pattern_name == "github_token" for m in matches)


def test_openai_api_key() -> None:
    text = "sk-" + "x" * 48
    matches = scan_for_secrets(text)
    assert any(m.pattern_name == "openai_api_key" for m in matches)


def test_private_key_header() -> None:
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIB..."
    matches = scan_for_secrets(text)
    assert any(m.pattern_name == "private_key_header" for m in matches)


def test_jwt_token() -> None:
    text = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w7Nxj"
    matches = scan_for_secrets(text)
    assert any(m.pattern_name == "jwt_token" for m in matches)


def test_generic_api_key() -> None:
    text = 'api_key = "AbCdEfGhIjKlMnOpQrStUvWxYz1234567890"'
    matches = scan_for_secrets(text)
    assert any(m.pattern_name == "generic_api_key" for m in matches)


def test_no_secrets() -> None:
    text = "This is just a normal conversation about refactoring."
    matches = scan_for_secrets(text)
    assert matches == []


def test_line_numbers_and_context() -> None:
    text = "line1\nline2\nkey = AKIAIOSFODNN7EXAMPLE\nline4"
    matches = scan_for_secrets(text)
    aws = [m for m in matches if m.pattern_name == "aws_access_key"][0]
    assert aws.line_number == 3
    assert aws.context.startswith("AKIA")


def test_scan_patterns_list_populated() -> None:
    assert len(SCAN_PATTERNS) >= 6
    names = {p[0] for p in SCAN_PATTERNS}
    assert "aws_access_key" in names
    assert "github_token" in names
    assert "openai_api_key" in names
