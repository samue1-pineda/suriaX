"""Figuras del diferencial (las escribe ``run_diff.py``; este módulo no se
ejecuta solo).

- ``figure.svg``: el estado de cada programa en los 3 targets (OK, No
  soportado o Error) con el HIR de esquema 2. Hecha para un hueco de
  26 × 21 cm del póster: 1000 px de ancho, así que 28 px se imprimen a unos
  20 pt. Las columnas de Python y C++ solo dicen "OK" y van estrechas; la del
  web, la única con causas, va ancha.
- ``size_change.svg``: el cambio de tamaño del ``.phir`` del esquema 1 al 2
  para cada programa, en una sola escala y con la mediana. Es el detalle
  para el informe y el QR; en el póster va como un número grande.

``run_diff.py`` las escribe a la vez que ``RESULTS.md``, con los mismos datos
y con su propio ``cell_status`` (se recibe como parámetro): la figura y el
informe no se pueden contradecir. Sin dependencias. Fondo blanco: son para
imprimir.
"""
from __future__ import annotations

import statistics
from html import escape
from typing import Callable

# -- datos -------------------------------------------------------------------

# nombres cortos: se leen a distancia
NOMBRES = {
    "01_hola": "Hola mundo",
    "02_aritmetica": "Aritmética",
    "03_control": "Control de flujo",
    "04_vector": "Vector",
    "05_funciones": "Funciones y recursión",
    "06_sintetico_10": "Sintético 10",
    "06_sintetico_1000": "Sintético 1.000",
    "06_sintetico_10000": "Sintético 10.000",
    "07_division_cero": "División por cero",
    "08_desbordamiento": "Desbordamiento",
    "09_structs": "Structs",
}
TARGETS = (("interp", "Python"), ("vm", "C++"), ("web", "Web"))

# La causa de cada rechazo en palabras: los códigos (WEB002...) van en el
# informe, no en el póster.
CAUSA_NO_SOPORTADO = {
    "04_vector": "usa punteros",
    "09_structs": "structs",
}

ESTADOS = {
    # estado: (clase del color, etiqueta)
    "OK": ("ok", "OK"),
    "NOT SUPPORTED": ("ns", "No soportado"),
    "ERROR": ("err", "Error"),
}

# Paleta de referencia del método de visualización: estados (fijos) y dos
# tonos categóricos validados (CVD incluido) para la polaridad de tamaños.
ESTILO = """
.viz { --surface:#ffffff; --ink:#0b0b0b; --ink-2:#52514e; --ink-3:#8a8984;
       --grid:#e6e5e0; --menos:#2a78d6; --mas:#eb6834;
       --good:#0ca30c; --warn:#fab219; --crit:#d03b3b; }
.fondo { fill: var(--surface); }
text { font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; fill: var(--ink); }
.ok   { fill: var(--good); } .ns { fill: var(--warn); } .err { fill: var(--crit); }
.ok-b { stroke: var(--good); } .ns-b { stroke: var(--warn); } .err-b { stroke: var(--crit); }
.menos { fill: var(--menos); } .mas { fill: var(--mas); }
.rejilla { stroke: var(--grid); stroke-width: 1; }
.eje { stroke: var(--ink-3); stroke-width: 1.5; }
.mediana { stroke: var(--ink); stroke-width: 1.5; stroke-dasharray: 5 4; }
"""


def coma(x: float, decimales: int = 1) -> str:
    """``-7.3`` -> ``−7,3`` (coma decimal y signo menos tipográfico)."""
    return f"{x:+.{decimales}f}".replace(".", ",").replace("-", "−")


def causa(clave: str, estado: str, detalle: str) -> str:
    """Una línea corta con el motivo; solo en lo que no es OK."""
    if estado == "OK":
        return ""
    if estado == "NOT SUPPORTED":
        return CAUSA_NO_SOPORTADO.get(clave, "")
    if "unrepresentable" in detalle:
        return "falla: MIN / −1"
    if "divide by zero" in detalle:
        return "falla: división por 0"
    return detalle[:22]


def envolver(ancho: float, alto: float, titulo: str, desc: str, cuerpo: list) -> str:
    cab = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" class="viz" viewBox="0 0 {ancho:.0f} {alto:.0f}" '
        f'width="{ancho:.0f}" height="{alto:.0f}" role="img" aria-labelledby="t d">',
        f'<title id="t">{escape(titulo)}</title>',
        f'<desc id="d">{escape(desc)}</desc>',
        f'<style>{ESTILO}</style>',
        f'<rect class="fondo" x="0" y="0" width="{ancho:.0f}" height="{alto:.0f}"/>',
    ]
    return "\n".join(cab + cuerpo + ["</svg>"]) + "\n"


