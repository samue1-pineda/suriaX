"""bootstrap/bootstrap_lexer — el lexer escrito en suriaX contra el de la V0.

``src/frontend/`` es el primer paso del bootstrap: el análisis léxico de
suriaX escrito en suriaX. Como sus números de clase son los mismos que los de
la V0, la prueba es DIFERENCIAL: el mismo fuente pasa por los dos lexers y se
comparan token a token (clase, línea, columna y lexema) y los códigos de los
errores léxicos, en orden. Cualquier diferencia es un error de uno de los dos
—y ya encontró uno en la V0 (un dígito no ASCII como ``²`` era un ICE).

Diferencias conocidas, fuera de estas muestras (ver ``src/frontend/readme.md``):
``#extern cpp { ... }`` (el bloque crudo) y la clase Unicode de símbolos no
ASCII que no son letras (``€``): el lenguaje todavía no tiene tablas Unicode.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

_AQUI = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_AQUI))
sys.path.insert(0, os.path.dirname(_AQUI))
sys.path.insert(0, os.path.join(_REPO, "V0"))

from src.frontend.lexer.lexer import Lexer  # noqa: E402

_FRONTEND = os.path.join(_REPO, "src", "frontend")
_MAIN = os.path.join(_REPO, "main.py")

_DRIVER = """#from io #import stdp
#import frontend.tokens as tk
#import frontend.lexer as lx
#import frontend.diagnosticos as dg
#import array.vector as vec

