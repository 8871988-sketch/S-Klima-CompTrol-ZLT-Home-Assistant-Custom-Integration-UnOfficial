"""Climate entities for the indoor units of a CompTrol ZLT."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    FAN_AUTO,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_TENTHS, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    FAN_SPEED_AUTO,
    LOUVER_SWING,
    MODE_AUTO,
    MODE_COOL,
    MODE_DRY,
    MODE_FAN,
    MODE_HEAT,
)
from .coordinator import SKlimaCoordinator
from .entity import SKlimaUnitEntity

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SKlimaConfigEntry

PARALLEL_UPDATES = 1

# HA 2026.x moved climate temperatures to native_* properties; keep older versions working.
_NATIVE = hasattr(ClimateEntity, "native_temperature_unit")

MODE_TO_HVAC: dict[int, HVACMode] = {
    MODE_AUTO: HVACMode.HEAT_COOL,
    MODE_DRY: HVACMode.DRY,
    MODE_COOL: HVACMode.COOL,
    MODE_FAN: HVACMode.FAN_ONLY,
    MODE_HEAT: HVACMode.HEAT,
}
HVAC_TO_MODE: dict[HVACMode, int] = {v: k for k, v in MODE_TO_HVAC.items()}

FAN_LEVELS = ("1", "2", "3", "4")
SWING_POSITIONS = ("position_1", "position_2", "position_3", "position_4")
SWING_ON = "swing"

DEFAULT_MIN_TEMP = 16.0
DEFAULT_MAX_TEMP = 30.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SKlimaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one climate entity per indoor unit."""
    coordinator = entry.runtime_data
    async_add_entities(
        SKlimaClimate(coordinator, unit_id) for unit_id in coordinator.data.units
    )


