"""Tests for the Layer 5 safety-critical pure functions in prompt_spec.

The honesty-and-safety claim of Layer 5 rests on two functions, so they are
pinned here:

  - lint_draft: the advisory safety net that flags a condition term, a missing
    [FIRST_NAME] placeholder, or a literal contact number in a drafted body. The
    evidence cites empty lint_flags on all drafts as proof nothing leaked, so the
    lint must actually catch those things.
  - parse_draft: turns the raw model reply (a string, a fenced block, or a list
    of Anthropic content blocks) into the subject/body written to
    gold.outreach_drafts.

Runs with pytest, or directly: `python3 tests/test_prompt_spec.py`.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "05_genai_drafting"))

import prompt_spec


# --- lint_draft -------------------------------------------------------------

def test_lint_flags_condition_term():
    body = "Hi [FIRST_NAME], a reminder about managing your diabetes. Call [CLINIC_PHONE]."
    flags = prompt_spec.lint_draft(body)
    assert any(f.startswith("possible_condition_reference:") and "diabet" in f for f in flags), flags


def test_lint_flags_missing_name_placeholder():
    body = "Hello there, your plan covers a yearly eye exam at no cost. Call [CLINIC_PHONE]."
    assert "missing_name_placeholder" in prompt_spec.lint_draft(body)


def test_lint_flags_literal_contact_number():
    body = "Hi [FIRST_NAME], call us at 555-123-4567 to schedule your covered screening."
    assert "possible_literal_contact" in prompt_spec.lint_draft(body)


def test_lint_clean_body_has_no_flags():
    body = ("Hi [FIRST_NAME], a yearly eye exam is a routine benefit your plan covers at no "
            "extra cost. Call [CLINIC_PHONE] to schedule.")
    assert prompt_spec.lint_draft(body) == []


def test_lint_clean_body_with_90_day_supply_not_flagged():
    # "90-day" must not trip the literal-contact regex; the MAD drafts rely on it.
    body = ("Hi [FIRST_NAME], we make refills easy with 90-day supplies and free mail delivery. "
            "Call [CLINIC_PHONE] to set up automatic refills.")
    assert prompt_spec.lint_draft(body) == []


# --- parse_draft ------------------------------------------------------------

def test_parse_clean_json():
    out = prompt_spec.parse_draft('{"subject": "A covered benefit", "body": "Hi [FIRST_NAME], ..."}')
    assert out == {"subject": "A covered benefit", "body": "Hi [FIRST_NAME], ..."}


def test_parse_fenced_json():
    reply = '```json\n{"subject": "S", "body": "Hi [FIRST_NAME]"}\n```'
    assert prompt_spec.parse_draft(reply) == {"subject": "S", "body": "Hi [FIRST_NAME]"}


def test_parse_salvages_json_after_prose():
    reply = 'Here is the draft:\n{"subject": "S", "body": "Hi [FIRST_NAME]"}'
    assert prompt_spec.parse_draft(reply) == {"subject": "S", "body": "Hi [FIRST_NAME]"}


def test_parse_non_json_falls_back_to_body():
    reply = "Hi [FIRST_NAME], this is plain text, not JSON."
    assert prompt_spec.parse_draft(reply) == {"subject": "", "body": reply}


def test_parse_coerces_list_content_blocks():
    # The gateway may return Anthropic-style content blocks: a reasoning block
    # (no usable text) followed by the actual text block.
    reply = [
        {"type": "reasoning", "summary": [{"type": "summary_text", "text": ""}]},
        {"type": "text", "text": '{"subject": "S", "body": "Hi [FIRST_NAME]"}'},
    ]
    assert prompt_spec.parse_draft(reply) == {"subject": "S", "body": "Hi [FIRST_NAME]"}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