# -- figura del póster: estados ----------------------------------------------

def estados(programas: list, cell_status: Callable[[dict, str], tuple]) -> str:
    """``cell_status`` es el de ``run_diff.py``: la figura clasifica cada
    celda con la MISMA función que escribe ``RESULTS.md``."""
    ancho = 1000                            # 26 cm de ancho
    x0 = 40
    col_nombre = 290
    anchos = {"interp": 150, "vm": 150, "web": 300}
    sep = 8
    alto_fila, hueco = 58, 1
    out = []

    # El título afirma algo de los datos, así que se calcula: antes estaba
    # escrito a mano y habría seguido diciendo "idénticos" aunque una corrida
    # nueva los hiciera distintos.
    distintas = sum(1 for p in programas for t, _ in TARGETS
                    if f"s1/{t}" in p["cells"] and f"s2/{t}" in p["cells"]
                    and cell_status(p, f"s1/{t}")[0] != cell_status(p, f"s2/{t}")[0])
    titulo = ("Con el esquema 1 y con el 2, los estados son idénticos" if distintas == 0 else
              f"Esquema 2 (con el 1 cambian {distintas} celdas)")

    y = 38
    out.append(f'<text x="{x0}" y="{y}" font-size="29" font-weight="700">{escape(titulo)}</text>')
    y_cab = y + 50
    x = x0 + col_nombre
    xs = {}
    for t, nombre in TARGETS:
        xs[t] = x
        out.append(f'<text x="{x + anchos[t] / 2:.0f}" y="{y_cab}" font-size="28" font-weight="700" '
                   f'style="fill:#52514e" text-anchor="middle">{nombre}</text>')
        x += anchos[t] + sep

    cuenta = {"OK": 0, "NOT SUPPORTED": 0, "ERROR": 0}
    y = y_cab + 14
    for p in programas:
        clave = p["program"].removesuffix(".srcx")
        nombre = NOMBRES.get(clave, clave)
        out.append(f'<text x="{x0}" y="{y + alto_fila / 2 + 10:.0f}" font-size="28">{escape(nombre)}</text>')
        for t, nombre_t in TARGETS:
            estado, detalle = cell_status(p, f"s2/{t}")
            cuenta[estado] += 1
            clase, etiqueta = ESTADOS[estado]
            cx, w = xs[t], anchos[t]
            motivo = causa(clave, estado, detalle)
            tip = f"{nombre} · {nombre_t}: {etiqueta}" + (f" — {detalle}" if detalle else "")
            out.append(f'<g><title>{escape(tip)}</title>')
            out.append(f'<rect class="{clase}-b" x="{cx}" y="{y}" width="{w}" height="{alto_fila}" '
                       'rx="7" fill="none" stroke-width="2.5"/>')
            out.append(f'<rect class="{clase}" x="{cx}" y="{y}" width="8" height="{alto_fila}" rx="3"/>')
            if motivo:
                out.append(f'<text x="{cx + 20}" y="{y + 25}" font-size="27" font-weight="700">'
                           f'{etiqueta}</text>')
                out.append(f'<text x="{cx + 20}" y="{y + 49}" font-size="26" style="fill:#52514e">'
                           f'{escape(motivo)}</text>')
            else:
                out.append(f'<text x="{cx + 20}" y="{y + alto_fila / 2 + 10:.0f}" font-size="27" '
                           f'font-weight="700">{etiqueta}</text>')
            out.append('</g>')
        y += alto_fila + hueco

    total = sum(cuenta.values())
    y += 32
    lx = x0
    for estado in ("OK", "NOT SUPPORTED", "ERROR"):
        clase, etiqueta = ESTADOS[estado]
        texto = f"{etiqueta}: {cuenta[estado]} de {total}"
        out.append(f'<rect class="{clase}" x="{lx}" y="{y - 20}" width="22" height="22" rx="4"/>')
        out.append(f'<text x="{lx + 32}" y="{y}" font-size="27">{escape(texto)}</text>')
        lx += 32 + len(texto) * 14 + 46
    alto = y + 25                           # con 11 programas, 808 px (21 cm)

    desc = (f"{len(programas)} programas por 3 targets (Python, C++ y web) con el esquema 2: OK "
            f"{cuenta['OK']} de {total}, no soportado {cuenta['NOT SUPPORTED']} de {total} y "
            f"error {cuenta['ERROR']} de {total}. "
            + ("Con el esquema 1 los estados son idénticos." if distintas == 0 else
               f"Con el esquema 1 cambian {distintas} celdas."))
    return envolver(ancho, alto, "Estado de cada programa en cada target", desc, out)


# -- detalle para el informe: tamaños ----------------------------------------

