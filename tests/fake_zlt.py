"""Emulates the web.dwh endpoint of a CompTrol ZLT.

Behaviour copied from the real device (firmware 5.003-074):
* response = "<level>\\r\\n<values...>\\r\\n<error>\\r\\n"
* unknown session -> level 0, ##USERLEVELS() = 0, other values "§§§", error -104
* #$GETRSA() returns "" when encryption is off
"""

from __future__ import annotations

import random
import re
from urllib.parse import unquote

FIELDS = {
    "Id": None,
    "Running": 1,
    "Mode": 4,
    "FanSpeed": 1,
    "Louver": 3,
    "SetTemperature": 250,
    "RoomTemperature": 207,
    "MinSetTemp": 160,
    "MaxSetTemp": 300,
    "ErrorCode": 0,
    "IsError": 0,
    "IsOnline": 1,
    "FilterStatus": 0,
    "AutoModeSupported": 1,
    "AutoFanSupported": 1,
    "FanSpeed4Supported": 1,
    "LouverSupported": 1,
    "FanSpeedMax": 4,
    "CurrentPower": 0,
    "MeterReading": 0,
    "IsRunningLocked": 0,
    "IsModeLocked": 0,
    "IsFanSpeedLocked": 0,
    "IsSetPointLocked": 0,
    "IsLouverPositionLocked": 0,
}

NAMES = ["Restaurant Right", "Restaurant Left", "Meeting Right", "Meeting Left", "Relax Area"]


class FakeZLT:
    """Stateful fake device."""

    def __init__(self, units: int = 3, user: str = "ha", password: str = "secret") -> None:
        self.user = user
        self.password = password
        self.rsa_key = ""
        self.sessions: set[int] = set()
        self.outside = 89
        self.units: dict[int, dict] = {}
        for i in range(units):
            uid = 1000 + i
            data = dict(FIELDS)
            data["Id"] = uid
            data["Name"] = NAMES[i % len(NAMES)]
            self.units[uid] = data
        self.requests: list[list[str]] = []
        self.writes: list[str] = []
        self.logins = 0
        self.logouts = 0
        self.fail_http = False
        self.fail_count = 0

    def expire_sessions(self) -> None:
        self.sessions.clear()

    # -- request handling -------------------------------------------------

    def handle(self, body: str) -> str:
        parts = body.split("&")
        assert parts[0].startswith("mg="), body
        mg = int(parts[0][3:])
        exprs: list[str] = []
        for part in parts[1:]:
            if part.startswith("V="):
                exprs.append(unquote(part[2:]))
            else:
                decoded = unquote(part)
                assert decoded.startswith("G="), decoded
                exprs.append(decoded)
        self.requests.append(exprs)
        valid = mg in self.sessions
        out: list[str] = []
        error = "0"
        for expr in exprs:
            if expr == "#$GETRSA()":
                out.append(self.rsa_key)
                continue
            if m := re.fullmatch(r"##LOGIN\('(.*)', '(.*)'\)", expr):
                if (m.group(1), m.group(2)) == (self.user, self.password):
                    new = random.randint(-2_000_000_000, 2_000_000_000) or 1
                    self.sessions.add(new)
                    self.logins += 1
                    out.append(str(new))
                else:
                    out.append("0")
                continue
            if expr == "##USERLEVELS()":
                out.append("254" if valid else "0")
                continue
            if not valid:
                out.append("§§§")
                error = "-104"
                continue
            if m := re.fullmatch(r"##LOGOUT\((-?\d+)\)", expr):
                self.sessions.discard(int(m.group(1)))
                self.logouts += 1
                out.append("1")
                continue
            if expr == "##Outside.Temperature":
                out.append(str(self.outside))
                continue
            if expr.startswith("G="):
                out.extend(self._list(expr[2:]))
                continue
            if m := re.fullmatch(r"##IndoorUnits\.Unit\[(\d+)\]\.(\w+):=(-?\d+)", expr):
                uid, name, value = int(m.group(1)), m.group(2), int(m.group(3))
                self.units[uid][name] = value
                self.writes.append(expr)
                out.append(str(value))
                continue
            out.append("ERR-1")
        header = "254" if valid else "0"
        return "\r\n".join([header, *out, error, ""])

    def _list(self, spec: str) -> list[str]:
        count_expr, *items = spec.split("\t")
        assert count_expr == "##IndoorUnits.Count"
        ids = list(self.units)
        out = [str(len(ids))]
        for uid in ids:
            for item in items:
                m = re.fullmatch(
                    r"(##|#\$)IndoorUnits\.Unit\[##IndoorUnits\.GetItemId\[##X\+0\]\]\.(\w+)",
                    item,
                )
                assert m, item
                out.append(str(self.units[uid].get(m.group(2), "ERR-2")))
        return out
