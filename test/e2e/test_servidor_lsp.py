"""e2e/servidor_lsp — el servidor de lenguaje, como lo ve un editor.

Se lanza ``python V0/main.py --lsp`` como lo lanzaría un editor y se le habla
LSP por sus tuberías. Lo que dice cada respuesta lo decide el índice del
compilador (``test/unit/test_lsp_index.py``); aquí se prueba lo que solo
existe con dos procesos: que el buffer SIN GUARDAR es lo que se analiza, que
las columnas llegan en la unidad del editor, que un fallo del compilador no
tumba al servidor y que el ciclo de vida (``shutdown``/``exit``) es el del
protocolo.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import textwrap
import threading

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (_REPO, os.path.join(_REPO, "V0")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_PROGRAMA = """\
#from io #import stdp

// un punto del plano
struct { int x; int y; } Punto;

// el doble de n
fn doble(int n) -> int {
    return n * 2;
}

fn main() -> int {
    var int a = doble(3);
    var Punto p = Punto{ x: 1, y: 2 };
    a += p.x;
    stdp.println(f"{a}");
    return 0;
}
"""


class _Sesion:
    """Un cliente LSP mínimo sobre las tuberías del servidor."""

    def __init__(self, carpeta: str, orden=None) -> None:
        self.carpeta = carpeta
        self.proc = subprocess.Popen(
            orden or [sys.executable, os.path.join(_REPO, "V0", "main.py"), "--lsp"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=carpeta)
        self._id = 0
        self._mensajes: "queue.Queue[dict]" = queue.Queue()
        self.notificaciones: list = []
        threading.Thread(target=self._lee, daemon=True).start()

    def _lee(self) -> None:
        salida = self.proc.stdout
        while True:
            largo = None
            while True:
                linea = salida.readline()
                if not linea:
                    self._mensajes.put({"fin": True})
                    return
                linea = linea.strip()
                if not linea:
                    break
                assert linea.lower().startswith(b"content-length:"), linea
                largo = int(linea.split(b":")[1])
            self._mensajes.put(json.loads(salida.read(largo).decode("utf-8")))

    def _siguiente(self) -> dict:
        mensaje = self._mensajes.get(timeout=120)
        assert not mensaje.get("fin"), ("el servidor se cerró",
                                        self.proc.stderr.read()[-800:])
        if "method" in mensaje and "id" not in mensaje:
            self.notificaciones.append(mensaje)
        return mensaje

    def manda(self, mensaje: dict) -> None:
        mensaje["jsonrpc"] = "2.0"
        cuerpo = json.dumps(mensaje).encode("utf-8")
        self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(cuerpo) + cuerpo)
        self.proc.stdin.flush()

    def pide(self, metodo: str, parametros) -> dict:
        """La RESPUESTA completa (``result`` o ``error``) a la petición."""
        self._id += 1
        self.manda({"id": self._id, "method": metodo, "params": parametros})
        while True:
            mensaje = self._siguiente()
            if mensaje.get("id") == self._id and "method" not in mensaje:
                return mensaje

    def notifica(self, metodo: str, parametros) -> None:
        self.manda({"method": metodo, "params": parametros})

    def diagnosticos(self, uri: str, version=None) -> list:
        """Los próximos diagnósticos publicados para ``uri`` (de esa versión,
        si se da)."""
        for mensaje in self.notificaciones:
            if _son_de(mensaje, uri, version) and not mensaje.get("_usado"):
                mensaje["_usado"] = True
                return mensaje["params"]["diagnostics"]
        while True:
            mensaje = self._siguiente()
            if _son_de(mensaje, uri, version):
                mensaje["_usado"] = True
                return mensaje["params"]["diagnostics"]

    def inicia(self) -> dict:
        respuesta = self.pide("initialize", {"processId": os.getpid(), "capabilities": {},
                                             "rootUri": _uri(self.carpeta)})
        self.notifica("initialized", {})
        return respuesta["result"]

    def abre(self, nombre: str, texto: str) -> str:
        uri = _uri(os.path.join(self.carpeta, nombre))
        self.notifica("textDocument/didOpen", {"textDocument": {
            "uri": uri, "languageId": "suriax", "version": 1, "text": texto}})
        return uri

    def cierra(self) -> int:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            return self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            raise AssertionError("el servidor no terminó al cerrarle la entrada")


def _son_de(mensaje: dict, uri: str, version) -> bool:
    return (mensaje.get("method") == "textDocument/publishDiagnostics"
            and mensaje["params"]["uri"] == uri
            and (version is None or mensaje["params"].get("version") == version))


def _uri(ruta: str) -> str:
    """El URI como lo escribe VS Code en Windows (la unidad en minúscula y
    los dos puntos codificados): es la forma que más cuesta leer."""
    from urllib.parse import quote
    ruta = os.path.abspath(ruta).replace("\\", "/")
    if not ruta.startswith("/"):
        ruta = "/" + ruta[0].lower() + ruta[1:]
    return "file://" + quote(ruta)


def _con_sesion(comprobar, orden=None) -> None:
    with tempfile.TemporaryDirectory(prefix="suriax-lsp-") as tmp:
        sesion = _Sesion(tmp, orden)
        try:
            comprobar(sesion)
        finally:
            if sesion.proc.poll() is None:
                sesion.cierra()
            for flujo in (sesion.proc.stdout, sesion.proc.stderr):
                flujo.close()


def _posicion(texto: str, trozo: str, desplazamiento: int = 0, *, ultima=False) -> dict:
    """La posición LSP de ``trozo`` en ``texto`` (todo ASCII: columna =
    índice)."""
    indice = (texto.rindex if ultima else texto.index)(trozo) + desplazamiento
    linea = texto.count("\n", 0, indice)
    return {"line": linea, "character": indice - (texto.rfind("\n", 0, indice) + 1)}


# --------------------------------------------------------------------------- #
# diagnósticos
# --------------------------------------------------------------------------- #

def test_analiza_el_buffer_sin_guardar_y_sigue_sus_cambios():
    """El archivo NO existe en disco: lo que se analiza es el texto del
    editor. Al corregirlo, los diagnósticos se vacían."""
    def comprobar(sesion):
        capacidades = sesion.inicia()["capabilities"]
        assert capacidades["textDocumentSync"]["change"] == 1, "sincronización completa"
        roto = _PROGRAMA.replace("return 0;", "return nada;")
        uri = sesion.abre("sin_guardar.srcx", roto)
        assert not os.path.exists(os.path.join(sesion.carpeta, "sin_guardar.srcx"))
        diagnosticos = sesion.diagnosticos(uri, 1)
        assert [d["code"] for d in diagnosticos] == ["SEM001"], diagnosticos
        error, = diagnosticos
        assert error["severity"] == 1 and error["source"] == "suriaX"
        assert error["range"]["start"] == _posicion(roto, "nada"), error["range"]
        assert error["range"]["end"] == _posicion(roto, "nada", 4)

        sesion.notifica("textDocument/didChange", {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [{"text": _PROGRAMA}]})
        assert sesion.diagnosticos(uri, 2) == []

        sesion.notifica("textDocument/didClose", {"textDocument": {"uri": uri}})
        assert sesion.diagnosticos(uri) == [], "al cerrar se limpian"

    _con_sesion(comprobar)


def test_las_columnas_llegan_en_utf16_como_las_cuenta_el_editor():
    """Un emoji es UN carácter para el compilador y DOS unidades para el
    editor: sin traducir, el subrayado queda corrido una columna."""
    def comprobar(sesion):
        sesion.inicia()
        texto = 'fn main() -> int {\n    var str s = "😀"; return nada;\n}\n'
        uri = sesion.abre("emoji.srcx", texto)
        error, = sesion.diagnosticos(uri, 1)
        linea = texto.split("\n")[1]
        caracteres = linea.index("nada")
        assert error["range"]["start"] == {"line": 1, "character": caracteres + 1}, error

    _con_sesion(comprobar)


def test_un_error_de_sintaxis_tambien_se_publica():
    def comprobar(sesion):
        sesion.inicia()
        uri = sesion.abre("roto.srcx", "fn main() -> int { var int = ; return 0; }\n")
        diagnosticos = sesion.diagnosticos(uri, 1)
        assert diagnosticos and all(d["code"].startswith("PAR") for d in diagnosticos), \
            diagnosticos

    _con_sesion(comprobar)


# --------------------------------------------------------------------------- #
# hover, definición, símbolos, completar
# --------------------------------------------------------------------------- #

def test_hover_trae_la_firma_y_el_comentario():
    def comprobar(sesion):
        sesion.inicia()
        uri = sesion.abre("prog.srcx", _PROGRAMA)
        donde = _posicion(_PROGRAMA, "doble(3)", 2)
        hover = sesion.pide("textDocument/hover", {
            "textDocument": {"uri": uri}, "position": donde})["result"]
        valor = hover["contents"]["value"]
        assert "fn doble(int n) -> int" in valor and "el doble de n" in valor, valor
        assert hover["range"]["start"] == _posicion(_PROGRAMA, "doble(3)")
        # fuera de un nombre no hay nada que decir
        vacio = sesion.pide("textDocument/hover", {
            "textDocument": {"uri": uri}, "position": {"line": 1, "character": 0}})
        assert vacio["result"] is None

    _con_sesion(comprobar)


def test_ir_a_la_definicion_en_el_archivo_y_en_una_libreria():
    def comprobar(sesion):
        sesion.inicia()
        uri = sesion.abre("prog.srcx", _PROGRAMA)
        local = sesion.pide("textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": _posicion(_PROGRAMA, "doble(3)", 1)})["result"]
        assert local["uri"] == uri, "el mismo documento, con el URI que mandó el editor"
        assert local["range"]["start"] == _posicion(_PROGRAMA, "doble(int")

        # 'println' va tras un punto: el índice no anota ese uso; se resuelve
        # por los miembros de 'stdp' y abre la librería
        ajena = sesion.pide("textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": _posicion(_PROGRAMA, "println", 3)})["result"]
        assert ajena["uri"].endswith("/lib/io/stdp.libsrx"), ajena
        with open(os.path.join(_REPO, "lib", "io", "stdp.libsrx"), encoding="utf-8") as fh:
            linea = fh.read().splitlines()[ajena["range"]["start"]["line"]]
        inicio, fin = ajena["range"]["start"]["character"], ajena["range"]["end"]["character"]
        assert linea[inicio:fin] == "println", linea

    _con_sesion(comprobar)


def test_los_simbolos_del_documento_van_anidados():
    def comprobar(sesion):
        sesion.inicia()
        uri = sesion.abre("prog.srcx", _PROGRAMA)
        simbolos = sesion.pide("textDocument/documentSymbol",
                               {"textDocument": {"uri": uri}})["result"]
        assert [s["name"] for s in simbolos] == ["Punto", "doble", "main"], simbolos
        punto, doble, main = simbolos
        assert (punto["kind"], doble["kind"]) == (23, 12)          # Struct, Function
        assert [h["name"] for h in punto["children"]] == ["x", "y"]
        assert [h["name"] for h in main["children"]] == ["a", "p"]
        assert doble["selectionRange"]["start"] == _posicion(_PROGRAMA, "doble(int")

    _con_sesion(comprobar)


def test_completar_tras_un_punto_aunque_el_archivo_no_parsee():
    """Mientras se escribe ``stdp.`` el archivo está roto y el compilador no
    da índice: se completa con el del último análisis limpio."""
    def comprobar(sesion):
        sesion.inicia()
        uri = sesion.abre("prog.srcx", _PROGRAMA)
        assert sesion.diagnosticos(uri, 1) == []
        a_medias = _PROGRAMA.replace('    return 0;', '    stdp.\n    return 0;')
        sesion.notifica("textDocument/didChange", {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [{"text": a_medias}]})
        items = sesion.pide("textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": _posicion(a_medias, "stdp.\n", 5)})["result"]
        etiquetas = {i["label"] for i in items}
        assert {"println", "print"} <= etiquetas, etiquetas
        assert "doble" not in etiquetas, "tras 'stdp.' van sus miembros, no todo"
        # sin punto: lo visible en 'main' y las palabras reservadas
        items = sesion.pide("textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": _posicion(a_medias, "    stdp.", 4)})["result"]
        etiquetas = {i["label"] for i in items}
        assert {"doble", "main", "a", "p", "Punto", "return", "while"} <= etiquetas
        assert "n" not in etiquetas, "'n' es de 'doble', no de 'main'"

    _con_sesion(comprobar)


# --------------------------------------------------------------------------- #
# robustez y ciclo de vida
# --------------------------------------------------------------------------- #

_ROMPE = textwrap.dedent("""\
    import sys
    sys.path[:0] = [{v0!r}, {repo!r}]
    from driver import inspect as canal
    original = canal.emit_index

    def rota(ruta, **kw):
        texto = kw.get("source") or ""
        if "ROMPE" in texto:
            raise RuntimeError("fallo provocado por la prueba")
        respuesta = original(ruta, **kw)
        if "MALFORMA" in texto:
            # una respuesta que el servidor no sabe traducir: el fallo no es
            # del compilador sino de quien lee su respuesta
            respuesta["diagnostics"] = [{{"line": "x", "column": None}}]
        return respuesta

    canal.emit_index = rota
    from tooling import lsp
    raise SystemExit(lsp.main())
