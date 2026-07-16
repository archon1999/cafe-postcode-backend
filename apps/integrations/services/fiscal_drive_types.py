from dataclasses import dataclass


SUPPORTED_FISCAL_PROVIDERS = frozenset({'fiscal-drive-service'})


class FiscalDriveError(Exception):
    def __init__(self, message: str, *, code: str = ''):
        super().__init__(message)
        self.code = str(code or '')


@dataclass(slots=True)
class FiscalDriveTarget:
    factory_id: str
    info: dict

