"""El comando ``suri``: un envoltorio, no una segunda línea de comandos.

Lo que se prueba aquí es justamente que NO añade nada propio: las banderas son
las del compilador y salen de un solo sitio. Una prueba que verificara "suri
acepta --emit-hir" estaría comprobando el parser del compilador otra vez; lo
que importa es que no exista una segunda lista que se pueda desincronizar.
"""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from suri import command  # noqa: E402


def _run(args, cwd=None, env=None):
    entorno = dict(os.environ)
    entorno["PYTHONPATH"] = _REPO
    entorno.update(env or {})
    return subprocess.run([sys.executable, "-m", "suri", *args],
                          capture_output=True, text=True, timeout=120,
                          cwd=cwd or _REPO, env=entorno)


# --------------------------------------------------------------------------- #
# no declara banderas propias
# --------------------------------------------------------------------------- #

def test_no_declara_ninguna_bandera():
    """El paquete no puede contener un 'add_argument': si lo tuviera, habría
    dos listas de banderas y una acabaría quedándose atrás."""
    carpeta = os.path.dirname(os.path.abspath(command.__file__))
    for nombre in sorted(os.listdir(carpeta)):
        if not nombre.endswith(".py"):
            continue
        with open(os.path.join(carpeta, nombre), encoding="utf-8") as fh:
            fuente = fh.read()
        assert "add_argument" not in fuente, (
            f"suri/{nombre} declara banderas: las del compilador viven en "
            "V0/cli/args.py y se reutilizan, no se copian")


def test_la_ayuda_es_la_del_compilador():
    propia = _run(["--help"])
    del_compilador = subprocess.run(
        [sys.executable, os.path.join(_REPO, "V0", "main.py"), "--help"],
        capture_output=True, text=True, timeout=120, cwd=_REPO)
    assert propia.returncode == 0, propia.stderr
    # el 'prog' difiere (lo pone argparse con el nombre del proceso); lo que
    # tiene que coincidir es la lista de banderas.
    banderas = lambda texto: sorted(  # noqa: E731
        p.strip(",") for p in texto.split() if p.startswith("--"))
    assert banderas(propia.stdout) == banderas(del_compilador.stdout)


def test_la_version_es_la_del_proyecto():
    from version import VERSION
    salida = _run(["--version"])
    assert VERSION in salida.stdout, salida.stdout


# --------------------------------------------------------------------------- #
# la única comodidad que añade
# --------------------------------------------------------------------------- #

def test_compilar_un_fuente_sin_decir_mas_lo_ejecuta():
    """Es lo que espera quien escribe 'suri hola.srcx', y lo mismo que hace el
    atajo de la raíz: el comportamiento no se bifurca por la vía de entrada."""
    assert command.forward(["hola.srcx"]) == ["hola.srcx", "--run"]


def test_un_subcomando_no_recibe_run():
    for bandera in ("--check", "--init-config", "--version", "--help"):
        assert command.forward([bandera]) == [bandera], bandera


def test_una_bandera_de_emision_no_ejecuta_dos_veces():
    """'--run' escrito a mano no se duplica."""
    assert command.forward(["a.srcx", "--run"]) == ["a.srcx", "--run"]


# --------------------------------------------------------------------------- #
# encontrar el compilador
# --------------------------------------------------------------------------- #

def test_encuentra_el_compilador_desde_el_repositorio():
    assert command.find_root() == _REPO


def test_sin_compilador_dice_donde_busco(capsys=None):
    """Un 'no encontrado' sin las rutas probadas obliga a adivinar.

    Se simulan las candidatas: corriendo desde el repositorio SIEMPRE hay una
    válida (la raíz sale del propio paquete), así que el caso no se puede
    provocar de otra forma sin mover archivos.
    """
    import io
    import contextlib

    original = command._candidatas
    with tempfile.TemporaryDirectory(prefix="suriax-suri-") as tmp:
        command._candidatas = lambda: [tmp]
        try:
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                code = command.main(["x.srcx"])
        finally:
            command._candidatas = original
    assert code == 2
    assert "Rutas probadas" in error.getvalue(), error.getvalue()
    assert tmp in error.getvalue()
    assert command.ENV_ROOT in error.getvalue()


def test_la_raiz_del_entorno_manda():
    """'SURIAX_ROOT' va primero: apuntar a un árbol concreto sin instalar."""
    with tempfile.TemporaryDirectory(prefix="suriax-suri-") as tmp:
        os.makedirs(os.path.join(tmp, "V0"))
        with open(os.path.join(tmp, "V0", "main.py"), "w") as fh:
            fh.write("")
        previo = os.environ.get(command.ENV_ROOT)
        os.environ[command.ENV_ROOT] = tmp
        try:
            assert command.find_root() == os.path.abspath(tmp)
        finally:
            if previo is None:
                del os.environ[command.ENV_ROOT]
            else:
                os.environ[command.ENV_ROOT] = previo


def test_compila_de_verdad_desde_otro_directorio():
    programa = ("fn __write__(str s) -> void;\n"
                "fn main() -> int { __write__(\"hola\\n\"); return 0; };\n")
    with tempfile.TemporaryDirectory(prefix="suriax-suri-") as tmp:
        ruta = os.path.join(tmp, "prog.srcx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(programa)
        salida = _run([ruta], cwd=tmp)
        assert "hola" in salida.stdout, (salida.stdout, salida.stderr)


# --------------------------------------------------------------------------- #
# empaquetado
# --------------------------------------------------------------------------- #

def test_el_pyproject_declara_la_version_del_proyecto():
    """El metadato de un paquete no puede ejecutarse, así que la versión se
    escribe; esta prueba es lo que impide que se separe de version.py."""
    from version import VERSION
    ruta = os.path.join(_REPO, "pyproject.toml")
    with open(ruta, encoding="utf-8") as fh:
        contenido = fh.read()
    assert f'version = "{VERSION}"' in contenido, (
        f"pyproject.toml no declara la version {VERSION} de version.py")


def test_el_pyproject_expone_el_comando():
    ruta = os.path.join(_REPO, "pyproject.toml")
    with open(ruta, encoding="utf-8") as fh:
        contenido = fh.read()
    assert 'suri = "suri.command:main"' in contenido
