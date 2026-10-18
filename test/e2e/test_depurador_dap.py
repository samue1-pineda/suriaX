"""e2e/depurador_dap — el depurador, como lo ve un editor.

Se lanza ``python V0/main.py --dap`` como lo lanzaría un editor y se le habla
DAP por sus tuberías: una sesión entera, de ``initialize`` a ``terminated``.
Lo que decide cuándo parar está probado en ``test_depurador.py``; aquí se
prueba la TRADUCCIÓN — que el protocolo dice lo mismo que el núcleo — y lo
que solo existe con dos procesos: que la salida del programa no ensucia el
canal, que desconectar a medias no deja un proceso colgado.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

_PROGRAMA = """\
#from io #import stdp

struct { int v; } Caja;

fn consume(Caja c) -> int {
    return c.v;
}

fn main() -> int {
    var Caja a = Caja{ v: 41 };
    var int r = consume(move a);
    r = r + 1;
    stdp.println(f"{r}");
    return 7;
}
"""


class _Sesion:
    """Un cliente DAP mínimo sobre las tuberías del adaptador."""

    def __init__(self, carpeta: str, orden=None) -> None:
        self.proc = subprocess.Popen(
            orden or [sys.executable, os.path.join(_REPO, "V0", "main.py"), "--dap"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=carpeta)
        self._seq = 0
        self._mensajes: "queue.Queue[dict]" = queue.Queue()
        self.vistos: list = []          # todo lo recibido, en orden
        threading.Thread(target=self._lee, daemon=True).start()

    def _lee(self) -> None:
        salida = self.proc.stdout
        while True:
            largo = None
            while True:
                linea = salida.readline()
                if not linea:
                    self._mensajes.put({"type": "fin"})
                    return
                linea = linea.strip()
                if not linea:
                    break
                assert linea.lower().startswith(b"content-length:"), linea
                largo = int(linea.split(b":")[1])
            self._mensajes.put(json.loads(salida.read(largo).decode("utf-8")))

    def _siguiente(self) -> dict:
        mensaje = self._mensajes.get(timeout=60)
        self.vistos.append(mensaje)
        return mensaje

    def pide(self, comando: str, **argumentos) -> dict:
        """Manda una petición y devuelve SU respuesta. Los eventos que
        lleguen antes quedan en ``vistos``."""
        self._seq += 1
        cuerpo = json.dumps({"seq": self._seq, "type": "request",
                             "command": comando, "arguments": argumentos}).encode()
        self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(cuerpo) + cuerpo)
        self.proc.stdin.flush()
        while True:
            mensaje = self._siguiente()
            assert mensaje["type"] != "fin", ("el adaptador se cerró",
                                              self.proc.stderr.read()[-600:])
            if mensaje["type"] == "response" and mensaje["request_seq"] == self._seq:
                return mensaje

    def espera(self, evento: str) -> dict:
        """El próximo evento ``evento`` (los ya vistos no cuentan dos veces)."""
        for mensaje in self.vistos:
            if mensaje.get("event") == evento and not mensaje.get("_usado"):
                mensaje["_usado"] = True
                return mensaje
        while True:
            mensaje = self._siguiente()
            assert mensaje["type"] != "fin", ("el adaptador se cerró esperando "
                                              + evento, self.proc.stderr.read()[-600:])
            if mensaje.get("event") == evento:
                mensaje["_usado"] = True
                return mensaje

    def salida_del_programa(self, categoria: str = "stdout") -> str:
        return "".join(m["body"]["output"] for m in self.vistos
                       if m.get("event") == "output"
                       and m["body"].get("category") == categoria)

    def cierra(self) -> int:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            return self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            raise AssertionError("el adaptador no terminó al cerrarle la entrada")


def _con_sesion(fuente: str, comprobar) -> None:
    with tempfile.TemporaryDirectory(prefix="suriax-dap-") as tmp:
        ruta = os.path.join(tmp, "prog.srcx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(fuente)
        sesion = _Sesion(tmp)
        try:
            comprobar(sesion, ruta)
        finally:
            if sesion.proc.poll() is None:
                sesion.cierra()
            for flujo in (sesion.proc.stdout, sesion.proc.stderr):
                flujo.close()


def _arranca(sesion, ruta, *, puntos=(), **lanzamiento):
    respuesta = sesion.pide("initialize", adapterID="suriax")
    assert respuesta["success"] and \
        respuesta["body"]["supportsConfigurationDoneRequest"]
    sesion.espera("initialized")
    assert sesion.pide("launch", program=ruta, **lanzamiento)["success"]
    puestos = sesion.pide("setBreakpoints", source={"path": ruta},
                          breakpoints=[{"line": n} for n in puntos])
    assert [p["line"] for p in puestos["body"]["breakpoints"]] == list(puntos)
    assert sesion.pide("configurationDone")["success"]


def _variables(sesion, ref) -> dict:
    return {v["name"]: v for v in
            sesion.pide("variables", variablesReference=ref)["body"]["variables"]}


def test_una_sesion_entera_de_initialize_a_terminated():
    def comprobar(sesion, ruta):
        _arranca(sesion, ruta, puntos=[11, 12])

        parada = sesion.espera("stopped")["body"]
        assert parada["reason"] == "breakpoint" and parada["threadId"] == 1
        assert sesion.pide("threads")["body"]["threads"] == \
            [{"id": 1, "name": "principal"}]

        pila = sesion.pide("stackTrace", threadId=1)["body"]["stackFrames"]
        assert [(m["name"], m["line"]) for m in pila] == [("main", 11)]
        assert os.path.normcase(pila[0]["source"]["path"]) == os.path.normcase(ruta)

        ambitos = {a["name"]: a["variablesReference"] for a in
                   sesion.pide("scopes", frameId=pila[0]["id"])["body"]["scopes"]}
        assert list(ambitos) == ["Locales", "Propiedad", "Globales"]
        locales = _variables(sesion, ambitos["Locales"])
        assert locales["a"]["type"] == "dueña" and "Caja" in locales["a"]["value"]
        # un struct se despliega en sus campos
        campos = _variables(sesion, locales["a"]["variablesReference"])
        assert campos["v"]["value"] == "41" and campos["v"]["variablesReference"] == 0

        # seguir hasta el siguiente punto: 'a' ya cedió su valor
        assert sesion.pide("continue", threadId=1)["success"]
        assert sesion.espera("stopped")["body"]["reason"] == "breakpoint"
        pila = sesion.pide("stackTrace", threadId=1)["body"]["stackFrames"]
        assert pila[0]["line"] == 12
        ambitos = {a["name"]: a["variablesReference"] for a in
                   sesion.pide("scopes", frameId=pila[0]["id"])["body"]["scopes"]}
        propiedad = {n: v["value"] for n, v in
                     _variables(sesion, ambitos["Propiedad"]).items()}
        assert propiedad == {"a": "movida", "r": "dueña"}, propiedad
        locales = _variables(sesion, ambitos["Locales"])
        assert locales["a"]["value"] == "(movida)" and \
            locales["a"]["variablesReference"] == 0
        assert locales["r"]["value"] == "41"

        # un paso: la línea siguiente, con 'r' ya cambiado
        assert sesion.pide("next", threadId=1)["success"]
        assert sesion.espera("stopped")["body"]["reason"] == "step"
        pila = sesion.pide("stackTrace", threadId=1)["body"]["stackFrames"]
        assert pila[0]["line"] == 13
        mirado = sesion.pide("evaluate", expression="r", frameId=pila[0]["id"])
        assert mirado["body"]["result"] == "42  (dueña)", mirado
        negado = sesion.pide("evaluate", expression="r + 1", frameId=pila[0]["id"])
        assert not negado["success"] and "solo se pueden mirar nombres" in \
            negado["message"]

        assert sesion.pide("continue", threadId=1)["success"]
        assert sesion.espera("exited")["body"]["exitCode"] == 7
        sesion.espera("terminated")
        # lo que el programa escribió llegó como evento, no por el canal
        assert sesion.salida_del_programa() == "42\n"
        assert sesion.pide("disconnect")["success"]
        assert sesion.cierra() == 0

    _con_sesion(_PROGRAMA, comprobar)


def test_entrar_y_salir_por_el_protocolo():
    def comprobar(sesion, ruta):
        _arranca(sesion, ruta, stopOnEntry=True)
        assert sesion.espera("stopped")["body"]["reason"] == "entry"
        lineas = []
        for comando in ("next", "stepIn", "stepOut"):
            assert sesion.pide(comando, threadId=1)["success"]
            sesion.espera("stopped")
            pila = sesion.pide("stackTrace", threadId=1)["body"]["stackFrames"]
            lineas.append([(m["name"], m["line"]) for m in pila])
        assert lineas == [
            [("main", 11)],                     # pasar: la línea siguiente
            [("consume", 6), ("main", 11)],     # entrar: dentro de la llamada
            [("main", 12)],                     # salir: de vuelta en quien llamó
        ], lineas
        sesion.pide("disconnect")
        assert sesion.cierra() == 0

    _con_sesion(_PROGRAMA, comprobar)


def test_un_programa_que_no_compila_lo_dice_y_termina():
    """Los diagnósticos van a la consola del editor; no queda una sesión
    abierta esperando un programa que no existe."""
    def comprobar(sesion, ruta):
        _arranca(sesion, ruta)
        assert sesion.espera("exited")["body"]["exitCode"] != 0
        sesion.espera("terminated")
        assert "SEM001" in sesion.salida_del_programa("stderr"), \
            sesion.salida_del_programa("stderr")
        sesion.pide("disconnect")
        assert sesion.cierra() == 0

    _con_sesion("fn main() -> int { return q; }\n", comprobar)


def test_un_error_de_ejecucion_detiene_y_luego_llega_a_la_consola():
    """Por defecto —como el filtro que el editor trae marcado— el depurador
    se detiene donde el programa va a terminar por un error, dice cuál es y
    deja mirar las variables; al seguir, el error sale por la consola."""
    def comprobar(sesion, ruta):
        capacidades = sesion.pide("initialize", adapterID="suriax")["body"]
        filtros = {f["filter"]: f["default"]
                   for f in capacidades["exceptionBreakpointFilters"]}
        assert filtros == {"sin-atrapar": True, "todos": False}
        sesion.espera("initialized")
        sesion.pide("launch", program=ruta)
        sesion.pide("configurationDone")

        parada = sesion.espera("stopped")["body"]
        assert parada["reason"] == "exception" and "EXC001" in parada["description"]
        assert "división por cero" in parada["text"]
        info = sesion.pide("exceptionInfo", threadId=1)["body"]
        assert info["exceptionId"] == "EXC001" and info["breakMode"] == "unhandled"
        pila = sesion.pide("stackTrace", threadId=1)["body"]["stackFrames"]
        assert pila[0]["line"] == 4
        ambitos = {a["name"]: a["variablesReference"] for a in
                   sesion.pide("scopes", frameId=pila[0]["id"])["body"]["scopes"]}
        assert _variables(sesion, ambitos["Locales"])["b"]["value"] == "0"

        assert sesion.pide("continue", threadId=1)["success"]
        assert sesion.espera("exited")["body"]["exitCode"] == 70
        sesion.espera("terminated")
        assert "EXC001" in sesion.salida_del_programa("stderr"), \
            sesion.salida_del_programa("stderr")
        sesion.pide("disconnect")
        assert sesion.cierra() == 0

    _con_sesion("fn main() -> int {\n"
                "    var int a = 1;\n"
                "    var int b = a - 1;\n"
                "    return a / b;\n"
                "}\n", comprobar)


def test_el_editor_puede_pedir_que_no_se_detenga_en_errores():
    def comprobar(sesion, ruta):
        sesion.pide("initialize", adapterID="suriax")
        sesion.espera("initialized")
        sesion.pide("launch", program=ruta)
        assert sesion.pide("setExceptionBreakpoints", filters=[])["success"]
        sesion.pide("configurationDone")
        assert sesion.espera("exited")["body"]["exitCode"] == 70
        assert not [m for m in sesion.vistos if m.get("event") == "stopped"]
        sesion.pide("disconnect")
        assert sesion.cierra() == 0

    _con_sesion("fn main() -> int {\n"
                "    var int a = 1;\n"
                "    var int b = a - 1;\n"
                "    return a / b;\n"
                "}\n", comprobar)


_CON_PRUEBAS = """\
#from io #import stdp

