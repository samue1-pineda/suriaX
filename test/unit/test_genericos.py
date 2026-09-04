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
from include import ast_nodes as ast  # noqa: E402

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


# --------------------------------------------------------------------------- #
# la SUSTITUCIÓN llega a todas las preguntas sobre el tipo
# --------------------------------------------------------------------------- #
# Un campo de un genérico se declara como 'T', y 'T' no resuelve a nada. Cada
# pregunta que baje a los campos tiene que sustituir primero; las que no lo
# hacían daban respuestas falsas sobre el tipo CONCRETO, en silencio.

def test_un_generico_posee_lo_que_posee_su_argumento():
    """``Caja<R>`` con ``R`` que declara ``__free__`` POSEE recursos. Sin
    sustituir, su campo era 'T' —que no resuelve— así que 'Caja<R>' no poseía
    nada y su destructor no se ejecutaba nunca: una fuga silenciosa."""
    from helpers import analyze
    from src.frontend.semantic import type_service
    from include.types_ast import Type, TypeKind

    _, table, errores = analyze(
        "struct { int id; } R;\n"
        "hook fn __free__(R ptr r) -> void { };\n"
        "struct { T dentro; } Caja<T>;\n"
        "fn main() -> int { return 0; };")
    assert not errores, [e.code for e in errores]

    scope = table.global_scope
    caja_r = Type(TypeKind.NOMINAL, name="Caja",
                  args=(Type(TypeKind.NOMINAL, name="R"),))
    caja_int = Type(TypeKind.NOMINAL, name="Caja",
                    args=(Type(TypeKind.INT),))
    assert type_service.owns_resources(caja_r, scope, table)
    # ...y la misma plantilla con otro argumento NO posee: es lo que hace que
    # la respuesta sea del tipo concreto y no de la plantilla.
    assert not type_service.owns_resources(caja_int, scope, table)


def test_un_ciclo_que_pasa_por_un_generico_se_detecta():
    """``struct { Caja<S> c; } S;`` no tiene tamaño finito, y sin sustituir el
    ciclo era invisible porque el campo de 'Caja' es 'T'."""
    from helpers import error_codes
    codes = error_codes("struct { T dentro; } Caja<T>;\n"
                        "struct { Caja<S> c; } S;\n"
                        "fn main() -> int { return 0; };")
    assert "SEM026" in codes, codes


def test_un_ciclo_ajeno_al_objetivo_no_cuelga_el_analisis():
    """Regresión: la guarda comparaba el nombre de un TIPO contra la lista de
    nombres de CAMPO recorridos. Un ciclo que no incluye al tipo consultado
    (A -> B -> C -> B) no la disparaba y el recorrido no terminaba."""
    from helpers import error_codes
    codes = error_codes("struct { B b; } A;\n"
                        "struct { C c; } B;\n"
                        "struct { B otra; } C;\n"
                        "fn main() -> int { return 0; };")
    assert "SEM026" in codes, codes


# --------------------------------------------------------------------------- #
# genéricos de FUNCIÓN
# --------------------------------------------------------------------------- #
# Los de tipo ya existían; los de función eran el hueco que impedía que una
# librería como 'array.vector' guardara algo que no fuera 'int'. Se resuelven
# igual que el resto del lenguaje: ESCRIBIÉNDOLOS ('make<int>(6)'), con una
# deducción literal cuando el parámetro aparece en un argumento.

def test_una_funcion_generica_se_llama_con_su_argumento_de_tipo():
    assert_ok("fn primero<T>(T a) -> T { return a; };\n"
                 "fn main() -> int { return primero<int>(1); };")


def test_el_parametro_se_deduce_cuando_esta_en_un_argumento():
    """'primero(1)' no necesita '<int>': la T está en la firma del argumento."""
    assert_ok("fn primero<T>(T a) -> T { return a; };\n"
                 "fn main() -> int { return primero(1); };")


def test_el_retorno_se_sustituye_con_los_argumentos_de_la_llamada():
    """Sin esto la llamada entregaría un 'Caja<T>' con la T sin ligar, y nada
    unificaría con él."""
    assert_ok("struct { T v; } Caja<T>;\n"
                 "fn crea<T>(T x) -> Caja<T> { return Caja<T>{ v: x }; };\n"
                 "fn main() -> int { var Caja<int> c = crea<int>(7); "
                 "return c.v; };")


def test_la_aridad_de_los_argumentos_de_tipo_se_comprueba():
    assert_has_code("fn primero<T>(T a) -> T { return a; };\n"
                    "fn main() -> int { return primero<int, str>(1); };",
                    "SEM027")


