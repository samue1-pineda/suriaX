"""Errores de RUNTIME del intérprete (``ARQUITECTURA.md`` — módulo ``errors.py``).

Jerarquía propia, separada de ``V0/error_handler`` (esos son errores de
COMPILACIÓN): aquí el programa ya validó estáticamente y falla EJECUTANDO —
la red de la que caen los casos que el análisis conservador no ve
(use-after-move a través de ramas, use-after-free, null deref...).

Cada error lleva código estable y la posición (``ln``/``col``) del nodo HIR
que lo disparó, para el reporte educativo. Hay DOS familias:

- ``EXCxxx`` (:class:`ExcepcionDelPrograma`): una operación sin resultado
  posible —dividir entre cero, un índice fuera de rango, un ``cast`` que no
  convierte—. Es una EXCEPCIÓN del programa, como en Python: el ``try`` más
  cercano la atrapa (``catch (excepciones.DivisionPorCero e)`` o
  ``catch (e)``); solo si nadie la atrapa termina el programa.
- ``RTxxx``: el programa está ROTO o la máquina no puede seguir (usar algo
  después de ``move``, agotar la pila, un destructor que lanza). No se
  atrapan: siempre terminan el programa.
"""

from __future__ import annotations

from typing import Optional


class SuriaXRuntimeError(Exception):
    """Base de todos los errores de ejecución del intérprete.

    ``severity`` (ver ``V0/error_handler/error.Severity``): un error de runtime
    corta la ejecución, así que por defecto es ``"critical"``; las violaciones
    de MEMORIA lo suben a ``"panic"`` (la clase más grave — es el error que el
    backend de memoria hace cumplir)."""

    code = "RT000"
    severity = "critical"

    def __init__(self, message: str, *, ln: int = 0, col: int = 0,
                 fn: Optional[str] = None, file: Optional[str] = None):
        self.message = message
        self.ln = ln
        self.col = col
        self.fn = fn
        #: archivo de la posición cuando NO es el programa principal (una
        #: librería). Lo pone el evaluador con :meth:`set_file`.
        self.file = file
        #: la unidad donde ocurrió (``loader.Unit``), una vez situado; ``None``
        #: mientras no se sepa. Lo usa el evaluador para no situarlo dos veces.
        self.unit = None
        super().__init__(self._texto())

    def _texto(self) -> str:
        # Con archivo, la posición sale como en los diagnósticos de una
        # librería al compilar: '(ruta:linea:col)'. Sin él (el programa
        # principal) sigue siendo '(linea:col)': el usuario sabe qué archivo
        # ejecutó, y lo que confundía era una línea de OTRO archivo.
        if self.fn:
            where = f" ({self.fn}:"
        elif self.file:
            where = f" ({self.file}:"
        else:
            where = " ("
        loc = f"{where}{self.ln}:{self.col})" if self.ln else ""
        return f"{self.code}: {self.message}{loc}"

    def set_file(self, unit, file: Optional[str]) -> "SuriaXRuntimeError":
        """Dice en qué unidad (y, si no es el programa, en qué archivo) está la
        posición del error, y rehace el texto. Solo la primera vez: quien
        sitúa primero es la sentencia más interna, la que falló."""
        if self.unit is None:
            self.unit = unit
            self.file = file
            self.args = (self._texto(),)
        return self

    def ubicar(self, ln: int, col: int) -> "SuriaXRuntimeError":
        """Pone la posición si el error no traía una y devuelve el mismo error.

        Un intrínseco del host no sabe desde dónde lo llamaron: su error nace
        sin posición y la pone quien hizo la llamada. Asignar ``ln`` a mano no
        bastaba: el texto del error ya estaba armado sin ella."""
        if not self.ln:
            self.ln, self.col = ln, col
            self.args = (self._texto(),)
        return self


