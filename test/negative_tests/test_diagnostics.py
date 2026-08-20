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


# --- propiedad: 'free' termina la propiedad igual que 'move' ---------------- #
# La misma pasada lineal rastrea las dos, porque son las dos formas que tiene
# el lenguaje de terminar una propiedad. Lo que cambia es el MOTIVO, y el
# motivo decide el diagnóstico: recuperarse de un 'move' es posible (el valor
# vive en el nuevo dueño), de un 'free' no.

def test_use_after_free():
    assert_has_code(
        "fn f() -> void { var int x = 1; var int ptr p = &x; free p; "
        "var int ptr q = p; };",
        "SEM023",
    )


def test_double_free():
    assert_has_code(
        "fn f() -> void { var int x = 1; var int ptr p = &x; free p; free p; };",
        "SEM024",
    )


def test_free_de_algo_ya_movido_es_use_after_move():
    """El motivo manda sobre la operación: 'p' se movió, así que ya no es suyo
    para liberarlo — lo liberará su nuevo dueño. No es un doble free."""
    assert_has_code(
        "fn f() -> void { var int x = 1; var int ptr p = &x; move p; free p; };",
        "SEM004",
    )


def test_move_de_algo_ya_liberado_es_use_after_free():
    """Y al revés: mover algo destruido es usarlo, no un doble move."""
    assert_has_code(
        "fn f() -> void { var int x = 1; var int ptr p = &x; free p; move p; };",
        "SEM023",
    )


def test_free_en_una_rama_invalida_despues_del_if():
    """Unión conservadora, igual que 'move': liberado en ALGUNA rama significa
    liberado después. Prefiere el falso positivo cero al falso negativo."""
    assert_has_code(
        "fn f(bool c) -> void { var int x = 1; var int ptr p = &x; "
        "if (c) { free p; }; var int ptr q = p; };",
        "SEM023",
    )


def test_liberar_un_campo_no_toca_al_hermano():
    """'free o.a' invalida ese campo y lo que cuelga de él, nunca al padre ni
    a sus hermanos (mismo criterio que 'move')."""
    assert_ok(
        "struct { int ptr a; int ptr b; } P;\n"
        "fn f() -> void { var int n = 1; var P p = P{ a: &n, b: &n }; "
        "free p.a; var int ptr x = p.b; };"
    )


def test_reasignar_revive_un_valor_liberado():
    """Un valor NUEVO en el mismo nombre no está liberado: el binding revive,
    igual que tras un 'move'."""
    assert_ok(
        "fn f() -> void { var int x = 1; var int ptr p = &x; free p; "
        "p = &x; var int ptr q = p; };"
    )


# --- consolidación del struct: lo que un tipo NO puede ser ------------------ #

def test_un_struct_no_puede_contenerse_por_valor():
    """``struct { S s; } S;`` no cabe en ninguna cantidad de memoria."""
    assert_has_code("struct { S s; int n; } S;", "SEM026")


def test_la_recursion_mutua_por_valor_tambien_es_infinita():
    assert_has_code("struct { B b; } A;\nstruct { A a; } B;", "SEM026")


def test_un_ciclo_de_tres_structs_se_detecta():
    assert_has_code("struct { B b; } A;\nstruct { C c; } B;\n"
                    "struct { A a; } C;", "SEM026")


def test_un_nullable_de_si_mismo_tambien_es_infinito():
    """``S?`` guarda una ``S`` por valor: el envoltorio no cambia el tamaño."""
    assert_has_code("struct { S? sig; int v; } S;", "SEM026")


def test_un_puntero_a_si_mismo_es_valido():
    """La recursión legítima se escribe con un puntero: se REFIERE en vez de
    contener, y ahí sí hay tamaño conocido. Es la misma distinción que decide
    la propiedad."""
    assert_ok("struct { S ptr sig; int v; } S;")


def test_void_no_puede_ser_el_tipo_de_un_campo():
    assert_has_code("struct { void v; } S;", "SEM025")


def test_void_no_puede_ser_el_tipo_de_una_variable():
    assert_has_code("fn f() -> void { var void x; };", "SEM025")


def test_void_no_puede_ser_el_tipo_de_un_parametro():
    """Las tres posiciones de valor se comprueban en un solo punto
    (``TypeBinder.bind``), y por eso ninguna se queda sin cubrir."""
    assert_has_code("fn f(void x) -> void { };", "SEM025")


def test_void_si_es_valido_como_retorno():
    assert_ok("fn f() -> void { };")


def test_un_puntero_a_void_es_valido():
    """``void ptr`` es una dirección sin tipo, no un valor de tipo ``void``."""
    assert_ok("struct { void ptr p; } S;")


def test_un_literal_incompleto_se_rechaza():
    """Sin valores por defecto, un campo que el literal no escribe no existe
    en el valor: leerlo reventaba en runtime, lejos de la causa."""
    assert_has_code("struct { int a; int b; } P;\n"
                    "fn f() -> void { var P p = P{ a: 1 }; };", "SEM028")


def test_un_literal_completo_no_reporta_nada():
    assert_ok("struct { int a; int b; } P;\n"
              "fn f() -> void { var P p = P{ a: 1, b: 2 }; };")


def test_el_valor_de_un_campo_tiene_que_ser_de_su_tipo():
    assert_has_code("struct { int a; } P;\n"
                    "fn f() -> void { var P p = P{ a: \"x\" }; };", "AST006")


