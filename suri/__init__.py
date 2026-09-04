"""El comando ``suri``: el compilador desde la terminal, sin rutas.

Es un ENVOLTORIO, no una segunda línea de comandos. Las banderas son las del
compilador y salen de un solo sitio (``V0/cli/args.build_parser``); aquí no se
declara ninguna, no se traduce ninguna y no se inventa ninguna. Ese era el
motivo por el que el parser se separó de ``main()``, escrito en su propio
docstring: *"permite que otro front —``suri run``— consulte o reutilice el
mismo parser sin arrastrar el resto"*.

Lo único que aporta es lo que un envoltorio puede aportar: encontrar el
compilador esté donde esté (instalado o desde el repositorio) y no obligar a
escribir ``python V0/main.py`` cada vez.
"""

from .command import main

__all__ = ["main"]
