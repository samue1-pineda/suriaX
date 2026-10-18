"""unit/hir_enum_scope — los valores de enum del ``.proto`` no se repiten.

En protobuf los valores de un enum son HERMANOS del enum (ámbito del
paquete, o del mensaje que lo contiene, como en C++), no hijos suyos. Dos
enums del mismo ámbito no pueden compartir un nombre de valor: ``protoc``
rechaza el archivo y el modelo C++ generado de él (``hir_modelo.hpp``) no
compila.

Pasó de verdad: ``TypeKind.FUNCTION = 13`` chocó con ``SymbolKind.FUNCTION``
y nadie lo vio, porque en esta máquina no hay ``protoc`` y el lector propio
(``V0/src/HIR/schema.py``) no lo comprobaba. Ahora el lector lo rechaza y la
suite lo ve sin depender de herramientas externas.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import helpers  # noqa: E402,F401  (pone V0 en sys.path)

from src.HIR import schema  # noqa: E402

_PROTO = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "V0", "src", "HIR", "proto", "hir.proto")


def _rejects(text: str) -> str:
    try:
        schema.parse(text)
    except schema.SchemaError as exc:
        return str(exc)
    raise AssertionError("el lector aceptó un valor de enum repetido")


def test_the_hir_proto_has_no_repeated_enum_value():
    with open(_PROTO, encoding="utf-8") as fh:
        parsed = schema.parse(fh.read())
    assert parsed.enums["TypeKind"]["FUNCTION_TYPE"] == 13
    assert parsed.enums["SymbolKind"]["FUNCTION"] == 1


def test_two_package_enums_cannot_share_a_value_name():
    msg = _rejects("syntax = \"proto3\";\n"
                   "enum A {\n  A_NONE = 0;\n  SAME = 1;\n}\n"
                   "enum B {\n  B_NONE = 0;\n  SAME = 1;\n}\n")
    assert "'SAME'" in msg and "'A'" in msg and "'B'" in msg
    assert "del paquete" in msg


def test_enums_in_different_messages_may_share_a_value_name():
    schema.parse("syntax = \"proto3\";\n"
                 "message M {\n  enum A {\n    A_NONE = 0;\n    SAME = 1;\n  }\n}\n"
                 "message N {\n  enum B {\n    B_NONE = 0;\n    SAME = 1;\n  }\n}\n")


def test_two_enums_in_the_same_message_cannot_share_a_value_name():
    msg = _rejects("syntax = \"proto3\";\n"
                   "message M {\n"
                   "  enum A {\n    A_NONE = 0;\n    SAME = 1;\n  }\n"
                   "  enum B {\n    B_NONE = 0;\n    SAME = 1;\n  }\n}\n")
    assert "del mensaje 'M'" in msg
