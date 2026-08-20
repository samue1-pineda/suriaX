#!/usr/bin/env python3
"""Entrypoint del compilador suriaX.

Este archivo hace **dos** cosas y ninguna más: preparar el entorno de
importación y ceder el control a la línea de comandos. Todo lo demás vive
separado, y la frontera es deliberada:

    cli/      qué se pide, cómo se muestra, con qué código se termina
    driver/   el compilador COMO LIBRERÍA: compila y ejecuta sin terminal

Antes las dos mitades estaban aquí, en una función de trescientas líneas que
cargaba la configuración, compilaba, escribía volcados, imprimía el progreso,
ejecutaba el programa y decidía el código de salida. Eso hacía que la ÚNICA
manera de compilar fuera pasar por el ``argparse``: cuando suriniX traiga
``suri run --args`` tendría que haber invocado a este proceso o reimplementar
el pipeline. Ahora reutiliza ``driver`` directamente y pone su propia CLI.

ejemplos de uso:
    python V0/main.py archivo.srcx
    python V0/main.py archivo.srcx --emit-ast-json --emit-tokens
    python V0/main.py --check          # verifica dependencias y configuracion
    python V0/main.py --init-config    # genera .suriaX_config.yaml
"""

from __future__ import annotations

import os
import sys
import time

#: Marca de tiempo lo más cerca posible del arranque del proceso. Todo lo que
#: pasa ANTES de la primera fase —el arranque del intérprete de Python y la
#: importación del compilador— es tiempo real que ``--time`` no medía: el
#: TOTAL sumaba solo las fases y daba un tercio del reloj de pared, que es
#: justo el número equivocado cuando alguien mide para saber por qué tarda.
ARRANQUE = time.perf_counter()

# Se agregan las rutas del paquete V0 y de la raíz del repositorio para que los
# módulos puedan importarse tanto ejecutando este archivo desde la carpeta V0
# como desde la raíz del proyecto.
_V0_ROOT = os.path.abspath(os.path.dirname(__file__))
_REPO_ROOT = os.path.dirname(_V0_ROOT)
for _p in (_V0_ROOT, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# El parser recorre las expresiones de forma recursiva: para que un programa
# con anidamiento extremo no rompa el proceso con un RecursionError, se sube el
# límite de Python y el parser lo convierte en un diagnóstico controlado
# (ExpressionTooDeepError).
sys.setrecursionlimit(10_000)

from cli import main  # noqa: E402  (después del bootstrap de sys.path)

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
