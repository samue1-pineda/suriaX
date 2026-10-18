"""Loader del intérprete: deserializa y VALIDA un ``.phir`` (Module protobuf).

Primera pieza real de la Fase 5.5 (``ARQUITECTURA.md`` secc. 4/13-1): el
punto donde el HIR emitido por el frontend (``V0/src/HIR/emmit_IR.py``)
entra al mundo del intérprete. Responsabilidades — y nada más:

 - leer los bytes de un ``.phir`` y parsearlos como ``Module``;
 - **fail-fast de esquema**: ``schema_version`` fuera de
   :data:`SUPPORTED_SCHEMA_VERSIONS` se rechaza con error claro ANTES de
   tocar el contenido (nunca interpretar bytes con un layout desconocido);
 - **normalizar el esquema 1** (tipos inline, sin pool) a la forma de hoy
   (``V0/src/HIR/schema_v1.normalize_v1``): desde ahí el intérprete tiene un
   solo camino, el del esquema 2;
 - indexar los hooks (``Module.symbols.hooks`` -> dict ``(owner, kind)``)
   en O(1), el mismo re-enlace que hará ``hook/dispatch.py``;
 - producir el resumen legible del módulo (``summarize``) que usa la CLI.

El tree-walk (evaluator/environment/values) NO vive aquí: flujo
unidireccional ``loader -> interpreter -> evaluator`` (secc. 4). Reusa los
stubs de ``V0/src/HIR/stubs.py`` — un solo lugar sabe generar/cargar
``hir_pb2`` en todo el proyecto.
"""

from __future__ import annotations

import os
from typing import Dict, Tuple

# el paquete se ejecuta con la raiz del repo y V0/ en sys.path (main.py de
# este directorio los inserta, igual que V0/main.py).
from V0.src.HIR.stubs import load_hir_pb2
# La notación de un tipo tiene UNA definición, la de la vista legible del HIR.
# Aquí vivía una copia byte a byte de esa función, y las dos se separaron: la
# de allá aprendió a escribir 'error int' y 'Vector<int>' y esta se quedó
# diciendo 'error' y 'Vector'. Un resumen y una vista legible del MISMO
# artefacto no pueden discrepar sobre cómo se llama un tipo.
from V0.src.HIR.pretty import format_type
from V0.src.HIR.schema_v1 import SCHEMA_V1, SchemaV1Error, normalize_v1
from .values import EnumItem, EnumValue, VariantCtor

#: versiones de esquema que este lector sabe interpretar. Un HIR de una
#: version futura se RECHAZA (fail-fast) en vez de mal-interpretarse. El 1
#: (tipos inline) se acepta y se NORMALIZA al cargar: es el rollback del
#: esquema versionado (ver la cabecera de hir.proto).
SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1, 2})


class HIRLoadError(RuntimeError):
    """El ``.phir`` no pudo cargarse: bytes corruptos o esquema no soportado."""


def load_module(path: str):
    """Lee ``path`` (``.phir``) y devuelve el ``Module`` validado.

    Lanza :class:`HIRLoadError` con mensaje accionable si los bytes no
    parsean o la versión del esquema no está soportada.
    """
    pb = load_hir_pb2()
    module = pb.Module()
    try:
        with open(path, "rb") as fh:
            module.ParseFromString(fh.read())
    except OSError as exc:
        raise HIRLoadError(f"no se pudo leer '{path}': {exc}") from exc
    except Exception as exc:  # DecodeError: protobuf corrupto / no es un .phir
        raise HIRLoadError(
            f"'{path}' no contiene un Module HIR válido: {exc}"
        ) from exc

    if module.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        supported = ", ".join(str(v) for v in sorted(SUPPORTED_SCHEMA_VERSIONS))
        raise HIRLoadError(
            f"schema_version {module.schema_version} no soportada por este "
            f"intérprete (soportadas: {supported}). Regenera el .phir con un "
            "frontend compatible o actualiza el intérprete."
        )
    if module.schema_version == SCHEMA_V1:
        # un solo camino de ejecucion: el v1 se lleva a la forma del 2 (pool
        # + indices) y el resto del interprete no sabe que existio
        try:
            normalize_v1(module)
        except SchemaV1Error as exc:
            raise HIRLoadError(f"'{path}': {exc}") from exc
    return module


