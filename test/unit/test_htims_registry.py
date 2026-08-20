"""HTIMS: construcción del ``ExtensionSet`` (``htims/registry.py``).

Cubre las dos fuentes (manifiesto y lista del yaml), su fusión, y la regla de
precedencia del nombre del proyecto.
"""

from __future__ import annotations

import os
import sys
import tempfile

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import htims  # noqa: E402

_MANIFEST = ("project:   DelManifiesto\n"
             "logic_dir: extensions/logic\n"
             "calls_dir: extensions/calls\n")

_PHYSICS = ('from htims import hook\n'
            'PROJECT = "MiJuego"\n'
            '@hook("__gravity__", owner="Body", params=["Body ptr mutable"],\n'
            '      returns="void", logic="gravity_cpp")\n'
            'def gravity(body): pass\n')

_AUDIO = ('from htims import hook\n'
          '@hook("__play__", owner="Sound", returns="void")\n'
          'def play(s): pass\n')


class _Project:
    """Proyecto temporal: ``files`` mapea ruta relativa -> contenido."""

    def __init__(self, files: dict, *, dirs=()):
        self._tmp = tempfile.TemporaryDirectory(prefix="suriax-reg-")
        self.root = self._tmp.name
        for rel in dirs:
            os.makedirs(os.path.join(self.root, *rel.split("/")), exist_ok=True)
        for rel, content in files.items():
            path = os.path.join(self.root, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False


def test_sin_manifiesto_ni_config_no_hay_conjunto():
    with _Project({"juego.srcx": "fn main() -> int { return 0; }\n"}) as proj:
        extensions, errors = htims.build(proj.root)
        assert extensions is None and errors == []


def test_el_manifiesto_recoge_todos_los_py_de_calls_dir():
    with _Project({
        "extends.srcx": _MANIFEST,
        "extensions/calls/physics.py": _PHYSICS,
        "extensions/calls/audio.py": _AUDIO,
    }, dirs=("extensions/logic",)) as proj:
        extensions, errors = htims.build(proj.root)
        assert errors == [], [e.code for e in errors]
        assert {m.name for m in extensions.modules} == {"physics", "audio"}
        assert extensions.names == ("__gravity__", "__play__")


def test_indice_por_dueño_y_nombre():
    with _Project({
        "extends.srcx": _MANIFEST,
        "extensions/calls/physics.py": _PHYSICS,
    }, dirs=("extensions/logic",)) as proj:
        extensions, _ = htims.build(proj.root)
        decl = extensions.hook("Body", "__gravity__")
        assert decl is not None and decl.logic == "gravity_cpp"
        assert extensions.hook("Body", "__nope__") is None
        assert len(extensions.hooks_of("Body")) == 1


def test_los_privados_y_pycache_no_se_escanean():
    with _Project({
        "extends.srcx": _MANIFEST,
        "extensions/calls/physics.py": _PHYSICS,
        "extensions/calls/__init__.py": "raise SystemExit('no')\n",
        "extensions/calls/_util.py": "roto(\n",
        "extensions/calls/__pycache__/physics.py": "roto(\n",
    }, dirs=("extensions/logic",)) as proj:
        extensions, errors = htims.build(proj.root)
        assert errors == [], [e.code for e in errors]
        assert {m.name for m in extensions.modules} == {"physics"}


def test_la_lista_del_yaml_funciona_sin_manifiesto():
    """'o se configura a mano': un proyecto puede declarar extensiones sin
    escribir un extends.srcx."""
    with _Project({"plugins/physics.py": _PHYSICS}) as proj:
        extensions, errors = htims.build(
            proj.root, config_entries=[{"path": "plugins/physics.py"}])
        assert errors == [], [e.code for e in errors]
        assert extensions.manifest is None
        assert extensions.names == ("__gravity__",)


def test_la_forma_corta_de_la_lista_tambien_vale():
    with _Project({"plugins/physics.py": _PHYSICS}) as proj:
        extensions, errors = htims.build(
            proj.root, config_entries=["plugins/physics.py"])
        assert errors == [] and extensions.names == ("__gravity__",)


def test_una_extension_configurada_que_no_existe_da_ext010():
    with _Project({"juego.srcx": ""}) as proj:
        extensions, errors = htims.build(
            proj.root, config_entries=[{"path": "plugins/fantasma.py"}])
        assert [e.code for e in errors] == ["EXT010"]
        assert extensions is None


def test_el_yaml_no_duplica_lo_que_ya_trae_calls_dir():
    with _Project({
        "extends.srcx": _MANIFEST,
        "extensions/calls/physics.py": _PHYSICS,
    }, dirs=("extensions/logic",)) as proj:
        extensions, errors = htims.build(
            proj.root,
            config_entries=[{"path": "extensions/calls/physics.py"}])
        # el mismo archivo por las dos vías es UNA extensión, no dos (si no,
        # cada hook chocaría consigo mismo con EXT024).
        assert errors == [], [e.code for e in errors]
        assert len(extensions.modules) == 1


def test_el_nombre_del_proyecto_lo_declara_el_py():
    """Precedencia: PROJECT del .py > manifiesto > yaml."""
    with _Project({
        "extends.srcx": _MANIFEST,               # project: DelManifiesto
        "extensions/calls/physics.py": _PHYSICS,  # PROJECT = "MiJuego"
    }, dirs=("extensions/logic",)) as proj:
        extensions, _ = htims.build(proj.root, config_project="DelYaml")
        assert extensions.project == "MiJuego"


def test_sin_py_que_lo_declare_manda_el_manifiesto():
    with _Project({
        "extends.srcx": _MANIFEST,
        "extensions/calls/audio.py": _AUDIO,   # sin PROJECT
    }, dirs=("extensions/logic",)) as proj:
        extensions, _ = htims.build(proj.root, config_project="DelYaml")
        assert extensions.project == "DelManifiesto"


def test_config_entries_devuelve_rutas_relativas_portables():
    with _Project({
        "extends.srcx": _MANIFEST,
        "extensions/calls/physics.py": _PHYSICS,
    }, dirs=("extensions/logic",)) as proj:
        extensions, _ = htims.build(proj.root)
        entries = extensions.config_entries()
        assert entries == [{"path": os.path.join("extensions", "calls",
                                                 "physics.py"),
                            "logic": ["gravity_cpp"]}]


def test_discover_deja_el_resultado_en_la_config():
    with _Project({
        "extends.srcx": _MANIFEST,
        "extensions/calls/physics.py": _PHYSICS,
    }, dirs=("extensions/logic",)) as proj:
        config = {"_root": proj.root, "project": "", "extensions": []}
        extensions, errors = htims.discover(config)
        assert errors == []
        assert config["project"] == "MiJuego"
        assert config["extensions"] == extensions.config_entries()
        assert htims.of(config) is extensions


def test_discover_sin_raiz_no_hace_nada():
    extensions, errors = htims.discover({})
    assert extensions is None and errors == []


def test_un_error_de_declaracion_no_deja_conjunto_a_medias():
    """Un vocabulario incompleto es peor que ninguno: la Semántica lo tomaría
    por completo y culparía al .srcx de lo que falta en el .py."""
    with _Project({
        "extends.srcx": _MANIFEST,
        "extensions/calls/physics.py": _PHYSICS,
        "extensions/calls/roto.py": '@hook("mal", owner="T", returns="void")\n'
                                    'def m(t): pass\n',
    }, dirs=("extensions/logic",)) as proj:
        extensions, errors = htims.build(proj.root)
        assert extensions is None
        assert [e.code for e in errors] == ["EXT020"]
