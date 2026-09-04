#!/usr/bin/env python3
"""Servidor del playground: el compilador de verdad detrás de una página.

Existe porque el compilador ya sabe entregar cada fase (``driver/artifacts``)
y no había forma de VERLAS sin una terminal. La alternativa era reimplementar
el frontend en TypeScript para que corriera en el navegador; sería un segundo
compilador que mantener sincronizado con este, y el proyecto ya sabe lo que
cuesta tener dos respuestas para la misma pregunta.

Sin dependencias: ``http.server`` de la biblioteca estándar. La página es
estática y el único endpoint es ``POST /api/compile``, que recibe el fuente y
devuelve las fases. Nada de esto toca el disco del usuario.

    python playground/server.py            # http://localhost:8000
    PORT=3000 python playground/server.py

En Railway el puerto lo pone la plataforma en ``PORT``; el volcado del backend
web va a ``.web/``, que es su carpeta de artefactos generados.
"""

from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import shutil
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.abspath(os.path.dirname(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
_STATIC = os.path.join(_HERE, "static")
_WEB_MAIN = os.path.join(_REPO_ROOT, "web", "main.ts")
#: volcados del backend web: su carpeta de artefactos generados.
_WEB_DUMPS = os.path.join(_REPO_ROOT, ".web")

# el compilador se importa como LIBRERIA, igual que lo hará suriniX.
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "V0")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

def cargar_env(ruta: str) -> None:
    """Lee un ``.env`` y lo vuelca en el entorno, SIN pisar lo que ya está.

    Railway (y cualquier PaaS) inyecta la configuración como variables de
    entorno, así que el servidor solo sabe leer variables. Este archivo es
    para el otro caso: correrlo en cualquier sitio sin exportar nada a mano.

    Lo que ya viene del entorno GANA: si mañana esto corre en una plataforma
    que define ``PORT``, un ``.env`` olvidado en el repositorio no puede
    cambiar el puerto donde escucha.

    Formato mínimo a propósito —``CLAVE=valor``, ``#`` comenta, comillas
    opcionales— y sin dependencias: un cargador de ``.env`` completo es una
    librería, y aquí no hay nada que justifique una.
    """
    if not os.path.isfile(ruta):
        return
    with open(ruta, encoding="utf-8") as fh:
        for linea in fh:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, _, valor = linea.partition("=")
            clave = clave.strip()
            valor = valor.strip().strip("'\"")
            if clave and clave not in os.environ:
                os.environ[clave] = valor


cargar_env(os.path.join(_REPO_ROOT, ".env"))

#: un fuente más largo que esto no se compila: el servidor es público y
#: compilar es trabajo real. No es una medida de seguridad, es una cota.
MAX_SOURCE_BYTES = int(os.environ.get("SURIAX_MAX_SOURCE_BYTES", 64 * 1024))

#: cuánto puede tardar el backend web en producir sus artefactos.
WEB_TIMEOUT_SECONDS = int(os.environ.get("SURIAX_WEB_TIMEOUT", 120))

#: el contrato del lenguaje se construye UNA vez por proceso: no cambia en
#: caliente y recorrer toda la taxonomía de errores en cada petición sería
#: trabajo repetido para dar siempre lo mismo.
_LANGUAGE = None

#: node ejecuta el backend web (TypeScript) borrando los tipos; desde la v23
#: sin bandera. Sin node, el panel de WebAssembly lo dice en vez de callarse.
_MIN_NODE_MAJOR = 22
_STRIP_TYPES_BY_DEFAULT = 23


def _node_major() -> int | None:
    node = shutil.which("node")
    if node is None:
        return None
    try:
        out = subprocess.run([node, "--version"], capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return int(out.stdout.strip().lstrip("v").split(".", 1)[0])
    except ValueError:
        return None


def _wasm(phir: bytes, unidades: dict) -> dict:
    """El WebAssembly del programa, en sus DOS vistas.

    ``pretty`` es para leer el programa (el WIR con las expresiones en línea)
    y ``wat`` para depurar el formato (el post-orden real de la pila). Son
    preguntas distintas y un solo volcado no responde bien a las dos.

    Las produce el backend web, que es TypeScript: se invoca por proceso en
    vez de reimplementar el lowering aquí. Si node no está, se dice — un
    panel vacío haría pensar que el programa no genera nada.
    """
    major = _node_major()
    if major is None or major < _MIN_NODE_MAJOR:
        return {"reason":
                "el backend web (TypeScript) necesita node 22 o superior; "
                "sin él no se pueden mostrar las fases del target web"}

    os.makedirs(_WEB_DUMPS, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=_WEB_DUMPS, prefix="wasm-") as tmp:
        phir_path = os.path.join(tmp, "programa.phir")
        # las unidades importadas, junto al principal: es como el consumidor
        # las resuelve (ruta relativa) y como viajan al distribuir.
        for alias, datos in unidades.items():
            with open(os.path.join(tmp, f"{alias}.phir"), "wb") as fh:
                fh.write(datos)
        wat_path = os.path.join(tmp, "programa.wat")
        pretty_path = os.path.join(tmp, "programa.pretty")
        with open(phir_path, "wb") as fh:
            fh.write(phir)
        cmd = ["node"]
        if major < _STRIP_TYPES_BY_DEFAULT:
            cmd.append("--experimental-strip-types")
        # '--json' entrega el informe COMPLETO del target: qué capacidades
        # deniega, qué eliminó el DCE y qué diagnosticó. Son fases reales del
        # pipeline web que nadie veía; pedirlas en la misma invocación no
        # cuesta un proceso más.
        cmd += [_WEB_MAIN, phir_path, "--json", "--emit-wat", wat_path,
                "--emit-pretty", pretty_path]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=WEB_TIMEOUT_SECONDS, cwd=_REPO_ROOT)
        informe = {}
        try:
            informe = json.loads(proc.stdout)
        except ValueError:
            pass

        salida = {"report": informe,
                  "stderr": (proc.stderr or "").strip()}
        if os.path.isfile(wat_path):
            with open(wat_path, encoding="utf-8") as fh:
                salida["wat"] = fh.read()
        if os.path.isfile(pretty_path):
            with open(pretty_path, encoding="utf-8") as fh:
                salida["pretty"] = fh.read()
        return salida


def _fases_del_web(phir, unidades: dict) -> tuple:
    """La fase del target web, y sus diagnósticos como lo que son: ERRORES.

    El programa va DIRECTO hacia el backend web. Si el target no soporta algo,
    eso no es "una fase que no produjo nada": es que **el programa no compila
    para ese target**, igual que un `#extern cpp` no compila para el navegador.
    Enseñarlo como un hueco invitaba a pensar que el intérprete lo salvaría, y
    por ese camino no pasa el intérprete.

    Devuelve ``(fases, diagnósticos)``: los diagnósticos se suman a los del
    frontend porque el usuario tiene UNA pregunta —¿compila?— y la respuesta
    no puede depender de qué pestaña abrió.
    """
    if phir is None:
        return ({"wasm": {"ok": False,
                          "reason": "sin HIR no hay nada que bajar al target web"}},
                [])

    bruto = _wasm(phir, unidades)
    if "reason" in bruto and "report" not in bruto:
        return {"wasm": {"ok": False, "reason": bruto["reason"]}}, []

    informe = bruto.get("report") or {}
    if "wat" in bruto:
        return ({"wasm": {"ok": True, "wat": bruto["wat"],
                          "pretty": bruto.get("pretty", "")}}, [])

    # Los WEB0xx y los WEB1xx dicen cosas DISTINTAS, y el proyecto ya las
    # separa. Para quien compila la diferencia se lee así:
    #
    #   WEB0xx  NO SOPORTADO       el target decidió no ejecutar esto
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

    no_soportado = [d for d in diagnosticos if d["kind"] == "unsupported"]
    motivo = ("el target web no soporta construcciones del programa"
              if no_soportado else
              "el target web todavía no compila construcciones del programa")
    return ({"wasm": {"ok": False, "reason": motivo,
                      "diagnostics": diagnosticos}}, diagnosticos)


def compile_source(source: str, *, debug: bool = False) -> dict:
    """Todas las fases del fuente, incluidas las del backend web.

    ``debug`` añade lo que el compilador mide de sí mismo —cuánto tarda cada
    fase y cuánto produce—, que es lo que ``--debug`` vuelca en la CLI. No
    cambia lo que se compila: es la misma corrida, contada.
    """
    import time

    from driver.artifacts import collect

    inicio = time.perf_counter()
    payload = collect(source, path="playground.srcx")
    frontend = time.perf_counter() - inicio

    inicio = time.perf_counter()
    fases, diagnosticos = _fases_del_web(payload.pop("phir", None),
                                         payload.pop("units", {}))
    payload["phases"].update(fases)
    # los diagnósticos del target se suman a los del frontend: el usuario tiene
    # UNA pregunta —¿compila?— y la respuesta no depende de la pestaña abierta.
    payload["diagnostics"].extend(diagnosticos)
    web = time.perf_counter() - inicio

    if debug:
        tokens = payload["phases"].get("tokens", {}).get("tokens") or []
        enlace = payload["phases"].get("link", {})
        payload["debug"] = {
            "times": {"frontend": round(frontend * 1000, 2),
                      "target web": round(web * 1000, 2)},
            "metrics": {
                "bytes del fuente": len(source.encode()),
                "líneas": source.count("\n") + 1,
                "tokens": len(tokens),
                "diagnósticos": len(payload["diagnostics"]),
                "librerías ligadas": len(enlace.get("libraries") or []),
                "hooks": len(enlace.get("hooks") or []),
                "conversiones": len(enlace.get("casts") or []),
            },
        }
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = "suriaX-playground"

    def log_message(self, fmt, *args):  # noqa: D102 - una línea por petición
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")

    # -- respuestas ------------------------------------------------------ #
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    # -- rutas ----------------------------------------------------------- #
    def do_GET(self) -> None:  # noqa: N802 - lo impone BaseHTTPRequestHandler
        ruta = self.path.split("?", 1)[0]
        if ruta == "/api/language":
            self._language()
            return
        if ruta == "/":
            ruta = "/index.html"
        # Solo se sirve lo que hay en 'static/': se resuelve la ruta real y se
        # comprueba que siga dentro. Sin esto, '../' saldría del directorio.
        destino = os.path.realpath(os.path.join(_STATIC, ruta.lstrip("/")))
        if not destino.startswith(os.path.realpath(_STATIC) + os.sep) \
                or not os.path.isfile(destino):
            self._send(404, b"no encontrado", "text/plain; charset=utf-8")
            return
        tipo = mimetypes.guess_type(destino)[0] or "application/octet-stream"
        with open(destino, "rb") as fh:
            self._send(200, fh.read(), f"{tipo}; charset=utf-8"
                       if tipo.startswith("text/") or "javascript" in tipo
                       else tipo)

    def _language(self) -> None:
        """El contrato del lenguaje: categorías de token y catálogo de errores.

        La página NO clasifica tokens ni explica códigos por su cuenta: los
        pide. ``lang_info`` existe justo para eso ("para que la extensión
        coloree sin reimplementar la gramática") y un segundo consumidor con
        sus propias reglas volvería a inventar la respuesta — que es como el
        playground acabó decidiendo por regex si ``INT`` era un tipo.
        """
        global _LANGUAGE
        if _LANGUAGE is None:
            from include.lang_info import build_language_info
            _LANGUAGE = build_language_info()
        self._json(200, _LANGUAGE)

    def do_POST(self) -> None:  # noqa: N802
        ruta = self.path.split("?", 1)[0]
        if ruta not in ("/api/compile", "/api/lex"):
            self._json(404, {"error": "ruta desconocida"})
            return
        largo = int(self.headers.get("Content-Length") or 0)
        if largo > MAX_SOURCE_BYTES:
            self._json(413, {"error": f"el fuente no puede pasar de "
                                      f"{MAX_SOURCE_BYTES // 1024} KB"})
            return
        try:
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
            source = str(cuerpo.get("source", ""))
            debug = bool(cuerpo.get("debug", False))
        except (ValueError, UnicodeDecodeError) as exc:
            self._json(400, {"error": f"petición ilegible: {exc}"})
            return

        try:
            if ruta == "/api/lex":
                # solo el lexer: el editor lo pide en cada pausa al escribir y
                # correr el pipeline entero para colorear sería pagar cien
                # veces lo que cuesta la respuesta.
                from driver.artifacts import lex_only
                self._json(200, lex_only(source, path="playground.srcx"))
                return
            self._json(200, compile_source(source, debug=debug))
        except Exception as exc:  # noqa: BLE001 - un fallo del compilador NO
            # puede tirar el servidor: se reporta como lo que es, un fallo
            # interno, y con su tipo para poder buscarlo.
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})


def main() -> int:
    puerto = int(os.environ.get("PORT", "8000"))
    servidor = ThreadingHTTPServer(("0.0.0.0", puerto), Handler)
    print(f"suriaX playground en http://localhost:{puerto}", file=sys.stderr)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nadiós", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
