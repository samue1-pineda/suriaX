"""unit/volcados — los artefactos que se escriben a disco no se leen a medias.

Dos compilaciones en la misma carpeta (``make -j``, el editor y una terminal
a la vez) escriben los MISMOS ``.phir`` de librería en ``dumps/``. Antes el
archivo se vaciaba al abrirlo para escribir, y la otra compilación podía
leerlo vacío o cortado: ``schema_version 0`` y un fallo interno. Medido con
seis programas compilando a la vez, cuatro rondas: 10 de 24 fallaban; con la
escritura de ahora, ninguno.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def test_quien_lee_un_phir_mientras_otro_lo_escribe_lo_ve_entero():
    from config.dumps import _escribe_entero

    datos = bytes(range(256)) * 8192            # 2 MB: escribirlo tarda
    with tempfile.TemporaryDirectory(prefix="suriax-volcado-") as tmp:
        destino = os.path.join(tmp, "IO.stdp.phir")
        _escribe_entero(destino, datos)
        parar = threading.Event()
        errores = []

        def escribe():
            while not parar.is_set():
                try:
                    _escribe_entero(destino, datos)
                except Exception as exc:  # noqa: BLE001 - se cuenta abajo
                    errores.append(f"escribiendo: {exc!r}")
                    return

        def lee():
            for _ in range(150):
                try:
                    with open(destino, "rb") as fh:
                        leido = fh.read()
                except PermissionError:
                    continue            # Windows: el cambio de nombre en curso
                if leido != datos:
                    errores.append(f"leído a medias: {len(leido)} de {len(datos)} bytes")
                    return

        escritor = threading.Thread(target=escribe)
        lectores = [threading.Thread(target=lee) for _ in range(3)]
        escritor.start()
        for hilo in lectores:
            hilo.start()
        for hilo in lectores:
            hilo.join(timeout=120)
        parar.set()
        escritor.join(timeout=120)
        assert not errores, errores[:3]
        # y no deja temporales detrás
        assert os.listdir(tmp) == ["IO.stdp.phir"], os.listdir(tmp)
