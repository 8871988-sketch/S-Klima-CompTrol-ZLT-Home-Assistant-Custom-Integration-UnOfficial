"""Sensors for the S-Klima CompTrol ZLT integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant

from .api import IndoorUnit
from .coordinator import SKlimaCoordinator
from .entity import SKlimaHubEntity, SKlimaUnitEntity

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SKlimaConfigEntry

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SKlimaUnitSensorDescription(SensorEntityDescription):
    """Describes an indoor unit sensor."""

    value_fn: Callable[[IndoorUnit], float | int | None]


UNIT_SENSORS: tuple[SKlimaUnitSensorDescription, ...] = (
    SKlimaUnitSensorDescription(
        key="room_temperature",
        translation_key="room_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda unit: unit.room_temperature,
    ),
    SKlimaUnitSensorDescription(
        key="error_code",
        translation_key="error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda unit: unit.error_code,
    ),
    SKlimaUnitSensorDescription(
        key="current_power",
        translation_key="current_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_registry_enabled_default=False,
        value_fn=lambda unit: unit.current_power,
    ),
    SKlimaUnitSensorDescription(
        key="energy",
        translation_key="energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        entity_registry_enabled_default=False,
        value_fn=lambda unit: unit.meter_reading,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SKlimaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [SKlimaOutsideTemperature(coordinator)]
    entities.extend(
        SKlimaUnitSensor(coordinator, unit_id, description)
        for unit_id in coordinator.data.units
        for description in UNIT_SENSORS
    )
    async_add_entities(entities)


class SKlimaOutsideTemperature(SKlimaHubEntity, SensorEntity):
    """Outside temperature reported by the outdoor unit."""

    _attr_translation_key = "outside_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: SKlimaCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "outside_temperature")

    @property
    def native_value(self) -> float | None:
        """Temperature."""
        return self.coordinator.data.outside_temperature if self.coordinator.data else None


class SKlimaUnitSensor(SKlimaUnitEntity, SensorEntity):
    """Sensor of an indoor unit."""

    entity_description: SKlimaUnitSensorDescription

    def __init__(
        self,
        coordinator: SKlimaCoordinator,
        unit_id: int,
        description: SKlimaUnitSensorDescription,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, unit_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | None:
        """Value."""
        unit = self.unit
        return self.entity_description.value_fn(unit) if unit else None
