from __future__ import annotations

from typing import Any, Optional

try:
    from .error import CompilerError, Severity
except ImportError:  # pragma: no cover - compatibility for direct execution
    from error import CompilerError, Severity


class SemanticError(CompilerError):
    """Base para los errores de la fase semántica.

    Agrupa problemas de símbolos, mutabilidad, propiedad, hooks y llamadas.
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


class UseAfterFreeError(SemanticError):
    """Uso de un valor destruido con ``free``.

    Hermano de :class:`UseAfterMoveError`: en los dos casos el dueño ya soltó
    el valor, y lo único que cambia es POR QUÉ — ``move`` lo transfirió,
    ``free`` lo destruyó. Lo detecta la misma pasada lineal
    (``semantic/memory_check.py``), así que hereda sus garantías: cero falsos
    positivos, y los caminos que el análisis conservador no ve los cubre el
    intérprete en ejecución (``RT003``).
    """

    severity = Severity.PANIC

    def __init__(self, message: Any = "uso después de 'free'", **kwargs: Any):
        super().__init__(message, code="SEM023", **kwargs)


class DoubleFreeError(SemanticError):
    """``free`` sobre un valor que ya fue destruido.

    Hermano de :class:`DoubleMoveError`. Antes solo lo veía el intérprete
    (``RT005``); ahora el camino lineal lo rechaza al compilar.
    """

    severity = Severity.PANIC

    def __init__(self, message: Any = "'free' de un valor ya destruido", **kwargs: Any):
        super().__init__(message, code="SEM024", **kwargs)


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


class InvalidValueTypeError(SemanticError):
    """``void`` usado como tipo de un VALOR (variable, parámetro o campo).

    ``void`` significa "no hay valor": solo tiene sentido como tipo de
    retorno. Se comprueba en el único punto por el que pasan las tres
    posiciones de valor (``TypeBinder.bind``), no en cada una — así no puede
    quedar una sin cubrir, que es como ``struct { void v; }`` llegó a
    compilar.
    """

    severity = Severity.PANIC

    def __init__(self, message: Any = "'void' no puede ser el tipo de un valor",
                 **kwargs: Any):
        super().__init__(message, code="SEM025", **kwargs)


class InfiniteSizeTypeError(SemanticError):
    """Un ``struct`` que se contiene a sí mismo POR VALOR.

    ``struct { S s; } S;`` no tiene tamaño finito: cada ``S`` contendría otro
    ``S``. La recursión legítima se escribe con un puntero
    (``struct { S ptr sig; } S;``), que sí tiene tamaño conocido — y es la
    misma distinción que gobierna la propiedad: un puntero no contiene, se
    refiere.
    """

    severity = Severity.PANIC

    def __init__(self, message: Any = "tipo de tamaño infinito", **kwargs: Any):
        super().__init__(message, code="SEM026", **kwargs)


class TypeArityError(SemanticError):
    """Un tipo generico usado con un numero de argumentos que no es el suyo.

    ``Vector<int, str>`` sobre un ``Vector<T>``, o ``Vector`` a secas cuando
    declara un parametro. Es la razon de que los parametros se escriban en la
    declaracion: sin ellos escritos, la aridad no seria comprobable.
    """

    severity = Severity.PANIC

    def __init__(self, message: Any = "numero de argumentos de tipo incorrecto",
                 **kwargs: Any):
        super().__init__(message, code="SEM027", **kwargs)


class IncompleteStructLiteralError(SemanticError):
    """Un literal de struct que deja campos sin valor.

    ``P{ a: 1 }`` sobre un ``struct { int a; int b; } P;`` construia un valor
    al que le FALTA ``b``: el programa compilaba y reventaba al leer ``p.b``,
    en runtime y lejos de la causa. No hay valor por defecto en suriaX —un
    campo sin escribir no tiene nada que leer—, asi que el literal es el unico
    sitio donde la ausencia se puede ver, y aqui se ve.
    """

    severity = Severity.PANIC

    def __init__(self, message: Any = "literal de struct incompleto",
                 **kwargs: Any):
        super().__init__(message, code="SEM028", **kwargs)


class UnsupportedPayloadError(SemanticError):
    """Una variante de ``enum`` que lleva un valor con destructor.

    Destruir un enum suma exige saber QUE variante es en ejecucion para
    destruir lo que esa variante lleva, y el drop de hoy trabaja sobre rutas
    estaticas de campos. Se rechaza en vez de filtrarse: un payload con
    ``__free__`` que nadie libera es una fuga silenciosa, y el silencio es
    justo lo que el modelo de memoria promete no hacer.
    """

    severity = Severity.PANIC

    def __init__(self, message: Any = "payload de variante no soportado",
                 **kwargs: Any):
        super().__init__(message, code="SEM029", **kwargs)


class MissingHandlerError(SemanticError):
    """Un nodo del AST llegó a una pasada que no sabe recorrerlo.

    NO es un error del programa que se compila: es un defecto del compilador.
    Se reporta como diagnóstico —y no con una excepción— por la misma razón
    que el resto de la fase: un fallo no debe tirar la compilación entera ni
    esconder los diagnósticos reales que ya se habían acumulado. Va con
    severidad ``PANIC`` para que se distinga de un error del usuario.

    Existe porque el silencio costó caro: el despacho de ``scope_resolver``
    ignoraba sin decir nada las clases que no estaban en su tabla, y por eso
    el inicializador de un ``type_decl`` cruzó el frontend entero sin que
    nadie lo mirara.
    """
    severity = Severity.PANIC

    def __init__(self, message: Any = "nodo sin handler en esta pasada",
                 **kwargs: Any):
        super().__init__(message, code="SEM000", **kwargs)


__all__ = [
    "SemanticError",
    "InvalidValueTypeError",
    "InfiniteSizeTypeError",
    "TypeArityError",
    "IncompleteStructLiteralError",
    "UnsupportedPayloadError",
    "MissingHandlerError",
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
    "UseAfterFreeError",
    "DoubleFreeError",
    "InvalidAddressOfError",
    "InvalidFreeTargetError",
    "ReadOnlyPointerWriteError",
    "InvalidCastError",
    "ExpressionTooDeepError",
    "UnknownHookError",
    "VisibilityViolationError",
    "TraitNotSatisfiedError",
    "InvalidDunderSignatureError",
]
