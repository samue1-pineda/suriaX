"""unit/lang_info — la especificación del lenguaje que consume el LSP
(``--emit-lang-info``) y el canal de diagnósticos (``--emit-diagnostics``).

Fija el CONTRATO con la extensión: si algo de esto cambia de forma, la
extensión hay que actualizarla (justo lo que el JSON busca evitar en el
vocabulario, ver ``extension_v0.0.3.md`` §4).
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_source  # noqa: E402
from include.lang_info import build_language_info  # noqa: E402
from include.t_types import KEYWORDS  # noqa: E402


def test_todos_los_keywords_estan_categorizados():
    """Cada keyword del lexer cae en una categoría explícita (sin fallback)."""
    info = build_language_info()
    assert "keyword" not in info["categories"], (
        "hay keywords sin categoría (fallback 'keyword'): "
        f"{info['categories'].get('keyword')}"
    )
    assert set(info["keywords"]) == set(KEYWORDS), \
        "el JSON debe listar exactamente los keywords del lexer"


def test_categorias_nuevas_presentes():
    info = build_language_info()
    assert info["keywords"]["public"]["category"] == "visibility"
    assert info["keywords"]["hook"]["category"] == "specifier"
    assert info["keywords"]["move"]["category"] == "memory"


def test_los_simbolos_publicados_son_los_que_el_lexer_reconoce():
    """La lista de símbolos se DERIVA del scanner, no se copia.

    Regresión: era un espejo escrito a mano que decía ser "espejo estable del
    scanner" y dejó de serlo en cuanto el lexer aprendió ``%``, ``+=`` y
    ``++`` — la extensión seguía sin conocerlos y nada lo detectaba. Esta
    prueba fija que la derivación siga siendo la fuente."""
    from src.frontend.lexer.scanners.operators import _DOUBLE, _SINGLE

    publicados = set(build_language_info()["symbols"])
    del_lexer = set(_SINGLE) | {a + b for (a, b) in _DOUBLE}
    faltan = del_lexer - publicados
    assert not faltan, f"el lexer reconoce símbolos que el spec no publica: {sorted(faltan)}"


def test_cada_simbolo_publicado_tokeniza_como_dice():
    """No basta con listarlos: el token que el spec promete tiene que ser el
    que el lexer produce de verdad."""
    from helpers import lex

    # '#' y '@' arrancan directivas/decoradores y no se tokenizan sueltos.
    for lexema, nombre in build_language_info()["symbols"].items():
        if lexema in ("#", "@"):
            continue
        tokens, errores = lex(lexema)
        assert not errores, f"{lexema!r} no lo reconoce el lexer: {errores}"
        assert tokens[0].type.name == nombre, (
            f"{lexema!r}: el spec dice {nombre} y el lexer da {tokens[0].type.name}")


def test_hooks_y_errores_en_el_spec():
    info = build_language_info()
    assert "__print__" in info["hooks"] and "__cast__" in info["hooks"]
    codes = {e["code"] for e in info["errors"]}
    for code in ("SEM018", "SEM019", "SEM021", "PAR004", "AST006"):
        assert code in codes, f"falta {code} en el catálogo de errores"


def test_emit_lang_info_por_cli_es_json_valido():
    code, out, _err = run_source("", args=["--emit-lang-info"])
    assert code == 0
    data = json.loads(out)
    assert data["language"] == "suriaX"
    assert data["extensions"] == [".srcx", ".libsrx"]


def test_emit_diagnostics_reporta_codigos_con_posicion():
    """El canal en vivo: JSON con code/line/column, exit 0 aunque haya errores."""
    src = ("hook fn __banana__(int a) -> int { return a; }\n"
           "fn main() -> int { free 1; return 0; }\n")
    code, out, _err = run_source(src, args=["--emit-diagnostics"])
    assert code == 0, "el canal LSP devuelve 0 aunque haya diagnósticos"
    data = json.loads(out)
    by_code = {d["code"]: d for d in data["diagnostics"]}
    assert "SEM018" in by_code and "SEM014" in by_code, by_code
    # severidad REAL: SEM018 es 'critical'; SEM014 (memoria) es 'panic'.
    assert by_code["SEM018"]["line"] == 1 and by_code["SEM018"]["severity"] == "critical"
    assert by_code["SEM014"]["severity"] == "panic"


def test_emit_diagnostics_reporta_las_regiones_como_error_de_sintaxis():
    """Las regiones se retiraron en v0.2.0. El canal LSP las marcaba antes con
    ``HIR005`` mediante una detección aparte que recorría el AST sin construir
    el HIR; esa maquinaria se borró con el modelo. Hoy las reporta el PARSER,
    que es más temprano y más barato — pero el canal tiene que seguir
    devolviendo exit 0 y posiciones utilizables por el editor."""
    src = ("fn main() -> int { region r { var int x = 5; }; "
           "new(shrd region r2); return 0; };\n")
    code, out, _err = run_source(src, args=["--emit-diagnostics"])
    assert code == 0, "el canal LSP devuelve 0 aunque haya diagnósticos"
    diags = json.loads(out)["diagnostics"]
    assert diags, "un programa con regiones ya no es válido: debe diagnosticar"
    assert not [d for d in diags if d["code"] == "HIR005"], \
        "el HIR ya no es quien rechaza las regiones"
    assert all(d["line"] and d["column"] for d in diags), diags


def test_emit_diagnostics_archivo_limpio_no_reporta_nada():
    code, out, _err = run_source("fn main() -> int { return 0; };",
                                 args=["--emit-diagnostics"])
    assert code == 0
    assert json.loads(out)["diagnostics"] == []


# --------------------------------------------------------------------------
# v4: la sintaxis (para colorear) y los snippets, sacados del compilador
# --------------------------------------------------------------------------

def test_la_version_del_contrato_es_la_4():
    from include.lang_info import LANG_INFO_VERSION
    info = build_language_info()
    assert LANG_INFO_VERSION == 4 and info["lang_info_version"] == 4
    assert {"syntax", "snippets"} <= set(info)


def test_los_escapes_publicados_son_los_del_lexer():
    """Derivados de la tabla del scanner: un escape nuevo aparece solo."""
    from src.frontend.lexer.scanners.strings import _ESCAPES
    syntax = build_language_info()["syntax"]
    esperados = sorted("\\" + k for k in _ESCAPES)
    assert syntax["string"]["escapes"] == esperados
    assert syntax["char"]["escapes"] == esperados


def test_los_comentarios_publicados_los_ignora_el_lexer():
    comments = build_language_info()["syntax"]["comments"]
    abre, cierra = comments["block"]
    from helpers import lex
    fuente = f"{comments['line']} nada\n{abre} tampoco\n nada {cierra} x"
    tokens, errores = lex(fuente)
    assert not errores
    assert [t.lexeme for t in tokens if t.type.name != "EOF"] == ["x"]


def test_el_formato_publicado_es_el_que_valida_el_parser():
    import re
    from src.frontend.parser.expressions.nud import formato_valido
    spec = build_language_info()["syntax"]["fstring"]["format_spec"]
    for muestra in ("", "08", ".2f", "x", "08b", "10.3f", "X", "o"):
        assert re.fullmatch(spec, muestra) and formato_valido(muestra), muestra
    for muestra in ("08q", "..2", "-3", "f2"):
        assert not re.fullmatch(spec, muestra) and not formato_valido(muestra), muestra


def test_lang_info_lexer():
    """Las expresiones de los numeros reconocen lo mismo que el scanner (que
    no usa expresiones): un literal que el regex acepta entero tokeniza como
    UN literal de esa clase, y uno que rechaza no."""
    import re
    numbers = build_language_info()["syntax"]["numbers"]
    from helpers import lex

    def un_literal(texto):
        tokens, errores = lex(texto)
        reales = [t for t in tokens if t.type.name != "EOF"]
        if errores or len(reales) != 1:
            return None
        return reales[0].type.name

    for texto in ("0", "42", "1_000_000", "0xFF", "0xff_ff", "0b1010", "0B1_0",
                  "0o755", "3.25", "1_0.2_5"):
        clase = "float" if re.fullmatch(numbers["float"], texto) else "int"
        assert re.fullmatch(numbers[clase], texto), texto
        assert un_literal(texto) == ("FLOAT_LIT" if clase == "float" else "INT_LIT"), texto
    for texto in ("1__0", "1_", "0x", "0b2", "0o8", "0xFG"):
        assert not re.fullmatch(numbers["int"], texto), texto
        assert un_literal(texto) is None, texto


def _expandir(body: str) -> str:
    """El snippet con cada campo en su valor por defecto (y '$N' vacio)."""
    import re
    texto = re.sub(r"\$\{\d+:([^}]*)\}", r"\1", body)
    return re.sub(r"\$\d+", "", texto)


def test_lang_info_snippets():
    """Cada snippet, con sus valores por defecto, compila sin diagnosticos:
    lo que el editor inserta tiene que ser suriaX valido."""
    from helpers import error_codes
    snippets = build_language_info()["snippets"]
    prefijos = [s["prefix"] for s in snippets]
    assert len(prefijos) == len(set(prefijos)), "prefijos repetidos"
    for snippet in snippets:
        assert snippet["context"] in ("top", "body"), snippet
        assert snippet["description"], snippet
        codigo = _expandir(snippet["body"])
        if snippet["context"] == "body":
            fuente = f"fn main() -> int {{\n{codigo}\nreturn 0;\n}}\n"
        else:
            fuente = "struct { int v; } Punto;\n" + codigo + "\n"
            if snippet["prefix"] != "main":
                fuente += "fn main() -> int { return 0; }\n"
        codigos = error_codes(fuente)
        assert not codigos, f"el snippet '{snippet['prefix']}' no compila: {codigos}\n{fuente}"
