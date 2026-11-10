"""Base entities for the S-Klima CompTrol ZLT integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import IndoorUnit
from .const import DOMAIN
from .coordinator import SKlimaCoordinator


class SKlimaHubEntity(CoordinatorEntity[SKlimaCoordinator]):
    """Entity belonging to the CompTrol ZLT itself."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SKlimaCoordinator, key: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)})


class SKlimaUnitEntity(CoordinatorEntity[SKlimaCoordinator]):
    """Entity belonging to one indoor unit."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SKlimaCoordinator, unit_id: int, key: str | None
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._unit_id = unit_id
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = (
            f"{entry_id}_{unit_id}" if key is None else f"{entry_id}_{unit_id}_{key}"
        )
        unit = coordinator.data.units[unit_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{unit_id}")},
            name=unit.name,
            manufacturer="Mitsubishi Heavy Industries",
            model=f"Innengerät {unit.address}",
        )

    @property
    def unit(self) -> IndoorUnit | None:
        """Current state of the unit."""
        data = self.coordinator.data
        return data.units.get(self._unit_id) if data else None

    @property
    def available(self) -> bool:
        """Available while the coordinator works and the unit is known."""
        return super().available and self.unit is not None