def index_hooks(module) -> Dict[Tuple[str, int, str], object]:
    """``Module.symbols.hooks`` -> ``{(owner_type, HookKind, nombre): Symbol}``.

    El mismo re-enlace O(1) que la Semántica hace en Python y que hará el
    lector C++: cada ``HookRef`` del árbol se resuelve contra este dict. La
    clave la construye ``hook/dispatch.hook_key`` — un solo sitio decide qué
    identifica a un hook (ver allí: el vocabulario ya no es cerrado).
    """
    from .hook.dispatch import hook_key
    return {hook_key(h.owner_type, h.kind, h.hook_name): h.symbol
            for h in module.symbols.hooks}


# ---------------------------------------------------------------------- #
# module linker: N unidades .phir -> una imagen ejecutable (secc. 10.1)
# ---------------------------------------------------------------------- #

class Unit:
    """Una unidad HIR cargada (main o una .libsrx) con sus índices."""

    __slots__ = ("alias", "path", "module", "functions", "dunder_decls",
                 "enum_values", "tests", "globals_frame")

    def __init__(self, alias: str, path: str, module) -> None:
        self.alias = alias
        self.path = path
        self.module = module
        # nombre -> FunctionDecl (los dunder pueden repetir nombre entre
        # overloads de __cast__: van aparte, indexados por (nombre, línea)).
        self.functions: Dict[str, object] = {}
        self.dunder_decls: Dict[Tuple[str, int], object] = {}
        # enum -> {item -> int} (auto-numerado estilo C, literal si lo hay)
        self.enum_values: Dict[str, Dict[str, int]] = {}
        # bloques 'test "nombre" { ... }' en orden de declaración
        self.tests: list = []
        self.globals_frame = None  # lo monta interpreter.run (Frame)
        self._index()

    def _index(self) -> None:
        for decl in self.module.items:
            which = decl.WhichOneof("node")
            if which == "function":
                fn = decl.function
                # invocable por NOMBRE siempre (incl. dunder no-hook como
                # '__write__'): un dunder que no es hook reconocido es una
                # funcion normal. Los overloads de __cast__ comparten nombre
                # pero solo se despachan por la tabla de casts, nunca por
                # nombre, asi que la colision en 'functions' es inocua.
                #
                # Un METODO de '@impl' (nombre llano y 'dunder' igual al
                # nombre) NO: se despacha por (tipo, nombre) en 'dunders', y
                # por nombre pisaba a una 'fn' homonima del modulo —'fn
                # distancia' y '@impl Punto { fn distancia }' conviven en la
                # Semantica, y la llamada 'distancia(5)' ejecutaba el metodo.
                if not (fn.dunder and fn.dunder == fn.name):
                    self.functions[fn.name] = fn
                if fn.dunder:
                    # ...y ademas resoluble como CUERPO de hook por (nombre,
                    # linea): hook/dispatch enlaza los HookRef contra esto.
                    self.dunder_decls[(fn.name, decl.ln)] = fn
            elif which == "test_decl":
                self.tests.append(decl.test_decl)
            elif which == "enum_decl":
                nombre_enum = decl.enum_decl.name
                values: Dict[str, object] = {}
                next_value = 0
                # ¿tipo SUMA? (alguna variante lleva datos). Entonces una
                # variante SIN datos es un valor del enum como sus hermanas
                # (un 'EnumValue' sin campos), no un entero: lo que despacha
                # por el tipo del valor la reconoce (A10, A10b, A02).
                is_sum = any(i.payload_type_ids for i in decl.enum_decl.items)
                for item in decl.enum_decl.items:
                    if item.payload_type_ids:
                        # variante con PAYLOAD: no es un entero sino algo que
                        # se invoca. La aridad viene del esquema, asi que el
                        # interprete no tiene que consultar la declaracion.
                        values[item.name] = VariantCtor(
                            nombre_enum, item.name, len(item.payload_type_ids))
                        continue
                    if item.HasField("value") and \
                            item.value.WhichOneof("node") == "literal":
                        next_value = int(item.value.literal.int_value)
                    if is_sum:
                        # UNA por variante: 'match' la reconoce por identidad
                        # (ver 'Evaluator._encaja'); sin campos, nada la copia
                        values[item.name] = EnumValue(nombre_enum, item.name, [])
                    else:
                        # estilo C: sigue siendo el entero, pero sabe su
                        # nombre (para escribirlo dentro de un genérico, A08)
                        values[item.name] = EnumItem(next_value, nombre_enum,
                                                     item.name)
                    next_value += 1
                self.enum_values[nombre_enum] = values


