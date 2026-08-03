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
    assert info["keywords"]["na"]["category"] == "memory"


def test_hooks_y_errores_en_el_spec():
    info = build_language_info()
    assert "__print__" in info["hooks"] and "__cast__" in info["hooks"]
    codes = {e["code"] for e in info["errors"]}
    for code in ("SEM018", "SEM019", "SEM020", "PAR004", "AST006"):
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
           "fn main() -> int { delete(); return 0; }\n")
    code, out, _err = run_source(src, args=["--emit-diagnostics"])
    assert code == 0, "el canal LSP devuelve 0 aunque haya diagnósticos"
    data = json.loads(out)
    by_code = {d["code"]: d for d in data["diagnostics"]}
    assert "SEM018" in by_code and "SEM020" in by_code, by_code
    # severidad REAL: SEM018 es 'critical'; SEM020 (memoria/región) es 'panic'.
    assert by_code["SEM018"]["line"] == 1 and by_code["SEM018"]["severity"] == "critical"
    assert by_code["SEM020"]["severity"] == "panic"


def test_emit_diagnostics_reporta_rbmm_hir005():
    """Los constructos RBMM se rechazan en la fase HIR (``HIR005``). El canal
    LSP los detecta SIN construir el HIR (sin protobuf), para que la extensión
    no se los 'salte': un ``region { }`` se marca MIENTRAS se escribe, no
    recién en el build. Deben reportarse TODOS, con posición y fase 'hir'."""
    src = ("fn main() -> int { region r { var int x = 5; }; "
           "new(shrd region r2); return 0; };\n")
    code, out, _err = run_source(src, args=["--emit-diagnostics"])
    assert code == 0
    hir = [d for d in json.loads(out)["diagnostics"] if d["code"] == "HIR005"]
    assert len(hir) == 2, hir
    assert all(d["phase"] == "hir" and d["line"] and d["column"] for d in hir)


def test_emit_diagnostics_archivo_limpio_no_reporta_nada():
    code, out, _err = run_source("fn main() -> int { return 0; };",
                                 args=["--emit-diagnostics"])
    assert code == 0
    assert json.loads(out)["diagnostics"] == []
