#!/usr/bin/env python3
# mm_meta:
#   mode: timer
#   name: Wildfire Incidents (NIFC)
#   emoji: 🔥
#   language: Python
"""
nifc_timer.py — named wildfire INCIDENT alerts from NIFC WFIGS.

Polls the National Interagency Fire Center's WFIGS "Current Incident Locations"
ArcGIS feature service (the interagency system of record, fed via IRWIN — covers
federal/state/tribal/local) for active WILDFIRE incidents in a state and tracks
each one through its lifecycle:

  • NEW       — first time we see the incident -> "🔥 NEW WILDFIRE: …" + map pin
  • UPDATE    — a MATERIAL change (acres grew ≥25%/≥10ac, or containment ±10 pts)
                -> "🔥 <name>: <acres>ac, <n>% contained" + refreshed pin
  • OUT       — FireOutDateTime set -> "✅ <name> is OUT" ONCE, pin removed, then
                never reported again (even while it lingers in the feed)

Between material changes, an active incident's pin is silently re-affirmed every
REAFFIRM_HOURS (re-broadcast, no text) so it stays on every map during a multi-day
fire without spamming the channel.

Unlike satellite hotspot feeds (FIRMS), every record here is a real reported
incident — no ag-burn / glint false positives — and carries name/size/containment.
Free, no API key. Returns {"responses", "waypoints"} for Mesh Commander to send.

Env (all optional):
  NIFC_STATE        POOState filter (default 'US-AZ')
  NIFC_INCLUDE_RX   '1' to also report prescribed burns (default off — WF only)
  PIN_TTL_HOURS     pin lifetime per (re)broadcast (default 48)
  REAFFIRM_HOURS    silent pin keep-alive interval for an active fire (default 24)
  ACRES_GROWTH      material growth ratio (default 1.25 = +25%)
  CONTAIN_DELTA     material containment change in points (default 10)
  MAX_MSGS          per-cycle cap on alerts (default 4)
  STATE_TTL_HOURS   forget an incident unseen this long (default 720 = 30d)
  WAYPOINT_CHANNEL  channel index the map pins ride (unset = the pins follow
                    the timer's own configured channel, same as the text
                    alerts; set an index only to force a different channel,
                    e.g. 0 = PRIMARY)
  HOME_LAT/HOME_LON optional — adds distance + bearing from here
"""
import os, sys, json, time, math, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    clamp, load_state, save_state, respond_silent, respond_multi, log, log_error,
)

TAG = "nifc"

SERVICE = ("https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
           "WFIGS_Incident_Locations_Current/FeatureServer/0/query")
STATE_POO   = os.getenv("NIFC_STATE", "US-AZ")
INCLUDE_RX  = os.getenv("NIFC_INCLUDE_RX", "") in ("1", "true", "yes")
PIN_TTL_H   = float(os.getenv("PIN_TTL_HOURS", "48"))
REAFFIRM_H  = float(os.getenv("REAFFIRM_HOURS", "24"))
ACRES_GROWTH = float(os.getenv("ACRES_GROWTH", "1.25"))
CONTAIN_DELTA = float(os.getenv("CONTAIN_DELTA", "10"))
MAX_MSGS    = int(os.getenv("MAX_MSGS", "4"))
STATE_TTL_H = float(os.getenv("STATE_TTL_HOURS", "720"))
# Unset (None) = pins ride the timer's own configured channel (JSON null →
# Mesh Commander's _emit_script_waypoints falls back to the rule's channel).
_wc = os.getenv("WAYPOINT_CHANNEL", "").strip()
WP_CHANNEL  = int(_wc) if _wc else None
STATE_FILE  = "nifc_seen.json"

_FIELDS = ("IncidentName,IncidentSize,DiscoveryAcres,PercentContained,POOCounty,"
           "FireDiscoveryDateTime,FireOutDateTime,ControlDateTime,FireCause,"
           "UniqueFireIdentifier,IrwinID,IncidentTypeCategory")


def _home():
    try:
        return float(os.environ["HOME_LAT"]), float(os.environ["HOME_LON"])
    except (KeyError, ValueError):
        return None

def _bearing(lat1, lon1, lat2, lon2):
    y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
         - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.cos(math.radians(lon2 - lon1)))
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][
        round(((math.degrees(math.atan2(y, x)) + 360) % 360) / 45) % 8]

def _dist_mi(lat1, lon1, lat2, lon2):
    R = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))

def _wid(eid):
    # stable uint32 waypoint id from the (string) IRWIN/unique fire id
    return int(__import__("hashlib").sha1(str(eid).encode()).hexdigest()[:8], 16)