class Image:
    """main + librerías ligadas: lo que ejecuta el intérprete."""

    __slots__ = ("main", "units", "hooks", "casts", "dunders", "type_params")

    def __init__(self, main: Unit, units: Dict[str, Unit]) -> None:
        from .hook.dispatch import (index_casts as _casts,
                                    index_dunders as _dunders,
                                    index_hooks as _hooks)
        self.main = main
        self.units = units  # alias -> Unit (main NO está: su alias es "")
        every = [main, *units.values()]
        self.hooks = _hooks(every)
        self.casts = _casts(every)
        # métodos de usuario (dunder fn) por (owner_type, nombre): x.__m__(...)
        self.dunders = _dunders(every)
        # los PARAMETROS DE TIPO de todas las unidades ('T', 'K'...). Un
        # HookRef cuyo dueño es uno de ellos viene de una COTA ('print(x)' con
        # 'T: Print'): no hay hook de 'T', se despacha con el tipo del valor.
        # Un parametro no choca con un tipo real de su archivo (la Semantica
        # lo rechaza), y el despacho estatico se intenta siempre antes.
        self.type_params = frozenset(
            name for unit in every for decl in unit.module.items
            for name in _type_params_of(decl))


def _type_params_of(decl):
    """Los parametros de tipo que declara un item del HIR (una funcion
    generica o un metodo de un '@impl' generico, un struct, un enum)."""
    which = decl.WhichOneof("node")
    if which == "function":
        return decl.function.type_params
    if which == "struct_decl":
        return decl.struct_decl.type_params
    if which == "enum_decl":
        return decl.enum_decl.type_params
    return ()


def load_image(main_path: str) -> Image:
    """Carga el ``.phir`` principal y TODAS sus unidades referenciadas.

    Cada ``LibraryRef.phir`` se resuelve RELATIVO al directorio del archivo
    que lo referencia; las unidades transitivas se cargan una sola vez
    (worklist con vistos por alias).
    """
    main = Unit("", main_path, load_module(main_path))
    units: Dict[str, Unit] = {}
    pending = [(main_path, ref) for ref in main.module.libraries]
    while pending:
        base_path, ref = pending.pop()
        if ref.alias in units:
            continue
        phir_path = os.path.join(os.path.dirname(os.path.abspath(base_path)),
                                 ref.phir)
        if not os.path.isfile(phir_path):
            raise HIRLoadError(
                f"la unidad '{ref.alias}' referencia '{ref.phir}' y no existe "
                f"junto a '{os.path.basename(base_path)}' — ¿se emitió con "
                "--emit-hir? (las unidades .phir viajan juntas)"
            )
        unit = Unit(ref.alias, phir_path, load_module(phir_path))
        units[ref.alias] = unit
        pending.extend((phir_path, sub) for sub in unit.module.libraries)
    return Image(main, units)


# ---------------------------------------------------------------------- #
# resumen legible (CLI): que trae el modulo, sin ejecutarlo
# ---------------------------------------------------------------------- #

def summarize(module) -> str:
    """Resumen del ``Module`` para la CLI: símbolos, hooks e items."""
    pb = load_hir_pb2()
    lines = [
        f"HIR schema v{module.schema_version} — {module.source_file}",
        f"  items de nivel superior: {len(module.items)}",
    ]

    types = module.symbols.types
    if types:
        lines.append(f"  tipos ({len(types)}):")
        for name in sorted(types):
            sym = types[name]
            kind = pb.SymbolKind.Name(sym.kind)
            detail = ""
            if sym.members:
                detail = " { " + ", ".join(
                    f"{format_type(sym.members[m].type, pb)} {m}"
                    for m in sorted(sym.members)
                ) + " }"
            lines.append(f"    {kind.lower():<8} {name}{detail}")

    values = module.symbols.values
    fns = [n for n in sorted(values)
           if values[n].kind == pb.SymbolKind.Value("FUNCTION")]
    others = [n for n in sorted(values) if n not in fns]
    if fns:
        lines.append(f"  funciones ({len(fns)}):")
        for name in fns:
            sym = values[name]
            params = ", ".join(format_type(t, pb) for t in sym.param_types)
            lines.append(
                f"    fn {name}({params}) -> {format_type(sym.type, pb)}"
            )
    if others:
        lines.append(f"  otros valores ({len(others)}): " + ", ".join(others))

    hooks = module.symbols.hooks
    if hooks:
        lines.append(f"  hooks ({len(hooks)}):")
        for h in hooks:
            lines.append(f"    __{pb.HookKind.Name(h.kind).lower()}__ de {h.owner_type}")

    return "\n".join(lines)


__all__ = [
    "SUPPORTED_SCHEMA_VERSIONS", "HIRLoadError",
    "load_module", "index_hooks", "format_type", "summarize",
    "Unit", "Image", "load_image",
]
