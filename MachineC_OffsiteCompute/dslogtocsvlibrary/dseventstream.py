from io import BufferedReader
from typing import Generator, Optional

from .entry.event_entry import EventEntry
from .entry.metadata import Metadata


class DsEventStream:
    def __init__(self, file: BufferedReader) -> None:
        self.file = file
        self.metadata = Metadata.from_bytes(self.file.read(Metadata.length()))
        if self.metadata.version != 4:
            raise ValueError(f"Unsupported log version {self.metadata.version}")

    def __iter__(self) -> Generator[EventEntry, None, None]:
        self.start_time = self.metadata.date
        while True:
            if data := self.conditional_read(EventEntry.length(), allow_eof=True):
                entry = EventEntry.from_bytes(data)
            else:
                break
            if not 0 <= entry.message_length <= 1_048_576:
                raise ValueError("Invalid DS event message length")
            entry.parse_message(self.conditional_read(entry.message_length))
            yield entry

    def conditional_read(self, expected_size: int, allow_eof=False) -> Optional[bytes]:
        data = self.file.read(expected_size)
        if not data and allow_eof:
            return None
        if len(data) != expected_size:
            raise ValueError(f"Truncated DS event: expected {expected_size}, got {len(data)}")
        return data
