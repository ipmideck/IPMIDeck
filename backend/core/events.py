"""Tombstone: EventBus was removed in Phase 04 (W6-01).

The in-process async EventBus had 4 emit() sites and ZERO subscribers — no
ModuleManifest ever declared event_handlers. Every plausible subscriber had a
cleaner inline path (temperature_critical was wired directly to broadcast_alert
in the alerting wave; power_state_changed and sensor_reading were already handled
inline by command_log + broadcast_sensor_update; fan_speed_changed had no target).

See .planning/phases/04-energy-management-safety-completion-alerting-hardening-and-mobile-redesign/04-RESEARCH.md
Open Question #3 for the full revive-vs-remove rationale (recommendation: REMOVE).

This module is intentionally left as a tombstone so that any stale import of
backend.core.events surfaces loudly instead of silently importing a dead bus.
"""

from __future__ import annotations
