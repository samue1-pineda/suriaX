"""Errores INTERNOS del compilador (ICE): un fallo del compilador, no del programa.

Un diagnóstico normal (``LEX``/``PAR``/``SEM``...) dice que el PROGRAMA está
mal. Un ICE dice lo contrario: el programa pudo estar bien y el que falló es
el compilador — una excepción de Python que ninguna fase esperaba. Mezclar
los dos es el peor error posible en un compilador educativo: quien aprende
lee "tu programa tiene un error" y busca en su código un fallo que no existe.

Por eso un ICE:

- tiene su propio código (``ICE000``) y su propio código de salida (``6``,
  ``driver.EXIT_INTERNAL_ERROR``), distinto del ``1`` de "hay errores";
- se muestra como lo haría Python: el traceback de la excepción ORIGINAL
  (dónde falló dentro del compilador y por qué) seguido de una línea que dice
  en qué fase y con qué archivo;
- nunca se disfraza de otra cosa ni se silencia.

Antes este módulo tenía seis clases vacías que no heredaban de nada y que
nadie usaba; los fallos internos salían como un traceback crudo con exit 1,
indistinguibles de un programa con errores.
"""

from __future__ import annotations

import os
import traceback
from typing import Optional

from .error import CompilerError, Severity

#: Raíz del repositorio: sirve para señalar, dentro de la traza, el último
#: frame que es código DEL COMPILADOR (no de la biblioteca estándar).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


class InternalCompilerError(CompilerError):
    """El compilador falló por un error propio mientras procesaba un archivo.

    No es un error de tu programa: es un bug del compilador. Repórtalo con el
    archivo que se estaba compilando y la traza completa (``--debug`` la deja
    en ``dumps/``).
    """

    severity = Severity.PANIC

    def __init__(self, message: str = "error interno del compilador", *,
                 phase: Optional[str] = None, file: Optional[str] = None,
                 cause: Optional[BaseException] = None, **kwargs) -> None:
        # 'file' NO se pasa como ubicación: un ICE no ocurre en una línea del
        # fuente, y darle 'línea 1, columna 1' señalaría una posición falsa.
        super().__init__(message, code="ICE000", phase=phase or "interno",
                         **kwargs)
        self.file = file
        self.cause = cause

    @classmethod
    def desde(cls, exc: BaseException, *, phase: str,
              file: Optional[str] = None) -> "InternalCompilerError":
        """Envuelve la excepción ``exc`` ocurrida en ``phase``.

        El mensaje nombra la excepción original y el sitio del compilador
        donde ocurrió: es lo único que ve un editor, que no muestra trazas.
        """
        sitio = cls._sitio_en_el_compilador(exc)
        mensaje = (f"error interno del compilador en la fase '{phase}': "
                   f"{type(exc).__name__}: {exc}")
        if sitio:
            mensaje += f" [{sitio}]"
        ice = cls(mensaje, phase=phase, file=file, cause=exc)
        ice.__cause__ = exc
        return ice

    @staticmethod
    def _sitio_en_el_compilador(exc: BaseException) -> str:
        """``archivo:línea en función()`` del último frame del proyecto."""
        propios = [f for f in traceback.extract_tb(exc.__traceback__)
                   if os.path.abspath(f.filename).startswith(_REPO_ROOT)]
        if not propios:
            return ""
        ultimo = propios[-1]
        archivo = os.path.relpath(ultimo.filename, _REPO_ROOT).replace(os.sep, "/")
        return f"{archivo}:{ultimo.lineno} en {ultimo.name}()"

    def render(self) -> str:
        """El informe completo, al estilo de Python.

        Primero la traza de la excepción original —el "dónde" y el "por qué"
        dentro del compilador—, después el "qué": el código, la fase y el
        archivo que se procesaba.
        """
        partes = []
        if self.cause is not None:
            partes.append("".join(traceback.format_exception(
                type(self.cause), self.cause, self.cause.__traceback__)).rstrip())
            partes.append("")
        partes.append(f"ICE000: error interno del compilador en la fase "
                      f"'{self.phase}'")
        if self.file:
            partes.append(f"  procesando: {self.file}")
        partes.append("  esto es un fallo del compilador, no de tu programa")
        return "\n".join(partes)


__all__ = ["InternalCompilerError"]
