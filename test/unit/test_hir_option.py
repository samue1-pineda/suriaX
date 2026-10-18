"""unit/hir_option — cómo viaja el paso 3 ("Option") en el HIR.

Dos campos ADITIVOS (``schema_version`` sigue en 2) y un operador:

- ``CaseArm.binds`` (3): ``case v`` sobre un ``T?`` LIGA el contenido. El
  patrón es un ``Identifier`` con el tipo ``T``; sin el campo, un lector lo
  leería como comparar con una variable ``v``, y por eso la VM lo rechaza.
- ``EnumDecl.type_params`` (3): los parámetros de un enum genérico; una
  instancia es un ``NOMINAL`` con sus ``args``.
- ``x ?? d`` es un ``BinaryOp`` con ``op == "??"``: no hace falta un mensaje
  nuevo, y un lector que no lo conoce ya lo rechaza por su nombre.

Lo aditivo se comprueba de verdad: un programa sin estas construcciones no
lleva ninguno de los campos nuevos.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import lex  # noqa: E402

_NULLABLE = 8
_NOMINAL = 9


def _module(source: str):
    from src.frontend.parser.parser import Parser
    from src.frontend.parser.typed_ast import resolve_types
    from src.frontend.semantic import analyze
    from src.HIR.emmit_IR import build_module

    tokens, lex_errors = lex(source)
    assert not lex_errors, [e.code for e in lex_errors]
    parser = Parser(tokens)
    program = parser.parse()
    assert not parser.ctx.errors, [e.code for e in parser.ctx.errors]
    resolve_types(program)
    table, sem_errors = analyze(program, source_path="<test>")
    assert not sem_errors, [e.code for e in sem_errors]
    module, hir_errors = build_module(program, table, source_file="<test>")
    assert not hir_errors, [e.code for e in hir_errors]
    return module


def _function(module, name: str):
    for d in module.items:
        if d.WhichOneof("node") == "function" and d.function.name == name:
            return d.function
    raise AssertionError(f"no hay funcion '{name}'")


def _match(module, name: str):
    for st in _function(module, name).body.statements:
        if st.WhichOneof("node") == "match_stmt":
            return st.match_stmt
    raise AssertionError("no hay match")


_OPTIONAL = """\
fn f(int? x) -> int {
    match (x) {
        case null { return 0; }
        case v { return v; }
    };
    return 1;
}
fn main() -> int { return f(2); }
"""


def test_case_v_carries_binds_and_the_content_type():
    module = _module(_OPTIONAL)
    arms = _match(module, "f").cases
    assert [a.binds for a in arms] == [False, True]
    patron = arms[1].pattern
    assert patron.WhichOneof("node") == "identifier" and patron.identifier.name == "v"
    assert module.types[patron.type_id].kind == 3        # INT: el contenido
    sujeto = _match(module, "f").subject
    assert module.types[sujeto.type_id].kind == _NULLABLE


def test_null_coalesce_is_a_binary_op():
    module = _module("fn f(int? x) -> int { return x ?? 7; }\n"
                     "fn main() -> int { return f(null); }\n")
    valor = _function(module, "f").body.statements[0].return_stmt.value
    assert valor.WhichOneof("node") == "binary" and valor.binary.op == "??"
    assert module.types[valor.type_id].kind == 3          # el resultado es 'int'


def test_a_generic_enum_carries_its_type_params():
    module = _module("enum Res<T, E> { Ok(T), Err(E) };\n"
                     "fn main() -> int {\n"
                     "    var Res<int, str> r = Res<int, str>.Ok(5);\n"
                     "    return 0;\n"
                     "}\n")
    enum = next(d.enum_decl for d in module.items
                if d.WhichOneof("node") == "enum_decl")
    assert list(enum.type_params) == ["T", "E"]
    ok = enum.items[0]
    assert [(module.types[t].kind, module.types[t].name)
            for t in ok.payload_type_ids] == [(_NOMINAL, "T")]
    construido = _function(module, "main").body.statements[0].var_decl.value
    tipo = module.types[construido.type_id]
    assert tipo.kind == _NOMINAL and tipo.name == "Res"
    assert [a.kind for a in tipo.args] == [3, 6]          # int, str


def test_the_new_fields_are_absent_without_the_constructs():
    """ADITIVO: sin ``case v`` ni un enum genérico, ningún campo nuevo se
    escribe (proto3 no serializa un ``false`` ni una lista vacía)."""
    module = _module("enum Color { ROJO, VERDE };\n"
                     "fn f(int? x) -> int {\n"
                     "    match (x) { case null { return 0; } case 7 { return 7; } };\n"
                     "    return 1;\n"
                     "}\n"
                     "fn main() -> int { return f(7); }\n")
    assert not any(a.binds for a in _match(module, "f").cases)
    enum = next(d.enum_decl for d in module.items
                if d.WhichOneof("node") == "enum_decl")
    assert list(enum.type_params) == []
    from src.HIR.wire import message_to_text
    texto = message_to_text(module)
    assert "binds" not in texto and "type_params" not in texto
