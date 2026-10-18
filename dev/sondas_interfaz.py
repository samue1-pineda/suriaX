"""Sondas de interfaz: ¿de qué hechos de una librería depende su importador?

Cada sonda es un proyecto mínimo (``main.srcx`` + ``lib/m.libsrx``) con DOS
versiones de la librería, A y B, que difieren en UN solo hecho (el cuerpo de
una función, el orden de dos campos, un hook que aparece...). Se compila y se
ejecuta el programa contra cada versión y se compara:

- el ``.phir`` del IMPORTADOR, byte a byte;
- lo que el programa escribe (las líneas que empiezan por ``SONDA:``) y cómo
  termina.

El veredicto dice si un compilador incremental podría reutilizar el ``.phir``
del importador tras ese cambio:

- ``IGUAL``     mismo ``.phir``, misma conducta: el hecho no le importa.
- ``TARDIA``    mismo ``.phir``, otra conducta: se enlaza al ejecutar. Se puede
                reutilizar; si la conducta nueva es un error de ejecución, el
                requisito no estaba escrito en ninguna interfaz.
- ``FUGA``      otro ``.phir``: el importador consumió ese hecho al compilar.
- ``RECHAZO``   el importador deja de compilar (o empieza a hacerlo).

Es una herramienta de MEDICIÓN, no una prueba: no está en la suite ni nada
depende de ella. Uso::

    python dev/sondas_interfaz.py            # todas
    python dev/sondas_interfaz.py orden      # las que contengan 'orden'
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPILADOR = os.path.join(RAIZ, "V0", "main.py")

_CODIGO = re.compile(r"\b(?:LEX|PAR|AST|SEM|HIR|RT|ICE|NOTA)\d{3}\b")


@dataclass
class Sonda:
    nombre: str
    hecho: str                      #: qué cambia entre A y B, en una frase
    main: str
    lib_a: str
    lib_b: str
    #: otras unidades de 'lib/' que no cambian (nombre de archivo -> fuente)
    fijas: Dict[str, str] = field(default_factory=dict)
    #: el archivo de 'lib/' que cambia entre A y B
    cambia: str = "m.libsrx"


@dataclass
class Corrida:
    compila: bool
    phir: Optional[str]             #: sha256 del .phir del importador
    unidades: Dict[str, str]        #: sha256 de cada .phir de librería
    salida: List[str]               #: las líneas 'SONDA:' del programa
    codigos: List[str]              #: códigos de diagnóstico o de runtime


MAIN_BASE = """\
#from io #import stdp
#import m
{extra}
fn main() -> int {{
{cuerpo}
    return 0;
}}
"""


def _main(cuerpo: str, extra: str = "") -> str:
    return MAIN_BASE.format(cuerpo=cuerpo.rstrip(), extra=extra)


SONDAS: List[Sonda] = [
    Sonda(
        "control_cuerpo_equivalente",
        "el cuerpo de una función, con el mismo resultado",
        _main('    stdp.println(f"SONDA: {m.doble(4)}");'),
        "public fn doble(int x) -> int { return x * 2; }\n#export as m\n",
        "public fn doble(int x) -> int { return x + x; }\n#export as m\n",
    ),
    Sonda(
        "control_cuerpo_distinto",
        "el cuerpo de una función, con otro resultado",
        _main('    stdp.println(f"SONDA: {m.doble(4)}");'),
        "public fn doble(int x) -> int { return x * 2; }\n#export as m\n",
        "public fn doble(int x) -> int { return x * 3; }\n#export as m\n",
    ),
    Sonda(
        "control_funcion_nueva",
        "una función pública nueva que el importador no usa",
        _main('    stdp.println(f"SONDA: {m.doble(4)}");'),
        "public fn doble(int x) -> int { return x * 2; }\n#export as m\n",
        "public fn triple(int x) -> int { return x * 3; }\n"
        "public fn doble(int x) -> int { return x * 2; }\n#export as m\n",
    ),
    Sonda(
        "orden_de_declaraciones",
        "el orden de dos funciones de la librería",
        _main('    stdp.println(f"SONDA: {m.doble(4)} {m.triple(4)}");'),
        "public fn doble(int x) -> int { return x * 2; }\n"
        "public fn triple(int x) -> int { return x * 3; }\n#export as m\n",
        "public fn triple(int x) -> int { return x * 3; }\n"
        "public fn doble(int x) -> int { return x * 2; }\n#export as m\n",
    ),
    Sonda(
        "valor_de_constante",
        "el valor de una constante pública",
        _main('    stdp.println(f"SONDA: {m.BASE}");'),
        "public const int BASE = 10;\n#export as m\n",
        "public const int BASE = 20;\n#export as m\n",
    ),
    Sonda(
        "orden_de_campos",
        "el orden de los campos de un struct público",
        _main('    var m.Par p = m.Par{ a: 1, b: 2 };\n'
              '    stdp.println(f"SONDA: {p.a} {p.b}");'),
        "public struct { int a; int b; } Par;\n#export as m\n",
        "public struct { int b; int a; } Par;\n#export as m\n",
    ),
    Sonda(
        "campo_nuevo",
        "un campo nuevo al final de un struct que el importador no construye",
        _main('    var m.Par p = m.par(1);\n'
              '    stdp.println(f"SONDA: {p.a}");'),
        "public struct { int a; int b; } Par;\n"
        "public fn par(int a) -> Par { return Par{ a: a, b: a }; }\n"
        "#export as m\n",
        "public struct { int a; int b; int c; } Par;\n"
        "public fn par(int a) -> Par { return Par{ a: a, b: a, c: a }; }\n"
        "#export as m\n",
    ),
    Sonda(
        "orden_de_variantes",
        "el orden de las variantes de un enum público",
        _main('    var m.Color c = m.Color.VERDE;\n'
              '    var int n = 0;\n'
              '    if (c == m.Color.VERDE) { n = 1; };\n'
              '    stdp.println(f"SONDA: {n}");'),
        "public enum Color { ROJO, VERDE };\n#export as m\n",
        "public enum Color { VERDE, ROJO };\n#export as m\n",
    ),
    Sonda(
        "aparece_free",
        "el tipo gana un '__free__' (pasa a poseer recursos)",
        _main('    var m.Par p = m.par(1);\n'
              '    stdp.println(f"SONDA: {p.a}");'),
        "public struct { int a; int b; } Par;\n"
        "public fn par(int a) -> Par { return Par{ a: a, b: a }; }\n"
        "#export as m\n",
        "public struct { int a; int b; } Par;\n"
        "public hook fn __free__(Par ptr p) -> void { }\n"
        "public fn par(int a) -> Par { return Par{ a: a, b: a }; }\n"
        "#export as m\n",
    ),
    Sonda(
        "propiedad_por_campo",
        "un campo por valor de un tipo que posee (la propiedad se hereda)",
        _main('    var m.Caja c = m.caja(1);\n'
              '    stdp.println(f"SONDA: {c.a}");'),
        "public struct { int id; } Rec;\n"
        "public hook fn __free__(Rec ptr r) -> void { }\n"
        "public struct { int a; } Caja;\n"
        "public fn caja(int a) -> Caja { return Caja{ a: a }; }\n"
        "#export as m\n",
        "public struct { int id; } Rec;\n"
        "public hook fn __free__(Rec ptr r) -> void { }\n"
        "public struct { int a; Rec r; } Caja;\n"
        "public fn caja(int a) -> Caja { return Caja{ a: a, r: Rec{ id: a } }; }\n"
        "#export as m\n",
    ),
    Sonda(
        "propiedad_transitiva",
        "un tipo de OTRA unidad (que el importador no importa) gana '__free__'",
        _main('    var m.Caja c = m.caja(1);\n'
              '    stdp.println(f"SONDA: {c.a}");'),
        "public struct { int id; } Rec;\n#export as n\n",
        "public struct { int id; } Rec;\n"
        "public hook fn __free__(Rec ptr r) -> void { }\n#export as n\n",
        fijas={"m.libsrx":
               "#import n\n"
               "public struct { int a; n.Rec r; } Caja;\n"
               "public fn caja(int a) -> Caja {"
               " return Caja{ a: a, r: n.Rec{ id: a } }; }\n"
               "#export as m\n"},
        cambia="n.libsrx",
    ),
    Sonda(
        "aparece_eq",
        "el tipo gana un '__eq__' (el '==' deja de ser la identidad)",
        _main('    var m.Par p = m.par(1);\n'
              '    var m.Par q = m.par(1);\n'
              '    var int n = 0;\n'
              '    if (p == q) { n = 1; };\n'
              '    stdp.println(f"SONDA: {n}");'),
        "public struct { int a; int b; } Par;\n"
        "public fn par(int a) -> Par { return Par{ a: a, b: a }; }\n"
        "#export as m\n",
        "public struct { int a; int b; } Par;\n"
        "public hook fn __eq__(Par ptr x, Par ptr y) -> bool { return x.a == y.a; }\n"
        "public fn par(int a) -> Par { return Par{ a: a, b: a }; }\n"
        "#export as m\n",
    ),
    Sonda(
        "cuerpo_de_eq",
        "el cuerpo de un '__eq__' que ya existía",
        _main('    var m.Par p = m.par(1);\n'
              '    var m.Par q = m.par(1);\n'
              '    var int n = 0;\n'
              '    if (p == q) { n = 1; };\n'
              '    stdp.println(f"SONDA: {n}");'),
        "public struct { int a; int b; } Par;\n"
        "public hook fn __eq__(Par ptr x, Par ptr y) -> bool { return x.a == y.a; }\n"
        "public fn par(int a) -> Par { return Par{ a: a, b: a }; }\n"
        "#export as m\n",
        "public struct { int a; int b; } Par;\n"
        "public hook fn __eq__(Par ptr x, Par ptr y) -> bool { return x.a != y.a; }\n"
        "public fn par(int a) -> Par { return Par{ a: a, b: a }; }\n"
        "#export as m\n",
    ),
    Sonda(
        "rango_de_literal",
        "el literal que devuelve '__max__' (el rango de un tipo numérico)",
        _main('    const m.Grado g = 100;\n'
              '    stdp.println("SONDA: compila");'),
        "public const type Grado;\n"
        "public hook fn __cast__(int n) -> Grado;\n"
        "public hook fn __min__(Grado ptr _) -> int { return 0; }\n"
        "public hook fn __max__(Grado ptr _) -> int { return 360; }\n"
        "#export as m\n",
        "public const type Grado;\n"
        "public hook fn __cast__(int n) -> Grado;\n"
        "public hook fn __min__(Grado ptr _) -> int { return 0; }\n"
        "public hook fn __max__(Grado ptr _) -> int { return 90; }\n"
        "#export as m\n",
    ),
    Sonda(
        "requisito_de_generico",
        "el cuerpo de un genérico empieza a pedir un hook a su 'T'",
        _main('    var Punto p = Punto{ x: 1 };\n'
              '    stdp.println(f"SONDA: {m.clave<Punto>(p)}");',
              extra="struct { int x; } Punto;\n"),
        "public fn clave<T>(T x) -> int { return 7; }\n#export as m\n",
        "public fn clave<T>(T x) -> int { return hash(x); }\n#export as m\n",
    ),
]


def _sha(ruta: str) -> str:
    with open(ruta, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _corre(proyecto: str, sonda: Sonda, lib: str) -> Corrida:
    """Arma el proyecto con una versión de la librería, lo compila y lo
    ejecuta en el intérprete (el motor que no necesita nada construido)."""
    if os.path.isdir(proyecto):
        shutil.rmtree(proyecto)     # misma ruta para A y B: nada de la ruta cambia
    os.makedirs(os.path.join(proyecto, "lib"))
    with open(os.path.join(proyecto, "main.srcx"), "w", encoding="utf-8") as f:
        f.write(sonda.main)
    for nombre, fuente in {**sonda.fijas, sonda.cambia: lib}.items():
        with open(os.path.join(proyecto, "lib", nombre), "w",
                  encoding="utf-8") as f:
            f.write(fuente)

    entorno = dict(os.environ, PYTHONUTF8="1")
    hecho = subprocess.run(
        [sys.executable, "-X", "utf8", COMPILADOR, "main.srcx",
         "--run", "interpreter"],
        cwd=proyecto, env=entorno, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120)
    texto = hecho.stdout + "\n" + hecho.stderr

    dumps = os.path.join(proyecto, "dumps")
    principal = os.path.join(dumps, "main.srcx.phir")
    compila = os.path.isfile(principal)
    unidades = {}
    if os.path.isdir(dumps):
        for nombre in sorted(os.listdir(dumps)):
            if nombre.endswith(".phir") and nombre != "main.srcx.phir":
                unidades[nombre] = _sha(os.path.join(dumps, nombre))
    return Corrida(
        compila=compila,
        phir=_sha(principal) if compila else None,
        unidades=unidades,
        salida=[l.strip() for l in texto.splitlines()
                if l.strip().startswith("SONDA:")],
        codigos=sorted(set(_CODIGO.findall(texto))),
    )


def _veredicto(a: Corrida, b: Corrida) -> str:
    if a.compila != b.compila:
        return "RECHAZO"
    if not a.compila:
        return "NO COMPILA"         # la sonda está mal escrita: no mide nada
    if a.phir != b.phir:
        return "FUGA"
    if a.salida != b.salida or a.codigos != b.codigos:
        return "TARDIA"
    return "IGUAL"


def main(argv: List[str]) -> int:
    filtro = argv[1] if len(argv) > 1 else ""
    elegidas = [s for s in SONDAS if filtro in s.nombre]
    if not elegidas:
        print(f"ninguna sonda contiene '{filtro}'. Hay: "
              + ", ".join(s.nombre for s in SONDAS))
        return 2

    base = tempfile.mkdtemp(prefix="suriax_sondas_")
    invalidas = 0
    try:
        for sonda in elegidas:
            proyecto = os.path.join(base, sonda.nombre)
            a = _corre(proyecto, sonda, sonda.lib_a)
            b = _corre(proyecto, sonda, sonda.lib_b)
            veredicto = _veredicto(a, b)
            if veredicto == "NO COMPILA":
                invalidas += 1
            cambiaron = sorted(u for u in set(a.unidades) | set(b.unidades)
                               if a.unidades.get(u) != b.unidades.get(u))
            print(f"{veredicto:<10} {sonda.nombre}")
            print(f"           cambia: {sonda.hecho}")
            print(f"           A: {' | '.join(a.salida) or '(sin salida)'}"
                  f" {a.codigos or ''}")
            print(f"           B: {' | '.join(b.salida) or '(sin salida)'}"
                  f" {b.codigos or ''}")
            print(f"           unidades de librería que cambiaron: "
                  f"{', '.join(cambiaron) or 'ninguna'}")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    # una sonda que no compila en ninguna versión no midió nada: se dice
    return 1 if invalidas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
