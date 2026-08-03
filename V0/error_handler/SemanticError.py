from __future__ import annotations

from typing import Any, Optional

try:
    from .error import CompilerError, Severity
except ImportError:  # pragma: no cover - compatibility for direct execution
    from error import CompilerError, Severity


class SemanticError(CompilerError):
    """Base para los errores de la fase semántica.

    Agrupa problemas de símbolos, mutabilidad, regiones, hooks y llamadas.
    Los errores de tipo más específicos se representan con clases propias del
    AST o del subsistema de tipos para mantener el reporte más claro.
    """

    def __init__(
        self,
        message: Any,
        code: str = "SEM000",
        line: Optional[int] = None,
        column: Optional[int] = None,
        file: Optional[str] = None,
        loc: Any = None,
    ):
        super().__init__(
            message,
            code=code,
            line=line,
            column=column,
            file=file,
            phase="semantic",
            loc=loc,
        )


class UndefinedSymbolError(SemanticError):
    """Se referencia un nombre que no existe en ningún scope visible."""

    def __init__(self, message: Any = "símbolo no definido", **kwargs: Any):
        super().__init__(message, code="SEM001", **kwargs)


class DuplicateSymbolError(SemanticError):
    """Un nombre ya está declarado en el mismo scope y espacio de nombres
    (tipos o valores, ver ``symbol_table.py``)."""

    def __init__(self, message: Any = "símbolo duplicado", **kwargs: Any):
        super().__init__(message, code="SEM002", **kwargs)


class ImmutableAssignmentError(SemanticError):
    """Se reasigna un binding declarado ``const``."""

    def __init__(self, message: Any = "asignación a un binding 'const'", **kwargs: Any):
        super().__init__(message, code="SEM003", **kwargs)


class UseAfterMoveError(SemanticError):
    """Se usa un valor después de haberlo movido (``move x;``).

    Chequeo intra-función, conservador y de una sola pasada (ver
    ``semantic/ARQUITECTURA.md`` secc. 4); puede tener falsos negativos a
    propósito — el MIR (C++) hace la verificación definitiva.
    """

    severity = Severity.PANIC

    def __init__(self, message: Any = "uso de un valor tras 'move'", **kwargs: Any):
        super().__init__(message, code="SEM004", **kwargs)


class DoubleMoveError(SemanticError):
    """Se mueve (``move x;``) un valor que ya había sido movido."""

    severity = Severity.PANIC

    def __init__(self, message: Any = "'move' duplicado sobre el mismo valor", **kwargs: Any):
        super().__init__(message, code="SEM005", **kwargs)


class InvalidHookSignatureError(SemanticError):
    """Una función con nombre "dunder" reconocido como hook
    (``__free__``/``__make__``/``__sizeof__``, ver ``semantic/hooks.py``) no
    cumple la convención de firma que le corresponde: ``__free__``/
    ``__sizeof__`` deben tomar ``ptr T`` como primer parámetro; ``__make__``
    debe devolver ``ptr T``.
    """

    def __init__(self, message: Any = "firma de hook inválida", **kwargs: Any):
        super().__init__(message, code="SEM006", **kwargs)


class DuplicateHookError(SemanticError):
    """Ya existe un hook del mismo tipo (``__free__``/``__make__``/
    ``__sizeof__``/``__print__``/``__len__``) registrado para el mismo tipo
    nominal."""

    def __init__(self, message: Any = "hook duplicado para el mismo tipo", **kwargs: Any):
        super().__init__(message, code="SEM007", **kwargs)


class CallArityError(SemanticError):
    """Una llamada pasa un número de argumentos distinto al de los
    parámetros de la función resuelta."""

    def __init__(self, message: Any = "número de argumentos incorrecto", **kwargs: Any):
        super().__init__(message, code="SEM008", **kwargs)


class LibraryNotFoundError(SemanticError):
    """No se encontró el archivo ``<lib>.libsrx`` en ninguna ruta de
    búsqueda (directorio del fuente + ``libraries.libsrx_paths`` de la
    configuración)."""

    def __init__(self, message: Any = "librería .libsrx no encontrada", **kwargs: Any):
        super().__init__(message, code="SEM009", **kwargs)


class InvalidLibraryError(SemanticError):
    """La librería ``.libsrx`` existe pero es inválida: no termina en
    ``#export <alias>``, su alias no coincide con el nombre importado, o su
    contenido tiene errores léxicos/sintácticos."""

    def __init__(self, message: Any = "librería .libsrx inválida", **kwargs: Any):
        super().__init__(message, code="SEM010", **kwargs)


class UnknownLibraryMemberError(SemanticError):
    """Se accede a un miembro (``IO.foo``) que la librería importada no
    exporta."""

    def __init__(self, message: Any = "miembro no exportado por la librería", **kwargs: Any):
        super().__init__(message, code="SEM011", **kwargs)


class UndefinedRegionError(SemanticError):
    """``make T in r`` / ``expr at r`` refieren una región ``r`` que no está
    declarada (o ya se cerró) en ese punto."""

    def __init__(self, message: Any = "región no declarada en este punto", **kwargs: Any):
        super().__init__(message, code="SEM012", **kwargs)


