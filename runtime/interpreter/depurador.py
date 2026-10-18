"""El depurador del intérprete: parar, mirar y seguir.

Este módulo NO sabe de protocolos ni de editores. Es el núcleo: decide cuándo
se detiene el programa y sabe contar lo que hay en ese momento. Quien lo usa
(``dap.py`` para un editor, una prueba, mañana una consola) le da una función
``al_parar`` y él la llama cada vez que el programa se detiene; el programa
sigue cuando esa función vuelve.

Por qué sobre el intérprete: todas las sentencias pasan por un único punto
(``Evaluator.exec_stmt``) que ya tiene la posición en el fuente y el marco con
las variables. El depurador se engancha ahí y en ``call_function``; con el
depurador apagado, el coste es una comparación por sentencia.

Lo que lo hace de suriaX es la columna de **propiedad**. Cada variable vive en
una celda que ya lleva su estado —es la misma que hace cumplir el
use-after-move y el use-after-free—, así que el depurador puede decir, de cada
nombre, si el valor sigue siendo suyo:

    dueña     la variable posee su valor
    prestada  es un puntero: mira (o muta) el valor de otra
    movida    cedió su valor con 'move'; usarla es un error
    liberada  se liberó con 'free'; usarla es un error
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

from .memory.block import Block
from .memory.pointer import CellState, Pointer
from .values import EnumValue, StructValue, format_value

#: por qué se detuvo el programa (los nombres son los del protocolo DAP, que
#: es quien los popularizó; aquí son solo etiquetas).
ENTRADA = "entry"
PUNTO = "breakpoint"
PASO = "step"
PAUSA = "pause"
ERROR = "exception"

#: cuándo detenerse por un error del programa
SIN_ATRAPAR = "sin-atrapar"     # solo si ningún 'catch' lo va a recibir
TODOS = "todos"                 # en cuanto ocurre, lo atrapen o no

DUENA = "dueña"
PRESTADA = "prestada"
MOVIDA = "movida"
LIBERADA = "liberada"

_MODULO = "<módulo>"


def misma_ruta(ruta: str) -> str:
    """Una ruta en la forma en que se comparan: absoluta, con las barras del
    sistema y, donde el sistema no distingue mayúsculas, en minúsculas. El
    editor y el compilador escriben la misma ruta de formas distintas."""
    return os.path.normcase(os.path.abspath(ruta))


class Marco:
    """Una llamada en curso: qué función, de qué unidad y por dónde va."""

    __slots__ = ("unidad", "nombre", "raiz", "frame", "linea", "columna")

    def __init__(self, unidad, nombre: str, raiz) -> None:
        self.unidad = unidad
        self.nombre = nombre
        #: el marco de la función (parámetros y locales del cuerpo)
        self.raiz = raiz
        #: el marco del bloque que se está ejecutando AHORA: lo que hay a la
        #: vista son sus nombres y los de sus padres hasta ``raiz``.
        self.frame = raiz
        self.linea = 0
        self.columna = 0


class Variable:
    """Un nombre a la vista, con su valor escrito y su estado de propiedad."""

    __slots__ = ("nombre", "valor", "propiedad", "contenido")

    def __init__(self, nombre: str, valor: str, propiedad: str, contenido: Any) -> None:
        self.nombre = nombre
        self.valor = valor
        self.propiedad = propiedad
        #: el valor de verdad, para desplegarlo (``hijos``); None si no tiene
        #: nada dentro o si ya no se puede leer.
        self.contenido = contenido


def _de_celda(nombre: str, celda) -> Variable:
    estado = celda.state
    if estado is CellState.MOVED:
        return Variable(nombre, "(movida)", MOVIDA, None)
    if estado is CellState.FREED:
        return Variable(nombre, "(liberada)", LIBERADA, None)
    valor = celda.value
    propiedad = PRESTADA if isinstance(valor, Pointer) else DUENA
    return Variable(nombre, format_value(valor), propiedad,
                    valor if _tiene_hijos(valor) else None)


def _tiene_hijos(valor: Any) -> bool:
    if isinstance(valor, StructValue):
        return bool(valor.fields)
    if isinstance(valor, EnumValue):
        return bool(valor.fields)
    return isinstance(valor, (Pointer, Block))


def hijos(valor: Any) -> List[Variable]:
    """Lo que hay DENTRO de un valor: los campos de un struct, los datos de
    una variante, las celdas de un bloque o aquello a lo que apunta un
    puntero. Cada uno con su propio estado: un campo se puede mover solo."""
    if isinstance(valor, StructValue):
        return [_de_celda(nombre, celda) for nombre, celda in valor.fields.items()]
    if isinstance(valor, EnumValue):
        return [Variable(str(i), format_value(dato), DUENA,
                         dato if _tiene_hijos(dato) else None)
                for i, dato in enumerate(valor.fields)]
    if isinstance(valor, Pointer):
        return [_de_celda("*", valor.cell)]
    if isinstance(valor, Block):
        return [_de_celda(f"[{i}]", celda) for i, celda in enumerate(valor.cells)]
    return []


class Depurador:
    """Decide cuándo parar. Un ``Evaluator`` con un depurador lo consulta en
    cada sentencia y en cada llamada."""

    def __init__(self, al_parar: Callable[["Depurador", str], None], *,
                 parar_al_entrar: bool = False) -> None:
        self.al_parar = al_parar
        #: ruta normalizada -> líneas con punto de parada
        self.puntos: Dict[str, set] = {}
        self.pila: List[Marco] = []
        self._modulo: Optional[Marco] = None
        self._rutas: Dict[int, str] = {}
        # cómo seguir: None = hasta el próximo punto; si no, un paso
        self._paso: Optional[str] = ENTRADA if parar_al_entrar else None
        self._hondo = 0                 # profundidad de la pila al pedir el paso
        self._linea = (None, 0)         # (ruta, línea) donde se pidió
        self._pausa = False
        # la última sentencia vista en cada profundidad: para no parar dos
        # veces en la misma línea al avanzar por ella.
        self._previa: Dict[int, tuple] = {}
        #: el marco donde está detenido AHORA; None mientras el programa corre
        self.detenido_en: Optional[Marco] = None
        #: en qué errores parar: None, SIN_ATRAPAR o TODOS
        self.errores: Optional[str] = None
        #: mientras está detenido POR un error: (código, descripción)
        self.error: Optional[tuple] = None
        # cuántos 'try' con algún 'catch' hay abiertos ahora mismo: si es
        # cero, lo que se lance no lo recibe nadie.
        self._intentos = 0
        self._visto = None              # el error ya avisado, mientras sube

    # ------------------------------------------------------------------ #
    # lo que pide quien depura
    # ------------------------------------------------------------------ #
    def pon_puntos(self, ruta: str, lineas) -> None:
        """Sustituye los puntos de parada de un archivo."""
        clave = misma_ruta(ruta)
        if lineas:
            self.puntos[clave] = {int(n) for n in lineas}
        else:
            self.puntos.pop(clave, None)

    def sigue(self) -> None:
        """Hasta el próximo punto de parada."""
        self._paso = None

    def paso(self, clase: str) -> None:
        """Un paso: ``"entrar"`` (a la siguiente sentencia, esté donde esté),
        ``"pasar"`` (a la siguiente de esta función, sin entrar en las que
        llame) o ``"salir"`` (hasta volver a quien llamó)."""
        if clase not in ("entrar", "pasar", "salir"):
            raise ValueError(f"paso desconocido: {clase}")
        self._paso = clase
        self._hondo = len(self.pila)
        actual = self.detenido_en
        self._linea = ((self.ruta_de(actual.unidad), actual.linea)
                       if actual is not None else (None, 0))

    def pausa(self) -> None:
        """Parar en la siguiente sentencia. Se puede pedir desde otro hilo."""
        self._pausa = True

    def para_en_errores(self, cuales: Optional[str]) -> None:
        """``SIN_ATRAPAR``: detenerse cuando el programa va a terminar por un
        error. ``TODOS``: en cuanto se lanza cualquiera. ``None``: nunca."""
        if cuales not in (None, SIN_ATRAPAR, TODOS):
            raise ValueError(f"filtro de errores desconocido: {cuales}")
        self.errores = cuales

    # ------------------------------------------------------------------ #
    # lo que avisa el intérprete
    # ------------------------------------------------------------------ #
    def entra(self, unidad, decl, frame) -> None:
        self.pila.append(Marco(unidad, decl.name, frame))

    def sale(self) -> None:
        self._previa.pop(len(self.pila), None)
        self.pila.pop()

    def en_sentencia(self, unidad, stmt, frame) -> None:
        if self.pila:
            marco = self.pila[-1]
        else:
            # sentencias de nivel de módulo: corren antes de 'main', sin
            # llamada que las contenga.
            if self._modulo is None or self._modulo.unidad is not unidad:
                self._modulo = Marco(unidad, _MODULO, frame)
            marco = self._modulo
        marco.frame = frame
        marco.linea, marco.columna = stmt.ln, stmt.col

        hondo = len(self.pila)
        ruta = self.ruta_de(unidad)
        previa = self._previa.get(hondo)
        self._previa[hondo] = (ruta, stmt.ln, stmt.col)
        # ¿es la misma línea, más adelante? Entonces no es "llegar" a ella.
        avanza = (previa is not None and previa[0] == ruta
                  and previa[1] == stmt.ln and stmt.col > previa[2])

        motivo = None
        if self._pausa:
            motivo = PAUSA
        elif self._paso == ENTRADA:
            motivo = ENTRADA
        elif stmt.ln in self.puntos.get(ruta, ()) and not avanza:
            motivo = PUNTO
        elif self._paso is not None and self._toca_parar(hondo, ruta, stmt.ln):
            motivo = PASO
        if motivo is None:
            return
        self._pausa = False
        self._paso = None
        self.detenido_en = marco
        self.al_parar(self, motivo)
        self.detenido_en = None

    def entra_try(self) -> None:
        self._intentos += 1

    def sale_try(self) -> None:
        self._intentos -= 1

    def en_error(self, fallo, atrapable: bool, codigo: str, descripcion: str,
                 unidad, stmt, frame) -> None:
        """El programa acaba de fallar en ``stmt``. Se detiene AQUÍ, con la
        pila y las variables intactas: cuando el error llega arriba del todo
        ya no queda nada que mirar.

        ``atrapable``: un ``throw`` o una excepción del programa, que un
        ``catch`` puede recibir. Un error de memoria (uso tras ``move``) no
        lo es: termina el programa siempre.
        """
        if self.errores is None or fallo is self._visto:
            return                      # el mismo error, subiendo por la pila
        self._visto = fallo
        if self.errores == SIN_ATRAPAR and atrapable and self._intentos > 0:
            return                      # hay un 'catch' esperándolo
        marco = self.pila[-1] if self.pila else self._modulo
        if marco is None:
            marco = self._modulo = Marco(unidad, _MODULO, frame)
        marco.frame = frame
        marco.linea, marco.columna = stmt.ln, stmt.col
        self.detenido_en = marco
        self.error = (codigo, descripcion)
        try:
            self.al_parar(self, ERROR)
        finally:
            self.error = None
            self.detenido_en = None

    def _toca_parar(self, hondo: int, ruta: str, linea: int) -> bool:
        otra_linea = (ruta, linea) != self._linea
        if self._paso == "entrar":
            return otra_linea or hondo != self._hondo
        if self._paso == "pasar":
            return hondo < self._hondo or (hondo == self._hondo and otra_linea)
        return hondo < self._hondo          # salir

    # ------------------------------------------------------------------ #
    # lo que se puede mirar mientras está detenido
    # ------------------------------------------------------------------ #
    def fija_ruta(self, unidad, ruta: str) -> None:
        """Dice cuál es el fuente de una unidad. Quien compiló el programa lo
        sabe con certeza; ``fuente_de`` solo lo deduce."""
        self._rutas[id(unidad)] = misma_ruta(ruta)

    def ruta_de(self, unidad) -> str:
        """El archivo fuente de una unidad, en la forma en que se comparan."""
        clave = id(unidad)
        if clave not in self._rutas:
            self._rutas[clave] = misma_ruta(fuente_de(unidad))
        return self._rutas[clave]

    def marcos(self) -> List[Marco]:
        """La pila de llamadas, la más reciente primero."""
        pila = list(reversed(self.pila))
        if not pila and self._modulo is not None:
            pila = [self._modulo]
        return pila

    @staticmethod
    def locales(marco: Marco) -> List[Variable]:
        """Los nombres a la vista en el marco: del bloque actual hacia fuera,
        hasta los parámetros. Un nombre que tapa a otro sale una vez."""
        vistos: Dict[str, Variable] = {}
        frame = marco.frame
        limite = marco.raiz.parent
        while frame is not None and frame is not limite:
            for nombre, celda in frame.cells.items():
                if nombre not in vistos:
                    vistos[nombre] = _de_celda(nombre, celda)
            frame = frame.parent
        return list(vistos.values())

    @staticmethod
    def globales(marco: Marco) -> List[Variable]:
        """Las variables de nivel superior de la unidad del marco. Las
        funciones, los tipos y los módulos importados no son variables."""
        frame = marco.unidad.globals_frame
        if frame is None:
            return []
        return [_de_celda(nombre, celda) for nombre, celda in frame.cells.items()
                if celda.state is not CellState.LIVE or _es_dato(celda.value)]

    def busca(self, marco: Marco, nombre: str) -> Optional[Variable]:
        """El valor de un nombre a la vista (para un panel de inspección)."""
        for variable in self.locales(marco) + self.globales(marco):
            if variable.nombre == nombre:
                return variable
        return None


def _es_dato(valor: Any) -> bool:
    from .values import EnumNamespace, FunctionValue, Namespace, TypeValue, VariantCtor
    return not isinstance(valor, (FunctionValue, Namespace, TypeValue,
                                  EnumNamespace, VariantCtor))


def fuente_de(unidad) -> str:
    """El archivo fuente de una unidad cargada.

    El módulo guarda su ruta PÚBLICA (``<stdlib>/io/stdp.libsrx``, o relativa
    a la raíz del proyecto) para que el ``.phir`` sea reproducible; aquí se
    deshace, porque un punto de parada se pone sobre un archivo de verdad.
    """
    publica = unidad.module.source_file or unidad.path
    if os.path.isabs(publica):
        return publica
    try:
        from V0.src.linker_p.resolver import PREFIJO_STDLIB, stdlib_path
    except ImportError:         # el intérprete suelto, sin el compilador
        PREFIJO_STDLIB, stdlib_path = "<stdlib>/", lambda: None
    if publica.startswith(PREFIJO_STDLIB):
        base = stdlib_path()
        if base:
            return os.path.join(base, publica[len(PREFIJO_STDLIB):])
    # relativa: junto al .phir de la unidad o, si no está, tal cual
    junto = os.path.join(os.path.dirname(os.path.abspath(unidad.path)), publica)
    return junto if os.path.isfile(junto) else publica


__all__ = ["Depurador", "Marco", "Variable", "hijos", "misma_ruta", "fuente_de",
           "ENTRADA", "PUNTO", "PASO", "PAUSA", "ERROR",
           "SIN_ATRAPAR", "TODOS",
           "DUENA", "PRESTADA", "MOVIDA", "LIBERADA"]
