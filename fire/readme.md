# NIFC Wildfire Alerts for Meshtastic

This project provides Arizona wildfire alerts and map pins for Meshtastic using the National Interagency Fire Center (NIFC) WFIGS incident feed.

I spend a lot of time out in the sticks and monitor wildfire radio traffic, but wanted a backup source of information when internet connectivity is available. This script pulls incident data from official wildfire reporting systems and broadcasts it over the mesh using the Weather channel (`Ww==`).

## Data Source

Information comes from the National Interagency Fire Center (NIFC) WFIGS Current Incident Locations feed.

WFIGS is the interagency system of record used by federal, state, tribal, and local agencies and is fed through IRWIN incident reporting systems.

Unlike satellite hotspot feeds, every alert represents a real reported wildfire incident with incident details such as name, size, county, and containment status when available. This avoids false alarms caused by agricultural burns, industrial heat sources, or other non-fire detections.

## Automatic Wildfire Alerts

The timer script monitors active Arizona wildfires and broadcasts alerts when significant events occur.

### 🔥 NEW WILDFIRE

Sent when a new wildfire appears in the feed.

Alerts can include:

* Incident name
* County
* Acreage
* Containment percentage (when available)
* Cause (when reported)
* Distance and bearing from a configured home location
* Google Maps link

### 🔥 UPDATE

Sent only when something material changes:

* Fire size increases by at least 25% and at least 10 acres
* Containment changes by 10 percentage points or more

Minor updates are ignored to reduce channel noise.

### ✅ OUT

Sent once when a wildfire is reported as out.

## Wildfire Waypoints

Active wildfires are also broadcast as Meshtastic map waypoints.

Waypoint behavior:

* New fires create a 🔥 map pin
* Existing pins update as acreage or containment changes
* Active fires receive periodic silent refreshes to keep pins visible during long-duration incidents
* Duplicate pins are not created
* Pins are automatically removed when a fire is declared out

Tapping a waypoint displays the latest available acreage and containment information.

## Containment Information

Containment percentages are not always available for new or small initial-attack fires.

When reported, containment values are pulled directly from incident reporting systems and appear automatically once entered into the source data.

## Commands

### Show recent active Arizona wildfires

```text
!wildfire
```

Returns the most recently discovered active Arizona wildfires.

### Search by fire name

```text
!wildfire telegraph
```

Returns active incidents matching the specified fire name.

### Search by county

```text
!wildfire gila
```

Returns active incidents within the specified county.

## Included Scripts

### `nifc_timer.py`

Scheduled polling script that:

* Monitors active wildfire incidents
* Tracks NEW, UPDATE, and OUT events
* Broadcasts wildfire alerts
* Creates, updates, and removes waypoints
* Maintains state to prevent duplicate notifications

### `nifc_responder.py`

On-demand responder that answers wildfire queries from Meshtastic users.

### `common.py`

Shared utility library used by MeshMonitor scripts.

## Requirements

* Meshtastic
* Mesh Commander / MeshMonitor compatible environment
* Internet connectivity
* Access to the NIFC WFIGS incident feed

## Disclaimer

Wildfire information is sourced from official incident reporting systems but may be delayed by reporting, dispatch, or synchronization intervals. Always follow instructions and evacuation orders issued by local fire agencies and emergency management officials.
