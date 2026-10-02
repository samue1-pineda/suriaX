"""Entrega del ``.phir`` al intérprete, y cierre del reporte de depuración.

Compilar y ejecutar son dos cosas, y estaban en la misma función. Separarlas
es lo que permite que ``suri run`` decida por su cuenta —compilar sin
ejecutar, ejecutar un ``.phir`` ya compilado, o compilar y ejecutar con otro
runtime— sin tocar el pipeline.

El reporte de ``--debug`` se cierra AQUÍ y no en el pipeline por una razón
concreta: incluye la traza de ejecución, que todavía no existe cuando la
compilación termina.
"""

from __future__ import annotations

import os
import time
from typing import Optional

from error_handler.InternalCompilerError import InternalCompilerError

from .options import CompileResult
from .reporting import Reporter, SilentReporter


def execute(result: CompileResult, *,
            trace_exec: bool = False, trace_memory: bool = False,
            reporter: Optional[Reporter] = None,
            argumentos: Optional[list] = None) -> int:
    """Ejecuta el ``.phir`` de ``result`` EN PROCESO y devuelve su código.

    En proceso —sin subproceso ni reparseo— porque el HIR ya está en memoria
    del lado del compilador y volver a leerlo solo añadiría latencia. Con
    ``--debug`` la traza se ACUMULA en ``result.trace_events`` para el reporte
    en vez de imprimirse.
    """
    reporter = reporter or SilentReporter()
    if not result.should_run or result.phir_path is None:
        return result.status

    if result.motor == "compiler":
        if trace_exec or trace_memory:
            reporter.warn("--trace-exec y --trace-memory son del interprete: "
                          "se ejecuta en el interprete")
        else:
            codigo = _en_la_vm(result, reporter, argumentos)
            if codigo is not None:
                return codigo

    t = time.perf_counter()
    from runtime.interpreter import interpreter as interp
    from runtime.interpreter import loader as interp_loader

    icfg = dict(result.config.get("interpreter") or {})
    icfg.setdefault("entry", "main")
    if trace_memory:
        icfg["trace_memory"] = True
    if trace_exec:
        icfg["trace_exec"] = True
    # lo que ve 'sistema.argumento(i)': el 0 es el archivo que se ejecuta
    icfg["argumentos"] = list(argumentos) if argumentos else [result.path]
    exit_code = result.status
    try:
        fase = "carga del HIR"
        image = interp_loader.load_image(result.phir_path)
        fase = "ligado de #extern cpp"
        _ligar_extern_cpp(image, result, reporter)
        fase = "interprete"
        # los errores DEL PROGRAMA (RTxxx, throw sin capturar) los atrapa
        # 'interp.run' y devuelve 70; lo que llegue aquí es del compilador.
        exit_code = interp.run(image, {"interpreter": icfg},
                               events=result.trace_events)
    except Exception as exc:  # noqa: BLE001 - se reporta como ICE, nunca se traga
        # Incluye HIRLoadError: el .phir lo acaba de escribir el propio
        # compilador, así que si su lector lo rechaza el fallo es del emisor
        # o del lector — no una "dependencia faltante" (exit 3), que es lo
        # que se decía antes.
        raise InternalCompilerError.desde(exc, phase=fase,
                                          file=result.path) from exc
    result.times["interprete"] = time.perf_counter() - t
    result.status = exit_code
    return exit_code


def binario_de_la_vm() -> Optional[str]:
    """``suriax-hir``: el de ``SURIAX_HIR_BIN`` o el de ``build/bin``."""
    escrito = os.environ.get("SURIAX_HIR_BIN")
    if escrito:
        for ruta in (escrito, escrito + ".exe"):
            if os.path.isfile(ruta):
                return ruta
        return None
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for nombre in ("suriax-hir", "suriax-hir.exe"):
        ruta = os.path.join(raiz, "build", "bin", nombre)
        if os.path.isfile(ruta):
            return ruta
    return None


