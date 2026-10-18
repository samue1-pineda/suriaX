"""El depurador, hablado en DAP (Debug Adapter Protocol).

DAP es el protocolo con el que un editor habla con un depurador: mensajes
JSON por la entrada y la salida estándar, cada uno precedido de su longitud.
Lo entienden VS Code, Neovim, Emacs, los IDE de JetBrains y otros, así que
hablarlo aquí —y no dentro de una extensión— deja toda la lógica en el
compilador y a cada editor solo el trabajo de lanzar este proceso:

    python V0/main.py --dap

Este módulo es SOLO la traducción. Cuándo parar y qué hay a la vista lo
decide ``depurador.py``, que no sabe que existe un protocolo.

Dos hilos, cada uno con un trabajo:

 * el principal LEE las peticiones del editor y las contesta;
 * el del programa compila y ejecuta. Cuando el depurador lo detiene, ese
   hilo avisa al editor (``stopped``) y espera; una petición de seguir lo
   despierta.

Lo que el programa escribe no va a la salida estándar —es el canal del
protocolo—: se convierte en eventos ``output``.

La columna de suriaX, la **propiedad**, llega al editor de dos formas: como
el tipo de cada variable (lo que el editor enseña al pasar por encima) y como
un ámbito propio, ``Propiedad``, donde cada nombre dice si sigue siendo
dueño de su valor.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from typing import Any, Dict, List, Optional

from . import depurador as nucleo

#: un solo hilo de ejecución: suriaX no tiene concurrencia.
_HILO = 1
_NOMBRE_HILO = "principal"

_PASOS = {"next": "pasar", "stepIn": "entrar", "stepOut": "salir"}


class _Terminar(BaseException):
    """Corta el programa desde dentro cuando el editor se desconecta. No es
    una ``Exception`` a propósito: ningún ``except Exception`` del intérprete
    debe poder tragársela."""


class _Salida:
    """Lo que el programa escribe, convertido en eventos ``output``."""

    def __init__(self, adaptador: "Adaptador", categoria: str) -> None:
        self._adaptador = adaptador
        self._categoria = categoria

    def write(self, texto: str) -> int:
        if texto:
            self._adaptador.evento("output", {"category": self._categoria,
                                              "output": texto})
        return len(texto)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


class Adaptador:
    """Una sesión de depuración sobre un par de flujos binarios."""

    def __init__(self, entrada, salida, lee_banderas=None) -> None:
        self._entrada = entrada
        self._salida = salida
        # quien arranca el adaptador le da la función que entiende las
        # banderas de 'launch' (la CLI: ``cli.depurar.banderas``). El
        # depurador es del compilador y no conoce a la terminal; sin ella,
        # una sesión no admite banderas.
        self._lee_banderas = lee_banderas
        self._escribe = threading.Lock()
        self._seq = 0
        self._lanzamiento: Dict[str, Any] = {}
        self._puntos: Dict[str, List[int]] = {}
        self._dep: Optional[nucleo.Depurador] = None
        self._seguir = threading.Event()
        self._hilo: Optional[threading.Thread] = None
        self._terminar = False
        self._fin = threading.Event()
        # lo que el editor puede pedir desplegar mientras está detenido:
        # número -> función que da la lista de variables. Se vacía al seguir,
        # como manda el protocolo (una referencia vale solo durante la parada).
        self._refs: Dict[int, Any] = {}
        self._marcos: List[nucleo.Marco] = []
        # por defecto, como el filtro que el editor trae marcado: parar donde
        # el programa va a terminar por un error.
        self._errores: Optional[str] = nucleo.SIN_ATRAPAR
        self._banderas: Dict[str, dict] = {"compilar": {}, "ejecutar": {}}

    # ------------------------------------------------------------------ #
    # el cable
    # ------------------------------------------------------------------ #
    def _lee(self) -> Optional[dict]:
        largo = None
        while True:
            linea = self._entrada.readline()
            if not linea:
                return None
            linea = linea.strip()
            if not linea:
                break
            nombre, _, valor = linea.partition(b":")
            if nombre.strip().lower() == b"content-length":
                largo = int(valor.strip())
        if largo is None:
            return None
        cuerpo = self._entrada.read(largo)
        if len(cuerpo) < largo:
            return None
        return json.loads(cuerpo.decode("utf-8"))

    def _manda(self, mensaje: dict) -> None:
        with self._escribe:
            self._seq += 1
            mensaje["seq"] = self._seq
            cuerpo = json.dumps(mensaje, ensure_ascii=False).encode("utf-8")
            self._salida.write(b"Content-Length: %d\r\n\r\n" % len(cuerpo))
            self._salida.write(cuerpo)
            self._salida.flush()

    def evento(self, nombre: str, cuerpo: Optional[dict] = None) -> None:
        self._manda({"type": "event", "event": nombre, "body": cuerpo or {}})

    def _responde(self, peticion: dict, cuerpo: Optional[dict] = None, *,
                  error: str = "") -> None:
        respuesta = {"type": "response", "request_seq": peticion["seq"],
                     "command": peticion["command"], "success": not error}
        if error:
            respuesta["message"] = error
        else:
            respuesta["body"] = cuerpo or {}
        self._manda(respuesta)

    # ------------------------------------------------------------------ #
    # el bucle
    # ------------------------------------------------------------------ #
    def atiende(self) -> int:
        """Lee peticiones hasta que el editor se va. Devuelve el código de
        salida del adaptador (no el del programa)."""
        while True:
            peticion = self._lee()
            if peticion is None:
                break
            if peticion.get("type") != "request":
                continue
            manejador = getattr(self, "_pide_" + peticion["command"], None)
            if manejador is None:
                self._responde(peticion, error=f"petición sin soporte: "
                                               f"{peticion['command']}")
                continue
            try:
                manejador(peticion, peticion.get("arguments") or {})
            except Exception as exc:  # noqa: BLE001 - se le dice al editor
                self._responde(peticion, error=f"{type(exc).__name__}: {exc}")
            if peticion["command"] == "disconnect":
                break
        self._corta()
        return 0

    def _corta(self) -> None:
        """Suelta al programa si estaba detenido, para que termine."""
        self._terminar = True
        if self._dep is not None:
            self._dep.pausa()
        self._seguir.set()
        if self._hilo is not None:
            self._hilo.join(timeout=5)

    # ------------------------------------------------------------------ #
    # arranque
    # ------------------------------------------------------------------ #
    def _pide_initialize(self, peticion, args) -> None:
        self._responde(peticion, {
            "supportsConfigurationDoneRequest": True,
            "supportsEvaluateForHovers": True,
            "supportsTerminateRequest": True,
            "supportsExceptionInfoRequest": True,
            "exceptionBreakpointFilters": [
                {"filter": nucleo.SIN_ATRAPAR, "default": True,
                 "label": "Errores que nadie atrapa",
                 "description": "Detenerse donde el programa va a terminar: "
                                "un error de ejecución, o un 'throw' sin "
                                "ningún 'catch' que lo espere."},
                {"filter": nucleo.TODOS, "default": False,
                 "label": "Todos los errores y 'throw'",
                 "description": "Detenerse en cuanto se lanza, aunque un "
                                "'catch' lo vaya a recibir."},
            ],
        })
        self.evento("initialized")

    def _pide_launch(self, peticion, args) -> None:
        programa = args.get("program")
        if not programa or not os.path.isfile(programa):
            self._responde(peticion, error=f"no existe el programa: {programa!r}")
            return
        # las banderas se comprueban AHORA: un error de escritura en
        # launch.json se dice al lanzar, no a mitad de la sesión.
        escritas = list(args.get("flags") or [])
        if escritas and self._lee_banderas is None:
            self._responde(peticion, error="este depurador se arrancó sin "
                           "lector de banderas: 'flags' no se admite")
            return
        if escritas:
            self._banderas = self._lee_banderas(programa, escritas)
        self._lanzamiento = args
        self._responde(peticion)

    def _pide_setBreakpoints(self, peticion, args) -> None:  # noqa: N802
        ruta = (args.get("source") or {}).get("path") or ""
        lineas = [int(p["line"]) for p in args.get("breakpoints") or []]
        self._puntos[ruta] = lineas
        if self._dep is not None:
            self._dep.pon_puntos(ruta, lineas)
        self._responde(peticion, {"breakpoints": [
            {"verified": True, "line": n} for n in lineas]})

    def _pide_setExceptionBreakpoints(self, peticion, args) -> None:  # noqa: N802
        filtros = list(args.get("filters") or [])
        self._errores = (nucleo.TODOS if nucleo.TODOS in filtros else
                         nucleo.SIN_ATRAPAR if nucleo.SIN_ATRAPAR in filtros
                         else None)
        if self._dep is not None:
            self._dep.para_en_errores(self._errores)
        self._responde(peticion, {"breakpoints": [{"verified": True}
                                                  for _ in filtros]})

    def _pide_exceptionInfo(self, peticion, args) -> None:  # noqa: N802
        error = self._dep.error if self._dep is not None else None
        if error is None:
            raise ValueError("el programa no está detenido por un error")
        codigo, descripcion = error
        self._responde(peticion, {
            "exceptionId": codigo, "description": descripcion,
            "breakMode": "always" if self._errores == nucleo.TODOS
                         else "unhandled"})

    def _pide_configurationDone(self, peticion, args) -> None:  # noqa: N802
        self._responde(peticion)
        self._hilo = threading.Thread(target=self._corre, name="programa",
                                      daemon=True)
        self._hilo.start()

    # ------------------------------------------------------------------ #
    # el programa (su propio hilo)
    # ------------------------------------------------------------------ #
    def _corre(self) -> None:
        codigo = 1
        previas = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = _Salida(self, "stdout"), _Salida(self, "stderr")
        try:
            codigo = self._compila_y_ejecuta()
        except _Terminar:
            codigo = 0
        except Exception as exc:  # noqa: BLE001 - fallo del compilador: se dice
            self.evento("output", {"category": "stderr", "output":
                                   f"error interno — {type(exc).__name__}: {exc}\n"})
            codigo = 6
        finally:
            sys.stdout, sys.stderr = previas
            self._dep = None
            self.evento("exited", {"exitCode": codigo})
            self.evento("terminated")
            self._fin.set()

    def _compila_y_ejecuta(self) -> int:
        from driver import CompileOptions, compile_source, execute

        programa = self._lanzamiento["program"]
        pedido = self._banderas
        resultado = compile_source(
            programa,
            CompileOptions(run="interpreter", **pedido["compilar"]),
            reporter=_Narrador(self))
        if not resultado.should_run:
            return resultado.status or 1
        self._dep = nucleo.Depurador(
            self._al_parar,
            parar_al_entrar=bool(self._lanzamiento.get("stopOnEntry")))
        self._dep.para_en_errores(self._errores)
        for ruta, lineas in self._puntos.items():
            self._dep.pon_puntos(ruta, lineas)
        argumentos = [programa, *map(str, self._lanzamiento.get("args") or [])]
        # la entrada estándar de este proceso es el canal del protocolo: si el
        # programa la leyera ('sistema.entrada') se comería los mensajes del
        # editor. Lee una entrada vacía.
        import io
        from . import intrinsics
        intrinsics.fijar_entrada(io.BytesIO(b""))
        try:
            return execute(resultado, depurador=self._dep, argumentos=argumentos,
                           **pedido["ejecutar"])
        finally:
            intrinsics.fijar_entrada(None)

    def _al_parar(self, dep: nucleo.Depurador, motivo: str) -> None:
        if self._terminar:
            raise _Terminar()
        self._marcos = dep.marcos()
        self._refs.clear()
        self._seguir.clear()
        cuerpo = {"reason": motivo, "threadId": _HILO, "allThreadsStopped": True}
        if dep.error is not None:
            cuerpo["description"] = f"Error: {dep.error[0]}"
            cuerpo["text"] = dep.error[1]
        self.evento("stopped", cuerpo)
        self._seguir.wait()
        self._marcos = []
        self._refs.clear()
        if self._terminar:
            raise _Terminar()

    # ------------------------------------------------------------------ #
    # mientras está detenido
    # ------------------------------------------------------------------ #
    def _pide_threads(self, peticion, args) -> None:
        self._responde(peticion, {"threads": [{"id": _HILO, "name": _NOMBRE_HILO}]})

    def _pide_stackTrace(self, peticion, args) -> None:  # noqa: N802
        dep = self._dep
        marcos = []
        for i, marco in enumerate(self._marcos):
            ruta = dep.ruta_de(marco.unidad) if dep is not None else ""
            marcos.append({
                "id": i + 1, "name": marco.nombre,
                "source": {"name": os.path.basename(ruta), "path": ruta},
                "line": marco.linea, "column": marco.columna,
            })
        self._responde(peticion, {"stackFrames": marcos, "totalFrames": len(marcos)})

    def _marco(self, numero: int) -> nucleo.Marco:
        if not 1 <= numero <= len(self._marcos):
            raise ValueError("ese marco ya no existe: el programa siguió")
        return self._marcos[numero - 1]

    def _ref(self, da_variables) -> int:
        numero = len(self._refs) + 1
        self._refs[numero] = da_variables
        return numero

    def _pide_scopes(self, peticion, args) -> None:
        marco = self._marco(int(args.get("frameId", 0)))
        dep = self._dep

        def propiedad():
            return [nucleo.Variable(v.nombre, v.propiedad, v.propiedad, None)
                    for v in dep.locales(marco)]

        self._responde(peticion, {"scopes": [
            {"name": "Locales", "presentationHint": "locals", "expensive": False,
             "variablesReference": self._ref(lambda: dep.locales(marco))},
            # de quién es cada valor: lo que un depurador genérico no enseña
            {"name": "Propiedad", "expensive": False,
             "variablesReference": self._ref(propiedad)},
            {"name": "Globales", "expensive": False,
             "variablesReference": self._ref(lambda: dep.globales(marco))},
        ]})

    def _a_dap(self, variable: nucleo.Variable) -> dict:
        contenido = variable.contenido
        return {
            "name": variable.nombre,
            "value": variable.valor,
            "type": variable.propiedad,
            "variablesReference": (self._ref(lambda: nucleo.hijos(contenido))
                                   if contenido is not None else 0),
        }

    def _pide_variables(self, peticion, args) -> None:
        da = self._refs.get(int(args.get("variablesReference", 0)))
        if da is None:
            raise ValueError("esa referencia ya no vale: el programa siguió")
        self._responde(peticion, {"variables": [self._a_dap(v) for v in da()]})

    def _pide_evaluate(self, peticion, args) -> None:
        marco = self._marco(int(args.get("frameId") or 1))
        nombre = str(args.get("expression", "")).strip()
        variable = self._dep.busca(marco, nombre) if self._dep else None
        if variable is None:
            raise ValueError(f"'{nombre}' no es un nombre a la vista (por ahora "
                             "solo se pueden mirar nombres, no expresiones)")
        self._responde(peticion, {
            "result": f"{variable.valor}  ({variable.propiedad})",
            "type": variable.propiedad,
            "variablesReference": self._a_dap(variable)["variablesReference"]})

    # ------------------------------------------------------------------ #
    # seguir
    # ------------------------------------------------------------------ #
    def _reanuda(self, peticion, cuerpo: Optional[dict] = None) -> None:
        self._responde(peticion, cuerpo)
        self._seguir.set()

    def _pide_continue(self, peticion, args) -> None:
        if self._dep is not None:
            self._dep.sigue()
        self._reanuda(peticion, {"allThreadsContinued": True})

    def _paso(self, peticion, args) -> None:
        if self._dep is not None:
            self._dep.paso(_PASOS[peticion["command"]])
        self._reanuda(peticion)

    _pide_next = _pide_stepIn = _pide_stepOut = _paso

    def _pide_pause(self, peticion, args) -> None:
        if self._dep is not None:
            self._dep.pausa()
        self._responde(peticion)

    def _pide_terminate(self, peticion, args) -> None:
        self._responde(peticion)
        self._corta()

    def _pide_disconnect(self, peticion, args) -> None:
        self._responde(peticion)


class _Narrador:
    """Lo que el compilador cuenta mientras compila, para la consola del
    editor: los diagnósticos van a ``stderr``, lo demás no hace falta."""

    def __init__(self, adaptador: Adaptador) -> None:
        self._adaptador = adaptador

    def _dice(self, texto: str) -> None:
        self._adaptador.evento("output", {"category": "stderr",
                                          "output": texto + "\n"})

    def info(self, message: str) -> None:
        pass

    def warn(self, message: str) -> None:
        self._dice(message)

    def diagnostics(self, title: str, errors: List) -> None:
        self._dice(f"=== {title} ({len(errors)}) ===")
        for error in errors:
            # la misma línea que escribe la CLI: código, mensaje y posición
            severidad = getattr(error, "severity", "critical")
            self._dice(f"  [{severidad}] {error.code}: {error.message}  "
                       f"({error.loc})")


def main(lee_banderas=None) -> int:
    """El adaptador sobre la entrada y la salida estándar del proceso.

    ``lee_banderas(programa, escritas) -> {"compilar": {...}, "ejecutar":
    {...}}`` traduce el ``flags`` de ``launch``; lanza ``ValueError`` con un
    mensaje para quien lo escribió."""
    return Adaptador(sys.stdin.buffer, sys.stdout.buffer,
                     lee_banderas=lee_banderas).atiende()


__all__ = ["Adaptador", "main"]
