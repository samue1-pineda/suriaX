"""La documentación no se queda vieja sola: aquí se le pide cuentas.

Estos tests existen porque pasó. ``lib/HOOKS.md`` daba ``__index__`` por
pendiente cuando ya ejecutaba, no mencionaba ``__index_set__`` ni ``__eq__``,
y afirmaba que los dunders cross-módulo no funcionaban — tres cosas falsas que
nadie detectó porque ningún test miraba la documentación.

Lo que se comprueba es lo VERIFICABLE mecánicamente: que los inventarios
(hooks del lenguaje, banderas de la CLI, códigos de salida) estén completos.
La prosa sigue siendo responsabilidad de quien escribe.
"""

from __future__ import annotations

import os
import re
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_V0 = os.path.join(_REPO_ROOT, "V0")
for _p in (_REPO_ROOT, _V0):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _leer(rel: str) -> str:
    with open(os.path.join(_REPO_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------- #
# el vocabulario de hooks
# --------------------------------------------------------------------------- #

def test_el_glosario_documenta_todos_los_hooks():
    """``HOOK_SPECS`` es la fuente de verdad; el glosario debe cubrirla entera."""
    from src.frontend.semantic.hooks import HOOK_SPECS

    doc = _leer("lib/HOOKS.md")
    faltan = [f"__{nombre}__" for nombre in HOOK_SPECS
              if f"__{nombre}__" not in doc]
    assert not faltan, (
        f"hooks sin documentar en lib/HOOKS.md: {faltan}. El glosario es lo "
        "que lee quien escribe una librería")


def test_el_glosario_no_inventa_hooks():
    """Lo contrario: una fila del glosario que ya no exista en el compilador."""
    from src.frontend.semantic.hooks import HOOK_SPECS

    doc = _leer("lib/HOOKS.md")
    # la tabla del glosario: filas '| `__x__` | ...'
    documentados = set(re.findall(r"\|\s*`__([a-z_]+)__`\s*\|", doc))
    inexistentes = sorted(documentados - set(HOOK_SPECS))
    assert not inexistentes, (
        f"el glosario documenta hooks que el compilador no reconoce: "
        f"{inexistentes}")


def test_el_esquema_del_hir_coincide_en_el_glosario_y_en_el_proto():
    """El enum del esquema y el vocabulario de la Semántica son el mismo
    conjunto: si uno gana un hook, el otro también."""
    from src.HIR.stubs import load_hir_pb2
    from src.frontend.semantic.hooks import HOOK_SPECS

    pb = load_hir_pb2()
    del_proto = {name.lower() for name in pb.HookKind.keys()
                 if name not in ("HOOK_UNSPECIFIED", "EXTENDED")}
    assert del_proto == set(HOOK_SPECS), (
        f"desajuste entre hir.proto y semantic/hooks.py: "
        f"solo en proto={sorted(del_proto - set(HOOK_SPECS))}, "
        f"solo en HOOK_SPECS={sorted(set(HOOK_SPECS) - del_proto)}")


# --------------------------------------------------------------------------- #
# la CLI
# --------------------------------------------------------------------------- #

def _flags_del_argparse(rel: str) -> set[str]:
    """Banderas largas declaradas en el ``argparse`` de un entrypoint."""
    fuente = _leer(rel)
    encontradas = set(re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', fuente))
    # Guarda contra el falso verde: si el argparse se mueve de archivo, este
    # test pasaria comparando el conjunto VACIO contra la documentacion. Pasó
    # al separar la CLI del driver.
    assert encontradas, f"no se encontro ningun 'add_argument' en {rel}"
    return encontradas


def _documentada(flag: str, doc: str) -> bool:
    """La bandera aparece entre comillas, con o sin su argumento
    (``--emit-hir`` cuenta como documentada si el texto dice
    ``--emit-hir [ARCHIVO]``)."""
    return re.search(rf"`{re.escape(flag)}(?:[ =][^`]*)?`", doc) is not None


def test_flags_md_documenta_todas_las_banderas_del_compilador():
    doc = _leer("FLAGS.md")
    faltan = sorted(f for f in _flags_del_argparse("V0/cli/args.py")
                    if not _documentada(f, doc))
    assert not faltan, (
        f"banderas sin documentar en FLAGS.md: {faltan} — FLAGS.md dice ser "
        "la referencia COMPLETA generada de los argparse reales")


def test_flags_md_documenta_las_banderas_del_interprete():
    doc = _leer("FLAGS.md")
    faltan = sorted(f for f in _flags_del_argparse("runtime/interpreter/main.py")
                    if not _documentada(f, doc))
    assert not faltan, f"banderas del intérprete sin documentar: {faltan}"


def test_los_codigos_de_salida_documentados_existen_en_el_codigo():
    """Cada código que FLAGS.md promete tiene que existir en el compilador.

    Los códigos dejaron de ser números sueltos dentro de ``V0/main.py``: viven
    como constantes con nombre en ``driver/options.py``, que es lo que
    consulta cualquier front (la CLI de hoy, ``suri run`` mañana). Se
    comparan contra ESAS, no contra un grep de literales."""
    from driver import options

    flags = _leer("FLAGS.md")
    seccion = flags.split("Códigos de salida", 1)[1]
    documentados = {int(m) for m in re.findall(r"\|\s*`(\d+)`\s*\|", seccion)}
    definidos = {valor for nombre, valor in vars(options).items()
                 if nombre.startswith("EXIT_") and isinstance(valor, int)}
    # 70 lo produce el intérprete (runtime/interpreter/), no el driver
    faltan = sorted(c for c in documentados - definidos if c != 70)
    assert not faltan, (
        f"FLAGS.md documenta códigos de salida que el driver no define: "
        f"{faltan} (ver driver/options.py)")


def test_los_codigos_del_driver_estan_documentados():
    """El otro lado: un código nuevo en el driver tiene que aparecer en
    FLAGS.md, que dice ser la referencia completa."""
    from driver import options

    flags = _leer("FLAGS.md")
    seccion = flags.split("Códigos de salida", 1)[1]
    documentados = {int(m) for m in re.findall(r"\|\s*`(\d+)`\s*\|", seccion)}
    definidos = {valor for nombre, valor in vars(options).items()
                 if nombre.startswith("EXIT_") and isinstance(valor, int)}
    faltan = sorted(definidos - documentados)
    assert not faltan, (
        f"el driver define códigos de salida que FLAGS.md no documenta: {faltan}")


# --------------------------------------------------------------------------- #
# el esquema del HIR en la documentación publicada
# --------------------------------------------------------------------------- #

def test_la_version_tiene_una_sola_fuente():
    """``version.py`` es la fuente única de la versión del proyecto.

    Regresión: estaba escrita a mano en ``CMakeLists.txt`` (``0.1.4``) y en
    ``documentation/source/conf.py`` (``0.2.0``). Dos números para el mismo
    commit, y ninguna forma de saber cuál mentía. Esta prueba exige que los
    consumidores la LEAN en vez de repetirla."""
    import re

    from version import VERSION

    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION), (
        f"la versión tiene que ser MAYOR.MENOR.PARCHE, es {VERSION!r}")

    cmake = _leer("CMakeLists.txt")
    assert "version.py" in cmake, (
        "CMakeLists.txt tiene que LEER la versión de version.py, no repetirla")
    assert not re.search(r"VERSION\s+\d+\.\d+\.\d+", cmake), (
        "CMakeLists.txt volvió a escribir la versión a mano")

    conf = _leer("documentation/source/conf.py")
    assert "from version import" in conf, (
        "conf.py tiene que LEER la versión de version.py, no repetirla")

    # El compilador y el contrato del LSP también la leen: sin esto,
    # 'suriaX --version' podría anunciar una y el sitio publicar otra.
    for ruta in ("V0/cli/args.py", "V0/include/lang_info.py"):
        assert "from version import VERSION" in _leer(ruta), (
            f"{ruta} tiene que LEER la versión de version.py, no repetirla")


def test_ningun_documento_escribe_la_version_a_mano():
    """Los documentos de portada NO repiten el número de versión.

    Regresión de la que salió ``version.py``: ``README.md`` decía 0.1.4,
    ``README_ES.md`` 0.1.5 y el ROADMAP 0.2.0, los tres a la vez y para el
    mismo commit. Un número escrito a mano en un documento no tiene forma de
    enterarse de que subió la versión, así que envejece siempre; el estado
    se anuncia con la medalla, que lee ``version.py``.

    Se prohíbe la FORMA con la que el proyecto anuncia su versión actual
    (``V.1.2.3``), no cualquier número: "las regiones se retiraron en
    v0.2.0" es un hecho histórico y no caduca.
    """
    import re

    idiom = re.compile(r"\bV\.\d+\.\d+")
    for ruta in ("README.md", "README_ES.md", "ROADMAP.md"):
        texto = _leer(ruta)
        encontrados = idiom.findall(texto)
        assert not encontrados, (
            f"{ruta} anuncia la versión a mano ({encontrados}): usa la medalla, "
            "que sale de version.py")

    # ...y las dos portadas tienen que llevar esa medalla, o el número no
    # aparece en ninguna parte.
    for ruta in ("README.md", "README_ES.md"):
        assert "badges/version.json" in _leer(ruta), (
            f"{ruta} perdió la medalla de versión")


def test_la_doc_publicada_nombra_la_version_de_esquema_vigente():
    """``documentation/source/hir.rst`` enseña un ``.phir`` de ejemplo: si el
    esquema sube y el ejemplo no, la web enseña un formato que ya no existe."""
    from src.HIR.emmit_IR import SCHEMA_VERSION
    doc = _leer("documentation/source/hir.rst")
    assert f"schema_version: {SCHEMA_VERSION}" in doc, (
        f"hir.rst no muestra 'schema_version: {SCHEMA_VERSION}' en su ejemplo")


# --------------------------------------------------------------------------- #
# el catálogo de errores
# --------------------------------------------------------------------------- #

def _codigos_del_compilador() -> set[str]:
    """Todos los códigos que el compilador puede emitir, por familia.

    Se leen del CÓDIGO, no de una lista escrita a mano: una lista paralela se
    desincroniza igual que la documentación y no arregla nada.
    """
    codigos: set[str] = set()
    # frontend: 'code="XXX000"' en el constructor de cada clase
    for archivo in (_REPO_ROOT + "/V0/error_handler",):
        for nombre in os.listdir(archivo):
            if not nombre.endswith(".py"):
                continue
            with open(os.path.join(archivo, nombre), encoding="utf-8") as fh:
                codigos |= set(re.findall(r'code="([A-Z]{3}\d{3})"', fh.read()))
    # intérprete: 'code = "RT000"' como atributo de clase
    codigos |= set(re.findall(r'code = "([A-Z]{3}\d{3})"',
                              _leer("runtime/interpreter/errors.py")))
    # HTIMS y configuración: constantes de módulo 'EXT001 = "EXT001"'
    for rel in ("htims/errors.py", "config/errors.py"):
        codigos |= set(re.findall(r'^([A-Z]{3}\d{3}) = ', _leer(rel), re.M))
    return codigos


def _codigos_documentados() -> set[str]:
    doc = _leer("documentation/source/errors.rst")
    return set(re.findall(r"``([A-Z]{3}\d{3})``\s", doc))


def test_todo_codigo_del_compilador_esta_documentado():
    """El catálogo dice ser la referencia COMPLETA de todas las familias.

    Este test existe porque no lo era: la familia ``EXT`` entera —18 códigos—
    figuraba en la tabla de familias y no tenía ni una fila.
    """
    faltan = sorted(_codigos_del_compilador() - _codigos_documentados())
    assert not faltan, (
        f"códigos sin documentar en documentation/source/errors.rst: {faltan}")


def test_el_catalogo_no_documenta_codigos_inexistentes():
    """El otro lado: un código retirado del compilador tiene que salir del
    catálogo. Pasó con ``SEM012``/``SEM020``/``PAR022`` al quitar las regiones
    y con ``SEM025`` al implementar el drop de campos.

    Los ``WEB`` viven en TypeScript (``web/src/``), fuera del alcance de este
    recuento; se excluyen a propósito y no por descuido.
    """
    documentados = {c for c in _codigos_documentados() if not c.startswith("WEB")}
    inexistentes = sorted(documentados - _codigos_del_compilador())
    assert not inexistentes, (
        f"el catálogo documenta códigos que ya no existen: {inexistentes}")



# --------------------------------------------------------------------------- #
# el sitio publicado (GitHub Pages)
# --------------------------------------------------------------------------- #

def test_el_workflow_de_docs_escucha_a_todas_sus_fuentes():
    """``docs.yml`` se dispara con TODO lo que ``conf.py`` publica.

    ``conf.py`` copia al sitio archivos que viven junto al código que
    documentan (``lib/HOOKS.md``, ``web/README.md``, la ARQUITECTURA del
    intérprete...). El filtro ``paths`` del workflow nombraba solo
    ``documentation/``, ``docs/`` y los ``.md`` de la raíz, así que editar
    cualquiera de los otros NO reconstruía la página: el repositorio quedaba
    al día y lo publicado no, que es el peor de los dos estados porque nada
    lo señala.

    La lista de ``paths`` no se puede generar (YAML no ejecuta código), así
    que se comprueba.
    """
    import re

    import importlib.util

    # Importar 'conf.py' es inocuo: las copias al sitio las dispara Sphinx
    # ('config-inited'), no la carga del módulo.
    conf_path = os.path.join(_REPO_ROOT, "documentation", "source", "conf.py")
    spec = importlib.util.spec_from_file_location("_conf_docs", conf_path)
    conf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conf)

    workflow = _leer(".github/workflows/docs.yml")
    # el bloque 'push:' es el que decide si se reconstruye y se publica
    push = workflow.split("pull_request:", 1)[0]
    declarados = set(re.findall(r'^\s*-\s*"([^"]+)"', push, re.M))

    def cubierto(origen: str) -> bool:
        if origen in declarados:
            return True
        # un comodín de carpeta ('documentation/**') cubre lo que hay debajo,
        # y '*.md' cubre los documentos de la raíz
        for patron in declarados:
            if patron.endswith("/**") and origen.startswith(patron[:-2]):
                return True
            if patron == "*.md" and "/" not in origen and origen.endswith(".md"):
                return True
        return False

    faltan = sorted(o for o, _destino in conf.REPO_DOCS if not cubierto(o))
    assert not faltan, (
        "docs.yml no se dispara al editar estos archivos, que conf.py publica: "
        f"{faltan}")

    # el título del sitio lleva la versión: si sube y la página no se
    # reconstruye, el sitio anuncia una versión que ya no es.
    assert cubierto("version.py"), (
        "docs.yml tiene que reconstruir el sitio cuando cambia version.py: "
        "el título de la página lo lleva")


# --------------------------------------------------------------------------- #
# la gramática (docs/gramar/grammar.ebnf)
# --------------------------------------------------------------------------- #

def _gramatica() -> dict[str, str]:
    """Las reglas de la EBNF, ``nombre -> cuerpo``, sin comentarios."""
    texto = re.sub(r"\(\*.*?\*\)", "", _leer("docs/gramar/grammar.ebnf"), flags=re.S)
    return dict(re.findall(r"^([A-Za-z_]+)\s*=\s*(.*?);\s*$", texto, flags=re.S | re.M))


def test_la_gramatica_no_usa_reglas_sin_definir():
    reglas = _gramatica()
    usadas: set[str] = set()
    for cuerpo in reglas.values():
        sin_terminales = re.sub(r'"[^"]*"|\'[^\']*\'|\?[^?]*\?', "", cuerpo)
        usadas |= set(re.findall(r"\b[A-Za-z_]+\b", sin_terminales))
    faltan = sorted(usadas - set(reglas) - {"EOF"})
    assert not faltan, f"la EBNF usa reglas que no define: {faltan}"


def test_la_gramatica_nombra_las_palabras_reservadas_del_lexer():
    """La EBNF quedó desactualizada una vez; esto ata su vocabulario al del
    lexer (``KEYWORDS``): una palabra reservada nueva, o una retirada, la
    obliga a cambiar."""
    sys.path.insert(0, os.path.join(_REPO_ROOT, "V0"))
    from include.t_types import KEYWORDS
    reglas = _gramatica()
    escritas: set[str] = set()
    for categoria in ("type_kw", "decl_kw", "control_kw", "memory_kw", "error_kw",
                      "test_kw", "word_op", "word_lit"):
        escritas |= set(re.findall(r'"([^"]+)"', reglas[categoria]))
    assert escritas == set(KEYWORDS), (
        f"faltan en la EBNF: {sorted(set(KEYWORDS) - escritas)}; "
        f"sobran: {sorted(escritas - set(KEYWORDS))}")


def test_el_glosario_de_tokens_documenta_todos_los_tokens():
    """``docs/gramar/t_types.md`` llegó a omitir 33 tokens (las excepciones,
    ``with``, ``byte``, los operadores de bits...). Cada valor de
    ``TokenType`` tiene que aparecer por su nombre."""
    sys.path.insert(0, os.path.join(_REPO_ROOT, "V0"))
    from include.t_types import TokenType
    doc = _leer("docs/gramar/t_types.md")
    faltan = [t.name for t in TokenType if not re.search(r"\b" + t.name + r"\b", doc)]
    assert not faltan, f"tokens sin documentar en docs/gramar/t_types.md: {faltan}"
