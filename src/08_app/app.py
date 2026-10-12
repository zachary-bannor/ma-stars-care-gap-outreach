"""Stars Care-Gap Coordinator Worklist (Layer 8, the Databricks App).

The coordinator-facing surface that closes the end-to-end journey. It reads the
prioritized worklist from the Lakebase serving table ops.worklist (member_ev ranking
plus the Layer 6 ai_decide lead decision and the Layer 5 outreach draft), lets a
coordinator work a member, and records the outreach with a transactional write-back
to ops.coordinator_action (append) and ops.worklist_status (upsert).

Governed identity: the app connects to Lakebase as the coordinator service principal
(the same persona proven in Layer 3 and used for write-back in Layer 6) via OAuth M2M.
The client secret is injected from a Databricks secret scope, never stored in code.
Coordinator-safety on this serving path is enforced two ways, by design: the serving
table is already the column-minimized, contract-scoped projection built in Layer 6
(cleartext member_id, no PHI leaves the lakehouse), and the identity holds only the
least-privilege coordinator Postgres role (no DELETE, no other schemas). The Layer 3
Unity Catalog masks and row filter enforce on the analytics path (the Layer 7 Genie
space); they are not re-implemented here.

Every operation is a sub-second point query against Postgres, so no request comes near
the Databricks Apps ~120s ingress timeout and the long-running async/WebSocket pattern
is not needed.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import psycopg
import streamlit as st
from databricks.sdk import WorkspaceClient

import worklist_queries as q

# --- configuration (all from the app environment; see app.yaml) -------------------
HOST = os.environ.get("DATABRICKS_HOST")  # auto-injected by the Apps runtime
INSTANCE = os.environ.get("LAKEBASE_INSTANCE", "zrb-stars-worklist")
LOGICAL_DB = os.environ.get("PG_DATABASE", "databricks_postgres")
PG_SCHEMA = os.environ.get("PG_SCHEMA", "ops")
COORD_CLIENT_ID = os.environ.get("COORD_CLIENT_ID")
COORD_CLIENT_SECRET = os.environ.get("COORD_CLIENT_SECRET")  # from secret scope via valueFrom

st.set_page_config(page_title="Stars Care-Gap Coordinator Worklist", layout="wide")


# --- connection (coordinator SP OAuth M2M -> short-lived Lakebase credential) ------
@st.cache_resource(ttl=2400)
def _db_credential():
    """Mint a Lakebase connection credential as the coordinator service principal.

    Cached for 40 minutes, comfortably under the credential's ~1h lifetime; open_conn()
    clears this and retries once if a connection is ever rejected for an expired token.
    Returns (read_write_dns, token)."""
    ws = WorkspaceClient(
        host=HOST,
        client_id=COORD_CLIENT_ID,
        client_secret=COORD_CLIENT_SECRET,
        auth_type="oauth-m2m",
    )
    inst = ws.database.get_database_instance(name=INSTANCE)
    cred = ws.database.generate_database_credential(instance_names=[INSTANCE])
    return inst.read_write_dns, cred.token


def _connect(dns, token):
    return psycopg.connect(
        host=dns,
        port=5432,
        dbname=LOGICAL_DB,
        user=COORD_CLIENT_ID,
        password=token,
        sslmode="require",
        autocommit=False,
        connect_timeout=10,
    )


def open_conn():
    """Open a fresh Lakebase connection, refreshing the cached credential once if the
    first attempt is rejected (e.g. the token expired just before use)."""
    dns, token = _db_credential()
    try:
        return _connect(dns, token)
    except psycopg.OperationalError:
        _db_credential.clear()
        dns, token = _db_credential()
        return _connect(dns, token)


def _rows_to_df(cur):
    cols = [c.name for c in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=cols)


@st.cache_data(ttl=30, show_spinner=False)
def load_worklist():
    """List-view worklist, cached briefly so pure UI reruns (selecting a member) do not
    re-hit Lakebase. Cleared after a write-back so a recorded action shows immediately."""
    with open_conn() as conn, conn.cursor() as cur:
        cur.execute(q.worklist_select_sql(schema=PG_SCHEMA))
        return _rows_to_df(cur)


def load_member(member_id):
    with open_conn() as conn, conn.cursor() as cur:
        cur.execute(q.member_detail_sql(schema=PG_SCHEMA), (member_id,))
        df = _rows_to_df(cur)
    return df.iloc[0].to_dict() if len(df) else None


def record_action(member_id, measure, action, channel, outcome, notes):
    """Transactional write-back: append the action and upsert the member's status in a
    single commit. Rolls back and re-raises on any error so a partial write never lands."""
    status, follow_up_days = q.derive_status(outcome)
    due = (
        datetime.now(timezone.utc) + timedelta(days=follow_up_days)
        if follow_up_days is not None
        else None
    )
    conn = open_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                q.insert_action_sql(schema=PG_SCHEMA),
                (member_id, measure, action, channel, outcome, notes, COORD_CLIENT_ID),
            )
            cur.execute(
                q.upsert_status_sql(schema=PG_SCHEMA),
                (member_id, status, action, due, COORD_CLIENT_ID),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return status, due


def read_status(member_id):
    with open_conn() as conn, conn.cursor() as cur:
        cur.execute(q.member_status_sql(schema=PG_SCHEMA), (member_id,))
        df = _rows_to_df(cur)
    return df.iloc[0].to_dict() if len(df) else None


# --- helpers for display -----------------------------------------------------------
def _fmt_money(x):
    try:
        return f"${float(x):,.2f}"
    except (TypeError, ValueError):
        return "-"


def _fmt_pct(x):
    try:
        return f"{float(x) * 100:.0f}%"
    except (TypeError, ValueError):
        return "-"


def _parse_probs(raw):
    if not raw:
        return None
    try:
        d = json.loads(raw) if isinstance(raw, str) else dict(raw)
        return {k: float(v) for k, v in d.items()}
    except (ValueError, TypeError):
        return None


# --- UI ----------------------------------------------------------------------------
def main():
    st.title("Stars Care-Gap Coordinator Worklist")
    st.caption(
        "Prioritized Medicare Advantage HEDIS care-gap outreach for contract H1234. "
        "Running as the governed coordinator service principal (least-privilege: "
        "record outreach, cannot delete)."
    )

    # Surface the confirmation of the last write-back, which survives the st.rerun that
    # refreshes the worklist (st.success alone would be discarded by that rerun).
    flash = st.session_state.pop("flash", None)
    if flash:
        {"success": st.success, "error": st.error}.get(flash[0], st.info)(flash[1])

    missing = [n for n, v in {
        "DATABRICKS_HOST": HOST,
        "COORD_CLIENT_ID": COORD_CLIENT_ID,
        "COORD_CLIENT_SECRET": COORD_CLIENT_SECRET,
    }.items() if not v]
    if missing:
        st.error(
            "The app is missing required configuration: "
            + ", ".join(missing)
            + ". Check app.yaml env and the attached secret resource."
        )
        st.stop()

    try:
        wl = load_worklist()
    except Exception as exc:  # surface connection/identity problems plainly
        st.error(f"Could not load the worklist from Lakebase: {exc}")
        st.stop()

    if wl.empty:
        st.warning("The worklist is empty. Has Layer 6 (lakebase_worklist_job) been run?")
        st.stop()

    # headline numbers: the exec story (EV dollars) plus operational state
    total_members = len(wl)
    total_ev = wl["member_ev"].astype(float).sum()
    needs_review = int(wl["requires_human_review"].fillna(False).astype(bool).sum())
    worked = int(wl["status"].notna().sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Members on worklist", f"{total_members:,}")
    c2.metric(
        "Worklist Star-weighted value",
        _fmt_money(total_ev),
        help="Expected Star-weighted value across this actionable worklist cohort "
             "(the top members by EV for contract H1234). Not the full-contract total.",
    )
    c3.metric("Drafts needing review", f"{needs_review:,}")
    c4.metric("Already worked", f"{worked:,} / {total_members:,}")

    left, right = st.columns([3, 2], gap="large")

    with left:
        st.subheader("Worklist")
        show = wl.copy()
        show["member_ev"] = show["member_ev"].map(_fmt_money)
        show["lead_confidence"] = show["lead_confidence"].map(_fmt_pct)
        display_cols = [
            "worklist_rank", "member_id", "contract_id", "member_ev",
            "open_gap_count", "lead_measure_name", "lead_confidence",
            "requires_human_review", "status",
        ]
        st.dataframe(
            show[display_cols],
            hide_index=True,
            use_container_width=True,
            height=560,
        )

    with right:
        st.subheader("Work a member")
        options = wl["member_id"].tolist()
        labels = {
            r.member_id: f"#{int(r.worklist_rank)}  {r.member_id}  "
                         f"({r.lead_measure}, {_fmt_money(r.member_ev)})"
            for r in wl.itertuples()
        }
        member_id = st.selectbox(
            "Member", options, format_func=lambda m: labels.get(m, m)
        )
        detail = load_member(member_id)
        if detail is None:
            st.info("Select a member to see the recommended outreach.")
            return

        st.markdown(
            f"**Lead ask: {detail['lead_measure_name']}**  \n"
            f"Expected value {_fmt_money(detail['lead_ev'])} | "
            f"close propensity {_fmt_pct(detail['lead_propensity'])} | "
            f"decision confidence {_fmt_pct(detail['lead_confidence'])}"
        )
        if detail.get("bundle_decision") == "bundle" and detail.get("bundle_measure_name"):
            st.markdown(f"Suggested bundle: also raise **{detail['bundle_measure_name']}**")

        probs = _parse_probs(detail.get("lead_probabilities"))
        if probs:
            with st.expander("ai_decide lead probabilities"):
                st.bar_chart(pd.Series(probs).sort_values(ascending=False))

        if detail.get("requires_human_review"):
            st.warning(
                "This outreach draft requires human review and is never auto-sent. "
                "The coordinator confirms the content before contacting the member."
            )
        with st.container(border=True):
            st.markdown(f"**Draft subject:** {detail.get('draft_subject') or '-'}")
            st.markdown(detail.get("draft_body") or "_No draft on file._")
            st.caption(
                f"Preferred channel: {detail.get('preferred_channel') or '-'} | "
                f"tenure: {detail.get('tenure_band') or '-'}"
            )

        existing = read_status(member_id)
        if existing and existing.get("status"):
            st.info(
                f"Current status: **{existing['status']}** "
                f"(last action {existing.get('last_action') or '-'}, "
                f"updated {existing.get('updated_at')})"
            )

        with st.form("record_action", clear_on_submit=True):
            st.markdown("**Record outreach**")
            action = st.selectbox("Action", q.ACTIONS)
            default_ch = q.default_channel(detail.get("preferred_channel"))
            channel = st.selectbox(
                "Channel",
                q.CHANNELS,
                index=q.CHANNELS.index(default_ch) if default_ch in q.CHANNELS else 0,
            )
            outcome = st.selectbox("Outcome", q.OUTCOMES)
            notes = st.text_area("Notes", placeholder="Optional notes for the member record.")
            submitted = st.form_submit_button("Save action")

        if submitted:
            try:
                status, due = record_action(
                    member_id, detail["lead_measure"], action, channel, outcome, notes
                )
            except Exception as exc:
                st.error(f"Write-back failed and was rolled back: {exc}")
            else:
                due_txt = f", follow-up due {due:%Y-%m-%d}" if due else ""
                st.session_state["flash"] = (
                    "success",
                    f"Recorded for {member_id}. Status is now '{status}'{due_txt}.",
                )
                load_worklist.clear()  # refresh the cached list so the new status shows
                st.rerun()


if __name__ == "__main__":
    main()
