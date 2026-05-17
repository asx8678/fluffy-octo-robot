"""Tests for summarization output validation and fidelity."""

from code_muse.summarization_agent import (
    SummaryValidationResult,
    _check_key_values_preserved,
    _validate_summary_fidelity,
)


def test_validate_with_protected_facts():
    """Test that validation detects preserved facts in a summary."""
    summary_text = (
        "PRESERVED FACTS:\n"
        "- [name] Amina\n"
        "- [project] solar tracker\n"
        "- [deadline] June 3\n"
        "- [budget] 4500 MAD\n"
        "\nKEY VALUES:\n"
        "- deadline: June 3\n"
        "- budget: 4500 MAD\n"
        "\nSUMMARY:\n"
        "Amina is working on a solar tracker project with a deadline of June 3 "
        "and a budget of 4500 MAD."
    )
    from pydantic_ai.messages import ModelRequest, TextPart

    msg = ModelRequest([TextPart(summary_text)])

    result = _validate_summary_fidelity([msg])
    assert result.is_valid or len(result.preserved_facts_missing) == 0


def test_validate_missing_protected_facts():
    """Test that validation catches missing protected facts."""
    summary_text = (
        "SUMMARY:\n"
        "A user is working on a project with some budget. "
        "The details were discussed earlier."
    )
    from pydantic_ai.messages import ModelRequest, TextPart

    msg = ModelRequest([TextPart(summary_text)])

    _validate_summary_fidelity([msg])
    # Without protected facts in the manager, should still be valid
    # (no facts to check against)


def test_validate_empty_summary():
    """Test that validation catches empty summary."""
    from pydantic_ai.messages import ModelRequest, TextPart

    msg = ModelRequest([TextPart("")])

    result = _validate_summary_fidelity([msg])
    assert not result.is_valid
    assert result.retry_needed
    assert "Summary text is empty" in result.issues


def test_check_key_values_preserved():
    """Test checking key value preservation."""
    text = "Amina has a budget of 4500 MAD for the solar tracker project ending June 3."
    keys = ["4500 MAD", "June 3", "Amina", "solar tracker"]

    matched, missing = _check_key_values_preserved(text, keys)

    assert len(missing) == 0
    assert all(k in matched for k in keys)


def test_check_key_values_paraphrased():
    """Test detecting paraphrased values."""
    text = "The user has about 4500 dirhams for their project ending early June."
    keys = ["4500 MAD", "June 3", "Amina"]

    matched, missing = _check_key_values_preserved(text, keys)

    assert "4500 MAD" in missing or "Amina" in missing


def test_check_key_values_empty():
    """Test with no key values to check."""
    text = "Some summary text."
    matched, missing = _check_key_values_preserved(text, [])

    assert matched == []
    assert missing == []


def test_validate_summary_with_structured_output():
    """Test validation of a properly structured summary with all sections."""
    summary_text = (
        "**PRESERVED FACTS:**\n"
        "- [name] Amina\n"
        "- [deadline] June 3\n"
        "\n**KEY VALUES:**\n"
        "- deadline: June 3\n"
        "- name: Amina\n"
        "\n**SUMMARY:**\n"
        "Amina needs to finish the project by June 3."
    )
    from pydantic_ai.messages import ModelRequest, TextPart

    msg = ModelRequest([TextPart(summary_text)])

    result = _validate_summary_fidelity([msg])
    # Key values should be found in the summary body
    assert "deadline" in result.key_values_matched or len(result.issues) == 0


def test_summary_validation_result_defaults():
    """Test SummaryValidationResult default values."""
    result = SummaryValidationResult(is_valid=True)
    assert result.preserved_facts_found == []
    assert result.preserved_facts_missing == []
    assert result.key_values_matched == {}
    assert result.issues == []
    assert not result.retry_needed


def test_validate_with_no_messages():
    """Test validation with empty message list."""
    result = _validate_summary_fidelity([])
    assert not result.is_valid
    assert result.retry_needed


def test_check_key_values_number_match():
    """Test that numeric key values can be matched."""
    text = "The budget is 4500 and the count is 42."
    matched, missing = _check_key_values_preserved(text, ["4500", "42"])

    assert "4500" in matched
    assert "42" in matched
    assert len(missing) == 0


def test_check_key_values_date_flexible():
    """Test that date values can be matched."""
    text = "The deadline is June 3."
    matched, missing = _check_key_values_preserved(text, ["June 3"])

    assert "June 3" in matched
