from enum import StrEnum

from pydantic import BaseModel


class CatalogSource(StrEnum):
    FC_MANIA = "FC_MANIA"
    TRANSFERMARKT = "TRANSFERMARKT"


class ImportRequest(BaseModel):
    source: CatalogSource
    file_name: str


class ImportResult(BaseModel):
    accepted: bool = False
    reason: str = (
        "Importadores aguardam arquivos autorizados; nenhuma coleta externa foi implementada."
    )
