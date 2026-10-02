"""e2e/libraries: formas de import, unidades y dependencias entre librerias.

Parte de ``test_libraries.py`` (partido por tema); lo compartido esta en
``libraries_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import assert_project_output, run_project  # noqa: E402
from libraries_support import (  # noqa: E402
    W,
    _main,
)

# --------------------------------------------------------------------------- #
# las formas de import, y el callback '.<funcion>'
# --------------------------------------------------------------------------- #

def test_import_paquete_y_callback_de_submodulo():
    """'#import text' -> 'text.upper.shout(...)': paquete, submódulo, función."""
    assert_project_output(
        _main('    text.upper.shout("A");\n    text.lower.whisper("b");',
              "#import text"),
        "A!\nb...\n")


def test_import_submodulo_directo():
    """'#import text.upper' liga SOLO el submódulo, bajo su propio alias."""
    assert_project_output(
        _main('    upper.shout("C");', "#import text.upper"), "C!\n")


def test_import_con_alias_explicito():
    assert_project_output(
        _main('    u.shout("D");', "#import text.upper as u"), "D!\n")


def test_from_paquete_import_submodulo():
    assert_project_output(
        _main('    upper.shout("E");', "#from text #import upper"), "E!\n")


def test_from_submodulo_import_funcion():
    """'#from text.upper #import shout': un solo símbolo, sin polución."""
    assert_project_output(
        _main('    shout("F");', "#from text.upper #import shout"), "F!\n")


def test_valor_de_retorno_a_traves_del_callback():
    assert_project_output(
        _main('    var int n = text.upper.twice(21);\n    __write__(f"{n}\\n");',
              W + "#import text"),
        "42\n")


def test_paquete_y_submodulo_importados_a_la_vez():
    assert_project_output(
        _main('    text.upper.shout("G");\n    lower.whisper("h");',
              "#import text\n#import text.lower"),
        "G!\nh...\n")


# --------------------------------------------------------------------------- #
# unidades: nombres calificados y colisiones
# --------------------------------------------------------------------------- #

def test_submodulos_homonimos_en_paquetes_distintos():
    """Dos paquetes con un submódulo 'util' cada uno: unidades DISTINTAS.

    Con nombres de unidad sin calificar ambos compartirían ``util.phir`` y
    una entrada de ``Image.units``, y el segundo ganaría en silencio.
    """
    files = {
        "lib/alpha/main.libsrx": "#export package as alpha\n",
        "lib/alpha/util.libsrx": W + 'fn who() -> void { __write__("alpha\\n"); }\n#export as util\n',
        "lib/beta/main.libsrx": "#export package as beta\n",
        "lib/beta/util.libsrx": W + 'fn who() -> void { __write__("beta\\n"); }\n#export as util\n',
        "main.srcx": "#import alpha\n#import beta\n"
                     "fn main() -> int { alpha.util.who(); beta.util.who(); return 0; };\n",
    }
    assert_project_output(files, "alpha\nbeta\n")


def test_cada_unidad_emite_su_phir_calificado():
    code, out, _err = run_project(
        _main('    text.upper.shout("x");', "#import text"), args=["--emit-hir"])
    assert code == 0, out
    assert "text.upper" in out and "text.lower" in out, (
        f"cada submódulo debe emitir su unidad calificada; salida: {out!r}")


# --------------------------------------------------------------------------- #
# dependencias entre librerías
# --------------------------------------------------------------------------- #

BASE = {
    "lib/base/main.libsrx": "#export package as base\n",
    "lib/base/core.libsrx": W + 'fn emit(str s) -> void { __write__(s); }\n#export as core\n',
    "lib/high/main.libsrx": "#export package as high\n",
    "lib/high/api.libsrx": '#import base.core\n\n'
                           'fn banner() -> void { core.emit("[api]\\n"); }\n#export as api\n',
}


def test_libreria_que_importa_otra_libreria():
    """Transitiva: main -> high.api -> base.core, y el cuerpo se ejecuta."""
    assert_project_output(
        {**BASE, "main.srcx": "#import high.api\n"
                              "fn main() -> int { api.banner(); return 0; };\n"},
        "[api]\n")


def test_diamante_la_unidad_compartida_se_carga_una_vez():
    assert_project_output(
        {**BASE, "main.srcx": "#import high.api\n#import base.core\n"
                              "fn main() -> int { api.banner(); "
                              'core.emit("[main]\\n"); return 0; };\n'},
        "[api]\n[main]\n")


def test_estado_global_de_la_libreria_se_inicializa_una_vez():
    files = {
        "lib/ctr/main.libsrx": "#export package as ctr\n",
        "lib/ctr/count.libsrx": W + "var int hits = 0;\n"
                                    "fn bump() -> int { hits = hits + 1; return hits; }\n"
                                    "#export as count\n",
        "main.srcx": W + "#import ctr.count\n"
                         "fn main() -> int { count.bump(); count.bump(); "
                         '__write__(f"{count.bump()}\\n"); return 0; };\n',
    }
    assert_project_output(files, "3\n")


# --------------------------------------------------------------------------- #
# '#from' de un TIPO y de una función GENÉRICA
# --------------------------------------------------------------------------- #

_COSA = """
public struct { int x; } Plano;
public enum Forma { Circulo(int), Nada };
public fn id<T>(T x) -> T { return x; }
public fn nuevo<T>(int n) -> T ptr mutable { return mem.reserve<T>(n); }
#export as cosa
"""


def test_from_de_un_tipo_se_usa_como_tipo():
    """Regresión: '#from cosa #import Plano' registraba el struct como un
    VALOR, y 'Plano p' o 'Plano{...}' daban AST005 ("el tipo no está
    declarado"). Ahora entra al espacio de tipos como uno propio, con alias,
    y es el MISMO tipo que 'cosa.Plano'."""
    assert_project_output({
        "lib/cosa.libsrx": "#import mem\n" + _COSA,
        "main.srcx": """#from io #import stdp
#from cosa #import Plano as P
#from cosa #import Forma
#import cosa
fn mide(P ptr p) -> int { return p.x; }
fn main() -> int {
    var P p = P{ x: 4 };
    var cosa.Plano q = p;
    var Forma f = Forma.Circulo(3);
    match (f) {
        case Forma.Circulo(r): { stdp.println(f"r={r} p={mide(&p)} q={mide(&q)}"); }
        case Forma.Nada: { stdp.println("nada"); }
    }
    return 0;
}
""",
    }, "r=3 p=4 q=4")


def test_from_de_una_funcion_generica_sustituye_su_parametro():
    """Regresión: la copia de '#from' no llevaba los parámetros de tipo, así
    que 'id<int>(1)' devolvía una 'T' sin ligar (AST006). Es la forma que
    documenta 'mem' ('#from mem #import reserve')."""
    assert_project_output({
        "lib/cosa.libsrx": "#import mem\n" + _COSA,
        "main.srcx": """#from io #import stdp
#from cosa #import id
#from mem #import reserve
fn main() -> int {
    var int ptr mutable p = reserve<int>(2);
    p[0] = id<int>(5) + id(1);
    var str s = id("ok");
    stdp.println(f"{p[0]} {s}");
    return 0;
}
""",
    }, "6 ok")
