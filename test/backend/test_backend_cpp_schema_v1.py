"""backend/backend_cpp: la VM lee el ESQUEMA 1 del HIR igual que el 2.

El esquema está versionado: ``--hir-schema 1`` emite el esquema inicial (cada
tipo inline, sin pool) y el lector C++ lo NORMALIZA al cargarlo
(``backend/src/schema_v1.cpp``), así que la VM, el MIR y las vistas tienen un
solo camino. Lo que se prueba:

- el mismo programa, emitido en los dos esquemas, se EJECUTA igual en la VM
  (salida, errores y código de salida);
- las vistas del lector C++ (``--summary``, ``--pretty``) sobre un ``.phir``
  v1 son byte a byte las de Python sobre el MISMO archivo: los dos
  normalizadores construyen el mismo pool, en el mismo orden;
- un v1 que mezcla los esquemas y una versión desconocida se rechazan.

Parte de ``test_backend_cpp.py`` (partido por tema); lo compartido está en
``backend_cpp_support.py``. Se OMITE si la VM no está construida.
"""

import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import omitir  # noqa: E402
from backend_cpp_support import (  # noqa: E402
    _COMPILER,
    _REPO_ROOT,
    _binario,
    _cargar,
    _cpp,
    _en_el_path,
)

_FUEGO = os.path.join(_REPO_ROOT, "test", "e2e", "fuego")


def _emitir(fuente: str, destino: str, esquema: int) -> str:
    os.makedirs(destino, exist_ok=True)
    phir = os.path.join(destino, "prog.phir")
    proc = subprocess.run(
        [sys.executable, _COMPILER, fuente, "--emit-hir", phir,
         "--hir-schema", str(esquema)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180, cwd=os.path.dirname(fuente))
    assert proc.returncode == 0 and os.path.isfile(phir), (
        f"no compiló con --hir-schema {esquema}:\n{proc.stdout}\n{proc.stderr}")
    return phir


def _con_los_dos(preparar, comprobar) -> None:
    """``preparar(tmp)`` deja un fuente en ``tmp`` y lo devuelve; se emite en
    los dos esquemas y ``comprobar(binario, v1, v2, tmp)`` decide."""
    binario = _binario()
    if binario is None:
        omitir("build/bin/suriax-hir no está construido "
               "(cmake -S . -B build && cmake --build build --target suriax-hir)")
    # dentro del repo (el linker resuelve './lib' desde ahí), con prefijo
    # reconocible si una corrida se interrumpe
    with tempfile.TemporaryDirectory(dir=_REPO_ROOT, prefix="suriax-v1-") as tmp:
        fuente = preparar(tmp)
        v1 = _emitir(fuente, os.path.join(tmp, "v1"), 1)
        v2 = _emitir(fuente, os.path.join(tmp, "v2"), 2)
        comprobar(binario, v1, v2, tmp)


def _fuego(nombre: str):
    def preparar(tmp: str) -> str:
        copia = os.path.join(tmp, "fuego")
        shutil.copytree(_FUEGO, copia,
                        ignore=shutil.ignore_patterns("dumps", "log", "*.phir"))
        return os.path.join(copia, nombre)
    return preparar


def _correr(binario: str, phir: str):
    """La VM desde la carpeta del .phir, con su nombre relativo."""
    proc = subprocess.run([binario, os.path.basename(phir), "--run"],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=180,
                          cwd=os.path.dirname(phir))
    return proc.returncode, proc.stdout, proc.stderr


def _misma_ejecucion(binario, v1, v2, _tmp) -> None:
    _en_el_path()
    con_v1 = _correr(binario, v1)
    con_v2 = _correr(binario, v2)
    assert "[vm] main() -> " in con_v2[1], (
        f"la VM no ejecutó el programa (rc={con_v2[0]}):\n{con_v2[1]}\n{con_v2[2]}")
    assert con_v1 == con_v2, (
        "la VM ejecuta distinto el esquema 1 que el 2:\n"
        f"--- v1 (rc={con_v1[0]})\n{con_v1[1]}\n{con_v1[2]}\n"
        f"--- v2 (rc={con_v2[0]})\n{con_v2[1]}\n{con_v2[2]}")


def test_la_vm_ejecuta_igual_los_programas_de_fuego_en_los_dos_esquemas():
    """Programas reales: genéricos de librería, enum con payload, structs con
    hooks, excepciones, un paquete de varias unidades. La normalización de
    cada campo de tipo, de verdad."""
    for nombre in ("inventario.srcx", "algoritmos.srcx", "estadistica.srcx",
                   os.path.join("proyecto", "app.srcx")):
        _con_los_dos(_fuego(nombre), _misma_ejecucion)


def test_las_vistas_del_v1_son_las_de_python_sobre_el_mismo_archivo():
    """Los dos normalizadores (Python y C++) construyen el MISMO pool, en el
    mismo orden: si no, la notación de un tipo o la cuenta de tipos de la
    cabecera difieren."""
    def comprobar(binario, v1, _v2, _tmp):
        _en_el_path()
        from src.HIR.pretty import pretty
        from runtime.interpreter.loader import summarize
        module = _cargar(v1)          # el lector de Python, normalizado
        assert module.schema_version == 1
        resumen = _cpp(binario, v1, "--summary")
        assert resumen.returncode == 0, resumen.stderr
        assert resumen.stdout == summarize(module) + "\n"
        vista = _cpp(binario, v1, "--pretty")
        assert vista.returncode == 0, vista.stderr
        assert vista.stdout == pretty(module)
        assert "schema 1" in vista.stdout.splitlines()[0]

    _con_los_dos(_fuego("inventario.srcx"), comprobar)


def test_la_vm_rechaza_un_v1_mezclado_y_las_versiones_desconocidas():
    def comprobar(binario, v1, v2, tmp):
        _en_el_path()
        from src.HIR.emmit_IR import serialize
        from src.HIR.stubs import load_hir_pb2
        # un v1 de verdad (sin índices) al que se le añade un pool: el rechazo
        # no puede depender de que algún nodo traiga un índice
        crudo = load_hir_pb2().Module()
        with open(v1, "rb") as fh:
            crudo.ParseFromString(fh.read())
        crudo.types.add()
        solo_pool = os.path.join(tmp, "solo_pool.phir")
        with open(solo_pool, "wb") as fh:
            fh.write(serialize(crudo))
        resultado = _cpp(binario, solo_pool, "--summary")
        assert resultado.returncode != 0, "la VM aceptó un v1 con pool"
        assert "Module.types" in resultado.stderr, resultado.stderr

        casos = {
            # un v2 (con pool) que dice ser un v1
            "mezcla.phir": (1, "mezcla los dos esquemas"),
            "cero.phir": (0, "schema_version 0 no soportada"),
            "tres.phir": (3, "schema_version 3 no soportada"),
        }
        for nombre, (version, esperado) in casos.items():
            module = _cargar(v2)
            module.schema_version = version
            ruta = os.path.join(tmp, nombre)
            with open(ruta, "wb") as fh:
                fh.write(serialize(module))
            resultado = _cpp(binario, ruta, "--summary")
            assert resultado.returncode != 0, f"la VM aceptó {nombre}"
            assert esperado in resultado.stderr, (nombre, resultado.stderr)
            if version != 1:
                assert "soportadas: 1, 2" in resultado.stderr, resultado.stderr

    _con_los_dos(_fuego("inventario.srcx"), comprobar)