""")


def test_un_fallo_del_compilador_no_tumba_el_servidor():
    """El análisis que falla se convierte en un ICE000 VISIBLE en el
    documento, con la excepción; el servidor sigue contestando y el resto
    de documentos se analiza normal. El fallo se provoca desde fuera (una
    envoltura que rompe el canal), sin ganchos de prueba en el servidor."""
    with tempfile.TemporaryDirectory(prefix="suriax-lsp-") as tmp:
        envoltura = os.path.join(tmp, "rompe.py")
        with open(envoltura, "w", encoding="utf-8") as fh:
            fh.write(_ROMPE.format(v0=os.path.join(_REPO, "V0"), repo=_REPO))

        def comprobar(sesion):
            sesion.inicia()
            uri = sesion.abre("roto.srcx", "// ROMPE\n" + _PROGRAMA)
            ice, = sesion.diagnosticos(uri, 1)
            assert ice["code"] == "ICE000" and ice["severity"] == 1, ice
            assert "RuntimeError: fallo provocado por la prueba" in ice["message"], ice
            # sigue vivo: contesta y analiza otro documento
            assert sesion.pide("textDocument/hover", {
                "textDocument": {"uri": uri},
                "position": {"line": 0, "character": 0}})["result"] is None
            sano = sesion.abre("sano.srcx", _PROGRAMA)
            assert sesion.diagnosticos(sano, 1) == []
            # un fallo al TRADUCIR la respuesta, analizando en reposo (fuera
            # de una petición, donde nadie más lo atraparía)
            raro = sesion.abre("raro.srcx", "// MALFORMA\n" + _PROGRAMA)
            ice, = sesion.diagnosticos(raro, 1)
            assert ice["code"] == "ICE000" and "TypeError" in ice["message"], ice
            assert sesion.pide("textDocument/documentSymbol",
                               {"textDocument": {"uri": raro}})["result"] == []
            # y la traza quedó en el registro del editor
            registro = [m["params"]["message"] for m in sesion.notificaciones
                        if m["method"] == "window/logMessage"]
            assert any("Traceback" in r and "RuntimeError" in r for r in registro), registro
            assert sesion.pide("shutdown", None)["result"] is None
            sesion.notifica("exit", None)
            assert sesion.proc.wait(timeout=30) == 0

        _con_sesion(comprobar, orden=[sys.executable, envoltura])


def test_peticiones_a_destiempo_o_desconocidas_se_contestan_con_error():
    def comprobar(sesion):
        antes = sesion.pide("textDocument/hover", {
            "textDocument": {"uri": "file:///x.srcx"}, "position": {"line": 0, "character": 0}})
        assert antes["error"]["code"] == -32002, antes        # sin inicializar
        sesion.inicia()
        rara = sesion.pide("textDocument/unaQueNoExiste", {})
        assert rara["error"]["code"] == -32601, rara
        # una notificación '$/…' que no se atiende no recibe respuesta ni
        # rompe nada
        sesion.notifica("$/cancelRequest", {"id": 99})
        # una petición mal formada (sin 'position') sobre un documento abierto
        uri = sesion.abre("prog.srcx", _PROGRAMA)
        mal = sesion.pide("textDocument/hover", {"textDocument": {"uri": uri}})
        assert mal["error"]["code"] == -32603 and "KeyError" in mal["error"]["message"], mal
        assert sesion.pide("shutdown", None)["result"] is None
        tarde = sesion.pide("textDocument/hover", {
            "textDocument": {"uri": "file:///x.srcx"}, "position": {"line": 0, "character": 0}})
        assert tarde["error"]["code"] == -32600, "tras 'shutdown' no se atiende nada"
        sesion.notifica("exit", None)
        assert sesion.proc.wait(timeout=30) == 0

    _con_sesion(comprobar)


def test_salir_sin_shutdown_o_cerrando_la_tuberia_tambien_termina():
    """El protocolo pide código 1 si el editor manda ``exit`` sin
    ``shutdown``; y un editor que muere solo cierra la entrada."""
    def sin_despedida(sesion):
        sesion.inicia()
        sesion.notifica("exit", None)
        assert sesion.proc.wait(timeout=30) == 1

    def cerrando(sesion):
        sesion.inicia()
        sesion.abre("prog.srcx", _PROGRAMA)
        assert sesion.cierra() == 1

    _con_sesion(sin_despedida)
    _con_sesion(cerrando)


def test_el_lanzador_de_la_extension_habla_con_el_mismo_servidor():
    """Lo que la extensión ejecuta es ``tooling/vscode/lanzar.py --lsp``,
    desde la carpeta de trabajo del usuario: tiene que dar con el compilador
    y pasar la conversación intacta."""
    lanzador = os.path.join(_REPO, "tooling", "vscode", "lanzar.py")

    def comprobar(sesion):
        resultado = sesion.inicia()
        assert resultado["serverInfo"]["name"] == "suriaX"
        from include.lang_info import LANG_INFO_VERSION
        assert resultado["capabilities"]["experimental"]["suriax"]["langInfoVersion"] \
            == LANG_INFO_VERSION
        uri = sesion.abre("prog.srcx", _PROGRAMA)
        assert sesion.diagnosticos(uri, 1) == []
        assert sesion.pide("shutdown", None)["result"] is None
        sesion.notifica("exit", None)
        assert sesion.proc.wait(timeout=30) == 0

    _con_sesion(comprobar, orden=[sys.executable, lanzador, "--lsp"])
