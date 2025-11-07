from __future__ import annotations
import struct
from datetime import datetime
from .generic_entry import GenericEntry
from .parse_date import parse_date


class Metadata(GenericEntry):
    byte_code = ">iqQ"

    def __init__(self, version: int, unix_time: float, offset: int):
        self.version = version
        self.unix_time = unix_time
        self.offset = offset

    @classmethod
    def from_bytes(cls, data: bytes) -> Metadata:
        version, unix_time, offset = struct.unpack(cls.byte_code, data)
        return cls(version, unix_time, offset)

    @classmethod
    def length(cls) -> int:
        return struct.calcsize(cls.byte_code)

    @property
    def date(self) -> datetime:
        return parse_date(self.unix_time, self.offset)
