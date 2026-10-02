"""La frontera entre el COMPILADOR y el tooling (suriniX).

Dos productos conviven en este repositorio: el compilador —que convierte un
``.srcx`` en artefactos— y el tooling que lo rodea (pedirlo desde una
terminal, decidir dónde van los volcados, enseñarlo en una página). La
dirección de la dependencia es una sola: **suriniX conoce al compilador y el
compilador no conoce a suriniX**.

No es purismo. Un compilador que sabe formatear para una terminal o que lee
el yaml del proyecto no se puede embeber en un editor, en un servidor ni en
otra herramienta sin arrastrar esas decisiones — y el playground y ``suri``
ya son dos consumidores que lo embeben.

Se comprueba sobre el CÓDIGO FUENTE, no importando nada: es el mismo método
que protege la frontera de ``htims/`` (``test_htims_no_importa_el_frontend``),
y funciona aunque el módulo cruzado no se pueda importar en esta máquina.

La lista de cruces conocidos solo puede ENCOGER. Añadir uno nuevo rompe esta
prueba; quitar el último es el final de la separación (ver ARCHITECTURE.md,
*La frontera*).
"""

import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

#: Lo que ES el compilador: convierte fuente en artefactos.
_COMPILADOR = (
    os.path.join("V0", "src"),
    os.path.join("V0", "driver"),
    os.path.join("V0", "include"),
    os.path.join("V0", "error_handler"),
    "runtime",
    "htims",
)

#: Lo que es TOOLING (suriniX): todo lo que rodea a compilar.
_TOOLING = ("config", "cli", "suri", "playground")

#: Cruces que ya existían cuando se declaró la frontera, con lo que hace
#: falta para cerrarlos. Es una lista que solo puede ENCOGER: es a la vez la
#: deuda reconocida y el plan de la mudanza.
_CONOCIDOS = {
    os.path.join("V0", "driver", "pipeline.py"): (
        "el driver lee el yaml y escribe los volcados por su cuenta; "
        "cerrarlo es que reciba la configuración ya cargada y un destino "
        "para sus volcados"
    ),
}


def _archivos_del_compilador():
    """Los ``.py`` del compilador, con su ruta relativa al repositorio."""
    for base in _COMPILADOR:
        raiz = os.path.join(_REPO, base)
        if not os.path.isdir(raiz):
            continue
        for carpeta, dirs, nombres in os.walk(raiz):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for nombre in sorted(n for n in nombres if n.endswith(".py")):
                ruta = os.path.join(carpeta, nombre)
                yield os.path.relpath(ruta, _REPO), ruta


def _modulos_importados(ruta: str):
    """Los módulos RAÍZ que importa un archivo, leyendo su AST.

    Con ``ast`` y no con una búsqueda de texto porque un comentario o una
    cadena que mencione ``config`` no es un import, y una prueba que salta
    con eso deja de creerse.
    """
    with open(ruta, encoding="utf-8") as fh:
        arbol = ast.parse(fh.read(), filename=ruta)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                yield alias.name.split(".")[0]
        elif isinstance(nodo, ast.ImportFrom):
            # 'from . import x' es relativo: nunca sale del paquete
            if nodo.level == 0 and nodo.module:
                yield nodo.module.split(".")[0]


def test_el_compilador_no_conoce_al_tooling():
    """La regla, sobre todo el árbol del compilador."""
    nuevos = []
    for relativa, ruta in _archivos_del_compilador():
        cruzados = {m for m in _modulos_importados(ruta) if m in _TOOLING}
        if not cruzados:
            continue
        if relativa in _CONOCIDOS:
            continue
        nuevos.append(f"{relativa} importa {sorted(cruzados)}")
    assert not nuevos, (
        "cruces NUEVOS de la frontera compilador -> suriniX:\n  " +
        "\n  ".join(nuevos) +
        "\n\nEl compilador no conoce al tooling (ver ARCHITECTURE.md, 'La "
        "frontera'). Si de verdad hace falta, el módulo tiene que recibir lo "
        "que necesita del llamador en vez de ir a buscarlo.")


