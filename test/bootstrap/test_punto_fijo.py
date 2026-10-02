"""bootstrap/punto_fijo — la V1 se compila a sí misma y da LO MISMO.

Es la meta del bootstrap, en las tres etapas clásicas:

1. la V0 compila la V1 (``src/``): ``A``, una unidad ``.phir`` por módulo y
   por librería;
2. ``A``, corriendo en la VM, compila el MISMO fuente: ``B``. ``B == A``
   byte a byte dice que la V1 hace lo que hace la V0;
3. ``B`` —la V1 compilada por sí misma— compila otra vez: ``C``. ``C == B``
   dice que el compilador autocompilado es estable: el punto fijo.

Cada etapa compara TODAS las unidades (la V1 y cada librería que importa) y
la lista de unidades. La V1 pasa del límite de pasos por defecto de la VM, así
que corre con ``--pasos 0``; ``--memoria`` deja medido su pico de memoria y que
no fuga nada.

Cada etapa tiene un límite de tiempo: ``SURIAX_LIMITE_ETAPA`` (segundos; 600
por defecto, unas 50 veces lo que tarda en una VM Release). Con una VM de
SANITIZADOR la prueba se OMITE: con ASan en Debug cada etapa tarda unas 2 h
(medido: 7005 s; con optimización, 776 s). El punto fijo bajo ASan se corre a
mano en cada hito (decisión del mantenedor); ver ``audit/pruebas.md``.
"""

from __future__ import annotations

import os
import re
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)

sys.path.insert(0, os.path.dirname(_AQUI))

from helpers import omitir, vm_sanitizada  # noqa: E402
from test_bootstrap_v1 import _STDLIB, _correr, _igual, _v1  # noqa: E402

#: el límite de cada etapa, en segundos
_LIMITE = float(os.environ.get("SURIAX_LIMITE_ETAPA", "600"))


def _etapa(vm: str, compilador: str, salida: str, cwd: str) -> str:
    """Corre el compilador ``compilador`` (un .phir) sobre ``main.srcx`` y deja
    sus unidades en la carpeta ``salida``. Devuelve el informe de memoria."""
    os.makedirs(os.path.join(cwd, salida), exist_ok=True)
    hecho = _correr([vm, compilador, "--run", "--quiet", "--pasos", "0", "--memoria",
                     "--", "main.srcx", os.path.join(salida, "main.srcx.phir"),
                     "--stdlib", _STDLIB], cwd, _LIMITE)
    assert hecho.returncode == 0, (
        f"'{compilador}' no se compila a sí mismo:\n{hecho.stdout[-2000:]}{hecho.stderr[-2000:]}")
    return hecho.stderr


def _iguales(antes: str, despues: str, cwd: str, vm: str) -> None:
    unidades = sorted(os.listdir(os.path.join(cwd, antes)))
    otras = sorted(os.listdir(os.path.join(cwd, despues)))
    assert unidades == otras, f"otras unidades.\n  {antes}: {unidades}\n  {despues}: {otras}"
    for unidad in unidades:
        _igual(unidad, os.path.join(antes, unidad), os.path.join(despues, unidad), vm, cwd)


def test_la_v1_compilada_por_si_misma_da_lo_mismo():
    tmp, vm = _v1()                     # etapa 1: 'dumps/' es A (la V0)
    if vm_sanitizada(vm):
        omitir(f"'{vm}' es la VM de un sanitizador: el punto fijo tarda unas 2 h "
               "por etapa (ASan en Debug). Se corre a mano en cada hito, con "
               "SURIAX_LIMITE_ETAPA alto")
    informe = _etapa(vm, os.path.join("dumps", "main.srcx.phir"), "etapa2", tmp)
    _iguales("dumps", "etapa2", tmp, vm)                 # B == A
    # sin fugas: todo objeto y toda cadena que crea la V1 se libera
    vivos = re.search(r"objetos creados \d+, liberados \d+, vivos al terminar (\d+)", informe)
    assert vivos is not None and vivos.group(1) == "0", informe[-600:]
    _etapa(vm, os.path.join("etapa2", "main.srcx.phir"), "etapa3", tmp)
    _iguales("etapa2", "etapa3", tmp, vm)                # C == B: el punto fijo