class UseAfterMoveError(SuriaXRuntimeError):
    """Lectura de una celda cuyo valor fue transferido con ``move``."""
    code = "RT001"
    severity = "panic"


class DoubleMoveError(SuriaXRuntimeError):
    """``move`` sobre una celda ya movida."""
    code = "RT002"
    severity = "panic"


class UseAfterFreeError(SuriaXRuntimeError):
    """Acceso a una celda liberada con ``free`` (o a través de un puntero
    colgante hacia ella)."""
    code = "RT003"
    severity = "panic"


class NullDereferenceError(SuriaXRuntimeError):
    """Desreferencia (acceso a miembro/índice) de un valor ``null``."""
    code = "RT004"
    severity = "panic"


class InvalidFreeError(SuriaXRuntimeError):
    """``free`` sobre un valor que no es un puntero vivo."""
    code = "RT005"
    severity = "panic"


class UndefinedNameError(SuriaXRuntimeError):
    """Nombre no ligado en el environment (defensivo: la Semántica ya lo
    valida; si salta aquí hay una brecha del análisis estático)."""
    code = "RT006"


class NotCallableError(SuriaXRuntimeError):
    """Llamada sobre algo que no es función/hook/intrínseco."""
    code = "RT007"


class MissingIntrinsicError(SuriaXRuntimeError):
    """Un PROTOTIPO (fn sin cuerpo) no tiene intrínseco registrado en el
    host: el HIR es ejecutable solo si el host provee esa primitiva."""
    code = "RT008"


class MissingEntryError(SuriaXRuntimeError):
    """La función de entrada configurada no existe en el módulo principal."""
    code = "RT009"


class StepLimitError(SuriaXRuntimeError):
    """Se alcanzó ``interpreter.max_steps`` (guarda contra bucles infinitos)."""
    code = "RT010"


class MemoryLimitError(SuriaXRuntimeError):
    """El programa pasó la memoria máxima. En la VM, la de ``suriax-hir
    --memoria-max``, que contabiliza en bytes lo que el programa crea. El
    intérprete no lleva esa cuenta (sus valores son objetos de Python, cuyo
    tamaño no dice nada del programa): lo emite solo cuando una reserva no
    cabe en la memoria de la máquina."""
    code = "RT023"


class UnsupportedNodeError(SuriaXRuntimeError):
    """Nodo HIR sin soporte de ejecución todavía (parte del plan por fases)."""
    code = "RT011"


class ExcepcionDelPrograma(SuriaXRuntimeError):
    """Base de los errores de ejecución que el programa PUEDE ATRAPAR.

    El ``try`` del intérprete la recibe igual que un ``throw``: la convierte
    en un valor del struct ``excepciones.<tipo_excepcion>`` (declarado en
    ``lib/excepciones.libsrx``) con el mensaje y la posición, y la pasa por
    las mismas ramas ``catch``. Por eso la conversión vive en UN sitio (el
    ``try``) y no en cada ``raise``: quien detecta el fallo no necesita saber
    si alguien lo va a atrapar.
    """
    tipo_excepcion = ""


class InvalidCastRuntimeError(SuriaXRuntimeError):
    """``cast`` sin conversión resoluble en runtime (par no registrado).

    NO es atrapable: la Semántica ya rechaza toda conversión sin resultado
    (SEM016), así que llegar aquí indica un HIR inconsistente, no un
    programa que pueda recuperarse. Cuando exista una conversión que pueda
    fallar con un programa válido (``str`` -> ``int``), su fallo será una
    excepción del programa (``EXC004``)."""
    code = "RT012"


class IndexOutOfRangeError(ExcepcionDelPrograma):
    """``buf[i]`` con ``i`` fuera de ``[0, tamaño)`` (o no entero) sobre un
    bloque reservado con ``__reserve__``. Se atrapa como
    ``excepciones.IndiceFueraDeRango``: el acceso se COMPRUEBA antes de
    hacerse, así que la memoria sigue intacta y el programa puede seguir."""
    code = "EXC002"
    tipo_excepcion = "IndiceFueraDeRango"