def test_los_cruces_conocidos_siguen_siendo_ciertos():
    """Un cruce que ya se cerró tiene que salir de la lista.

    Sin esto la lista se convertiría en una excusa permanente: seguiría
    permitiendo algo que ya nadie hace, y el día que alguien lo volviera a
    escribir la prueba callaría.
    """
    obsoletos = []
    for relativa in sorted(_CONOCIDOS):
        ruta = os.path.join(_REPO, relativa)
        if not os.path.isfile(ruta):
            obsoletos.append(f"{relativa} ya no existe")
            continue
        if not any(m in _TOOLING for m in _modulos_importados(ruta)):
            obsoletos.append(f"{relativa} ya no cruza la frontera")
    assert not obsoletos, (
        "cruces ya cerrados que siguen en la lista de conocidos:\n  " +
        "\n  ".join(obsoletos) +
        "\n\nQuítalos de _CONOCIDOS: la lista solo puede encoger.")


def test_el_tooling_si_puede_conocer_al_compilador():
    """La dirección permitida, comprobada sobre un consumidor real.

    No es simetría: el playground pide los artefactos con
    'driver.artifacts.collect()' y no analiza nada por su cuenta. Que ESA
    dirección exista es lo que hace que la frontera valga la pena.
    """
    ruta = os.path.join(_REPO, "playground", "server.py")
    assert os.path.isfile(ruta), (
        f"no existe {ruta}: si el playground se movió, esta prueba tiene que "
        "apuntar a su nueva ubicación (o a otro consumidor real del driver)")
    with open(ruta, encoding="utf-8") as fh:
        fuente = fh.read()
    assert "artifacts" in fuente, (
        "el playground dejó de usar el driver: si reimplementa el frontend, "
        "habría dos compiladores que mantener sincronizados")


# --------------------------------------------------------------------------- #
# las BANDERAS también tienen dueño
# --------------------------------------------------------------------------- #
# La regla: lo que hace falta para compilar (y para leer lo que la compilación
# produjo) es del compilador; lo que es una comodidad alrededor de compilar es
# de suriniX. Sin una tabla explícita, la separación se decide bandera a
# bandera el día de la mudanza, que es cuando peor se decide.

def _parser():
    sys.path.insert(0, os.path.join(_REPO, "V0"))
    from cli.args import DUENO, build_parser
    return DUENO, build_parser()


def test_toda_bandera_tiene_dueno_declarado():
    dueno, parser = _parser()
    declaradas = set()
    for accion in parser._actions:
        if accion.dest == "help":
            continue
        # la posicional ('source') no tiene '--'; las demás, su forma larga
        nombre = accion.option_strings[-1] if accion.option_strings \
            else accion.dest
        declaradas.add(nombre)
    sin_dueno = sorted(declaradas - set(dueno))
    assert not sin_dueno, (
        f"banderas sin dueño declarado: {sin_dueno}\n"
        "Añádelas a 'DUENO' en V0/cli/args.py: lo que hace falta para "
        "compilar es del compilador, lo que rodea a compilar es de suriniX.")


def test_no_sobran_entradas_en_la_tabla():
    """Una bandera que ya no existe no puede seguir teniendo dueño: la tabla
    dejaría de describir el programa."""
    dueno, parser = _parser()
    reales = {a.option_strings[-1] if a.option_strings else a.dest
              for a in parser._actions if a.dest != "help"}
    fantasmas = sorted(set(dueno) - reales)
    assert not fantasmas, f"'DUENO' nombra banderas que ya no existen: {fantasmas}"


def test_los_dos_duenos_son_los_unicos_valores():
    dueno, _p = _parser()
    valores = set(dueno.values())
    assert valores <= {"compilador", "surinix"}, valores
    # las dos categorías tienen que estar POBLADAS: si una queda vacía, la
    # tabla no está clasificando nada.
    assert "compilador" in valores and "surinix" in valores
