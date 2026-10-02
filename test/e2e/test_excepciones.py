"""e2e/excepciones — la serie de programas de ``test/e2e/excepciones/``.

Al estilo de la suite de CPython: cada caracteristica de ``throw``/``try``/
``catch`` es un PROGRAMA completo que se puede leer, correr a mano y
modificar, junto a su salida esperada (``NN_nombre.salida``, verificada a
mano al escribirla). Esta prueba solo los descubre y los compara; lo que se
prueba —y por que— esta explicado en la cabecera de cada ``.srcx``.

    01_basico              throw/catch, propagacion por funciones y recursion
    02_filtro_por_tipo     una rama por tipo, primera que encaja, sin tipo
    03_anidado_y_relanzar  try anidados, relanzar el mismo valor u otro
    04_control_de_flujo    break/continue/return dentro de try y catch
    05_desenrollado        destructores al subir, propiedad del valor lanzado
    06_origenes            throw desde metodo, hook, generico, match, expresion
    07_librerias           tipos homonimos de dos librerias (lib/errs)
    08_no_capturado        RT020, codigo 70, y lo que se destruye antes
    09_el_catch_parte_de_la_entrada     el catch no supone que el try acabo
    10_move_en_el_try_y_uso_en_el_catch si el move ocurrio: RT001 en ejecucion
    11_throw_cede_el_valor             'throw r;' cede r sin escribir 'move'
    12_un_destructor_no_lanza          un __free__ que lanza: RT021
    13_excepciones_del_runtime         dividir entre cero, indice: se atrapan
    14_excepcion_no_capturada          EXC001 que nadie atrapa
    15_repertorio_estandar             ValorInvalido, NoEncontrado... (como Python)
    16_relanzar_conserva_el_tipo       'catch (e) { throw e; }' no pierde el tipo

Un programa que debe TERMINAR con error lo dice en su cabecera con una linea
``codigo: <salida> <diagnostico>`` (p. ej. ``codigo: 70 RT020``); sin ella se
espera salida 0. Se agrega una prueba nueva soltando un ``.srcx`` con su
``.salida`` en la carpeta: se genera sola una funcion ``test_<nombre>``.

Se corren sobre una COPIA en un temporal: compilar deja 'dumps/' y 'log/'
junto al fuente, y eso no puede ensuciar el arbol del repositorio.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

_AQUI = os.path.dirname(os.path.abspath(__file__))
_SERIE = os.path.join(_AQUI, "excepciones")
_MAIN = os.path.join(os.path.dirname(os.path.dirname(_AQUI)), "main.py")
_CODIGO = re.compile(r"^\s*codigo:\s*(\d+)(?:\s+(\S+))?", re.MULTILINE)


def _salida_del_programa(stdout: str) -> str:
    """Lo que imprimio el PROGRAMA, sin las lineas informativas del compilador."""
    lineas = [l for l in stdout.splitlines()
              if not l.startswith(("frontend OK", "HIR "))
              and not (l.lstrip().startswith("unidad '") and " -> " in l)]
    return "\n".join(lineas) + "\n"


def _correr(nombre: str) -> None:
    fuente = os.path.join(_SERIE, nombre + ".srcx")
    with open(fuente, encoding="utf-8") as fh:
        directiva = _CODIGO.search(fh.read())
    codigo = int(directiva.group(1)) if directiva else 0
    diagnostico = directiva.group(2) if directiva else None

    with tempfile.TemporaryDirectory(prefix="suriax-excepciones-") as tmp:
        copia = os.path.join(tmp, "excepciones")
        shutil.copytree(_SERIE, copia)
        # modo UTF-8 en el hijo: sin el, en Windows el programa escribe en
        # cp1252 y una salida con tildes no se compararia bien.
        entorno = {**os.environ, "PYTHONUTF8": "1"}
        proc = subprocess.run(
            [sys.executable, _MAIN, nombre + ".srcx"], cwd=copia,
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=300, env=entorno)

    assert "Traceback" not in proc.stderr and "ICE000" not in proc.stderr, \
        proc.stderr
    assert proc.returncode == codigo, (
        f"{nombre}: salio con {proc.returncode}, se esperaba {codigo}\n"
        f"{proc.stderr}")
    if diagnostico is not None:
        assert diagnostico in proc.stderr, (
            f"{nombre}: falta {diagnostico} en stderr\n{proc.stderr}")
    with open(os.path.join(_SERIE, nombre + ".salida"), encoding="utf-8") as fh:
        esperado = fh.read()
    obtenido = _salida_del_programa(proc.stdout)
    assert obtenido == esperado, (
        f"{nombre}: la salida cambio.\n--- esperado\n{esperado}\n"
        f"--- obtenido\n{obtenido}")


def _registrar() -> None:
    """Una funcion ``test_<nombre>`` por programa de la serie."""
    for archivo in sorted(os.listdir(_SERIE)):
        if not archivo.endswith(".srcx"):
            continue
        nombre = archivo[:-len(".srcx")]
        prueba = (lambda n=nombre: _correr(n))
        prueba.__name__ = "test_" + nombre
        globals()[prueba.__name__] = prueba


def test_cada_programa_tiene_su_salida_esperada():
    """Un ``.srcx`` sin ``.salida`` no se compararia contra nada."""
    for archivo in os.listdir(_SERIE):
        if archivo.endswith(".srcx"):
            salida = os.path.join(_SERIE, archivo[:-len(".srcx")] + ".salida")
            assert os.path.isfile(salida), f"falta {salida}"


_registrar()
