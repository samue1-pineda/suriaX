"""La costura entre el compilador y quien lo invoca.

El *driver* compila; **no** decide cómo se muestra lo que va pasando. Esta
diferencia es la que permite que mañana ``suri run`` (suriniX) reutilice el
pipeline entero sin heredar ni una línea de la presentación en terminal: la
CLI pasa un reporter que imprime, un build system pasa uno que acumula, y un
test pasa el silencioso.

El protocolo es deliberadamente diminuto —tres verbos— porque es lo único que
el pipeline necesita decir hacia fuera. La diferencia entre ``info`` y ``warn``
NO es decorativa: separa lo que un script querría capturar (los artefactos que
se produjeron) de lo que se lee mientras se arregla algo. En una terminal eso
es stdout contra stderr, y confundirlos hace que ``> salida.txt`` se lleve los
avisos o los pierda. Todo lo demás (métricas, artefactos, tiempos) viaja en el
resultado, que es dato, no mensaje.
"""

from __future__ import annotations

from typing import List, Protocol


class Reporter(Protocol):
    """Lo que el driver necesita de su llamador."""

    def info(self, message: str) -> None:
        """Un hecho de la compilación (un volcado escrito, un resumen)."""

    def warn(self, message: str) -> None:
        """Algo que salió mal sin ser un diagnóstico con posición: una nota,
        una dependencia que falta, una unidad que no se pudo emitir."""

    def diagnostics(self, title: str, errors: List) -> None:
        """Un grupo de diagnósticos de una fase, ya acumulados."""


class SilentReporter:
    """No dice nada. Es el DEFECTO a propósito.

    Un consumidor que no pide reporter es uno que quiere el resultado, no la
    narración: que compilar escriba en stdout sin que nadie lo haya pedido es
    justo el acoplamiento del que este módulo saca al compilador.
    """

    def info(self, message: str) -> None:
        pass

    def warn(self, message: str) -> None:
        pass

    def diagnostics(self, title: str, errors: List) -> None:
        pass


__all__ = ["Reporter", "SilentReporter"]
