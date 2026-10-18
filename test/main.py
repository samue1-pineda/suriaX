#!/usr/bin/env python3
"""Runner de pruebas de suriaX (propio, sin framework externo).

Descubre y ejecuta los tests de las categorías del proyecto. Seis corren
siempre y dos, a pedido:

    unit · grammar · negative_tests · snapshot · e2e · fuzz
    backend · bootstrap          (a pedido: ver 'Uso')

``grammar`` cubre la gramática regla a regla en tres niveles (forma del AST,
código de error exacto, y ejecución de punta a punta) para que un fallo se
localice sin leer el resto del pipeline.

**Todas** las pruebas del repositorio viven bajo ``test/``, y este es el único
comando que las corre. Junto a las categorías hay dos carpetas que NO lo
son y por eso no se descubren solas:

    test/web/     la suite del backend web (TypeScript). La engancha
                  ``unit/test_web_backend.py``, que la ejecuta con
                  ``node --test``: sigue habiendo un solo comando.
    test/manual/  utilidades que se corren a mano, no en cada corrida.

Cada categoría es una carpeta junto a este archivo. Un test es un módulo con
funciones ``test_*`` (sin argumentos) que lanzan ``AssertionError`` al fallar.

Tres resultados posibles por prueba, y ninguno se disfraza de otro:

    ✓ pasada   se ejecutó y no lanzó nada
    ✗ fallida  lanzó (una aserción o cualquier otra excepción)
    ○ omitida  llamó a ``helpers.omitir(motivo)``: no se ejecutó, y se dice
               por qué. NO cuenta como pasada — antes una prueba se saltaba
               con ``return`` y el resumen la sumaba al verde.

Una omisión no hace fallar la corrida (el código de salida solo depende de
los fallos), pero se lista con su motivo en consola, en ``--json`` y en el
resumen de la CI.

Uso:
    python test/main.py                  # las categorías de siempre
    python test/main.py unit fuzz        # solo categorías indicadas
    python test/main.py backend          # a pedido: VM contra intérprete
    python test/main.py backend/test_vm  # solo los módulos que empiezan así
    python test/main.py bootstrap        # a pedido: la V1 contra la V0
    python test/main.py --todo           # todas, las de a pedido incluidas
    python test/main.py --json out.json  # + resumen legible por máquina

Las categorías ``backend`` y ``bootstrap`` COMPARAN dos implementaciones
(la VM de C++ con el intérprete; el frontend escrito en suriaX con el de la
V0). Son las más lentas y no hace falta correrlas en cada cambio: se corren
cuando se toca lo que prueban. En la CI cada una tiene su workflow con filtro
de rutas, y el release corre todo.

``--json`` existe para la CI: escribe el recuento, la LISTA DE FALLOS (con
archivo y línea) y la de OMITIDAS (con motivo), que es lo que el workflow
convierte en la medalla y en el informe del job.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import traceback
from typing import List, Optional

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TEST_DIR)
_V0 = os.path.join(_REPO_ROOT, "V0")

CATEGORIES = ["unit", "grammar", "negative_tests", "snapshot", "e2e", "fuzz"]

#: Categorias que NO corren por defecto: comparan dos implementaciones entre
#: si (la VM contra el interprete; el frontend en suriaX contra la V0) y son
#: las mas lentas. Se piden por nombre o con '--todo'; en la CI corren cuando
#: cambian sus archivos (un workflow por categoria, con filtro de rutas) y
#: siempre en el release.
A_PEDIDO = ["backend", "bootstrap"]

#: Tope de caracteres al mostrar una variable local en un fallo: lo justo para
#: ver el valor que rompió la aserción sin volcar un .phir entero.
_MAX_REPR = 400


# --------------------------------------------------------------------------- #
# modo UTF-8
# --------------------------------------------------------------------------- #

def _relanzar_en_utf8(argv: List[str]) -> Optional[int]:
    """Vuelve a lanzar el runner en el modo UTF-8 de Python si no lo está.

    Sin esto la suite dependía de la codificación de la máquina, y en Windows
    con la salida redirigida (cp1252) fallaba de dos formas:

    - el runner reventaba con ``UnicodeEncodeError`` al imprimir ``✓``;
    - las pruebas que leen la salida de un subproceso con ``text=True`` la
      decodificaban en cp1252 lo que el compilador había escrito en otra
      codificación, y comparaban texto roto (``parÃ¡metro``).

    El modo UTF-8 solo se puede activar al ARRANCAR el intérprete, por eso se
    relanza. ``PYTHONUTF8=1`` en el entorno hace que también lo usen los
    subprocesos que lancen las pruebas: todos escriben y leen UTF-8.
    Devuelve el código de salida del relanzamiento, o ``None`` si ya estaba
    en modo UTF-8 y hay que seguir aquí.
    """
    if sys.flags.utf8_mode:
        return None
    entorno = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run([sys.executable, "-X", "utf8",
                           os.path.abspath(__file__), *argv],
                          env=entorno).returncode


# --------------------------------------------------------------------------- #
# descubrir y ejecutar
# --------------------------------------------------------------------------- #

def _preparar_ruta() -> type:
    """Rutas de importación del compilador y de ``helpers``; devuelve
    la excepción ``Omitida`` compartida con las pruebas."""
    for p in (_REPO_ROOT, _V0, _TEST_DIR):
        if p not in sys.path:
            sys.path.insert(0, p)
    from helpers import Omitida
    return Omitida


def _discover(category: str) -> list[str]:
    """Rutas de los módulos ``test_*.py`` de una categoría."""
    folder = os.path.join(_TEST_DIR, category)
    if not os.path.isdir(folder):
        return []
    return [
        os.path.join(folder, f)
        for f in sorted(os.listdir(folder))
        if f.startswith("test_") and f.endswith(".py")
    ]


def _rel(path: str) -> str:
    """Ruta relativa a la raíz del repo, con '/' (estable entre sistemas)."""
    try:
        return os.path.relpath(path, _REPO_ROOT).replace(os.sep, "/")
    except ValueError:  # otra unidad en Windows: no hay ruta relativa
        return path


def _es_frame_de_infraestructura(tb) -> bool:
    """Frames que no dicen nada de la prueba: los de este runner y los de la
    maquinaria de importación de Python (``<frozen importlib...>``)."""
    archivo = tb.tb_frame.f_code.co_filename
    return (archivo.startswith("<frozen ")
            or os.path.abspath(archivo) == os.path.abspath(__file__))


def _sin_frames_del_runner(exc: BaseException):
    """El traceback empezando en la prueba, sin los frames de infraestructura.

    Quien lee un fallo quiere ver SU prueba y lo que ella llamó; la línea
    ``fn()`` del runner o ``exec_module`` de importlib no dicen nada y son las
    primeras que se leen.
    """
    tb = exc.__traceback__
    while tb is not None and _es_frame_de_infraestructura(tb):
        tb = tb.tb_next
    return tb


def _frame_de_la_prueba(tb, modulo_path: str):
    """El frame más profundo que pertenece al archivo de la prueba.

    Es "dónde falló" desde el punto de vista de quien escribió la prueba: la
    aserción que no se cumplió, o la llamada de la prueba que acabó lanzando.
    """
    elegido = None
    destino = os.path.abspath(modulo_path)
    while tb is not None:
        if os.path.abspath(tb.tb_frame.f_code.co_filename) == destino:
            elegido = tb
        tb = tb.tb_next
    return elegido


def _locales(frame) -> List[str]:
    """Las variables locales de ``frame`` que son DATOS, con su valor.

    Solo se muestran cuando una aserción falla sin mensaje: sin ellas
    ``assert "x" in err`` dice que falló pero no qué tenía ``err``, que es
    justamente el porqué.
    """
    import types

    lineas = []
    for nombre, valor in frame.f_locals.items():
        if nombre.startswith("__") or isinstance(
                valor, (types.ModuleType, types.FunctionType, type)):
            continue
        try:
            texto = repr(valor)
        except Exception as exc:  # noqa: BLE001 - un repr roto no tapa el fallo
            texto = f"<repr() falló: {type(exc).__name__}: {exc}>"
        if len(texto) > _MAX_REPR:
            texto = texto[:_MAX_REPR] + f"… (+{len(texto) - _MAX_REPR} caracteres)"
        lineas.append(f"    {nombre} = {texto}")
    return lineas


def _describir_fallo(exc: BaseException, category: str, modulo_path: str,
                     test: str) -> dict:
    """Todo lo que hace falta para entender un fallo sin reproducirlo.

    Qué falló (tipo y mensaje), dónde (archivo:línea de la prueba y el
    traceback completo, como lo imprime Python) y, si la aserción no trae
    mensaje, por qué (las variables locales de la prueba).
    """
    tb = _sin_frames_del_runner(exc)
    traza = "".join(traceback.format_exception(type(exc), exc, tb))
    propio = _frame_de_la_prueba(tb, modulo_path)
    if isinstance(exc, SyntaxError) and exc.filename:
        # un error de sintaxis no tiene frame propio: su sitio viaja en la
        # excepción, igual que lo imprime Python ("File x.py, line N").
        archivo, linea = _rel(exc.filename), exc.lineno or 0
    elif propio is not None:
        archivo, linea = _rel(modulo_path), propio.tb_lineno
    else:
        ultimo = traceback.extract_tb(tb)[-1] if tb is not None else None
        archivo = _rel(ultimo.filename) if ultimo else _rel(modulo_path)
        linea = ultimo.lineno if ultimo else 0

    mensaje = str(exc).strip()
    primera = mensaje.splitlines()[0] if mensaje else ""
    fuente = ""
    if propio is not None:
        import linecache
        fuente = linecache.getline(modulo_path, propio.tb_lineno).strip()
    if isinstance(exc, AssertionError) and fuente:
        # Una aserción se resume por lo que COMPROBABA: el mensaje suele ser
        # el valor que se inspeccionó (una salida entera, una lista), y su
        # primera línea sola no dice qué se esperaba.
        resumen = f"AssertionError en `{fuente}`"
        if primera:
            resumen += f" — {primera}"
    elif primera:
        resumen = f"{type(exc).__name__}: {primera}"
    else:
        resumen = type(exc).__name__

    locales: List[str] = []
    if isinstance(exc, AssertionError) and not mensaje and propio is not None:
        locales = _locales(propio.tb_frame)

    return {
        "category": category,
        "module": os.path.splitext(os.path.basename(modulo_path))[0],
        "test": test,
        "file": archivo,
        "line": linea,
        "error": resumen[:300],
        "traceback": traza,
        "locals": locales,
    }


def _run_module(path: str, category: str, omitida_cls: type,
                failures: list, skips: list) -> tuple[int, int, int]:
    """Importa un módulo de test y ejecuta sus funciones ``test_*``.

    Devuelve (pasadas, fallidas, omitidas). Un módulo que no se puede
    importar cuenta como UN fallo con su traceback: antes tumbaba el runner
    entero y ocultaba el resultado de todos los demás.
    """
    name = os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - se reporta como fallo, no se oculta
        print(f"    ✗ <importación de {name}>")
        failures.append(_describir_fallo(exc, category, path,
                                         "<importación del módulo>"))
        return 0, 1, 0

    passed = failed = skipped = 0
    for attr in dir(module):
        if not attr.startswith("test_"):
            continue
        fn = getattr(module, attr)
        if not callable(fn):
            continue
        resultado, detalle = "pasada", None
        try:
            fn()
        except omitida_cls as exc:
            resultado, detalle = "omitida", str(exc)
        # SystemExit también: una prueba que llama a algo que termina el
        # proceso (un 'main' de una herramienta) no puede matar la corrida
        # entera y dejarla sin resumen. KeyboardInterrupt sí la corta.
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - un fallo no detiene los demás
            resultado, detalle = "fallida", _describir_fallo(
                exc, category, path, attr)

        # la marca se imprime FUERA del try: un fallo al informar no puede
        # convertirse en el fallo de la prueba.
        if resultado == "pasada":
            passed += 1
            print(f"    ✓ {attr}")
        elif resultado == "omitida":
            skipped += 1
            print(f"    ○ {attr}  (omitida: {detalle})")
            skips.append({"category": category, "module": name,
                          "test": attr, "reason": detalle})
        else:
            failed += 1
            print(f"    ✗ {attr}  [{detalle['file']}:{detalle['line']}] "
                  f"{detalle['error']}")
            failures.append(detalle)
    return passed, failed, skipped


# --------------------------------------------------------------------------- #
# informe
# --------------------------------------------------------------------------- #

def _informe_de_fallos(failures: list) -> None:
    """Cada fallo como lo mostraría Python: traceback, excepción y, si la
    aserción vino sin mensaje, los valores con los que falló."""
    if not failures:
        return
    print("\n" + "=" * 72)
    print(f"FALLOS ({len(failures)})")
    print("=" * 72)
    for f in failures:
        print(f"\n--- {f['category']}/{f['module']}::{f['test']}  "
              f"({f['file']}:{f['line']})")
        print(f["traceback"].rstrip())
        if f["locals"]:
            print("  variables locales de la prueba al fallar:")
            print("\n".join(f["locals"]))


def _informe_de_omisiones(skips: list) -> None:
    """Las omitidas agrupadas por motivo: 35 líneas con el mismo 'falta el
    binario' esconden el único motivo distinto."""
    if not skips:
        return
    por_motivo: dict = {}
    for s in skips:
        por_motivo.setdefault(s["reason"], []).append(
            f"{s['category']}/{s['module']}::{s['test']}")
    print("\n" + "=" * 72)
    print(f"OMITIDAS ({len(skips)}) — no se ejecutaron; no cuentan como pasadas")
    print("=" * 72)
    for motivo, pruebas in sorted(por_motivo.items(), key=lambda kv: -len(kv[1])):
        print(f"\n  {len(pruebas)} × {motivo}")
        for p in pruebas:
            print(f"      {p}")