def test_null_en_un_campo_no_nullable_se_rechaza():
    assert_has_code("struct { int ptr p; } S;\n"
                    "fn f() -> void { var S s = S{ p: null }; };", "AST006")


def test_null_en_un_campo_nullable_si_pasa():
    assert_ok("struct { int ptr? p; } S;\n"
              "fn f() -> void { var S s = S{ p: null }; };")


def test_escribir_un_campo_con_otro_tipo_se_rechaza():
    """``p.x = "a"`` cruzaba el frontend entero: la rama del ``Identifier``
    comprobaba el tipo del valor y la del campo no."""
    assert_has_code("struct { int x; } P;\n"
                    "fn f(P ptr mutable p) -> void { p.x = \"a\"; };", "AST006")


def test_escribir_un_elemento_con_otro_tipo_se_rechaza():
    """El tipo admitido lo dice ``__index_set__``, no ``__index__``."""
    assert_has_code(
        "struct { int n; } V;\n"
        "hook fn __index_set__(V ptr mutable v, int i, int x) -> void { };\n"
        "fn f(V ptr mutable v) -> void { v[0] = \"a\"; };", "AST006")


def test_escribir_un_elemento_de_su_tipo_si_pasa():
    assert_ok("struct { int n; } V;\n"
              "hook fn __index_set__(V ptr mutable v, int i, int x) -> void { };\n"
              "fn f(V ptr mutable v) -> void { v[0] = 1; };")


def test_un_enum_inicializa_un_int():
    """Los items de un enum son enteros (estilo C). Pasarlo como ARGUMENTO ya
    valía; inicializar y asignar no — la misma pregunta con tres respuestas
    distintas. Ahora las cuatro posiciones comparten predicado."""
    assert_ok("enum Color { ROJO, VERDE };\n"
              "fn f() -> void { var int n = Color.VERDE; n = Color.ROJO; };")


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
    """``int -> bool`` no es un par nativo: la vuelta (``bool -> int``) sí,
    pero decidir qué entero es 'verdadero' es una convención, no una
    conversión."""
    assert_has_code("fn f() -> void { var bool b = cast<bool>(5); };", "SEM016")


def test_cast_a_str_si_es_nativo():
    """Todo primitivo tiene forma de texto —la que ya interpolaba un
    f-string—, así que ``cast<str>`` no puede fallar y no necesita hook."""
    assert_ok("fn f() -> void {\n"
              "    var str a = cast<str>(5);\n"
              "    var str b = cast<str>(1.5);\n"
              "    var str c = cast<str>(true);\n"
              "    var str d = cast<str>('z');\n};")


def test_cast_a_nominal_sin_hook():
    assert_has_code(
        "const type int8;\nfn f() -> void { var int8 b = cast<int8>(1); };",
        "SEM016",
    )


# El inicializador de un 'type_decl' NO lo visitaba ninguna pasada: 'ast.TypeDecl'
# faltaba en el despacho del scope_resolver y 'visit_stmt' ignora en silencio lo
# que no tiene handler. Un nombre inexistente cruzaba el frontend entero y solo
# lo veia el runtime (RT006, "brecha del analisis estatico").

def test_inicializador_de_type_decl_resuelve_sus_nombres():
    assert_has_code("const type Bloque = _no_existe(4);", "SEM001")


def test_inicializador_de_type_decl_tambien_dentro_de_una_funcion():
    """El inicializador de un 'type' ANIDADO tambien pasa por la Semantica."""
    assert_has_code("fn f() -> void { const type L = _no_existe(1); };", "SEM001")


def test_inicializador_de_type_decl_debe_producir_un_tipo():
    """'type' es un metatipo: inicializarlo con un valor normal es AST006."""
    assert_has_code("const type Malo = 5;", "AST006")


def test_type_decl_con_inicializador_valido_compila_limpio():
    """El otro lado del contrato: una 'fn ... -> type' SI es un inicializador
    valido, y el arreglo no puede convertirlo en un falso positivo."""
    assert_ok("fn entero_de(int bits) -> type;\nconst type int8 = entero_de(8);")


def test_type_decl_sin_inicializador_sigue_limpio():
    assert_ok("const type int8;")


def test_un_type_en_el_nivel_superior_sigue_siendo_valido():
    assert_ok("const type int8;\nfn f() -> void { const int8 x; };")


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
# memoria: las construcciones de región ya no son del lenguaje (v0.2.0)
# --------------------------------------------------------------------------- #

def test_un_bloque_de_region_ya_no_parsea():
    """No hay que dejar que 'region r { }' siga COMPILANDO por accidente: si
    algún día 'region' vuelve a ser una sentencia, tiene que ser a propósito.
    Hoy es un identificador seguido de un bloque, que no es sintaxis válida."""
    assert error_codes("fn f() -> void { region r { var int x = 1; }; };"), \
        "'region r { }' deberia dejar de parsear"


def test_las_operaciones_de_region_ya_no_parsean():
    for fuente in ("new(shrd region c);",
                   "delete(region c);",
                   "in region c: return;",
                   "move region a -> region b;"):
        assert error_codes(f"fn f() -> void {{ {fuente} }};"), \
            f"'{fuente}' deberia dejar de parsear"


def test_la_colocacion_at_ya_no_parsea():
    assert error_codes("fn f() -> void { var int x = (1 * 2) at r; };"), \
        "'expr at r' deberia dejar de parsear"


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
