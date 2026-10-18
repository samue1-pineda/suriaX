"""e2e/hir_schema_v1 — el mismo programa, en los esquemas 1 y 2, se ejecuta IGUAL.

El esquema del HIR está versionado: ``--hir-schema 1`` emite el esquema
inicial (cada tipo inline, sin pool) y el intérprete lo normaliza al
cargarlo. La prueba que importa es la de EJECUCIÓN: para programas reales y
complejos del repositorio (los de ``fuego/``, unos de ``excepciones/`` y el
fixture del rollback del web), se emiten los dos esquemas por la CLI real y se
ejecutan con el intérprete; salida, errores y código de salida tienen que ser
EXACTAMENTE los mismos.

También por la CLI real: la vista legible (``--hir-pretty``) y el volcado de
texto del módulo YA NORMALIZADO (``runtime/interpreter/main.py --text``)
coinciden salvo la línea que dice el esquema.

Todo corre sobre COPIAS en un temporal (compilar deja ``log/`` junto al
fuente). Las pruebas unitarias del rollback están en
``test/unit/test_hir_schema_v1.py``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

_AQUI = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_AQUI))
_COMPILADOR = os.path.join(_REPO, "V0", "main.py")
_INTERPRETE = os.path.join(_REPO, "runtime", "interpreter", "main.py")

for _p in (_REPO, os.path.join(_REPO, "V0")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: (carpeta a copiar, fuente dentro de ella)
_PROGRAMAS = [
    (os.path.join(_AQUI, "fuego"), "inventario.srcx"),
    (os.path.join(_AQUI, "fuego"), "algoritmos.srcx"),
    (os.path.join(_AQUI, "fuego"), "estadistica.srcx"),
    (os.path.join(_AQUI, "fuego"), os.path.join("proyecto", "app.srcx")),
    (os.path.join(_AQUI, "excepciones"), "05_desenrollado.srcx"),
    (os.path.join(_AQUI, "excepciones"), "07_librerias.srcx"),
    (os.path.join(_AQUI, "excepciones"), "14_excepcion_no_capturada.srcx"),
    (os.path.join(_AQUI, "excepciones"), "17_finally.srcx"),
    (os.path.join(_REPO, "test", "web", "fixtures"), "rollback.srcx"),
]


def _proc(args, cwd):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300, cwd=cwd)


def _emitir(fuente: str, destino: str, esquema: int, *extra: str) -> str:
    """Emite el .phir (y sus unidades) del esquema pedido en ``destino``."""
    os.makedirs(destino, exist_ok=True)
    phir = os.path.join(destino, "prog.phir")
    proc = _proc([_COMPILADOR, fuente, "--emit-hir", phir,
                  "--hir-schema", str(esquema), *extra],
                 cwd=os.path.dirname(fuente))
    assert proc.returncode == 0 and os.path.isfile(phir), (
        f"{fuente} no compiló con --hir-schema {esquema}:\n"
        f"{proc.stdout}\n{proc.stderr}")
    return phir


def _leer_crudo(phir: str):
    from src.HIR.stubs import load_hir_pb2
    module = load_hir_pb2().Module()
    with open(phir, "rb") as fh:
        module.ParseFromString(fh.read())
    return module


def _con_los_dos(carpeta: str, relativo: str, comprobar) -> None:
    with tempfile.TemporaryDirectory(prefix="suriax-esquema1-") as tmp:
        copia = os.path.join(tmp, "src")
        shutil.copytree(carpeta, copia,
                        ignore=shutil.ignore_patterns("dumps", "log", "*.phir"))
        fuente = os.path.join(copia, relativo)
        v1 = _emitir(fuente, os.path.join(tmp, "v1"), 1)
        v2 = _emitir(fuente, os.path.join(tmp, "v2"), 2)
        comprobar(fuente, v1, v2)


def _ejecutar(phir: str, *modo: str):
    """Ejecuta con el intérprete desde la carpeta del .phir y con su nombre
    relativo: el programa recibe la misma ruta en los dos esquemas."""
    proc = _proc([_INTERPRETE, os.path.basename(phir), *modo],
                 cwd=os.path.dirname(phir))
    return proc.returncode, proc.stdout, proc.stderr


def test_el_mismo_programa_se_ejecuta_igual_en_los_dos_esquemas():
    for carpeta, relativo in _PROGRAMAS:
        def comprobar(_fuente, v1, v2, relativo=relativo):
            # que de verdad sean un v1 y un v2 (unidades de librería incluidas)
            for ruta in os.listdir(os.path.dirname(v1)):
                if ruta.endswith(".phir"):
                    crudo = _leer_crudo(os.path.join(os.path.dirname(v1), ruta))
                    assert crudo.schema_version == 1, (relativo, ruta)
                    assert len(crudo.types) == 0, (relativo, ruta)
            assert _leer_crudo(v2).schema_version == 2
            assert len(_leer_crudo(v2).types) > 1

            con_v1 = _ejecutar(v1, "--exec")
            con_v2 = _ejecutar(v2, "--exec")
            assert "Traceback" not in con_v1[2], (relativo, con_v1[2])
            assert con_v1 == con_v2, (
                f"{relativo}: el esquema 1 se ejecuta distinto que el 2\n"
                f"--- v1 (rc={con_v1[0]})\n{con_v1[1]}\n{con_v1[2]}\n"
                f"--- v2 (rc={con_v2[0]})\n{con_v2[1]}\n{con_v2[2]}")
            # algo se ejecutó: una salida vacía en los dos no probaría nada
            assert con_v2[1].strip() or con_v2[0] != 0, relativo

        _con_los_dos(carpeta, relativo, comprobar)


def test_los_bloques_test_corren_igual_en_los_dos_esquemas():
    def comprobar(_fuente, v1, v2):
        con_v1 = _ejecutar(v1, "--test")
        con_v2 = _ejecutar(v2, "--test")
        assert "PASS" in con_v2[1], con_v2
        assert con_v1 == con_v2, (con_v1, con_v2)

    _con_los_dos(os.path.join(_AQUI, "fuego"), "estadistica.srcx", comprobar)


def test_la_vista_legible_de_la_cli_coincide_salvo_el_esquema():
    def comprobar(fuente, v1, v2):
        vistas = {}
        for esquema, phir in ((1, v1), (2, v2)):
            pretty = os.path.join(os.path.dirname(phir), "prog.pretty")
            _emitir(fuente, os.path.dirname(phir), esquema, "--hir-pretty", pretty)
            with open(pretty, encoding="utf-8") as fh:
                vistas[esquema] = fh.read()
        cabecera_1, resto_1 = vistas[1].split("\n", 1)
        cabecera_2, resto_2 = vistas[2].split("\n", 1)
        assert "schema 1" in cabecera_1, cabecera_1
        assert cabecera_1.replace("schema 1", "schema 2") == cabecera_2
        assert resto_1 == resto_2

    _con_los_dos(os.path.join(_AQUI, "fuego"), "inventario.srcx", comprobar)


def test_el_texto_del_modulo_normalizado_es_el_del_v2():
    """``--text`` vuelca el Module TAL COMO LO CARGÓ el intérprete: el v1 ya
    normalizado tiene que ser, campo a campo, el v2 (pool incluido)."""
    def comprobar(_fuente, v1, v2):
        con_v1 = _ejecutar(v1, "--text")
        con_v2 = _ejecutar(v2, "--text")
        assert con_v1[0] == con_v2[0] == 0, (con_v1, con_v2)
        texto_v1 = con_v1[1].replace("HIR schema v1", "HIR schema v2").replace(
            "schema_version: 1", "schema_version: 2")
        assert "types {" in con_v1[1], "el v1 normalizado no tiene pool"
        assert texto_v1 == con_v2[1]

    _con_los_dos(os.path.join(_AQUI, "fuego"), "algoritmos.srcx", comprobar)
