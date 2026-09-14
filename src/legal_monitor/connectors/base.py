from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from legal_monitor.models import RawDocument


class BaseConnector(ABC):
    name: str

    @abstractmethod
    def fetch(self, date_from: date, date_to: date) -> list[RawDocument]:
        raise NotImplementedError
