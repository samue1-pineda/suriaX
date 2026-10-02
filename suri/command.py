"""``suri [archivo.srcx] [banderas]`` -> el entrypoint real del compilador.

Reenvía a ``V0/main.py`` sin tocar los argumentos salvo por una comodidad que
la raíz del repositorio ya aplicaba: **compilar un fuente sin decir qué hacer
con él ejecuta el programa**. Es lo que espera quien escribe ``suri hola.srcx``
en una terminal, y es exactamente lo mismo que hace ``python main.py``; el
comportamiento no se bifurca por la vía de entrada.

Encontrar el compilador es todo el trabajo real de este módulo. Se busca, en
orden:

1. ``SURIAX_ROOT`` — para apuntar a un árbol concreto sin instalar nada;
2. la raíz del repositorio, subiendo desde este archivo (uso desde el clon);
3. el directorio actual, por si ``suri`` se instaló y se corre dentro de un
   proyecto que lleva su propio ``V0/``.

Si no aparece, se dice DÓNDE se buscó: un "no encontrado" sin las rutas
probadas obliga a adivinar, y ese es justo el error que el compilador evita en
sus propios diagnósticos de librerías.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import List, Optional

#: Subcomandos que NO ejecutan un fuente: piden información o preparan el
#: proyecto. Añadirles '--run' no tendría sentido.
#: Es la misma lista que aplica el atajo de la raíz, y por el mismo motivo.
_SIN_RUN = {"--check", "--init-config", "--emit-extensions",
            "--version", "-h", "--help"}

#: Variable de entorno que fija la raíz del compilador.
ENV_ROOT = "SURIAX_ROOT"


def _candidatas() -> List[str]:
    """Las raíces donde buscar ``V0/main.py``, en orden de precedencia."""
    rutas: List[str] = []
    desde_entorno = os.environ.get(ENV_ROOT)
    if desde_entorno:
        rutas.append(os.path.abspath(desde_entorno))
    # este archivo vive en '<raiz>/suri/command.py'
    rutas.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    rutas.append(os.path.abspath(os.getcwd()))
    vistas: set = set()
    return [r for r in rutas if not (r in vistas or vistas.add(r))]


def find_root() -> Optional[str]:
    """La raíz del compilador, o ``None`` si ninguna candidata la contiene."""
    for raiz in _candidatas():
        if os.path.isfile(os.path.join(raiz, "V0", "main.py")):
            return raiz
    return None


def forward(argv: List[str]) -> List[str]:
    """Los argumentos tal cual, con ``--run`` si se pidió compilar y nada más.

    ``argv`` NO incluye el nombre del programa.
    """
    # lo que va despues de '--' es del PROGRAMA: no cuenta, y el '--run' va
    # antes (si no, el programa lo recibia como un argumento suyo)
    corte = argv.index("--") if "--" in argv else len(argv)
    propios = argv[:corte]
    hay_fuente = any(not a.startswith("-") for a in propios)
    es_subcomando = any(a in _SIN_RUN for a in propios)
    pide_run = any(a == "--run" or a.startswith("--run=") for a in propios)
    if hay_fuente and not es_subcomando and not pide_run:
        return [*argv[:corte], "--run", *argv[corte:]]
    return list(argv)


def _cargar(entry: str):
    """Carga ``V0/main.py`` como módulo sin importarlo por nombre.

    Por ruta y no por ``import``: el compilador no está publicado como paquete
    instalable y su ``main.py`` monta su propio ``sys.path``. Es el mismo
    mecanismo que usa el atajo de la raíz del repositorio.
    """
    spec = importlib.util.spec_from_file_location("suriax_v0_entry", entry)
    if spec is None or spec.loader is None:  # pragma: no cover - ruta rota
        raise ImportError(f"no se pudo cargar {entry}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: Optional[List[str]] = None) -> int:
    """Punto de entrada del comando. Devuelve el código de salida."""
    args = list(sys.argv[1:] if argv is None else argv)
    raiz = find_root()
    if raiz is None:
        probadas = "\n  ".join(_candidatas())
        print(
            "no se encontró el compilador (V0/main.py). Rutas probadas:\n  "
            f"{probadas}\n"
            f"Apunta a tu copia con {ENV_ROOT}=/ruta/al/repositorio, o corre "
            "'suri' desde el directorio del proyecto.",
            file=sys.stderr)
        return 2
    entry = os.path.join(raiz, "V0", "main.py")
    return _cargar(entry).main(["V0/main.py", *forward(args)])


if __name__ == "__main__":  # pragma: no cover - entrada del comando
    raise SystemExit(main())
