"""Extrae y VERIFICA los ejemplos de código de la documentación publicada.

La documentación de suriaX enseña el lenguaje con ejemplos, y hasta ahora
nadie los ejecutaba: el capítulo del lexer llegó a enseñar sintaxis que el
compilador rechazaba desde hacía versiones (``if x > 0`` sin paréntesis,
``mutable int x``, ``entero as float``) sin que ninguna prueba lo notara.
Este módulo cierra ese hueco — es la única fuente de verdad de qué ejemplos
existen y qué se espera de cada uno.

Lo usan dos consumidores, y por eso la lógica vive aquí y no en el test:

- ``test/e2e/test_docs_examples.py`` — dentro de ``python test/main.py``;
- ``python test/docs_examples.py`` — informe legible para trabajar a mano.

Cada bloque declara qué se espera de él con la opción ``:class:`` de su
``code-block``:

``(sin marca)``
   Compila SIN diagnósticos y se EJECUTA hasta el final. Es el valor por
   defecto a propósito: lo estricto no debe depender de que alguien se
   acuerde de pedirlo.

``:class: solo-compila``
   Compila limpio pero no se ejecuta. Para lo que necesita algo que el
   intérprete no aporta — un prototipo cuyo cuerpo pone el host, por
   ejemplo.

``:class: fragmento``
   No se verifica. Para un trozo que continúa el bloque anterior, un
   programa de varios archivos, o un ejemplo que ENSEÑA un error. Se
   informan siempre, para que no se conviertan en un basurero silencioso.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Iterator, List, Optional

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_V0_MAIN = os.path.join(_REPO_ROOT, "V0", "main.py")

#: Raíces que se recorren. ``documentation/source`` es el sitio publicado;
#: ``source/repo`` se excluye porque son COPIAS que ``conf.py`` genera al
#: construir — sus originales se listan aparte y se verifican una sola vez.
_RAICES = ("documentation/source",)
_EXCLUIDOS = ("repo",)

#: Documentos del repositorio que el sitio publica tal cual (ver la tabla
#: ``REPO_DOCS`` de ``documentation/source/conf.py``). Se verifican desde su
#: ubicación real, que es donde se editan.
_MARKDOWN = (
    "ARCHITECTURE.md",
    "lib/HOOKS.md",
    "htims/readme.md",
    "docs/gramar/t_types.md",
)

EJECUTA, COMPILA, OMITIDO = "ejecuta", "solo-compila", "fragmento"


@dataclass(frozen=True)
class Ejemplo:
    """Un bloque de código de la documentación, con su origen y su contrato."""
    doc: str          # ruta relativa a la raíz del repo
    linea: int        # línea donde empieza el CÓDIGO (no la directiva)
    codigo: str
    modo: str         # EJECUTA | COMPILA | OMITIDO

    @property
    def origen(self) -> str:
        return f"{self.doc}:{self.linea}"


@dataclass(frozen=True)
class Fallo:
    ejemplo: Ejemplo
    motivo: str            # qué se esperaba y no pasó
    diagnosticos: List[str]  # líneas del compilador que lo explican


# --------------------------------------------------------------------------- #
# extracción
# --------------------------------------------------------------------------- #

_RST_DIRECTIVA = re.compile(r"^([ \t]*)\.\. code-block:: (?:srcx|suriax)\s*$")
_RST_OPCION = re.compile(r"^\s*:([a-z-]+):\s*(.*)$")
_MD_VALLA = re.compile(r"^```(?:srcx|suriax)\s*$")


def _desangrar(cuerpo: List[str]) -> str:
    """Quita la sangría común del bloque, conservando la relativa."""
    utiles = [ln for ln in cuerpo if ln.strip()]
    if not utiles:
        return ""
    margen = min(len(ln) - len(ln.lstrip()) for ln in utiles)
    return "\n".join(ln[margen:] if ln.strip() else "" for ln in cuerpo)


def _modo_de(clases: str) -> str:
    """Traduce el ``:class:`` del bloque a su contrato."""
    valores = clases.split()
    if OMITIDO in valores:
        return OMITIDO
    if COMPILA in valores:
        return COMPILA
    return EJECUTA


def _bloques_rst(doc: str, texto: str) -> Iterator[Ejemplo]:
    lineas = texto.split("\n")
    i = 0
    while i < len(lineas):
        m = _RST_DIRECTIVA.match(lineas[i])
        if m is None:
            i += 1
            continue
        base = len(m.group(1))
        j = i + 1
        clases = ""
        # las opciones (:linenos:, :class:, ...) van pegadas a la directiva
        while j < len(lineas):
            opcion = _RST_OPCION.match(lineas[j])
            if opcion is None:
                break
            if opcion.group(1) == "class":
                clases = opcion.group(2)
            j += 1
        while j < len(lineas) and not lineas[j].strip():
            j += 1
        inicio, cuerpo = j, []
        while j < len(lineas):
            ln = lineas[j]
            if ln.strip() and (len(ln) - len(ln.lstrip())) <= base:
                break
            cuerpo.append(ln)
            j += 1
        while cuerpo and not cuerpo[-1].strip():
            cuerpo.pop()
        codigo = _desangrar(cuerpo)
        if codigo.strip():
            yield Ejemplo(doc, inicio + 1, codigo, _modo_de(clases))
        i = j


def _bloques_md(doc: str, texto: str) -> Iterator[Ejemplo]:
    """Markdown no tiene ``:class:``: sus bloques son siempre ilustrativos y
    su contrato lo fija el archivo que los publica, así que se tratan como
    fragmentos salvo que la valla diga otra cosa."""
    lineas = texto.split("\n")
    i = 0
    while i < len(lineas):
        if _MD_VALLA.match(lineas[i]):
            j, cuerpo = i + 1, []
            while j < len(lineas) and not lineas[j].startswith("```"):
                cuerpo.append(lineas[j])
                j += 1
            codigo = "\n".join(cuerpo)
            if codigo.strip():
                yield Ejemplo(doc, i + 2, codigo, OMITIDO)
            i = j + 1
        else:
            i += 1


def extraer() -> List[Ejemplo]:
    """Todos los ejemplos de la documentación, en orden estable."""
    encontrados: List[Ejemplo] = []
    for raiz in _RAICES:
        base = os.path.join(_REPO_ROOT, raiz)
        for carpeta, subdirs, archivos in os.walk(base):
            subdirs[:] = [d for d in sorted(subdirs) if d not in _EXCLUIDOS]
            for nombre in sorted(archivos):
                if not nombre.endswith(".rst"):
                    continue
                ruta = os.path.join(carpeta, nombre)
                rel = os.path.relpath(ruta, _REPO_ROOT)
                with open(ruta, encoding="utf-8") as fh:
                    encontrados.extend(_bloques_rst(rel, fh.read()))
    for rel in _MARKDOWN:
        ruta = os.path.join(_REPO_ROOT, rel)
        if not os.path.isfile(ruta):
            continue
        with open(ruta, encoding="utf-8") as fh:
            encontrados.extend(_bloques_md(rel, fh.read()))
    return encontrados


# --------------------------------------------------------------------------- #
# verificación
# --------------------------------------------------------------------------- #

#: Líneas de la salida del compilador que explican un fallo. El contrato de
#: la suite es el CÓDIGO, no el texto (ver ``negative_tests``).
_DIAGNOSTICO = re.compile(r"\b[A-Z]{2,4}\d{3}\b")


class Banco:
    """Directorio de trabajo compartido por todos los ejemplos de una corrida.

    Se monta UNA vez: crear un proyecto por ejemplo multiplicaría por cien el
    coste sin aislar nada que importe —cada bloque compila en su propio
    archivo y el linker resuelve por ruta.
    """

    def __init__(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="suriax-docs-")
        # el linker busca junto al fuente y en '<dir>/lib': un enlace basta y
        # evita copiar la librería estándar una vez por corrida.
        destino = os.path.join(self.dir, "lib")
        origen = os.path.join(_REPO_ROOT, "lib")
        try:
            os.symlink(origen, destino)
        except (OSError, NotImplementedError):  # sistemas sin symlink
            shutil.copytree(origen, destino)
        # ancla la raíz del proyecto al banco, no al CWD del proceso
        shutil.copyfile(os.path.join(_REPO_ROOT, ".suriaX_config.yaml"),
                        os.path.join(self.dir, ".suriaX_config.yaml"))

    def cerrar(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def compilar(self, ejemplo: Ejemplo, indice: int) -> "subprocess.CompletedProcess[str]":
        nombre = f"ej{indice:03d}.srcx"
        with open(os.path.join(self.dir, nombre), "w", encoding="utf-8") as fh:
            fh.write(ejemplo.codigo + "\n")
        cmd = [sys.executable, _V0_MAIN, nombre]
        if ejemplo.modo == EJECUTA:
            cmd.append("--run")
        return subprocess.run(cmd, cwd=self.dir, capture_output=True,
                              text=True, timeout=180)


def _diagnosticos(salida: str) -> List[str]:
    return [ln.strip() for ln in salida.splitlines() if _DIAGNOSTICO.search(ln)]


def verificar(ejemplos: Optional[List[Ejemplo]] = None) -> List[Fallo]:
    """Corre cada ejemplo según su modo y devuelve SOLO los que fallan."""
    ejemplos = extraer() if ejemplos is None else ejemplos
    banco = Banco()
    fallos: List[Fallo] = []
    try:
        for indice, ejemplo in enumerate(ejemplos):
            if ejemplo.modo == OMITIDO:
                continue
            proc = banco.compilar(ejemplo, indice)
            salida = proc.stdout + proc.stderr
            if "=== errores" in salida or "HIR no emitido" in salida:
                fallos.append(Fallo(
                    ejemplo, "el ejemplo NO compila", _diagnosticos(salida)))
            elif ejemplo.modo == EJECUTA and proc.returncode == 70:
                fallos.append(Fallo(
                    ejemplo, "compila pero FALLA al ejecutarse",
                    _diagnosticos(salida)))
    finally:
        banco.cerrar()
    return fallos


# --------------------------------------------------------------------------- #
# informe legible (uso manual)
# --------------------------------------------------------------------------- #

def _numerado(ejemplo: Fallo) -> str:
    """El código del bloque con la línea REAL del documento al margen: es lo
    que hace falta para ir a arreglarlo sin buscarlo."""
    ancho = len(str(ejemplo.ejemplo.linea + ejemplo.ejemplo.codigo.count("\n")))
    salida = []
    for desplazamiento, linea in enumerate(ejemplo.ejemplo.codigo.split("\n")):
        salida.append(f"      {ejemplo.ejemplo.linea + desplazamiento:>{ancho}} | {linea}")
    return "\n".join(salida)


def informe() -> int:
    """Imprime el estado de todos los ejemplos. Devuelve el código de salida."""
    ejemplos = extraer()
    fallos = verificar(ejemplos)

    por_modo = {modo: sum(1 for e in ejemplos if e.modo == modo)
                for modo in (EJECUTA, COMPILA, OMITIDO)}
    print(f"ejemplos en la documentación: {len(ejemplos)}")
    print(f"  compilan y ejecutan : {por_modo[EJECUTA]}")
    print(f"  solo compilan       : {por_modo[COMPILA]}")
    print(f"  fragmentos (omitidos): {por_modo[OMITIDO]}")
    print()

    if not fallos:
        print(f"OK — los {len(ejemplos) - por_modo[OMITIDO]} ejemplos "
              "verificables se comportan como la documentación promete.")
    else:
        print(f"FALLAN {len(fallos)} de "
              f"{len(ejemplos) - por_modo[OMITIDO]} ejemplos verificables:\n")
        for fallo in fallos:
            print(f"  {fallo.ejemplo.origen}")
            print(f"      {fallo.motivo} (modo '{fallo.ejemplo.modo}')")
            for diagnostico in fallo.diagnosticos:
                print(f"      -> {diagnostico}")
            print(_numerado(fallo))
            print()

    omitidos = [e for e in ejemplos if e.modo == OMITIDO and e.doc.endswith(".rst")]
    if omitidos:
        print(f"fragmentos declarados ({len(omitidos)}) — no se verifican:")
        for ejemplo in omitidos:
            print(f"  {ejemplo.origen}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(informe())
