"""El esquema 1 del HIR: escribirlo (rollback) y normalizarlo al esquema 2.

Entre el esquema 1 y el 2 cambió UNA sola cosa: el pool de tipos. En el 1
cada nodo llevaba su ``Type`` inline (``Expr.restype``, ``VarDecl.type``...);
en el 2 el ``Module`` lleva el pool (``Module.types``) y los nodos un índice
(``Expr.type_id``...). Ver la cabecera de ``proto/hir.proto`` y
``docs/plan_hir_v2.md``.

Como el esquema está VERSIONADO, el 1 puede seguir funcionando. Este módulo
es todo lo que hace falta en Python para eso, en dos direcciones:

- :func:`to_schema_v1` (el emisor, ``--hir-schema 1``): toma el ``Module`` del
  esquema 2 que construye ``emmit_IR`` y "despliega" el pool: cada índice se
  sustituye por una copia del tipo, inline. Es un paso APARTE a propósito: el
  emisor sigue teniendo un solo camino (el del 2), y el 1 se deriva de él, así
  que no hay dos emisores que puedan divergir.
- :func:`normalize_v1` (el intérprete, al cargar): hace lo contrario. Construye
  el pool desde los tipos inline y rellena los índices; desde ahí el
  intérprete sigue igual que con un ``.phir`` del 2. Un solo camino de
  ejecución.

Los campos de tipo de cada mensaje están en :data:`TYPE_FIELDS`, y es la ÚNICA
lista: el recorrido es genérico sobre el esquema (``schema.py`` lo lee del
propio ``.proto``) y baja solo por los mensajes que pueden contener alguno.

**El orden del pool.** Al normalizar, los tipos entran al pool en el MISMO
orden en que los registra el emisor (``_Emitter._type_id``): el recorrido
visita los campos por número, y el campo de tipo de cada mensaje en la
posición del MENOR de sus dos tags (el del índice y el inline). Con esa regla
el orden coincide con el del emisor en todos los mensajes (``LambdaExpr``:
parámetros, retorno, cuerpo; ``FunctionDecl``: igual; ``Expr``: su tipo antes
que sus hijos). No cambia lo que el programa significa —un índice es solo una
dirección en una tabla—, pero hace que normalizar el ``.phir`` v1 de un
programa dé, byte a byte, el del v2 (salvo ``schema_version``), y eso es lo que
lo hace COMPROBABLE (``test/unit/test_hir_schema_v1.py``).

**Sin errores silenciosos.** Un ``.phir`` v1 con pool o con algún índice es un
archivo mal formado (mezcla los dos esquemas), no "casi un v2": se rechaza con
:class:`SchemaV1Error`. Un índice fuera del pool al desplegar, igual.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .schema import Schema, hir_schema

#: el esquema de tipos INLINE (sin pool).
SCHEMA_V1 = 1
#: el esquema del pool de tipos (el que se emite por defecto).
SCHEMA_V2 = 2
#: los que el emisor sabe escribir (``--hir-schema``).
EMITTABLE_SCHEMAS: Tuple[int, ...] = (SCHEMA_V1, SCHEMA_V2)

#: mensaje -> sus campos de tipo, como ``(campo índice, campo inline,
#: repetido)``. Los inline del esquema 1 conservan su tag original; los de
#: ``LambdaExpr`` y ``EnumItem`` nacieron después y llevan un tag nuevo (ver
#: ``hir.proto``). ``SizeofExpr.type``, ``CastExpr.type``,
#: ``CatchClause.type`` y la ``SymbolTable`` siempre fueron inline.
TYPE_FIELDS: Dict[str, Tuple[Tuple[str, str, bool], ...]] = {
    "Expr": (("type_id", "restype", False),),
    "VarDecl": (("type_id", "type", False),),
    "Parameter": (("type_id", "type", False),),
    "FunctionDecl": (("return_type_id", "return_type", False),),
    "Field": (("type_id", "type", False),),
    "LambdaExpr": (("return_type_id", "return_type", False),),
    "EnumItem": (("payload_type_ids", "payload_types", True),),
}


class SchemaV1Error(ValueError):
    """Un ``.phir`` que no se puede convertir entre los esquemas 1 y 2."""


# --------------------------------------------------------------------------- #
# el plan de recorrido, derivado del esquema
# --------------------------------------------------------------------------- #

# paso: ("type", campo_indice, campo_inline, repetido)
#     | ("child", campo, "single" | "repeated" | "map")
_Paso = tuple
_planes: Optional[Dict[str, List[_Paso]]] = None


def _construir_planes(esquema: Schema) -> Dict[str, List[_Paso]]:
    """Para cada mensaje que PUEDE contener un campo de tipo: qué visitar y en
    qué orden. Los demás (``Type``, ``SymbolTable``, ``Literal``...) no tienen
    plan y el recorrido no baja por ellos."""
    # punto fijo: un mensaje es relevante si tiene campos de tipo o un hijo
    # relevante
    relevantes = set(TYPE_FIELDS)
    cambio = True
    while cambio:
        cambio = False
        for nombre, msg in esquema.messages.items():
            if nombre in relevantes:
                continue
            if any(f.type in relevantes for f in msg.fields.values()):
                relevantes.add(nombre)
                cambio = True

    planes: Dict[str, List[_Paso]] = {}
    for nombre in relevantes:
        msg = esquema.messages[nombre]
        pasos: List[Tuple[int, _Paso]] = []
        de_tipo = set()
        for id_campo, inline, repetido in TYPE_FIELDS.get(nombre, ()):
            orden = min(msg.fields[id_campo].number, msg.fields[inline].number)
            pasos.append((orden, ("type", id_campo, inline, repetido)))
            de_tipo.update((id_campo, inline))
        for campo in msg.fields.values():
            if campo.name in de_tipo or campo.type not in relevantes:
                continue
            forma = ("map" if campo.is_map
                     else "repeated" if campo.repeated else "single")
            pasos.append((campo.number, ("child", campo.name, forma)))
        planes[nombre] = [paso for _, paso in sorted(pasos, key=lambda p: p[0])]
    return planes


def _plan(nombre: str) -> Optional[List[_Paso]]:
    global _planes
    if _planes is None:
        _planes = _construir_planes(hir_schema())
    return _planes.get(nombre)


def _recorrer(msg, visitar_tipo) -> None:
    """Recorre ``msg`` en el orden del plan y llama a ``visitar_tipo(msg,
    campo_indice, campo_inline, repetido)`` en cada campo de tipo."""
    # '_desc' es el descriptor del mensaje en 'wire.py' (mismo paquete): la
    # clase de mensaje no expone su nombre de otra forma barata.
    plan = _plan(msg._desc.name)
    if plan is None:
        return
    for paso in plan:
        if paso[0] == "type":
            visitar_tipo(msg, paso[1], paso[2], paso[3])
            continue
        _, campo, forma = paso
        if forma == "single":
            if msg.HasField(campo):
                _recorrer(getattr(msg, campo), visitar_tipo)
        elif forma == "repeated":
            for hijo in getattr(msg, campo):
                _recorrer(hijo, visitar_tipo)
        else:
            for clave in sorted(getattr(msg, campo)):
                _recorrer(getattr(msg, campo)[clave], visitar_tipo)


# --------------------------------------------------------------------------- #
# esquema 2 -> esquema 1 (el emisor, '--hir-schema 1')
# --------------------------------------------------------------------------- #

def to_schema_v1(module):
    """Devuelve el MISMO programa en el esquema 1, sin tocar ``module``.

    ``module`` es un ``Module`` del esquema 2 (lo que construye
    ``emmit_IR.build_module``). Se trabaja sobre una copia profunda —se
    serializa y se vuelve a leer—: el emisor puede seguir usando el original
    (por ejemplo para la vista legible), y desplegar no puede alterarlo.
    """
    from .emmit_IR import serialize
    from .stubs import load_hir_pb2

    if module.schema_version != SCHEMA_V2:
        raise SchemaV1Error(
            f"solo se despliega un Module del esquema {SCHEMA_V2} "
            f"(llegó schema_version {module.schema_version})")
    copia = load_hir_pb2().Module()
    copia.ParseFromString(serialize(module))
    pool = list(copia.types)

    def desplegar(msg, id_campo: str, inline: str, repetido: bool) -> None:
        if repetido:
            for tid in getattr(msg, id_campo):
                getattr(msg, inline).add().CopyFrom(_del_pool(pool, tid))
            msg.ClearField(id_campo)
            return
        tid = getattr(msg, id_campo)
        if tid:
            getattr(msg, inline).CopyFrom(_del_pool(pool, tid))
        msg.ClearField(id_campo)

    for decl in copia.items:
        _recorrer(decl, desplegar)
    copia.ClearField("types")
    copia.schema_version = SCHEMA_V1
    return copia


def _del_pool(pool: list, tid: int):
    if tid >= len(pool):
        raise SchemaV1Error(
            f"type_id {tid} fuera del pool de tipos ({len(pool)} entradas): "
            "el .phir está mal formado")
    return pool[tid]


# --------------------------------------------------------------------------- #
# esquema 1 -> forma del esquema 2 (los lectores, al cargar)
# --------------------------------------------------------------------------- #

def normalize_v1(module):
    """Convierte EN SITIO un ``Module`` del esquema 1 a la forma de hoy.

    Construye ``Module.types`` desde los tipos inline (con la entrada 0 vacía
    = "sin tipo", y sin repetir: dos tipos iguales comparten entrada, igual
    que en el emisor) y pone cada índice en su sitio; los inline se quitan.
    ``schema_version`` se CONSERVA en 1: dice qué se leyó, y ningún consumidor
    decide nada por ella después de cargar. (Quien quiera re-serializar el
    resultado tiene que ponerle 2: con 1 y un pool sería un archivo que mezcla
    los dos esquemas, y los lectores lo rechazan; no se degrada en silencio.)

    Devuelve el mismo ``module``. Lanza :class:`SchemaV1Error` si el archivo
    mezcla los dos esquemas.
    """
    if module.schema_version != SCHEMA_V1:
        raise SchemaV1Error(
            f"solo se normaliza un Module del esquema {SCHEMA_V1} "
            f"(llegó schema_version {module.schema_version})")
    if len(module.types) != 0:
        raise SchemaV1Error(
            f"un .phir del esquema {SCHEMA_V1} no lleva pool de tipos "
            f"('Module.types', {len(module.types)} entradas): el archivo "
            "mezcla los dos esquemas")
    pool = module.types
    vacio = pool.add()                       # 0 = sin tipo
    ids: Dict[str, int] = {type_key(vacio): 0}

    def indice(tipo) -> int:
        clave = type_key(tipo)
        tid = ids.get(clave)
        if tid is None:
            tid = len(pool)
            pool.add().CopyFrom(tipo)
            ids[clave] = tid
        return tid

    def plegar(msg, id_campo: str, inline: str, repetido: bool) -> None:
        if repetido:
            if len(getattr(msg, id_campo)) != 0:
                raise SchemaV1Error(_mezcla(msg, id_campo))
            tipos = list(getattr(msg, inline))
            msg.ClearField(inline)
            destino = getattr(msg, id_campo)
            for tipo in tipos:
                destino.append(indice(tipo))
            return
        if getattr(msg, id_campo) != 0:
            raise SchemaV1Error(_mezcla(msg, id_campo))
        if msg.HasField(inline):
            tid = indice(getattr(msg, inline))
            msg.ClearField(inline)
            if tid:
                setattr(msg, id_campo, tid)

    for decl in module.items:
        _recorrer(decl, plegar)
    return module


def type_key(tipo) -> str:
    """La identidad ESTRUCTURAL de un ``Type``: la clave del pool al normalizar.

    Es, carácter a carácter, la de ``backend/src/view.cpp::type_key`` (el
    normalizador C++ deduplica con ella); ``web/src/hir/schema.typeKey``
    agrupa igual salvo que escribe el tipo vacío como ``""``. Distingue lo
    mismo que los bytes del ``Type``: un ``inner`` presente pero vacío no es
    un ``inner`` ausente.
    """
    interior = type_key(tipo.inner) if tipo.HasField("inner") else ""
    argumentos = ",".join(type_key(a) for a in tipo.args)
    return (f"{int(tipo.kind)}:{tipo.name}:{1 if tipo.mut else 0}:"
            f"({interior}):[{argumentos}]")


def _mezcla(msg, campo: str) -> str:
    return (f"un .phir del esquema {SCHEMA_V1} no lleva índices de tipo, y "
            f"'{msg._desc.name}.{campo}' trae uno: el archivo mezcla los dos "
            "esquemas")


def with_type_pool(module):
    """``module`` en la forma de hoy (con pool), para quien necesita LEERLO.

    Un v2 se devuelve tal cual; de un v1 se devuelve una copia normalizada (el
    original no se toca). Lo usa la vista legible del emisor con
    ``--hir-schema 1``.
    """
    if module.schema_version != SCHEMA_V1:
        return module
    from .emmit_IR import serialize
    from .stubs import load_hir_pb2
    copia = load_hir_pb2().Module()
    copia.ParseFromString(serialize(module))
    return normalize_v1(copia)


__all__ = ["SCHEMA_V1", "SCHEMA_V2", "EMITTABLE_SCHEMAS", "TYPE_FIELDS",
           "SchemaV1Error", "to_schema_v1", "normalize_v1", "with_type_pool",
           "type_key"]
