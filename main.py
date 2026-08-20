#!/usr/bin/env python3
""" 
atajo en la raiz para realizar "python main.py archivo.srcx"

algunos comandos son:

``python main.py archivo.srcx``: compila y ejecuta con la configuracion establecida en suriaX_config.yaml
``python main.py archivo.srcx --emit--hir``: emite el hir pero no compila

la logica real esta en "V0/main.py"
"""



from __future__ import annotations

import importlib.util
import os
import sys

_ROOT = os.path.abspath(os.path.dirname(__file__))
_V0_ROOT = os.path.join(_ROOT, "V0")
_V0_MAIN = os.path.join(_V0_ROOT, "main.py")

#Subcomandos que no deben ejecutar un archivo fuente
#('--emit-extensions' acepta un fuente para anclar la raiz del proyecto, pero
# consulta las extensiones: no compila ni ejecuta nada)
_NON_RUN_FLAGS = {"--check", "--init-config", "--emit-extensions",
                  "-h", "--help"}


def _forward_argv(argv: list[str]) -> list[str]:
    """
    Reenvía los argumentos al entrypoint real(V0/main.py) y añade ``--run`` por defecto
    cuando el usuario está compilando y ejecutando un archivo fuente
    """
    args = argv[1:]
    has_source = any(not a.startswith("-") for a in args)
    is_subcommand = any(a in _NON_RUN_FLAGS for a in args)
    if has_source and not is_subcommand and "--run" not in args:
        args = args + ["--run"]
    return ["V0/main.py", *args]


def _load_v0_main():#carga el entry point real
    spec = importlib.util.spec_from_file_location("suriax_v0_entry", _V0_MAIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str]) -> int:
    if not os.path.isfile(_V0_MAIN):
        print(f"no se encontró el entrypoint del compilador: {_V0_MAIN}",
              file=sys.stderr)
        return 2
    return _load_v0_main().main(_forward_argv(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
