"""Lector y emisor del *wire format* de protobuf — cero dependencias.

Contraparte en Python de ``web/src/hir/wire.ts`` + ``encode.ts``, y por las
mismas razones (ver la cabecera de :mod:`schema`): el ``.phir`` es un formato
de bytes estable y bien documentado, y leerlo no debería costar ni un
``protoc`` en el sistema ni un ``google.protobuf`` de pip cuya versión tenga
que concordar con él.

Lo que se implementa es el subconjunto que usa ``hir.proto`` y nada más:
varints, campos delimitados por longitud, ``double``, ``repeated`` (con el
empaquetado por defecto de proto3 para los escalares), ``oneof`` y
``map<string, M>``. Los grupos, las extensiones, ``Any`` y la reflexión no
existen aquí — son el 90% de un runtime genérico y este esquema no los toca.

La API de los mensajes imita la del stub generado en lo que el proyecto
realmente usa (``HasField``, ``WhichOneof``, ``SetInParent``, ``add``,
``extend``, ``ParseFromString``, ``SerializeToString`` y el acceso por
atributo), para que sustituirlo no obligue a tocar ni el emisor ni ningún
lector.

**PRESENCIA**: en proto3 solo la tienen los mensajes y los miembros de un
``oneof``; un escalar ausente y uno con su valor por defecto son
indistinguibles. Por eso ``msg.sub`` devuelve un submensaje VACÍO sin
marcarlo presente, y solo escribir en él (o llamar a ``SetInParent``) lo
marca — exactamente como el stub. Sin esa pereza, leer un campo opcional lo
crearía, y el ``.phir`` engordaría con mensajes vacíos que nadie escribió.
"""

from __future__ import annotations

import struct
from typing import Any, Dict, Iterator, List, Optional

from . import schema as _schema
from .schema import DEFAULTS, SCALARS, Field, Schema, SchemaError

#: tipos de wire de protobuf (los tres que este esquema usa)
_WIRE_VARINT = 0
_WIRE_F64 = 1
_WIRE_BYTES = 2
_WIRE_F32 = 5

_WIRE_DE = {"varint": _WIRE_VARINT, "f64": _WIRE_F64, "f32": _WIRE_F32,
            "bytes": _WIRE_BYTES}


class DecodeError(RuntimeError):
    """Bytes que no encajan con el esquema. Siempre dice el OFFSET."""


# --------------------------------------------------------------------------- #
# codec de bajo nivel
# --------------------------------------------------------------------------- #

def _escribe_varint(salida: bytearray, valor: int) -> None:
    if valor < 0:
        # proto3 codifica los negativos de int32/int64 como un varint de 64
        # bits en complemento a dos (10 bytes), no en zigzag: eso es 'sint'.
        valor += 1 << 64
    while True:
        byte = valor & 0x7F
        valor >>= 7
        if valor:
            salida.append(byte | 0x80)
        else:
            salida.append(byte)
            return


def _lee_varint(datos: bytes, pos: int) -> tuple:
    resultado = 0
    desplazamiento = 0
    while True:
        if pos >= len(datos):
            raise DecodeError(f"varint sin terminar en el offset {pos}")
        byte = datos[pos]
        pos += 1
        resultado |= (byte & 0x7F) << desplazamiento
        if not byte & 0x80:
            return resultado, pos
        desplazamiento += 7
        if desplazamiento > 63:
            raise DecodeError(f"varint de mas de 64 bits en el offset {pos}")


def _con_signo(valor: int) -> int:
    """Reinterpreta un varint de 64 bits como entero CON signo."""
    return valor - (1 << 64) if valor >= 1 << 63 else valor


# --------------------------------------------------------------------------- #
# colecciones
# --------------------------------------------------------------------------- #