def tamanos(programas: list) -> str:
    """Barras horizontales del cambio de tamaño (esquema 2 frente a 1), en
    2:1 para un hueco de 26 × 13 cm: 1000 px de ancho, así que 28 px se
    imprimen a unos 20 pt."""
    cambios = []
    for p in programas:
        s = p["sizes"]
        v1, v2 = s["s1"]["main_bytes"], s["s2"]["main_bytes"]
        cambios.append((p["program"].removesuffix(".srcx"), (v2 - v1) / v1 * 100, v1, v2))
    mediana = statistics.median(c for _, c, _, _ in cambios)

    ancho = 1000
    x0, col_nombre = 30, 245
    alto_fila = 37
    out = [f'<text x="{x0}" y="36" font-size="28" font-weight="700">'
           'Cambio de tamaño del .phir del programa, esquema 2 frente a 1</text>',
           f'<text x="{x0}" y="70" font-size="24" style="fill:#52514e">'
           'Solo la unidad del programa, sin las librerías (negativo = más pequeño)</text>']
    lo, hi = -12.0, 3.0
    x_izq, x_der = x0 + col_nombre + 20, ancho - 90

    def xpos(v: float) -> float:
        return x_izq + (v - lo) / (hi - lo) * (x_der - x_izq)

    ys = [126 + i * alto_fila for i in range(len(cambios))]
    y_arriba, y_abajo = ys[0] - 2, ys[-1] + alto_fila + 2
    for v in (-12, -6, 0):
        x = xpos(v)
        out.append(f'<line class="rejilla" x1="{x:.1f}" x2="{x:.1f}" y1="{y_arriba}" y2="{y_abajo}"/>')
        out.append(f'<text x="{x:.1f}" y="{ys[0] - 12}" font-size="24" style="fill:#52514e" '
                   f'text-anchor="middle">{"0 %" if v == 0 else coma(v, 0) + " %"}</text>')
    x_cero = xpos(0)
    alto_barra = 29
    for (clave, c, v1, v2), y in zip(cambios, ys):
        out.append(f'<text x="{x0}" y="{y + alto_fila / 2 + 9:.0f}" font-size="26">'
                   f'{escape(NOMBRES.get(clave, clave))}</text>')
        yb = y + (alto_fila - alto_barra) / 2
        x_fin = xpos(c)
        x, w = (x_fin, x_cero - x_fin) if c < 0 else (x_cero, x_fin - x_cero)
        tip = f"{NOMBRES.get(clave, clave)}: {v1:,} → {v2:,} B ({coma(c)} %)".replace(",", ".")
        out.append(f'<g><title>{escape(tip)}</title>')
        out.append(f'<rect class="{"menos" if c < 0 else "mas"}" x="{x:.1f}" y="{yb:.1f}" '
                   f'width="{max(w, 1):.1f}" height="{alto_barra}" rx="3"/>')
        if c < 0 and w >= 110:
            # dentro de la barra, junto al cero: la mediana cae cerca del extremo
            out.append(f'<text x="{x_cero - 8:.1f}" y="{yb + 23:.1f}" font-size="24" font-weight="700" '
                       f'style="fill:#ffffff" text-anchor="end">{coma(c)} %</text>')
        elif c < 0:
            out.append(f'<text x="{x_fin - 8:.1f}" y="{yb + 23:.1f}" font-size="24" font-weight="700" '
                       f'text-anchor="end">{coma(c)} %</text>')
        else:
            out.append(f'<text x="{x_fin + 8:.1f}" y="{yb + 23:.1f}" font-size="24" '
                       f'font-weight="700">{coma(c)} %</text>')
        out.append('</g>')
    out.append(f'<line class="eje" x1="{x_cero:.1f}" x2="{x_cero:.1f}" y1="{y_arriba}" y2="{y_abajo}"/>')
    x_med = xpos(mediana)
    out.append(f'<line class="mediana" x1="{x_med:.1f}" x2="{x_med:.1f}" y1="{y_arriba}" y2="{y_abajo + 8}"/>')
    out.append(f'<text x="{x_med:.1f}" y="{y_abajo + 34}" font-size="26" font-weight="700" '
               f'text-anchor="middle">mediana {coma(mediana)} %</text>')
    alto = y_abajo + 46
    peor = max(c for _, c, _, _ in cambios)
    mejor = min(c for _, c, _, _ in cambios)
    desc = (f"El .phir del programa con el esquema 2 cambia entre {coma(mejor)} % y {coma(peor)} % "
            f"respecto del esquema 1 en los {len(cambios)} programas; mediana {coma(mediana)} %.")
    return envolver(ancho, alto, "Cambio de tamaño del .phir del programa, esquema 2 frente a 1", desc, out)
