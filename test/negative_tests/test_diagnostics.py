"""negative_tests — cada diagnóstico se dispara EN SU CASO y no en otros.

Se comprueba el CÓDIGO (``SEM001``, ``AST006``...), nunca el texto del
mensaje: los mensajes se reescriben, los códigos son el contrato estable.

El otro lado del contrato importa igual: un programa VÁLIDO no debe producir
diagnósticos (cero falsos positivos, ver ``semantic/ARQUITECTURA.md`` 4.2).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import assert_has_code, assert_ok, error_codes  # noqa: E402


# --------------------------------------------------------------------------- #
# léxicos / sintácticos
# --------------------------------------------------------------------------- #

def test_nombre_que_empieza_por_digito():
    assert_has_code("int 1mal;", "PAR003")


def test_mutable_ya_no_califica_variables():
    codes = error_codes("fn f() -> void { mutable int x = 1; };")
    assert codes, "'mutable int x' debe ser error (usar 'var')"


def test_ptr_prefijo_retirado():
    codes = error_codes("fn f() -> void { ptr int p = null; };")
    assert codes, "'ptr int' (prefijo) ya no es válido: es sufijo postfijo"


def test_break_fuera_de_bucle():
    codes = error_codes("fn f() -> void { break; };")
    assert codes, "'break' fuera de un bucle debe reportarse"


# --------------------------------------------------------------------------- #
# semánticos: símbolos y scopes
# --------------------------------------------------------------------------- #

def test_simbolo_no_declarado():
    assert_has_code("fn f() -> void { var int a = desconocido; };", "SEM001")


def test_simbolo_duplicado_en_el_mismo_scope():
    assert_has_code("fn f() -> void { var int a = 1; var int a = 2; };", "SEM002")


def test_asignar_a_const():
    assert_has_code("fn f() -> void { const int a = 1; a = 2; };", "SEM003")


def test_aridad_de_llamada():
    assert_has_code(
        "fn g(int a, int b) -> int { return a; };\n"
        "fn f() -> void { var int x = g(1); };", "SEM008",
    )


def test_tipo_no_declarado():
    assert_has_code("fn f() -> void { var Inexistente x = null; };", "AST005")


# --------------------------------------------------------------------------- #
# semánticos: memoria y punteros
# --------------------------------------------------------------------------- #

def test_use_after_move():
    assert_has_code(
        "fn f() -> void { var int a = 1; move a; var int b = a; };", "SEM004",
    )


def test_double_move():
    assert_has_code(
        "fn f() -> void { var int a = 1; move a; move a; };", "SEM005",
    )


def test_use_after_move_de_un_campo():
    """'move o.it' invalida ese campo (y lo que cuelga de él): usar 'o.it.v'
    después es use-after-move, no un falso negativo diferido al MIR."""
    assert_has_code(
        "struct { int v; } I;\nstruct { I it; } O;\n"
        "fn f() -> void { var O o = O{ it: I{ v: 1 } }; move o.it; "
        "var int x = o.it.v; };", "SEM004",
    )


def test_use_after_move_campo_por_mover_la_variable():
    """Mover la variable completa invalida también sus campos."""
    assert_has_code(
        "struct { int v; } I;\nstruct { I it; } O;\n"
        "fn f() -> void { var O o = O{ it: I{ v: 1 } }; var O c = o; "
        "move o; var int x = o.it.v; };", "SEM004",
    )


def test_addr_of_sobre_temporal():
    assert_has_code(
        "fn f() -> void { var int a = 1; var int ptr p = &(a + 1); };", "SEM013",
    )


def test_free_sobre_no_puntero():
    assert_has_code("fn f() -> void { var int a = 1; free a; };", "SEM014")


def test_escritura_por_puntero_de_solo_lectura():
    assert_has_code(
        "struct { int x; } P;\n"
        "fn f(P ptr p) -> void { p.x = 1; };", "SEM015",
    )


# --------------------------------------------------------------------------- #
# semánticos: tipos y conversiones
# --------------------------------------------------------------------------- #

def test_inicializador_de_tipo_incompatible():
    assert_has_code('fn f() -> void { var int a = "texto"; };', "AST006")


def test_null_a_tipo_no_nullable():
    assert_has_code("fn f() -> void { var int a = null; };", "AST006")


def test_retorno_de_tipo_incorrecto():
    assert_has_code('fn f() -> int { return "texto"; };', "AST012")


def test_operacion_entre_tipos_incompatibles():
    assert_has_code('fn f() -> void { var int a = 1 + "x"; };', "AST006")


def test_argumento_de_tipo_incompatible():
    """El TIPO de cada argumento se verifica contra su parámetro (sin
    coerciones implícitas: 'g(int)' donde 'g' espera 'str' es AST006). Para
    imprimir un entero se usa una f-string ('print(f\"{x}\")')."""
    assert_has_code(
        "fn g(str s) -> void { };\n"
        "fn f() -> void { var int c = 5; g(c); };", "AST006",
    )


def test_argumento_puntero_mutable_desde_const():
    """Pasar 'ptr T' donde se espera 'ptr mutable T' permitiría mutar un
    'const' a través de la función: se rechaza (const-correctness)."""
    assert_has_code(
        "struct { int v; } B;\n"
        "fn g(B ptr mutable b) -> void { b.v = 1; };\n"
        "fn f() -> void { const B c = B{ v: 0 }; g(&c); };", "AST006",
    )


def test_argumento_nominal_incorrecto():
    """Pasar '&O' donde se espera 'B ptr' (nominales distintos) es error de
    tipos en compilación, no una confusión de tipos que explota en runtime."""
    assert_has_code(
        "struct { int v; } B;\nstruct { int w; } O;\n"
        "fn g(B ptr b) -> int { return b.v; };\n"
        "fn f() -> void { var O o = O{ w: 1 }; var int x = g(&o); };", "AST006",
    )


def test_cast_sin_conversion_nativa():
    assert_has_code("fn f() -> void { var str s = cast<str>(5); };", "SEM016")


def test_cast_a_nominal_sin_hook():
    assert_has_code(
        "const type int8;\nfn f() -> void { var int8 b = cast<int8>(1); };",
        "SEM016",
    )


# --------------------------------------------------------------------------- #
# semánticos: structs
# --------------------------------------------------------------------------- #

def test_campo_inexistente_en_literal():
    assert_has_code(
        "struct { int x; } P;\nfn f() -> void { var P p = P{ y: 1 }; };", "SEM001",
    )


def test_campo_repetido_en_literal():
    assert_has_code(
        "struct { int x; } P;\nfn f() -> void { var P p = P{ x: 1, x: 2 }; };",
        "SEM002",
    )


def test_literal_de_tipo_que_no_es_struct():
    assert_has_code(
        "enum E { A };\nfn f() -> void { var E e = E{ A: 1 }; };", "AST005",
    )


def test_campo_inexistente_en_acceso():
    assert_has_code(
        "struct { int x; } P;\n"
        "fn f(P ptr p) -> int { return p.zzz; };", "SEM001",
    )


# --------------------------------------------------------------------------- #
# CERO FALSOS POSITIVOS: programas válidos que NO deben dar diagnósticos
# --------------------------------------------------------------------------- #

def test_valido_shadowing_en_scope_anidado():
    """Redeclarar en un scope INTERNO no colisiona con el externo.

    El scope interno se abre con una construcción de control (``if``): un
    bloque SUELTO ``{ }`` no es una sentencia de la gramática (ver
    ``grammar.ebnf`` secc. 2) aunque el HIR sí sepa transportarlo."""
    assert_ok("fn f() -> void { var int a = 1; if (true) { var int a = 2; }; };")


def test_valido_reasignar_revive_un_movido():
    assert_ok("fn f() -> void { var int a = 1; move a; a = 2; var int b = a; };")


def test_valido_puntero_mutable_escribe():
    assert_ok("struct { int x; } P;\nfn f(P ptr mutable p) -> void { p.x = 1; };")


def test_valido_cast_entre_primitivos():
    assert_ok("fn f() -> void { var float x = cast<float>(3); "
              "var int y = cast<int>(x); };")


def test_valido_try_catch_y_throw():
    assert_ok(
        "fn g() -> error int { throw 1; };\n"
        "fn f() -> void { try { var int x = g(); } catch (e) { }; };"
    )


def test_valido_bloque_test():
    assert_ok('test "caso" { var int a = 1; };')


def test_valido_enum_es_asignable_a_int():
    """Los items de un enum son enteros (estilo C): pasar uno a un 'int' es
    válido (ver e2e/grammar 'test_enum_y_match')."""
    assert_ok(
        "enum E { A, B, C };\nfn g(int n) -> void { };\n"
        "fn f() -> void { g(A); };"
    )


def test_valido_argumento_puntero_mutable_a_solo_lectura():
    """'ptr mutable T' donde se espera 'ptr T': soltar el permiso de escritura
    siempre es seguro — no debe reportarse."""
    assert_ok(
        "struct { int v; } B;\nfn g(B ptr b) -> int { return b.v; };\n"
        "fn f() -> void { var B x = B{ v: 1 }; var int n = g(&x); };"
    )


def test_valido_mover_un_campo_no_afecta_al_hermano():
    assert_ok(
        "struct { int v; } I;\nstruct { I a; I b; } P;\n"
        "fn f() -> void { var P p = P{ a: I{v:1}, b: I{v:2} }; "
        "move p.a; var int x = p.b.v; };"
    )


def test_valido_reasignar_un_campo_movido_lo_revive():
    assert_ok(
        "struct { int v; } I;\nstruct { I it; } O;\n"
        "fn f() -> void { var O o = O{ it: I{v:1} }; move o.it; "
        "o.it = I{v:9}; var int x = o.it.v; };"
    )


def test_valido_struct_recursivo_con_punteros():
    assert_ok(
        "struct { int v; Node ptr? next; } Node;\n"
        "fn f() -> void { var Node n = Node{ v: 1, next: null }; };"
    )


def test_valido_catch_liga_solo_en_su_bloque():
    """El binding del catch NO se filtra fuera de su bloque."""
    codes = error_codes(
        "fn f() -> void { try { } catch (e) { }; var int x = e; };"
    )
    assert "SEM001" in codes, (
        f"'e' no debería existir fuera del catch; códigos: {codes}"
    )


# --------------------------------------------------------------------------- #
# especificador hook/dunder (el compilador ya no adivina por la forma __x__)
# --------------------------------------------------------------------------- #

def test_hook_desconocido_es_error():
    """'hook fn __x__' con __x__ fuera del set fijo -> SEM018."""
    assert_has_code("hook fn __banana__(int a) -> int { return a; };", "SEM018")


def test_hook_del_set_fijo_es_valido():
    assert_ok("struct { int x; } P;\nhook fn __free__(P ptr p) -> void { };")


def test_dunder_libre_es_valido():
    """'dunder fn __x__(T ptr self)' es un método especial libre del usuario
    (hook del usuario), asociado a su tipo dueño."""
    assert_ok("struct { int x; } P;\n"
              "dunder fn __cualquiera__(P ptr self) -> int { return 1; };")


def test_dunder_sin_dueno_es_error():
    """Un 'dunder fn' necesita un receptor nominal (T ptr) -> SEM022."""
    assert_has_code("dunder fn __x__(int a) -> int { return a; };", "SEM022")


# --------------------------------------------------------------------------- #
# traits (@trait / @impl): contratos verificados por el compilador
# --------------------------------------------------------------------------- #

def test_impl_valido_no_reporta():
    assert_ok(
        "@trait struct { fn __next__(self ptr) -> int?; } iterable;\n"
        "dunder fn __next__(L ptr self) -> int? { return null; }\n"
        "@impl(iterable) struct { int pos; } L;"
    )


def test_impl_metodo_faltante():
    assert_has_code(
        "@trait struct { fn __next__(self ptr) -> int?; } iterable;\n"
        "@impl(iterable) struct { int x; } L;", "SEM021")


def test_impl_firma_no_coincide():
    assert_has_code(
        "@trait struct { fn __next__(self ptr) -> int?; } iterable;\n"
        "dunder fn __next__(L ptr self) -> int { return 0; }\n"  # int != int?
        "@impl(iterable) struct { int x; } L;", "SEM021")


def test_impl_trait_desconocido():
    assert_has_code("@impl(fantasma) struct { int x; } L;", "SEM021")


def test_trait_metodo_no_dunder_es_error():
    assert_has_code(
        "@trait struct { fn siguiente(self ptr) -> int; } iterable;", "SEM021")


def test_fn_dunder_desnudo_es_funcion_normal():
    """'fn __x__' sin especificador es una función corriente (cero errores)."""
    assert_ok("fn __x__(int a) -> int { return a; };")


def test_hook_o_dunder_solo_antes_de_fn():
    assert error_codes("hook struct { int x; } P;"), \
        "'hook' solo puede preceder a 'fn'"
    assert error_codes("dunder const int X = 1;"), \
        "'dunder' solo puede preceder a 'fn'"


def test_hook_exige_nombre_dunder():
    assert error_codes("hook fn normal() -> void { };"), \
        "'hook fn' exige un nombre con forma '__x__'"


# --------------------------------------------------------------------------- #
# reservas de visibilidad: mal uso sintáctico
# --------------------------------------------------------------------------- #

def test_visibilidad_dentro_de_un_bloque_es_error():
    assert error_codes("fn f() -> void { public var int x = 1; };"), \
        "la visibilidad solo aplica a declaraciones de nivel superior"


def test_visibilidad_sobre_no_declaracion_es_error():
    assert error_codes("public region r { };"), \
        "la visibilidad solo recae sobre una declaración (no una región)"


def test_visibilidad_en_declaraciones_top_level_es_valida():
    assert_ok("public fn f() -> void { };\n"
              "private struct { int x; } P;\n"
              "internal enum E { A, B };\n"
              "public const int MAX = 10;")


# --------------------------------------------------------------------------- #
# regiones (modelo híbrido): resolución y vida
# --------------------------------------------------------------------------- #

def test_delete_sin_argumento_fuera_de_region():
    assert_has_code("fn f() -> void { delete(); };", "SEM020")


def test_delete_sin_argumento_dentro_de_region_es_valido():
    assert_ok("fn f() -> void { na region r { delete(); }; };")


def test_move_region_inexistente():
    assert_has_code(
        "fn f() -> void { move region fantasma -> region otra; };", "SEM012")


def test_in_region_inexistente():
    assert_has_code("fn f() -> void { in region fantasma: return; };", "SEM012")


def test_na_region_persiste_para_delete_externo():
    """Una 'na region' NO se auto-libera: su nombre vive tras el bloque."""
    assert_ok("fn f() -> void { na region r { var int x = 1; }; "
              "delete(region r); };")


def test_region_normal_no_escapa_de_su_bloque():
    """Una región normal (no 'na') vive solo en su bloque: referenciarla
    después es 'no declarada' (SEM012)."""
    assert_has_code("fn f() -> void { region r { var int x = 1; }; "
                    "delete(region r); };", "SEM012")


# --------------------------------------------------------------------------- #
# bloques @impl (métodos de nombre llano)
# --------------------------------------------------------------------------- #

def test_impl_receptor_de_otro_tipo_es_error():
    """El primer parámetro de un método '@impl Tipo' debe ser el receptor de
    ESE tipo; un receptor de otro tipo se rechaza (no se registra en silencio)."""
    codes = error_codes(
        "struct { int v; } Box;\nstruct { int w; } Other;\n"
        "@impl Box { fn oops(Other ptr self) -> int { return self.w; } }"
    )
    assert codes, "@impl Box con receptor Other debe ser error"


def test_impl_metodo_duplicado_es_error():
    assert_has_code(
        "struct { int v; } Box;\n"
        "@impl Box {\n"
        "  fn a(Box ptr self) -> int { return self.v; }\n"
        "  fn a(Box ptr self) -> int { return 0; }\n"
        "}", "SEM002",
    )


def test_valido_impl_receptor_correcto():
    assert_ok(
        "struct { int v; } Box;\n"
        "@impl Box {\n"
        "  fn get(Box ptr self) -> int { return self.v; }\n"
        "  fn set(Box ptr mutable self, int x) -> void { self.v = x; }\n"
        "}"
    )


def test_valido_dos_impl_del_mismo_tipo():
    assert_ok(
        "struct { int v; } Box;\n"
        "@impl Box { fn a(Box ptr self) -> int { return self.v; } }\n"
        "@impl Box { fn b(Box ptr self) -> int { return self.v; } }"
    )


def test_index_hook_firma_invalida():
    """'__index__' exige 2 parámetros (receptor + índice); con otra aridad es
    error de firma de hook (SEM006)."""
    assert_has_code(
        "struct { int v; } Box;\n"
        "hook fn __index__(Box ptr self) -> int { return self.v; }", "SEM006",
    )