class _Repetido(list):
    """Base de las colecciones: cualquier mutación MATERIALIZA a su dueño.

    Hace falta porque la presencia es perezosa (ver :class:`Message`): pedir
    ``msg.sub.lista`` no marca ``sub`` como presente, así que si además no lo
    marcara el ``append``, lo que se guardara en la lista no se serializaría
    nunca. Es la trampa de este modelo y por eso vive en la clase base, no
    repartida por cada método.
    """

    __slots__ = ("_dueno",)

    def _tocar(self) -> None:
        self._dueno._marcar()

    def append(self, item) -> None:            # type: ignore[override]
        self._tocar()
        list.append(self, item)

    def extend(self, otros) -> None:           # type: ignore[override]
        self._tocar()
        list.extend(self, otros)

    def insert(self, indice, item) -> None:    # type: ignore[override]
        self._tocar()
        list.insert(self, indice, item)

    def __setitem__(self, indice, item) -> None:  # type: ignore[override]
        self._tocar()
        list.__setitem__(self, indice, item)


class RepeatedScalar(_Repetido):
    """``repeated`` de escalares."""

    __slots__ = ()

    def __init__(self, dueno: "Message") -> None:
        super().__init__()
        self._dueno = dueno


class RepeatedMessage(_Repetido):
    """``repeated`` de mensajes, con el ``add()`` del stub generado."""

    __slots__ = ("_tipo", "_esquema")

    def __init__(self, tipo: str, esquema: Schema, dueno: "Message") -> None:
        super().__init__()
        self._tipo = tipo
        self._esquema = esquema
        self._dueno = dueno

    def add(self) -> "Message":
        hijo = Message(self._tipo, self._esquema, dueno=None)
        self.append(hijo)
        return hijo

    def extend(self, otros) -> None:           # type: ignore[override]
        for otro in otros:
            self.add().CopyFrom(otro)


class MapField(dict):
    """``map<string, M>``: al pedir una clave que no existe, la crea vacía.

    Es lo que hace el stub (``msg.members[name].kind = ...`` funciona sin
    haber insertado nada antes) y de lo que depende el emisor.
    """

    __slots__ = ("_tipo", "_esquema", "_dueno")

    def __init__(self, tipo: str, esquema: Schema, dueno: "Message") -> None:
        super().__init__()
        self._tipo = tipo
        self._esquema = esquema
        self._dueno = dueno

    def __getitem__(self, clave: str) -> "Message":
        if clave not in self:
            self._dueno._marcar()
            super().__setitem__(clave, Message(self._tipo, self._esquema,
                                               dueno=None))
        return super().__getitem__(clave)


# --------------------------------------------------------------------------- #
# el mensaje
# --------------------------------------------------------------------------- #

