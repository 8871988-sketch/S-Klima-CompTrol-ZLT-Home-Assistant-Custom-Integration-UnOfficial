"""Async client for the S-Klima / STULZ CompTrol ZLT web interface.

The CompTrol ZLT web UI talks to the device through a single endpoint,
"POST /web.dwh" ("DigiWEB"). The request body is plain text::

    mg=<session>&V=<url-encoded expression>&V=<expression>&<url-encoded G=list>

* "V=" entries are single expressions. "##Name" returns a number,
  "#$Name" returns a string, "##Name:=value" writes a value.
* "G=" entries are list expressions: "G=<count expr>\\t<expr>\\t<expr>..."
  where "##X" is the running index of the list.

The response is CRLF separated::

    <user level>\\r\\n<value 1>\\r\\n...<value n>\\r\\n<error code>\\r\\n

This module has no Home Assistant dependencies so it can be tested alone.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import re
from typing import Any
from urllib.parse import quote

import aiohttp

_LOGGER = logging.getLogger(__name__)

_ERR_VALUE = re.compile(r"^ERR-\d+$")
# Marker values the device returns while it has no valid data for a field
# (seen for whole units for one poll, e.g. room temperature -2147483648).
INVALID_VALUES = frozenset({-2147483648, 2147483647})
# If one of these fields carries an invalid marker, the whole row is not usable.
_CORE_FIELDS = ("Mode", "SetTemperature", "RoomTemperature")
# Raw values of these fields are kept for diagnostics.
_RAW_FIELDS = ("FilterStatus", "IsOnline", "IsError", "ErrorCode")
# Error code the device returns when the session number is unknown or expired.
_SESSION_ERRORS = {"-104"}
# Bit that marks an active (logged-in) user in ##USERLEVELS().
_LEVEL_ACTIVE = 2

# Numeric fields read for every indoor unit (order matters for parsing).
UNIT_NUMERIC_FIELDS: tuple[str, ...] = (
    "Id",
    "Running",
    "Mode",
    "FanSpeed",
    "Louver",
    "SetTemperature",
    "RoomTemperature",
    "MinSetTemp",
    "MaxSetTemp",
    "ErrorCode",
    "IsError",
    "IsOnline",
    "FilterStatus",
    "AutoModeSupported",
    "AutoFanSupported",
    "FanSpeed4Supported",
    "LouverSupported",
    "FanSpeedMax",
    "CurrentPower",
    "MeterReading",
    "IsRunningLocked",
    "IsModeLocked",
    "IsFanSpeedLocked",
    "IsSetPointLocked",
    "IsLouverPositionLocked",
)
# Fields that may be written through "async_write_unit".
WRITABLE_FIELDS = frozenset({"Running", "Mode", "FanSpeed", "Louver", "SetTemperature"})

_LIST_ITEM = "IndoorUnits.Unit[##IndoorUnits.GetItemId[##X+0]]"


class CompTrolError(Exception):
    """Base error."""


class CompTrolConnectionError(CompTrolError):
    """Device not reachable or returned an HTTP error."""


class CompTrolAuthError(CompTrolError):
    """Login failed or session could not be established."""


class CompTrolUnsupportedError(CompTrolError):
    """Device uses a feature this client does not implement (RSA encryption)."""


class CompTrolProtocolError(CompTrolError):
    """Unexpected response from the device."""


def encode_component(value: str) -> str:
    """Encode like JavaScript's encodeURIComponent (as the web UI does)."""
    return quote(value, safe="-_.!~*'()")


def build_body(mg: int, expressions: list[str]) -> str:
    """Build the text/plain request body for web.dwh."""
    parts = [f"mg={mg}"]
    for expr in expressions:
        if expr.startswith("G="):
            parts.append(encode_component(expr))
        else:
            parts.append("V=" + encode_component(expr))
    return "&".join(parts)


@dataclass
class DwhResult:
    """Parsed web.dwh response."""

    header: str
    data: list[str]
    error: str


def parse_response(text: str) -> DwhResult:
    """Parse a web.dwh response (same logic as the web UI)."""
    lines = text.split("\r\n")
    if len(lines) < 3:
        raise CompTrolProtocolError(f"Unexpected response: {text[:100]!r}")
    error = lines[-2] or "0"
    return DwhResult(header=lines[0], data=lines[1:-2], error=error)


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _to_int(value: str | None) -> int | None:
    if value is None or _ERR_VALUE.match(value):
        return None
    try:
        return int(value)
    except ValueError:
        try:
            return int(float(value))
        except ValueError:
            return None


def _tenth(value: int | None) -> float | None:
    return None if value is None else value / 10


def format_address(unit_id: int) -> str:
    """Return the address as shown in the web UI (1000 -> '1-0')."""
    return f"{unit_id // 1000}-{unit_id % 1000}"


