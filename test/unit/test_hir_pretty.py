"""La vista legible del HIR (``--hir-pretty``, ``V0/src/HIR/pretty.py``).

Lo que se fija aquí no es el formato exacto —cambiará— sino las propiedades
que la hacen útil: que muestre el PROGRAMA (no el árbol del protobuf), que
resuelva el pool de tipos a nombres legibles, que traiga las posiciones del
fuente y que las decisiones de la Semántica (los hooks enlazados) se vean.
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_V0 = os.path.join(_REPO_ROOT, "V0")
for _p in (_REPO_ROOT, _V0):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.path.insert(0, os.path.join(_REPO_ROOT, "test"))

from helpers import lex  # noqa: E402

_PROGRAMA = """
struct { int x; int y; } Punto;

hook fn __print__(Punto ptr p) -> void { }

fn suma(int a, int b) -> int { return a + b; }

fn main() -> int {
    var Punto p = Punto{ x: 1, y: 2 };
    var int total = suma(p.x, p.y);
    while (total > 10) { total = total - 1; }
    if (total > 2) { total = 0; } else { total = 1; }
    return total;
}
"""


def _pretty(source: str = _PROGRAMA) -> str:
    from src.frontend.parser.parser import Parser
    from src.frontend.parser.typed_ast import resolve_types
    from src.frontend.semantic import analyze
    from src.HIR.emmit_IR import build_module
    from src.HIR.pretty import pretty

    tokens, lex_errors = lex(source)
    assert not lex_errors, [e.code for e in lex_errors]
    parser = Parser(tokens)
    program = parser.parse()
    assert not parser.ctx.errors, [e.code for e in parser.ctx.errors]
    resolve_types(program)
    table, sem_errors = analyze(program, source_path="prog.srcx")
    assert not sem_errors, [e.code for e in sem_errors]
    module, hir_errors = build_module(program, table, source_file="prog.srcx")
    assert not hir_errors, [e.code for e in hir_errors]
    return pretty(module)


def test_se_lee_el_programa_no_el_arbol_del_protobuf():
    texto = _pretty()
    assert "fn suma(int a, int b) -> int" in texto
    assert "struct Punto { int x, int y }" in texto
    assert "while" in texto and "if" in texto and "else" in texto
    # y NO la sopa de campos del text_format
    assert "oneof" not in texto and "kind:" not in texto


def test_una_linea_por_sentencia():
    """La medida de que es legible: el cuerpo de 'suma' cabe en una línea."""
    texto = _pretty()
    cuerpo = [l for l in texto.splitlines() if "return" in l and "+" in l]
    assert len(cuerpo) == 1, cuerpo
    assert "a:int" in cuerpo[0] and "b:int" in cuerpo[0]


def test_el_pool_de_tipos_se_resuelve_a_nombres():
    """El plegado del esquema v2 no debe costar legibilidad: se imprime
    'Punto ptr', nunca '#4'."""
    texto = _pretty()
    assert "Punto ptr" in texto
    assert "#4" not in texto.split("types", 1)[1].split("\n\n", 1)[1]


def test_las_posiciones_del_fuente_van_al_margen():
    texto = _pretty()
    linea = next(l for l in texto.splitlines() if l.lstrip().startswith("fn suma"))
    assert "@" in linea
    ln, col = linea.rsplit("@", 1)[1].split(":")
    assert int(ln) > 0 and int(col) > 0


def test_los_hooks_enlazados_son_visibles():
    """Lo que la Semántica decidió y el intérprete ejecuta sin re-decidir."""
    texto = _pretty()
    assert "__print__ de Punto" in texto


def test_el_encabezado_resume_la_unidad():
    texto = _pretty()
    cabecera = texto.splitlines()[0]
    assert cabecera.startswith("unit prog.srcx")
    assert "schema 2" in cabecera and "items" in cabecera


def test_un_prototipo_se_distingue_de_una_funcion_con_cuerpo():
    texto = _pretty("fn __write__(str s) -> void;\n"
                    "fn main() -> int { return 0; }\n")
    assert "prototipo" in texto


def test_las_ramas_catch_viajan_con_su_filtro_de_tipo():
    """Regresión: la vista leía 'catch_name'/'catch_block', tags que quedaron
    'reserved' cuando 'TryStmt' pasó a N ramas filtradas — cualquier programa
    con try/catch reventaba la vista con AttributeError. El TIPO se imprime
    porque es lo que decide qué rama gana."""
    texto = _pretty(
        "fn riesgo(int x) -> int {\n"
        "    if (x > 5) { throw \"demasiado\"; }\n"
        "    return x;\n"
        "}\n"
        "fn main() -> int {\n"
        "    try { const int r = riesgo(9); }\n"
        "    catch (str e) { return 1; }\n"
        "    catch (f) { return 2; }\n"
        "    return 0;\n"
        "}\n")
    assert "try" in texto
    assert "catch (str e)" in texto
    # rama sin filtro: atrapa cualquier valor, y se ve que no lo tiene
    assert "catch (f)" in texto


def test_la_notacion_escribe_todo_lo_que_identifica_al_tipo():
    """Regresión: ``format_type`` perdía dos cosas que SON el tipo —
    ``error int`` se veía como ``error`` (el tipo del valor, perdido) y
    ``Vector<int>`` como ``Vector`` (justo la distinción que hace que el
    genérico no sea decorativo)."""
    texto = _pretty(
        "struct { T valor; } Caja<T>;\n"
        "fn puede_fallar(int n) -> error int {\n"
        "    if (n < 0) { throw \"malo\"; }\n"
        "    return n;\n"
        "}\n"
        "fn main() -> int {\n"
        "    var Caja<int> c = Caja<int>{ valor: 1 };\n"
        "    return 0;\n"
        "}\n")
    assert "error int" in texto, texto
    assert "Caja<int>" in texto, texto


def test_la_destruccion_que_inserta_el_compilador_se_ve():
    """El HIR transporta los drops de ámbito, el ``transfers`` del retorno y
    el drop del temporal — y ninguna vista los mostraba. En un lenguaje cuyo
    modelo de memoria es la característica principal, "¿qué decidió el
    frontend que hay que destruir aquí?" es justo la pregunta que se le hace
    a esta vista."""
    texto = _pretty(
        "fn __write__(str s) -> void;\n"
        "struct { int id; } R;\n"
        "hook fn __free__(R ptr r) -> void { __write__(\"x\"); };\n"
        "struct { R b; int n; } Caja;\n"
        "fn fabrica() -> R {\n"
        "    var R nuevo = R{ id: 9 };\n"
        "    return nuevo;\n"
        "}\n"
        "fn main() -> int {\n"
        "    var R a = R{ id: 1 };\n"
        "    var Caja k = Caja{ b: R{ id: 2 }, n: 0 };\n"
        "    fabrica();\n"
        "    return 0;\n"
        "}\n")
    # el drop del ámbito, con el hook que lo ejecuta
    assert "drop a  ⟨hook __free__ de R⟩" in texto, texto
    # ...y el de un CAMPO, con la ruta ya aplanada por el frontend
    assert "drop k.b" in texto, texto
    # la propiedad que sale hacia el llamador: el ámbito NO lo destruye
    assert "⟨transfiere⟩" in texto, texto
    # el valor que nadie recibe y muere al terminar la sentencia
    assert "⟨temporal __free__ de R⟩" in texto, texto


def test_una_variante_con_payload_no_se_lee_como_un_entero():
    """``Numero(int)`` es un constructor, ``ROJO`` un entero. Sin los tipos
    del payload las dos formas del enum se leían igual."""
    texto = _pretty("enum Color { ROJO, VERDE = 5 };\n"
                    "enum Dato { Vacio, Numero(int), Texto(str) };\n"
                    "fn main() -> int { return 0; }\n")
    assert "enum Color { ROJO, VERDE = 5 }" in texto, texto
    assert "Numero(int)" in texto and "Texto(str)" in texto, texto


def test_escribe_en_streaming_sin_armar_la_cadena():
    """El defecto que motivó esta vista: 'module_to_text' construía 20 MB en
    memoria. ``write_pretty`` escribe sobre el archivo a medida que recorre."""
    from src.HIR.pretty import write_pretty

    escrituras: list[str] = []

    class _Sonda:
        def write(self, text: str) -> int:
            escrituras.append(text)
            return len(text)

    from src.frontend.parser.parser import Parser
    from src.frontend.parser.typed_ast import resolve_types
    from src.frontend.semantic import analyze
    from src.HIR.emmit_IR import build_module

    tokens, _ = lex(_PROGRAMA)
    program = Parser(tokens).parse()
    resolve_types(program)
    table, _ = analyze(program, source_path="prog.srcx")
    module, _ = build_module(program, table, source_file="prog.srcx")
    write_pretty(module, _Sonda())

    assert len(escrituras) > 20, (
        "la vista se escribió de una sola vez: no está en streaming")