class Message:
    """Un mensaje del esquema, con la API que usa el proyecto."""

    __slots__ = ("_nombre", "_esquema", "_desc", "_valores", "_presentes",
                 "_dueno", "_campo_en_dueno")

    def __init__(self, nombre: str, esquema: Schema, *,
                 dueno: Optional[tuple] = None) -> None:
        self._nombre = nombre
        self._esquema = esquema
        self._desc = esquema.messages[nombre]
        self._valores: Dict[str, Any] = {}
        self._presentes: set = set()
        # (mensaje padre, nombre del campo) mientras este submensaje no se
        # haya materializado; None cuando ya es suyo.
        self._dueno = dueno

    # -- presencia perezosa ------------------------------------------------ #
    def _marcar(self) -> None:
        """Materializa este mensaje en su padre (y al padre en el suyo)."""
        if self._dueno is None:
            return
        padre, campo = self._dueno
        self._dueno = None
        padre._valores[campo] = self
        padre._presentes.add(campo)
        desc = padre._desc.fields[campo]
        if desc.oneof is not None:
            for hermano in padre._desc.oneofs[desc.oneof]:
                if hermano != campo:
                    padre._presentes.discard(hermano)
                    padre._valores.pop(hermano, None)
        padre._marcar()

    def SetInParent(self) -> None:
        """Marca presente un mensaje que no escribe ningún campo.

        Hace falta porque en proto3 un mensaje vacío y uno ausente se
        codifican igual salvo por su etiqueta: ``return;`` y un bloque ``{}``
        existen aunque no lleven nada dentro.
        """
        self._marcar()

    # -- acceso por atributo ----------------------------------------------- #
    def __getattr__(self, nombre: str) -> Any:
        if nombre == "DESCRIPTOR":
            # lo consultan las pruebas que preguntan QUE campos tiene un
            # mensaje; se construye aqui para no cargarlo en cada instancia.
            from .stubs import _Descriptor
            return _Descriptor(self._desc)
        desc = self._desc.fields.get(nombre)
        if desc is None:
            raise AttributeError(
                f"'{self._nombre}' no tiene el campo '{nombre}'")
        if nombre in self._valores:
            return self._valores[nombre]
        valor = self._nuevo(desc)
        if desc.repeated or desc.is_map:
            # las colecciones se guardan al vuelo: mutarlas es lo normal, y
            # el 'add'/'__getitem__' se encarga de marcar al padre
            self._valores[nombre] = valor
        return valor

    def __setattr__(self, nombre: str, valor: Any) -> None:
        if nombre in Message.__slots__:
            object.__setattr__(self, nombre, valor)
            return
        desc = self._desc.fields.get(nombre)
        if desc is None:
            raise AttributeError(
                f"'{self._nombre}' no tiene el campo '{nombre}'")
        if desc.repeated or desc.is_map:
            raise AttributeError(
                f"'{nombre}' es repetido: usa 'add'/'extend', no asignacion")
        self._valores[nombre] = valor
        self._presentes.add(nombre)
        if desc.oneof is not None:
            for hermano in self._desc.oneofs[desc.oneof]:
                if hermano != nombre:
                    self._presentes.discard(hermano)
                    self._valores.pop(hermano, None)
        self._marcar()

    def _nuevo(self, desc: Field) -> Any:
        if desc.is_map:
            return MapField(desc.type, self._esquema, self)
        if desc.repeated:
            clase = self._esquema.kind_of(desc.type)
            if clase == "message":
                return RepeatedMessage(desc.type, self._esquema, self)
            return RepeatedScalar(self)
        clase = self._esquema.kind_of(desc.type)
        if clase == "message":
            return Message(desc.type, self._esquema, dueno=(self, desc.name))
        if clase == "enum":
            return 0
        return DEFAULTS[desc.type]

    # -- consultas del stub ------------------------------------------------ #
    def HasField(self, nombre: str) -> bool:
        desc = self._desc.fields.get(nombre)
        if desc is None:
            raise ValueError(f"'{self._nombre}' no tiene el campo '{nombre}'")
        return nombre in self._presentes

    def WhichOneof(self, oneof: str) -> Optional[str]:
        for nombre in self._desc.oneofs.get(oneof, ()):
            if nombre in self._presentes:
                return nombre
        return None

    def ClearField(self, nombre: str) -> None:
        """Deja el campo AUSENTE (el ``ClearField`` del stub de protobuf).

        Lo usa la normalización del esquema 1 (``schema_v1.py``), que
        reescribe un tipo inline como índice del pool y tiene que quitar el
        inline: si quedara, el mensaje llevaría el mismo dato dos veces.
        """
        if nombre not in self._desc.fields:
            raise ValueError(f"'{self._nombre}' no tiene el campo '{nombre}'")
        self._valores.pop(nombre, None)
        self._presentes.discard(nombre)

    def CopyFrom(self, otro: "Message") -> None:
        self._valores = dict(otro._valores)
        self._presentes = set(otro._presentes)
        self._marcar()

    def __bool__(self) -> bool:  # 'if msg.sub:' -> ¿tiene algo?
        return bool(self._presentes)

    def __repr__(self) -> str:  # pragma: no cover - depuracion
        return f"<{self._nombre} {sorted(self._presentes)}>"

    # -- serializacion ----------------------------------------------------- #
    def SerializeToString(self, deterministic: bool = True) -> bytes:
        """Los bytes del mensaje.

        ``deterministic`` se acepta por compatibilidad con el stub y se
        ignora: aquí la salida es determinista SIEMPRE. Los campos se
        escriben por número y las entradas de un ``map`` por clave, así que
        no hay un modo "rápido pero desordenado" del que haga falta salir.
        """
        salida = bytearray()
        # en ORDEN DE NUMERO DE CAMPO: es lo que hace el runtime de protobuf,
        # y es lo que hace que dos emisiones del mismo programa den los mismos
        # bytes (ver 'test_hir_reproducible').
        for numero in sorted(self._desc.by_number):
            desc = self._desc.by_number[numero]
            if desc.name not in self._valores:
                continue
            self._escribe_campo(salida, desc, self._valores[desc.name])
        return bytes(salida)

    def _escribe_campo(self, salida: bytearray, desc: Field, valor: Any) -> None:
        esq = self._esquema
        if desc.is_map:
            # un map es 'repeated Entry { key = 1; value = 2; }'. Se ordena
            # por clave: el orden de un diccionario no es parte del dato, y
            # sin fijarlo el .phir dejaria de ser reproducible.
            for clave in sorted(valor):
                entrada = bytearray()
                _campo_bytes(entrada, 1, clave.encode("utf-8"))
                _campo_bytes(entrada, 2, valor[clave].SerializeToString())
                _campo_bytes(salida, desc.number, bytes(entrada))
            return

        clase = esq.kind_of(desc.type)
        if desc.repeated:
            if clase == "message":
                for hijo in valor:
                    _campo_bytes(salida, desc.number, hijo.SerializeToString())
                return
            if clase == "enum" or SCALARS[desc.type] == "varint":
                # EMPAQUETADO: proto3 empaqueta los escalares repetidos por
                # defecto, y el lector C++ y el web esperan justo eso.
                if not valor:
                    return
                cuerpo = bytearray()
                for item in valor:
                    _escribe_varint(cuerpo, int(item))
                _campo_bytes(salida, desc.number, bytes(cuerpo))
                return
            for item in valor:
                _escribe_escalar(salida, desc, item)
            return

        if clase == "message":
            _campo_bytes(salida, desc.number, valor.SerializeToString())
            return
        # PRESENCIA: proto3 no serializa un escalar que valga su default...
        # salvo si es miembro de un 'oneof', que SIEMPRE tiene presencia
        # explicita. Sin esa excepcion un literal '0' se escribia como
        # "ningun campo del oneof presente", que en este esquema significa
        # 'null' — el programa cambiaba de sentido al serializarse.
        obligatorio = desc.oneof is not None
        if clase == "enum":
            if valor or obligatorio:
                _etiqueta(salida, desc.number, _WIRE_VARINT)
                _escribe_varint(salida, int(valor))
            return
        if not obligatorio and valor == DEFAULTS[desc.type]:
            return
        _escribe_escalar(salida, desc, valor)

    # -- deserializacion --------------------------------------------------- #
    def ParseFromString(self, datos: bytes) -> None:
        self._valores.clear()
        self._presentes.clear()
        self._leer(datos, 0, len(datos))

    def _leer(self, datos: bytes, pos: int, fin: int) -> None:
        esq = self._esquema
        while pos < fin:
            etiqueta, pos = _lee_varint(datos, pos)
            numero, tipo_wire = etiqueta >> 3, etiqueta & 7
            desc = self._desc.by_number.get(numero)
            if desc is None:
                pos = _salta(datos, pos, tipo_wire)
                continue
            if desc.is_map:
                largo, pos = _lee_varint(datos, pos)
                entrada = _leer_entrada_map(datos, pos, pos + largo,
                                            desc.type, esq)
                self.__getattr__(desc.name)  # materializa el MapField
                dict.__setitem__(self._valores[desc.name], entrada[0],
                                 entrada[1])
                self._presentes.add(desc.name)
                pos += largo
                continue
            clase = esq.kind_of(desc.type)
            if clase == "message":
                largo, pos = _lee_varint(datos, pos)
                hijo = Message(desc.type, esq, dueno=None)
                hijo._leer(datos, pos, pos + largo)
                pos += largo
                if desc.repeated:
                    self.__getattr__(desc.name).append(hijo)
                    self._presentes.add(desc.name)
                else:
                    self._valores[desc.name] = hijo
                    self._marcar_oneof(desc)
                continue
            # escalar o enum
            if desc.repeated and tipo_wire == _WIRE_BYTES \
                    and (clase == "enum" or SCALARS[desc.type] != "bytes"):
                largo, pos = _lee_varint(datos, pos)      # bloque empaquetado
                limite = pos + largo
                destino = self.__getattr__(desc.name)
                while pos < limite:
                    item, pos = _lee_escalar(datos, pos, desc, _WIRE_VARINT, esq)
                    destino.append(item)
                self._presentes.add(desc.name)
                continue
            valor, pos = _lee_escalar(datos, pos, desc, tipo_wire, esq)
            if desc.repeated:
                self.__getattr__(desc.name).append(valor)
                self._presentes.add(desc.name)
            else:
                self._valores[desc.name] = valor
                self._marcar_oneof(desc)

    def _marcar_oneof(self, desc: Field) -> None:
        self._presentes.add(desc.name)
        if desc.oneof is not None:
            for hermano in self._desc.oneofs[desc.oneof]:
                if hermano != desc.name:
                    self._presentes.discard(hermano)
                    self._valores.pop(hermano, None)


