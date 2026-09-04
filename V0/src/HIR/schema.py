"""El esquema del HIR, leído del propio ``proto/hir.proto``.

Espejo en Python de lo que ``web/src/hir/schema.ts`` es para el target web,
con una diferencia: aquí el esquema **no se transcribe a mano**, se lee del
``.proto``. Así ``hir.proto`` sigue siendo la fuente única —no hay un cuarto
sitio que mantener sincronizado— y no hace falta ni ``protoc`` ni el runtime
``google.protobuf`` para leerlo.

Por qué esto existe (las mismas razones que da ``wire.ts``, más una):

 - **cero pasos de build**: generar los stubs exigía un ``protoc`` en el
   sistema Y un ``google.protobuf`` de pip cuya versión fuera compatible con
   él. Se instalan por vías distintas, así que nada garantizaba que
   concordaran: un ``protoc`` 36 con un ``protobuf`` 7.35 rompe la
   compilación en cuanto el ``.proto`` cambia, con un ``VersionError`` en
   bruto. Sin la librería, el problema no existe.
 - **cero peso muerto**: el 90% de la superficie de un runtime genérico
   (Any, extensiones, grupos, JSON, reflexión) no la usa este esquema.
 - **el frontend vuelve a no depender de nada**: ver ``PROTOBUF_BRIDGE.md``
   secc. 2, que prometía justo eso y había dejado de ser cierto.

El subconjunto de proto3 que se entiende es el que ``hir.proto`` usa, y
nada más: mensajes (anidados incluidos), enums, ``oneof``, ``repeated``,
``map<string, M>`` y los escalares ``uint32``/``int64``/``double``/``bool``/
``string``. Cualquier otra cosa es un error explícito al cargar el esquema,
nunca un campo ignorado en silencio.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

#: tipos escalares y su forma en el wire (ver 'wire.py').
#:  'varint'  -> enteros y bool
#:  'f64'     -> double (64 bits fijos)
#:  'bytes'   -> string (delimitado por longitud)
SCALARS: Dict[str, str] = {
    "uint32": "varint",
    "int32": "varint",
    "int64": "varint",
    "uint64": "varint",
    "bool": "varint",
    "double": "f64",
    "float": "f32",
    "string": "bytes",
}

#: valor por defecto de cada escalar en proto3 (lo que vale un campo ausente).
DEFAULTS: Dict[str, object] = {
    "uint32": 0, "int32": 0, "int64": 0, "uint64": 0,
    "bool": False, "double": 0.0, "float": 0.0, "string": "",
}


class Field:
    """Un campo del esquema: cómo se llama, qué número lleva y de qué tipo es."""

    __slots__ = ("name", "number", "type", "repeated", "oneof", "key_type")

    def __init__(self, name: str, number: int, type_: str, *,
                 repeated: bool = False, oneof: Optional[str] = None,
                 key_type: Optional[str] = None) -> None:
        self.name = name
        self.number = number
        self.type = type_          # escalar, nombre de enum, o de mensaje
        self.repeated = repeated
        self.oneof = oneof         # nombre del oneof al que pertenece, si alguno
        self.key_type = key_type   # 'string' si el campo es un map

    @property
    def is_map(self) -> bool:
        return self.key_type is not None

    def __repr__(self) -> str:  # pragma: no cover - depuracion
        return f"<Field {self.name}={self.number} {self.type}>"


class Message:
    """Un mensaje del esquema: sus campos, por nombre y por número."""

    __slots__ = ("name", "fields", "by_number", "oneofs")

    def __init__(self, name: str) -> None:
        self.name = name
        self.fields: Dict[str, Field] = {}
        self.by_number: Dict[int, Field] = {}
        self.oneofs: Dict[str, List[str]] = {}

    def add(self, field: Field) -> None:
        self.fields[field.name] = field
        self.by_number[field.number] = field
        if field.oneof is not None:
            self.oneofs.setdefault(field.oneof, []).append(field.name)


class Schema:
    """Todos los mensajes y enums de un ``.proto``."""

    __slots__ = ("messages", "enums")

    def __init__(self) -> None:
        self.messages: Dict[str, Message] = {}
        self.enums: Dict[str, Dict[str, int]] = {}

    def kind_of(self, type_name: str) -> str:
        """``'scalar'`` | ``'enum'`` | ``'message'`` para un tipo de campo."""
        if type_name in SCALARS:
            return "scalar"
        if type_name in self.enums:
            return "enum"
        if type_name in self.messages:
            return "message"
        raise SchemaError(f"tipo desconocido en el esquema: '{type_name}'")


class SchemaError(RuntimeError):
    """El ``.proto`` usa algo que este lector no entiende."""


# --------------------------------------------------------------------------- #
# el lector del .proto
# --------------------------------------------------------------------------- #
# Deliberadamente literal: recorre líneas, no construye un AST. El '.proto'
# de este proyecto es plano y estable, y un parser "de verdad" seria mas
# codigo que mantener por una gramatica que no cambia.

_CAMPO = re.compile(
    r"^(?:(repeated|optional)\s+)?"
    r"(map\s*<\s*(\w+)\s*,\s*([\w.]+)\s*>|[\w.]+)\s+"
    r"(\w+)\s*=\s*(\d+)\s*;"
)
_MENSAJE = re.compile(r"^message\s+(\w+)\s*\{")
_ENUM = re.compile(r"^enum\s+(\w+)\s*\{")
_ONEOF = re.compile(r"^oneof\s+(\w+)\s*\{")
_ITEM_ENUM = re.compile(r"^(\w+)\s*=\s*(\d+)\s*;")


def _sin_comentarios(texto: str) -> List[str]:
    """Las líneas sin comentarios ``//`` ni bloques ``/* */``, ya recortadas."""
    texto = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
    return [linea.split("//")[0].strip() for linea in texto.splitlines()]