def _acres(rec):
    for k in ("IncidentSize", "DiscoveryAcres"):
        v = rec.get(k)
        if v not in (None, ""):
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None

def _fmt_acres(a):
    if a is None:
        return "size unknown"
    return f"{a:,.0f} ac" if a >= 1 else "<1 ac"

def _epoch_ms(v):
    # ArcGIS f=json returns dates as epoch milliseconds
    try:
        return float(v) / 1000.0 if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def fetch_incidents():
    where = f"POOState='{STATE_POO}'"
    if not INCLUDE_RX:
        where += " AND IncidentTypeCategory='WF'"
    params = {"where": where, "outFields": _FIELDS, "returnGeometry": "true",
              "outSR": "4326", "f": "json"}
    url = SERVICE + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mesh-commander/nifc"})
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.load(r)
    except Exception as e:
        log_error(TAG, f"NIFC fetch failed: {e}")
        return None, f"NIFC fetch failed: {e}"
    if data.get("error"):
        return None, f"NIFC error: {data['error']}"
    out = []
    for f in data.get("features", []):
        a = f.get("attributes", {})
        g = f.get("geometry") or {}
        eid = a.get("UniqueFireIdentifier") or a.get("IrwinID")
        if not eid:
            continue
        out.append({
            "id": str(eid),
            "name": (a.get("IncidentName") or "Unnamed").strip().title(),
            "county": (a.get("POOCounty") or "").strip(),
            "acres": _acres(a),
            "contained": a.get("PercentContained"),
            "cause": (a.get("FireCause") or "").strip(),
            "discovered": _epoch_ms(a.get("FireDiscoveryDateTime")),
            "out": a.get("FireOutDateTime") is not None,
            "lat": g.get("y") if g.get("y") is not None else a.get("InitialLatitude"),
            "lon": g.get("x") if g.get("x") is not None else a.get("InitialLongitude"),
        })
    return out, None


def is_material(prior, inc):
    """True if the incident changed enough to re-broadcast since we last did."""
    pa = prior.get("acres") or 0
    pc = prior.get("contained") or 0
    a = inc.get("acres") or 0
    c = inc.get("contained") or 0
    if pa <= 0 and a > 0:
        return True
    if pa > 0 and a >= pa * ACRES_GROWTH and (a - pa) >= 10:
        return True
    if abs(c - pc) >= CONTAIN_DELTA:
        return True
    return False


def format_incident(inc, label=""):
    """Operator's multi-line wildfire format (3-4 lines):
        🔥 <label>: <FIRE NAME>          (label e.g. "NEW WILDFIRE" / "UPDATE";
                                          omitted → bare "🔥 <FIRE NAME>")
        📍 <County> County  📏 <#> ac
        ℹ️ <% contained>, <cause>         (only if there's info worth a line)
        🗺️ <dist/bearing> <map link>     (only when we have coordinates)
    Shared by the timer (NEW/UPDATE) and the on-demand responder."""
    name = (inc["name"] or "Unnamed")[:40]
    head = f"🔥 {label}: {name}" if label else f"🔥 {name}"
    loc = f"📍 {inc['county']} County  " if inc["county"] else ""
    lines = [head, f"{loc}📏 {_fmt_acres(inc['acres'])}"]
    info = _info_line(inc)
    if info:
        lines.append(info)
    mp = _map_line(inc)
    if mp:
        lines.append(mp)
    return clamp("\n".join(lines))

def alert_new(inc):
    return format_incident(inc, "NEW WILDFIRE")

def alert_update(inc):
    return format_incident(inc, "UPDATE")

def alert_out(inc):
    return clamp(f"✅ {inc['name']} wildfire is OUT")

def _info_line(inc):
    bits = []
    c = inc.get("contained")
    if c not in (None, ""):
        try:
            bits.append(f"{float(c):.0f}% contained")
        except (TypeError, ValueError):
            pass
    cause = (inc.get("cause") or "").strip()
    if cause and cause.lower() not in ("undetermined", "under investigation"):
        bits.append(cause)
    return "ℹ️ " + ", ".join(bits) if bits else ""

def _map_line(inc):
    if inc["lat"] is None or inc["lon"] is None:
        return ""
    home = _home()
    pre = ""
    if home:
        pre = f"{_dist_mi(*home, inc['lat'], inc['lon']):.0f}mi {_bearing(*home, inc['lat'], inc['lon'])} "
    # %2C (encoded comma), not a literal ',': the Meshtastic Android app's URL
    # linkifier regex has no comma in its char class and truncates the link at
    # the first ',' (dropping the longitude). %2C survives + Maps decodes it.
    return f"🗺️ {pre}https://www.google.com/maps?q={inc['lat']:.4f}%2C{inc['lon']:.4f}"


