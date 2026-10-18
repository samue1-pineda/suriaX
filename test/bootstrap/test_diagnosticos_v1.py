"""bootstrap/diagnosticos_v1 — la V1 da los MISMOS diagnósticos que la V0.

Lo mismo = la lista completa, en el mismo orden, con el mismo ARCHIVO, CÓDIGO,
LÍNEA y COLUMNA (el texto del mensaje es de cada una; decisión del mantenedor,
lote 18). El archivo importa con las librerías: el error de una librería va con
el suyo. La referencia es el canal real de la V0 (``inspect.emit_diagnostics``:
léxicos, de sintaxis y —solo sobre un parseo limpio— semánticos).

El corpus son los programas de las pruebas NEGATIVAS y de GRAMÁTICA: se
capturan al vuelo (cada fuente que esas pruebas le pasan a
``helpers.error_codes``), así que una prueba negativa nueva es también un
caso de este diferencial sin escribirlo dos veces. A eso se suman las sondas
de ``test/bootstrap/v1_diagnosticos/``: un ``.srcx`` suelto, o una CARPETA de
proyecto (su ``main.srcx`` y su ``lib/``) para lo que necesita librerías.

Los códigos llegan por tandas (18a, 18b, 18c). Un programa cuya lista en la
V0 usa un código que la V1 todavía no da es PENDIENTE: no se compara, y una
prueba aparte los cuenta y se omite diciéndolo (nunca en silencio).
"""

from __future__ import annotations

import contextlib
import glob
import importlib.util
import io
import os
import re
import shutil
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_AQUI))
sys.path.insert(0, _AQUI)
sys.path.insert(0, os.path.dirname(_AQUI))
sys.path.insert(0, os.path.join(_REPO, "V0"))

import helpers  # noqa: E402
from helpers import omitir  # noqa: E402
from test_bootstrap_v1 import _STDLIB, _correr, _v1  # noqa: E402

_SONDAS = os.path.join(_AQUI, "v1_diagnosticos")

#: los códigos que la V1 ya da. Los léxicos y los de sintaxis son de su
#: lexer y su parser; los semánticos se suman por tandas (un código entra
#: cuando la V1 lo da en TODOS los sitios donde lo da la V0).
_PREFIJOS_HECHOS = ("LEX", "PAR")
_HECHOS: frozenset = frozenset({
    # 18a, nombres: no declarado, repetido, tipo inexistente, 'void' como valor
    "SEM001", "SEM002", "AST005", "SEM025",
    # 18a, tipos: el chequeo de tipos y lo que depende de él
    "AST006", "AST012", "SEM003", "SEM008", "SEM013", "SEM015", "SEM016", "SEM028",
    "SEM031", "SEM035",
    # 18a, el aviso del 'match' que no cubre todas las variantes
    "SEM030",
    # 18b, la propiedad: lo movido y lo liberado (la última pasada de la V0),
    # copias de un dueño, préstamos, direcciones locales, tamaño y capacidad
    "SEM004", "SEM005", "SEM023", "SEM024", "SEM014", "SEM026", "SEM032", "SEM033",
    "SEM034", "SEM036", "SEM037",
    # 18c-1: hooks, métodos, traits, aridad de un genérico y la nota del
    # '__free__' que no suelta un campo
    "SEM006", "SEM007", "SEM018", "SEM021", "SEM022", "SEM027", "NOTE002",
    # 18c-2: el linker (no encontrada, no válida, no exporta, privada, un .srcx
    # como librería)
    "SEM009", "SEM010", "SEM011", "SEM019", "NOTE001",
    # 18c-3: un genérico que copia un dueño
    "SEM038",
})

_LINEA = re.compile(r"^(.*?):(\d+):(\d+): ([A-Z]{3,4}\d{3}) ")

_estado: dict = {}


def _hecho(codigo: str) -> bool:
    return codigo.startswith(_PREFIJOS_HECHOS) or codigo in _HECHOS


#: lo que la V0 ya tiene y la V1 todavía no (se construye primero en la V0;
#: la V1 se pone al día cuando la V0 se estabilice: decisión del mantenedor).
#: Un programa que lo usa es PENDIENTE: 'expect', 'errfinally', o un 'test'
#: (que en la V0 exige un 'expect' y la V1 acepta sin él).
_SINTAXIS_PENDIENTE = re.compile(r'\b(expect|errfinally)\b|\btest\s*"')
#: ...y su código nuevo (una prueba sin 'expect')
_CODIGOS_PENDIENTES = frozenset({"PAR029"})


def _pendiente_por_sintaxis(fuente: str, esperado: list) -> bool:
    if _SINTAXIS_PENDIENTE.search(fuente):
        return True
    return any(c in _CODIGOS_PENDIENTES for _a, c, _l, _c in esperado)


