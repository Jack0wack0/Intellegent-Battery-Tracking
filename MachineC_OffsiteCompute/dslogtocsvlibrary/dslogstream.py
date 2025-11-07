from datetime import timedelta
from io import BufferedReader
from typing import Generator, Optional, Type, cast

from .entry.log_entry import LogEntry
from .entry.metadata import Metadata
from .entry.pdp_ctre_data import PdpCtreData
from .entry.pdp_data import PdpData
from .entry.pdp_meta_data import PdpMetaData
from .entry.pdp_rev_pdh_data import PdpRevPdhData
from .entry.pdp_type import PdpType


class DsLogStream:
    def __init__(self, file: BufferedReader) -> None:
        self.file = file
        self.metadata = Metadata.from_bytes(self.file.read(Metadata.length()))
        if self.metadata.version != 4:
            raise ValueError(f"Unsupported log version {self.metadata.version}")
        self.pdp_map: dict[PdpType, Optional[Type[PdpData]]] = {
            PdpType.NONE: None,
            PdpType.CTRE: PdpCtreData,
            PdpType.REV: PdpRevPdhData,
        }
        self.entry_distance_s = 0.02

    def __iter__(self) -> Generator[LogEntry, None, None]:
        self.start_time = self.metadata.date
        index = 0
        while True:
            time = self.start_time + timedelta(seconds=self.entry_distance_s * index)
            index += 1
            if data := self.conditional_read(LogEntry.length()):
                entry = LogEntry.from_bytes(data)
            else:
                break
            entry.date = time
            if data := self.conditional_read(PdpMetaData.length()):
                entry.pdp_meta_data = PdpMetaData.from_bytes(data)
            else:
                break
            pdp_class = self.pdp_map[entry.pdp_meta_data.type]
            if pdp_class is not None:
                if data := self.conditional_read(pdp_class.length()):
                    pdp_data = cast(PdpData, pdp_class.from_bytes(data))
                else:
                    break
                entry.pdp_data = pdp_data
            yield entry

    def conditional_read(self, expected_size: int) -> Optional[bytes]:
        data = self.file.read(expected_size)
        if len(data) != expected_size:
            return None
        return data