# Waypoint.icon codepoint — Meshtastic apps render it as the map pin, so the
# 🔥 rides the icon field, not the name (emoji-in-the-name showed as a default
# pin with the emoji in the title on receiving apps).
FIRE_ICON = ord("🔥")


def pin_for(inc, expire):
    c = inc.get("contained")
    cs = f", {c:.0f}% contained" if c not in (None, "") else ""
    return {
        "waypoint_id": _wid(inc["id"]),
        "name": inc["name"][:30],
        "description": f"{_fmt_acres(inc['acres'])}{cs}"[:100],
        "icon": FIRE_ICON,
        "lat": round(float(inc["lat"]), 5), "lon": round(float(inc["lon"]), 5),
        "expire": expire, "channel": WP_CHANNEL,
    }


def main():
    incidents, err = fetch_incidents()
    if err is not None:
        respond_silent(error=err)
        return

    state = load_state(STATE_FILE)
    if not isinstance(state, dict):
        state = {}
    now = time.time()
    cutoff = now - STATE_TTL_H * 3600
    state = {k: v for k, v in state.items()
             if isinstance(v, dict) and v.get("last_seen", 0) >= cutoff}

    pin_ttl = int(now + PIN_TTL_H * 3600)
    reaffirm = REAFFIRM_H * 3600
    texts, waypoints = [], []

    # Per-cycle text budget. The cap is enforced INLINE (not after the loop) and
    # gated together with state advancement: an incident we can't announce this
    # cycle is DEFERRED — its state is left untouched so it's still NEW/material
    # next cycle and gets announced then. Draining ~MAX_MSGS/cycle avoids both a
    # channel flood AND the old bug where capping texts post-loop marked every
    # incident seen while only sending MAX_MSGS — the rest never announced.
    # Newest fires first so a backlog drains most-recent-first.
    incidents.sort(key=lambda i: i.get("discovered", 0), reverse=True)
    budget = MAX_MSGS

    for inc in incidents:
        sid = inc["id"]
        prior = state.get(sid) if isinstance(state.get(sid), dict) else None
        has_geo = inc["lat"] is not None and inc["lon"] is not None

        # ---- OUT: announce once, remove the pin, then never report again ----
        if inc["out"]:
            if prior and not prior.get("out_announced"):
                if budget <= 0:
                    # defer the OUT text — keep alive, announce next cycle
                    prior["last_seen"] = now
                    state[sid] = prior
                    continue
                budget -= 1
                texts.append(alert_out(inc))
                if has_geo:
                    waypoints.append({"waypoint_id": _wid(sid), "name": inc["name"][:30], "icon": FIRE_ICON,
                                      "lat": round(float(inc["lat"]),5),
                                      "lon": round(float(inc["lon"]),5), "expire": int(now - 1),  # past expiry = delete
                                      "channel": WP_CHANNEL})
                prior["out_announced"] = True
            (prior or state.setdefault(sid, {}))["last_seen"] = now
            state[sid] = prior or state[sid]
            continue

        # ---- NEW ----
        if not prior:
            if budget <= 0:
                # defer: leave state UNwritten so it's still new next cycle
                continue
            budget -= 1
            state[sid] = {"first": now, "last_seen": now, "last_pin": now,
                          "acres": inc["acres"], "contained": inc["contained"]}
            texts.append(alert_new(inc))
            if has_geo:
                waypoints.append(pin_for(inc, pin_ttl))
            continue

        # ---- existing active incident ----
        prior["last_seen"] = now
        if is_material(prior, inc):
            if budget <= 0:
                # defer the UPDATE text — leave acres/contained UNchanged so it's
                # still material next cycle; keep the pin alive silently meanwhile
                if has_geo and (now - prior.get("last_pin", 0)) >= reaffirm:
                    prior["last_pin"] = now
                    waypoints.append(pin_for(inc, pin_ttl))
                state[sid] = prior
                continue
            budget -= 1
            texts.append(alert_update(inc))
            prior["acres"] = inc["acres"]
            prior["contained"] = inc["contained"]
            prior["last_pin"] = now
            if has_geo:
                waypoints.append(pin_for(inc, pin_ttl))
        elif has_geo and (now - prior.get("last_pin", 0)) >= reaffirm:
            # silent keep-alive: refresh the pin, no text
            prior["last_pin"] = now
            waypoints.append(pin_for(inc, pin_ttl))
        state[sid] = prior

    save_state(STATE_FILE, state)

    if not texts and not waypoints:
        respond_silent()
        return
    log(TAG, f"{len(texts)} text alert(s), {len(waypoints)} pin(s)")
    respond_multi(texts, waypoints=waypoints)


if __name__ == "__main__":
    main()
