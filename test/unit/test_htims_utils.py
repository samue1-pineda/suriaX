"""Las herramientas de ``htims/utils/``: verificar, y los dos contratos.

De una declaración salen dos cosas que hoy se copiaban a mano: la línea
``hook fn`` que hay que escribir en el ``.srcx`` y el prototipo C++ que
``logic_dir`` tendrá que implementar. Que se generen desde la MISMA firma es
lo que impide que se desincronicen — copiarla es exactamente donde aparecen
los desajustes que luego reporta la Semántica.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from htims.utils import check as check_mod          # noqa: E402
from htims.utils import cxx as cxx_mod              # noqa: E402
from htims.utils import srcx as srcx_mod            # noqa: E402

_EXT = (
    'from htims import signature, signature_extends\n'
    'PROJECT = "MiJuego"\n'
    '@signature("__area__", owner="Rect", params=["Rect ptr"],\n'
    '           returns="int")\n'
    'def area(r): pass\n'
    '@signature_extends("__win_open__", owner="Ventana",\n'
    '                   params=["int", "int"],\n'
    '                   returns="Ventana ptr mutable",\n'
    '                   cxx=True, logic="win_open_cpp")\n'
    'def win_open(w, h): pass\n'
)


def _con_extension(texto=_EXT):
    """Escribe la extensión en un temporal y devuelve ``(decls, errores)``."""
    tmp = tempfile.mkdtemp(prefix="suriax-utils-")
    with open(os.path.join(tmp, "ventana.py"), "w", encoding="utf-8") as fh:
        fh.write(texto)
    return tmp, check_mod.check(tmp)


# --------------------------------------------------------------------------- #
# check: el MISMO escaneo que el compilador
# --------------------------------------------------------------------------- #

def test_check_encuentra_las_declaraciones():
    _tmp, (decls, errores) = _con_extension()
    assert errores == [], [e.code for e in errores]
    assert {d.name for d in decls} == {"__area__", "__win_open__"}


def test_check_reporta_lo_mismo_que_el_compilador():
    """No es una verificación propia: llama al escaneo real, así que no puede
    discrepar con lo que dirá el compilador."""
    _tmp, (decls, errores) = _con_extension(
        'from htims import signature\n'
        '@signature("__free__", owner="B", returns="void")\n'
        'def f(b): pass\n')
    assert [e.code for e in errores] == ["EXT027"]
    assert decls == []


def test_los_privados_no_se_escanean():
    """Misma regla que el descubrimiento del compilador: si él no los mira,
    verificarlos aquí daría una respuesta que no se corresponde."""
    tmp = tempfile.mkdtemp(prefix="suriax-utils-")
    for nombre in ("visible.py", "_privado.py", "notas.txt"):
        with open(os.path.join(tmp, nombre), "w", encoding="utf-8") as fh:
            fh.write("")
    encontrados = {os.path.basename(p) for p in check_mod.archivos(tmp)}
    assert encontrados == {"visible.py"}


# --------------------------------------------------------------------------- #
# srcx: la línea que hay que escribir en el programa
# --------------------------------------------------------------------------- #

def test_el_stub_nombra_self_al_receptor():
    """El primer parámetro es el receptor cuando su tipo es el del dueño, y
    así se escribe en el resto del lenguaje."""
    _tmp, (decls, _errores) = _con_extension()
    area = next(d for d in decls if d.name == "__area__")
    assert srcx_mod.stub(area) == "hook fn __area__(Rect ptr self) -> int { }"


def test_el_stub_de_un_hook_sin_receptor_numera_sus_parametros():
    _tmp, (decls, _errores) = _con_extension()
    win = next(d for d in decls if d.name == "__win_open__")
    assert srcx_mod.stub(win) == (
        "hook fn __win_open__(int arg1, int arg2) -> Ventana ptr mutable { }")


# --------------------------------------------------------------------------- #
# cxx: el prototipo nativo
# --------------------------------------------------------------------------- #

def test_los_tipos_del_lenguaje_bajan_a_cpp():
    assert cxx_mod.cxx_type("int") == ("int64_t", None)
    assert cxx_mod.cxx_type("float") == ("double", None)
    # un char es UN code point, no un byte
    assert cxx_mod.cxx_type("char") == ("char32_t", None)
    # notación POSTFIJA, la del lenguaje
    assert cxx_mod.cxx_type("Body ptr mutable") == ("Body*", None)
    # sin 'mutable' el hook solo puede leer, y el 'const' lo hace cumplir del
    # lado de C++ — la mitad que el compilador de suriaX no vigila
    assert cxx_mod.cxx_type("Body ptr") == ("const Body*", None)


def test_un_tipo_sin_representacion_decidida_se_reporta_no_se_inventa():
    """'str' viaja distinto en cada consumidor (cadena en el intérprete,
    índice en el web): elegir aquí fijaría por la puerta de atrás una decisión
    del lenguaje."""
    for tipo in ("str", "int?", "error int", "Caja<int>"):
        rendido, motivo = cxx_mod.cxx_type(tipo)
        assert rendido is None and motivo, tipo


def test_la_cabecera_solo_trae_los_que_declaran_cxx():
    _tmp, (decls, _errores) = _con_extension()
    texto, problemas = cxx_mod.header(decls)
    assert problemas == []
    assert "win_open_cpp" in texto
    assert "__area__" not in texto, \
        "una firma pura se resuelve en el lenguaje: no tiene símbolo nativo"


def test_la_cabecera_evita_el_mangling():
    """Quien busque el símbolo lo hará por su NOMBRE, y el mangling de C++ lo
    cambia según la firma."""
    _tmp, (decls, _errores) = _con_extension()
    texto, _problemas = cxx_mod.header(decls)
    assert 'extern "C" {' in texto
    assert "#include <cstdint>" in texto, "int64_t necesita su cabecera"


def test_un_hook_intraducible_se_nombra_y_no_sale_a_medias():
    _tmp, (decls, _errores) = _con_extension(
        'from htims import signature_extends\n'
        '@signature_extends("__titulo__", owner="V", params=["str"],\n'
        '                   returns="void", cxx=True, logic="titulo_cpp")\n'
        'def titulo(v, t): pass\n')
    texto, problemas = cxx_mod.header(decls)
    assert len(problemas) == 1 and "str" in problemas[0]
    assert "titulo_cpp" not in texto, \
        "no se emite un prototipo a medias: el que no se puede traducir falta"