def run_tests(categories: list[str] | None = None,
              json_path: str | None = None) -> int:
    omitida_cls = _preparar_ruta()
    selected = categories or CATEGORIES
    total_pass = total_fail = total_skip = total_mods = 0
    failures: list = []
    skips: list = []

    for selector in selected:
        # 'categoria' o 'categoria/prefijo': el prefijo elige módulos por
        # nombre ('backend/test_vm_diferencial' corre todos los
        # test_vm_diferencial_*.py, que antes eran un solo archivo)
        category, _, prefix = selector.replace("\\", "/").partition("/")
        prefix = prefix[:-3] if prefix.endswith(".py") else prefix
        if category not in CATEGORIES + A_PEDIDO:
            print(f"categoría desconocida: '{category}' "
                  f"(las que hay: {', '.join(CATEGORIES + A_PEDIDO)})", file=sys.stderr)
            return 2
        modules = [m for m in _discover(category)
                   if os.path.basename(m).startswith(prefix)]
        if prefix and not modules:
            print(f"ningún módulo de '{category}' empieza por '{prefix}'", file=sys.stderr)
            return 2
        print(f"== {selector} ({len(modules)} módulos) ==")
        for path in modules:
            total_mods += 1
            p, f, s = _run_module(path, category, omitida_cls, failures, skips)
            total_pass += p
            total_fail += f
            total_skip += s

    if total_mods == 0:
        print("\nno se encontró ningún módulo test_*.py en las categorías "
              f"pedidas: {', '.join(selected)}")
        return 0

    _informe_de_fallos(failures)
    _informe_de_omisiones(skips)
    total = total_pass + total_fail + total_skip
    print(f"\nresultado: {total_pass} pasadas, {total_fail} fallidas, "
          f"{total_skip} omitidas ({total} pruebas en {total_mods} módulos).")

    if json_path:
        _write_summary(json_path, total_pass, total_fail, total_skip,
                       total_mods, selected, failures, skips)
    return 1 if total_fail else 0


