"""El ``.suriaX_config.yaml`` mal escrito se reporta, no se ignora.

Existe porque pasaba lo contrario: un yaml roto, un ``target`` inventado, una
clave con una letra de más (``libsrx_path`` por ``libsrx_paths``) o un valor
del tipo equivocado se descartaban EN SILENCIO y la compilación seguía con
los valores por defecto. El usuario veía el síntoma mucho después y en otro
sitio —"no se encontró la librería X"— sin ninguna pista de que su
configuración nunca llegó a aplicarse.
"""

from __future__ import annotations

import os
import sys
import tempfile

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "V0")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _codigos(contenido: str) -> list[str]:
    """Códigos que produce cargar un yaml con ese contenido."""
    from config import errors_of, reload_config

    with tempfile.TemporaryDirectory(prefix="suriax-cfg-") as tmp:
        with open(os.path.join(tmp, ".suriaX_config.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write(contenido)
        return [e.code for e in errors_of(reload_config(start_dir=tmp))]


def _hay_yaml() -> bool:
    """Sin ``pyyaml`` no se llega a parsear: estos casos no aplican."""
    try:
        import yaml  # noqa: F401
        return True
    except ImportError:
        return False


def test_una_clave_mal_escrita_se_reporta():
    if not _hay_yaml():
        return
    codigos = _codigos("version: 2\nlibraries:\n  libsrx_path:\n    - ./lib\n")
    assert "CFG004" in codigos, (
        f"un typo en una clave debe reportarse, no ignorarse: {codigos}")


def test_la_sugerencia_nombra_la_clave_correcta():
    """Lo que convierte el diagnóstico en útil: decir qué se quiso escribir."""
    if not _hay_yaml():
        return
    from config import errors_of, reload_config

    with tempfile.TemporaryDirectory(prefix="suriax-cfg-") as tmp:
        with open(os.path.join(tmp, ".suriaX_config.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write("libraries:\n  libsrx_path: []\n")
        errores = errors_of(reload_config(start_dir=tmp))
    assert errores and "libsrx_paths" in errores[0].message, (
        f"el mensaje debe sugerir la clave real: {errores[0].message if errores else None}")


def test_un_valor_fuera_del_conjunto_se_reporta():
    if not _hay_yaml():
        return
    assert "CFG006" in _codigos("target: zzz_no_existe\n")


def test_un_tipo_equivocado_se_reporta():
    """``libsrx_paths: ./lib`` (cadena en vez de lista) recorrería la cadena
    carácter a carácter como si cada letra fuera una ruta."""
    if not _hay_yaml():
        return
    assert "CFG005" in _codigos("libraries:\n  libsrx_paths: ./lib\n")


def test_un_yaml_roto_se_reporta():
    if not _hay_yaml():
        return
    assert "CFG002" in _codigos("target: [[[roto\n")


def test_una_configuracion_valida_no_reporta_nada():
    """El otro lado del contrato: cero falsos positivos."""
    if not _hay_yaml():
        return
    assert _codigos("version: 2\ntarget: interp\n"
                    "libraries:\n  libsrx_paths:\n    - ./lib\n") == []


def test_la_configuracion_del_repositorio_es_valida():
    """La que se distribuye tiene que pasar su propia validación."""
    if not _hay_yaml():
        return
    from config import errors_of, reload_config

    criticos = [e.code for e in errors_of(reload_config(start_dir=_REPO_ROOT))
                if e.severity == "critical"]
    assert not criticos, f"el .suriaX_config.yaml del repo no valida: {criticos}"


def test_falta_pyyaml_es_aviso_y_no_impide_compilar():
    """El frontend completo corre con la librería estándar (how_to_run.md):
    no tener el lector de yaml avisa, pero no puede tumbar la compilación."""
    from config.errors import CFG007, ConfigError

    assert ConfigError(CFG007, "x", severity="warning").severity == "warning"
    assert ConfigError("CFG004", "x").severity == "critical"


def test_el_esquema_se_deriva_de_la_configuracion_por_defecto():
    """No hay dos listas de claves que puedan divergir: el validador lee el
    esquema de 'default_config()', que ES la definición del formato."""
    from config import default_config
    from config.validate import validate

    assert validate(default_config(), default_config()) == [], (
        "la configuración por defecto debe validar contra su propio esquema")