# --------------------------------------------------------------------------- #
# auxiliares de bajo nivel
# --------------------------------------------------------------------------- #

def _etiqueta(salida: bytearray, numero: int, tipo_wire: int) -> None:
    _escribe_varint(salida, (numero << 3) | tipo_wire)


def _campo_bytes(salida: bytearray, numero: int, cuerpo: bytes) -> None:
    _etiqueta(salida, numero, _WIRE_BYTES)
    _escribe_varint(salida, len(cuerpo))
    salida.extend(cuerpo)


def _escribe_escalar(salida: bytearray, desc: Field, valor: Any) -> None:
    forma = SCALARS[desc.type]
    if forma == "bytes":
        _campo_bytes(salida, desc.number, valor.encode("utf-8"))
    elif forma == "f64":
        _etiqueta(salida, desc.number, _WIRE_F64)
        salida.extend(struct.pack("<d", float(valor)))
    elif forma == "f32":
        _etiqueta(salida, desc.number, _WIRE_F32)
        salida.extend(struct.pack("<f", float(valor)))
    else:
        _etiqueta(salida, desc.number, _WIRE_VARINT)
        _escribe_varint(salida, int(valor))


def _lee_escalar(datos: bytes, pos: int, desc: Field, tipo_wire: int,
                 esq: Schema) -> tuple:
    if esq.kind_of(desc.type) == "enum":
        valor, pos = _lee_varint(datos, pos)
        return valor, pos
    forma = SCALARS[desc.type]
    if forma == "bytes":
        largo, pos = _lee_varint(datos, pos)
        return datos[pos:pos + largo].decode("utf-8"), pos + largo
    if forma == "f64":
        return struct.unpack_from("<d", datos, pos)[0], pos + 8
    if forma == "f32":
        return struct.unpack_from("<f", datos, pos)[0], pos + 4
    crudo, pos = _lee_varint(datos, pos)
    if desc.type == "bool":
        return bool(crudo), pos
    if desc.type in ("int32", "int64"):
        return _con_signo(crudo), pos
    return crudo, pos


