"""Layer 5 / GenAI outreach drafting: shared prompt spec.

Imported by the generation notebook (01) and the evidence writer (02) so the
prompt that produced the drafts and the prompt in the evidence are the same
string, with no drift.

The honesty-and-safety contract lives here. The model is given ONLY
non-identifying segment features (the covered service, the member's preferred
contact channel, and a coarse tenure band). It never sees a name, a member id, a
birth date, a contract, a diagnosis, or any clinical value, so it cannot leak or
fabricate member specifics. Everything personal is a merge placeholder a human
coordinator fills before anything is sent, and every draft is a human-review
draft that is never auto-sent.
"""

# Each HEDIS measure maps to a member-safe, non-diagnostic description of a
# covered preventive service. The framing is deliberate: outreach must encourage
# the service WITHOUT stating or implying the member has a condition. EED/GSD/MAD
# are diabetes measures and CBP is a hypertension measure, but the member never
# gets told that; they are offered a routine, covered service any eligible member
# would be offered.
MEASURE_SERVICE = {
    "EED": {
        "name": "a yearly eye exam",
        "purpose": "a routine eye exam that the plan covers at no extra cost and recommends for members each year",
        "cta": "schedule a covered eye exam",
    },
    "GSD": {
        "name": "a quick lab test (a simple blood draw)",
        "purpose": "a routine lab test the plan covers so the member's own doctor can keep an eye on their overall health",
        "cta": "complete a covered lab test",
    },
    "CBP": {
        "name": "a blood pressure check",
        "purpose": "a quick, covered blood pressure check the member can get with their care team or at a local pharmacy",
        "cta": "get a covered blood pressure check",
    },
    "COL": {
        "name": "a colorectal cancer screening",
        "purpose": "a covered colorectal cancer screening recommended for members in this age range, with easy options including a simple at-home test",
        "cta": "complete a covered colorectal screening",
    },
    "MAD": {
        "name": "refilling prescriptions on time",
        "purpose": "a friendly reminder that the plan makes it easy to refill the prescriptions the member already takes, including 90-day supplies and free mail delivery",
        "cta": "refill prescriptions or set up automatic refills",
    },
}

# Human-readable channel and tenure descriptions. These are the ONLY member
# attributes that reach the model, and neither is identifying.
CHANNEL_TEXT = {
    "digital": "digital (a short email, text, or in-app message)",
    "mail_phone": "mail or a phone call (the member has no digital contact on file)",
}

TENURE_TEXT = {
    "new": "new to the plan (less than a year)",
    "established": "with the plan for a few years",
    "longtime": "a long-time member (several years)",
}

SYSTEM_PROMPT = """You are a copywriter on the care team of a Medicare Advantage health plan. \
You write short, warm, plain-language outreach that encourages a member to complete a routine, \
covered preventive health service.

You are given ONLY three things about the member: the covered service to encourage, their preferred \
contact channel, and roughly how long they have been with the plan. You know nothing else about them, \
and you must not pretend to.

Hard rules:
- NEVER state or imply the member has any medical condition, diagnosis, risk, or test result. Frame the \
service as a routine benefit the plan offers to eligible members, never as a response to a health problem.
- NEVER invent specifics. No real names, no dates, no phone numbers, no clinic or doctor names, no dollar \
amounts, no rewards or gift cards. The only benefit you may state is that the plan covers the service at \
no extra cost, which is true for these preventive services.
- Use square-bracket merge placeholders for anything personal: [FIRST_NAME] in the greeting, [PLAN_NAME] \
for the plan name, and [CLINIC_PHONE] for a number to call. A human coordinator fills these in before \
anything is sent. Do not write a real name or number yourself.
- Keep it short and kind: 2 to 4 short sentences, about a 6th-grade reading level, one clear call to action. \
Digital messages are a touch shorter and more direct; mail or phone messages can be a sentence warmer.
- This is a DRAFT for a human coordinator to review and edit. It will never be sent automatically.

Return ONLY strict JSON on a single line, no markdown and no commentary, in exactly this shape:
{"subject": "<short subject or opening line>", "body": "<the message, with [FIRST_NAME] greeting>"}"""


def tenure_band(months):
    """Coarsen tenure_months into a non-identifying band."""
    if months is None:
        return "established"
    if months < 12:
        return "new"
    if months < 48:
        return "established"
    return "longtime"


def channel_of(digital_on_file):
    """Preferred channel from the digital-contact flag (non-identifying)."""
    return "digital" if digital_on_file else "mail_phone"


def segment_key(measure_id, channel, tenure):
    return f"{measure_id}|{channel}|{tenure}"


def build_messages(measure_id, channel, tenure):
    """The (system, user) message pair for one non-PHI segment."""
    svc = MEASURE_SERVICE[measure_id]
    user = (
        f"Service to encourage: {svc['name']} ({svc['purpose']}).\n"
        f"Preferred contact channel: {CHANNEL_TEXT[channel]}.\n"
        f"Member tenure: {TENURE_TEXT[tenure]}.\n"
        f"Suggested call to action: {svc['cta']}.\n\n"
        "Write the outreach draft now."
    )
    return SYSTEM_PROMPT, user


# Advisory lint. These never block a draft (every draft is human-reviewed), but
# they flag anything that drifts from the safety contract so a reviewer and the
# evidence can see it. Condition terms should never appear given the prompt; the
# lint proves it on the actual output rather than asserting it.
_CONDITION_TERMS = [
    "diabet", "hypertens", "high blood pressure", "a1c", "hemoglobin",
    "cholesterol", "diagnos", "disease", "condition",
]


def lint_draft(body):
    """Return a list of advisory safety flags for a drafted body."""
    flags = []
    low = (body or "").lower()
    hits = sorted({t for t in _CONDITION_TERMS if t in low})
    if hits:
        flags.append("possible_condition_reference:" + "+".join(hits))
    if "[first_name]" not in low:
        flags.append("missing_name_placeholder")
    # A literal 7+ digit run or NNN-NNN pattern suggests an invented phone number.
    import re
    if re.search(r"\d[\d\-\.\s]{6,}\d", body or ""):
        flags.append("possible_literal_contact")
    return flags


def _to_text(content):
    """Coerce a chat reply to text. The gateway may return a plain string or a
    list of content blocks (Anthropic-style); join the text parts of the latter."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict):
                parts.append(b.get("text") or b.get("content") or "")
            else:
                parts.append(getattr(b, "text", "") or "")
        return "".join(parts)
    return str(content)


def parse_draft(text):
    """Pull {subject, body} out of the model's reply, tolerant of stray fences."""
    import json
    import re
    s = _to_text(text).strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    try:
        obj = json.loads(s)
        return {"subject": str(obj.get("subject", "")).strip(),
                "body": str(obj.get("body", "")).strip()}
    except Exception:
        pass
    # Fallback: first {...} block, else treat the whole reply as the body.
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            return {"subject": str(obj.get("subject", "")).strip(),
                    "body": str(obj.get("body", "")).strip()}
        except Exception:
            pass
    return {"subject": "", "body": s}
