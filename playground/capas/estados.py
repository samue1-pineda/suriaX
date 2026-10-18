"""Los cuatro estados con los que responde un proveedor.

Un proveedor es quien hace el trabajo detrás de un adaptador: el compilador o
el target web. Antes la respuesta era un ``ok`` booleano y un motivo, y con
eso no se podía distinguir "tu programa tiene un error" de "al compilador se
le rompió algo": las dos cosas salían como un panel sin artefacto.

Son cuatro porque piden acciones distintas a quien lo lee:

    ok                  nada que hacer
    error_del_programa  lo arregla quien escribió el programa
    no_disponible       lo arregla quien instaló el entorno (falta node, falta
                        protobuf) o no había nada que procesar
    error_interno       lo arregla quien mantiene el compilador

Los valores son parte del contrato público (``docs`` del playground y
``openapi``): no se renombran sin subir la versión de la API.
"""

from __future__ import annotations

OK = "ok"
ERROR_DEL_PROGRAMA = "error_del_programa"
NO_DISPONIBLE = "no_disponible"
ERROR_INTERNO = "error_interno"

#: de más grave a menos: el estado de la respuesta entera es el peor de los
#: de sus proveedores.
_GRAVEDAD = (ERROR_INTERNO, ERROR_DEL_PROGRAMA, NO_DISPONIBLE, OK)


def proveedor(estado: str, detalle: str = "") -> dict:
    """Lo que un adaptador cuenta de su proveedor en una respuesta."""
    return {"status": estado, "detail": detalle}


def sin_rutas(texto: str, **otras: str) -> str:
    """``texto`` sin las rutas de esta máquina: lo que se puede publicar.

    La raíz del repositorio pasa a ser ``<repo>``; ``otras`` son rutas
    adicionales con el nombre que las sustituye (``tmp="C:/..."``). Es parte
    del vocabulario común porque los dos adaptadores publican texto que no
    escribieron ellos.
    """
    from . import config
    for nombre, ruta in (*otras.items(), ("repo", config.REPO)):
        for variante in {ruta, ruta.replace("\\", "/"),
                         ruta.replace("/", "\\")}:
            texto = texto.replace(variante, f"<{nombre}>")
    return texto


def peor(*estados: str) -> str:
    """El estado más grave de la lista."""
    for estado in _GRAVEDAD:
        if estado in estados:
            return estado
    return OK
