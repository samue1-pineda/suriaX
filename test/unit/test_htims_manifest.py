"""HTIMS: lectura y validación de ``extends.srcx`` (``htims/manifest.py``).

El manifiesto se lee ANTES del léxico y con su propio parser, así que sus
diagnósticos son lo único que el usuario ve cuando lo escribe mal: cada test
comprueba el CÓDIGO y la POSICIÓN, que es el contrato con el editor.
"""

from __future__ import annotations

import os
import sys
import tempfile

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from htims import manifest as manifest_mod  # noqa: E402


# --------------------------------------------------------------------------- #
# andamiaje
# --------------------------------------------------------------------------- #

class _Project:
    """Proyecto temporal con los directorios que el manifiesto exige."""

    def __init__(self, text: str | None = None, *, dirs=("extensions/logic",
                                                         "extensions/calls")):
        self._tmp = tempfile.TemporaryDirectory(prefix="suriax-htims-")
        self.root = self._tmp.name
        for rel in dirs:
            os.makedirs(os.path.join(self.root, *rel.split("/")), exist_ok=True)
        if text is not None:
            with open(os.path.join(self.root, manifest_mod.MANIFEST_FNAME),
                      "w", encoding="utf-8") as fh:
                fh.write(text)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False


_VALID = (
    "# manifiesto del proyecto\n"
    "project:   MiJuego\n"
    "logic_dir: extensions/logic     # C++\n"
    "calls_dir: extensions/calls     # Python\n"
)


def _codes(errors):
    return [e.code for e in errors]


# --------------------------------------------------------------------------- #
# camino feliz
# --------------------------------------------------------------------------- #

def test_sin_manifiesto_no_hay_ni_error_ni_conjunto():
    """Un proyecto normal (la inmensa mayoría) no paga NADA por esta capa."""
    with _Project() as proj:
        man, errors = manifest_mod.parse(proj.root)
        assert man is None
        assert errors == []


def test_manifiesto_valido_resuelve_rutas_absolutas():
    with _Project(_VALID) as proj:
        man, errors = manifest_mod.parse(proj.root)
        assert errors == [], _codes(errors)
        assert man is not None
        assert man.project == "MiJuego"
        assert man.calls_dir == os.path.join(proj.root, "extensions", "calls")
        assert man.logic_dir == os.path.join(proj.root, "extensions", "logic")
        assert os.path.isabs(man.calls_dir)


def test_comentarios_y_comillas_son_transparentes():
    text = ('calls_dir: "extensions/calls"   # con comillas y comentario\n'
            "\n"
            "# una linea entera de comentario\n")
    with _Project(text) as proj:
        man, errors = manifest_mod.parse(proj.root)
        assert errors == [], _codes(errors)
        assert man.calls_dir.endswith(os.path.join("extensions", "calls"))


def test_logic_dir_es_opcional():
    """La lógica C++ llega con la VM+JIT: declarar sin implementar tiene que
    compilar, o nadie podría empezar."""
    with _Project("calls_dir: extensions/calls\n") as proj:
        man, errors = manifest_mod.parse(proj.root)
        assert errors == [], _codes(errors)
        assert man.logic_dir is None


def test_project_es_opcional_en_el_manifiesto():
    """El nombre lo declara el .py; el manifiesto solo es el respaldo."""
    with _Project("calls_dir: extensions/calls\n") as proj:
        man, _ = manifest_mod.parse(proj.root)
        assert man.project == ""


# --------------------------------------------------------------------------- #
# diagnósticos
# --------------------------------------------------------------------------- #

def test_linea_malformada_da_ext002_con_su_linea():
    with _Project("calls_dir: extensions/calls\nesto no es una clave\n") as proj:
        _, errors = manifest_mod.parse(proj.root)
        assert _codes(errors) == ["EXT002"]
        assert errors[0].line == 2


def test_directorio_inexistente_da_ext003_apuntando_al_valor():
    text = "calls_dir: extensions/calls\nlogic_dir: extensions/fantasma\n"
    with _Project(text) as proj:
        _, errors = manifest_mod.parse(proj.root)
        assert _codes(errors) == ["EXT003"]
        assert errors[0].line == 2
        # la columna cae sobre el VALOR, no sobre la clave: es lo que el
        # editor tiene que subrayar.
        assert errors[0].column > len("logic_dir")


def test_clave_desconocida_da_ext004():
    with _Project("calls_dir: extensions/calls\nlogik_dir: x\n") as proj:
        _, errors = manifest_mod.parse(proj.root)
        assert _codes(errors) == ["EXT004"]


def test_clave_duplicada_da_ext005_y_señala_la_primera():
    text = ("calls_dir: extensions/calls\n"
            "calls_dir: extensions/logic\n")
    with _Project(text) as proj:
        _, errors = manifest_mod.parse(proj.root)
        assert _codes(errors) == ["EXT005"]
        assert "línea 1" in errors[0].message


def test_valor_vacio_da_ext006():
    with _Project("calls_dir: extensions/calls\nproject:\n") as proj:
        _, errors = manifest_mod.parse(proj.root)
        assert _codes(errors) == ["EXT006"]


def test_falta_calls_dir_da_ext007():
    with _Project("project: MiJuego\n") as proj:
        _, errors = manifest_mod.parse(proj.root)
        assert _codes(errors) == ["EXT007"]


def test_se_reportan_TODOS_los_errores_de_una_vez():
    """Arreglar un manifiesto a razón de un error por compilación sería
    hostil: la capa acumula y reporta en bloque."""
    text = ("logik_dir: x\n"
            "linea suelta\n"
            "project:\n")
    with _Project(text) as proj:
        _, errors = manifest_mod.parse(proj.root)
        assert set(_codes(errors)) == {"EXT004", "EXT002", "EXT006", "EXT007"}


def test_con_errores_no_se_devuelve_manifiesto_a_medias():
    with _Project("calls_dir: extensions/fantasma\n") as proj:
        man, errors = manifest_mod.parse(proj.root)
        assert man is None and errors


def test_el_diagnostico_es_serializable_como_el_del_frontend():
    """Mismo contrato que ``CompilerError.to_dict()``: es lo que consumen el
    log JSONL y el canal ``--emit-diagnostics``."""
    with _Project("nada\n") as proj:
        _, errors = manifest_mod.parse(proj.root)
        payload = errors[0].to_dict()
        for key in ("code", "message", "line", "column", "file", "phase",
                    "severity", "location"):
            assert key in payload, key
        assert payload["severity"] == "critical"
        assert payload["phase"] == "extensions"
