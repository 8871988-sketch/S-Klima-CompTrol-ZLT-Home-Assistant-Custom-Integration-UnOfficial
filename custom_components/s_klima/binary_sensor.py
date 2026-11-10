"""Binary sensors for the S-Klima CompTrol ZLT integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from .api import IndoorUnit
from .coordinator import SKlimaCoordinator
from .entity import SKlimaUnitEntity

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SKlimaConfigEntry

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SKlimaBinarySensorDescription(BinarySensorEntityDescription):
    """Describes an indoor unit binary sensor."""

    value_fn: Callable[[IndoorUnit], bool]


UNIT_BINARY_SENSORS: tuple[SKlimaBinarySensorDescription, ...] = (
    SKlimaBinarySensorDescription(
        key="fault",
        translation_key="fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda unit: unit.is_error,
    ),
    SKlimaBinarySensorDescription(
        key="filter",
        translation_key="filter",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda unit: unit.filter_alarm,
    ),
    SKlimaBinarySensorDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda unit: unit.is_online,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SKlimaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        SKlimaUnitBinarySensor(coordinator, unit_id, description)
        for unit_id in coordinator.data.units
        for description in UNIT_BINARY_SENSORS
    )


class SKlimaUnitBinarySensor(SKlimaUnitEntity, BinarySensorEntity):
    """Binary sensor of an indoor unit."""

    entity_description: SKlimaBinarySensorDescription

    def __init__(
        self,
        coordinator: SKlimaCoordinator,
        unit_id: int,
        description: SKlimaBinarySensorDescription,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, unit_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """State."""
        unit = self.unit
        return self.entity_description.value_fn(unit) if unit else None
