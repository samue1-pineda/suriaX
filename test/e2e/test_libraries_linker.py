"""e2e/libraries: el contrato #export, ciclos, .srcx como libreria y metodos.

Parte de ``test_libraries.py`` (partido por tema); lo compartido esta en
``libraries_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import assert_project_output, run_project  # noqa: E402
from libraries_support import (  # noqa: E402
    PKG,
    W,
)

# --------------------------------------------------------------------------- #
# pruebas arduas del linker: contrato #export, ciclos, .srcx, dotted, caché
# --------------------------------------------------------------------------- #

def test_libreria_sin_export_es_invalida():
    """Toda .libsrx debe TERMINAR en '#export'; si no -> SEM010."""
    files = {
        "lib/sinexport.libsrx": "fn f() -> void { }\n",
        "main.srcx": "#import sinexport;\nfn main() -> int { return 0; };\n",
    }
    err = run_project(files)[2]
    assert "SEM010" in err, err


def test_libreria_con_errores_internos_es_invalida():
    """Errores léxicos/sintácticos DENTRO de la lib -> SEM010 (con su ruta)."""
    files = {
        "lib/rota.libsrx": "fn f( -> void { }\n#export as rota\n",
        "main.srcx": "#import rota;\nfn main() -> int { return 0; };\n",
    }
    err = run_project(files)[2]
    assert "SEM010" in err, err


def test_import_circular_se_detecta():
    """a -> b -> a: el guard de la caché corta el ciclo (SEM010)."""
    files = {
        "lib/a.libsrx": "#import b\nfn fa() -> void { }\n#export as a\n",
        "lib/b.libsrx": "#import a\nfn fb() -> void { }\n#export as b\n",
        "main.srcx": "#import a\nfn main() -> int { return 0; };\n",
    }
    err = run_project(files)[2]
    assert "SEM010" in err, err


def test_srcx_como_libreria_emite_nota():
    """Un .srcx usado como librería compila pero avisa con NOTE001."""
    files = {
        "lib/util.srcx": W + "fn u(str s) -> void { __write__(s); }\n#export as util\n",
        "main.srcx": W + "#import util\n"
                         'fn main() -> int { util.u("ok\\n"); return 0; };\n',
    }
    code, out, err = run_project(files, args=["--run"])
    assert "NOTE001" in err, err
    assert "ok\n" in out, out


def test_subpaquete_anidado_no_soportado():
    """'#import text.upper.extra' (3 niveles) -> SEM010."""
    files = {**PKG, "main.srcx": "#import text.upper.extra\n"
                                 "fn main() -> int { return 0; };\n"}
    err = run_project(files)[2]
    assert "SEM010" in err, err


def test_reimport_del_mismo_nombre_es_idempotente():
    """Importar dos veces el MISMO submódulo bajo el mismo alias no colisiona."""
    files = {**PKG, "main.srcx": "#import text.upper\n#import text.upper\n"
                                 'fn main() -> int { upper.shout("z"); return 0; };\n'}
    assert_project_output(files, "z!\n")


def test_dotted_ignora_un_archivo_plano_homonimo():
    """Un import PUNTEADO solo lo satisface un PAQUETE: el .libsrx plano
    homónimo ('text.libsrx') se ignora en vez de bloquear el submódulo."""
    files = {
        **PKG,
        "lib/text.libsrx": "fn flat() -> void { }\n#export as text\n",
        "main.srcx": '#import text.upper\nfn main() -> int { upper.shout("p"); return 0; };\n',
    }
    assert_project_output(files, "p!\n")


# --------------------------------------------------------------------------- #
# métodos (dunder fn) de un tipo declarado por una librería, CROSS-MÓDULO
# --------------------------------------------------------------------------- #

def test_metodos_de_un_tipo_de_libreria_cross_modulo():
    """Un 'dunder fn __m__(T ptr self, ...)' declarado en una librería se
    despacha como método 'x.__m__(...)' desde el consumidor, sobre un valor del
    tipo de la librería (owner cualificado). Muta el receptor por referencia."""
    files = {
        "lib/counter/main.libsrx": (
            "struct { int cur; } Counter;\n"
            "dunder fn __inc__(Counter ptr mutable c) -> void { c.cur = c.cur + 1; }\n"
            "dunder fn __get__(Counter ptr c) -> int { return c.cur; }\n"
            "fn make() -> Counter { return Counter{ cur: 0 }; }\n"
            "#export package as counter\n"
        ),
        "main.srcx": W + (
            "#import counter\n"
            "fn main() -> int {\n"
            "    var counter.Counter c = counter.make();\n"
            "    c.__inc__(); c.__inc__(); c.__inc__();\n"
            '    __write__(f"cur={c.__get__()}\\n");\n'
            "    return 0;\n"
            "};\n"
        ),
    }
    assert_project_output(files, "cur=3\n")


def test_todas_las_librerias_del_repositorio_compilan():
    """Cada ``.libsrx`` de ``lib/`` pasa el frontend sin un solo diagnóstico.

    La librería estándar es lo primero que toca quien prueba el lenguaje, y
    hasta la 0.1.4 hubo una (``lib/math/basic.libsrx``) que ni siquiera
    parseaba: el informe público la listaba como error conocido. Los tests de
    entonces usaban librerías escritas dentro del propio test —aislamiento
    correcto para probar el LINKER, pero por eso mismo ninguno miraba las
    reales.

    Se compilan una por una, no importándolas desde un programa: así el
    fallo dice QUÉ archivo, y una librería que nadie importa todavía no se
    queda sin comprobar.
    """
    import glob
    import subprocess

    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    compilador = os.path.join(repo, "V0", "main.py")
    libs = sorted(glob.glob(os.path.join(repo, "lib", "**", "*.libsrx"),
                            recursive=True))
    assert libs, "no se encontró ninguna librería en lib/"

    rotas = []
    for ruta in libs:
        proc = subprocess.run([sys.executable, compilador, ruta],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", cwd=repo,
                              timeout=120)
        if proc.returncode != 0:
            rotas.append(f"{os.path.relpath(ruta, repo)}:\n{proc.stdout}{proc.stderr}")
    assert not rotas, "librerías del repositorio que no compilan:\n" + "\n".join(rotas)