class FileAccessError(ExcepcionDelPrograma):
    """Una operación de archivo de ``lib/sistema`` que no se pudo hacer: no
    existe, es una carpeta, no es UTF-8, falta permiso. Se atrapa como
    ``excepciones.ErrorDeArchivo``.

    El mensaje es CANÓNICO (no el ``strerror`` del sistema): el mismo texto
    en el intérprete y en la VM, en Windows y en Linux. El del sistema cambia
    con el idioma y la plataforma, y un programa que lo imprime daría otra
    salida en cada máquina."""
    code = "EXC003"
    tipo_excepcion = "ErrorDeArchivo"


class NotIndexableError(SuriaXRuntimeError):
    """``x[i]`` sobre un valor que no es un bloque reservable ni un puntero
    a uno (la indexación solo opera sobre memoria de ``__reserve__``)."""
    code = "RT014"


class CorruptMemoryHandleError(SuriaXRuntimeError):
    """El backend de memoria recibió un handle INVÁLIDO (``BAD_HANDLE``): una
    celda que no existe. No debería ocurrir con un HIR válido — indica una
    brecha del intérprete o del backend, no un error del programa usuario. Es
    ``panic`` por ser un fallo de integridad de memoria."""
    code = "RT015"
    severity = "panic"


class ConversionError(ExcepcionDelPrograma):
    """Un texto que no se puede convertir: ``text.parse_int("12a")``, unos
    bytes que no son UTF-8. Se atrapa como ``excepciones.ConversionInvalida``.
    El mensaje es canonico, el mismo en la VM."""
    code = "EXC004"
    tipo_excepcion = "ConversionInvalida"


class ShiftOutOfRangeError(ExcepcionDelPrograma):
    """``x << n`` o ``x >> n`` con ``n`` fuera de ``[0, 64)``.

    En C es comportamiento indefinido y en Python da un entero de otro
    tamaño; aqui no hay respuesta que dar con 64 bits, y el programa puede
    atraparlo (``excepciones.DesplazamientoInvalido``).
    """
    code = "EXC005"
    tipo_excepcion = "DesplazamientoInvalido"


class DivisionByZeroError(ExcepcionDelPrograma):
    """``a / 0`` o ``a % 0``.

    Existe porque el fallo salia como un ``ZeroDivisionError`` de Python: un
    traceback del intérprete en vez de un diagnóstico del lenguaje, sin
    posición y sin decirle al usuario que su programa dividió por cero. Un
    error del programa se reporta como tal; un traceback es un fallo del
    compilador, y confundirlos hace imposible saber cuál de los dos pasó.

    Se atrapa como ``excepciones.DivisionPorCero``. Una división por un cero
    LITERAL (``x / 0``) ni siquiera compila: SEM035.
    """
    code = "EXC001"
    tipo_excepcion = "DivisionPorCero"


class MissingReturnError(SuriaXRuntimeError):
    """Una función con tipo de retorno terminó SIN devolver nada.

    Antes devolvía ``null`` en silencio: un ``fn f() -> int`` entregaba un
    valor que no es un ``int`` a un lenguaje que no tiene coerciones
    implícitas ni inferencia, y el error aparecía como un ``null`` impreso a
    tres funciones de distancia.

    Es de EJECUCIÓN y no de compilación a propósito: decidir estáticamente si
    todos los caminos devuelven exige tratar los bucles que no terminan como
    divergentes, y sin eso un ``while`` infinito legítimo se rechazaría. El
    contrato de cero falsos positivos manda; aquí el fallo se reporta donde
    ocurre, con su posición.
    """
    code = "RT017"