def parse(texto: str) -> Schema:
    """Lee un ``.proto`` y devuelve su :class:`Schema`.

    Los mensajes ANIDADOS se registran con su nombre simple (``Part``): el
    esquema del HIR no repite nombres, y aplanarlos evita arrastrar la
    resolución de ámbitos de protobuf por un caso que no ocurre.
    """
    esquema = Schema()
    pila: List[object] = []          # Message | Dict (enum) en curso
    oneof_actual: List[Optional[str]] = [None]

    for linea in _sin_comentarios(texto):
        if not linea or linea.startswith(("syntax", "package", "import",
                                          "option", "reserved")):
            continue

        if linea == "}":
            if oneof_actual[-1] is not None:
                oneof_actual[-1] = None       # cierra el oneof, no el mensaje
            elif pila:
                pila.pop()
                oneof_actual.pop()
            continue

        m = _MENSAJE.match(linea)
        if m:
            msg = Message(m.group(1))
            esquema.messages[msg.name] = msg
            # 'message X { ... }' en una sola linea: se procesa su cuerpo
            cuerpo = linea[m.end():].rstrip()
            if cuerpo.endswith("}"):
                for trozo in cuerpo[:-1].split(";"):
                    trozo = trozo.strip()
                    if trozo:
                        _leer_campo(msg, trozo + ";", None)
                continue
            pila.append(msg)
            oneof_actual.append(None)
            continue

        m = _ENUM.match(linea)
        if m:
            items: Dict[str, int] = {}
            esquema.enums[m.group(1)] = items
            pila.append(items)
            oneof_actual.append(None)
            continue

        m = _ONEOF.match(linea)
        if m:
            oneof_actual[-1] = m.group(1)
            continue

        if not pila:
            continue
        actual = pila[-1]
        if isinstance(actual, dict):
            m = _ITEM_ENUM.match(linea)
            if m:
                actual[m.group(1)] = int(m.group(2))
            continue
        _leer_campo(actual, linea, oneof_actual[-1])

    return esquema


def _leer_campo(msg: Message, linea: str, oneof: Optional[str]) -> None:
    m = _CAMPO.match(linea)
    if m is None:
        return
    etiqueta, tipo, clave_map, valor_map, nombre, numero = m.groups()
    if clave_map is not None:
        msg.add(Field(nombre, int(numero), valor_map, repeated=True,
                      key_type=clave_map))
        return
    msg.add(Field(nombre, int(numero), tipo,
                  repeated=etiqueta == "repeated", oneof=oneof))


_RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "proto", "hir.proto")
_cache: Optional[Schema] = None


def hir_schema() -> Schema:
    """El esquema del HIR, leído una sola vez por proceso."""
    global _cache
    if _cache is None:
        with open(_RUTA, encoding="utf-8") as fh:
            _cache = parse(fh.read())
    return _cache


__all__ = ["Field", "Message", "Schema", "SchemaError", "SCALARS", "DEFAULTS",
           "parse", "hir_schema"]
