"""Paquete ``config/``: configuración, dependencias y salidas del compilador.

API pública = la del orquestador (``compilerconfig.py``); el resto del
compilador importa desde aquí o desde el orquestador, nunca de los
submódulos directamente (así la distribución interna puede cambiar sin
tocar llamadores).
"""

from .compilerconfig import *  # noqa: F401,F403
from .compilerconfig import _print_report  # noqa: F401  (uso interno de main.py)
