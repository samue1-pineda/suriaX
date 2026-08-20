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
        "--run", action="store_true",
        help="fuerza el target 'interp': emite el HIR y lo ejecuta con el "
             "'target: interp' en .suriaX_config.yaml",
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
        "--stdin", action="store_true", dest="from_stdin",
        help="con --emit-diagnostics: lee el FUENTE de stdin en vez del disco. "
             "El argumento de archivo sigue siendo obligatorio y sigue anclando "
             "la resolucion de .libsrx, pero no hace falta que exista todavia. "
             "Permite a un editor analizar el buffer sin guardar.",
    )
    return parser


__all__ = ["build_parser"]
