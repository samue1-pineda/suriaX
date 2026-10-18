"""La configuración: variables de entorno, leídas UNA vez.

El servidor solo sabe leer variables de entorno, que es como las inyecta
cualquier plataforma; el ``.env`` es para correrlo sin exportar nada a mano.
Todo lo configurable está aquí para que la lista de ``.env.example`` y la del
README se puedan comparar contra un solo archivo.
"""

from __future__ import annotations

import os

_AQUI = os.path.abspath(os.path.dirname(__file__))
PLAYGROUND = os.path.dirname(_AQUI)
REPO = os.path.dirname(PLAYGROUND)
ESTATICOS = os.path.join(PLAYGROUND, "static")
WEB_MAIN = os.path.join(REPO, "web", "main.ts")
#: volcados del backend web: su carpeta de artefactos generados.
WEB_VOLCADOS = os.path.join(REPO, ".web")

#: versión del contrato HTTP. Sube cuando un campo cambia de significado o
#: desaparece; añadir campos no la sube.
API = "1"


def cargar_env(ruta: str) -> None:
    """Lee un ``.env`` y lo vuelca en el entorno, SIN pisar lo que ya está.

    Railway (y cualquier PaaS) inyecta la configuración como variables de
    entorno, así que el servidor solo sabe leer variables. Este archivo es
    para el otro caso: correrlo en cualquier sitio sin exportar nada a mano.

    Lo que ya viene del entorno GANA: si mañana esto corre en una plataforma
    que define ``PORT``, un ``.env`` olvidado en el repositorio no puede
    cambiar el puerto donde escucha.

    Formato mínimo a propósito —``CLAVE=valor``, ``#`` comenta, comillas
    opcionales— y sin dependencias: un cargador de ``.env`` completo es una
    librería, y aquí no hay nada que justifique una.
    """
    if not os.path.isfile(ruta):
        return
    with open(ruta, encoding="utf-8") as fh:
        for linea in fh:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, _, valor = linea.partition("=")
            clave = clave.strip()
            valor = valor.strip().strip("'\"")
            if clave and clave not in os.environ:
                os.environ[clave] = valor


def _entero(clave: str, defecto: int, minimo: int) -> int:
    """Una variable entera. Un valor ilegible NO arranca con el de defecto:
    quien la puso quería otra cosa, y enterarse al arrancar es más barato que
    enterarse en producción."""
    bruto = os.environ.get(clave)
    if bruto is None or not bruto.strip():
        return defecto
    try:
        valor = int(bruto)
    except ValueError:
        raise SystemExit(f"{clave}={bruto!r} no es un número entero") from None
    if valor < minimo:
        raise SystemExit(f"{clave}={valor} no puede ser menor que {minimo}")
    return valor


cargar_env(os.path.join(REPO, ".env"))

#: dónde escucha. Por defecto SOLO esta máquina: publicar el servidor en la
#: red es una decisión de quien despliega (``HOST=0.0.0.0``), no un descuido.
HOST = os.environ.get("HOST", "").strip() or "127.0.0.1"
PUERTO = _entero("PORT", 8000, 0)

#: un fuente más largo que esto no se compila: el servidor es público y
#: compilar es trabajo real. No es una medida de seguridad, es una cota.
MAX_FUENTE = _entero("SURIAX_MAX_SOURCE_BYTES", 64 * 1024, 1)

#: cuánto puede tardar el backend web en producir sus artefactos.
WEB_TIEMPO = _entero("SURIAX_WEB_TIMEOUT", 120, 1)

#: cuántos procesos del backend web pueden correr a la vez. Cada uno es un
#: node entero; sin cota, N peticiones simultáneas son N procesos.
WEB_SIMULTANEOS = _entero("SURIAX_WEB_CONCURRENCY", 2, 1)

#: segundos que se espera a que un cliente termine de enviar su petición.
#: Sin cota, una conexión que no envía nada ocupa un hilo para siempre.
ESPERA_CLIENTE = _entero("SURIAX_CLIENT_TIMEOUT", 30, 1)

#: origen al que se le permite llamar a la API desde OTRO sitio (CORS). Vacío
#: —el valor por defecto— significa que solo la propia página puede.
ORIGEN_PERMITIDO = os.environ.get("SURIAX_CORS_ORIGIN", "").strip()
