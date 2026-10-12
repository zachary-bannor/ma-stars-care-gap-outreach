"""Pure SQL and action-mapping helpers for the coordinator worklist app.

Kept free of any Streamlit, network, or Databricks SDK imports so the SQL shape
and the outcome -> status mapping can be unit-tested headless (tests/test_worklist_queries.py).
The app (app.py) and the evidence script (01_evidence.py) both call these, so the
exact read + transactional write-back path is exercised the same way in the UI and
in committed evidence.

Tables (Lakebase Postgres, schema ``ops``, registered in Unity Catalog by Layer 6):
  worklist         read surface, synced from the governed Delta worklist (member-grain,
                   ranked by member_ev, carries the ai_decide lead decision + L5 draft).
  worklist_status  upsert target, one row per member (current coordinator state).
  coordinator_action  append-only log, one row per recorded outreach action.
"""

SCHEMA = "ops"

# Full set of columns the member detail panel reads. Deliberately a subset of the
# lakehouse: the serving surface is already column-minimized to coordinator-entitled
# fields, so the app never selects anything it should not see.
WORKLIST_COLUMNS = [
    "worklist_rank",
    "member_id",
    "contract_id",
    "plan_id",
    "member_ev",
    "open_gap_count",
    "lead_measure",
    "lead_measure_name",
    "lead_confidence",
    "lead_ev",
    "lead_propensity",
    "lead_probabilities",
    "bundle_decision",
    "bundle_measure_name",
    "preferred_channel",
    "tenure_band",
    "draft_subject",
    "draft_body",
    "requires_human_review",
]

# Lighter column set for the list view. The table, headline metrics, and member
# selector need only these, so the per-member draft text and probabilities are not
# shipped for every row on every rerun (they load with the selected member instead).
LIST_COLUMNS = [
    "worklist_rank",
    "member_id",
    "contract_id",
    "member_ev",
    "open_gap_count",
    "lead_measure",
    "lead_measure_name",
    "lead_confidence",
    "requires_human_review",
]

# Action vocabulary offered in the UI.
ACTIONS = ["called", "emailed", "mailed", "scheduled"]
CHANNELS = ["phone", "digital", "mail"]

# Outcome -> (worklist status, follow-up days). None follow-up means no auto-scheduled
# next touch (either the member is done, declined, or an appointment is already set).
OUTCOME_STATUS = {
    "reached": ("contacted", 7),
    "left_voicemail": ("contacted", 3),
    "no_answer": ("attempted", 2),
    "scheduled_appointment": ("scheduled", None),
    "declined": ("declined", None),
    "completed": ("closed", None),
}
OUTCOMES = list(OUTCOME_STATUS.keys())

# The L5 drafts carry a preferred_channel of 'digital' or 'mail_phone'. Suggest a
# default action channel so the coordinator starts from the member's known preference.
PREFERRED_CHANNEL_DEFAULT = {
    "digital": "digital",
    "mail_phone": "phone",
}


def derive_status(outcome):
    """Map a recorded outcome to (status, follow_up_days). Unknown outcomes fall back
    to a safe 'contacted' with a short follow-up rather than dropping the member."""
    return OUTCOME_STATUS.get(outcome, ("contacted", 3))


def default_channel(preferred_channel):
    """Suggest the action channel from the member's L5 preferred_channel."""
    return PREFERRED_CHANNEL_DEFAULT.get(preferred_channel, "phone")


def worklist_select_sql(schema=SCHEMA, limit=None):
    """Prioritized worklist (list columns) joined to the member's current status.

    LEFT JOIN keeps members who have not been worked yet (status NULL). Ordered by
    worklist_rank, which Layer 6 computed from member_ev DESC (the exec-defensible
    ranking, unchanged by ai_decide). No LIMIT by default: the serving table is already
    bounded to the top actionable cohort upstream in Layer 6, so the app reads it whole
    rather than re-capping it to a magic number. `limit` is int-coerced if supplied."""
    cols = ", ".join(f"w.{c}" for c in LIST_COLUMNS)
    sql = (
        f"SELECT {cols}, "
        f"s.status, s.last_action, s.next_action_due, s.updated_at "
        f"FROM {schema}.worklist w "
        f"LEFT JOIN {schema}.worklist_status s USING (member_id) "
        f"ORDER BY w.worklist_rank"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return sql


def member_detail_sql(schema=SCHEMA):
    """Full serving row for one member (parameterized; %s is the member_id)."""
    cols = ", ".join(WORKLIST_COLUMNS)
    return f"SELECT {cols} FROM {schema}.worklist WHERE member_id = %s"


def member_status_sql(schema=SCHEMA):
    """Current status row for one member, to prove the write-back round-trip."""
    return (
        f"SELECT member_id, status, last_action, next_action_due, updated_by, updated_at "
        f"FROM {schema}.worklist_status WHERE member_id = %s"
    )


def insert_action_sql(schema=SCHEMA):
    """Append one outreach action to the immutable log. acted_by records the governed
    identity that performed it (the coordinator service principal)."""
    return (
        f"INSERT INTO {schema}.coordinator_action "
        f"(member_id, measure, action, channel, outcome, notes, acted_by) "
        f"VALUES (%s, %s, %s, %s, %s, %s, %s)"
    )


def upsert_status_sql(schema=SCHEMA):
    """Upsert the member's current coordinator status (one row per member)."""
    return (
        f"INSERT INTO {schema}.worklist_status "
        f"(member_id, status, last_action, next_action_due, updated_by, updated_at) "
        f"VALUES (%s, %s, %s, %s, %s, now()) "
        f"ON CONFLICT (member_id) DO UPDATE SET "
        f"status = EXCLUDED.status, "
        f"last_action = EXCLUDED.last_action, "
        f"next_action_due = EXCLUDED.next_action_due, "
        f"updated_by = EXCLUDED.updated_by, "
        f"updated_at = EXCLUDED.updated_at"
    )
