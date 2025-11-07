from __future__ import annotations

import struct
from datetime import datetime
from typing import Optional

from .generic_entry import GenericEntry
from .pdp_data import PdpData
from .pdp_meta_data import PdpMetaData
from .pdp_type import PdpType
from .status_entry import StatusEntry


class LogEntry(GenericEntry):
    byte_code = ">BbHBBBBHB"

    def __init__(
        self,
        trip_time: float,
        packet_loss: float,
        voltage: float,
        rio: float,
        status: StatusEntry,
        can: float,
        wifi: float,
        bandwidth: float,
        pdp_id: int,
        date: datetime = datetime(1904, 1, 1, 0, 0, 0),
        pdp_meta_data: PdpMetaData = PdpMetaData(PdpType.NONE),
        pdp_data: PdpData = PdpData(),
    ) -> None:
        self.trip_time = trip_time
        self.packet_loss = packet_loss
        self.voltage = voltage
        self.rio = rio
        self.status = status
        self.can = can
        self.wifi = wifi
        self.bandwidth = bandwidth
        self.pdp_id = pdp_id
        self.date = date
        self.pdp_meta_data = pdp_meta_data
        self.pdp_data = pdp_data

    @classmethod
    def from_bytes(cls, data: bytes) -> LogEntry:
        (
            trip_time,
            packet_loss,
            voltage,
            rio,
            status,
            can,
            wifi,
            bandwidth,
            pdp_id,
        ) = struct.unpack(cls.byte_code, data)
        return cls(
            trip_time=cls._trip_time_to_double(trip_time),
            packet_loss=cls._packet_loss_to_double(packet_loss),
            voltage=cls._voltage_to_double(voltage),
            rio=cls._roborio_cpu_to_double(rio),
            status=StatusEntry.from_int(status),
            can=cls._can_util_to_double(can),
            wifi=cls._wifi_db_to_double(wifi),
            bandwidth=cls._bandwidth_to_double(bandwidth),
            pdp_id=pdp_id,
        )

    @classmethod
    def _trip_time_to_double(cls, trip_time: int) -> float:
        return trip_time * 0.5

    @classmethod
    def _packet_loss_to_double(cls, packet_loss: int) -> float:
        return (packet_loss * 4) * 0.01

    @classmethod
    def _voltage_to_double(cls, voltage: int) -> float:
        return voltage * 0.00390625

    @classmethod
    def _roborio_cpu_to_double(cls, rio: int) -> float:
        return (rio * 0.5) * 0.01

    @classmethod
    def _can_util_to_double(cls, can: int) -> float:
        return (can * 0.5) * 0.01

    @classmethod
    def _wifi_db_to_double(cls, wifi: int) -> float:
        return (wifi * 0.5) * 0.01

    @classmethod
    def _bandwidth_to_double(cls, bandwidth: int) -> float:
        return bandwidth * 0.00390625

    @classmethod
    def length(cls) -> int:
        return struct.calcsize(cls.byte_code)

    def __str__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"trip_time={self.trip_time}, "
            f"packet_loss={self.packet_loss}, "
            f"voltage={self.voltage}, "
            f"rio={self.rio}, "
            f"status={self.status}, "
            f"can={self.can}, "
            f"wifi={self.wifi}, "
            f"bandwidth={self.bandwidth}, "
            f"pdp_id={self.pdp_id}, "
            f"time={self.date}, "
            f"pdp_meta_data={self.pdp_meta_data}, "
            f"pdp_data={self.pdp_data})"
        )

    __repr__ = __str__
