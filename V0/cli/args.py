"""La definición de la línea de comandos: UNA sola fuente de las banderas.

Vivía dentro de ``main()``, mezclada con el despacho y con la compilación.
Separarla es lo que permite que otro front —``suri run`` de suriniX— consulte
o reutilice el mismo parser sin arrastrar el resto, y que una prueba pueda
verificar las banderas sin ejecutar nada.

``FLAGS.md`` se genera contra estos ``add_argument``, y un test de la suite
comprueba que no se queden sin documentar.
"""

from __future__ import annotations

import argparse


def _version() -> str:
    """La version del proyecto, leida de ``version.py`` (raiz del repo).

    Se lee y no se repite: es la misma fuente que usan ``CMakeLists.txt`` y la
    documentacion. Si el modulo no esta al alcance -alguien importo el parser
    sin el bootstrap de ``V0/main.py``- se dice que se desconoce, que es cierto,
    en vez de inventar un numero que luego alguien citaria.
    """
    try:
        from version import VERSION
    except ImportError:  # pragma: no cover - fuera del arbol del repositorio
        return "desconocida"
    return VERSION


#: A quién pertenece cada bandera. La regla, y no es cosmética:
#:
#:   COMPILADOR  hace falta para COMPILAR o para leer lo que la compilación
#:               produjo (un artefacto de una fase, un diagnóstico). Sin
#:               ella el compilador haría menos.
#:   SURINIX     es una comodidad ALREDEDOR de compilar: preparar el
#:               proyecto, medir, contar lo que pasó. Sin ella el compilador
#:               hace exactamente lo mismo.
#:
#: Existe para que la separación se pueda ejecutar: el día que ``surinix/``
#: sea su propio paquete, esta tabla dice qué se lleva y qué se queda — y
#: mientras tanto impide que una bandera nueva entre sin decidirlo (lo
#: comprueba ``test/unit/test_frontera_tooling.py``).
DUENO = {
    # --- del COMPILADOR: la compilación y sus artefactos ---
    "source": "compilador",
    "--run": "compilador",          # ejecutar es un target, no una comodidad
    "--stdin": "compilador",        # de dónde viene el fuente
    "--emit-hir": "compilador",
    "--hir-pretty": "compilador",
    "--hir-text": "compilador",
    "--emit-ast-json": "compilador",
    "--emit-tokens": "compilador",
    "--emit-stage": "compilador",
    "--dump-symbols-table": "compilador",
    "--emit-diagnostics": "compilador",   # el canal del editor: son SUS errores
    "--emit-index": "compilador",
    "--emit-lang-info": "compilador",     # la especificación del lenguaje
    "--emit-extensions": "compilador",    # el vocabulario que el proyecto añade
    "--trace-exec": "compilador",         # traza del intérprete: es su ejecución
    "--trace-memory": "compilador",

    # --- de SURINIX: alrededor de compilar ---
    "--version": "surinix",
    "--check": "surinix",           # dependencias de la MÁQUINA, no del programa
    "--init-config": "surinix",     # preparar el proyecto
    "--time": "surinix",            # medir
    "--debug": "surinix",           # contar lo que pasó, en un informe
}


def _motor(valor: str) -> str:
    """El valor de '--run': vacio (el del yaml), 'compiler' o 'interpreter'."""
    if valor not in ("", "compiler", "interpreter"):
        raise argparse.ArgumentTypeError(
            f"'--run {valor}': el motor es 'compiler' o 'interpreter'")
    return valor


