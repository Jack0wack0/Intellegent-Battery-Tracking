from __future__ import annotations

from abc import ABC, abstractmethod


class GenericEntry(ABC):
    @classmethod
    @abstractmethod
    def from_bytes(cls, data: bytes) -> GenericEntry:
        pass

    @classmethod
    @abstractmethod
    def length(cls) -> int:
        pass
