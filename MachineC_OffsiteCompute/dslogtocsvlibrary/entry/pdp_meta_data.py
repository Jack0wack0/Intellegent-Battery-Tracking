from __future__ import annotations
import struct
from .generic_entry import GenericEntry
from .pdp_type import PdpType


class PdpMetaData(GenericEntry):
    byte_code = ">BBB"

    def __init__(self, type: PdpType) -> None:
        self.type = type

    @classmethod
    def from_bytes(cls, data: bytes) -> PdpMetaData:
        _, _, pdp_type = struct.unpack(cls.byte_code, data)
        return cls(PdpType(pdp_type))

    @classmethod
    def length(cls) -> int:
        return struct.calcsize(cls.byte_code)

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(type={self.type})"

    __repr__ = __str__