def build_parser() -> argparse.ArgumentParser:
    """El parser de argumentos del compilador."""
    parser = argparse.ArgumentParser(
        prog="suriaX",
        description="Compilador suriaX (Pre-Alpha)",
    )
    parser.add_argument(
        "--version", action="version", version=f"suriaX {_version()}",
        help="imprime la version del compilador y termina",
    )
    parser.add_argument("source", nargs="?", help="archivo .srcx a procesar")
    parser.add_argument(
        "--check", action="store_true",
        help="verifica las dependencias del compilador",
    )
    parser.add_argument(
        "--init-config", action="store_true",
        help="genera un .suriaX_config.yaml por defecto",
    )
    parser.add_argument(
        "--emit-ast-json", nargs="?", const="", default=None, metavar="ARCHIVO",
        help="vuelca el AST-tipado a JSON"
             "ARCHIVO va a <dumps_dir>/<fuente>.ast.json",
    )
    parser.add_argument(
        "--emit-tokens", nargs="?", const="", default=None, metavar="ARCHIVO",
        help="vuelca el arreglo de tokens a texto sin ARCHIVO va a "
             "<dumps_dir>/<fuente>.tokens.txt",
    )
    parser.add_argument(
        "--emit-hir", nargs="?", const="", default=None, metavar="ARCHIVO",
        help="serializa el HIR tras una compilacion limpia sin "
             "ARCHIVO va a <dumps_dir>/<fuente>.phir + .phir.txt (requiere protobuf)",
    )
    parser.add_argument(
        "--dump-symbols-table", nargs="?", const="", default=None, metavar="ARCHIVO",
        dest="dump_symbols",
        help="vuelca la tabla de simbolos como diagrama de clases UML (Mermaid'classDiagram') "
             "sin ARCHIVO va a <dumps_dir>/<fuente>.symbols.mmd. ",
    )
    parser.add_argument(
        "--run", nargs="?", const="", default=None, metavar="MOTOR",
        type=_motor,
        help="emite el HIR y lo EJECUTA. Sin valor, en el motor que dice el "
             "'target' del .suriaX_config.yaml ('native' -> la VM compilada, "
             "'interp' -> el interprete); 'compiler' o 'interpreter' lo fuerza. "
             "Sin la VM construida, se interpreta con un aviso",
    )
    parser.add_argument(
        "--time", action="store_true", dest="show_times",
        help="tiempo de compilacion de cada fase(ms)",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="reporte GENERAL de depuracion en <dumps_dir>/<fuente>.debug.txt "
             "entorno, dependencias, metricas, tokens, AST, simbolos, HIR en "
             "texto, traza de ejecucion y tiempos",
    )
    parser.add_argument(
        "--hir-text", action="store_true", dest="hir_text",
        help="escribe la vista de TEXTO del HIR (<fuente>.phir.txt): el arbol "
             "crudo del protobuf, para depurar el FORMATO (que tag lleva que). "
             "Para leer el PROGRAMA usa --hir-pretty",
    )
    parser.add_argument(
        "--hir-pretty", nargs="?", const="", default=None, metavar="ARCHIVO",
        dest="hir_pretty",
        help="escribe la vista LEGIBLE del HIR (<fuente>.phir.pretty): una "
             "linea por sentencia, expresiones con su tipo resuelto y la "
             "posicion del fuente al margen. Es como se lee lo que le llego "
             "al interprete. Implicito con --debug",
    )
    parser.add_argument(
        "--trace-exec", action="store_true", dest="trace_exec",
        help="traza la ejecucion (llamadas/retornos anidados) al correr",
    )
    parser.add_argument(
        "--trace-memory", action="store_true", dest="trace_memory",
        help="traza las instrucciones de memoria (&, move, free) al correr",
    )
    parser.add_argument(
        "--emit-lang-info", action="store_true", dest="emit_lang_info",
        help="imprime en stdout la ESPECIFICACION del lenguaje en JSON "
             "(keywords por categoria, tokens, directivas, hooks, codigos de "
             "error) y termina. Fuente para el LSP/extension (no reimplementar "
             "el vocabulario a mano). No necesita un archivo fuente.",
    )
    parser.add_argument(
        "--emit-diagnostics", action="store_true", dest="emit_diagnostics",
        help="corre el frontend sobre el archivo y emite en stdout un JSON con "
             "TODOS los diagnosticos (codigo/mensaje/linea/columna/fase) y "
             "notas, Canal en vivo para el LSP. exit 0 aunque haya diagnosticos.",
    )
    parser.add_argument(
        "--emit-extensions", action="store_true", dest="emit_extensions",
        help="descubre las extensiones del proyecto (HTIMS: 'extends.srcx' + "
             "la lista 'extensions:' del yaml) y emite en stdout un JSON con "
             "los hooks declarados, sus firmas y las lineas de config "
             "equivalentes. NO importa ni ejecuta el .py del usuario. Sin "
             "archivo fuente usa el directorio actual como raiz.",
    )
    parser.add_argument(
        "--emit-stage", dest="emit_stage", metavar="FASE",
        help="vuelca UNA fase del pipeline (lexer, parser, ast, sem, hir) sin "
             "que el archivo tenga que traer '#test'. Mismo contenido que la "
             "directiva; lo consume el visualizador de la extension.",
    )
    parser.add_argument(
        "--emit-index", action="store_true", dest="emit_index",
        help="corre el frontend y emite en stdout un JSON con los diagnosticos "
             "(como --emit-diagnostics) MAS el indice del archivo: sus simbolos "
             "(tipo, firma, posicion, comentario, archivo de la libreria), cada "
             "uso de cada uno y los miembros de cada tipo. Canal del LSP para "
             "hover, ir a la definicion y completar; exit 0 aunque haya "
             "diagnosticos.",
    )
    parser.add_argument(
        "--stdin", action="store_true", dest="from_stdin",
        help="con --emit-diagnostics o --emit-index: lee el FUENTE de stdin en vez del disco. "
             "El argumento de archivo sigue siendo obligatorio y sigue anclando "
             "la resolucion de .libsrx, pero no hace falta que exista todavia. "
             "Permite a un editor analizar el buffer sin guardar.",
    )
    return parser


__all__ = ["DUENO", "build_parser"]