def _write_summary(path: str, passed: int, failed: int, skipped: int,
                   modules: int, categories: list, failures: list,
                   skips: list) -> None:
    """Resumen de la corrida en JSON (para la CI).

    ``total`` incluye las omitidas: una medalla ``pasadas/total`` que las
    excluyera volvería a contar como probado lo que no se ejecutó.
    """
    carpeta = os.path.dirname(os.path.abspath(path))
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total": passed + failed + skipped,
            "modules": modules,
            "categories": categories,
            "failures": [{k: v for k, v in f.items() if k != "locals"}
                         for f in failures],
            "skips": skips,
        }, fh, ensure_ascii=False, indent=2)


def _parse_args(argv: list[str]) -> tuple[list[str] | None, str | None]:
    """``[categorías...] [--json RUTA]``. Sin argparse: son dos opciones."""
    categorias: list[str] = []
    json_path = None
    resto = list(argv)
    while resto:
        arg = resto.pop(0)
        if arg == "--json":
            if not resto:
                print("--json necesita una ruta", file=sys.stderr)
                raise SystemExit(2)
            json_path = resto.pop(0)
        elif arg.startswith("--json="):
            json_path = arg.split("=", 1)[1]
        elif arg == "--todo":
            categorias.extend(c for c in CATEGORIES + A_PEDIDO if c not in categorias)
        else:
            categorias.append(arg)
    return (categorias or None), json_path


if __name__ == "__main__":
    _codigo = _relanzar_en_utf8(sys.argv[1:])
    if _codigo is not None:
        raise SystemExit(_codigo)
    _cats, _json = _parse_args(sys.argv[1:])
    raise SystemExit(run_tests(_cats, _json))
