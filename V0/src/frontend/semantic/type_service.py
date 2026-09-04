"""Servicio de consulta de tipos: el punto de enganche de la futura Fase 3.

``DESIGN_PRINCIPLES.md`` secc. 7: *"el sistema de tipos no es una fase, es
un servicio"*. Las pasadas (``type_resolver``/``scope_resolver``) NUNCA
comparan ``Type`` a mano: consultan estas funciones. Cuando la Fase 3
(sistema de tipos real: coerciones, genéricos, unificación de nullables)
aterrice, se reemplaza la implementación de ESTE archivo sin tocar a ningún
llamador — ver ``ARQUITECTURA.md`` secc. 5 para la justificación de costo.

Implementación mínima de hoy: identidad estructural estricta (``Type`` es un
dataclass frozen: ``==`` compara estructura), más las dos únicas reglas que
el lenguaje ya necesita (``null`` -> nullable, ``T`` -> ``T?``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Tuple

try:
    from include.types_ast import Type, TypeKind
except ImportError:  # pragma: no cover - ejecucion directa
    from types_ast import Type, TypeKind  # type: ignore

from .hooks import HookKind
from .symbol_table import Scope, Symbol, SymbolKind, SymbolTable

# los tres SymbolKind que nombran un TIPO utilizable en una anotacion.
# 'TYPE' es el tipo nominal opaco de una libreria ('const type int8;'): para
# el consumidor es indistinguible de un struct — de eso se trata.
_TYPE_KINDS = frozenset({SymbolKind.STRUCT, SymbolKind.ENUM, SymbolKind.TYPE})


class TypeLookup(Enum):
    """Resultado de :func:`lookup_type_path` (por que fallo, no solo si fallo)."""
    OK = auto()
    NOT_FOUND = auto()    # el nombre (o la raiz del camino) no existe
    NO_MEMBER = auto()    # el modulo existe pero no publica ese miembro
    NOT_A_TYPE = auto()   # el miembro existe pero no nombra un tipo
    OPAQUE = auto()       # viene de una libreria que no se pudo cargar


@dataclass(slots=True, frozen=True)
class TypeLookupResult:
    status: TypeLookup
    symbol: Optional[Symbol] = None
    owner: str = ""      # prefijo que SI resolvio ('dt' en 'dt.uint8')
    missing: str = ""    # componente que fallo ('uint8')
    available: Tuple[str, ...] = field(default=())  # tipos que el owner si publica


def resolve_nominal(name: str, scope: Scope) -> Optional[Symbol]:
    """Busca ``name`` en el namespace de TIPOS, caminando la cadena de scopes.

    Solo nombres SIMPLES; para los cualificados (``dt.int8``) usa
    :func:`lookup_type_path`, que además explica los fallos.
    """
    return scope.resolve_type(name)


def lookup_type_path(name: str, scope: Scope) -> TypeLookupResult:
    """Resuelve un nombre de tipo, simple (``Punto``) o CUALIFICADO (``dt.int8``).

    Un nombre cualificado atraviesa el namespace de VALORES en su raíz (un
    módulo importado es un valor) y luego desciende por ``Symbol.members``,
    que es un dict plano: cada salto es O(1), sin recorrer scopes.

    Camino rápido: sin puntos —el caso común— no se parte el string ni se
    construye ninguna lista; es una sola búsqueda en la cadena de scopes.
    """
    if "." not in name:
        symbol = scope.resolve_type(name)
        if symbol is None:
            return TypeLookupResult(TypeLookup.NOT_FOUND, missing=name)
        return TypeLookupResult(TypeLookup.OK, symbol)

    parts = name.split(".")
    current = scope.resolve_value(parts[0])
    if current is None:
        return TypeLookupResult(TypeLookup.NOT_FOUND, missing=parts[0])

    for i, part in enumerate(parts[1:], 1):
        members = current.members
        if members is None:
            if current.kind is SymbolKind.IMPORT:
                # import OPACO: la libreria no cargo y ya se reporto una vez.
                # Callar aqui evita una cascada de errores derivados por cada
                # uso del modulo (mismo criterio que 'collect.define_import').
                return TypeLookupResult(TypeLookup.OPAQUE)
            return TypeLookupResult(
                TypeLookup.NO_MEMBER, owner=".".join(parts[:i]), missing=part,
            )
        nxt = members.get(part)
        if nxt is None:
            return TypeLookupResult(
                TypeLookup.NO_MEMBER, owner=".".join(parts[:i]), missing=part,
                available=_type_names(members),
            )
        current = nxt

    if current.kind not in _TYPE_KINDS:
        return TypeLookupResult(TypeLookup.NOT_A_TYPE, current,
                                owner=".".join(parts[:-1]), missing=parts[-1])
    return TypeLookupResult(TypeLookup.OK, current)


def canonical_name(symbol: Symbol, written: str = "") -> str:
    """Nombre CANONICO del tipo que declara ``symbol``.

    El usuario escribe ``dt.int8``; la libreria registro sus hooks y sus
    conversiones bajo el nombre con el que DECLARO el tipo (``int8``). Sin
    esta traduccion el par no se encuentra y el tipo queda inservible fuera
    de su libreria.

    ``Symbol.type_name`` es la fuente cuando el simbolo declara un tipo: lo
    fija ``collect`` ya calificado con su unidad, y sirve igual para un
    struct/enum que para un alias ``const type int8`` — cuyo ``Symbol.type``
    es el metatipo y no un nominal del que sacar el nombre.

    Para los que no lo traen (parametros de tipo, simbolos importados) se
    cae a ``Symbol.type`` si es nominal y luego a ``Symbol.name``.
    ``written`` es la ultima red si el simbolo no trae ninguno.
    """
    if symbol.type_name:
        return symbol.type_name
    t = symbol.type
    if t is not None and t.kind is TypeKind.NOMINAL:
        return t.name
    return symbol.name or written


def canonical(t: Optional[Type], scope: Scope) -> Optional[Type]:
    """Reescribe el NUCLEO nominal de ``t`` con su nombre canonico.

    ``dt.int8 ptr`` -> ``dt_variables.int8 ptr``, y tambien al reves: dentro
    de la libreria que lo declara, ``int8`` -> ``dt_variables.int8``. Los
    envoltorios (``ptr``/``?``/``error``) y los argumentos de un generico se
    conservan, canonicalizando tambien los argumentos — ``Vector<Node>`` y
    ``Vector<a.Node>`` tienen que dar el mismo tipo o el generico volveria a
    unificar lo que no debe.

    NO se puede atajar por "no lleva punto": la calificacion se AÑADE tanto
    como se quita desde que un tipo se llama ``a.Node`` tambien dentro de
    ``a`` (ver ``SemanticContext.qualify``).
    """
    if t is None:
        return None
    if t.kind is TypeKind.NOMINAL:
        result = lookup_type_path(t.name, scope)
        if result.status is not TypeLookup.OK or result.symbol is None:
            return t
        name = canonical_name(result.symbol, t.name)
        args = tuple(canonical(a, scope) for a in t.args)
        if name == t.name and all(x is y for x, y in zip(args, t.args)):
            return t
        return Type(TypeKind.NOMINAL, name=name, args=args)
    if t.inner is None:
        return t
    inner = canonical(t.inner, scope)
    if inner is t.inner:
        return t
    return Type(t.kind, name=t.name, inner=inner, mut=t.mut)


def substitute(t: Optional[Type], mapa: dict) -> Optional[Type]:
    """Reemplaza los PARAMETROS de tipo de ``t`` por sus argumentos.

    Es lo que convierte la declaracion de un generico en un tipo concreto: el
    campo ``T ptr mutable`` de un ``Vector<T>``, visto a traves de un
    ``Vector<int>``, es ``int ptr mutable``. Sin esto los genericos serian
    sintaxis sin significado — el consumidor escribiria ``Vector<int>`` y el
    compilador seguiria viendo ``T``.

    Recorre los envoltorios (``ptr``/``?``/``error``) y los argumentos de un
    generico anidado (``Vector<Vector<T>>``). ``Type`` es frozen, asi que
    reconstruye solo lo que cambia: si no hay nada que sustituir devuelve el
    MISMO objeto, que es el caso de casi todos los tipos de un programa.
    """
    if t is None or not mapa:
        return t
    if t.kind is TypeKind.NOMINAL:
        if not t.args:
            reemplazo = mapa.get(t.name)
            return reemplazo if reemplazo is not None else t
        args = tuple(substitute(a, mapa) for a in t.args)
        return t if args == t.args else Type(TypeKind.NOMINAL, name=t.name,
                                             args=args)
    if t.inner is None:
        return t
    inner = substitute(t.inner, mapa)
    if inner is t.inner:
        return t
    return Type(t.kind, name=t.name, inner=inner, mut=t.mut)


def bindings(symbol: Symbol, t: Optional[Type]) -> dict:
    """Mapa ``parametro -> argumento`` de un uso concreto de un generico.

    Vacio si el tipo no es generico, que es lo que hace que :func:`substitute`
    salga por el camino rapido en la inmensa mayoria de los casos.
    """
    if not symbol.type_params or t is None or not t.args:
        return {}
    return dict(zip(symbol.type_params, t.args))


def owns_resources(t: Optional[Type], scope: Scope, table: SymbolTable) -> bool:
    """¿Un valor de tipo ``t`` tiene una obligación de destrucción?

    Es la noción CENTRAL del modelo de memoria (``ownership + drop + arenas``,
    ver ``documentation/source/memory_model.rst``): responde qué valores el
    compilador tendrá que destruir al cerrar el ámbito que los posee. Sin esta
    pregunta el drop automático no se puede escribir — tendría que invocar un
    destructor sobre todo, o sobre nada.

    Tres reglas, y la primera es la que sostiene a las otras dos:

    1. **Un ``ptr T`` NO posee.** Es un préstamo: apunta a algo cuyo dueño está
       en otra parte. Destruir un puntero al salir de ámbito destruiría el
       valor de otro. Esto es también lo que hace que la recursión TERMINE: un
       ``struct Nodo { Nodo ptr sig; }`` se cierra sobre sí mismo a través de
       un puntero, y ahí la respuesta es "no" sin mirar más.
    2. **Un tipo nominal posee si declara ``__free__``.** Es la declaración
       explícita de que tiene algo que soltar. Vale igual para un tipo OPACO de
       una librería (``const type T;``): sus campos no se ven, pero su
       ``__free__`` viaja en la tabla de hooks y es su contrato completo.
    3. **Un ``struct`` posee si algún campo POR VALOR posee**, aunque él no
       declare ``__free__``: contener un dueño es ser dueño.

    ``T?`` y ``error T`` son envoltorios: poseen si lo que envuelven posee.
    Los primitivos nunca poseen.

    Un nombre que no resuelve devuelve ``False``: no se inventa una obligación
    sobre un tipo que no se pudo ver — el diagnóstico de que el nombre no
    existe ya lo da quien resolvió el scope.
    """
    return _posee(t, scope, table, set())


def _posee(t: Optional[Type], scope: Scope, table: SymbolTable,
           visitados: set) -> bool:
    if t is None:
        return False
    kind = t.kind
    if kind is TypeKind.POINTER:
        return False                      # prestamo, no dueno (regla 1)
    if kind is TypeKind.NULLABLE or kind is TypeKind.ERROR:
        return _posee(t.inner, scope, table, visitados)
    if kind is not TypeKind.NOMINAL or t.name is None:
        return False

    simbolo = lookup_type_path(t.name, scope).symbol
    if simbolo is None:
        return False
    if table.lookup_hook(simbolo.name, HookKind.FREE) is not None:
        return True                       # lo declara (regla 2)
    if simbolo.kind is not SymbolKind.STRUCT or not simbolo.members:
        return False

    # 'visitados' guarda contra un struct que se contenga a si mismo POR VALOR
    # ('struct { S s; } S;'): es un tipo de tamano infinito y no deberia
    # existir, pero esta pasada no es quien lo rechaza y no puede colgarse por
    # ello. La recursion normal (a traves de punteros) ya paro en la regla 1.
    #
    # La clave es el TIPO, no su nombre: 'Caja<int>' y 'Caja<R>' comparten
    # nombre y son tipos distintos, asi que marcar por nombre habria cortado
    # el recorrido de 'Caja<Caja<R>>' en el nivel de fuera y perdido el
    # destructor de dentro.
    if t in visitados:
        return False
    visitados.add(t)
    # Regla 3 SOBRE EL TIPO CONCRETO: el campo de un generico se declara como
    # 'T' y 'T' no resuelve a nada; sin sustituir, 'Caja<R>' no poseia nada
    # aunque 'R' tuviera '__free__', y su destructor no se ejecutaba nunca.
    # Es la misma sustitucion que hace falta para leer cualquier campo suyo.
    mapa = bindings(simbolo, t)
    return any(_posee(substitute(campo.type, mapa), scope, table, visitados)
               for campo in simbolo.members.values())


def infinite_size_path(name: str, scope: Scope) -> Optional[Tuple[str, ...]]:
    """El camino de campos que hace de ``name`` un tipo de tamaño INFINITO, o
    ``None`` si tiene tamaño finito.

    ``struct { S s; } S;`` no cabe en ninguna cantidad de memoria: cada ``S``
    contendría otro. Lo mismo entre varios (``A`` contiene ``B``, ``B``
    contiene ``A``).

    La distinción que decide es la MISMA que gobierna la propiedad
    (:func:`owns_resources`): un puntero **no contiene**, se refiere. Por eso
    ``struct { S ptr sig; } S;`` es legítimo y es como se escribe una lista.
    Y por eso este recorrido termina: solo baja por campos POR VALOR.

    Devuelve el camino (``("s",)``, ``("b", "a")``) para que el diagnóstico
    pueda señalar por dónde se cierra el ciclo, no solo que existe.
    """
    return _camino_infinito(Type(TypeKind.NOMINAL, name=name), scope, name,
                            (), set())


def _camino_infinito(actual: Optional[Type], scope: Scope, objetivo: str,
                     ruta: Tuple[str, ...],
                     vistos: set) -> Optional[Tuple[str, ...]]:
    """``ruta`` son los CAMPOS recorridos; ``vistos``, los TIPOS ya abiertos.

    Son dos cosas distintas y antes eran una sola: la guarda comparaba el
    nombre de un TIPO contra la lista de nombres de CAMPO, así que un ciclo
    ajeno al objetivo (``A`` -> ``B`` -> ``C`` -> ``B``) no se detenía y el
    recorrido se colgaba salvo que campo y tipo se llamaran igual.
    """
    if actual is None or actual.name is None:
        return None
    simbolo = resolve_nominal(actual.name, scope)
    if simbolo is None or simbolo.kind is not SymbolKind.STRUCT:
        return None
    if actual in vistos:
        return None           # otro ciclo, ajeno a 'objetivo': lo reporta el suyo
    vistos = vistos | {actual}
    # El campo de un generico se declara como 'T': sin sustituir, un ciclo que
    # pasa POR el generico ('struct { Caja<S> c; } S;') era invisible y el
    # tipo de tamano infinito se aceptaba.
    mapa = bindings(simbolo, actual)
    for campo in (simbolo.members or {}).values():
        t = substitute(campo.type, mapa)
        while t is not None and (t.kind is TypeKind.NULLABLE
                                 or t.kind is TypeKind.ERROR):
            t = t.inner
        if t is None or t.kind is not TypeKind.NOMINAL or t.name is None:
            continue          # primitivo, puntero: tamano conocido
        if t.name == objetivo:
            return ruta + (campo.name,)
        hallado = _camino_infinito(t, scope, objetivo, ruta + (campo.name,),
                                   vistos)
        if hallado is not None:
            return hallado
    return None


def _type_names(members) -> Tuple[str, ...]:
    """Los miembros que nombran un tipo, para el '(disponibles: ...)' del error."""
    return tuple(sorted(
        n for n, s in members.items() if s.kind in _TYPE_KINDS
    ))


def _leaf(name: Optional[str]) -> Optional[str]:
    """El último componente de un nombre nominal (``point.Point`` -> ``Point``)."""
    return name.rsplit(".", 1)[-1] if name else name


def _same_nominal(a: Optional[Type], b: Optional[Type]) -> bool:
    """¿``a`` y ``b`` son el MISMO tipo nominal?

    Por nombre COMPLETO, y ahí está la identidad: un tipo declarado en una
    librería se llama ``a.Node`` en todo el pipeline —dentro de su propia
    unidad también— porque ``SemanticContext.qualify`` lo califica al
    declararlo. Los dos lados llegan ya canónicos, así que no hay
    calificación que perdonar.

    Antes se comparaba el nombre-HOJA, porque la librería declaraba ``Node``
    y el consumidor escribía ``a.Node``: eso resolvía la asimetría, pero
    unificaba también los ``Node`` de DOS librerías distintas — y como los
    hooks, las conversiones y los dunders se indexan por ese nombre, el
    ``__free__`` que corría dependía del orden de carga, en silencio.

    Los ARGUMENTOS de un genérico entran en la comparación y lo hacen
    INVARIANTE: ``Vector<int>`` y ``Vector<str>`` comparten nombre y aun
    así son tipos distintos. Sin esta parte el genérico sería decorativo —
    ``Vector<T>`` daría una garantía que el checker no comprueba.
    """
    return (a is not None and b is not None
            and a.kind is TypeKind.NOMINAL and b.kind is TypeKind.NOMINAL
            and a.name == b.name
            and len(a.args) == len(b.args)
            and all(_mismo_tipo(x, y) for x, y in zip(a.args, b.args)))


def _mismo_tipo(a: Optional[Type], b: Optional[Type]) -> bool:
    """Igualdad de tipos módulo calificación de los nominales.

    Un argumento de tipo se compara así y NO con :func:`is_assignable`: los
    argumentos son INVARIANTES. ``Vector<ptr mutable int>`` no es un
    ``Vector<ptr int>`` aunque el puntero suelto sí se pueda degradar —
    leerlo como el segundo permitiría escribir por el primero.
    """
    if a is None or b is None:
        return a is b
    if a == b:
        return True
    if a.kind is not b.kind:
        return False
    if a.kind is TypeKind.NOMINAL:
        return _same_nominal(a, b)
    return a.mut == b.mut and _mismo_tipo(a.inner, b.inner)


def es_desconocido(t: Optional[Type]) -> bool:
    """¿El tipo ``t`` no dice nada sobre el valor?

    Dos formas significan lo mismo y tienen que tratarse igual:

    * ``None`` — esta fase todavía no infiere ese tipo;
    * ``error`` SIN envolver — el binding de un ``catch (e)`` y el retorno de
      un ``fn f() -> error``. ``throw`` acepta cualquier valor, así que lo
      único que se sabe de ``e`` es que llegó por la vía del error; su tipo
      es literalmente desconocido. Tratarlo como un tipo CONCRETO que no
      unifica con nada dejaba el valor capturado inservible: no se podía
      ligar, ni pasar, ni operar con él — solo interpolarlo. ``error T`` (con
      inner) sí dice algo y no entra aquí.
    """
    return t is None or (t.kind is TypeKind.ERROR and t.inner is None)


def is_assignable(target: Optional[Type], value: Optional[Type]) -> bool:
    """¿Un valor de tipo ``value`` puede asignarse a un binding ``target``?

    Conservador: si alguno de los dos tipos NO se conoce (ver
    :func:`es_desconocido`), se responde ``True`` — esta fase nunca rechaza un
    programa por información que no tiene (cero falsos positivos, ver
    ``ARQUITECTURA.md`` secc. 4.2).

    HOY: identidad estructural estricta + unificación nominal por nombre-hoja
    (``point.Point`` = ``Point``) + ``T`` asignable a ``T?``.
    FUTURO (Fase 3): coerciones numéricas, genéricos, unificación fina.
    """
    if es_desconocido(target) or es_desconocido(value):
        return True
    if target == value or _same_nominal(target, value):
        return True
    # T? = T y T? = U?  (envolver en nullable nunca pierde informacion). Se
    # RECURRE al inner para que las coerciones internas compongan: un
    # 'ptr mutable T' es asignable a 'ptr T?' (soltar mutabilidad DENTRO del
    # nullable). 'null' lo cubre 'unify_literal_null', no esta rama.
    if target.kind is TypeKind.NULLABLE:
        inner_value = value.inner if value.kind is TypeKind.NULLABLE else value
        return is_assignable(target.inner, inner_value)
    # modelo de errores por EXCEPCIONES: 'error T' es transparente en la ruta
    # de exito (el throw es control de flujo aparte). Un valor 'error T' se
    # usa como T (lo que devuelve la funcion cuando NO lanza), y un T plano
    # es un 'error T' valido (variante sin error). Se compara el nucleo.
    tv = value.inner if value.kind is TypeKind.ERROR else value
    tt = target.inner if target.kind is TypeKind.ERROR else target
    if (value.kind is TypeKind.ERROR or target.kind is TypeKind.ERROR) \
            and tv is not None and tt is not None and tv == tt:
        return True
    # 'ptr mutable T' es asignable a 'ptr T': SOLTAR el permiso de escritura
    # siempre es seguro (la direccion contraria nunca: ganaria permisos).
    if (
        target.kind is TypeKind.POINTER and value.kind is TypeKind.POINTER
        and value.mut and not target.mut
        and (target.inner == value.inner
             or _same_nominal(target.inner, value.inner))
    ):
        return True
    return False


def unify_literal_null(target: Optional[Type]) -> bool:
    """¿El literal ``null`` es asignable a ``target``?

    HOY: ``null`` unifica con cualquier ``NullableType`` (y con lo
    desconocido, por la misma regla conservadora de :func:`is_assignable`).
    """
    return target is None or target.kind is TypeKind.NULLABLE


__all__ = [
    "resolve_nominal", "lookup_type_path", "TypeLookup", "TypeLookupResult",
    "is_assignable", "unify_literal_null", "es_desconocido",
    "canonical", "canonical_name",
]