@dataclass
class IndoorUnit:
    """State of one indoor unit."""

    unit_id: int
    name: str
    running: bool | None = None
    mode: int | None = None
    fan_speed: int | None = None
    louver: int | None = None
    set_temperature: float | None = None
    room_temperature: float | None = None
    min_set_temp: float | None = None
    max_set_temp: float | None = None
    error_code: int | None = None
    # None = the device did not deliver a valid value in this poll.
    is_error: bool | None = False
    is_online: bool | None = False
    filter_alarm: bool | None = False
    auto_mode_supported: bool = False
    auto_fan_supported: bool = False
    fan_speed4_supported: bool = False
    louver_supported: bool = False
    fan_speed_max: int | None = None
    current_power: int | None = None
    meter_reading: int | None = None
    running_locked: bool = False
    mode_locked: bool = False
    fan_speed_locked: bool = False
    setpoint_locked: bool = False
    louver_locked: bool = False
    # False when the device returned "no data" markers for this unit.
    data_valid: bool = True
    raw: dict[str, int | None] = field(default_factory=dict, compare=False, repr=False)

    @property
    def address(self) -> str:
        """Bus address as shown in the web UI."""
        return format_address(self.unit_id)

    @classmethod
    def from_values(cls, values: dict[str, int | None], name: str) -> IndoorUnit:
        """Create from the raw numeric field values."""
        unit_id = values["Id"]
        if unit_id is None:
            raise CompTrolProtocolError("Indoor unit without id")

        def flag(key: str) -> bool:
            return bool(values.get(key))

        def opt_flag(key: str) -> bool | None:
            value = values.get(key)
            return None if value is None else bool(value)

        running = values.get("Running")
        return cls(
            unit_id=unit_id,
            name=name or f"Innengerät {format_address(unit_id)}",
            running=None if running is None else bool(running),
            mode=values.get("Mode"),
            fan_speed=values.get("FanSpeed"),
            louver=values.get("Louver"),
            set_temperature=_tenth(values.get("SetTemperature")),
            room_temperature=_tenth(values.get("RoomTemperature")),
            min_set_temp=_tenth(values.get("MinSetTemp")),
            max_set_temp=_tenth(values.get("MaxSetTemp")),
            error_code=values.get("ErrorCode"),
            is_error=opt_flag("IsError"),
            is_online=opt_flag("IsOnline"),
            filter_alarm=opt_flag("FilterStatus"),
            auto_mode_supported=flag("AutoModeSupported"),
            auto_fan_supported=flag("AutoFanSupported"),
            fan_speed4_supported=flag("FanSpeed4Supported"),
            louver_supported=flag("LouverSupported"),
            fan_speed_max=values.get("FanSpeedMax"),
            current_power=values.get("CurrentPower"),
            meter_reading=values.get("MeterReading"),
            running_locked=flag("IsRunningLocked"),
            mode_locked=flag("IsModeLocked"),
            fan_speed_locked=flag("IsFanSpeedLocked"),
            setpoint_locked=flag("IsSetPointLocked"),
            louver_locked=flag("IsLouverPositionLocked"),
        )


@dataclass
class CompTrolState:
    """Snapshot of the whole system."""

    outside_temperature: float | None
    units: dict[int, IndoorUnit] = field(default_factory=dict)


def units_list_expression() -> str:
    """List expression that reads all indoor units in one request."""
    exprs = [f"##{_LIST_ITEM}.{name}" for name in UNIT_NUMERIC_FIELDS]
    exprs.append("#$" + _LIST_ITEM + ".Name")
    return "G=##IndoorUnits.Count\t" + "\t".join(exprs)


def parse_state(data: list[str]) -> CompTrolState:
    """Parse the values of "##Outside.Temperature" + "units_list_expression()"."""
    if len(data) < 2:
        raise CompTrolProtocolError("Response too short")
    outside_raw = _to_int(data[0])
    outside = None if outside_raw in INVALID_VALUES else _tenth(outside_raw)
    count = _to_int(data[1]) or 0
    width = len(UNIT_NUMERIC_FIELDS) + 1
    rows = data[2:]
    if len(rows) < count * width:
        raise CompTrolProtocolError(
            f"Expected {count * width} values for {count} units, got {len(rows)}"
        )
    units: dict[int, IndoorUnit] = {}
    for index in range(count):
        row = rows[index * width : (index + 1) * width]
        raw = {name: _to_int(row[pos]) for pos, name in enumerate(UNIT_NUMERIC_FIELDS)}
        if raw["Id"] is None or raw["Id"] in INVALID_VALUES:
            continue
        data_valid = not any(raw[name] in INVALID_VALUES for name in _CORE_FIELDS)
        values = {
            name: None if value in INVALID_VALUES else value
            for name, value in raw.items()
        }
        if not data_valid:
            # Status values of an invalid row are not trustworthy either.
            for name in ("IsError", "IsOnline", "FilterStatus", "ErrorCode"):
                values[name] = None
        unit = IndoorUnit.from_values(values, row[-1].strip())
        unit.data_valid = data_valid
        unit.raw = {name: raw[name] for name in _RAW_FIELDS}
        units[unit.unit_id] = unit
    return CompTrolState(outside_temperature=outside, units=units)


