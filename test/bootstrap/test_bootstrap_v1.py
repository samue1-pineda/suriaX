"""bootstrap/bootstrap_v1 — la V1 (el compilador escrito en suriaX) contra la
V0: el MISMO ``.phir``, byte a byte.

``src/main.srcx`` es la V1: lee un fuente y escribe su HIR con el lexer y el
parser de ``src/frontend/``, la Semántica de ``src/semantica/`` y el emisor de
``src/hir/``. Aquí la compila la V0, la ejecuta la VM, y el ``.phir`` que
produce sobre cada programa de ``test/bootstrap/v1/`` se compara con el que
produce la V0 sobre el mismo programa. Cada PROYECTO de
``test/bootstrap/v1_proyectos/`` (un ``main.srcx`` con sus librerías en
``lib/``) compara además cada UNIDAD: el ``<unidad>.phir`` de cada librería.
La meta del bootstrap es el PUNTO FIJO (la V1 compilándose a sí misma); cada
lote agranda el subconjunto que cubre y este corpus con él.

Si difieren, el fallo dice en qué byte y muestra las dos vistas legibles del
HIR (``suriax-hir --pretty``): el byte solo no dice qué nodo es.
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

_AQUI = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_AQUI))
sys.path.insert(0, os.path.dirname(_AQUI))

from helpers import hir_binary, omitir  # noqa: E402

# V0/main.py y no el main.py de la raíz: ese agrega --run (compilar la V1
# la EJECUTARÍA sin argumentos)
_MAIN = os.path.join(_REPO, "V0", "main.py")
_CORPUS = os.path.join(_AQUI, "v1")
_PROYECTOS = os.path.join(_AQUI, "v1_proyectos")
#: la stdlib que usan las dos: la V0 la deduce de donde está; la V1 la recibe
_STDLIB = os.path.join(_REPO, "lib")
#: los paquetes de la V1 (cada uno va a la 'lib/' del proyecto de prueba)
_PAQUETES = ("frontend", "semantica", "hir")

#: el proyecto de prueba con la V1 ya compilada: se arma UNA vez por corrida
_estado: dict = {}


def _correr(orden, cwd: str, limite: float = 600,
            entorno: Optional[dict] = None) -> subprocess.CompletedProcess:
    return subprocess.run(orden, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=limite,
                          env={**os.environ, "PYTHONUTF8": "1", **(entorno or {})})


def _v1() -> tuple[str, str]:
    """``(carpeta del proyecto, binario de la VM)``, con la V1 compilada."""
    vm = hir_binary()
    if vm is None:
        omitir("suriax-hir no está construido: la V1 corre en la VM "
               "(cmake --build build --target suriax-hir)")
    if "tmp" not in _estado:
        tmp = tempfile.mkdtemp(prefix="suriax-v1-")
        atexit.register(shutil.rmtree, tmp, ignore_errors=True)
        shutil.copytree(os.path.join(_REPO, "lib"), os.path.join(tmp, "lib"))
        for paquete in _PAQUETES:
            shutil.copytree(os.path.join(_REPO, "src", paquete),
                            os.path.join(tmp, "lib", paquete))
        shutil.copy(os.path.join(_REPO, "src", "main.srcx"), tmp)
        # 'native': las unidades de librería se emiten junto al .phir
        with open(os.path.join(tmp, ".suriaX_config.yaml"), "w", encoding="utf-8") as fh:
            fh.write("version: 1\ntarget: native\n")
        hecho = _correr([sys.executable, _MAIN, "main.srcx", "--emit-hir"], tmp)
        assert hecho.returncode == 0, f"la V0 no compila la V1:\n{hecho.stdout}{hecho.stderr}"
        _estado["tmp"] = tmp
    return _estado["tmp"], vm


def _vista(vm: str, phir: str, cwd: str) -> str:
    return _correr([vm, phir, "--pretty"], cwd).stdout


def _compilador(tmp: str, compilador: Optional[str]) -> str:
    """El .phir del compilador que se prueba: ``compilador`` o, por defecto,
    la V1 compilada por la V0 (``dumps/main.srcx.phir``, la etapa A)."""
    return compilador or os.path.join(tmp, "dumps", "main.srcx.phir")


def _comparar(programa: str, compilador: Optional[str] = None) -> None:
    tmp, vm = _v1()
    shutil.copy(os.path.join(_CORPUS, programa), tmp)
    v0 = _correr([sys.executable, _MAIN, programa, "--emit-hir"], tmp)
    assert v0.returncode == 0, f"la V0 rechaza '{programa}':\n{v0.stdout}{v0.stderr}"
    salida = programa + ".v1.phir"
    v1 = _correr([vm, _compilador(tmp, compilador), "--run", "--quiet",
                  "--", programa, salida], tmp)
    assert v1.returncode == 0, f"la V1 falla con '{programa}':\n{v1.stdout}{v1.stderr}"
    _igual(programa, os.path.join("dumps", programa + ".phir"), salida, vm, tmp)


def _igual(nombre: str, v0_phir: str, v1_phir: str, vm: str, cwd: str) -> None:
    """Los dos .phir, byte a byte; si difieren, en qué byte y las dos vistas."""
    with open(os.path.join(cwd, v0_phir), "rb") as fh:
        esperado = fh.read()
    with open(os.path.join(cwd, v1_phir), "rb") as fh:
        obtenido = fh.read()
    if esperado == obtenido:
        return
    byte = next((i for i, (x, y) in enumerate(zip(esperado, obtenido)) if x != y),
                min(len(esperado), len(obtenido)))
    raise AssertionError(
        f"'{nombre}': el .phir de la V1 difiere del de la V0 en el byte {byte} "
        f"({len(obtenido)} contra {len(esperado)} bytes).\n"
        f"--- V0 ---\n{_vista(vm, v0_phir, cwd)}\n"
        f"--- V1 ---\n{_vista(vm, v1_phir, cwd)}")


def _comparar_proyecto(nombre: str, compilador: Optional[str] = None) -> None:
    """Un proyecto con librerías: la V0 y la V1 lo compilan, y cada unidad
    (el programa y cada librería que carga) tiene que dar el mismo .phir. La
    lista de unidades tiene que ser la misma."""
    tmp, vm = _v1()
    carpeta = os.path.join(tmp, "proyecto_" + nombre)
    shutil.rmtree(carpeta, ignore_errors=True)
    shutil.copytree(os.path.join(_PROYECTOS, nombre), carpeta)
    with open(os.path.join(carpeta, ".suriaX_config.yaml"), "w", encoding="utf-8") as fh:
        fh.write("version: 1\ntarget: native\n")
    v0 = _correr([sys.executable, _MAIN, "main.srcx", "--emit-hir"], carpeta)
    assert v0.returncode == 0 and "no se emit" not in v0.stdout + v0.stderr, (
        f"la V0 rechaza el proyecto '{nombre}':\n{v0.stdout}{v0.stderr}")
    os.makedirs(os.path.join(carpeta, "v1"))
    v1 = _correr([vm, _compilador(tmp, compilador), "--run", "--quiet",
                  "--", "main.srcx", os.path.join("v1", "main.srcx.phir"),
                  "--stdlib", _STDLIB], carpeta)
    assert v1.returncode == 0, f"la V1 falla con el proyecto '{nombre}':\n{v1.stdout}{v1.stderr}"
    unidades_v0 = sorted(os.listdir(os.path.join(carpeta, "dumps")))
    unidades_v1 = sorted(os.listdir(os.path.join(carpeta, "v1")))
    assert unidades_v0 == unidades_v1, (
        f"'{nombre}': otras unidades.\n  V0: {unidades_v0}\n  V1: {unidades_v1}")
    for unidad in unidades_v0:
        _igual(f"{nombre}/{unidad}", os.path.join("dumps", unidad),
               os.path.join("v1", unidad), vm, carpeta)


def _registrar(programa: str) -> None:
    def prueba():
        _comparar(programa)
    nombre = "test_v1_" + os.path.splitext(programa)[0]
    prueba.__name__ = nombre
    prueba.__doc__ = f"La V1 emite para '{programa}' el mismo .phir que la V0."
    globals()[nombre] = prueba


def _registrar_proyecto(nombre: str) -> None:
    def prueba():
        _comparar_proyecto(nombre)
    prueba.__name__ = "test_v1_proyecto_" + nombre
    prueba.__doc__ = f"La V1 emite para el proyecto '{nombre}' las mismas unidades que la V0."
    globals()[prueba.__name__] = prueba


for _programa in sorted(os.listdir(_CORPUS)):
    if _programa.endswith(".srcx"):
        _registrar(_programa)

for _proyecto in sorted(os.listdir(_PROYECTOS)):
    if os.path.isfile(os.path.join(_PROYECTOS, _proyecto, "main.srcx")):
        _registrar_proyecto(_proyecto)


#: programas VÁLIDOS para la V0 que usan algo fuera del subconjunto de la
#: V1: (fuente, lo que tiene que nombrar el aviso, línea:col)
_FUERA_DEL_SUBCONJUNTO = (
    ("const type T;\nfn main() -> int { return 0; }\n", "'type'", "1:1"),
    ("struct { int a; } P;\nfn main() -> int { return sizeof(P); }\n", "'sizeof'", "2:27"),
    # (un 'test' salió de esta lista: en la V0 exige un 'expect', que la V1
    # todavía no conoce; ver 'test_bootstrap_parser.V1_SIN_PRUEBAS')
    ("@trait struct { fn __next__(self ptr) -> int?; } iterable;\n"
     "dunder fn __next__(L ptr self) -> int? { return null; }\n"
     "@impl(iterable) struct { int pos; } L;\nfn main() -> int { return 0; }\n",
     "'@trait'", "1:1"),
    ("struct { int v; } R;\nhook fn __min__(R ptr _) -> int { return 0; }\n"
     "hook fn __max__(R ptr _) -> int { return 9; }\nfn main() -> int { return min(R); }\n",
     "'min'/'max'", "4:27"),
    # lo que el chequeo de tipos inserta en la V0 (una conversión implícita)
    ("fn main() -> int { var byte b = 5; return 0; }\n", "'byte'", "1:33"),
    # la V0 emite los '__cast__' en otra tabla del HIR ('casts')
    ("#from d_types #import dt_variables as dt\nfn main() -> int { return 0; }\n",
     "'__cast__'", "1:1"),
)


def test_lo_que_la_v1_no_compila_se_dice():
    """Lo que la V1 todavía no emite NO sale como un `.phir` incompleto: la
    compilación se detiene diciendo qué y dónde. (Antes un 'type' o un
    '@trait' se emitían como una sentencia vacía, sin aviso.)"""
    tmp, vm = _v1()
    for i, (fuente, que, donde) in enumerate(_FUERA_DEL_SUBCONJUNTO):
        archivo = f"fuera_{i}.srcx"
        with open(os.path.join(tmp, archivo), "w", encoding="utf-8") as fh:
            fh.write(fuente)
        v0 = _correr([sys.executable, _MAIN, archivo, "--emit-hir"], tmp)
        assert v0.returncode == 0, f"la V0 tiene que aceptarlo:\n{fuente}\n{v0.stdout}{v0.stderr}"
        salida = os.path.join("fuera_salida", archivo + ".phir")
        hecho = _correr([vm, os.path.join("dumps", "main.srcx.phir"), "--run", "--quiet",
                         "--", archivo, salida, "--stdlib", _STDLIB], tmp)
        assert hecho.returncode == 1, (fuente, hecho.returncode, hecho.stderr[-800:])
        assert f"{archivo}:{donde}: la V1 todavía no compila" in hecho.stderr \
            and que in hecho.stderr, (fuente, hecho.stderr[-800:])
        assert not os.path.exists(os.path.join(tmp, salida)), f"escribió un .phir:\n{fuente}"


def test_la_v1_crea_la_carpeta_de_salida():
    """Como la V0: escribir en 'nueva/sub/x.phir' crea las carpetas que
    falten ('mkdir -p'). Antes era EXC003 y las recetas tenían que crearla."""
    tmp, vm = _v1()
    with open(os.path.join(tmp, "hola_carpeta.srcx"), "w", encoding="utf-8") as fh:
        fh.write('#from io #import stdp\nfn main() -> int { stdp.println("hola"); return 0; }\n')
    salida = os.path.join("carpeta_nueva", "sub", "hola.phir")
    assert not os.path.exists(os.path.join(tmp, "carpeta_nueva"))
    hecho = _correr([vm, os.path.join("dumps", "main.srcx.phir"), "--run", "--quiet",
                     "--", "hola_carpeta.srcx", salida, "--stdlib", _STDLIB], tmp)
    assert hecho.returncode == 0, hecho.stderr[-1500:]
    corrida = _correr([vm, salida, "--run", "--quiet"], tmp)
    assert corrida.stdout.strip() == "hola", (corrida.stdout, corrida.stderr[-500:])
