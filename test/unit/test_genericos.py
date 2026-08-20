"""Tipos genéricos: ``struct { ... } Vector<T>;`` y ``Vector<int>``.

Los parámetros van con el NOMBRE, al final, que es donde suriaX pone siempre
lo que identifica una declaración. Escribirlos es lo que hace comprobable la
aridad; sin ellos, ``Vector<int, str>`` no se podría rechazar.

Lo que este archivo fija es la propiedad de la que depende todo lo demás: que
la SUSTITUCIÓN ocurra. Un genérico cuyos campos y firmas siguieran hablando
de ``T`` después de instanciarlo sería sintaxis sin significado.
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "V0"),
           os.path.join(_REPO_ROOT, "test")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from helpers import assert_has_code, assert_ok, parse  # noqa: E402

#: un genérico con un campo del parámetro, su hook de indexado y un método.
VEC = (
    "struct { T ptr mutable d; int n; } Vector<T>;\n"
    "hook fn __index__(Vector<T> ptr self, int i) -> T { return self.d[i]; }\n"
    "@impl Vector { fn get(Vector<T> ptr self, int i) -> T { return self.d[i]; } }\n"
)


# --------------------------------------------------------------------------- #
# declaración
# --------------------------------------------------------------------------- #

def test_un_struct_declara_sus_parametros_con_el_nombre():
    from include import ast_nodes as ast
    program, errors, _lex = parse("struct { T ptr d; int n; } Vector<T>;")
    assert not errors, [e.message for e in errors]
    decl = next(i for i in program.items if isinstance(i, ast.StructDecl))
    assert decl.type_params == ["T"]


def test_un_tipo_opaco_tambien_puede_ser_generico():
    from include import ast_nodes as ast
    program, errors, _lex = parse("const type Caja<T>;\nconst type Par<A, B>;")
    assert not errors, [e.message for e in errors]
    decls = [i for i in program.items if isinstance(i, ast.TypeDecl)]
    assert [d.type_params for d in decls] == [["T"], ["A", "B"]]


def test_un_parametro_no_puede_ser_un_tipo_ya_escrito():
    """``Vector<int>`` en una DECLARACIÓN estaría declarando un parámetro
    llamado 'int', que no significa nada. El mensaje lo dice."""
    _program, errors, _lex = parse("struct { int a; } Malo<int>;")
    assert errors, "debería rechazarse"
    assert "parametro de tipo" in errors[0].message


# --------------------------------------------------------------------------- #
# aridad
# --------------------------------------------------------------------------- #

def test_usar_un_generico_con_su_aridad():
    assert_ok(VEC + "fn f(Vector<int> v) -> void { };")


def test_demasiados_argumentos_de_tipo():
    assert_has_code(VEC + "fn f(Vector<int, str> v) -> void { };", "SEM027")


def test_un_generico_exige_sus_argumentos():
    assert_has_code(VEC + "fn f(Vector v) -> void { };", "SEM027")


def test_un_tipo_corriente_no_admite_argumentos():
    assert_has_code("struct { int a; } P;\nfn f(P<int> p) -> void { };",
                    "SEM027")


def test_un_argumento_de_tipo_se_valida_como_cualquier_tipo():
    assert_has_code(VEC + "fn f(Vector<Fantasma> v) -> void { };", "AST005")


def test_los_genericos_anidan():
    assert_ok(VEC + "fn f(Vector<Vector<int>> v) -> void { };")


# --------------------------------------------------------------------------- #
# sustitución: lo que hace que el genérico signifique algo
# --------------------------------------------------------------------------- #

def test_un_campo_del_parametro_toma_el_argumento():
    assert_ok(VEC + "fn f(Vector<int> v) -> void { "
              "var int ptr mutable p = v.d; };")


def test_un_campo_sustituido_no_unifica_con_otro_tipo():
    assert_has_code(VEC + "fn f(Vector<int> v) -> void { "
                    "var str ptr mutable p = v.d; };", "AST006")


def test_el_indexado_devuelve_el_argumento():
    assert_ok(VEC + "fn f(Vector<int> v) -> void { var int x = v[0]; };")


def test_el_indexado_de_otra_instancia_devuelve_otro_tipo():
    assert_ok(VEC + "fn f(Vector<str> v) -> void { var str x = v[0]; };")


def test_el_indexado_mal_asignado_se_rechaza():
    assert_has_code(VEC + "fn f(Vector<int> v) -> void { var str x = v[0]; };",
                    "AST006")


def test_un_metodo_devuelve_el_argumento():
    assert_ok(VEC + "fn f(Vector<int> v) -> void { var int x = v.get(0); };")


def test_un_metodo_mal_asignado_se_rechaza():
    assert_has_code(VEC + "fn f(Vector<int> v) -> void { "
                    "var str x = v.get(0); };", "AST006")


def test_un_campo_no_generico_no_cambia():
    assert_ok(VEC + "fn f(Vector<int> v) -> void { var int n = v.n; };")


# --------------------------------------------------------------------------- #
# identidad
# --------------------------------------------------------------------------- #

def test_dos_instancias_distintas_son_tipos_distintos():
    """Es todo el punto: si ``Vector<int>`` y ``Vector<str>`` fueran el mismo
    tipo, los genéricos no darían ninguna garantía."""
    from include.types_ast import PRIMITIVE_TYPES, nominal
    vi = nominal("Vector", (PRIMITIVE_TYPES["int"],))
    vs = nominal("Vector", (PRIMITIVE_TYPES["str"],))
    v = nominal("Vector")
    assert vi != vs and vi != v
    assert len({vi, vs, v}) == 3, "Type tiene que seguir siendo hashable"
    assert repr(vi) == "Vector<int>"


def test_los_argumentos_viajan_en_el_hir():
    from helpers import lex
    from src.frontend.parser.parser import Parser
    from src.frontend.parser.typed_ast import resolve_types
    from src.frontend.semantic import analyze
    from src.HIR.emmit_IR import build_module

    fuente = (VEC + "fn f(Vector<int> v) -> void { };\n"
              "fn main() -> int { return 0; };")
    tokens, _ = lex(fuente)
    parser = Parser(tokens)
    program = parser.parse()
    resolve_types(program)
    table, errors = analyze(program, source_path="<test>")
    assert not errors, [e.message for e in errors]
    module, hir_errors = build_module(program, table, source_file="<test>")
    assert not hir_errors, [e.message for e in hir_errors]
    con_args = [t for t in module.types if t.name == "Vector" and t.args]
    assert con_args, "el pool no lleva ningún 'Vector' con argumentos"
    assert con_args[0].args[0].kind == 3  # INT


# --------------------------------------------------------------------------- #
# invarianza: la identidad tiene que llegar hasta el CHECKER
# --------------------------------------------------------------------------- #
#: un genérico instanciable (campo por valor), para escribir sus literales.
CAJA = "struct { T valor; int n; } Caja<T>;\n"


def test_una_instancia_no_es_asignable_a_otra():
    """``Vector<int>`` y ``Vector<str>`` ya eran ``Type`` distintos; lo que
    esta prueba fija es que ``is_assignable`` LO VEA. Comparar solo el
    nombre-hoja los unificaba, y el genérico quedaba en decoración: el
    compilador aceptaba pasar uno donde se pedía el otro."""
    assert_has_code(CAJA + "fn f(Caja<str> s) -> void { "
                    "var Caja<int> c = s; };", "AST006")


def test_un_argumento_no_asignable_al_parametro_se_rechaza():
    assert_has_code(CAJA + "fn g(Caja<int> c) -> void { };\n"
                    "fn f(Caja<str> s) -> void { g(s); };", "AST006")


def test_devolver_otra_instancia_se_rechaza():
    assert_has_code(CAJA + "fn f(Caja<str> s) -> Caja<int> { return s; };",
                    "AST012")


def test_la_misma_instancia_si_pasa():
    assert_ok(CAJA + "fn g(Caja<int> c) -> void { };\n"
              "fn f(Caja<int> c) -> void { g(c); };")


def test_los_argumentos_son_invariantes():
    """``ptr mutable T`` se degrada a ``ptr T`` suelto, pero NO dentro de un
    argumento de tipo: leer un ``Caja<int ptr mutable>`` como
    ``Caja<int ptr>`` dejaría escribir por un puntero que se creyó de solo
    lectura."""
    from include.types_ast import PRIMITIVE_TYPES, nominal, pointer_of
    from src.frontend.semantic import type_service
    entero = PRIMITIVE_TYPES["int"]
    mut = nominal("Caja", (pointer_of(entero, mut=True),))
    ro = nominal("Caja", (pointer_of(entero),))
    assert not type_service.is_assignable(ro, mut)
    assert not type_service.is_assignable(mut, ro)
    # suelto (fuera del argumento) la degradación sí es válida
    assert type_service.is_assignable(pointer_of(entero),
                                      pointer_of(entero, mut=True))


# --------------------------------------------------------------------------- #
# construcción: 'Caja<int>{ ... }'
# --------------------------------------------------------------------------- #

def test_un_literal_lleva_sus_argumentos_de_tipo():
    from include import ast_nodes as ast
    program, errors, _lex = parse(
        "fn f() -> void { var Caja<int> c = Caja<int>{ v: 1 }; };")
    assert not errors, [e.message for e in errors]
    literal = program.items[0].body.statements[0].value
    assert isinstance(literal, ast.StructLiteral)
    assert literal.type_name == "Caja"
    assert len(literal.type_args) == 1


def test_un_literal_construye_la_instancia_que_se_anota():
    assert_ok(CAJA + "fn f() -> void { "
              "var Caja<int> c = Caja<int>{ valor: 1, n: 0 }; };")


def test_un_literal_de_otra_instancia_no_encaja():
    assert_has_code(CAJA + "fn f() -> void { "
                    "var Caja<int> c = Caja<str>{ valor: \"a\", n: 0 }; };",
                    "AST006")


def test_un_literal_sin_argumentos_sobre_un_generico_se_rechaza():
    """La aridad se comprueba con la MISMA regla que en una anotación."""
    assert_has_code(CAJA + "fn f() -> void { "
                    "var Caja<int> c = Caja{ valor: 1, n: 0 }; };", "SEM027")


def test_el_valor_de_un_campo_se_verifica_ya_sustituido():
    assert_has_code(CAJA + "fn f() -> void { "
                    "var Caja<int> c = Caja<int>{ valor: \"a\", n: 0 }; };",
                    "AST006")


def test_el_menor_que_sigue_siendo_una_comparacion():
    """El literal genérico es la única posición del lenguaje donde ``<`` es
    ambiguo. Se resuelve mirando si tras el ``>`` viene un ``{``; si no, el
    parser RETROCEDE y ``a < b`` vuelve a ser lo que siempre fue."""
    assert_ok("fn f(int a, int b) -> bool { return a < b; };")
    assert_ok("fn f(int a, int b, int c) -> bool { return a < b > c; };")