class SKlimaClimate(SKlimaUnitEntity, ClimateEntity):
    """An indoor unit."""

    _attr_name = None
    _attr_translation_key = "indoor_unit"
    if _NATIVE:
        _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    else:
        _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_TENTHS
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator: SKlimaCoordinator, unit_id: int) -> None:
        """Initialize."""
        super().__init__(coordinator, unit_id, None)

    # --- state -----------------------------------------------------------

    @property
    def available(self) -> bool:
        """Unit must also be online on the bus."""
        unit = self.unit
        return super().available and unit is not None and unit.is_online

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Features depend on the unit."""
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.FAN_MODE
        )
        unit = self.unit
        if unit is not None and unit.louver_supported:
            features |= ClimateEntityFeature.SWING_MODE
        return features

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Supported modes."""
        modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.DRY, HVACMode.FAN_ONLY]
        unit = self.unit
        if unit is not None and unit.auto_mode_supported:
            modes.insert(1, HVACMode.HEAT_COOL)
        return modes

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Current mode."""
        unit = self.unit
        if unit is None or unit.running is None:
            return None
        if not unit.running:
            return HVACMode.OFF
        return MODE_TO_HVAC.get(unit.mode) if unit.mode is not None else None

    @property
    def _room_temperature(self) -> float | None:
        """Room temperature."""
        return self.unit.room_temperature if self.unit else None

    @property
    def _set_temperature(self) -> float | None:
        """Set point."""
        return self.unit.set_temperature if self.unit else None

    if _NATIVE:
        native_current_temperature = _room_temperature
        native_target_temperature = _set_temperature
    else:
        current_temperature = _room_temperature
        target_temperature = _set_temperature

    @property
    def min_temp(self) -> float:
        """Lowest set point."""
        unit = self.unit
        if unit and unit.min_set_temp:
            return unit.min_set_temp
        return DEFAULT_MIN_TEMP

    @property
    def max_temp(self) -> float:
        """Highest set point."""
        unit = self.unit
        if unit and unit.max_set_temp:
            return unit.max_set_temp
        return DEFAULT_MAX_TEMP

    @property
    def fan_modes(self) -> list[str]:
        """Fan levels the unit supports (same logic as the web UI)."""
        unit = self.unit
        modes: list[str] = []
        if unit is None or unit.auto_fan_supported:
            modes.append(FAN_AUTO)
        four = unit is not None and (
            unit.fan_speed4_supported or (unit.fan_speed_max or 0) >= 4
        )
        modes.extend(FAN_LEVELS if four else FAN_LEVELS[:3])
        return modes

    @property
    def fan_mode(self) -> str | None:
        """Current fan level."""
        unit = self.unit
        if unit is None or unit.fan_speed is None:
            return None
        if unit.fan_speed == FAN_SPEED_AUTO:
            return FAN_AUTO
        if 1 <= unit.fan_speed <= len(FAN_LEVELS):
            return FAN_LEVELS[unit.fan_speed - 1]
        return None

    @property
    def swing_modes(self) -> list[str] | None:
        """Louver positions."""
        unit = self.unit
        if unit is None or not unit.louver_supported:
            return None
        return [*SWING_POSITIONS, SWING_ON]

    @property
    def swing_mode(self) -> str | None:
        """Current louver position."""
        unit = self.unit
        if unit is None or unit.louver is None:
            return None
        if unit.louver == LOUVER_SWING:
            return SWING_ON
        if 0 <= unit.louver < len(SWING_POSITIONS):
            return SWING_POSITIONS[unit.louver]
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Extra information from the CompTrol ZLT."""
        unit = self.unit
        if unit is None:
            return {}
        return {
            "address": unit.address,
            "error_code": unit.error_code,
            "filter_alarm": unit.filter_alarm,
            "locked_on_off": unit.running_locked,
            "locked_mode": unit.mode_locked,
            "locked_fan": unit.fan_speed_locked,
            "locked_setpoint": unit.setpoint_locked,
            "locked_louver": unit.louver_locked,
        }

    # --- commands --------------------------------------------------------

    def _require(self, locked: bool, what: str) -> None:
        if locked:
            raise HomeAssistantError(
                f"{what} of {self.unit.name if self.unit else self._unit_id} "
                "is locked on the CompTrol ZLT"
            )

    async def _write(self, values: dict[str, int], optimistic: dict[str, Any]) -> None:
        await self.coordinator.async_write_unit(self._unit_id, values, optimistic)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Change mode (OFF switches the unit off)."""
        unit = self.unit
        if unit is None:
            raise HomeAssistantError("Unit not available")
        if hvac_mode == HVACMode.OFF:
            self._require(unit.running_locked, "On/off")
            await self._write({"Running": 0}, {"running": False})
            return
        if hvac_mode not in HVAC_TO_MODE:
            raise HomeAssistantError(f"Unsupported mode {hvac_mode}")
        mode = HVAC_TO_MODE[hvac_mode]
        values: dict[str, int] = {}
        optimistic: dict[str, Any] = {}
        if unit.mode != mode:
            self._require(unit.mode_locked, "Mode")
            values["Mode"] = mode
            optimistic["mode"] = mode
        if not unit.running:
            self._require(unit.running_locked, "On/off")
            values["Running"] = 1
            optimistic["running"] = True
        if values:
            await self._write(values, optimistic)

    async def async_turn_on(self) -> None:
        """Switch on in the last used mode."""
        unit = self.unit
        if unit is None:
            raise HomeAssistantError("Unit not available")
        self._require(unit.running_locked, "On/off")
        await self._write({"Running": 1}, {"running": True})

    async def async_turn_off(self) -> None:
        """Switch off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Change the set point (and optionally the mode)."""
        unit = self.unit
        if unit is None:
            raise HomeAssistantError("Unit not available")
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self.async_set_hvac_mode(hvac_mode)
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        self._require(unit.setpoint_locked, "Set point")
        temperature = min(max(float(temperature), self.min_temp), self.max_temp)
        raw = int(round(temperature * 10))
        await self._write({"SetTemperature": raw}, {"set_temperature": raw / 10})

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Change fan level."""
        unit = self.unit
        if unit is None:
            raise HomeAssistantError("Unit not available")
        if fan_mode not in self.fan_modes:
            raise HomeAssistantError(f"Unsupported fan mode {fan_mode}")
        self._require(unit.fan_speed_locked, "Fan speed")
        value = FAN_SPEED_AUTO if fan_mode == FAN_AUTO else FAN_LEVELS.index(fan_mode) + 1
        await self._write({"FanSpeed": value}, {"fan_speed": value})

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Change louver position."""
        unit = self.unit
        if unit is None:
            raise HomeAssistantError("Unit not available")
        if swing_mode == SWING_ON:
            value = LOUVER_SWING
        elif swing_mode in SWING_POSITIONS:
            value = SWING_POSITIONS.index(swing_mode)
        else:
            raise HomeAssistantError(f"Unsupported swing mode {swing_mode}")
        self._require(unit.louver_locked, "Louver")
        await self._write({"Louver": value}, {"louver": value})