def _leer_entrada_map(datos: bytes, pos: int, fin: int, tipo: str,
                      esq: Schema) -> tuple:
    clave = ""
    valor = Message(tipo, esq, dueno=None)
    while pos < fin:
        etiqueta, pos = _lee_varint(datos, pos)
        numero, tipo_wire = etiqueta >> 3, etiqueta & 7
        largo, pos = _lee_varint(datos, pos)
        if numero == 1:
            clave = datos[pos:pos + largo].decode("utf-8")
        elif numero == 2:
            valor._leer(datos, pos, pos + largo)
        pos += largo
    return clave, valor


def _salta(datos: bytes, pos: int, tipo_wire: int) -> int:
    """Un campo que el esquema no conoce: se salta, no se inventa."""
    if tipo_wire == _WIRE_VARINT:
        _, pos = _lee_varint(datos, pos)
        return pos
    if tipo_wire == _WIRE_F64:
        return pos + 8
    if tipo_wire == _WIRE_F32:
        return pos + 4
    if tipo_wire == _WIRE_BYTES:
        largo, pos = _lee_varint(datos, pos)
        return pos + largo
    raise DecodeError(f"tipo de wire desconocido ({tipo_wire}) en {pos}")


# --------------------------------------------------------------------------- #
# el formato de TEXTO
# --------------------------------------------------------------------------- #
# La vista legible del HIR ('--emit-hir --text', el playground, el golden).
# Es el mismo formato que imprime 'text_format.MessageToString' de protobuf,
# reproducido aqui por la misma razon que el resto del modulo: era la ultima
# llamada que ataba el proyecto a la libreria.

