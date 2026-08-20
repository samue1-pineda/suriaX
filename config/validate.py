"""Validación del ``.suriaX_config.yaml`` contra el esquema del proyecto.

El esquema NO se escribe aquí: se **deriva** de :func:`yaml_config.default_config`,
que ya es la definición del formato. Dos listas de claves acabarían
divergiendo, y la que se quedara vieja rechazaría configuraciones válidas —
justo el fallo que esta validación existe para evitar. Lo único que se
declara a mano es lo que un valor por defecto no puede expresar: el conjunto
de valores admitidos de una clave enumerada (:data:`ENUMERADOS`).

Reglas, en el orden en que se comprueban:

1. la raíz tiene que ser un mapa (``CFG003``);
2. cada clave tiene que existir en el esquema (``CFG004``) — es lo que
   atrapa el typo silencioso, ``libsrx_path`` por ``libsrx_paths``;
3. cada valor tiene que ser del tipo del defecto (``CFG005``);
4. una clave enumerada solo admite sus valores (``CFG006``).

Nada de esto lanza: se devuelve la lista de diagnósticos y quien llama
decide. Es el mismo contrato que el resto del compilador.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .errors import CFG003, CFG004, CFG005, CFG006, ConfigError

#: Claves cuyo valor pertenece a un conjunto cerrado. La ruta va con puntos,
#: igual que se lee el yaml anidado.
ENUMERADOS: Dict[str, Tuple[str, ...]] = {
    "target": ("native", "wasm", "interp"),
    "optimization": ("O0", "O1", "O2", "O3"),
    "platform": ("win32", "linux", "macos", "unknown"),
    "codegen.artifact": ("o", "exe", "wasm"),
    "visualization.format": ("text", "json", "dot"),
}

#: Claves internas: las pone el compilador en memoria (valor ya resuelto), no
#: el usuario. Empiezan por '_' igual que ``_root``; si aparecen en un yaml se
#: ignoran sin protestar, porque un volcado de la config las puede incluir.
_INTERNAS = ("_",)


def _tipo_legible(valor: Any) -> str:
    return {dict: "un mapa", list: "una lista", str: "una cadena",
            bool: "un booleano", int: "un entero",
            float: "un número"}.get(type(valor), type(valor).__name__)


def _compatible(valor: Any, defecto: Any) -> bool:
    """¿``valor`` sirve donde el esquema espera algo como ``defecto``?

    Se compara por FAMILIA, no por tipo exacto: un ``int`` vale donde el
    defecto es ``float`` (nadie escribe ``1.0`` para un tamaño de pila), y
    una cadena vacía vale donde el defecto es una cadena.  ``bool`` se trata
    aparte porque en Python es subclase de ``int`` y ``enabled: 1`` no
    debería colarse como booleano.
    """
    if isinstance(defecto, bool):
        return isinstance(valor, bool)
    if isinstance(defecto, (int, float)):
        return isinstance(valor, (int, float)) and not isinstance(valor, bool)
    if isinstance(defecto, dict):
        return isinstance(valor, dict)
    if isinstance(defecto, list):
        return isinstance(valor, list)
    if isinstance(defecto, str):
        return isinstance(valor, str)
    return True  # el defecto es None: la clave admite cualquier cosa


def _sugerencia(clave: str, conocidas: Any) -> str:
    """La clave conocida más parecida, si la hay: el typo se arregla solo
    cuando el mensaje dice qué se quiso escribir."""
    import difflib
    cercanas = difflib.get_close_matches(clave, list(conocidas), n=1, cutoff=0.7)
    return f" — ¿querías decir '{cercanas[0]}'?" if cercanas else ""


def _validar_mapa(datos: dict, esquema: dict, ruta: str,
                  archivo: Optional[str], errores: List[ConfigError]) -> None:
    for clave, valor in datos.items():
        if not isinstance(clave, str) or clave.startswith(_INTERNAS):
            continue
        completa = f"{ruta}.{clave}" if ruta else clave
        if clave not in esquema:
            errores.append(ConfigError(
                CFG004,
                f"clave desconocida '{completa}' en la configuración"
                f"{_sugerencia(clave, esquema)}",
                file=archivo,
            ))
            continue
        defecto = esquema[clave]
        if not _compatible(valor, defecto):
            errores.append(ConfigError(
                CFG005,
                f"'{completa}' debe ser {_tipo_legible(defecto)} y se "
                f"encontró {_tipo_legible(valor)} ({valor!r})",
                file=archivo,
            ))
            continue
        admitidos = ENUMERADOS.get(completa)
        if admitidos is not None and valor not in admitidos:
            errores.append(ConfigError(
                CFG006,
                f"'{completa}' no admite {valor!r}; los valores válidos son: "
                f"{', '.join(admitidos)}",
                file=archivo,
            ))
            continue
        if isinstance(defecto, dict) and isinstance(valor, dict):
            _validar_mapa(valor, defecto, completa, archivo, errores)


def validate(datos: Any, esquema: dict, *,
             archivo: Optional[str] = None) -> List[ConfigError]:
    """Diagnósticos de ``datos`` contra ``esquema``. Lista vacía = todo bien."""
    errores: List[ConfigError] = []
    if not isinstance(datos, dict):
        errores.append(ConfigError(
            CFG003,
            f"la raíz del archivo debe ser un mapa 'clave: valor' y se "
            f"encontró {_tipo_legible(datos)}",
            file=archivo,
        ))
        return errores
    _validar_mapa(datos, esquema, "", archivo, errores)
    return errores


__all__ = ["ENUMERADOS", "validate"]
