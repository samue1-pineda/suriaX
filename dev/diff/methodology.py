"""Diagrama de la metodología para el póster: tres fases en vertical (lo
escribe ``run_diff.py``; este módulo no se ejecuta solo).

FASE 1 · Diseño (Obj. 1) -> FASE 2 · Implementación (Obj. 2) ->
FASE 3 · Evaluación (Obj. 3). La fase 3 define la referencia y las tres
categorías (OK, No soportado, Error) con los mismos colores que la figura
de resultados (``figure.py``), para que el jurado entienda la tabla antes de
verla.

Las cifras (programas, corridas) salen de los mismos resultados que
``RESULTS.md``: no se escriben a mano. Sin dependencias; fondo claro.
"""
from __future__ import annotations

from html import escape

ESTILO = """
.viz { --surface:#ffffff; --ink:#0b0b0b; --ink-2:#52514e; --borde:#c9c8c1;
       --cabecera:#eef3fb; --acento:#2a78d6;
       --good:#0ca30c; --warn:#fab219; --crit:#d03b3b; }
.fondo { fill: var(--surface); }
text { font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; fill: var(--ink); }
.caja { fill: var(--surface); stroke: var(--borde); stroke-width: 1.5; }
.cab { fill: var(--cabecera); }
.fase { font-size: 25px; font-weight: 700; }
.obj { font-size: 21px; font-weight: 600; fill: var(--acento); }
.linea { font-size: 22px; }
.fuerte { font-size: 22px; font-weight: 700; }
.flecha { stroke: var(--ink-2); stroke-width: 2.5; fill: none; }
.punta { fill: var(--ink-2); }
.ok { fill: var(--good); } .ns { fill: var(--warn); } .err { fill: var(--crit); }
"""

ANCHO, X0 = 760, 30
PASO = 33          # interlineado
CABECERA = 48


def caja(y: float, fase: str, obj: str, lineas: list) -> tuple:
    """Una fase: cabecera (fase y objetivo) y sus lineas; el alto sale de
    cuantas lineas haya. Cada linea es ``(clase, texto)`` o
    ``("estado", clase_color, etiqueta, texto)``."""
    alto = CABECERA + 26 + len(lineas) * PASO
    out = [f'<rect class="caja" x="{X0}" y="{y}" width="{ANCHO}" height="{alto}" rx="10"/>',
           f'<path class="cab" d="M{X0 + 1},{y + CABECERA} L{X0 + 1},{y + 10} Q{X0 + 1},{y + 1} {X0 + 10},{y + 1} '
           f'L{X0 + ANCHO - 10},{y + 1} Q{X0 + ANCHO - 1},{y + 1} {X0 + ANCHO - 1},{y + 10} '
           f'L{X0 + ANCHO - 1},{y + CABECERA} Z"/>',
           f'<text class="fase" x="{X0 + 18}" y="{y + 32}">{escape(fase)}</text>',
           f'<text class="obj" x="{X0 + ANCHO - 18}" y="{y + 32}" text-anchor="end">{escape(obj)}</text>']
    ly = y + CABECERA + 36
    for linea in lineas:
        if linea[0] == "estado":
            _, clase, etiqueta, texto = linea
            out.append(f'<rect class="{clase}" x="{X0 + 18}" y="{ly - 17}" width="19" height="19" rx="3"/>')
            out.append(f'<text class="linea" x="{X0 + 47}" y="{ly}"><tspan font-weight="700">'
                       f'{escape(etiqueta)}</tspan>: {escape(texto)}</text>')
        else:
            clase, texto = linea
            out.append(f'<text class="{clase}" x="{X0 + 18}" y="{ly}">{escape(texto)}</text>')
        ly += PASO
    return out, y + alto


def flecha(y_desde: float, y_hasta: float) -> list:
    cx = X0 + ANCHO / 2
    return [f'<line class="flecha" x1="{cx}" x2="{cx}" y1="{y_desde + 4}" y2="{y_hasta - 14}"/>',
            f'<path class="punta" d="M{cx - 9},{y_hasta - 16} L{cx + 9},{y_hasta - 16} L{cx},{y_hasta - 2} Z"/>']


def diagrama(resultados: dict) -> str:
    """``resultados`` es el mismo diccionario con el que ``run_diff.py``
    escribe ``RESULTS.md``."""
    n = len(resultados["programs"])
    corridas = resultados["reps"]

    out = []
    y = 20
    a, y = caja(y, "FASE 1 · Diseño", "Objetivo 1", [
        ("fuerte", "Esquema versionado del HIR (protobuf)"),
        ("linea", "Esquema 1: cada tipo se escribe dentro de su nodo"),
        ("linea", "Esquema 2: cada tipo se guarda una vez y los nodos"),
        ("linea", "lo referencian (pool de tipos)"),
    ])
    out += a
    y_sig = y + 40
    out += flecha(y, y_sig)
    b, y = caja(y_sig, "FASE 2 · Implementación", "Objetivo 2", [
        ("fuerte", "El compilador (Python) emite el .phir en el esquema 1 o 2"),
        ("linea", "Lo leen el intérprete (Python), la VM (C++)"),
        ("linea", "y el web (TS → WASM), con los dos esquemas"),
    ])
    out += b
    y_sig = y + 40
    out += flecha(y, y_sig)
    c, y = caja(y_sig, "FASE 3 · Evaluación", "Objetivo 3", [
        ("fuerte", f"{n} programas × 3 targets × 2 esquemas"),
        ("linea", f"{corridas} corridas, la primera descartada; mediana"),
        ("linea", "Se mide: equivalencia · tamaño · tiempo"),
        ("linea", "Referencia: intérprete con esquema 2. Cada celda es:"),
        ("estado", "ok", "OK", "misma salida y código de salida"),
        ("estado", "ns", "No soportado", "el target lo rechaza"),
        ("estado", "err", "Error", "el programa diverge"),
    ])
    out += c
    alto = y + 20
    ancho = X0 * 2 + ANCHO
    cab = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" class="viz" viewBox="0 0 {ancho} {alto:.0f}" '
        f'width="{ancho}" height="{alto:.0f}" role="img" aria-labelledby="t d">',
        '<title id="t">Metodología: tres fases</title>',
        '<desc id="d">Fase 1, diseño: esquema versionado del HIR, del esquema 1 con los tipos '
        'en línea al esquema 2 con pool de tipos. Fase 2, implementación: el compilador en '
        'Python emite el .phir y lo leen el intérprete en Python, la VM en C++ y el target web '
        f'en TypeScript a WebAssembly. Fase 3, evaluación: {n} programas por 3 targets por 2 '
        f'esquemas, {corridas} corridas con la primera descartada y la mediana; se mide equivalencia, tamaño y tiempo '
        'contra el intérprete con el esquema 2, y cada celda es OK, No soportado o Error.</desc>',
        f'<style>{ESTILO}</style>',
        f'<rect class="fondo" x="0" y="0" width="{ancho}" height="{alto:.0f}"/>',
    ]
    return "\n".join(cab + out + ["</svg>"]) + "\n"
