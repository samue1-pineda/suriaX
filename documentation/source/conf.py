"""Configuración de Sphinx para la documentación de suriaX.

Dos decisiones que explican casi todo el archivo:

1. **La documentación del proyecto vive en Markdown** (``ARCHITECTURE.md``,
   ``docs/*.md``, los README de cada subsistema) y se escribe ahí porque es
   lo que se lee desde GitHub. Reescribirla a reStructuredText sería
   duplicarla y condenarla a desincronizarse, así que MyST la lee tal cual.

2. **Los archivos de la raíz no se copian a mano.** Sphinx solo mira dentro
   de ``source/``, y un ``cp`` en el workflow haría que el build local y el
   de CI fueran distintos. En vez de eso, este mismo archivo los copia al
   arrancar (``config-inited``): ``make html`` y la Action producen
   exactamente el mismo sitio.

Ver https://www.sphinx-doc.org/en/master/usage/configuration.html
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

#: URL base para enlazar al código fuente desde la documentación. GitHub usa
#: rutas distintas para archivos y directorios, y redirige de una a otra: usar
#: la correcta desde el principio evita una redirección por enlace.
GITHUB_BLOB = "https://github.com/samue1-pineda/suriaX/blob/main"
GITHUB_TREE = "https://github.com/samue1-pineda/suriaX/tree/main"

# -- Información del proyecto ------------------------------------------------

project = "suriaX"
copyright = "2026, Samuel Pineda"
author = "Samuel Pineda"

# La versión se LEE de 'version.py' (raíz del repo), que es su fuente única.
# Estaba escrita aquí a mano y en 'CMakeLists.txt' a mano, y los dos números
# habían dejado de coincidir: el sitio publicado y el artefacto nativo decían
# cosas distintas del mismo commit.
_RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)
from version import VERSION as release  # noqa: E402

version = release

# -- Configuración general ---------------------------------------------------

extensions = [
    "myst_parser",             # Markdown (CommonMark + extensiones)
    "sphinx.ext.autodoc",      # docstrings del frontend Python, cuando se documente
    "sphinx.ext.viewcode",     # enlace al fuente desde el API
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
    "sphinxcontrib.mermaid",   # los diagramas de ARCHITECTURE.md, renderizados
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "_appendices.rst"]
language = "es"

# Los dos formatos conviven: las páginas nuevas en Markdown, las antiguas en
# reStructuredText, sin migración forzosa.
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# -- MyST --------------------------------------------------------------------

myst_enable_extensions = [
    "colon_fence",     # ::: bloques de directiva sin backticks
    "deflist",         # listas de definición
    "linkify",         # URLs sueltas -> enlaces
    "substitution",
    "tasklist",        # [x] del ROADMAP
]
#: Ancla automática hasta ``###``: permite enlazar a una sección de un .md.
myst_heading_anchors = 3
#: Los .md del repo se enlazan entre ellos con rutas relativas ('./ROADMAP.md');
#: MyST las convierte en enlaces internos del sitio.
myst_all_links_external = False
#: Un bloque ```mermaid del Markdown se trata como la directiva de mermaid, así
#: que el diagrama del pipeline se DIBUJA en vez de mostrarse como texto.
myst_fence_as_directive = ["mermaid"]

# -- todo --------------------------------------------------------------------

#: El proyecto está en Pre-Alpha: lo pendiente se muestra, no se esconde.
todo_include_todos = True

# -- HTML --------------------------------------------------------------------

html_theme = "furo"
html_static_path = ["_static"]
#: Copiado tal cual a la raíz del sitio. Contiene '.nojekyll': sin ese archivo,
#: un despliegue por rama ignoraría los directorios que empiezan por '_' y el
#: sitio saldría sin estilos. El despliegue por Actions no usa Jekyll, pero el
#: archivo cuesta nada y cubre el día que se cambie de método.
html_extra_path = ["_extra"]
#: Página de proyecto de GitHub Pages: el sitio cuelga de /suriaX/.
html_baseurl = "https://samue1-pineda.github.io/suriaX/"
html_title = f"suriaX {release}"
html_short_title = "suriaX"
html_theme_options = {
    "source_repository": "https://github.com/samue1-pineda/suriaX/",
    "source_branch": "main",
    "source_directory": "documentation/source/",
}

# -- linkcheck ---------------------------------------------------------------

#: El sitio enlaza al código en github.com; comprobar decenas de esas URLs
#: choca con el límite de tasa y el comprobador se queda esperando. Los
#: enlaces internos al repositorio ya los garantiza el reescritor (solo
#: enlaza lo que existe), así que aquí se revisa lo demás.
linkcheck_ignore = [r"https://github\.com/samue1-pineda/suriaX/(blob|tree)/.*"]
linkcheck_timeout = 15
linkcheck_retries = 1

# -- intersphinx -------------------------------------------------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# -- Documentación que vive en la raíz del repositorio -----------------------

#: (origen relativo a la raíz del repo, destino relativo a source/)
REPO_DOCS: tuple[tuple[str, str], ...] = (
    # Documentos del proyecto: se leen desde GitHub y desde el sitio, así que
    # su fuente sigue siendo el archivo del repositorio.
    ("ARCHITECTURE.md", "repo/ARCHITECTURE.md"),
    ("ROADMAP.md", "repo/ROADMAP.md"),
    ("DESIGN_PRINCIPLES.md", "repo/DESIGN_PRINCIPLES.md"),
    ("CONTRIBUTING.md", "repo/CONTRIBUTING.md"),
    # Referencia que produce el propio compilador: la gramática es la fuente de
    # verdad sintáctica y el vocabulario de tokens su tabla de terminales. Se
    # publican desde donde viven, sin copia editable en medio.
    ("docs/gramar/grammar.ebnf", "repo/grammar.ebnf"),
    ("docs/gramar/t_types.md", "repo/t_types.md"),
    # La guía de hooks/dunders/traits vive junto a las librerías, que es donde
    # se escribe: se publica desde ahí para no tener dos versiones del mismo
    # vocabulario (el capítulo del sitio y el archivo que lee quien abre lib/).
    ("lib/HOOKS.md", "repo/hooks.md"),
    # Documentos técnicos de un subsistema, con más detalle del que cabe en un
    # capítulo: se publican como apéndices.
    ("V0/src/HIR/PROTOBUF_BRIDGE.md", "repo/protobuf_bridge.md"),
    ("runtime/interpreter/ARQUITECTURA.md", "repo/interpreter_internals.md"),
    ("web/README.md", "repo/web_backend.md"),
    ("htims/readme.md", "repo/htims.md"),
)

_SOURCE_DIR = Path(__file__).parent
_REPO_ROOT = _SOURCE_DIR.parents[1]


#: ``origen en el repo -> nombre del documento`` para reescribir enlaces.
_DOC_BY_SOURCE = {source: target for source, target in REPO_DOCS}

#: Enlace Markdown ``[texto](destino)`` con destino relativo (no http/mailto/#).
#: El texto puede ser una imagen, como una medalla:
#: ``[![Versión](https://img.shields.io/...)](version.py)``. Sin la primera
#: alternativa, el ``]`` de la imagen cortaba el texto, el enlace a
#: ``version.py`` llegaba sin reescribir a Sphinx y, con ``-W``, su
#: ``myst.xref_missing`` rompía el build (ROADMAP.md, commit 130b528).
_MD_LINK = re.compile(r"\[((?:!\[[^\]]*\]\([^)\s]*\)|[^\]])*)\]"
                      r"\((?!https?://|mailto:|#)([^)\s]+)\)")


def _rewrite_link(origin_rel: str, target: str) -> str | None:
    """Reescribe un enlace relativo del repositorio.

    Un ``.md`` del repositorio enlaza a sus vecinos con rutas relativas
    (``docs/hir.md``, ``../test/e2e/x.py``). En el sitio publicado esas rutas
    no existen, así que:

    - si el destino es OTRO documento que también se publica, se enlaza a su
      página (los dos viven en ``repo/``, así que basta el nombre);
    - si el destino EXISTE en el repositorio, se enlaza al fuente en GitHub
      (``/blob/`` para un archivo, ``/tree/`` para un directorio: GitHub
      redirige de uno a otro, y una redirección es un aviso evitable);
    - si NO existe, se devuelve ``None`` y el enlace se degrada a texto.

    Ese último caso es el que importa. Un documento puede referenciar algo
    que se renombró, que nunca llegó a escribirse o que todavía no está
    commiteado; publicarlo como enlace produce un 404 en el sitio y un fallo
    en cualquier comprobador. Que el enlace desaparezca solo, sin editar el
    documento original, mantiene el sitio sano sin pedirle a nadie que
    recuerde nada.

    La existencia se comprueba **sobre el árbol de trabajo**. En CI eso es
    exactamente el contenido del repositorio, que es lo que se publica; en
    local puede haber archivos sin commitear, y entonces el enlace se genera
    aunque en GitHub todavía no resuelva.
    """
    anchor = ""
    if "#" in target:
        target, _, anchor = target.partition("#")
        anchor = f"#{anchor}"
    if target == "":
        return anchor  # enlace a una sección del mismo documento

    resolved = _normalize((Path(origin_rel).parent / target).as_posix())

    published = _DOC_BY_SOURCE.get(resolved)
    if published is not None and (_REPO_ROOT / resolved).exists():
        return Path(published).name + anchor

    destination = _REPO_ROOT / resolved
    if destination.is_dir():
        return f"{GITHUB_TREE}/{resolved}{anchor}"
    if destination.is_file():
        return f"{GITHUB_BLOB}/{resolved}{anchor}"
    return None


def _replace_link(source: str, match: "re.Match[str]") -> str:
    """``[texto](destino)`` -> enlace reescrito, o solo el texto si no resuelve."""
    label, target = match.group(1), match.group(2)
    rewritten = _rewrite_link(source, target)
    if rewritten is None:
        # el destino no está en el repositorio: se conserva la referencia como
        # código, que sigue diciendo de qué habla, pero sin enlace roto.
        return f"`{label}`" if label else f"`{target}`"
    return f"[{label}]({rewritten})"


def _normalize(path: str) -> str:
    """Colapsa ``a/../b`` sin tocar el disco (los destinos pueden no existir)."""
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


#: Apéndices técnicos: se publican si su archivo está en el repositorio.
#: La lista se resuelve contra el checkout en vez de darse por hecha: un
#: subsistema puede documentarse antes de existir, o quedarse fuera de un
#: paquete recortado, y ni una cosa ni la otra debe romper la construcción
#: del sitio.
APPENDICES: tuple[tuple[str, str], ...] = (
    ("repo/protobuf_bridge", "El puente protobuf en detalle"),
    ("repo/interpreter_internals", "Interioridades del intérprete"),
    ("repo/web_backend", "Backend web: guía del paquete"),
    ("repo/htims", "HTIMS: extensiones del proyecto"),
)


def _write_appendix_toc(publicados: set[str]) -> None:
    """Escribe el ``toctree`` de apéndices con los que EXISTEN.

    Un ``toctree`` es estático y falla si nombra un documento ausente. Como la
    lista depende de qué haya en el checkout —hay documentación que vive junto
    a código todavía sin versionar—, se genera aquí, con la misma pasada que
    copia los archivos. Así el sitio se construye igual con el repositorio
    completo o con una parte.
    """
    lineas = [
        ".. Generado por conf.py: no editar a mano.",
        "",
        ".. toctree::",
        "   :maxdepth: 1",
        "   :caption: Referencia técnica",
        "",
    ]
    lineas += [f"   {doc}" for doc, _ in APPENDICES if doc in publicados]
    if len(lineas) == 6:            # ninguno disponible: un toctree vacío avisa
        lineas = [".. Generado por conf.py: no hay apéndices en este checkout."]
    (_SOURCE_DIR / "_appendices.rst").write_text("\n".join(lineas) + "\n",
                                                 encoding="utf-8")


def _sync_repo_docs(app, config) -> None:  # noqa: ANN001 - firma de Sphinx
    """Copia a ``source/repo/`` la documentación que vive en el repositorio.

    Se salta en silencio lo que no exista: el proyecto está vivo y un
    documento puede aún no estar escrito; eso no debe romper el build.
    """
    target_root = _SOURCE_DIR / "repo"
    target_root.mkdir(exist_ok=True)
    publicados: set[str] = set()
    for source, target in REPO_DOCS:
        origin = _REPO_ROOT / source
        if not origin.is_file():
            continue
        publicados.add(target.removesuffix(".md"))
        destination = _SOURCE_DIR / target
        destination.parent.mkdir(parents=True, exist_ok=True)

        if origin.suffix == ".md":
            text = origin.read_text(encoding="utf-8")
            text = _MD_LINK.sub(lambda m: _replace_link(source, m), text)
            destination.write_text(text, encoding="utf-8")
        else:
            shutil.copyfile(origin, destination)
    _write_appendix_toc(publicados)


# -- Resaltado de suriaX -----------------------------------------------------

def _srcx_lexer():
    """Lexer de Pygments para ``.srcx``, construido con las keywords REALES.

    El vocabulario se importa de ``V0/include/t_types.py`` en vez de copiarse:
    es el mismo sitio del que sale ``--emit-lang-info`` para el editor. Si
    mañana entra una palabra clave, la documentación la resalta sin que nadie
    se acuerde de actualizar esta lista.
    """
    from pygments.lexer import RegexLexer, words
    from pygments.token import (Comment, Keyword, Name, Number, Operator,
                                Punctuation, String, Text)

    keywords = ("fn", "struct", "enum", "if", "else", "while", "return",
                "match", "case", "break", "continue", "const", "var", "true",
                "false", "null", "and", "or", "not")
    types = ("int", "float", "bool", "char", "str", "void", "type", "ptr")
    try:
        sys.path.insert(0, str(_REPO_ROOT / "V0"))
        from include.t_types import KEYWORDS  # type: ignore[import-not-found]
        keywords = tuple(sorted(KEYWORDS))
    except Exception:  # noqa: BLE001 - sin el compilador, la lista de reserva
        pass

    class SuriaXLexer(RegexLexer):
        name = "suriaX"
        aliases = ["srcx", "suriax"]
        filenames = ["*.srcx", "*.libsrx"]

        tokens = {
            "root": [
                (r"//[^\n]*", Comment.Single),
                (r"/-", Comment.Multiline, "blockcomment"),
                (r"#(import|export|extern|test|from)\b", Comment.Preproc),
                (r"@[A-Za-z_]\w*", Name.Decorator),
                (r"__\w+__", Name.Function.Magic),
                (r'f?"', String, "string"),
                (r"'(\\.|[^'\\])'", String.Char),
                (r"\d+\.\d+", Number.Float),
                (r"\d+", Number.Integer),
                (words(types, suffix=r"\b"), Keyword.Type),
                (words(keywords, suffix=r"\b"), Keyword),
                (r"->|==|!=|<=|>=|[-+*/<>=&?]", Operator),
                (r"[{}()\[\];:,.]", Punctuation),
                (r"[A-Za-z_]\w*", Name),
                (r"\s+", Text),
                (r".", Text),
            ],
            "string": [
                (r'[^"\\{]+', String),
                (r"\\.", String.Escape),
                (r"\{[^}]*\}", String.Interpol),
                (r'"', String, "#pop"),
            ],
            "blockcomment": [
                (r"[^-]+", Comment.Multiline),
                (r"-/", Comment.Multiline, "#pop"),
                (r"-", Comment.Multiline),
            ],
        }

    return SuriaXLexer


def setup(app):  # noqa: ANN001, ANN201 - firma de Sphinx
    app.connect("config-inited", _sync_repo_docs)
    try:
        app.add_lexer("srcx", _srcx_lexer())
    except Exception:  # noqa: BLE001 - sin Pygments no hay resaltado, no un fallo
        pass
    return {"parallel_read_safe": True, "parallel_write_safe": True}
