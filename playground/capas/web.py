"""Adaptador del target web: el backend TypeScript, en OTRO proceso.

Recibe un ``.phir`` (bytes) y devuelve la fase ``wasm``. No conoce al
compilador de Python ni al servidor: lo que cruza es un archivo y lo que
vuelve es un informe en JSON, que es el mismo contrato que tiene cualquiera
que invoque ``node web/main.ts`` a mano.

Que sea otro proceso es lo que lo desacopla, y también lo que puede salir mal
de más formas: que node no esté, que tarde demasiado, que muera, que escriba
algo que no es JSON. Cada una se convierte aquí en un estado; ninguna sale
como excepción.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time

from . import config
from .estados import (ERROR_DEL_PROGRAMA, ERROR_INTERNO, NO_DISPONIBLE, OK,
                      proveedor, sin_rutas)

#: node ejecuta el backend web (TypeScript) borrando los tipos; desde la v23
#: sin bandera. Sin node, el panel de WebAssembly lo dice en vez de callarse.
MIN_NODE = 22
_SIN_BANDERA_DESDE = 23

#: el perfil de contención que se le pide al target (``web/src/target/
#: policy.ts``): el del target web más una lista blanca de librerías. Qué se
#: puede usar en el playground se decide ALLÍ, una sola vez y como datos; aquí
#: solo se dice cuál.
PERFIL = "playground"

_SIN_NODE = (f"el backend web (TypeScript) necesita node {MIN_NODE} o "
             "superior; sin él no se pueden mostrar las fases del target web")

#: cuánto vale la versión de node ya consultada. Consultarla es lanzar un
#: proceso, y ``/api/health`` es público: sin esto cada visita lanzaba uno.
_VIGENCIA_VERSION = 60.0
_version = {"valor": None, "hasta": 0.0}
_candado_version = threading.Lock()

_cupo = threading.BoundedSemaphore(config.WEB_SIMULTANEOS)

#: lo más que se publica de la salida de error de node.
_MAX_DETALLE = 1200


def _version_de_node() -> int | None:
    """La versión mayor de node, o ``None`` si no está o no contesta."""
    node = shutil.which("node")
    if node is None:
        return None
    try:
        out = subprocess.run([node, "--version"], capture_output=True,
                             text=True, timeout=30)
        return int(out.stdout.strip().lstrip("v").split(".", 1)[0])
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def version_de_node() -> int | None:
    with _candado_version:
        if time.monotonic() >= _version["hasta"]:
            _version["valor"] = _version_de_node()
            _version["hasta"] = time.monotonic() + _VIGENCIA_VERSION
        return _version["valor"]


def _lanzar(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=config.WEB_TIEMPO, cwd=config.REPO)


def _publicable(texto: str, carpeta: str) -> str:
    """La salida de error de node, sin las rutas de esta máquina."""
    texto = sin_rutas(texto, tmp=carpeta).strip()
    return texto[-_MAX_DETALLE:] if len(texto) > _MAX_DETALLE else texto


def _fallo(estado: str, motivo: str, detalle: str = "") -> tuple:
    fase = {"ok": False, "status": estado, "reason": motivo}
    if detalle:
        fase["detail"] = detalle
    return {"wasm": fase}, [], proveedor(estado, detalle or motivo)


def _interno(que: str, detalle: str = "") -> tuple:
    return _fallo(ERROR_INTERNO,
                  f"el backend web falló por dentro: {que}", detalle)


def bajar(phir: bytes | None, unidades: dict) -> tuple:
    """La fase del target web. Devuelve ``(fases, diagnósticos, proveedor)``.

    Los diagnósticos se suman a los del frontend porque el usuario tiene UNA
    pregunta —¿compila?— y la respuesta no puede depender de qué pestaña
    abrió: si el target no soporta algo, **el programa no compila para ese
    target**, igual que un ``#extern cpp`` no compila para el navegador.
    """
    if phir is None:
        return _fallo(NO_DISPONIBLE,
                      "sin HIR no hay nada que bajar al target web")
    try:
        return _bajar(phir, unidades)
    except Exception as exc:  # noqa: BLE001 - nada de aquí tira al servidor
        return _interno(f"{type(exc).__name__}: {exc}")


def _bajar(phir: bytes, unidades: dict) -> tuple:
    mayor = version_de_node()
    if mayor is None or mayor < MIN_NODE:
        return _fallo(NO_DISPONIBLE, _SIN_NODE)

    if not _cupo.acquire(timeout=config.WEB_TIEMPO):
        return _fallo(NO_DISPONIBLE,
                      "el backend web está ocupado; vuelve a intentarlo")
    try:
        os.makedirs(config.WEB_VOLCADOS, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=config.WEB_VOLCADOS,
                                         prefix="wasm-") as tmp:
            return _en_carpeta(tmp, mayor, phir, unidades)
    finally:
        _cupo.release()


def _en_carpeta(tmp: str, mayor: int, phir: bytes, unidades: dict) -> tuple:
    phir_path = os.path.join(tmp, "programa.phir")
    # las unidades importadas, junto al principal: es como el consumidor las
    # resuelve (ruta relativa) y como viajan al distribuir.
    for alias, datos in unidades.items():
        with open(os.path.join(tmp, f"{alias}.phir"), "wb") as fh:
            fh.write(datos)
    wat_path = os.path.join(tmp, "programa.wat")
    pretty_path = os.path.join(tmp, "programa.pretty")
    with open(phir_path, "wb") as fh:
        fh.write(phir)

    cmd = ["node"]
    if mayor < _SIN_BANDERA_DESDE:
        cmd.append("--experimental-strip-types")
    # '--json' entrega el informe COMPLETO del target: qué capacidades
    # deniega, qué eliminó el DCE y qué diagnosticó. Son fases reales del
    # pipeline web que nadie veía; pedirlas en la misma invocación no cuesta
    # un proceso más.
    cmd += [config.WEB_MAIN, phir_path, "--json", "--policy", PERFIL,
            "--emit-wat", wat_path, "--emit-pretty", pretty_path]
    try:
        proc = _lanzar(cmd)
    except subprocess.TimeoutExpired:
        return _interno(f"no respondió en {config.WEB_TIEMPO} s")
    except OSError as exc:
        return _interno(f"no se pudo lanzar node ({exc})")

    stderr = _publicable(proc.stderr or "", tmp)
    try:
        informe = json.loads(proc.stdout)
    except ValueError:
        informe = None
    if not isinstance(informe, dict):
        # sin informe no hay nada que atribuirle al programa: node murió o
        # escribió otra cosa. Su salida de error es lo único que lo explica.
        return _interno(f"terminó con código {proc.returncode} y sin informe",
                        stderr)

    if os.path.isfile(wat_path):
        with open(wat_path, encoding="utf-8") as fh:
            wat = fh.read()
        pretty = ""
        if os.path.isfile(pretty_path):
            with open(pretty_path, encoding="utf-8") as fh:
                pretty = fh.read()
        return ({"wasm": {"ok": True, "status": OK, "wat": wat,
                          "pretty": pretty}}, [], proveedor(OK))

    # Los WEB0xx y los WEB1xx dicen cosas DISTINTAS, y el proyecto ya las
    # separa. Para quien compila la diferencia se lee así:
    #
    #   WEB0xx  NO SOPORTADO         el target decidió no ejecutar esto
    #   WEB1xx  NO SE PUDO COMPILAR  el codegen todavía no llega
    #
    # La primera es definitiva; la segunda es trabajo pendiente. Mezclarlas
    # haría parecer que un 'struct' está prohibido, y no lo está.
    diagnosticos = []
    for diag in informe.get("diagnostics") or []:
        codigo = str(diag.get("code", ""))
        diagnosticos.append({**diag, "phase": "web",
                             "kind": "unsupported" if codigo.startswith("WEB0")
                                     else "not-compiled"})
    if not diagnosticos:
        # ni artefacto ni diagnóstico: el target no dijo por qué. Culpar al
        # programa aquí sería inventar un motivo.
        return _interno("no generó WebAssembly ni dijo por qué", stderr)

    no_soportado = [d for d in diagnosticos if d["kind"] == "unsupported"]
    motivo = ("el target web no soporta construcciones del programa"
              if no_soportado else
              "el target web todavía no compila construcciones del programa")
    return ({"wasm": {"ok": False, "status": ERROR_DEL_PROGRAMA,
                      "reason": motivo, "diagnostics": diagnosticos}},
            diagnosticos, proveedor(ERROR_DEL_PROGRAMA, motivo))


def salud() -> dict:
    """¿Puede bajar al target web este entorno? No compila nada."""
    mayor = version_de_node()
    if mayor is None or mayor < MIN_NODE:
        return {**proveedor(NO_DISPONIBLE, _SIN_NODE), "node": mayor}
    if not os.path.isfile(config.WEB_MAIN):
        return {**proveedor(ERROR_INTERNO, "falta web/main.ts"), "node": mayor}
    return {**proveedor(OK), "node": mayor}
