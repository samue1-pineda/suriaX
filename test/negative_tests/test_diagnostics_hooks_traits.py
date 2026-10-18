"""negative_tests/diagnostics: hooks, traits, visibilidad, regiones retiradas y @impl.

Parte de ``test_diagnostics.py`` (partido por tema); lo compartido esta en
``diagnostics_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import analyze, assert_has_code, assert_ok, error_codes  # noqa: E402

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


def _codes(source: str) -> list:
    """Los códigos por ``analyze`` y no por ``error_codes``: lo que pasa por
    ``error_codes`` entra en el corpus del diferencial V0/V1, y la V1 todavía
    no conoce los métodos llanos en un trait (paso 4)."""
    _, _, errors = analyze(source)
    return [e.code for e in errors]


def test_trait_method_with_plain_name_is_met_by_an_impl_method():
    """Paso 4: un trait puede pedir un método de ``@impl`` (nombre llano).
    Antes era SEM021 ("debe tener nombre dunder")."""
    assert _codes(
        "@trait struct { fn siguiente(self ptr) -> int; } iterable;\n"
        "@impl(iterable) struct { int pos; } L;\n"
        "@impl L { fn siguiente(L ptr self) -> int { return self.pos; } }\n") == []


def test_trait_method_with_plain_name_needs_the_impl_method():
    """Sin el método en un ``@impl L { ... }`` (un ``dunder fn`` homónimo no
    vale: la forma del nombre dice con qué se cumple), SEM021."""
    assert _codes(
        "@trait struct { fn siguiente(self ptr) -> int; } iterable;\n"
        "@impl(iterable) struct { int pos; } L;\n") == ["SEM021"]
    assert _codes(
        "@trait struct { fn siguiente(self ptr) -> int; } iterable;\n"
        "@impl(iterable) struct { int pos; } L;\n"
        "@impl L { fn siguiente(L ptr self) -> str { return \"x\"; } }\n") == ["SEM021"]


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
