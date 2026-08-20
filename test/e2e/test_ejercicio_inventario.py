"""e2e/ejercicio — ``b.srcx`` compila y da lo que dice.

No es una prueba unitaria más: es el EJERCICIO REAL del repositorio, un
programa que alguien escribiría de verdad (un inventario con su dominio, sus
fallos y su presentación). Existe porque las pruebas unitarias solo encuentran
lo que ya sospechabas: ``b.srcx`` encontró que no existía ``%``, ni ``+=``, ni
forma de medir un ``str``, ni de preguntar el rango de un tipo, ni variantes de
enum con datos, ni ``catch`` filtrado por tipo — ninguna de esas la habría
levantado un test escrito para verificar una función concreta.

Se ejecuta el archivo del REPOSITORIO, no una copia: si ``b.srcx`` deja de
compilar, esto falla. Es lo que lo mantiene vivo en vez de convertirlo en un
adorno de la raíz.
"""

from __future__ import annotations

import os
import subprocess
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

#: cada línea que el ejercicio tiene que imprimir, en orden. Se comprueban
#: todas y no solo un fragmento: media salida correcta no dice nada.
ESPERADO = [
    "[1001] llave inglesa x12 @ 4500",
    "[1002] tornillo M4 x500 @ 15",
    "categoria: herramienta",
    "valor en llaves: 54000",
    "el nombre mide 13 caracteres",
    "articulos registrados: 2",
    "entrada de 6 -> quedan 18",
    "ajuste -2 (rotura) -> quedan 16",
    "recuento -> quedan 16",
    "sin stock de 'llave inglesa': hay 16, piden 999",
    "3 caja(s) de 5 y 1 sueltas",
    "suma de codigos: 2003",
    "son articulos distintos",
    "umbral 100: ocupa 2 bytes, rango [-32768, 32767]",
]


def _ejecutar() -> tuple:
    proc = subprocess.run(
        [sys.executable, os.path.join(_REPO_ROOT, "V0", "main.py"),
         os.path.join(_REPO_ROOT, "b.srcx"), "--run"],
        capture_output=True, text=True, cwd=_REPO_ROOT, timeout=120,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_el_ejercicio_compila_y_corre():
    code, _out, err = _ejecutar()
    assert code == 0, f"b.srcx no compiló/corrió (exit={code}):\n{err}"
    assert "Traceback" not in err, f"error no controlado:\n{err}"


def test_el_ejercicio_imprime_lo_que_dice():
    _code, out, err = _ejecutar()
    lineas = [l for l in out.splitlines() if l.strip()]
    for esperada in ESPERADO:
        assert esperada in lineas, (
            f"falta la línea {esperada!r}.\nsalida:\n{out}\n{err}")


def test_el_ejercicio_usa_lo_que_encontro():
    """Guarda contra el ejercicio que se queda viejo: si alguien recorta
    ``b.srcx``, deja de ejercitar justo lo que reveló y vuelve a ser un
    programa de juguete."""
    with open(os.path.join(_REPO_ROOT, "b.srcx"), encoding="utf-8") as fh:
        fuente = fh.read()
    for rasgo, marca in [
        ("modulo", " % "),
        ("asignacion compuesta", "+="),
        ("incremento", "++;"),
        ("len sobre str", "len(a.nombre)"),
        ("rango de un tipo", "min(dt.int16)"),
        ("variantes con payload", "Movimiento.Ajuste("),
        ("catch tipado", "catch (SinStock s)"),
        ("sizeof de un valor", "sizeof(umbral)"),
    ]:
        assert marca in fuente, f"el ejercicio dejó de ejercitar {rasgo}"
