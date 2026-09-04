"""El módulo de mensajes del HIR: construido del ``.proto``, sin dependencias.

Antes esto generaba stubs con ``protoc`` y los cargaba con
``google.protobuf``. Eso ataba la compilación a DOS instalaciones que se
hacen por vías distintas —un binario del sistema y un paquete de pip— y que
tienen que ser compatibles entre sí: el stub generado lleva dentro su versión
de gencode y el runtime se niega a cargar uno más nuevo que él. Un ``protoc``
36 con un ``protobuf`` 7.35 es una combinación perfectamente normal, y rompía
la compilación entera en cuanto alguien tocaba el ``.proto``.

Ahora los mensajes se construyen leyendo ``proto/hir.proto`` (:mod:`schema`)
y se serializan a mano (:mod:`wire`). Es lo que el target web ya hacía —ver
la cabecera de ``web/src/hir/wire.ts``, que da estas mismas razones— y
significa que el ``.proto`` sigue siendo la fuente única sin necesitar nada
instalado.

La API que se expone es la que el proyecto usaba del stub y nada más: un
constructor por mensaje (``pb.Module()``) y los tres enums con su
``Value``/``Name``. Si algún día hiciera falta algo más, se añade aquí y se
ve; con la reflexión de protobuf no se veía.
"""

from __future__ import annotations

from types import ModuleType, SimpleNamespace
from typing import Dict, Optional

from . import schema as _schema
from . import wire as _wire


class StubGenerationError(RuntimeError):
    """No fue posible construir los mensajes del HIR desde el ``.proto``."""


class _Enum:
    """Un enum del esquema con la API del stub: ``Value``/``Name``.

    Los valores también están como atributos (``TypeKind.NOMINAL``), que es
    como se leen en el ``.proto`` y en los otros consumidores.
    """

    __slots__ = ("_nombre", "_por_nombre", "_por_numero")

    def __init__(self, nombre: str, items: Dict[str, int]) -> None:
        self._nombre = nombre
        self._por_nombre = dict(items)
        self._por_numero = {v: k for k, v in items.items()}

    def Value(self, nombre: str) -> int:
        try:
            return self._por_nombre[nombre]
        except KeyError:
            raise ValueError(
                f"'{nombre}' no es un valor de {self._nombre} "
                f"(hay: {sorted(self._por_nombre)})") from None

    def keys(self):
        """Los nombres del enum, como el ``EnumTypeWrapper`` del stub."""
        return list(self._por_nombre)

    def values(self):
        return list(self._por_numero)

    def items(self):
        return list(self._por_nombre.items())

    def Name(self, numero: int) -> str:
        try:
            return self._por_numero[numero]
        except KeyError:
            raise ValueError(
                f"{numero} no es un valor de {self._nombre}") from None

    def __getattr__(self, nombre: str) -> int:
        try:
            return self._por_nombre[nombre]
        except KeyError:
            raise AttributeError(nombre) from None


class _Descriptor:
    """Lo mínimo del descriptor de protobuf que el proyecto consulta.

    Solo ``full_name`` y ``fields`` (con su ``name``): se usa para preguntar
    QUÉ campos tiene un mensaje, no para reflexión de verdad.
    """

    __slots__ = ("full_name", "name", "fields")

    def __init__(self, desc: _schema.Message) -> None:
        self.name = desc.name
        self.full_name = desc.name
        self.fields = [SimpleNamespace(name=f.name, number=f.number,
                                       type=f.type)
                       for f in desc.fields.values()]


class _Constructor:
    """Fábrica de un mensaje concreto: ``pb.Module()`` crea uno vacío."""

    __slots__ = ("_nombre", "_esquema", "DESCRIPTOR")

    def __init__(self, nombre: str, esquema: _schema.Schema) -> None:
        self._nombre = nombre
        self._esquema = esquema
        self.DESCRIPTOR = _Descriptor(esquema.messages[nombre])

    def __call__(self, **campos) -> _wire.Message:
        """Crea el mensaje. Los ``kwargs`` inicializan campos, como el stub.

        Un campo REPETIDO se inicializa con una lista (``args=[...]``) y uno
        de tipo ``map`` con un diccionario: asignarlos directamente no vale
        —ni aquí ni en el stub— pero darlos al construir sí, y el proyecto lo
        usa así.
        """
        msg = _wire.Message(self._nombre, self._esquema, dueno=None)
        desc = self._esquema.messages[self._nombre]
        for nombre, valor in campos.items():
            campo = desc.fields.get(nombre)
            if campo is not None and campo.is_map:
                destino = getattr(msg, nombre)
                for clave, sub in valor.items():
                    destino[clave].CopyFrom(sub)
            elif campo is not None and campo.repeated:
                getattr(msg, nombre).extend(valor)
            else:
                setattr(msg, nombre, valor)
        return msg


_loaded: Optional[ModuleType] = None


def load_hir_pb2() -> ModuleType:
    """El módulo de mensajes del HIR, construido una vez por proceso.

    Conserva el nombre por compatibilidad con sus llamadores; ya no genera
    ni carga ningún stub. Sigue lanzando :class:`StubGenerationError` si el
    ``.proto`` no se puede leer, que es el único fallo que queda.
    """
    global _loaded
    if _loaded is not None:
        return _loaded

    try:
        esquema = _schema.hir_schema()
    except (OSError, _schema.SchemaError) as exc:
        raise StubGenerationError(
            f"no se pudo leer el esquema del HIR ({_schema._RUTA}): {exc}"
        ) from exc

    espacio = SimpleNamespace()
    for nombre in esquema.messages:
        setattr(espacio, nombre, _Constructor(nombre, esquema))
    for nombre, items in esquema.enums.items():
        setattr(espacio, nombre, _Enum(nombre, items))
        # los valores, también sueltos: es como se escriben en el .proto
        # ('pb.NOMINAL') y como los nombran los otros lectores.
        for item, numero in items.items():
            setattr(espacio, item, numero)

    _loaded = espacio  # type: ignore[assignment]
    return espacio     # type: ignore[return-value]


__all__ = ["load_hir_pb2", "StubGenerationError"]