_ESCAPES = {
    ord("\n"): "\\n", ord("\r"): "\\r", ord("\t"): "\\t",
    ord('"'): '\\"', ord("'"): "\\'", ord("\\"): "\\\\",
}


def _cadena(texto: str) -> str:
    """Una cadena como la escribe protobuf: comillas dobles y escapes de C.

    Los bytes no imprimibles salen en OCTAL (``\\303``), no en hexadecimal ni
    como el carácter: es lo que hace 'text_format', y el volcado tiene que
    coincidir byte a byte con el que se guardó como golden.
    """
    salida = ['"']
    for byte in texto.encode("utf-8"):
        if byte in _ESCAPES:
            salida.append(_ESCAPES[byte])
        elif 0x20 <= byte < 0x7F:
            salida.append(chr(byte))
        else:
            salida.append("\\%03o" % byte)
    salida.append('"')
    return "".join(salida)


def _escalar_texto(valor: Any, tipo: str) -> str:
    if tipo == "string":
        return _cadena(valor)
    if tipo == "bool":
        return "true" if valor else "false"
    if tipo in ("double", "float"):
        return repr(float(valor))
    return str(valor)


def message_to_text(msg: "Message", sangria: int = 0) -> str:
    """El mensaje en el formato de texto de protobuf."""
    lineas: List[str] = []
    espacio = "  " * sangria
    esq = msg._esquema
    for numero in sorted(msg._desc.by_number):
        desc = msg._desc.by_number[numero]
        if desc.name not in msg._valores:
            continue
        valor = msg._valores[desc.name]
        if desc.is_map:
            for clave in sorted(valor):
                lineas.append(f"{espacio}{desc.name} {{")
                lineas.append(f"{espacio}  key: {_cadena(clave)}")
                lineas.append(f"{espacio}  value {{")
                cuerpo = message_to_text(valor[clave], sangria + 2)
                if cuerpo:
                    lineas.append(cuerpo)
                lineas.append(f"{espacio}  }}")
                lineas.append(f"{espacio}}}")
            continue
        clase = esq.kind_of(desc.type)
        # la MISMA regla de presencia que al serializar: un escalar que vale
        # su default no esta, salvo dentro de un 'oneof'. Sin esto el texto
        # mostraria campos que el .phir no lleva.
        if not desc.repeated and clase != "message" and desc.oneof is None:
            defecto = 0 if clase == "enum" else DEFAULTS[desc.type]
            if valor == defecto:
                continue
        items = valor if desc.repeated else [valor]
        for item in items:
            if clase == "message":
                lineas.append(f"{espacio}{desc.name} {{")
                cuerpo = message_to_text(item, sangria + 1)
                if cuerpo:
                    lineas.append(cuerpo)
                lineas.append(f"{espacio}}}")
            elif clase == "enum":
                nombre = next((k for k, v in esq.enums[desc.type].items()
                               if v == item), str(item))
                lineas.append(f"{espacio}{desc.name}: {nombre}")
            else:
                lineas.append(
                    f"{espacio}{desc.name}: {_escalar_texto(item, desc.type)}")
    return "\n".join(lineas)


__all__ = ["Message", "DecodeError", "SchemaError", "message_to_text"]
