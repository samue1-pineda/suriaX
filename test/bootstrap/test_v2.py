"""bootstrap/v2 — la V2 (la V1 compilada por sí misma) y la reproducibilidad.

La V2 es lo que da la etapa 2 del bootstrap: la V1 de hoy (``src/``),
compilada por la V1 que compiló la V0. El punto fijo ya dice que es IDÉNTICA
a la etapa A; aquí se la usa como compilador de verdad sobre TODO el corpus:
cada programa y cada proyecto del bootstrap (el mismo ``.phir`` que la V0) y
el corpus de diagnósticos (la misma lista que la V0). Decisión del
mantenedor (fase V2), aunque sea redundante con el punto fijo: lo que prueba
de más es que la VM corre igual el compilador autocompilado.

Y la REPRODUCIBILIDAD: el mismo compilador da los mismos bytes en otra
carpeta (otro nombre, otra profundidad, con espacios) y con la stdlib en otro
lugar. Las rutas que viajan en el HIR son relativas a su raíz
(``linker_p.resolver.ruta_publica`` en la V0, ``enlazador.ruta_publica`` en la
V1); antes eran absolutas y el punto fijo solo valía dentro de una carpeta.
"""

from __future__ import annotations

import glob
import os
import shutil
import sys
import tempfile

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)
sys.path.insert(0, os.path.dirname(_AQUI))

from helpers import omitir, vm_sanitizada  # noqa: E402
import test_bootstrap_v1 as bv1  # noqa: E402
from test_bootstrap_v1 import (_CORPUS, _MAIN, _PROYECTOS, _REPO, _STDLIB,  # noqa: E402
                               _comparar, _comparar_proyecto, _correr, _igual, _v1)
from test_diagnosticos_v1 import comparar_diagnosticos  # noqa: E402

_estado: dict = {}


def _v2() -> str:
    """La V2: la etapa A compila la V1 de hoy (una vez por corrida)."""
    tmp, vm = _v1()
    if vm_sanitizada(vm):
        omitir(f"'{vm}' es la VM de un sanitizador: compilar la V1 tarda horas")
    if "v2" not in _estado:
        salida = os.path.join(tmp, "v2")
        os.makedirs(salida, exist_ok=True)
        hecho = _correr([vm, os.path.join(tmp, "dumps", "main.srcx.phir"), "--run", "--quiet",
                         "--pasos", "0", "--", "main.srcx", os.path.join(salida, "main.srcx.phir"),
                         "--stdlib", _STDLIB], tmp, 600)
        assert hecho.returncode == 0, hecho.stderr[-2000:]
        _estado["v2"] = os.path.join(salida, "main.srcx.phir")
    return _estado["v2"]


def test_la_v2_compila_el_corpus_como_la_v0():
    v2 = _v2()
    for programa in sorted(os.listdir(_CORPUS)):
        if programa.endswith(".srcx"):
            _comparar(programa, v2)
    for proyecto in sorted(os.listdir(_PROYECTOS)):
        if os.path.isfile(os.path.join(_PROYECTOS, proyecto, "main.srcx")):
            _comparar_proyecto(proyecto, v2)


def test_la_v2_da_los_diagnosticos_de_la_v0():
    comparar_diagnosticos(_v2())


def _proyecto_v1(destino: str) -> None:
    """La forma canónica del proyecto de la V1 (la de ``_v1`` y la semilla)."""
    shutil.copytree(_STDLIB, os.path.join(destino, "lib"))
    for paquete in bv1._PAQUETES:
        shutil.copytree(os.path.join(_REPO, "src", paquete), os.path.join(destino, "lib", paquete))
    shutil.copy(os.path.join(_REPO, "src", "main.srcx"), destino)
    with open(os.path.join(destino, ".suriaX_config.yaml"), "w", encoding="utf-8") as fh:
        fh.write("version: 1\ntarget: native\n")


def _unidades(carpeta: str) -> dict:
    return {os.path.basename(p): open(p, "rb").read()
            for p in sorted(glob.glob(os.path.join(carpeta, "*.phir")))}


def test_la_v1_sale_igual_en_otra_carpeta():
    """La V0 compila la V1 en OTRA carpeta (más profunda, con espacios) y da
    los mismos bytes que en la de siempre, unidad por unidad."""
    tmp, vm = _v1()
    with tempfile.TemporaryDirectory(prefix="suriax otra carpeta-") as otra:
        proyecto = os.path.join(otra, "un nivel", "v1")
        _proyecto_v1(proyecto)
        v0 = _correr([sys.executable, _MAIN, "main.srcx", "--emit-hir"], proyecto)
        assert v0.returncode == 0, v0.stdout[-1500:] + v0.stderr[-1500:]
        aqui = _unidades(os.path.join(tmp, "dumps"))
        alla = _unidades(os.path.join(proyecto, "dumps"))
        assert sorted(aqui) == sorted(alla)
        distintas = [n for n in aqui if aqui[n] != alla[n]]
        assert not distintas, f"otros bytes en otra carpeta: {distintas}"


def test_la_stdlib_en_otro_lugar_no_cambia_el_phir():
    """Un programa que importa de la STDLIB (no de su proyecto), con la stdlib
    en dos lugares distintos y el programa en dos carpetas distintas: la V0
    y la V1 dan los mismos bytes en los cuatro casos, y la librería viaja
    como '<stdlib>/...'."""
    tmp, vm = _v1()
    fuente = ('#from io #import stdp\n#import array.vector as vec\n'
              'fn main() -> int { var vec.Vector<int> v = vec.dynamic<int>(2); v.push(3);\n'
              '    stdp.println(f"{v.get(0)}"); return 0; }\n')
    resultados = {}
    with tempfile.TemporaryDirectory(prefix="suriax-stdlib-") as base:
        for caso in ("uno", "otro lugar/mas hondo"):
            stdlib = os.path.join(base, caso, "stdlib")
            shutil.copytree(_STDLIB, stdlib)
            prog = os.path.join(base, caso, "prog")
            os.makedirs(prog)
            with open(os.path.join(prog, "main.srcx"), "w", encoding="utf-8") as fh:
                fh.write(fuente)
            with open(os.path.join(prog, ".suriaX_config.yaml"), "w", encoding="utf-8") as fh:
                fh.write("version: 1\ntarget: native\n")
            v0 = _correr([sys.executable, _MAIN, "main.srcx", "--emit-hir"], prog,
                         entorno={"SURIAX_STDLIB": stdlib})
            assert v0.returncode == 0, v0.stdout[-1500:] + v0.stderr[-1500:]
            resultados[f"V0 en {caso}"] = _unidades(os.path.join(prog, "dumps"))
            v1 = _correr([vm, os.path.join(tmp, "dumps", "main.srcx.phir"), "--run", "--quiet",
                          "--", "main.srcx", os.path.join("v1", "main.srcx.phir"),
                          "--stdlib", stdlib], prog)
            assert v1.returncode == 0, v1.stderr[-1500:]
            resultados[f"V1 en {caso}"] = _unidades(os.path.join(prog, "v1"))
    primero = next(iter(resultados.values()))
    assert b"<stdlib>/io/" in primero["IO.phir"], primero["IO.phir"][:200]
    for nombre, unidades in resultados.items():
        assert sorted(unidades) == sorted(primero), (nombre, sorted(unidades))
        distintas = [n for n in unidades if unidades[n] != primero[n]]
        assert not distintas, f"{nombre}: otros bytes en {distintas}"