def test_un_argumento_que_no_casa_con_el_tipo_escrito_se_rechaza():
    assert_has_code("fn primero<T>(T a) -> T { return a; };\n"
                    "fn main() -> int { return primero<str>(1); };",
                    "AST006")


def test_el_menor_que_sigue_siendo_una_comparacion():
    """'a < b' y 'make<int>(...)' comparten el '<'. Es la única posición
    ambigua del lenguaje y se resuelve MIRANDO qué hay tras el '>': un '('
    abre una llamada, un '{' un literal, y cualquier otra cosa retrocede."""
    assert_ok("fn main() -> int {\n"
                 "    var int a = 1; var int b = 2; var int c = 3;\n"
                 "    if (a < b and b < c) { return 1; };\n"
                 "    return 0;\n"
                 "};")


def test_un_metodo_de_un_generico_devuelve_el_tipo_instanciado():
    """'@impl Caja<T>': el receptor nombra la T que hay que ligar."""
    assert_ok("struct { T v; } Caja<T>;\n"
                 "@impl Caja<T> { fn get(Caja<T> ptr self) -> T "
                 "{ return self.v; } }\n"
                 "fn main() -> int { var Caja<int> c = Caja<int>{ v: 7 }; "
                 "return c.get(); };")


# --------------------------------------------------------------------------- #
# declaración de CONTENEDOR: 'int vec.Vector v[8];'
# --------------------------------------------------------------------------- #
# Es AZÚCAR y se deshace en el parser: la Semántica, el HIR y los backends ven
# exactamente el 'var' y la llamada que ya veían. Lo que se prueba aquí es que
# la forma nueva produzca ESO y no otra cosa.

_VECTOR = ("struct { T ptr mutable datos; int len; int cap; } Vector<T>;\n"
           "fn make<T>(int cap) -> Vector<T>;\n")


def test_la_declaracion_con_corchetes_es_el_var_de_siempre():
    program, errores, _lex = parse(
        "fn main() -> int { int Vector v[8]; return 0; };")
    assert not errores, errores
    decl = program.items[0].body.statements[0]
    assert isinstance(decl, ast.VarDecl)
    assert decl.name == "v"
    # el tipo es el contenedor INSTANCIADO con el elemento
    assert decl.type.name == "Vector"
    assert [a.name for a in decl.type.args] == ["int"]
    # y el valor, la llamada al constructor de su módulo
    assert isinstance(decl.value, ast.Call)
    assert [a.name for a in decl.value.type_args] == ["int"]


def test_el_constructor_se_busca_en_el_modulo_del_contenedor():
    """'vec.Vector' -> 'vec.make': la convención es de la librería, no de la
    gramática (el mismo criterio que pone 'print' en IO)."""
    program, errores, _lex = parse(
        "fn main() -> int { int vec.Vector v[8]; return 0; };")
    assert not errores, errores
    decl = program.items[0].body.statements[0]
    callee = decl.value.callee
    assert isinstance(callee, ast.MemberAccess)
    assert callee.obj.name == "vec" and callee.member == "make"


def test_una_declaracion_corriente_sigue_teniendo_un_solo_tipo():
    """El retroceso del parser no puede tragarse 'int x;'."""
    program, errores, _lex = parse(
        "fn main() -> int { int x = 1; return x; };")
    assert not errores, errores
    decl = program.items[0].body.statements[0]
    assert isinstance(decl, ast.VarDecl) and decl.name == "x"
    assert decl.type.name == "int" and decl.capacity is None


def test_reservar_sin_contenedor_dice_que_falta():
    _program, errores, _lex = parse("fn main() -> int { int v[8]; return 0; };")
    assert errores, "una declaración con '[...]' y sin contenedor no es válida"
    assert "contenedor" in errores[0].message, errores[0].message


def test_mas_push_que_espacios_se_ve_al_compilar():
    assert_has_code(
        _VECTOR +
        "@impl Vector<T> { fn push(Vector<T> ptr mutable self, T x) -> void { } }\n"
        "fn main() -> int {\n"
        "    int Vector v[2];\n"
        "    v.push(1);\n"
        "    v.push(2);\n"
        "    v.push(3);\n"
        "    return 0;\n"
        "};", "SEM033")


def test_los_push_que_dependen_de_la_ejecucion_no_se_cuentan():
    """Dentro de un bucle la cuenta no es decidible: afirmar que no cabe
    rechazaría un programa correcto. Sigue fallando en ejecución."""
    assert_ok(
        _VECTOR +
        "@impl Vector<T> { fn push(Vector<T> ptr mutable self, T x) -> void { } }\n"
        "fn main() -> int {\n"
        "    int Vector v[2];\n"
        "    var int i = 0;\n"
        "    while (i < 10) { v.push(i); i = i + 1; };\n"
        "    return 0;\n"
        "};")
