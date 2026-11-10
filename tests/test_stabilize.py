"""Tests for the glitch filter."""

from __future__ import annotations

from custom_components.s_klima.api import parse_state, units_list_expression, UNIT_NUMERIC_FIELDS
from custom_components.s_klima.stabilize import StateStabilizer

INVALID = "-2147483648"


def _row(uid: int, **over: str) -> list[str]:
    base = {
        "Id": str(uid), "Running": "0", "Mode": "4", "FanSpeed": "1", "Louver": "3",
        "SetTemperature": "250", "RoomTemperature": "215", "MinSetTemp": "160",
        "MaxSetTemp": "300", "ErrorCode": "0", "IsError": "0", "IsOnline": "1",
        "FilterStatus": "0",
    }
    base.update(over)
    return [base.get(name, "0") for name in UNIT_NUMERIC_FIELDS] + [f"Unit {uid}"]


def _poll(*rows: list[str]):
    data = ["89", str(len(rows))]
    for row in rows:
        data.extend(row)
    return parse_state(data)


def test_invalid_row_keeps_previous_values() -> None:
    """A poll with 'no data' markers (seen on the real device) changes nothing."""
    stab = StateStabilizer()
    first = stab.apply(_poll(_row(1000)))
    assert first.units[1000].room_temperature == 21.5
    glitch = _poll(_row(1000, Mode=INVALID, SetTemperature=INVALID,
                        RoomTemperature=INVALID, ErrorCode="255", FilterStatus="1"))
    assert glitch.units[1000].data_valid is False
    state = stab.apply(glitch)
    unit = state.units[1000]
    assert unit.room_temperature == 21.5
    assert unit.set_temperature == 25.0
    assert unit.error_code == 0
    assert unit.filter_alarm is False
    assert unit.is_online is True


def test_flag_needs_confirmation() -> None:
    """A changed flag is accepted only after N polls in a row."""
    stab = StateStabilizer({"filter_alarm": 3, "is_error": 2, "is_online": 2})
    stab.apply(_poll(_row(1000)))
    assert stab.apply(_poll(_row(1000, FilterStatus="1"))).units[1000].filter_alarm is False
    assert stab.apply(_poll(_row(1000))).units[1000].filter_alarm is False
    for expected in (False, False, True):
        assert stab.apply(_poll(_row(1000, FilterStatus="1"))).units[1000].filter_alarm is expected
    assert stab.apply(_poll(_row(1000))).units[1000].filter_alarm is True
    assert stab.apply(_poll(_row(1000))).units[1000].filter_alarm is True
    assert stab.apply(_poll(_row(1000))).units[1000].filter_alarm is False


def test_single_invalid_field_is_filled() -> None:
    """One invalid value in an otherwise valid row keeps the old value."""
    stab = StateStabilizer()
    stab.apply(_poll(_row(1000, FilterStatus="0")))
    state = stab.apply(_poll(_row(1000, FilterStatus=INVALID)))
    assert state.units[1000].data_valid is True
    assert state.units[1000].filter_alarm is False


def test_list_expression_unchanged() -> None:
    assert units_list_expression().startswith("G=##IndoorUnits.Count\t")
