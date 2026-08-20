"""La clave de despacho de un hook: ``(dueño, kind, nombre)``.

El vocabulario de hooks dejó de ser cerrado (HTIMS): un hook declarado por el
usuario viaja en el HIR con ``kind == EXTENDED`` y su identidad en
``hook_name``. Este archivo fija las dos mitades del contrato:

  1. dos hooks EXTENDED del MISMO dueño no colisionan (era imposible con la
     clave de dos elementos: ambos serían ``(dueño, EXTENDED)``);
  2. un ``.phir`` emitido ANTES del cambio se indexa exactamente igual —
     ``hook_name`` ausente vale ``""``, que es la clave del vocabulario fijo.
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_V0 = os.path.join(_REPO_ROOT, "V0")
for _p in (_REPO_ROOT, _V0):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from runtime.interpreter.hook.dispatch import (hook_key, index_hooks,  # noqa: E402
                                               ref_key)
from src.HIR.stubs import load_hir_pb2  # noqa: E402


def _pb():
    return load_hir_pb2()


def _unit(*entries):
    """Unidad mínima con los ``HookEntry`` dados y un cuerpo por símbolo."""
    pb = _pb()
    module = pb.Module(schema_version=2)
    decls = {}
    for entry in entries:
        module.symbols.hooks.append(entry)
        decls[(entry.symbol.name, entry.symbol.ln)] = f"cuerpo:{entry.symbol.name}"
    return SimpleNamespace(module=module, dunder_decls=decls)


def _entry(owner: str, kind: int, name: str, *, ln: int, hook_name: str = "",
           extension: str = ""):
    pb = _pb()
    return pb.HookEntry(
        owner_type=owner, kind=kind, hook_name=hook_name, extension=extension,
        symbol=pb.Symbol(name=name, kind=pb.SymbolKind.Value("HOOK"), ln=ln),
    )


# --------------------------------------------------------------------------- #
# el esquema
# --------------------------------------------------------------------------- #

def test_el_hir_tiene_kind_extendido_y_nombre():
    pb = _pb()
    assert pb.HookKind.Value("EXTENDED") == 100
    # los campos nuevos existen en los tres mensajes que forman la clave
    assert pb.HookEntry(hook_name="__g__").hook_name == "__g__"
    assert pb.HookRef(hook_name="__g__").hook_name == "__g__"
    assert pb.Symbol(hook_name="__g__").hook_name == "__g__"


def test_los_campos_del_hook_de_usuario_son_aditivos():
    """Los campos que HTIMS añadió (``hook_name``, ``extension``) no tienen
    presencia obligatoria: una entrada que no los escribe vale ``""``, que es
    la clave del vocabulario fijo.

    (El esquema sí subió a 2 después, pero por otra razón — el pool de tipos,
    ver ``docs/plan_hir_v2.md``. Estos campos no participaron de esa ruptura.)
    """
    pb = _pb()
    modulo = pb.Module(schema_version=2)
    modulo.symbols.hooks.append(_entry("Punto", pb.HookKind.Value("PRINT"),
                                       "__print__", ln=3))
    releido = pb.Module()
    releido.ParseFromString(modulo.SerializeToString())
    assert releido.symbols.hooks[0].hook_name == ""
    assert releido.symbols.hooks[0].extension == ""


# --------------------------------------------------------------------------- #
# la clave
# --------------------------------------------------------------------------- #

def test_el_vocabulario_fijo_usa_nombre_vacio():
    pb = _pb()
    print_kind = pb.HookKind.Value("PRINT")
    unit = _unit(_entry("Punto", print_kind, "__print__", ln=3))
    index = index_hooks([unit])
    assert list(index) == [("Punto", print_kind, "")]
    assert index[hook_key("Punto", print_kind)] == (unit, "cuerpo:__print__")


def test_un_hook_ref_viejo_resuelve_contra_el_indice():
    """Compatibilidad hacia atrás: el ``HookRef`` de un .phir anterior no
    trae ``hook_name``, y su clave es la misma que antes."""
    pb = _pb()
    print_kind = pb.HookKind.Value("PRINT")
    unit = _unit(_entry("Punto", print_kind, "__print__", ln=3))
    index = index_hooks([unit])
    ref = pb.HookRef(owner_type="Punto", kind=print_kind)
    assert index.get(ref_key(ref)) is not None


def test_dos_hooks_de_usuario_del_mismo_dueño_no_colisionan():
    """Lo que la clave de dos elementos hacía imposible."""
    pb = _pb()
    extended = pb.HookKind.Value("EXTENDED")
    unit = _unit(
        _entry("Body", extended, "__gravity__", ln=10,
               hook_name="__gravity__", extension="physics"),
        _entry("Body", extended, "__drag__", ln=20,
               hook_name="__drag__", extension="physics"),
    )
    index = index_hooks([unit])
    assert len(index) == 2
    assert index[hook_key("Body", extended, "__gravity__")][1] == "cuerpo:__gravity__"
    assert index[hook_key("Body", extended, "__drag__")][1] == "cuerpo:__drag__"


def test_un_hook_de_usuario_no_pisa_al_del_vocabulario_fijo():
    pb = _pb()
    extended = pb.HookKind.Value("EXTENDED")
    print_kind = pb.HookKind.Value("PRINT")
    unit = _unit(
        _entry("Body", print_kind, "__print__", ln=5),
        _entry("Body", extended, "__gravity__", ln=10, hook_name="__gravity__"),
    )
    index = index_hooks([unit])
    assert set(index) == {("Body", print_kind, ""),
                          ("Body", extended, "__gravity__")}


def test_la_procedencia_viaja_con_la_entrada():
    """Para que un diagnóstico pueda decir de qué extensión salió el hook."""
    pb = _pb()
    entry = _entry("Body", pb.HookKind.Value("EXTENDED"), "__gravity__", ln=1,
                   hook_name="__gravity__", extension="physics")
    assert entry.extension == "physics"


def test_el_proyecto_no_viaja_en_el_hir():
    """Frontera deliberada: el .phir describe una UNIDAD, no el proyecto.
    El nombre del proyecto y la lista de extensiones son configuración
    (``--emit-extensions``), no IR."""
    pb = _pb()
    campos = {f.name for f in pb.Module.DESCRIPTOR.fields}
    assert "extensions" not in campos and "project" not in campos
