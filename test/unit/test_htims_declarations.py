"""HTIMS: escaneo estático de las declaraciones en Python
(``htims/declarations.py``).

El test que MANDA en este archivo es
:func:`test_escanear_no_ejecuta_el_archivo`: la garantía de que compilar un
``.srcx`` no corre el ``.py`` de nadie. Todo lo demás (firmas, códigos de
error) es la validación que se apoya en esa garantía.
"""

from __future__ import annotations

import os
import sys
import tempfile

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from htims import declarations  # noqa: E402


def _scan(text: str, *, name: str = "physics.py"):
    """Escanea ``text`` como si fuera un ``.py`` de ``calls_dir``."""
    with tempfile.TemporaryDirectory(prefix="suriax-decl-") as tmp:
        path = os.path.join(tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return declarations.scan_file(path)


def _codes(errors):
    return [e.code for e in errors]


_VALID = '''
from htims import signature_extends

PROJECT = "MiJuego"


@signature_extends("__gravity__", owner="Body",
                   params=["Body ptr mutable", "float"], returns="void",
                   cxx=True, logic="gravity_cpp")
def gravity(body, dt):
    """cae"""
'''


# --------------------------------------------------------------------------- #
# la garantía: leer no es ejecutar
# --------------------------------------------------------------------------- #

def test_escanear_no_ejecuta_el_archivo():
    """Un ``.py`` que escribe en disco al importarse NO escribe nada.

    Si este test falla, el compilador estaría ejecutando código arbitrario
    del proyecto en cada compilación.
    """
    with tempfile.TemporaryDirectory(prefix="suriax-exec-") as tmp:
        testigo = os.path.join(tmp, "EJECUTADO")
        path = os.path.join(tmp, "malicioso.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(
                "from htims import hook\n"
                f"open({testigo!r}, 'w').write('boom')\n"
                'raise SystemExit("y ademas aborta")\n'
                '@hook("__x__", owner="T", returns="void")\n'
                "def x(t):\n    pass\n"
            )
        project, decls, errors = declarations.scan_file(path)
        assert not os.path.exists(testigo), (
            "el archivo del usuario se EJECUTÓ durante el escaneo")
        # y aun así la declaración se extrae: el ast ve el decorador igual.
        assert [d.name for d in decls] == ["__x__"]
        assert errors == []


# --------------------------------------------------------------------------- #
# extracción
# --------------------------------------------------------------------------- #

def test_declaracion_completa_se_extrae_con_su_firma():
    project, decls, errors = _scan(_VALID)
    assert errors == [], _codes(errors)
    assert project == "MiJuego"
    assert len(decls) == 1
    decl = decls[0]
    assert decl.name == "__gravity__"
    assert decl.owner == "Body"
    assert decl.params == ("Body ptr mutable", "float")
    assert decl.returns == "void"
    assert decl.logic == "gravity_cpp"
    assert decl.func == "gravity"
    assert decl.module == "physics"
    assert decl.key == ("Body", "__gravity__")


def test_la_posicion_apunta_al_decorador():
    _, decls, _ = _scan(_VALID)
    assert decls[0].line == 7   # la línea del '@hook(...)'
    assert decls[0].column == 2  # tras la '@'


def test_params_y_logic_son_opcionales():
    _, decls, errors = _scan(
        'from htims import hook\n'
        '@hook("__ping__", owner="T", returns="void")\n'
        'def ping(t):\n    pass\n')
    assert errors == [], _codes(errors)
    assert decls[0].params == () and decls[0].logic == ""


def test_se_reconoce_el_decorador_calificado():
    """``@htims.hook(...)`` y ``@suriax.hook(...)`` son la misma declaración."""
    for decorador in ("htims.hook", "suriax.hook", "hook"):
        _, decls, errors = _scan(
            f'@{decorador}("__ping__", owner="T", returns="void")\n'
            'def ping(t):\n    pass\n')
        assert errors == [], (decorador, _codes(errors))
        assert len(decls) == 1, decorador


def test_una_funcion_sin_decorador_no_declara_nada():
    _, decls, errors = _scan("def gravity(body, dt):\n    return 1\n")
    assert decls == [] and errors == []


def test_varias_declaraciones_salen_en_orden_de_aparicion():
    _, decls, _ = _scan(
        'from htims import hook\n'
        '@hook("__b__", owner="T", returns="void")\n'
        'def b(t): pass\n'
        '@hook("__a__", owner="T", returns="void")\n'
        'def a(t): pass\n')
    assert [d.name for d in decls] == ["__b__", "__a__"]


# --------------------------------------------------------------------------- #
# diagnósticos de una declaración
# --------------------------------------------------------------------------- #

def test_nombre_sin_forma_de_hook_da_ext020():
    _, _, errors = _scan('@hook("gravity", owner="T", returns="void")\n'
                         'def g(t): pass\n')
    assert _codes(errors) == ["EXT020"]


def test_sin_owner_da_ext021():
    _, _, errors = _scan('@hook("__g__", returns="void")\ndef g(t): pass\n')
    assert _codes(errors) == ["EXT021"]


def test_sin_returns_da_ext022():
    _, _, errors = _scan('@hook("__g__", owner="T")\ndef g(t): pass\n')
    assert _codes(errors) == ["EXT022"]


def test_params_que_no_es_lista_de_cadenas_da_ext023():
    _, _, errors = _scan('@hook("__g__", owner="T", returns="void", '
                         'params="T ptr")\ndef g(t): pass\n')
    assert _codes(errors) == ["EXT023"]


def test_argumento_no_literal_da_ext025():
    """Consecuencia directa de no ejecutar: lo calculado no es declarable."""
    _, _, errors = _scan('NOMBRE = "__g__"\n'
                         '@hook(NOMBRE, owner="T", returns="void")\n'
                         'def g(t): pass\n')
    assert _codes(errors) == ["EXT025"]


def test_argumento_desconocido_da_ext026():
    _, _, errors = _scan('@hook("__g__", owner="T", returns="void", '
                         'prioridad=3)\ndef g(t): pass\n')
    assert _codes(errors) == ["EXT026"]


def test_redefinir_el_vocabulario_fijo_da_ext027():
    _, _, errors = _scan('@hook("__print__", owner="T", returns="void")\n'
                         'def p(t): pass\n')
    assert _codes(errors) == ["EXT027"]


def test_python_invalido_da_ext011_con_su_linea():
    _, _, errors = _scan("def roto(:\n    pass\n")
    assert _codes(errors) == ["EXT011"]
    assert errors[0].line == 1


def test_archivo_inexistente_da_ext010():
    _, _, errors = declarations.scan_file("/no/existe/physics.py")
    assert _codes(errors) == ["EXT010"]


# --------------------------------------------------------------------------- #
# consolidación entre archivos
# --------------------------------------------------------------------------- #

def _scan_files(files: dict):
    with tempfile.TemporaryDirectory(prefix="suriax-decls-") as tmp:
        paths = []
        for name, text in files.items():
            path = os.path.join(tmp, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            paths.append(path)
        return declarations.scan_files(sorted(paths))


def test_mismo_hook_del_mismo_tipo_dos_veces_da_ext024():
    _, decls, errors = _scan_files({
        "a.py": '@hook("__g__", owner="T", returns="void")\ndef g(t): pass\n',
        "b.py": '@hook("__g__", owner="T", returns="void")\ndef g(t): pass\n',
    })
    assert _codes(errors) == ["EXT024"]
    assert len(decls) == 1  # la primera gana, determinista


def test_el_mismo_nombre_para_dos_tipos_distintos_convive():
    _, decls, errors = _scan_files({
        "a.py": '@hook("__g__", owner="A", returns="void")\ndef g(t): pass\n',
        "b.py": '@hook("__g__", owner="B", returns="void")\ndef g(t): pass\n',
    })
    assert errors == [], _codes(errors)
    assert {d.owner for d in decls} == {"A", "B"}


def test_dos_project_en_conflicto_dan_ext012():
    project, _, errors = _scan_files({
        "a.py": 'PROJECT = "Uno"\n',
        "b.py": 'PROJECT = "Otro"\n',
    })
    assert _codes(errors) == ["EXT012"]


def test_el_mismo_project_repetido_no_es_conflicto():
    project, _, errors = _scan_files({
        "a.py": 'PROJECT = "MiJuego"\n',
        "b.py": 'PROJECT = "MiJuego"\n',
    })
    assert errors == [] and project == "MiJuego"


# --------------------------------------------------------------------------- #
# la frontera, verificada
# --------------------------------------------------------------------------- #

def test_vocabulario_reservado_sincronizado_con_la_semantica():
    """``htims/`` no importa ``V0/`` — pero alguien tiene que garantizar que
    su copia del vocabulario fijo no se quede vieja. Ese alguien es este test:
    cruza la frontera A PROPÓSITO, para que el módulo no tenga que hacerlo.
    """
    _V0 = os.path.join(_REPO_ROOT, "V0")
    if _V0 not in sys.path:
        sys.path.insert(0, _V0)
    from src.frontend.semantic.hooks import HOOK_SPECS

    esperado = {f"__{name}__" for name in HOOK_SPECS}
    assert set(declarations.RESERVED_HOOKS) == esperado, (
        "el vocabulario fijo cambió en semantic/hooks.py: actualiza "
        "RESERVED_HOOKS en htims/declarations.py")


def test_htims_no_importa_el_frontend():
    """La frontera del módulo, comprobada sobre el código fuente."""
    import htims
    folder = os.path.dirname(os.path.abspath(htims.__file__))
    # RECURSIVO: 'utils/' es del mismo paquete y le vale la misma frontera.
    for base, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(n for n in names if n.endswith(".py")):
            ruta = os.path.join(base, name)
            with open(ruta, encoding="utf-8") as fh:
                source = fh.read()
            relativa = os.path.relpath(ruta, os.path.dirname(folder))
            for prohibido in ("from src.", "import src.", "from V0",
                              "import V0", "from config", "import config"):
                assert prohibido not in source, (
                    f"{relativa} importa '{prohibido}': la capa dejaría de ser "
                    "independiente de V0/ y config/")


# --------------------------------------------------------------------------- #
# bajar a C++ se ESCRIBE: negado por defecto
# --------------------------------------------------------------------------- #
# La verificación es el opt-in. Un hook cuya lógica vive en logic_dir deja de
# ser comprobable por el compilador —su cuerpo está fuera de su alcance—, así
# que sacarlo del lenguaje tiene que ser una decisión escrita y no lo que
# ocurre al copiar una declaración de otro sitio.

def test_una_firma_pura_no_puede_pedir_cpp():
    _project, decls, errors = _scan(
        'from htims import signature\n'
        '@signature("__g__", owner="B", returns="void", logic="g_cpp")\n'
        'def g(b): pass\n')
    assert _codes(errors) == ["EXT028"], _codes(errors)
    assert decls == []
    assert "signature_extends" in errors[0].message, \
        "el error dice cuál es el decorador que sí puede"


def test_extends_sin_optin_se_rechaza():
    _project, decls, errors = _scan(
        'from htims import signature_extends\n'
        '@signature_extends("__g__", owner="B", returns="void",\n'
        '                   logic="g_cpp")\n'
        'def g(b): pass\n')
    assert _codes(errors) == ["EXT029"], _codes(errors)
    assert decls == []


def test_cxx_false_explicito_tampoco_vale():
    """Escribir 'cxx=False' y esperar C++ es un contrasentido: se reporta."""
    _project, _decls, errors = _scan(
        'from htims import signature_extends\n'
        '@signature_extends("__g__", owner="B", returns="void",\n'
        '                   cxx=False, logic="g_cpp")\n'
        'def g(b): pass\n')
    assert _codes(errors) == ["EXT029"], _codes(errors)


def test_cxx_sin_simbolo_no_tiene_nada_que_ligar():
    _project, _decls, errors = _scan(
        'from htims import signature_extends\n'
        '@signature_extends("__g__", owner="B", returns="void", cxx=True)\n'
        'def g(b): pass\n')
    assert _codes(errors) == ["EXT029"], _codes(errors)
    assert "logic=" in errors[0].message


def test_una_firma_pura_no_es_cxx():
    _project, decls, errors = _scan(
        'from htims import signature\n'
        '@signature("__g__", owner="B", returns="void")\n'
        'def g(b): pass\n')
    assert errors == [], _codes(errors)
    assert decls[0].cxx is False and decls[0].logic == ""


def test_el_contrato_cpp_completo_se_acepta():
    _project, decls, errors = _scan(
        'from htims import signature_extends\n'
        '@signature_extends("__g__", owner="B", params=["int"],\n'
        '                   returns="void", cxx=True, logic="g_cpp")\n'
        'def g(b, n): pass\n')
    assert errors == [], _codes(errors)
    assert decls[0].cxx is True and decls[0].logic == "g_cpp"


def test_el_alias_hook_sigue_escaneando_con_las_reglas_nuevas():
    """'@hook' se mantiene para no romper extensiones ya escritas, pero no es
    una puerta trasera al C++ implícito."""
    _project, decls, errors = _scan(
        'from htims import hook\n'
        '@hook("__g__", owner="B", returns="void")\n'
        'def g(b): pass\n')
    assert errors == [], _codes(errors)
    assert decls[0].name == "__g__" and decls[0].cxx is False

    _project, _decls, errors = _scan(
        'from htims import hook\n'
        '@hook("__g__", owner="B", returns="void", logic="g_cpp")\n'
        'def g(b): pass\n')
    assert _codes(errors) == ["EXT028"], _codes(errors)
