"""e2e/programas_de_fuego — programas REALES y complejos, de punta a punta.

Las pruebas por construcción aislada no encuentran lo que se rompe al
COMBINAR: un genérico de librería en la firma de una función, recursión mutua
dentro de una librería, un ``v[i] = x`` sobre un puntero a un vector. Los tres
programas de ``test/e2e/fuego/`` se escribieron para eso, y encontraron seis
fallos que ninguna prueba cubría (las regresiones van abajo, una por fallo).

    fuego/inventario.srcx   structs con métodos y hooks, enum con payload,
                            Vector<T> de structs, ordenamiento, búsqueda
                            binaria, nullables, excepciones filtradas, cadenas
    fuego/algoritmos.srcx   criba sobre un bloque de 'mem', memo, matrices,
                            recursión, César, pila GENÉRICA propia, lista
                            enlazada con punteros nullables
    fuego/proyecto/         paquete propio con submódulos, tipos, enum con
                            payload y hooks cruzando unidades, y la propiedad
                            bajo estrés (return temprano en bucles, throw que
                            cruza destructores, move de campos y en ramas)

La salida esperada de cada uno (``.salida``) se verificó a mano al escribirla.
Se corren sobre una COPIA en un temporal: compilar deja 'dumps/' y 'log/'
junto al fuente, y eso no puede ensuciar el árbol del repositorio.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import assert_output, run_project, run_source  # noqa: E402

_AQUI = os.path.dirname(os.path.abspath(__file__))
_FUEGO = os.path.join(_AQUI, "fuego")
_REPO = os.path.dirname(os.path.dirname(_AQUI))
_MAIN = os.path.join(_REPO, "main.py")


def _salida_del_programa(stdout: str) -> str:
    """Lo que imprimió el PROGRAMA, sin las líneas informativas del compilador."""
    lineas = [l for l in stdout.splitlines()
              if not l.startswith(("frontend OK", "HIR "))
              and not (l.lstrip().startswith("unidad '") and " -> " in l)]
    return "\n".join(lineas) + "\n"


def _correr_fixture(relativo: str) -> None:
    with tempfile.TemporaryDirectory(prefix="suriax-fuego-") as tmp:
        copia = os.path.join(tmp, "fuego")
        shutil.copytree(_FUEGO, copia)
        fuente = os.path.join(copia, relativo)
        proc = subprocess.run([sys.executable, _MAIN, fuente],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300,
                              cwd=os.path.dirname(fuente))
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    assert "Traceback" not in proc.stderr and "ICE000" not in proc.stderr, proc.stderr
    with open(os.path.join(_FUEGO, relativo[:-len(".srcx")] + ".salida"),
              encoding="utf-8") as fh:
        esperado = fh.read()
    obtenido = _salida_del_programa(proc.stdout)
    assert obtenido == esperado, (
        f"{relativo}: la salida cambió.\n--- esperado\n{esperado}\n"
        f"--- obtenido\n{obtenido}")


# --------------------------------------------------------------------------- #
# los programas completos
# --------------------------------------------------------------------------- #

def test_inventario_corre_completo():
    _correr_fixture("inventario.srcx")


def test_algoritmos_corre_completo():
    _correr_fixture("algoritmos.srcx")


def test_proyecto_de_varios_archivos_corre_completo():
    _correr_fixture(os.path.join("proyecto", "app.srcx"))


def test_estadistica_corre_completo():
    _correr_fixture("estadistica.srcx")


def test_los_bloques_test_del_programa_pasan_con_el_runner_del_interprete():
    """'test "..." { }' dentro de un programa real: el runner del intérprete
    (``runtime/interpreter/main.py --test``) los ejecuta y todos pasan."""
    with tempfile.TemporaryDirectory(prefix="suriax-fuego-") as tmp:
        copia = os.path.join(tmp, "fuego")
        shutil.copytree(_FUEGO, copia)
        fuente = os.path.join(copia, "estadistica.srcx")
        phir = os.path.join(copia, "estadistica.phir")
        emit = subprocess.run(
            [sys.executable, os.path.join(_REPO, "V0", "main.py"), fuente,
             "--emit-hir", phir],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300, cwd=copia)
        assert emit.returncode == 0, emit.stderr
        # las unidades de librería quedan JUNTO al .phir principal, que es
        # donde las busca el runner (antes iban a 'dumps/' y había que
        # copiarlas a mano)
        assert os.path.isfile(os.path.join(copia, "array.vector.phir")), \
            sorted(os.listdir(copia))
        proc = subprocess.run(
            [sys.executable, os.path.join(_REPO, "runtime", "interpreter",
                                          "main.py"), phir, "--test"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300, cwd=copia)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "2 pasaron, 0 fallaron" in proc.stdout, proc.stdout


# --------------------------------------------------------------------------- #
# regresiones: un fallo encontrado por los programas = una prueba mínima
# --------------------------------------------------------------------------- #

_VEC = "#import array.vector as vec\n"


def test_un_generico_de_libreria_en_el_retorno_de_una_funcion():
    """'fn hace() -> vec.Vector<int>' devolvía 'vec.Vector<int>' sin
    canonizar, y guardarlo en un 'var vec.Vector<int>' (canónico:
    'vector.Vector<int>') era AST006 entre dos nombres del MISMO tipo."""
    code, _out, err = run_source(
        _VEC + "fn hace() -> vec.Vector<int> { return vec.make<int>(2); }\n"
        "fn main() -> int { var vec.Vector<int> v = hace(); v.push(7); "
        "return v.get(0); };", args=["--run"])
    assert code == 7, (code, err)


def test_un_generico_de_libreria_en_un_parametro():
    code, _out, err = run_source(
        _VEC + "fn mide(vec.Vector<int> ptr v) -> int { return v.len(); }\n"
        "fn main() -> int { var vec.Vector<int> x = vec.make<int>(4); "
        "x.push(1); x.push(2); return mide(&x); };", args=["--run"])
    assert code == 2, (code, err)


def test_un_campo_generico_recibe_el_retorno_de_una_funcion():
    code, _out, err = run_source(
        _VEC + "struct { vec.Vector<int> xs; } Caja;\n"
        "fn hace() -> vec.Vector<int> { return vec.make<int>(2); }\n"
        "fn main() -> int { var Caja c = Caja{ xs: hace() }; c.xs.push(3); "
        "return c.xs.len(); };", args=["--run"])
    assert code == 1, (code, err)


_LIB_RECURSIVA = """\
enum Tipo { UNO = 10, DOS = 20 };
struct { int pos; } Estado;
public fn familia(Tipo t) -> int { return cast<int>(t) / 10; }
public fn a(Estado ptr mutable e, int n) -> int {
    if (n == 0) { return e.pos; };
    e.pos = e.pos + 1;
    return b(e, n - 1);
}
public fn b(Estado ptr mutable e, int n) -> int { return a(e, n); }
public fn nuevo() -> Estado { return Estado{ pos: 0 }; }
#export as rec
"""


def test_una_libreria_con_recursion_mutua_y_casts_de_su_enum_compila_como_unidad():
    """Dos fallos que solo aparecían al emitir el '.phir' de la LIBRERÍA (su
    segundo análisis, como unidad propia 'rec'):

    - 'a' llama a 'b', declarada después: la firma de 'b' no estaba enlazada
      aún y 'Estado ptr mutable' no unificaba con 'rec.Estado ptr mutable';
    - 'cast<int>(t)' sobre su propio enum buscaba 'rec.TType' como RUTA de
      import y daba SEM016.
    """
    code, out, err = run_project({
        "rec.libsrx": _LIB_RECURSIVA,
        "main.srcx": "#import rec\nfn __write__(str s) -> void;\n"
                     "fn main() -> int { var rec.Estado e = rec.nuevo(); "
                     "__write__(f\"{rec.a(&e, 4)} {rec.familia(rec.Tipo.DOS)}\\n\"); "
                     "return 0; };\n",
    }, args=["--run"])
    assert code == 0, (code, out, err)
    assert "4 2" in out, (out, err)


def test_los_errores_de_una_unidad_de_libreria_se_muestran():
    """Antes solo salía "la unidad 'x' tiene errores; su .phir no se emitió",
    sin decir CUÁLES. Se provoca con la librería rota a propósito y se llama
    directo al constructor de unidades."""
    for p in (_REPO, os.path.join(_REPO, "V0")):
        if p not in sys.path:
            sys.path.insert(0, p)
    from driver.pipeline import build_library_units
    from driver.reporting import SilentReporter

    class Captura(SilentReporter):
        def __init__(self):
            self.bloques = []

        def diagnostics(self, titulo, diagnosticos):
            self.bloques.append((titulo, [d.code for d in diagnosticos]))

    with tempfile.TemporaryDirectory(prefix="suriax-unidad-") as tmp:
        ruta = os.path.join(tmp, "rota.libsrx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write("public fn f() -> int { return nada; }\n#export as rota\n")
        reporter = Captura()
        unidades, fallo = build_library_units({"rota": ruta}, {},
                                              reporter=reporter)
    assert unidades == {}
    assert fallo and "rota" in fallo, fallo
    assert reporter.bloques, "los errores de la unidad no se reportaron"
    titulo, codigos = reporter.bloques[0]
    assert "rota" in titulo and "SEM001" in codigos, reporter.bloques


def test_indexar_a_traves_de_un_puntero_a_un_vector_usa_sus_hooks():
    """'v[i] = x' con 'v: Vector<T> ptr mutable': la Semántica lo tipaba con
    el hook y el intérprete lo indexaba como memoria cruda (RT013)."""
    assert_output(
        _VEC + "fn __write__(str s) -> void;\n"
        "fn pon(vec.Vector<int> ptr mutable v) -> void { v[1] = 99; }\n"
        "fn lee(vec.Vector<int> ptr v) -> int { return v[1]; }\n"
        "fn main() -> int { var vec.Vector<int> x = vec.make<int>(3); "
        "x.push(1); x.push(2); pon(&x); "
        "__write__(f\"{x.get(1)} {lee(&x)}\\n\"); return 0; };",
        "99 99\n")


def test_un_throw_no_capturado_tiene_codigo_RT020():
    code, _out, err = run_source(
        "fn main() -> int { throw \"sin red\"; return 0; };", args=["--run"])
    assert code == 70, (code, err)
    assert "RT020" in err and "no capturado" in err, err
