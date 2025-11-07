from __future__ import annotations

from typing import Optional

from .generic_entry import GenericEntry


class PdpData(GenericEntry):
    def __init__(
        self,
        pdp_id: int = 0,
        currents: Optional[list[float]] = None,
        resistance: float = 0.0,
        voltage: float = 0.0,
        temperature: float = 0.0,
    ) -> None:
        self.pdp_id = pdp_id
        self.currents = currents if currents else []
        self.voltage = voltage
        self.resistance = resistance
        self.temperature = temperature

    @classmethod
    def from_bytes(cls, data: bytes) -> PdpData:
        return PdpData()

    @classmethod
    def length(cls) -> int:
        return 0
