"""unit/lsp_index — el canal de hover, ir a la definición y completar
(``--emit-index``) y la vista de desugaring (``--emit-stage desugar``).

Fija el CONTRATO con la extensión: la forma del JSON (``index_version``) y
lo que promete cada campo. Si cambia, la extensión hay que actualizarla.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

_TEST_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_TEST_DIR)
sys.path.insert(0, _TEST_DIR)

_ENTRY = os.path.join("V0", "main.py")


def _cli(source: str, *args: str, name: str = "__lsp_probe.srcx") -> tuple[int, str, str]:
    """Corre el compilador sobre ``source`` leido de stdin (nada va a disco)."""
    completed = subprocess.run(
        [sys.executable, _ENTRY, name, *args, "--stdin"],
        cwd=_REPO_ROOT, input=source.encode("utf-8"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
    )
    return (completed.returncode, completed.stdout.decode("utf-8"),
            completed.stderr.decode("utf-8"))


def _index(source: str) -> dict:
    code, out, err = _cli(source, "--emit-index")
    assert code == 0, f"el canal sale con 0 aunque haya diagnosticos: {err[:300]}"
    return json.loads(out.strip().splitlines()[-1])


_PROGRAMA = """#from io #import stdp

// un punto del plano
struct { int x; int y; } Punto;

// el doble de n
fn doble(int n) -> int {
    return n * 2;
}

fn main() -> int {
    var int a = doble(3);
    a += 1;
    stdp.println(f"{a}");
    return 0;
}
"""


def _simbolo(index: dict, name: str, **filtro) -> tuple[int, dict]:
    for i, s in enumerate(index["symbols"]):
        if s["name"] == name and all(s.get(k) == v for k, v in filtro.items()):
            return i, s
    raise AssertionError(f"no hay simbolo '{name}' {filtro}: "
                         f"{[s['name'] for s in index['symbols']]}")


def test_el_indice_trae_diagnosticos_y_su_version():
    from src.frontend.semantic.index import INDEX_VERSION
    index = _index(_PROGRAMA)
    assert index["index_version"] == INDEX_VERSION
    assert index["diagnostics"] == []
    assert {"symbols", "references", "members"} <= set(index)


def test_una_funcion_trae_firma_con_nombres_y_su_comentario():
    _i, doble = _index_y("doble")
    assert doble["kind"] == "function" and doble["type"] == "int"
    assert doble["detail"] == "fn doble(int n) -> int"
    assert doble["doc"] == "el doble de n"
    assert (doble["line"], doble["column"]) == (7, 1)


def test_un_local_pertenece_a_su_funcion():
    _i, n = _index_y("n")
    assert n["kind"] == "param" and n["container"] == "doble"
    assert "doc" not in n, "un parametro no hereda el comentario de su funcion"
    _i, a = _index_y("a")
    assert a["kind"] == "var" and a["container"] == "main" and a["type"] == "int"


def test_los_miembros_de_un_struct():
    index = _index(_PROGRAMA)
    campos = sorted(index["symbols"][i]["name"] for i in index["members"]["Punto"])
    assert campos == ["x", "y"]
    _i, x = _simbolo(index, "x")
    assert "doc" not in x, "un campo en la linea del struct no hereda su comentario"


def test_cada_uso_apunta_a_su_simbolo_una_sola_vez():
    index = _index(_PROGRAMA)
    a, _ = _simbolo(index, "a")
    usos = sorted((r["line"], r["column"]) for r in index["references"] if r["symbol"] == a)
    # 'a += 1' es 'a = a + 1' en el arbol, pero en el fuente es UNA 'a'
    assert usos == [(13, 5), (14, 21)], usos
    doble, _ = _simbolo(index, "doble")
    assert [(r["line"], r["column"]) for r in index["references"]
            if r["symbol"] == doble] == [(12, 17)]


def test_lo_de_una_libreria_lleva_su_archivo():
    """Ir a la definicion de 'stdp.println' abre la libreria, no este archivo."""
    index = _index(_PROGRAMA)
    _i, stdp = _simbolo(index, "stdp")
    assert stdp["file"].endswith(os.path.join("io", "stdp.libsrx")), stdp["file"]
    _i, println = _simbolo(index, "println")
    assert println["file"].endswith(os.path.join("io", "stdp.libsrx")), println["file"]
    assert println["detail"].startswith("fn println(")
    assert "println" in [index["symbols"][i]["name"] for i in index["members"]["stdp"]]
    # y su comentario sale del archivo de la libreria
    _i, imprime = _simbolo(index, "print")
    assert imprime.get("doc", "").startswith("API publica"), imprime


def test_un_error_de_sintaxis_da_diagnosticos_y_un_indice_vacio():
    index = _index("fn main() -> int { var int = ; return 0; }\n")
    assert index["diagnostics"], "debe diagnosticar"
    assert index["symbols"] == [] and index["references"] == [] and index["members"] == {}


def test_un_error_semantico_no_impide_el_indice():
    """Con el arbol limpio el indice sale aunque haya errores de tipos: el
    editor sigue pudiendo navegar un archivo a medio escribir."""
    index = _index("fn f(int n) -> int { return n; }\n"
                   "fn main() -> int { var str s = f(1); return 0; }\n")
    assert index["diagnostics"]
    _simbolo(index, "f", kind="function")


def _index_y(name: str) -> tuple[int, dict]:
    return _simbolo(_index(_PROGRAMA), name)


# --------------------------------------------------------------------------
# --emit-stage desugar: lo que se escribio y lo que el compilador entiende
# --------------------------------------------------------------------------

_AZUCAR = """fn main() -> int {
    var int x = 1;
    x += 4;
    x++;
    return x;
}
"""


def test_la_vista_de_desugaring_marca_cada_azucar():
    code, out, err = _cli(_AZUCAR, "--emit-stage", "desugar")
    assert code == 0, err[:300]
    assert "=== desugaring: 2 construccion(es) de azucar ===" in out, out[:400]
    assert "linea 3: '+=': x = x + ..." in out
    assert "linea 4: '++': x = x + 1" in out
    # la linea del fuente, como se escribio, encima de lo que se entiende
    assert "// fuente 3: x += 4;" in out
    assert "⟨azúcar: '+=': x = x + ...⟩" in out


def test_sin_azucar_la_vista_lo_dice():
    code, out, _err = _cli("fn main() -> int { return 0; }\n", "--emit-stage", "desugar")
    assert code == 0
    assert "=== desugaring: 0 construccion(es) de azucar ===" in out


def test_la_vista_no_se_emite_con_errores():
    _code, out, _err = _cli("fn main() -> int { var str s = 1; x += 1; return 0; }\n",
                            "--emit-stage", "desugar")
    assert "NO emitido" in out, out[:300]


def test_las_marcas_no_viajan_al_hir():
    """``azucar`` es del arbol y de esta vista: el HIR no lo lleva."""
    from src.HIR.desugar import _HIR_NODE, sugar_marks
    from helpers import analyze
    program, _table, errors = analyze(_AZUCAR)
    assert not errors
    marcas = sugar_marks(program)
    assert sorted(ln for (ln, _c, _n) in marcas) == [3, 4]
    assert set(_HIR_NODE.values()) >= {nodo for (_l, _c, nodo) in marcas}
    proto = open(os.path.join(_REPO_ROOT, "V0", "src", "HIR", "proto", "hir.proto"),
                 encoding="utf-8").read()
    assert "azucar" not in proto
