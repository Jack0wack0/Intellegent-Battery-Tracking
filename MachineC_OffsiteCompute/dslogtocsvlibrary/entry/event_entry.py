from __future__ import annotations

import re
import struct
from datetime import datetime
from typing import Optional

from .generic_entry import GenericEntry
from .parse_date import parse_date


class EventEntry(GenericEntry):
    byte_code = ">qQi"
    message_pattern = r"<\w*>"

    def __init__(
        self,
        unix_time: int,
        offset: int,
        message_length: int,
        message: Optional[dict] = None,
    ) -> None:
        self.unix_time = unix_time
        self.offset = offset
        self.message_length = message_length
        self.message = message if message else {}
        super().__init__()

    @classmethod
    def from_bytes(cls, data: bytes) -> EventEntry:
        unix_time, offset, length = struct.unpack(cls.byte_code, data)
        return cls(unix_time, offset, length)

    def parse_message(self, data: bytes) -> None:
        text = struct.unpack(f">{self.message_length}s", data)[0].decode(
            "ascii", "backslashreplace"
        )
        self.message = text
        matches: list[re.Match] = list(re.finditer(self.message_pattern, text))
        message = {}
        for index in range(len(matches)):
            match = matches[index]
            key = text[match.start() + 1 : match.end() - 1]
            if index == len(matches) - 1:
                value_stop = len(text) - 1
            else:
                next_match = matches[index + 1]
                value_stop = next_match.start() - 1
            value_start = match.end() + 1
            is_version = key == "TagVersion"
            if is_version:
                value_start -= 1
            value = text[value_start:value_stop]
            if is_version:
                value = int(value)
                if value != 1:
                    raise ValueError(f"Unsupported version {value}")
            message[key] = value
        self.message = message

    @classmethod
    def length(cls) -> int:
        return struct.calcsize(cls.byte_code)

    @property
    def date(self) -> datetime:
        return parse_date(self.unix_time, self.offset)
