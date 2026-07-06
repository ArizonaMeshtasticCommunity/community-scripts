# Meshtastic Traffic Alerts

A set of Mesh Commander / MeshMonitor scripts that pull traffic events from the Arizona ADOT 511 API and broadcast traffic alerts and waypoints over Meshtastic.

This project was inspired by Ted Malone's ADOT 511 project (https://github.com/temalo/ADOT-511), which explored bringing Arizona traffic data onto the mesh. His work helped spark the idea for this implementation and influenced some of the early command-handling concepts.

The goal is simple: provide useful traffic information to the mesh without turning a traffic feed into constant channel noise.

## Included Scripts

### `traffic_timer.py`

Runs on a schedule and polls the ADOT 511 Events API.

When a new or updated incident is detected, it broadcasts:

- A traffic alert message
- A Meshtastic waypoint

The timer focuses on higher-impact event types such as accidents and closures and tracks previously seen incidents to avoid repeated broadcasts.

### `traffic_responder.py`

Provides on-demand traffic lookups from the mesh.

Examples:

```text
!traffic
!traffic 10
!traffic 60
!traffic 101
!traffic 202
!traffic i17
```

### `common.py`

Shared utility library used by all scripts.

Provides:

- HTTP helpers
- State management
- Caching
- Message formatting
- Deduplication helpers
- Utility functions

## Query Modes

The responder supports two different modes.

### Metro Traffic Digest

```text
!traffic
```

Returns a summary of active freeway incidents in the Metro Phoenix coverage zones.

Only the highest-priority incidents are returned, keeping responses short enough for mesh use.

### Roadway Lookup

```text
!traffic 10
!traffic 60
!traffic 101
!traffic 202
!traffic i17
```

Searches all configured coverage zones for incidents matching the requested roadway.

Roadway lookups include additional event types such as:

- Closures
- Hazards
- Roadwork
- Accidents and incidents

Responses are limited to a small number of results to reduce airtime usage.

## Incident Classification

ADOT's `EventType` field is fairly broad and often groups many different incidents together.

To provide more useful alerts, the scripts apply keyword matching against the ADOT `EventSubType` and `Description` fields.

Current classifications include:

- 🪨 Debris
- 🌫️ Dust / Haboob
- 🌊 Flooding
- 🔥 Fire
- 💥 Collision
- 💥 Rollover
- ⛔ Wrong Way Driver
- 🚶 Pedestrian
- 🐄 Animal
- 🚗 Disabled Vehicle
- 🚓 Police Activity
- ☣️ Hazmat
- ⛔ Closure
- 🚧 Roadwork
- 🕳️ Pothole

If no classification rule matches, the script falls back to the event information provided by ADOT.

## Coverage Areas

The default configuration includes coverage zones for:

- East Valley
- Central Valley
- West Valley
- I-17 Corridor
- SR-87 Corridor
- US-60 Corridor
- Casa Grande Area
- Tucson Corridor
- I-10 West Corridor

Coverage zones are defined in `traffic_timer.py` and can be adjusted as needed.

## Deduplication

Traffic incidents are fingerprinted using:

- Event ID
- Event Description

This prevents the same incident from being repeatedly broadcast while still allowing updates to be sent when ADOT changes an event's details.

## Waypoints

Scheduled traffic broadcasts include Meshtastic waypoints.

Waypoint IDs are derived from the ADOT event ID, allowing updates to refresh an existing waypoint instead of creating duplicate pins.

## Requirements

- Python 3.11+
- Mesh Commander or MeshMonitor
- ADOT 511 Developer API Key

Environment variable:

```text
ADOT_API_KEY=your_api_key_here
```

## Installation

Place the scripts in your Mesh Commander scripts directory:

```text
common.py
traffic_timer.py
traffic_responder.py
```

Configure:

- `traffic_timer.py` as a scheduled automation
- `traffic_responder.py` as a responder automation

Example keyword configuration:

```text
!traffic
!traffic ([\w-]+)
```

## Design Goals

These scripts were written specifically for mesh networks where airtime matters.

To reduce unnecessary congestion:

- Messages are kept short
- Scheduled broadcasts are capped
- Duplicate alerts are suppressed
- On-demand responses are limited
- Multiple incidents are split into separate messages

The intent is to provide useful situational awareness while keeping mesh traffic manageable.
