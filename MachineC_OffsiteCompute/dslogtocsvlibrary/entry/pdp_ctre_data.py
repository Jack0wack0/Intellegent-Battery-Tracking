from __future__ import annotations

import struct

from .pdp_data import PdpData


class PdpCtreData(PdpData):
    byte_code = ">BQQ" + ("B" * 8)

    def __init__(
        self,
        pdp_id: int,
        currents: list[float],
        resistance: float,
        main_voltage: float,
        temperature: float,
    ) -> None:
        self.pdp_id = pdp_id
        self.currents = currents
        self.voltage = main_voltage
        self.resistance = resistance
        self.temperature = temperature

    @classmethod
    def from_bytes(cls, data: bytes) -> PdpCtreData:
        parsed = struct.unpack(cls.byte_code, data)
        pdp_id = parsed[0]
        longs = (
            parsed[1],
            parsed[2],
            int.from_bytes(
                b"".join([i.to_bytes(1, "big") for i in parsed[3:8]]) + b"\x00\x00\x00",
                byteorder="big",
            ),
        )
        resistance = parsed[8]
        voltage = parsed[9] * 0.0736
        temperature = float(parsed[10])
        currents = [0.0 for _ in range(16)]
        for index in range(len(currents)):
            data_index = index // 6
            data_offset = index % 6
            value = longs[data_index]
            num = value << (data_offset * 10)
            num = num >> 54
            currents[index] = num / 8

        return cls(pdp_id, currents, resistance, voltage, temperature)

    @classmethod
    def length(cls) -> int:
        return struct.calcsize(cls.byte_code)
