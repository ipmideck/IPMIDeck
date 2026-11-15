"""Tombstone: the in-process async EventBus was removed.

It had 4 emit() sites and ZERO subscribers — no ModuleManifest ever declared
event_handlers. Every plausible subscriber already had a cleaner inline path
(temperature_critical was wired directly to broadcast_alert; power_state_changed
and sensor_reading were handled inline by command_log + broadcast_sensor_update;
fan_speed_changed had no target), so reviving the bus would have added
indirection with no subscriber to serve.

This module is intentionally left as a tombstone so that any stale import of
backend.core.events surfaces loudly instead of silently importing a dead bus.
"""

from __future__ import annotations
