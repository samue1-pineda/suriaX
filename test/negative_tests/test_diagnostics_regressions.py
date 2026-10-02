"""negative_tests/diagnostics: exhaustividad de match y regresiones de ejercicios reales.

Parte de ``test_diagnostics.py`` (partido por tema); lo compartido esta en
``diagnostics_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import assert_has_code, assert_ok, error_codes, parse  # noqa: E402

# --------------------------------------------------------------------------- #
# exhaustividad de 'match' (SEM030) — un AVISO, y solo donde se sabe
# --------------------------------------------------------------------------- #

_COLOR = "enum Color { ROJO, VERDE, AZUL };\n"
_DATO = "enum Dato { Vacio, Numero(int) };\n"


def test_match_que_deja_variantes_sin_cubrir_avisa():
    """Un 'match' que no encaja con nada no hace nada, en silencio; y añadir
    una variante deja incompletos todos los 'match' sin que nada lo diga."""
    assert_has_code(
        _COLOR + "fn f(Color c) -> int {\n"
        "    match (c) {\n"
        "        case Color.ROJO: { return 1; }\n"
        "        case Color.VERDE: { return 2; }\n"
        "    }\n"
        "    return 0;\n"
        "};", "SEM030")


def test_un_match_completo_no_avisa():
    assert_ok(_COLOR + "fn f(Color c) -> int {\n"
              "    match (c) {\n"
              "        case Color.ROJO: { return 1; }\n"
              "        case Color.VERDE: { return 2; }\n"
              "        case Color.AZUL: { return 3; }\n"
              "    }\n"
              "    return 0;\n"
              "};")


def test_un_match_sobre_algo_que_no_es_enum_no_avisa():
    """El análisis solo sabe enumerar las variantes de un enum."""
    assert_ok("fn f(int n) -> int {\n"
              "    match (n) { case 1: { return 1; } }\n"
              "    return 0;\n"
              "};")


def test_una_rama_opaca_calla_el_aviso():
    """Cero falsos positivos: si una rama es una expresión que este análisis
    no puede leer como variante concreta, no se puede afirmar nada del
    conjunto — y entonces no se afirma."""
    assert_ok(_COLOR + "fn f(Color c, Color otro) -> int {\n"
              "    match (c) {\n"
              "        case Color.ROJO: { return 1; }\n"
              "        case otro: { return 2; }\n"
              "    }\n"
              "    return 0;\n"
              "};")


def test_la_variante_con_payload_cuenta_como_cubierta():
    """'case Dato.Numero(n)' desestructura, pero cubre 'Numero' igual."""
    assert_ok(_DATO + "fn f(Dato d) -> int {\n"
              "    match (d) {\n"
              "        case Dato.Vacio: { return 0; }\n"
              "        case Dato.Numero(n): { return n; }\n"
              "    }\n"
              "    return 0;\n"
              "};")


def test_el_aviso_no_rechaza_el_programa():
    """SEM030 es un AVISO: un match parcial es un programa válido con
    significado definido (no hacer nada), y el lenguaje no tiene comodín con
    el que decir 'el resto me da igual'."""
    from helpers import analyze
    _, _, errores = analyze(
        _COLOR + "fn f(Color c) -> int {\n"
        "    match (c) { case Color.ROJO: { return 1; } }\n"
        "    return 0;\n"
        "};")
    avisos = [e for e in errores if e.code == "SEM030"]
    assert avisos, "debería avisar"
    assert all(e.severity == "warning" for e in avisos), (
        [(e.code, e.severity) for e in avisos])


# --------------------------------------------------------------------------- #
# lo que los ejercicios reales destaparon
# --------------------------------------------------------------------------- #

def test_indexar_un_primitivo_que_no_es_str_es_error_de_compilacion():
    """``x[i]`` compilaba y moría en ejecución con ``RT014``. Un primitivo no
    tiene dónde declarar ``__index__``, así que el sistema de tipos puede
    decirlo al leer el programa.

    La excepción es ``str``, que SÍ se indexa: nativamente y por el mismo
    motivo por el que ``len(s)`` lo es —una cadena se lee sin que ninguna
    librería lo declare, y ``str`` es primitivo, así que SEM006 le prohíbe
    tener hooks propios—. Sin eso una cadena se podía medir pero no leer.
    """
    for tipo, valor in (("int", "0"), ("float", "0.0"), ("bool", "true"),
                        ("char", "'a'")):
        assert_has_code(
            "fn f(%s t) -> int { var int c = t[0]; return 0; };" % tipo,
            "SEM031")


def test_una_cadena_si_se_indexa():
    """El otro lado de la regla: ``s[i]`` es un ``char``."""
    assert_ok('fn f(str t) -> char { return t[0]; };')


def test_indexar_un_nominal_sin_hook_no_se_rechaza():
    """Cero falsos positivos: el ``__index__`` puede venir de una librería
    que esta pasada aún no vio."""
    assert_ok("struct { int x; } P;\n"
              "fn f(P p) -> int { var int v = p[0]; return 0; };")


def test_ligar_un_valor_con_destructor_exige_move():
    """``var R b = a;`` dejaba DOS dueños del mismo recurso y su destructor
    corría dos veces — la doble liberación que el modelo promete evitar."""
    assert_has_code(
        "struct { int id; } R;\n"
        "hook fn __free__(R ptr r) -> void { };\n"
        "fn f() -> int {\n"
        "    var R a = R{ id: 1 };\n"
        "    var R b = a;\n"
        "    return 0;\n"
        "};", "SEM032")


def test_con_move_la_transferencia_es_valida():
    assert_ok("struct { int id; } R;\n"
              "hook fn __free__(R ptr r) -> void { };\n"
              "fn f() -> int {\n"
              "    var R a = R{ id: 1 };\n"
              "    var R b = move a;\n"
              "    return 0;\n"
              "};")


def test_un_struct_sin_destructor_se_liga_sin_move():
    """Copiar un valor que no posee nada no duplica ningún dueño."""
    assert_ok("struct { int v; } Caja;\n"
              "fn f() -> int {\n"
              "    var Caja a = Caja{ v: 1 };\n"
              "    var Caja b = a;\n"
              "    return b.v;\n"
              "};")


def test_move_como_expresion_invalida_el_origen():
    """La expresión transfiere igual que la sentencia: usar el origen después
    sigue siendo SEM004, sin importar en qué posición se escribió el move."""
    assert_has_code(
        "struct { int id; } R;\n"
        "hook fn __free__(R ptr r) -> void { };\n"
        "fn f() -> int {\n"
        "    var R a = R{ id: 1 };\n"
        "    var R b = move a;\n"
        "    return a.id;\n"
        "};", "SEM004")


# --------------------------------------------------------------------------- #
# diagnósticos que apuntaban al síntoma y no a la causa
# --------------------------------------------------------------------------- #

def test_un_contenedor_sin_nombre_dice_que_falta_el_nombre():
    """'int vec.Vector[10];' no declara CÓMO se llama la variable.

    El retroceso del parser tomaba 'vec' por el nombre y el error salía en el
    '.' ('se esperaba SEMICOLON, se encontro DOT'), que señala el síntoma.
    """
    _program, errores, _lex = parse(
        "fn main() -> int { int vec.Vector[10]; return 0; };")
    assert errores, "una declaración de contenedor sin nombre no es válida"
    assert "NOMBRE" in errores[0].message, errores[0].message
    assert "vec.Vector" in errores[0].message


def test_un_miembro_cualificado_en_from_import_lo_dice():
    """'#from vector #import vector.Vector': el miembro no lleva el módulo
    delante, que ya lo dijo el '#from'. El '.' llegaba al motor de
    expresiones y salía 'token inesperado en expresion: DOT'."""
    _program, errores, _lex = parse(
        "#from vector #import vector.Vector\nfn main() -> int { return 0; };")
    assert errores, "un miembro cualificado no es válido en '#from'"
    assert "#from" in errores[0].message and "modulo" in errores[0].message


def test_ordenar_un_nullable_se_rechaza():
    """``a < 7`` con ``a: int?`` pasaba el frontend, y con ``a`` en null el
    interprete caia (ICE000): null no es menor ni mayor que nada. Comparar
    por igualdad si vale (``a == 7``, ``a == null``)."""
    assert_has_code("fn f(int? a) -> bool { return a < 7; };", "AST006")
    assert_has_code("fn f(int? a) -> bool { return 7 >= a; };", "AST006")
    assert_ok("fn f(int? a) -> bool { return a == 7 or a != null; };")


def test_los_operadores_de_bits_son_de_int():
    assert_has_code("fn f(float a) -> float { return a & a; };", "AST006")
    assert_has_code("fn f(bool a) -> bool { return a | a; };", "AST006")
    assert_has_code("fn f(float a) -> float { return ~a; };", "AST006")
    assert_ok("fn f(int a, int b) -> int { return (a & b) | (a ^ b) << 1 >> 1 | ~a; };")


def test_hash_de_float_y_de_un_tipo_sin_hash():
    """'hash(x)' es nativo sobre int/bool/char/str; un 'float' no tiene hash
    (NaN no es igual a si mismo) y un tipo propio necesita su '__hash__'."""
    assert_has_code("fn f(float x) -> int { return hash(x); };", "AST006")
    assert error_codes("struct { int a; } P;\n"
                       "fn f(P ptr p) -> int { return hash(p); };")
    assert_ok("fn f(int a, str s, char c, bool b) -> int "
              "{ return hash(a) ^ hash(s) ^ hash(c) ^ hash(b); };")
    assert_ok("struct { int a; } P;\n"
              "hook fn __hash__(P ptr p) -> int { return hash(p.a); };\n"
              "fn f(P ptr p) -> int { return hash(p); };")