fn main() -> int {
    var vec.Vector<dg.Diagnostico> errores = vec.dynamic<dg.Diagnostico>(4);
    var vec.Vector<tk.Token> toks = lx.tokenizar(__FUENTE__, &errores);
    var int i = 0;
    while (i < toks.len()) {
        var tk.Token t = toks.get(i);
        stdp.println(f"{t.linea}:{t.col} {cast<int>(t.tipo)} {t.lexema}");
        i = i + 1;
    }
    var int e = 0;
    while (e < errores.len()) {
        stdp.println("error " + dg.texto(errores.get(e)));
        e = e + 1;
    }
    return 0;
}
"""


def _como_literal(texto: str) -> str:
    """``texto`` escrito como una cadena de suriaX (plana: sin interpolar)."""
    escapado = (texto.replace("\\", "\\\\").replace('"', '\\"')
                .replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r"))
    return f'"{escapado}"'


def _v0(fuente: str):
    lexer = Lexer(fuente)
    tokens = lexer.tokenize()
    lineas = [f"{t.ln}:{t.col} {t.type.value} {t.lexeme}" for t in tokens]
    return lineas, [f"{e.code} {e.line}:{e.column}" for e in lexer.errors]


def _suriax(fuente: str):
    with tempfile.TemporaryDirectory(prefix="suriax-bootstrap-") as tmp:
        destino = os.path.join(tmp, "lib", "frontend")
        os.makedirs(destino)
        for nombre in ("main.libsrx", "tokens.libsrx", "lexer.libsrx", "diagnosticos.libsrx"):
            shutil.copy(os.path.join(_FRONTEND, nombre), destino)
        programa = os.path.join(tmp, "driver.srcx")
        with open(programa, "w", encoding="utf-8") as fh:
            fh.write(_DRIVER.replace("__FUENTE__", _como_literal(fuente)))
        proc = subprocess.run(
            [sys.executable, _MAIN, programa], cwd=tmp, capture_output=True,
            encoding="utf-8", errors="replace", timeout=600,
            env={**os.environ, "PYTHONUTF8": "1"})
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    lineas, codigos = [], []
    for linea in proc.stdout.splitlines():
        if linea.startswith(("frontend OK", "HIR ")) or \
                (linea.lstrip().startswith("unidad '") and " -> " in linea):
            continue
        if linea.startswith("error "):
            # "error LEXnnn l:c mensaje" -> "LEXnnn l:c": el codigo Y la
            # posicion, que es lo que un diagnostico tiene que compartir
            codigos.append(" ".join(linea.split()[1:3]))
        else:
            lineas.append(linea)
    return lineas, codigos


def _compara(fuente: str) -> None:
    esperado, errores_v0 = _v0(fuente)
    obtenido, errores_srx = _suriax(fuente)
    for i, (a, b) in enumerate(zip(esperado, obtenido)):
        assert a == b, f"token {i}: V0 {a!r} / suriaX {b!r}"
    assert len(esperado) == len(obtenido), (
        f"V0 dio {len(esperado)} tokens, suriaX {len(obtenido)}:\n"
        f"{esperado[len(obtenido):] or obtenido[len(esperado):]}")
    assert errores_v0 == errores_srx, (errores_v0, errores_srx)


# --------------------------------------------------------------------------- #
# muestras
# --------------------------------------------------------------------------- #

def test_palabras_reservadas_y_operadores():
    _compara(
        "char int float str byte bool void true false null type const var mutable\n"
        "fn struct enum sizeof public private internal hook dunder error try\n"
        "catch throw if else while return match case break continue test\n"
        "move free ptr cast and or not\n"
        "+ - * / % = == != < <= > >= -> += -= *= /= %= ++ --\n"
        "( ) { } [ ] . , ; : & ?\n"
        "| ^ ~ << <<= &= |= ^= >> >>= a<<b x>>=1\n")


def test_literales_numericos_caracteres_y_cadenas():
    _compara(
        "12 3.25 0 1.foo 7.x 42.0\n"
        "'a' '\\n' '\\'' '\\\\' 'ñ'\n"
        '"hola" "con \\"comillas\\"" "tab\\t" ""\n'
        'f"x = {x}" f"{{literal}}" f"{f(a{b})}" f"sin nada"\n'
        '"uno" "dos"\n'
        'f"a{x}" "b" "c"\n')


def test_literales_con_base_y_separadores():
    """``0x``/``0b``/``0o`` y ``_`` entre dígitos, y sus errores: los mismos
    tokens y los mismos LEX007 en los dos lexers."""
    _compara(
        "0xFF 0b1010 0o755 0X1f 1_000_000 0xFFFF_FFFF_FFFF_FFFF 3.14_15 0 00\n"
        "0x8000000000000000 0b1_0\n")
    _compara("0x a 0b102 b 1__0 c 1_ d 0x1_0000000000000000 e 0o8 f\n")


def test_nombres_dunder_y_unicode():
    _compara("__free__ ____ __x__ _x1 x_ año 日本 __init valor2\n")


def test_comentarios_y_posiciones():
    _compara(
        "// linea entera\n"
        "a /- en medio -/ b\n"
        "/- varias\n   lineas\n-/ c\n"
        "\t\td  // tabuladores\r\n"
        "e\n")


def test_directivas_y_decoradores():
    _compara(
        "#from io #import stdp\n#export as x\n#test\n"
        "@impl Caja { }\n")


def test_los_errores_lexicos_coinciden():
    _compara(
        'a "sin cerrar\n'
        '"escape \\q malo" b\n'
        "'ab' '' 'x\n"
        "1.2.3 $ ! c\n"
        '#bogus # @ @1\n'
        'f"{sin cerrar" f"{}" f"}"\n'
        "fin /- sin cerrar")


def test_un_programa_real():
    """El programa de fuego del inventario, entero."""
    with open(os.path.join(_REPO, "test", "e2e", "fuego", "inventario.srcx"),
              encoding="utf-8") as fh:
        _compara(fh.read())


def test_el_lexer_se_lee_a_si_mismo():
    """El lexer de suriaX tokenizando SU PROPIO fuente: la primera vez que el
    compilador en suriaX lee código del compilador en suriaX."""
    with open(os.path.join(_FRONTEND, "lexer.libsrx"), encoding="utf-8") as fh:
        _compara(fh.read())
