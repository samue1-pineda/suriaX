"""Lectura y decodificacion del codigo fuente.

Esta es la fase previa al lexer. Su unica responsabilidad es transformar los
bytes crudos de un archivo `.srcx` / `.libsrx` en una cadena Unicode (`str`)
lista para tokenizar.

Diseño (rendimiento + modularidad):
 - la decodificacion UTF-8 -> str ocurre **una sola vez** aqui, fuera del
   lexer. el lexer trabaja sobre `str`, donde indexar es O(1).
 - NO se eliminan comentarios en esta fase: hacerlo aqui obligaria a una
   segunda pasada y a copiar el texto. Los comentarios se saltan dentro del
   lexer, en el mismo paso en el que se generan los tokens.
 - se normaliza el fin de linea (CRLF / CR -> LF) para que el lexer maneje un
   unico separador y el conteo de lineas sea estable.
"""

from __future__ import annotations

from typing import Optional

try:
    from error_handler import lex_error
except ImportError:  # pragma: no cover - ejecucion directa
    import lex_error  # type: ignore


# BOM UTF-8 opcional al inicio del archivo
# EF BB BF
_BOM = "﻿"


def decode(data: bytes, *, file: Optional[str] = None) -> str:
    """Decodifica bytes UTF-8 a `str`, normalizando los saltos de linea.

    Lanza :class:`InvalidUnicodeCharacterError` (LEX008) si el contenido no es
    UTF-8 valido.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        # localizamos la linea/columna aproximada del byte ofensivo.
        prefix = data[: exc.start]
        line = prefix.count(b"\n") + 1
        col = exc.start - (prefix.rfind(b"\n") + 1) + 1
        raise lex_error.InvalidUnicodeCharacterError(
            f"byte UTF-8 invalido: {exc.reason}",
            line=line,
            column=col,
            file=file,
        ) from exc

    return _normalize(text)


def read_file(path: str) -> str:
    """Lee un archivo del disco y lo decodifica a `str` normalizado."""
    with open(path, "rb") as fh:
        data = fh.read()
    return decode(data, file=path)


def from_text(text: str) -> str:
    """Normaliza una cadena que ya esta en memoria (sin tocar el disco).

    Util para el playground, los tests y la directiva ``#test lexer``.
    """
    return _normalize(text)


def _normalize(text: str) -> str:
    """Quita el BOM inicial y unifica los saltos de linea a ``\\n``."""
    if text.startswith(_BOM):
        text = text[len(_BOM):]
    # CRLF primero para no dejar un CR suelto.
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text
