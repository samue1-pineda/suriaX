"""unit/tipos — resolución de tipos, tabla de símbolos, hooks y conversiones.

Cubre el AST-tipado (``restype``) y las estructuras que la Semántica publica
hacia el HIR: símbolos, hooks por ``(dueño, kind)`` y la tabla de casts por
``(origen, destino)``.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import analyze, typed  # noqa: E402
from include import ast_nodes as ast  # noqa: E402
from include.types_ast import PRIMITIVE_TYPES, TypeKind  # noqa: E402
from src.frontend.semantic.hooks import HookKind  # noqa: E402
from src.frontend.semantic.symbol_table import SymbolKind  # noqa: E402


def _first_body(program):
    return program.items[0].body.statements


def test_literales_reciben_su_tipo():
    program, _ = typed("fn f() -> void { var int a = 1; var float b = 2.5; "
                       'var str c = "x"; var bool d = true; };')
    values = [s.value for s in _first_body(program)]
    assert values[0].restype is PRIMITIVE_TYPES["int"]
    assert values[1].restype is PRIMITIVE_TYPES["float"]
    assert values[2].restype is PRIMITIVE_TYPES["str"]
    assert values[3].restype is PRIMITIVE_TYPES["bool"]


def test_null_no_recibe_tipo_en_ast_tipado():
    """'null' se unifica en Semántica, no en AST-tipado."""
    program, _ = typed("fn f() -> void { var int? a = null; };")
    assert _first_body(program)[0].value.restype is None


def test_puntero_y_nullable_estructurales():
    program, _ = typed("fn f() -> void { var int ptr mutable p = null; };")
    t = _first_body(program)[0].restype
    assert t.kind is TypeKind.POINTER and t.mut is True
    assert t.inner is PRIMITIVE_TYPES["int"]


def test_tipo_error_resuelto():
    program, _ = typed("fn f() -> error int { return 1; };")
    t = program.items[0].return_restype
    assert t.kind is TypeKind.ERROR
    assert t.inner is PRIMITIVE_TYPES["int"]


def test_addr_of_hereda_mutabilidad_del_binding():
    """&x sobre 'var' -> ptr mutable; sobre 'const' -> ptr (solo lectura)."""
    program, _, errors = analyze(
        "fn f() -> void { var int a = 1; const int b = 2; "
        "var int ptr p = &a; var int ptr q = &b; };"
    )
    assert not errors, errors
    body = _first_body(program)
    assert body[2].value.mut is True, "&var debe dar ptr mutable"
    assert body[3].value.mut is False, "&const debe dar ptr de solo lectura"


def test_restype_anotado_en_toda_expresion():
    """La Semántica anota el tipo de las expresiones para el HIR."""
    program, _, errors = analyze("fn f() -> void { var int a = 1; var int b = a + 1; };")
    assert not errors, errors
    binop = _first_body(program)[1].value
    assert binop.restype is PRIMITIVE_TYPES["int"], (
        "un BinaryOp debe llevar su restype anotado"
    )


def test_simbolos_globales_en_la_tabla():
    _, table, errors = analyze(
        "struct { int x; } P;\nenum E { A, B };\nfn g() -> int { return 1; };"
    )
    assert not errors, errors
    assert table.global_scope.types["P"].kind is SymbolKind.STRUCT
    assert table.global_scope.types["E"].kind is SymbolKind.ENUM
    assert table.global_scope.values["g"].kind is SymbolKind.FUNCTION


def test_campos_de_struct_en_members():
    _, table, _ = analyze("struct { int x; float y; } P;")
    members = table.global_scope.types["P"].members
    assert sorted(members) == ["x", "y"]
    assert members["y"].type is PRIMITIVE_TYPES["float"]


def test_hook_registrado_por_dueno_y_kind():
    _, table, errors = analyze(
        "struct { int x; } P;\nhook fn __print__(P ptr p) -> void { };"
    )
    assert not errors, errors
    assert table.lookup_hook("P", HookKind.PRINT) is not None


def test_varios_cast_por_tipo_en_la_tabla():
    """La tabla de conversiones se indexa por PAR (origen, destino)."""
    _, table, errors = analyze(
        "const type int8;\n"
        "hook fn __cast__(int x) -> int8;\n"
        "hook fn __cast__(int8 x) -> int;\n"
        "hook fn __cast__(float x) -> int8;\n"
    )
    assert not errors, errors
    assert len(table.casts) == 3, f"se esperaban 3 conversiones, hay {len(table.casts)}"


def test_hook_duplicado_del_mismo_kind_es_error():
    codes = [e.code for e in analyze(
        "struct { int x; } P;\n"
        "hook fn __print__(P ptr a) -> void { };\n"
        "hook fn __print__(P ptr b) -> void { };\n"
    )[2]]
    assert "SEM007" in codes, codes


def test_is_assignable_coerciones():
    """Reglas del servicio de tipos (no comparar Type a mano)."""
    from include.types_ast import nullable_of, pointer_of
    from src.frontend.semantic import type_service

    INT = PRIMITIVE_TYPES["int"]
    assert type_service.is_assignable(INT, INT)
    # T -> T?
    assert type_service.is_assignable(nullable_of(INT), INT)
    # ptr mutable T -> ptr T (soltar permiso de escritura es seguro)
    assert type_service.is_assignable(pointer_of(INT), pointer_of(INT, mut=True))
    # ...pero NO al revés (ganar permisos)
    assert not type_service.is_assignable(pointer_of(INT, mut=True), pointer_of(INT))
    # la coerción compone DENTRO de un nullable
    assert type_service.is_assignable(
        nullable_of(pointer_of(INT)), pointer_of(INT, mut=True),
    )
    # tipos desconocidos: permisivo (cero falsos positivos)
    assert type_service.is_assignable(None, INT)
    assert type_service.is_assignable(INT, None)


def test_error_es_transparente_en_la_ruta_de_exito():
    """Una 'fn -> error int' se asigna a un int (el fallo va por throw)."""
    _, _, errors = analyze(
        "fn puede_fallar() -> error int { return 1; };\n"
        "fn f() -> void { var int x = puede_fallar(); };"
    )
    assert not errors, errors
