"""unit/diagnostics_channel — el canal en vivo del LSP (``--emit-diagnostics``).

Fija tres reglas que la extensión de VS Code descubrió incumplidas, cada una
con la forma de "un archivo VÁLIDO se reportaba como roto":

1. ``#test <fase>`` se CONSUME igual que en la ruta normal. Antes llegaba a
   ``parse_directive``, que no tiene rama para él, y daba ``PAR020``.
2. La semántica NO corre sobre un AST recuperado en modo pánico. Antes, lo que
   la recuperación se tragaba se reportaba como "no declarado" — señalando
   código correcto.
3. Todo diagnóstico sale con ``file``, no con ``null``.

Y una capacidad nueva: ``--stdin``, que permite a un editor analizar su buffer
sin guardar (el archivo puede ni existir todavía).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

_TEST_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_TEST_DIR)
sys.path.insert(0, _TEST_DIR)

_ENTRY = os.path.join("V0", "main.py")


def _run(source: str, *, name: str = "probe.srcx", stdin: bool = False) -> list[dict]:
    """Corre el canal sobre ``source`` y devuelve la lista de diagnósticos.

    Con ``stdin`` el archivo NO se escribe a disco, que es justo el caso que la
    bandera existe para cubrir.
    """
    path = os.path.join(_REPO_ROOT, name)
    args = [sys.executable, _ENTRY, name, "--emit-diagnostics"]
    written = False

    try:
        if stdin:
            args.append("--stdin")
            completed = subprocess.run(
                args, cwd=_REPO_ROOT, input=source.encode("utf-8"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
            )
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(source)
            written = True
            completed = subprocess.run(
                args, cwd=_REPO_ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
            )
    finally:
        if written and os.path.exists(path):
            os.remove(path)

    assert completed.returncode == 0, (
        "el canal debe salir con 0 aunque haya diagnósticos; "
        f"salió {completed.returncode}: {completed.stderr.decode('utf-8')[:300]}"
    )

    payload = json.loads(completed.stdout.decode("utf-8").strip().splitlines()[-1])
    return payload["diagnostics"]


_VALIDO = """fn foo(int x) -> int {
    return x + 1;
}

fn main() -> int {
    return foo(2);
}
"""


def test_archivo_valido_no_reporta_nada():
    assert _run(_VALIDO) == []


def test_directiva_test_no_es_un_error():
    """'#test <fase>' es una feature documentada (how_to_run.md §'#test')."""
    diagnostics = _run("#test lexer\n\n" + _VALIDO)
    assert diagnostics == [], (
        "'#test' debe consumirse como en la ruta normal, no reportarse: "
        f"{[d['code'] for d in diagnostics]}"
    )


def test_un_error_de_sintaxis_no_inventa_errores_semanticos():
    """La recuperación en modo pánico salta tokens; lo saltado NO es 'no declarado'.

    Sin esto, un solo token suelto producía un SEM001 contra una función
    declarada más arriba — señalando código perfectamente correcto.
    """
    roto = """fn foo(int x) -> int {
    return x + 1;
}

