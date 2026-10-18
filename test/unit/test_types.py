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


# --------------------------------------------------------------------------- #
# un tipo OPACO ('const type T;') vale en todas las posiciones de un nominal
# --------------------------------------------------------------------------- #
# 'const type' es la vía para que un tipo NO primitivo exista sin cablearlo en
# el compilador: es lo que usa 'lib/d_types' para int8/float32 y lo que usará
# cualquier handle del sistema. La cobertura estaba repartida (la gramática
# probaba su visibilidad, 'ancho_fijo' su __sizeof__), pero ninguna prueba
# fijaba que el tipo se comporte como un nominal CUALQUIERA allí donde se
# escriba un tipo — que es justo lo que lo hace utilizable.

_OPACO = "const type H;\n"


def _sin_errores(fuente: str) -> None:
    _program, _table, errors = analyze(fuente)
    assert not errors, [f"{e.code}: {e.message}" for e in errors]


def test_un_opaco_vale_como_parametro_y_como_retorno():
    _sin_errores(_OPACO + "fn recibe(H ptr h) -> void { };\n"
                          "fn crea() -> H ptr mutable;\n"
                          "fn main() -> int { return 0; };")


def test_un_opaco_vale_como_campo_y_por_valor():
    _sin_errores(_OPACO + "struct { H ptr dentro; } Caja;\n"
                          "fn porValor(H h) -> void { };\n"
                          "fn main() -> int { return 0; };")


def test_un_opaco_vale_como_argumento_de_un_generico():
    """Sin esto, un contenedor no podría guardar un handle del sistema."""
    _sin_errores(_OPACO + "struct { T v; } Caja<T>;\n"
                          "fn main() -> int { var Caja<H>? c = null; return 0; };")


def test_un_opaco_recibe_hooks_como_cualquier_nominal():
    """__sizeof__ y __cast__ despachan por tipo: el opaco es su destinatario
    natural (es como 'int8' tiene tamaño sin ser primitivo)."""
    _sin_errores(_OPACO +
                 "hook fn __sizeof__(H ptr h) -> int { return 8; };\n"
                 "hook fn __cast__(int n) -> H;\n"
                 "fn main() -> int { var H h = cast<H>(1); return sizeof(H); };")


def test_un_nominal_que_no_se_declaro_es_un_error_con_su_nombre():
    """El otro lado: usar un tipo inexistente no pasa en silencio."""
    _program, _table, errors = analyze(
        "fn f(Cosa ptr c) -> void { };\nfn main() -> int { return 0; };")
    assert [e.code for e in errors] == ["AST005"], errors
    assert "Cosa" in errors[0].message


# --------------------------------------------------------------------------- #
# un enum SIN payload es un entero con nombre
# --------------------------------------------------------------------------- #
# Lo es en el HIR, en el intérprete y en el target web, así que convertirlo no
# cambia el valor: solo se gana o se pierde el nombre. No entra en la tabla de
# conversiones nativas porque esa va por 'TypeKind' y un enum es NOMINAL —
# aceptarlo ahí habría abierto la conversión a cualquier struct.

_TTYPE = "enum TType { INT_LIT = 1, PLUS = 10 };\n"


def test_un_enum_se_convierte_a_int_y_de_vuelta():
    _sin_errores(_TTYPE + "fn main() -> int {\n"
                          "    var int n = cast<int>(TType.PLUS);\n"
                          "    var TType t = cast<TType>(1);\n"
                          "    return n;\n"
                          "};")


def test_convertir_desde_un_valor_que_el_enum_no_declara_se_rechaza():
    """Sin esto, 'cast<TType>(999)' produciría un valor de un tipo que no lo
    tiene, y el 'match' exhaustivo que el compilador verifica dejaría de
    cubrirlo."""
    _program, _table, errors = analyze(
        _TTYPE + "fn main() -> int { var TType t = cast<TType>(999); "
                 "return 0; };")
    assert [e.code for e in errors] == ["SEM016"], errors
    assert "999" in errors[0].message and "PLUS=10" in errors[0].message


def test_un_valor_calculado_no_se_puede_comprobar_y_pasa():
    """Cero falsos positivos: lo que no se ve al compilar, no se afirma."""
    _sin_errores(_TTYPE + "fn main() -> int {\n"
                          "    var int n = 10;\n"
                          "    var TType t = cast<TType>(n);\n"
                          "    return 0;\n"
                          "};")


def test_un_struct_no_se_convierte_a_int_por_ser_nominal():
    """La regla es del ENUM, no de los nominales."""
    _program, _table, errors = analyze(
        "struct { int v; } P;\n"
        "fn main() -> int { var P p = P{ v: 1 }; return cast<int>(p); };")
    assert [e.code for e in errors] == ["SEM016"], errors


def test_el_nombre_de_un_item_se_resuelve_al_compilar():
    """``TType.PLUS.name`` -> ``"PLUS"``: se sabe sin ejecutar nada, así que
    viaja como el literal que es y no hay tabla que consultar en ejecución."""
    program, _table, errors = analyze(
        _TTYPE + 'fn main() -> int { var str s = TType.PLUS.name; '
                 "return 0; };")
    assert not errors, errors
    decl = program.items[1].body.statements[0]
    assert decl.value.nombre_de_item == "PLUS"


def test_pedirle_el_nombre_al_enum_y_no_a_un_item_lo_dice():
    _program, _table, errors = analyze(
        _TTYPE + "fn main() -> int { var str s = TType.name; return 0; };")
    assert errors, "'TType.name' no nombra ningún item"
    assert "item" in errors[0].message


# --------------------------------------------------------------------------- #
# no hay VERACIDAD: una condición es 'bool' o no es
# --------------------------------------------------------------------------- #
# 'if (1)' era una coerción implícita, justo lo que el lenguaje prohíbe en
# todos los demás sitios. Y las consecuencias se veían: el frontend lo
# aceptaba, el intérprete lo ejecutaba con la veracidad de Python y el target
# web lo rechazaba porque WASM exige un i32 en la condición. Tres respuestas
# para el mismo programa.

def test_una_condicion_que_no_es_bool_se_rechaza():
    for condicion in ("1", "0", '"x"', "1.5", "'c'"):
        _program, _table, errors = analyze(
            "fn main() -> int { if (%s) { return 1; }; return 0; };" % condicion)
        assert [e.code for e in errors] == ["AST006"], (condicion, errors)
        assert "bool" in errors[0].message


def test_el_while_sigue_la_misma_regla():
    _program, _table, errors = analyze(
        "fn main() -> int { while (1) { break; }; return 0; };")
    assert [e.code for e in errors] == ["AST006"], errors


def test_la_comparacion_es_lo_que_se_escribe():
    _sin_errores("fn main() -> int {\n"
                 "    var int x = 1;\n"
                 "    if (x != 0) { return 1; };\n"
                 "    while (x < 10) { x = x + 1; };\n"
                 "    return 0;\n"
                 "};")
