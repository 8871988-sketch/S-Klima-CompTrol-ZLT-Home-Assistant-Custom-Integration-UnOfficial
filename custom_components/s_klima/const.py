"""Constants for the S-Klima CompTrol ZLT integration."""

from __future__ import annotations

DOMAIN = "s_klima"

CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 30  # seconds
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 600

MANUFACTURER = "STULZ / S-Klima"

# Operating modes as used by the CompTrol ZLT (enum "NS" in the web UI)
MODE_AUTO = 0
MODE_DRY = 1  # "Entfeuchten"
MODE_COOL = 2
MODE_FAN = 3  # "Lüften"
MODE_HEAT = 4

# Fan speed: 0 = automatic, 1..4 = level
FAN_SPEED_AUTO = 0

# Louver: 0..3 = position 1..4, 10 = swinging
LOUVER_SWING = 10