class InvalidAddressOfError(SemanticError):
    """``&expr`` sobre algo que no es un lvalue (identificador, campo o
    índice): un temporal no tiene dirección estable que tomar."""

    severity = Severity.PANIC

    def __init__(self, message: Any = "'&' requiere un lvalue", **kwargs: Any):
        super().__init__(message, code="SEM013", **kwargs)


class InvalidFreeTargetError(SemanticError):
    """``free x;`` sobre un valor cuyo tipo NO es puntero (``ptr T``):
    solo la memoria referenciada por un puntero puede liberarse."""

    severity = Severity.PANIC

    def __init__(self, message: Any = "'free' requiere un puntero", **kwargs: Any):
        super().__init__(message, code="SEM014", **kwargs)


class ReadOnlyPointerWriteError(SemanticError):
    """Escritura a través de un ``ptr T`` de solo lectura. Para mutar el
    apuntado, el puntero debe declararse ``ptr mutable T``."""

    severity = Severity.PANIC

    def __init__(self, message: Any = "escritura a través de un puntero de solo lectura", **kwargs: Any):
        super().__init__(message, code="SEM015", **kwargs)


class ExpressionTooDeepError(SemanticError):
    """Se detecta una expresión con un nivel de anidación excesivo.

    Las pasadas semánticas recorren el árbol de forma recursiva, así que un
    programa demasiado anidado puede agotar la pila de Python. Este error lo
    convierte en un diagnóstico controlado en lugar de dejar que el proceso
    se detenga con un traceback.
    """

    def __init__(self, message: Any = "construcción demasiado anidada para el análisis semántico", **kwargs: Any):
        super().__init__(message, code="SEM017", **kwargs)


class InvalidCastError(SemanticError):
    """``cast<T>(x)`` sin conversión definida: par de primitivos no
    permitido, o tipo nominal destino sin hook ``__cast__`` declarado."""

    def __init__(self, message: Any = "conversión 'cast' inválida", **kwargs: Any):
        super().__init__(message, code="SEM016", **kwargs)


class UnknownHookError(SemanticError):
    """``hook fn __x__(...)`` cuyo nombre NO pertenece al set fijo de hooks
    del compilador (``__free__``/``__make__``/``__sizeof__``/``__print__``/
    ``__len__``/``__cast__``, ver ``semantic/hooks.py``). El especificador
    ``hook`` promete un hook reconocido; para un metodo especial libre use
    ``dunder``."""

    def __init__(self, message: Any = "nombre de hook no reconocido", **kwargs: Any):
        super().__init__(message, code="SEM018", **kwargs)


class VisibilityViolationError(SemanticError):
    """Se usa un símbolo cuya reserva de visibilidad lo prohíbe en este punto:
    un ``internal`` fuera de su archivo, o un ``private`` fuera de su paquete."""

    def __init__(self, message: Any = "símbolo no visible en este punto", **kwargs: Any):
        super().__init__(message, code="SEM019", **kwargs)


class InvalidDeleteError(SemanticError):
    """``delete()`` sin argumento fuera del bloque de una región (no hay
    región a la que referirse), o ``delete(region r)`` sobre un nombre que no
    es una región."""

    severity = Severity.PANIC

    def __init__(self, message: Any = "'delete' de región inválido", **kwargs: Any):
        super().__init__(message, code="SEM020", **kwargs)


class TraitNotSatisfiedError(SemanticError):
    """Un ``@impl(trait)`` no cumple el contrato: al tipo le falta un método
    dunder que el trait requiere, o la firma no coincide (con ``self``
    sustituido por el tipo que implementa). También cubre ``@impl`` de un
    trait no declarado."""

    def __init__(self, message: Any = "el tipo no satisface el trait", **kwargs: Any):
        super().__init__(message, code="SEM021", **kwargs)


class InvalidDunderSignatureError(SemanticError):
    """Un ``dunder fn`` (método especial libre del usuario) no toma un tipo
    dueño como receptor: su primer parámetro debe ser ``T`` o ``T ptr`` (T
    nominal), para poder indexarlo por tipo igual que un hook."""

    def __init__(self, message: Any = "firma de 'dunder fn' inválida", **kwargs: Any):
        super().__init__(message, code="SEM022", **kwargs)


__all__ = [
    "SemanticError",
    "UndefinedSymbolError",
    "DuplicateSymbolError",
    "ImmutableAssignmentError",
    "UseAfterMoveError",
    "DoubleMoveError",
    "InvalidHookSignatureError",
    "DuplicateHookError",
    "CallArityError",
    "LibraryNotFoundError",
    "InvalidLibraryError",
    "UnknownLibraryMemberError",
    "UndefinedRegionError",
    "InvalidAddressOfError",
    "InvalidFreeTargetError",
    "ReadOnlyPointerWriteError",
    "InvalidCastError",
    "ExpressionTooDeepError",
    "UnknownHookError",
    "VisibilityViolationError",
    "InvalidDeleteError",
    "TraitNotSatisfiedError",
    "InvalidDunderSignatureError",
]