fn main() -> int {
    int y = ;
    return foo(y);
}
"""
    codes = [d["code"] for d in _run(roto)]
    assert any(c.startswith("PAR") for c in codes), \
        f"debe reportarse el error de sintaxis real: {codes}"
    assert not any(c.startswith("SEM") for c in codes), \
        f"no debe haber semántica derivada de un AST recuperado: {codes}"


def test_un_error_semantico_puro_si_se_reporta():
    """La regla anterior no debe silenciar la semántica cuando el archivo parsea."""
    codes = [d["code"] for d in _run("#import no_existe_esta_lib;\nfn f() -> void {}\n")]
    assert "SEM009" in codes, f"la librería inexistente debe reportarse: {codes}"


def test_todo_diagnostico_trae_su_archivo():
    for diagnostic in _run("#import no_existe_esta_lib;\nfn f() -> void {}\n"):
        assert diagnostic["file"], f"diagnóstico sin 'file': {diagnostic}"


def test_stdin_analiza_un_buffer_sin_guardar():
    """El archivo ni siquiera existe: la ruta solo ancla la resolución de .libsrx."""
    source = '#import io.stdp;\n\nfn main() -> int {\n    stdp.println("hola");\n    return 0;\n}\n'
    assert _run(source, name="__jamas_guardado.srcx", stdin=True) == []


def test_stdin_da_los_mismos_diagnosticos_que_el_disco():
    roto = 'fn main() -> int {\n    stdp.println("x");\n    return 0;\n}\n'
    por_disco = [(d["code"], d["line"]) for d in _run(roto)]
    por_stdin = [(d["code"], d["line"]) for d in _run(roto, stdin=True)]
    assert por_disco == por_stdin, \
        f"stdin y disco deben coincidir: {por_disco} vs {por_stdin}"


def test_los_diagnosticos_traen_rango_no_solo_inicio():
    """Con solo el inicio, un editor no puede subrayar: acaba marcando un caracter.

    El final se deriva del lexema del token que empieza en esa posicion, asi que
    ningun sitio de 'raise' tuvo que cambiar.
    """
    source = "fn main() -> int {\n    unaFuncionQueNoExiste(1);\n    return 0;\n}\n"
    diagnostics = _run(source)
    assert diagnostics, "el nombre no declarado debe reportarse"

    d = diagnostics[0]
    assert d["end_line"] == d["line"], "el nombre cabe en una linea"
    assert d["end_column"] - d["column"] == len("unaFuncionQueNoExiste"), (
        f"el rango debe cubrir el nombre entero: {d['column']}..{d['end_column']}"
    )


def test_el_rango_nunca_es_vacio():
    """Un rango de ancho cero no se puede dibujar; el minimo es un caracter."""
    for source in ("fn f() -> void {\n    int x = ;\n}\n",
                   "#import no_existe_esta_lib;\nfn f() -> void {}\n"):
        for d in _run(source):
            assert (d["end_line"], d["end_column"]) > (d["line"], d["column"]), \
                f"rango vacio o invertido: {d}"


# --------------------------------------------------------------------------
# --emit-stage: el mismo volcado que '#test <fase>', pedido desde fuera.
# --------------------------------------------------------------------------

def _stage(source: str, stage: str, *, name: str = "__stage_probe.srcx") -> tuple[int, str, str]:
    completed = subprocess.run(
        [sys.executable, _ENTRY, name, "--emit-stage", stage, "--stdin"],
        cwd=_REPO_ROOT, input=source.encode("utf-8"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
    )
    return (completed.returncode,
            completed.stdout.decode("utf-8"),
            completed.stderr.decode("utf-8"))


def test_cada_fase_publicada_se_puede_volcar():
    """Lo que 'lang_info' anuncia en 'stages' tiene que poder pedirse de verdad."""
    from include.lang_info import build_language_info

    stages = build_language_info()["stages"]
    assert stages, "el spec debe publicar las fases del pipeline"

    for stage in stages:
        code, out, err = _stage(_VALIDO, stage)
        assert code == 0, f"la fase '{stage}' falló: {err[:200]}"
        assert out.strip(), f"la fase '{stage}' no produjo nada"


def test_una_fase_desconocida_lista_las_validas():
    code, _out, err = _stage(_VALIDO, "no_existe")
    assert code == 2
    assert "disponibles" in err, f"debe decir cuáles hay: {err[:200]}"


def test_la_fase_pedida_gana_sobre_la_directiva_del_archivo():
    """El visualizador pide una fase; un '#test' en el fuente no debe secuestrarla."""
    _code, out, _err = _stage("#test lexer\n\n" + _VALIDO, "parser")
    assert "#test parser" in out, f"debía volcarse 'parser', no lo del archivo: {out[:120]}"


def test_emit_stage_no_necesita_que_el_archivo_exista():
    """Con --stdin la ruta solo ancla la resolución; el buffer puede no estar guardado."""
    code, out, _err = _stage(_VALIDO, "lexer", name="__jamas_guardado_stage.srcx")
    assert code == 0 and out.strip()


def test_un_test_mal_colocado_nombra_la_regla():
    """'#test' fuera de la primera posición SÍ es un error — pero decir solo
    'no válida en esta posición' deja al usuario adivinando cuál es la válida."""
    diagnostics = _run("#from io #import stdp\n#test lexer\n\nstdp.println(\"x\");\n")
    par020 = [d for d in diagnostics if d["code"] == "PAR020"]
    assert par020, f"debe reportarse: {[d['code'] for d in diagnostics]}"
    assert "PRIMER" in par020[0]["message"], \
        f"el mensaje debe nombrar la regla: {par020[0]['message']}"
    assert par020[0]["line"] == 2, "debe señalar la línea del '#test', no otra"


# --------------------------------------------------------------------------- #
# lo que DETIENE una compilación es la severidad, no el número de diagnósticos
# --------------------------------------------------------------------------- #

def test_un_aviso_no_detiene_la_compilacion():
    """La escala de ``Severity`` promete desde el principio que un WARNING
    deja continuar. El pipeline no lo cumplía: cualquier diagnóstico ponía el
    código de salida en error y el HIR no se emitía, así que declarar algo
    como aviso no servía de nada — y por eso no había ni uno."""
    from error_handler.error import Severity, blocks

    class _Diag:
        def __init__(self, severity):
            self.severity = severity

    assert not blocks([_Diag(Severity.WARNING), _Diag(Severity.NOTE)])
    assert blocks([_Diag(Severity.WARNING), _Diag(Severity.CRITICAL)])
    assert blocks([_Diag(Severity.PANIC)])
    assert not blocks([])


def test_un_programa_con_solo_avisos_emite_su_hir():
    """La prueba de que la compuerta es la correcta de punta a punta: un
    ``match`` no exhaustivo (SEM030) avisa y el artefacto se emite igual."""
    import os
    import sys
    import tempfile

    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if repo not in sys.path:
        sys.path.insert(0, repo)
    try:
        import google.protobuf  # noqa: F401
    except ImportError:
        print("      (omitido: sin protobuf no hay fase HIR)", file=sys.stderr)
        return

    from driver import CompileOptions, compile_source

    fuente = ("enum Color { ROJO, VERDE };\n"
              "fn main() -> int {\n"
              "    var Color c = Color.ROJO;\n"
              "    match (c) { case Color.ROJO: { return 1; } }\n"
              "    return 0;\n"
              "};\n")
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "aviso.srcx")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(fuente)
        phir = os.path.join(tmp, "aviso.phir")
        resultado = compile_source(src, CompileOptions(emit_hir=phir))

        codigos = [d.code for d in resultado.diagnostics]
        assert "SEM030" in codigos, codigos
        assert resultado.status == 0, (
            f"un aviso no debe detener la compilación (status={resultado.status})")
        assert os.path.isfile(phir), "el HIR tiene que emitirse igual"
