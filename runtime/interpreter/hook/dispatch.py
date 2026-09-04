"""Re-enlace de hooks y casts en runtime (secc. 7).

El HIR transporta los hooks como REFERENCIAS (``HookRef {owner, kind,
hook_name}``) y las conversiones como símbolos con firma; este módulo
construye los índices O(1) que el evaluator consulta:

 - ``(owner_type, kind, name) -> BoundFunction``  (hooks: __print__, ...)
 - ``(clave tipo origen, clave tipo destino) -> BoundFunction``   (__cast__)

La clave de un hook es una TERNA porque el vocabulario dejó de ser cerrado:
un hook declarado por el usuario (HTIMS, ``htims/``) llega con
``kind == EXTENDED`` y su identidad real en ``hook_name``. Los hooks del
vocabulario fijo llevan ``name == ""`` — el enum ya los distingue — así que
un ``.phir`` emitido antes de este cambio indexa exactamente igual.

La clave de un ``Type`` protobuf es una tupla hashable recursiva
(:func:`type_key`) — el mismo par exacto que la Semántica registró.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

#: (unidad, FunctionDecl): la fn con la unidad cuyos globales necesita.
BoundFunction = Tuple[Any, Any]

TypeKey = Tuple

#: clave de un hook en el índice: ``(dueño, kind, nombre)``.
HookKey = Tuple[str, int, str]


def hook_key(owner_type: str, kind: int, name: str = "") -> HookKey:
    """Clave ÚNICA de un hook — el único sitio que la construye.

    Que exista esta función (y no una tupla escrita a mano en cada sitio de
    consulta) es lo que permitió pasar de ``(owner, kind)`` a la terna sin
    revisar cada lectura del evaluator una por una: los llamadores dicen QUÉ
    buscan, no cómo se indexa.
    """
    return (owner_type, kind, name)


def ref_key(ref) -> HookKey:
    """Clave de un ``HookRef`` del HIR (el caso más común de consulta)."""
    return (ref.owner_type, ref.kind, ref.hook_name)


def type_key(t) -> Optional[TypeKey]:
    """``Type`` protobuf -> clave hashable estructural (o ``None`` si el
    mensaje viene vacío/ausente).

    Los ARGUMENTOS de un genérico entran en la clave porque participan de la
    identidad del tipo: ``Vector<int>`` y ``Vector<str>`` son tipos
    DISTINTOS, y sin ellos las dos instanciaciones colapsaban en la misma
    entrada del índice de conversiones — el genérico habría vuelto a ser
    decorativo, esta vez en runtime.
    """
    if t is None or t.kind == 0:  # TYPE_UNSPECIFIED
        return None
    return (t.kind, t.name, t.mut,
            type_key(t.inner) if t.HasField("inner") else None,
            tuple(type_key(arg) for arg in t.args))


def index_hooks(units) -> Dict[HookKey, BoundFunction]:
    """Todos los ``HookEntry`` de todas las unidades -> índice combinado.

    El cuerpo de un hook vive en los ``items`` de SU unidad: se resuelve por
    (nombre, línea) del símbolo — dos ``__cast__`` comparten nombre pero no
    posición. Primera unidad en registrar una clave gana (mismo orden
    determinista que la fusión de la Semántica).
    """
    index: Dict[HookKey, BoundFunction] = {}
    for unit in units:
        for entry in unit.module.symbols.hooks:
            key = hook_key(entry.owner_type, entry.kind, entry.hook_name)
            if key in index:
                continue
            decl = unit.dunder_decls.get((entry.symbol.name, entry.symbol.ln))
            if decl is not None:
                index[key] = (unit, decl)
    return index


def index_dunders(units) -> Dict[Tuple[str, str], BoundFunction]:
    """Métodos de usuario (``dunder fn __x__(T ptr self, ...)``) -> índice
    ``(owner_type, nombre) -> (unit, decl)``.

    El ``owner`` sale del PRIMER parámetro (el receptor), desenvuelto hasta su
    nominal; el ``nombre`` es el ``fn.name`` completo (``__bump__``), tal como
    se escribe la llamada ``c.__bump__()``. Solo entran los que tienen CUERPO
    y receptor nominal (un prototipo como ``__write__`` o un ``__cast__`` entre
    primitivos no es un método). Los hooks del set fijo también encajan aquí,
    pero se despachan ANTES por ``(owner, kind)`` y nunca se consultan por esta
    vía — incluirlos es inocuo. Primera unidad en registrar un par gana.
    """
    from V0.src.HIR.stubs import load_hir_pb2
    pb = load_hir_pb2()
    nominal = pb.TypeKind.Value("NOMINAL")
    wrappers = (pb.TypeKind.Value("POINTER"), pb.TypeKind.Value("NULLABLE"))
    index: Dict[Tuple[str, str], BoundFunction] = {}
    for unit in units:
        for decl in unit.module.items:
            if decl.WhichOneof("node") != "function":
                continue
            fn = decl.function
            if not fn.dunder or not fn.HasField("body") or not fn.params:
                continue
            # el tipo del receptor viaja como INDICE en el pool de SU unidad
            # (esquema v2): 0 = sin tipo anotado, y un metodo sin receptor
            # tipado no es despachable.
            if not fn.params[0].type_id:
                continue
            receiver = unit.module.types[fn.params[0].type_id]
            while receiver.kind in wrappers and receiver.HasField("inner"):
                receiver = receiver.inner
            if receiver.kind != nominal:
                continue
            index.setdefault((receiver.name, fn.name), (unit, fn))
    return index


def index_casts(units) -> Dict[Tuple[TypeKey, TypeKey], BoundFunction]:
    """``SymbolTable.casts`` de todas las unidades -> índice (origen, destino).

    La clave del par es DERIVABLE de la firma del símbolo (origen =
    ``param_types[0]``, destino = ``type``) — contrato del esquema.
    """
    index: Dict[Tuple[TypeKey, TypeKey], BoundFunction] = {}
    for unit in units:
        for sym in unit.module.symbols.casts:
            if not sym.param_types:
                continue
            key = (type_key(sym.param_types[0]), type_key(sym.type))
            if key in index:
                continue
            decl = unit.dunder_decls.get((sym.name, sym.ln))
            if decl is not None:
                index[key] = (unit, decl)
    return index


__all__ = ["BoundFunction", "HookKey", "TypeKey", "hook_key", "ref_key",
           "type_key", "index_hooks", "index_dunders", "index_casts"]
