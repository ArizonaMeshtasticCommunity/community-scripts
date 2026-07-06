#!/usr/bin/env python3
# mm_meta:
#   mode: responder
#   name: Wildfire (On-Demand)
#   emoji: 🔥
#   language: Python
"""
nifc_responder.py — on-demand wildfire incident report (NIFC WFIGS).

The trigger companion to nifc_timer.py. Where the timer pushes lifecycle
alerts (NEW / UPDATE / OUT) on a schedule, this answers a mesh user asking
"what's burning right now?" — same authoritative NIFC source, same data
shape, same multi-line format, so a triggered reply reads identically to
an auto-broadcast.

Two modes, decided by whether a fire-name parameter rides the trigger:

  !wildfire              → the most recently-discovered active AZ wildfires
                           (top MAX_RESULTS, newest first)

  !wildfire telegraph    → fires matching the term — substring, case-insensitive,
  !wildfire gila         against BOTH the incident name AND the POO county. So a
  !wildfire bush         fire name ("telegraph") or a county ("gila") both work;
                         a county returns every active fire in it.

MM/Mesh Commander passes regex captures as PARAM_1, PARAM_2, … env vars.
We scan os.environ for the first non-empty PARAM_* (group order varies by
keyword config and we'd rather be robust than coupled to it).

OUT incidents are excluded — this is a "what's active" report. No state is
touched, so a trigger never affects the timer's NEW/UPDATE/OUT dedup.

Env vars: same as nifc_timer (NIFC_STATE, NIFC_INCLUDE_RX, HOME_LAT/LON).

Suggested Mesh Commander keywords:
  !wildfire              (no capture group)
  !wildfire (.+)         (fire name as capture group → PARAM_1)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import respond, respond_multi, log, log_error
from nifc_timer import fetch_incidents, format_incident

TAG = "nifc_trigger"
MAX_RESULTS = 3


def get_param():
    """First non-empty PARAM_* env var — the fire-name filter, or None."""
    for key in sorted(os.environ.keys()):
        if not key.startswith("PARAM_"):
            continue
        val = os.environ[key].strip()
        if val:
            return val
    return None


def main():
    incidents, err = fetch_incidents()
    if err is not None:
        respond("⚠️ NIFC wildfire data unavailable")
        log_error(TAG, f"fetch failed: {err}")
        return

    active = [i for i in incidents if not i["out"]]
    active.sort(key=lambda i: i.get("discovered", 0), reverse=True)

    term = get_param()
    if term:
        q = term.lower()
        matches = [i for i in active
                   if q in (i["name"] or "").lower() or q in (i["county"] or "").lower()]
        log(TAG, f"query '{term}' matched {len(matches)} active incident(s) (name/county)")
        if not matches:
            respond(f"✅ No active wildfire matching '{term}'")
            return
    else:
        log(TAG, f"{len(active)} active incident(s)")
        if not active:
            respond("✅ No active wildfires reported")
            return
        matches = active

    capped = matches[:MAX_RESULTS]
    if len(matches) > MAX_RESULTS:
        log(TAG, f"capping {len(matches)} matches at {MAX_RESULTS}")

    msgs = [format_incident(i) for i in capped]
    respond_multi(msgs)


if __name__ == "__main__":
    main()