class CompTrolClient:
    """Client for one CompTrol ZLT."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        timeout: float = 15,
    ) -> None:
        """Initialize."""
        host = host.strip().rstrip("/")
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        self._url = f"{host}/web.dwh"
        self._session = session
        self._username = username
        self._password = password
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._mg = 0
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        """Web interface URL."""
        return self._url.rsplit("/", 1)[0] + "/"

    async def _post(self, mg: int, expressions: list[str]) -> DwhResult:
        body = build_body(mg, expressions)
        try:
            async with self._session.post(
                self._url,
                data=body.encode("utf-8"),
                headers={"Content-Type": "text/plain; charset=utf-8"},
                timeout=self._timeout,
            ) as resp:
                if resp.status != 200:
                    raise CompTrolConnectionError(f"HTTP status {resp.status}")
                raw = await resp.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CompTrolConnectionError(
                f"Error talking to {self._url}: {err!r}"
            ) from err
        return parse_response(_decode(raw))

    async def _login_locked(self) -> None:
        self._mg = 0
        rsa = await self._post(0, ["#$GETRSA()"])
        key = rsa.data[0] if rsa.data else ""
        if key and key != "0":
            raise CompTrolUnsupportedError(
                "The CompTrol ZLT uses RSA-encrypted requests, which this "
                "integration does not support yet"
            )
        result = await self._post(
            0, [f"##LOGIN('{self._username}', '{self._password}')"]
        )
        mg = _to_int(result.data[0]) if result.data else None
        if not mg:
            raise CompTrolAuthError("Login rejected (wrong user name or password)")
        levels = await self._post(mg, ["##USERLEVELS()"])
        level = _to_int(levels.data[0]) if levels.data else None
        if not level or level & _LEVEL_ACTIVE != _LEVEL_ACTIVE:
            raise CompTrolAuthError("User is not active on the CompTrol ZLT")
        self._mg = mg
        _LOGGER.debug("Logged in to %s", self._url)

    @staticmethod
    def _session_valid(result: DwhResult) -> bool:
        if result.error in _SESSION_ERRORS or not result.data:
            return False
        level = _to_int(result.data[0])
        return bool(level) and level & _LEVEL_ACTIVE == _LEVEL_ACTIVE

    async def async_query(self, expressions: list[str]) -> list[str]:
        """Run expressions with a valid session, re-login if needed."""
        async with self._lock:
            if not self._mg:
                await self._login_locked()
            request = ["##USERLEVELS()", *expressions]
            result = await self._post(self._mg, request)
            if not self._session_valid(result):
                _LOGGER.debug("Session expired, logging in again")
                await self._login_locked()
                result = await self._post(self._mg, request)
                if not self._session_valid(result):
                    raise CompTrolAuthError("Session not accepted after login")
            if result.error != "0":
                raise CompTrolProtocolError(f"Device returned error {result.error}")
            return result.data[1:]

    async def async_login(self) -> None:
        """Log in (normally done automatically)."""
        async with self._lock:
            await self._login_locked()

    async def async_logout(self) -> None:
        """Close the session on the device (best effort)."""
        async with self._lock:
            if not self._mg:
                return
            mg, self._mg = self._mg, 0
            try:
                await self._post(mg, [f"##LOGOUT({mg})"])
            except CompTrolError as err:
                _LOGGER.debug("Logout failed: %s", err)

    async def async_get_state(self) -> CompTrolState:
        """Read outside temperature and all indoor units."""
        return parse_state(
            await self.async_query(["##Outside.Temperature", units_list_expression()])
        )

    async def async_write_unit(self, unit_id: int, values: dict[str, Any]) -> list[str]:
        """Write raw values to an indoor unit, in the given order.

        Example: "{"Mode": 2, "Running": 1}" or "{"SetTemperature": 225}"
        (temperatures in tenths of a degree).
        """
        expressions = []
        for name, value in values.items():
            if name not in WRITABLE_FIELDS:
                raise ValueError(f"Field {name} is not writable")
            expressions.append(f"##IndoorUnits.Unit[{int(unit_id)}].{name}:={int(value)}")
        if not expressions:
            return []
        return await self.async_query(expressions)
