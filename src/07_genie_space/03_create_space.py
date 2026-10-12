#!/usr/bin/env python3
"""Layer 7 / Create (or update) the governed Genie space from the curated spec.

Builds the serialized_space v2 payload from space_spec.py and calls
genie.create_space (or update_space if a space of the same title already exists, so
re-runs are idempotent). Writes the exact payload and the created space's id / URL to
evidence/07_genie_space/ as text.

Genie reads the governed star schema + the certified metric view, plus the uncertified
scratch trap (reachable on purpose, so OntoRank's preference for the certified source
is a real outcome). The space is served to the quality-analyst persona; Genie runs
every query under the caller's identity, so the Layer 3 masks and row filter apply.

Run locally after the governed surfaces + metric view + trap exist (genie_space_job):

    python3 src/07_genie_space/03_create_space.py
"""
import json
import os
import sys

from databricks.sdk import WorkspaceClient

sys.path.insert(0, os.path.dirname(__file__))
import space_spec

PROFILE = "fe-vm-zrb-fe-bar-uhc-stars"
WAREHOUSE = "c6360590bf1c28d6"
CATALOG = "zrb_fe_bar_uhc_stars_catalog"
TITLE = "MA Stars Care-Gap Analytics (VP Stars)"
DESCRIPTION = ("Governed natural-language analytics over Medicare Advantage Star and HEDIS "
               "care gaps for the quality manager / VP Stars: open gaps, retrievable "
               "Star-weighted value, and the active outreach worklist.")
EVID = os.path.join(os.path.dirname(__file__), "..", "..", "evidence", "07_genie_space")
os.makedirs(EVID, exist_ok=True)

w = WorkspaceClient(profile=PROFILE)


def strip_column_configs(payload):
    """column_configs shape is not empirically confirmed; drop it for a fallback create."""
    p = json.loads(json.dumps(payload))
    for t in p["data_sources"]["tables"]:
        t.pop("column_configs", None)
    return p


def find_existing():
    try:
        resp = w.genie.list_spaces()
        for sp in (getattr(resp, "spaces", None) or []):
            if getattr(sp, "title", None) == TITLE:
                return sp.space_id
    except Exception as e:
        print("list_spaces warning:", str(e).splitlines()[0][:120])
    return None


def create_or_update(payload):
    body = json.dumps(payload)
    existing = find_existing()
    if existing:
        etag = None
        try:
            etag = getattr(w.genie.get_space(existing), "etag", None)
        except Exception:
            pass
        sp = w.genie.update_space(existing, serialized_space=body, warehouse_id=WAREHOUSE,
                                  title=TITLE, description=DESCRIPTION, etag=etag)
        print("updated existing space", existing)
    else:
        sp = w.genie.create_space(warehouse_id=WAREHOUSE, serialized_space=body,
                                  title=TITLE, description=DESCRIPTION)
        print("created space", sp.space_id)
    return sp


def main():
    payload = space_spec.serialized_space(CATALOG)
    try:
        sp = create_or_update(payload)
    except Exception as e:
        msg = str(e).splitlines()[0]
        if "column_config" in msg or "get_example_values" in msg or "build_value_dictionary" in msg:
            print("column_configs rejected, retrying without them:", msg[:120])
            sp = create_or_update(strip_column_configs(payload))
        else:
            raise

    space_id = sp.space_id
    host = w.config.host.rstrip("/")
    url = f"{host}/genie/rooms/{space_id}"

    # Read back the stored serialized_space (the authoritative committed definition).
    got = w.genie.get_space(space_id, include_serialized_space=True)
    stored = got.serialized_space
    with open(os.path.join(EVID, "serialized_space.json"), "w") as f:
        f.write(stored if isinstance(stored, str) else json.dumps(stored, indent=2, default=str))

    info = {
        "space_id": space_id,
        "title": TITLE,
        "url": url,
        "warehouse_id": WAREHOUSE,
        "catalog": CATALOG,
        "tables": list(space_spec.tables(CATALOG).values()),
        "metric_view": space_spec.metric_view(CATALOG),
        "scratch_trap": space_spec.scratch_trap(CATALOG),
        "n_sample_questions": len(space_spec.SAMPLE_QUESTIONS),
        "n_example_sqls": len(space_spec.example_sqls(CATALOG)),
    }
    with open(os.path.join(EVID, "space_info.json"), "w") as f:
        json.dump(info, f, indent=2)
    print("space URL:", url)
    print("wrote serialized_space.json + space_info.json")
    return space_id


if __name__ == "__main__":
    main()
