"""Ayudas de la lista de ubigeos del INEI."""

import unicodedata


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes: «San Martín» y «san martin» se buscan igual."""
    sin_tildes = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sin_tildes if not unicodedata.combining(c)).lower().strip()


def texto_de_busqueda(codigo: str, departamento: str, provincia: str, distrito: str) -> str:
    """Lo que se compara al buscar: el código y los tres nombres, normalizados."""
    return normalizar(f"{codigo} {departamento} {provincia} {distrito}")