fn doble(int n) -> int { return n + n; }

fn main() -> int {
    stdp.println("esto es main");
    return 0;
}

test "doble" {
    var int r = doble(4);
    expect (r == 8);
}
"""


def test_las_banderas_del_compilador_se_pasan_desde_la_configuracion():
    """``"flags": ["--test"]`` en launch.json: las mismas banderas que en la
    terminal, leídas con el mismo analizador. Con ``--test`` lo que se depura
    son las pruebas, no ``main``."""
    def comprobar(sesion, ruta):
        _arranca(sesion, ruta, puntos=[12], flags=["--test", "--trace-memory"])
        assert sesion.espera("stopped")["body"]["reason"] == "breakpoint"
        pila = sesion.pide("stackTrace", threadId=1)["body"]["stackFrames"]
        assert pila[0]["line"] == 12
        ambitos = {a["name"]: a["variablesReference"] for a in
                   sesion.pide("scopes", frameId=pila[0]["id"])["body"]["scopes"]}
        assert _variables(sesion, ambitos["Locales"])["r"]["value"] == "8"
        sesion.pide("continue", threadId=1)
        assert sesion.espera("exited")["body"]["exitCode"] == 0
        salida = sesion.salida_del_programa()
        assert "esto es main" not in salida, salida     # corrieron las pruebas
        assert "doble" in salida, salida
        sesion.pide("disconnect")
        assert sesion.cierra() == 0

    _con_sesion(_CON_PRUEBAS, comprobar)


def test_una_bandera_de_volcado_deja_su_archivo():
    """Las banderas que piden un artefacto valen igual que en la terminal:
    se compila como siempre y, además, queda el volcado."""
    def comprobar(sesion, ruta):
        _arranca(sesion, ruta, flags=["--hir-pretty"])
        assert sesion.espera("exited")["body"]["exitCode"] == 0
        sesion.pide("disconnect")
        assert sesion.cierra() == 0
        volcados = os.path.join(os.path.dirname(ruta), "dumps")
        legibles = [n for n in os.listdir(volcados) if n.endswith(".pretty")]
        assert legibles, os.listdir(volcados)

    _con_sesion(_CON_PRUEBAS, comprobar)


def test_una_bandera_que_no_vale_se_dice_al_lanzar():
    """Un error de escritura en launch.json no puede esperar a mitad de la
    sesión, ni caer en silencio a "sin banderas"."""
    def comprobar(sesion, ruta):
        sesion.pide("initialize", adapterID="suriax")
        for mala, motivo in ((["--tets"], "unrecognized arguments"),
                             (["--run", "compiler"], "no se puede usar al depurar"),
                             (["--emit-lang-info"], "no se puede usar al depurar"),
                             (["otro.srcx"], "banderas no válidas")):
            negada = sesion.pide("launch", program=ruta, flags=mala)
            assert not negada["success"] and motivo in negada["message"], \
                (mala, negada)
        assert sesion.pide("launch", program=ruta, flags=["--hir-pretty"])["success"]
        sesion.pide("disconnect")
        assert sesion.cierra() == 0

    _con_sesion(_CON_PRUEBAS, comprobar)


def test_un_programa_que_lee_la_entrada_no_se_come_el_protocolo():
    """Bajo el depurador la entrada estándar del proceso es el canal por el
    que habla el editor. Un programa que la lee ve una entrada VACÍA; si la
    leyera de verdad, se tragaría los mensajes siguientes y la sesión se
    colgaría."""
    fuente = ("#from io #import stdp\n"
              "#import sistema.entrada as entrada\n"
              "fn main() -> int {\n"
              '    stdp.println(f"vacía={entrada.terminada()} todo=[{entrada.todo()}]");\n'
              "    return 0;\n"
              "}\n")

    def comprobar(sesion, ruta):
        _arranca(sesion, ruta, puntos=[4])
        assert sesion.espera("stopped")["body"]["reason"] == "breakpoint"
        # la sesión sigue respondiendo después de que el programa lea
        assert sesion.pide("next", threadId=1)["success"]
        assert sesion.espera("stopped")["body"]["reason"] == "step"
        assert sesion.pide("continue", threadId=1)["success"]
        sesion.espera("exited")
        assert sesion.salida_del_programa() == "vacía=true todo=[]\n"
        assert sesion.pide("disconnect")["success"]
        assert sesion.cierra() == 0

    _con_sesion(fuente, comprobar)


def test_desconectar_con_el_programa_detenido_no_deja_nada_colgado():
    def comprobar(sesion, ruta):
        _arranca(sesion, ruta, stopOnEntry=True)
        sesion.espera("stopped")
        assert sesion.pide("disconnect")["success"]
        assert sesion.cierra() == 0

    _con_sesion(_PROGRAMA, comprobar)


def test_terminar_corta_el_programa_detenido_y_lo_dice():
    """``terminate`` no es irse: es pedir que el PROGRAMA acabe. El editor
    espera el ``terminated`` para cerrar la sesión; si el programa se quedara
    detenido, no llegaría nunca."""
    def comprobar(sesion, ruta):
        _arranca(sesion, ruta, stopOnEntry=True)
        sesion.espera("stopped")
        assert sesion.pide("terminate")["success"]
        sesion.espera("terminated")
        # no llegó a escribir nada: se cortó antes de su 'println'
        assert sesion.salida_del_programa() == ""
        sesion.pide("disconnect")
        assert sesion.cierra() == 0

    _con_sesion(_PROGRAMA, comprobar)


def test_cerrar_la_tuberia_sin_despedirse_tambien_termina():
    """Un editor que muere no manda ``disconnect``: solo se cierra la
    entrada. El adaptador tiene que irse igual."""
    def comprobar(sesion, ruta):
        _arranca(sesion, ruta, puntos=[12])
        sesion.espera("stopped")
        assert sesion.cierra() == 0

    _con_sesion(_PROGRAMA, comprobar)


def test_el_lanzador_de_la_extension_habla_con_el_mismo_depurador():
    """Lo que VS Code ejecuta es ``tooling/vscode/depurar.py``. Se lanza
    desde OTRA carpeta, como hará el editor, y tiene que dar con el
    compilador y pasar la conversación intacta."""
    lanzador = os.path.join(_REPO, "tooling", "vscode", "depurar.py")
    with tempfile.TemporaryDirectory(prefix="suriax-dap-") as tmp:
        ruta = os.path.join(tmp, "prog.srcx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(_PROGRAMA)
        sesion = _Sesion(tmp, [sys.executable, lanzador])
        try:
            _arranca(sesion, ruta, puntos=[12])
            assert sesion.espera("stopped")["body"]["reason"] == "breakpoint"
            assert sesion.pide("continue", threadId=1)["success"]
            assert sesion.espera("exited")["body"]["exitCode"] == 7
            sesion.pide("disconnect")
            assert sesion.cierra() == 0
        finally:
            if sesion.proc.poll() is None:
                sesion.proc.kill()
            for flujo in (sesion.proc.stdout, sesion.proc.stderr):
                flujo.close()


def test_una_peticion_desconocida_o_a_destiempo_no_tumba_la_sesion():
    def comprobar(sesion, ruta):
        sesion.pide("initialize", adapterID="suriax")
        negada = sesion.pide("unaQueNoExiste")
        assert not negada["success"] and "sin soporte" in negada["message"]
        negada = sesion.pide("launch", program=ruta + ".noexiste")
        assert not negada["success"] and "no existe el programa" in negada["message"]
        # sin programa detenido no hay marcos que mirar
        negada = sesion.pide("scopes", frameId=1)
        assert not negada["success"]
        assert sesion.pide("threads")["success"]
        sesion.pide("disconnect")
        assert sesion.cierra() == 0

    _con_sesion(_PROGRAMA, comprobar)
