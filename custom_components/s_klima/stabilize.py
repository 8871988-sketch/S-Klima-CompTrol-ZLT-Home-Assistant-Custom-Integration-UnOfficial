"""Smooth out short glitches of the CompTrol ZLT.

The device sometimes returns "no data" markers for a unit for one poll, or
flips status flags (filter alarm, fault, online) for a few seconds on all
units at once. This module keeps the last good values and accepts a changed
status flag only after it was seen in several polls in a row.

No Home Assistant dependencies, so it can be tested alone.
"""

from __future__ import annotations

from dataclasses import fields, replace
import logging

from .api import CompTrolState, IndoorUnit

_LOGGER = logging.getLogger(__name__)

# Polls in a row a changed flag must be seen before it is accepted.
# With the default 30 s poll interval: filter 5 min, fault/online 1.5 min.
CONFIRM_POLLS: dict[str, int] = {
    "filter_alarm": 10,
    "is_error": 3,
    "is_online": 3,
}
# Default for a flag that never had a valid value.
_FLAG_DEFAULTS: dict[str, bool] = {
    "filter_alarm": False,
    "is_error": False,
    "is_online": False,
}
# Polls in a row a unit may deliver "no data" before its old values are dropped.
MAX_STALE_POLLS = 10
# Fields that are never taken over from an older poll.
_NO_FILL = {"unit_id", "name", "data_valid", "raw", *CONFIRM_POLLS}


class StateStabilizer:
    """Turn raw polls into a stable state."""

    def __init__(self, confirm: dict[str, int] | None = None) -> None:
        """Initialize."""
        self._confirm = confirm or CONFIRM_POLLS
        self._prev: CompTrolState | None = None
        # unit id -> flag -> (candidate value, polls seen)
        self._pending: dict[int, dict[str, tuple[bool, int]]] = {}
        self._stale: dict[int, int] = {}

    def apply(self, new: CompTrolState) -> CompTrolState:
        """Merge a new poll with the previous state."""
        prev = self._prev
        units: dict[int, IndoorUnit] = {}
        for unit_id, unit in new.units.items():
            old = prev.units.get(unit_id) if prev else None
            units[unit_id] = self._unit(unit, old)
        outside = new.outside_temperature
        if outside is None and prev is not None:
            outside = prev.outside_temperature
        state = CompTrolState(outside_temperature=outside, units=units)
        self._prev = state
        return state

    def _unit(self, unit: IndoorUnit, old: IndoorUnit | None) -> IndoorUnit:
        unit_id = unit.unit_id
        if not unit.data_valid and old is not None:
            stale = self._stale.get(unit_id, 0) + 1
            self._stale[unit_id] = stale
            if stale <= MAX_STALE_POLLS:
                _LOGGER.debug(
                    "Unit %s returned no data (%s), keeping previous values (%d/%d)",
                    unit.address, unit.raw, stale, MAX_STALE_POLLS,
                )
                return replace(old, raw=unit.raw)
            _LOGGER.debug("Unit %s returned no data for %d polls", unit.address, stale)
        else:
            self._stale.pop(unit_id, None)

        # Missing single values: keep the last known value.
        if old is not None:
            changes = {
                f.name: getattr(old, f.name)
                for f in fields(IndoorUnit)
                if f.name not in _NO_FILL
                and getattr(unit, f.name) is None
                and getattr(old, f.name) is not None
            }
            if changes:
                unit = replace(unit, **changes)

        flags = {name: self._flag(unit, old, name) for name in self._confirm}
        return replace(unit, **flags)

    def _flag(self, unit: IndoorUnit, old: IndoorUnit | None, name: str) -> bool:
        candidate: bool | None = getattr(unit, name)
        pending = self._pending.setdefault(unit.unit_id, {})
        if old is None:
            # First poll: take what the device says.
            pending.pop(name, None)
            return _FLAG_DEFAULTS[name] if candidate is None else candidate
        stable = bool(getattr(old, name))
        if candidate is None or candidate == stable:
            if name in pending:
                _LOGGER.debug(
                    "Unit %s: %s back to %s after %d poll(s), ignored (raw %s)",
                    unit.address, name, stable, pending[name][1], unit.raw,
                )
            pending.pop(name, None)
            return stable
        seen = pending[name][1] + 1 if name in pending and pending[name][0] == candidate else 1
        need = self._confirm[name]
        if seen >= need:
            pending.pop(name, None)
            _LOGGER.debug(
                "Unit %s: %s changed to %s (confirmed after %d polls, raw %s)",
                unit.address, name, candidate, seen, unit.raw,
            )
            return candidate
        pending[name] = (candidate, seen)
        _LOGGER.debug(
            "Unit %s: %s reports %s (%d/%d, raw %s)",
            unit.address, name, candidate, seen, need, unit.raw,
        )
        return stable