def _corpus() -> list:
    """``[(nombre, fuente)]``: lo que compilan las pruebas negativas y de
    gramática, más las sondas. Se captura una vez por corrida."""
    if "corpus" in _estado:
        return _estado["corpus"]
    capturados: list = []
    original = helpers.error_codes

    def captura(source, **kwargs):
        if not kwargs:    # con su propio 'file'/'source_path' dependen de su entorno
            capturados.append(source)
        return original(source, **kwargs)

    helpers.error_codes = captura
    try:
        for carpeta in ("negative_tests", "grammar"):
            for ruta in sorted(glob.glob(os.path.join(_REPO, "test", carpeta, "test_*.py"))):
                sys.path.insert(0, os.path.dirname(ruta))
                nombre = "_corpus_" + os.path.splitext(os.path.basename(ruta))[0]
                spec = importlib.util.spec_from_file_location(nombre, ruta)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                for k in sorted(dir(mod)):
                    f = getattr(mod, k)
                    if k.startswith("test_") and callable(f):
                        try:
                            with contextlib.redirect_stdout(io.StringIO()):
                                f()
                        except BaseException:   # noqa: BLE001 - aquí solo se captura
                            pass
    finally:
        helpers.error_codes = original
    corpus = [(f"prueba {i}", f) for i, f in enumerate(dict.fromkeys(capturados))]
    for ruta in sorted(glob.glob(os.path.join(_SONDAS, "*.srcx"))):
        with open(ruta, encoding="utf-8") as fh:
            corpus.append((os.path.basename(ruta), fh.read()))
    for carpeta in sorted(glob.glob(os.path.join(_SONDAS, "*", "main.srcx"))):
        corpus.append((os.path.basename(os.path.dirname(carpeta)), os.path.dirname(carpeta)))
    _estado["corpus"] = corpus
    return corpus


def _v0(ruta: str) -> list:
    from driver.inspect import emit_diagnostics
    with contextlib.redirect_stdout(io.StringIO()):
        datos = emit_diagnostics(ruta)
    return [(os.path.basename(d.get("file") or ""), d["code"], d["line"], d["column"])
            for d in datos["diagnostics"]]


def _v1_diags(vm: str, tmp: str, archivo: str, compilador: str = "") -> list:
    compilador = compilador or os.path.join(tmp, "dumps", "main.srcx.phir")
    hecho = _correr([vm, compilador, "--run", "--quiet", "--",
                     archivo, os.path.join("diag_salida", archivo + ".phir"),
                     "--stdlib", _STDLIB], tmp)
    diags = []
    for linea in hecho.stderr.splitlines():
        m = _LINEA.match(linea)
        if m:
            diags.append((os.path.basename(m.group(1)), m.group(4), int(m.group(2)),
                          int(m.group(3))))
    return diags


def _casos() -> tuple:
    """``(comparables, pendientes)``: cada caso con su lista de la V0."""
    if "casos" in _estado:
        return _estado["casos"]
    tmp, _vm = _v1()
    comparables, pendientes = [], []
    for i, (nombre, fuente) in enumerate(_corpus()):
        archivo = f"diag_{i}.srcx"
        if os.path.isdir(fuente):
            # una sonda con librerías: su carpeta entera, como un proyecto
            # (otra carga de este módulo —la prueba de la V2— comparte la
            # carpeta: se reemplaza, no se suma)
            shutil.rmtree(os.path.join(tmp, f"diag_{i}"), ignore_errors=True)
            shutil.copytree(fuente, os.path.join(tmp, f"diag_{i}"))
            # SU raíz de proyecto (sin esto lo sería la del proyecto de la V1,
            # y su 'lib/' no se vería: todo saldría como "no se encontró")
            with open(os.path.join(tmp, f"diag_{i}", ".suriaX_config.yaml"), "w",
                      encoding="utf-8") as fh:
                fh.write("version: 1\ntarget: native\n")
            archivo = os.path.join(f"diag_{i}", "main.srcx")
            with open(os.path.join(tmp, archivo), encoding="utf-8") as fh:
                fuente = fh.read()
        else:
            with open(os.path.join(tmp, archivo), "w", encoding="utf-8") as fh:
                fh.write(fuente)
        esperado = _v0(os.path.join(tmp, archivo))
        caso = (nombre, archivo, fuente, esperado)
        hechos = all(_hecho(c) for _a, c, _l, _c in esperado)
        if hechos and not _pendiente_por_sintaxis(fuente, esperado):
            comparables.append(caso)
        else:
            pendientes.append(caso)
    _estado["casos"] = (comparables, pendientes)
    return _estado["casos"]


def test_los_diagnosticos_de_la_v1_son_los_de_la_v0():
    comparar_diagnosticos()


def comparar_diagnosticos(compilador: str = "") -> None:
    """La lista de cada programa comparable del corpus con ``compilador`` (por
    defecto, la etapa A) contra la de la V0. La usa también la prueba de la V2."""
    tmp, vm = _v1()
    comparables, _pendientes = _casos()
    assert comparables, "el corpus no tiene casos comparables"
    distintos = []
    for nombre, archivo, fuente, esperado in comparables:
        obtenido = _v1_diags(vm, tmp, archivo, compilador)
        if obtenido != esperado:
            distintos.append(f"--- {nombre} ({archivo})\n{fuente}\n"
                             f"  V0: {esperado}\n  V1: {obtenido}")
    assert not distintos, (
        f"{len(distintos)} de {len(comparables)} programas con otros diagnósticos:\n\n"
        + "\n\n".join(distintos[:15]))


def test_los_programas_pendientes_se_cuentan():
    """Los que usan un código o una sintaxis que la V1 todavía no tiene."""
    _comparables, pendientes = _casos()
    if pendientes:
        codigos = sorted({c for *_x, esperado in pendientes for _a, c, _l, _c in esperado
                          if not _hecho(c)})
        por_sintaxis = sum(1 for _n, _a, fuente, esperado in pendientes
                           if _pendiente_por_sintaxis(fuente, esperado))
        omitir(f"{len(pendientes)} programas no se comparan: {por_sintaxis} usan "
               f"'test'/'expect'/'errfinally' (la V1 todavía no los tiene, se "
               f"construyeron primero en la V0)"
               + (f"; códigos que la V1 no da: {', '.join(codigos)}" if codigos else ""))
