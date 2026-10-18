"""unit/llamadas_al_host — el contrato de lo que un programa le pide al host.

``lib/LLAMADAS_AL_HOST.md`` dice, de cada llamada, su firma y qué motor la
cumple. Esa lista estaba repartida en tres sitios (la librería, el
intérprete y la VM) y nada comprobaba que dijeran lo mismo: una llamada
nueva podía existir en uno y faltar en otro sin que nadie se enterase hasta
ejecutarla. Aquí se comparan los cuatro.

No se ejecuta ningún motor: la VM y el target web se miran por su código.
"""

from __future__ import annotations

import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (_REPO, os.path.join(_REPO, "V0")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: una función SIN cuerpo de la librería: ``internal fn __x__(...) -> T;``.
#: Los ``hook fn`` sin cuerpo (las conversiones de ``d_types``) no son
#: llamadas al host: son la tabla de conversiones del lenguaje.
_PROTOTIPO = re.compile(
    r"^\s*(?:(?:internal|public|private)\s+)?fn\s+(__\w+__)\s*(<[^>]*>)?\s*"
    r"\(([^)]*)\)\s*(?:->\s*([^;{]+?))?\s*;", re.M)

#: una fila de la tabla: | `__x__` | `firma` | sí | no | no |
_FILA = re.compile(r"^\| `(__\w+__)` \| `([^`]+)` \| (sí|no) \| (sí|no) \| (sí|no) \|$",
                   re.M)

#: intrínsecos del intérprete que no son de la librería estándar, y por qué.
_SOLO_DEL_HOST = {
    # el nombre antiguo de '__write__', que usan los ejemplos de docs/
    "suriax_write",
}


def _leer(*partes):
    with open(os.path.join(_REPO, *partes), encoding="utf-8") as fh:
        return fh.read()


def _de_la_libreria() -> dict:
    """``{nombre: (unidad, firma)}`` de cada llamada declarada en ``lib/``."""
    vistas: dict = {}
    for ruta in sorted(glob.glob(os.path.join(_REPO, "lib", "**", "*.libsrx"),
                                 recursive=True)):
        unidad = os.path.relpath(ruta, os.path.join(_REPO, "lib")).replace(os.sep, "/")
        for m in _PROTOTIPO.finditer(_leer(ruta)):
            firma = (f"{m.group(2) or ''}({m.group(3).strip()}) -> "
                     f"{(m.group(4) or 'void').strip()}")
            anterior = vistas.setdefault(m.group(1), (unidad, firma))
            # la misma llamada en dos unidades (__write__ en stdp y stdpf)
            # tiene que tener la MISMA firma: el host implementa una.
            assert anterior[1] == firma, (m.group(1), anterior, (unidad, firma))
    return vistas


def _de_la_tabla() -> dict:
    """``{nombre: (firma, intérprete, vm, web)}`` de ``LLAMADAS_AL_HOST.md``."""
    filas = {}
    for m in _FILA.finditer(_leer("lib", "LLAMADAS_AL_HOST.md")):
        assert m.group(1) not in filas, f"fila repetida: {m.group(1)}"
        filas[m.group(1)] = (m.group(2), m.group(3) == "sí",
                             m.group(4) == "sí", m.group(5) == "sí")
    return filas


def test_la_tabla_nombra_cada_llamada_de_la_libreria_con_su_firma():
    libreria, tabla = _de_la_libreria(), _de_la_tabla()
    assert len(libreria) > 40, "no se encontraron las llamadas de la librería"
    faltan = sorted(set(libreria) - set(tabla))
    sobran = sorted(set(tabla) - set(libreria))
    assert not faltan and not sobran, (
        f"en la librería y no en la tabla: {faltan}; en la tabla y no en la "
        f"librería: {sobran}")
    distintas = {n: (libreria[n][1], tabla[n][0]) for n in libreria
                 if libreria[n][1] != tabla[n][0]}
    assert not distintas, f"firma de la librería frente a la de la tabla: {distintas}"


def test_el_interprete_cumple_todas_las_llamadas():
    """El intérprete es el motor de referencia: no hay llamada sin él."""
    from runtime.interpreter import intrinsics

    tabla = _de_la_tabla()
    sin_marcar = sorted(n for n, fila in tabla.items() if not fila[1])
    assert not sin_marcar, f"la tabla dice que el intérprete no las tiene: {sin_marcar}"
    sin_implementar = sorted(n for n in tabla if intrinsics.lookup(n) is None)
    assert not sin_implementar, f"sin implementación en el intérprete: {sin_implementar}"
    huerfanas = sorted(set(intrinsics.REGISTRY) - set(tabla) - _SOLO_DEL_HOST)
    assert not huerfanas, (
        f"el intérprete implementa llamadas que ninguna librería declara: {huerfanas}")


def test_la_columna_de_la_vm_dice_lo_que_hay_en_la_vm():
    """La VM despacha cada llamada por su NOMBRE (``backend/src/vm.cpp``):
    está si su nombre aparece entre comillas. Una llamada que la VM no tiene
    es ``RT008`` al ejecutarla; la tabla tiene que decirlo antes."""
    vm = _leer("backend", "src", "vm.cpp")
    distintas = {n: fila[2] for n, fila in _de_la_tabla().items()
                 if fila[2] != (f'"{n}"' in vm)}
    assert not distintas, f"la columna VM no coincide con la VM (tabla dice): {distintas}"


def test_la_columna_web_dice_lo_que_el_target_web_aporta():
    """El target web solo implementa las primitivas que declara su política
    (``hostPrimitives`` en ``web/src/target/policy.ts``)."""
    politica = _leer("web", "src", "target", "policy.ts")
    primitivas = set(re.findall(r'hostPrimitives:\s*\[([^\]]*)\]', politica))
    del_web = {n for grupo in primitivas for n in re.findall(r'"(__\w+__)"', grupo)}
    distintas = {n: fila[3] for n, fila in _de_la_tabla().items()
                 if fila[3] != (n in del_web)}
    assert not distintas, f"la columna Web no coincide con el target web: {distintas}"


def test_las_llamadas_no_se_ven_fuera_de_su_archivo():
    """El programa usa la función pública, nunca la llamada: así una
    librería puede cambiar cómo usa al host sin cambiar su interfaz. Las de
    ``mem`` son ``private`` (las comparte su paquete); el resto, ``internal``."""
    publicas = []
    for ruta in glob.glob(os.path.join(_REPO, "lib", "**", "*.libsrx"), recursive=True):
        for linea in _leer(ruta).splitlines():
            m = _PROTOTIPO.match(linea)
            if m and not linea.lstrip().startswith(("internal ", "private ")):
                publicas.append((os.path.relpath(ruta, _REPO), linea.strip()))
    assert not publicas, publicas
