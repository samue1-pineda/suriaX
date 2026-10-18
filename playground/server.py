#!/usr/bin/env python3
"""Servidor del playground: el compilador de verdad detrás de una página.

Existe porque el compilador ya sabe entregar cada fase (``driver/artifacts``)
y no había forma de VERLAS sin una terminal. La alternativa era reimplementar
el frontend en TypeScript para que corriera en el navegador; sería un segundo
compilador que mantener sincronizado con este, y el proyecto ya sabe lo que
cuesta tener dos respuestas para la misma pregunta.

Sin dependencias: ``http.server`` de la biblioteca estándar. Este archivo es
solo la capa de TRANSPORTE —rutas, cabeceras, límites y errores HTTP—; lo que
se compila y con quién está en ``capas/`` (ver su docstring).

    python playground/server.py            # http://127.0.0.1:8000
    PORT=3000 python playground/server.py
    HOST=0.0.0.0 python playground/server.py   # publicado en la red

En una plataforma el puerto lo pone ella en ``PORT``; el volcado del backend
web va a ``.web/``, que es su carpeta de artefactos generados.
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.abspath(os.path.dirname(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from capas import aplicacion, config  # noqa: E402
from capas.aplicacion import compile_source  # noqa: E402,F401 - API pública
from capas.config import cargar_env  # noqa: E402,F401 - API pública

MAX_SOURCE_BYTES = config.MAX_FUENTE

_STATIC = config.ESTATICOS

#: el contrato del lenguaje se construye UNA vez por proceso: no cambia en
#: caliente y recorrer toda la taxonomía de errores en cada petición sería
#: trabajo repetido para dar siempre lo mismo.
_LANGUAGE = None

#: las rutas de la API y el método que acepta cada una. Lo que no está aquí
#: y no es un archivo de 'static/' no existe.
_RUTAS = {
    "/api/compile": "POST",
    "/api/lex": "POST",
    "/api/language": "GET",
    "/api/health": "GET",
    "/api/openapi.json": "GET",
}

#: la descripción de la API (OpenAPI 3.1). Se sirve tal cual está en disco.
_OPENAPI = os.path.join(_HERE, "openapi.json")

#: lo más que se lee de un cuerpo rechazado por grande antes de responder.
_MAX_DESCARTE = 8 * config.MAX_FUENTE

#: De dónde puede cargar cosas la página. Todo de este servidor, con dos
#: excepciones que se nombran:
#:   - los scripts de ``cdn.jsdelivr.net``: de ahí sale Mermaid (el diagrama
#:     de la pestaña Símbolos), con la versión fija en ``static/app.js``;
#:   - los estilos en línea: Mermaid los escribe dentro del SVG que genera.
#: Lo demás —otros orígenes, ``eval``, formularios hacia fuera, cambiar la
#: base de las rutas— queda cerrado.
_CSP_DE_LA_PAGINA = "; ".join((
    "default-src 'none'",
    "script-src 'self' https://cdn.jsdelivr.net",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "base-uri 'none'",
    "form-action 'none'",
))

_JSON = "application/json; charset=utf-8"
#: RFC 9457: el formato de un error HTTP que una herramienta puede leer.
_PROBLEMA = "application/problem+json; charset=utf-8"


class Handler(BaseHTTPRequestHandler):
    server_version = "suriaX-playground"
    #: no se anuncia la versión de Python: no le sirve a nadie que no esté
    #: buscando qué fallo conocido probar.
    sys_version = ""

    def setup(self) -> None:
        # segundos sin recibir nada antes de soltar la conexión: sin cota,
        # un cliente que no envía ocupa un hilo para siempre.
        self.timeout = config.ESPERA_CLIENTE
        super().setup()

    def log_message(self, fmt, *args):  # noqa: D102 - una línea por petición
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")

    # -- respuestas ------------------------------------------------------ #
    def _send(self, status: int, body: bytes, content_type: str,
              extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # el navegador NO adivina el tipo de lo que se le sirve, y la página
        # no le cuenta a otros sitios desde dónde se llegó.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for clave, valor in (extra or {}).items():
            self.send_header(clave, valor)
        self.end_headers()
        self.wfile.write(body)

    def _cabeceras_de_api(self) -> dict:
        # una respuesta de la API son datos: no se guarda y, si alguien la
        # abre como página, no puede cargar ni ejecutar nada.
        cabeceras = {"Cache-Control": "no-store",
                     "Content-Security-Policy": "default-src 'none'"}
        if config.ORIGEN_PERMITIDO:
            cabeceras["Access-Control-Allow-Origin"] = config.ORIGEN_PERMITIDO
            cabeceras["Vary"] = "Origin"
        return cabeceras

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode(),
                   _JSON, self._cabeceras_de_api())

    def _problema(self, status: int, titulo: str, detalle: str,
                  extra: dict | None = None) -> None:
        """Un error HTTP: la petición no se pudo atender.

        No es lo mismo que un programa que no compila —eso es una respuesta
        200 con sus diagnósticos—. ``error`` repite el detalle para quien ya
        leía ese campo antes de que el formato fuese el de la RFC 9457.
        """
        cuerpo = {"type": "about:blank", "title": titulo, "status": status,
                  "detail": detalle, "error": detalle}
        self._send(status, json.dumps(cuerpo, ensure_ascii=False).encode(),
                   _PROBLEMA, {**self._cabeceras_de_api(), **(extra or {})})

    def _ruta(self) -> str:
        return self.path.split("?", 1)[0]

    def _metodo_equivocado(self, ruta: str) -> bool:
        """Responde 405 si la ruta es de la API y no admite este método."""
        permitido = _RUTAS.get(ruta)
        if permitido is None or permitido == self.command:
            return False
        self._problema(405, "método no permitido",
                       f"{ruta} solo admite {permitido}",
                       {"Allow": f"{permitido}, OPTIONS"})
        return True

    # -- rutas ----------------------------------------------------------- #
    def do_OPTIONS(self) -> None:  # noqa: N802 - lo impone BaseHTTPRequestHandler
        """La pregunta previa de un navegador que llama desde OTRO origen."""
        ruta = self._ruta()
        if ruta not in _RUTAS:
            self._problema(404, "no encontrado", "ruta desconocida")
            return
        cabeceras = {"Allow": f"{_RUTAS[ruta]}, OPTIONS"}
        if config.ORIGEN_PERMITIDO:
            cabeceras.update({
                "Access-Control-Allow-Origin": config.ORIGEN_PERMITIDO,
                "Access-Control-Allow-Methods": f"{_RUTAS[ruta]}, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": "600",
                "Vary": "Origin",
            })
        self._send(204, b"", "text/plain; charset=utf-8", cabeceras)

    def do_GET(self) -> None:  # noqa: N802
        ruta = self._ruta()
        if self._metodo_equivocado(ruta):
            return
        if ruta == "/api/language":
            self._language()
            return
        if ruta == "/api/health":
            # 200 aunque un proveedor esté mal: lo que contesta es el
            # servidor, y está vivo. El estado de cada uno va en el cuerpo.
            self._json(200, aplicacion.health())
            return
        if ruta == "/api/openapi.json":
            with open(_OPENAPI, "rb") as fh:
                self._send(200, fh.read(), _JSON, self._cabeceras_de_api())
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
        # la página se revalida siempre: son cuatro archivos y una versión
        # vieja en caché habla con una API nueva.
        cabeceras = {"Cache-Control": "no-cache"}
        if tipo == "text/html":
            cabeceras["Content-Security-Policy"] = _CSP_DE_LA_PAGINA
        with open(destino, "rb") as fh:
            self._send(200, fh.read(), f"{tipo}; charset=utf-8"
                       if tipo.startswith("text/") or "javascript" in tipo
                       else tipo, cabeceras)

    def _language(self) -> None:
        """El contrato del lenguaje: categorías de token y catálogo de errores.

        La página NO clasifica tokens ni explica códigos por su cuenta: los
        pide. ``lang_info`` existe justo para eso ("para que la extensión
        coloree sin reimplementar la gramática") y un segundo consumidor con
        sus propias reglas volvería a inventar la respuesta — que es como el
        playground acabó decidiendo por regex si ``INT`` era un tipo.
        """
        global _LANGUAGE
        try:
            if _LANGUAGE is None:
                from include.lang_info import build_language_info
                _LANGUAGE = build_language_info()
        except Exception as exc:  # noqa: BLE001
            self._problema(500, "fallo interno del compilador",
                           f"{type(exc).__name__}: {exc}")
            return
        self._json(200, _LANGUAGE)

    def _descartar(self, largo: int) -> None:
        """Lee y tira un cuerpo que no se va a usar, hasta una cota.

        Responder sin leerlo corta la conexión mientras el cliente todavía
        envía, y lo que ve no es el 413 sino una conexión abortada. Pasada la
        cota no se lee más: se responde y se cierra.
        """
        self.close_connection = True
        resto = min(largo, _MAX_DESCARTE)
        try:
            while resto > 0:
                trozo = self.rfile.read(min(resto, 64 * 1024))
                if not trozo:
                    return
                resto -= len(trozo)
        except OSError:
            return

    def _fuente(self) -> tuple | None:
        """Lee ``(source, debug)`` del cuerpo, o responde el error y da None."""
        tipo = (self.headers.get("Content-Type") or "").split(";", 1)[0]
        if tipo.strip().lower() != "application/json":
            # además de ser lo correcto, obliga al navegador a preguntar
            # antes (CORS): una página ajena no puede poner a compilar a un
            # servidor local con un formulario.
            self._problema(415, "tipo de contenido no admitido",
                           "el cuerpo debe ser application/json")
            return None
        try:
            largo = int(self.headers.get("Content-Length") or "")
        except ValueError:
            self._problema(411, "falta la longitud",
                           "la petición debe traer Content-Length")
            return None
        if largo < 0:
            self._problema(400, "petición ilegible", "Content-Length negativo")
            return None
        if largo > MAX_SOURCE_BYTES:
            self._descartar(largo)
            self._problema(413, "fuente demasiado grande",
                           f"el fuente no puede pasar de "
                           f"{MAX_SOURCE_BYTES // 1024} KB")
            return None
        try:
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
        except (ValueError, UnicodeDecodeError) as exc:
            self._problema(400, "petición ilegible", f"petición ilegible: {exc}")
            return None
        except OSError:
            # el cliente dejó de enviar: no hay a quién responderle.
            self.close_connection = True
            return None
        if not isinstance(cuerpo, dict) \
                or not isinstance(cuerpo.get("source", ""), str):
            self._problema(400, "petición ilegible",
                           'se espera un objeto con "source" de tipo texto')
            return None
        return cuerpo.get("source", ""), bool(cuerpo.get("debug", False))

    def do_POST(self) -> None:  # noqa: N802
        ruta = self._ruta()
        if ruta not in _RUTAS:
            self._problema(404, "no encontrado", "ruta desconocida")
            return
        if self._metodo_equivocado(ruta):
            return
        leido = self._fuente()
        if leido is None:
            return
        source, debug = leido
        try:
            if ruta == "/api/lex":
                # solo el lexer: el editor lo pide en cada pausa al escribir y
                # correr el pipeline entero para colorear sería pagar cien
                # veces lo que cuesta la respuesta.
                self._json(200, aplicacion.lex_source(source))
                return
            self._json(200, compile_source(source, debug=debug))
        except Exception as exc:  # noqa: BLE001 - los proveedores ya no dejan
            # pasar sus fallos; lo que llega aquí es del propio servidor, y
            # tampoco puede tirarlo.
            self._problema(500, "fallo interno del servidor",
                           f"{type(exc).__name__}: {exc}")


def comprobar() -> int:
    """``--check``: dice qué tiene y qué le falta a este entorno, y sale.

    Es la misma pregunta que ``GET /api/health``, sin levantar el servidor:
    para quien acaba de clonar el repositorio y quiere saber si puede usarlo.
    Sale con 0 solo si está todo.
    """
    salud = aplicacion.health()
    nombres = {"compiler": "compilador", "web": "target web"}
    for clave, datos in salud["providers"].items():
        linea = f"{nombres.get(clave, clave):<11} {datos['status']}"
        if datos["detail"]:
            linea += f"  ({datos['detail']})"
        print(linea)
    print(f"escucharía en http://{config.HOST}:{config.PUERTO}")
    return 0 if salud["status"] == "ok" else 1


def main(argv: list | None = None) -> int:
    argumentos = sys.argv[1:] if argv is None else argv
    if argumentos == ["--check"]:
        return comprobar()
    if argumentos:
        print("uso: python playground/server.py [--check]", file=sys.stderr)
        print("la configuración va por variables de entorno "
              "(ver playground/README.md)", file=sys.stderr)
        return 2
    servidor = ThreadingHTTPServer((config.HOST, config.PUERTO), Handler)
    servidor.daemon_threads = True
    donde = "localhost" if config.HOST == "127.0.0.1" else config.HOST
    print(f"suriaX playground en http://{donde}:{servidor.server_address[1]}",
          file=sys.stderr)
    if config.HOST == "127.0.0.1":
        print("  (solo esta máquina; HOST=0.0.0.0 lo publica en la red)",
              file=sys.stderr)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nadiós", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
