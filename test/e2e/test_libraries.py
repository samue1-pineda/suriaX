"""e2e/libraries — importar y USAR librerías y paquetes de punta a punta.

Cubre la capa que va del linker de librerías (``V0/src/linker_p/``) al
*module linker* del intérprete: resolver el ``#import``, emitir un ``.phir``
por unidad, ligarlas en una imagen y que ``modulo.funcion(...)`` ejecute el
cuerpo correcto.

Cada test escribe su propio árbol de proyecto en un temporal
(``helpers.run_project``), así la suite NO depende del estado real de
``lib/``: lo que se prueba es el mecanismo, no el contenido de la stdlib.

Nombres de unidad: una unidad se identifica por su nombre CALIFICADO
(``IO.stdp``), no por el alias suelto del submódulo — es lo que permite que
dos paquetes publiquen un submódulo homónimo sin pisarse.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import assert_project_output, run_project  # noqa: E402

W = "fn __write__(str s) -> void;\n"

#: un paquete 'text' con DOS submódulos: el caso que exige nombres calificados.
PKG = {
    "lib/text/main.libsrx": "#export package as text\n",
    "lib/text/upper.libsrx": W + """
fn shout(str s) -> void { __write__(s); __write__("!\\n"); }
fn twice(int n) -> int { return n * 2; }
#export as upper
""",
    "lib/text/lower.libsrx": W + """
fn whisper(str s) -> void { __write__(s); __write__("...\\n"); }
#export as lower
""",
}


def _main(body: str, extra: str = "") -> dict:
    return {**PKG, "main.srcx": extra + "\nfn main() -> int {\n" + body +
            "\n    return 0;\n};\n"}


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
# tipos publicados por una librería (se nombran CUALIFICADOS)
# --------------------------------------------------------------------------- #

GEO = {
    "lib/geo/main.libsrx": "#export package as geo\n",
    "lib/geo/point.libsrx": """
struct { int x; int y; } Point;
fn build(int a, int b) -> Point { return Point{ x: a, y: b }; }
fn sum(Point ptr p) -> int { return p.x + p.y; }
#export as point
""",
}


def test_tipo_de_libreria_en_una_anotacion():
    """'point.Point' debe UNIFICAR con el 'Point' que devuelve la librería."""
    assert_project_output(
        {**GEO, "main.srcx": W + "#import geo.point\n"
                                 "fn main() -> int { var point.Point p = point.build(3, 4); "
                                 '__write__(f"{point.sum(&p)}\\n"); return 0; };\n'},
        "7\n")


def test_tipo_de_libreria_construido_con_literal():
    assert_project_output(
        {**GEO, "main.srcx": W + "#import geo.point\n"
                                 "fn main() -> int { var point.Point p = point.Point{ x: 2, y: 5 }; "
                                 '__write__(f"{point.sum(&p)}\\n"); return 0; };\n'},
        "7\n")


def test_tipo_de_libreria_envuelto_en_puntero_y_nullable():
    assert_project_output(
        {**GEO, "main.srcx": W + "#import geo.point\n"
                                 "fn total(point.Point ptr p) -> int { return point.sum(p); };\n"
                                 "fn main() -> int { var point.Point p = point.build(10, 5); "
                                 '__write__(f"{total(&p)}\\n"); return 0; };\n'},
        "15\n")


def test_tipo_de_libreria_como_campo_de_un_struct_local():
    assert_project_output(
        {**GEO, "main.srcx": W + "#import geo.point\n"
                                 "struct { point.Point origin; int id; } Shape;\n"
                                 "fn main() -> int { var Shape s = Shape{ origin: point.build(6, 1), id: 9 }; "
                                 '__write__(f"{point.sum(&s.origin)}\\n"); return 0; };\n'},
        "7\n")


def test_enum_de_libreria():
    files = {
        "lib/col/main.libsrx": "#export package as col\n",
        "lib/col/hue.libsrx": "enum Color { Rojo, Verde, Azul };\n"
                              "fn code(int c) -> int { return c * 10; }\n#export as hue\n",
        "main.srcx": W + "#import col.hue\n"
                         'fn main() -> int { __write__(f"{hue.code(hue.Color.Verde)}\\n"); return 0; };\n',
    }
    assert_project_output(files, "10\n")


# --------------------------------------------------------------------------- #
# hooks declarados por una librería
# --------------------------------------------------------------------------- #

def test_hooks_de_un_tipo_de_libreria_despachan():
    """'print(x)'/'len(x)' sobre un tipo de librería van a SUS hooks."""
    files = {
        "lib/txt/main.libsrx": "#export package as txt\n",
        "lib/txt/cadena.libsrx": W + """
struct { str text; int size; } S;
hook fn __print__(S ptr s) -> void { __write__(s.text); }
hook fn __len__(S ptr s) -> int { return s.size; }
fn of(str t, int n) -> S { return S{ text: t, size: n }; }
#export as cadena
""",
        "main.srcx": W + "#import txt.cadena\n"
                         'fn main() -> int { var cadena.S s = cadena.of("hooked\\n", 6); '
                         'print(s); __write__(f"{len(s)}\\n"); return 0; };\n',
    }
    assert_project_output(files, "hooked\n6\n")


# --------------------------------------------------------------------------- #
# diagnósticos del linker de librerías
# --------------------------------------------------------------------------- #

def test_libreria_inexistente_se_reporta():
    code, _out, err = run_project(
        {"main.srcx": "#import noexiste;\nfn main() -> int { return 0; };\n"},
        args=["--run"])
    assert code != 0 and "SEM009" in err, err


def test_submodulo_inexistente_lista_los_disponibles():
    code, _out, err = run_project(
        {**PKG, "main.srcx": "#import text.nada;\nfn main() -> int { return 0; };\n"},
        args=["--run"])
    assert code != 0 and "SEM011" in err, err


def test_alias_del_export_debe_coincidir_con_el_import():
    """Regla central del linker: un módulo se llama como su '#export'."""
    files = {
        "lib/cosa.libsrx": "fn f() -> void { }\n#export as otra\n",
        "main.srcx": "#import cosa;\nfn main() -> int { return 0; };\n",
    }
    code, _out, err = run_project(files, args=["--run"])
    assert code != 0 and "SEM010" in err, err


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
                              capture_output=True, text=True, cwd=repo,
                              timeout=120)
        if proc.returncode != 0:
            rotas.append(f"{os.path.relpath(ruta, repo)}:\n{proc.stdout}{proc.stderr}")
    assert not rotas, "librerías del repositorio que no compilan:\n" + "\n".join(rotas)