class ExternBoundaryError(SuriaXRuntimeError):
    """Un valor no puede cruzar la frontera de ``#extern``.

    No todo lo que existe en suriaX tiene una representación de máquina que
    C++ pueda leer: un bloque de ``str`` es una lista de objetos, no un
    buffer contiguo. Decirlo con el porqué es la diferencia entre un
    diagnóstico y un volcado de pila de Python.

    Es de EJECUCIÓN porque el tipo del prototipo sí es válido —``str ptr``
    existe— y lo que falla es el CONTENIDO del bloque, que solo se conoce al
    llamar.
    """
    code = "RT018"


class StackOverflowError(SuriaXRuntimeError):
    """Desbordamiento de pila: demasiadas llamadas anidadas.

    Casi siempre es una recursión sin caso base. Antes el intérprete dejaba
    escapar el ``RecursionError`` de Python y salía como error INTERNO del
    compilador (ICE000), diciendo "no es un fallo de tu programa" cuando la
    causa estaba justo en el programa.

    El límite NO es un número fijo: lo pone la pila de Python, y cada llamada
    de suriaX gasta más o menos marcos según cuánto anida su cuerpo (medido:
    entre ~600 y ~1400 llamadas). La VM de C++ tiene su propio límite
    (``kMaxDepth`` = 4096 marcos). El error dice la profundidad alcanzada
    para que se vea que no es un número mágico.
    """
    code = "RT019"


class UncaughtThrowError(SuriaXRuntimeError):
    """Un ``throw`` escapó de todo ``try``/``catch`` y terminó el programa.

    No es un fallo del intérprete: es el programa terminando mal, con el valor
    que lanzó. Era el único error de ejecución que salía SIN código estable
    ("error no capturado — throw x"), así que un editor o una prueba no podía
    distinguirlo sin leer el texto.
    """
    code = "RT020"


class DestructorThrewError(SuriaXRuntimeError):
    """Un ``__free__`` lanzó: un destructor NUNCA puede fallar.

    Es la regla de C++ (los destructores son ``noexcept`` desde C++11). La
    razón se ve en el desenrollado: si un ``throw`` ya está subiendo y, al
    destruir lo que deja atrás, un ``__free__`` lanza OTRO, habría dos
    excepciones en vuelo y el ``catch`` solo puede recibir una. Antes la
    segunda reemplazaba a la primera sin decir nada —un error oculto—. Es,
    de cierto modo, un "move después de move" de la excepción.

    Un ``throw`` escrito directamente en un ``__free__`` ya lo rechaza la
    Semántica (SEM034); este error cubre el caso que no se ve al compilar:
    el ``__free__`` llama a una función que lanza. Siempre termina el
    programa: no se puede atrapar.
    """
    code = "RT021"


class FinallyThrewError(SuriaXRuntimeError):
    """Un ``finally`` lanzó mientras ya viajaba otra excepción.

    El ``finally`` corría PORQUE una excepción estaba saliendo del ``try``. Si
    el ``finally`` lanza otra, habría dos en vuelo y el ``catch`` de afuera
    solo puede recibir una: la primera se perdería sin rastro. Es la misma
    regla que ``RT021`` (un destructor que lanza durante un desenrollado).
    Siempre termina el programa: no se puede atrapar.
    """
    code = "RT022"


__all__ = [
    "SuriaXRuntimeError", "ExcepcionDelPrograma", "UseAfterMoveError", "DoubleMoveError",
    "UseAfterFreeError", "NullDereferenceError", "InvalidFreeError",
    "UndefinedNameError", "NotCallableError", "MissingIntrinsicError",
    "MissingEntryError", "StepLimitError", "UnsupportedNodeError",
    "InvalidCastRuntimeError", "IndexOutOfRangeError", "NotIndexableError",
    "FileAccessError",
    "CorruptMemoryHandleError", "DivisionByZeroError", "ShiftOutOfRangeError",
    "MissingReturnError", "ExternBoundaryError", "StackOverflowError",
    "UncaughtThrowError", "DestructorThrewError", "FinallyThrewError",
]