def _en_la_vm(result: CompileResult, reporter: Reporter,
              argumentos: Optional[list]) -> Optional[int]:
    """Ejecuta el ``.phir`` en la VM (``suriax-hir``) y devuelve su codigo.

    ``None`` = no se pudo, y se interpreta: la VM no esta construida o el
    MIR no cubre el programa. Se AVISA siempre —ejecutar en otro motor del
    que se pidio no puede pasar en silencio—; la semantica es la misma, y es
    lo que comprueba el diferencial.
    """
    import subprocess

    # los hooks de las extensiones del proyecto (HTIMS) los implementa Python:
    # solo el interprete puede llamarlos
    extensiones = result.config.get("_extensions")
    if extensiones is not None and (extensiones.modules or extensiones.hooks):
        reporter.info("el proyecto declara extensiones (HTIMS): las ejecuta el "
                      "interprete")
        return None
    binario = binario_de_la_vm()
    if binario is None:
        reporter.warn("la VM (suriax-hir) no esta construida: se ejecuta en el "
                      "interprete. Para compilar: cmake -S . -B build && "
                      "cmake --build build --target suriax-hir (o --run "
                      "interpreter para no ver este aviso)")
        return None
    comprobacion = subprocess.run([binario, result.phir_path, "--check-mir"],
                                  capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")
    if comprobacion.returncode != 0:
        motivo = (comprobacion.stderr.strip().splitlines() or ["?"])[-1].strip()
        reporter.warn(f"la VM no cubre este programa ({motivo}): se ejecuta en "
                      "el interprete")
        return None
    # lo que el compilador ya escribio sale ANTES que lo del programa: la VM
    # escribe directo en el descriptor, sin pasar por el buffer de Python
    import sys
    sys.stdout.flush()
    sys.stderr.flush()
    t = time.perf_counter()
    orden = [binario, result.phir_path, "--run", "--quiet",
             "--arg0", (argumentos or [result.path])[0],
             "--", *(argumentos or [result.path])[1:]]
    codigo = subprocess.run(orden).returncode
    result.times["vm"] = time.perf_counter() - t
    result.status = codigo
    return codigo


def _ligar_extern_cpp(image, result: CompileResult, reporter: Reporter) -> None:
    """Compila los ``#extern cpp`` del programa y liga sus prototipos.

    Va AQUÍ y no en el pipeline porque es parte de preparar la EJECUCIÓN, no
    de compilar: un programa que solo emite su HIR no necesita que exista un
    compilador de C++ en la máquina.

    Un fallo se avisa y no detiene: quizá los prototipos los cumpla el host
    en Python, y si de verdad falta uno el intérprete lo dirá al llamarlo,
    con el nombre y la posición — que es mejor diagnóstico que este.
    """
    from runtime import extern_cpp

    dumps = os.path.dirname(os.path.abspath(result.phir_path))
    report = extern_cpp.bind(image, dumps_dir=dumps, config=result.config)
    if report.error is not None:
        reporter.warn(f"#extern cpp: {report.error}")
        return
    if report.ligados:
        reporter.info(f"#extern cpp: {len(report.ligados)} prototipo(s) "
                      f"ligado(s) a C++ ({', '.join(report.ligados)})")
    for nombre, motivo in report.omitidos:
        reporter.warn(f"#extern cpp: '{nombre}' no se pudo ligar — {motivo}")


def finish_report(result: CompileResult) -> Optional[str]:
    """Cierra el reporte de ``--debug`` (traza + tiempos) y lo escribe.

    Devuelve la ruta escrita, o ``None`` si no se pidió el reporte.
    """
    report = result.debug_report
    if report is None:
        return None
    report.diagnostics("ERRORES LEXICOS", result.lexer_errors)
    report.trace(result.trace_events)
    report.timings(result.times)
    result.report_file = report.write()
    return result.report_file


__all__ = ["execute", "finish_report"]
