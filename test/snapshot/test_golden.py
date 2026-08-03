"""snapshot — golden de los contratos entre fases.

Un snapshot congela la FORMA de una salida (AST-tipado en JSON, HIR en texto)
para que un cambio accidental de contrato salte aquí y no tres fases más
abajo. Los golden viven en ``test/snapshot/golden/`` y se regeneran con:

    SURIAX_UPDATE_GOLDEN=1 python test/main.py snapshot

Solo se congelan programas PEQUEÑOS y estables: un golden gigante se vuelve
ruido que nadie revisa (y cada cambio legítimo obliga a regenerar a ciegas).
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import analyze  # noqa: E402

_GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
_UPDATE = os.environ.get("SURIAX_UPDATE_GOLDEN") == "1"


def _compare(name: str, actual: str) -> None:
    """Compara contra el golden ``name`` (o lo (re)genera si se pidió)."""
    os.makedirs(_GOLDEN_DIR, exist_ok=True)
    path = os.path.join(_GOLDEN_DIR, name)
    if _UPDATE or not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(actual)
        return
    with open(path, encoding="utf-8") as fh:
        expected = fh.read()
    if actual != expected:
        # diff mínimo: la primera línea que difiere (un diff completo de un
        # AST en JSON es ilegible en la consola del runner).
        a_lines, e_lines = actual.splitlines(), expected.splitlines()
        for i, (got, want) in enumerate(zip(a_lines, e_lines), 1):
            if got != want:
                raise AssertionError(
                    f"snapshot '{name}' difiere en la línea {i}:\n"
                    f"  esperado: {want}\n  obtenido: {got}\n"
                    f"  (regenera con SURIAX_UPDATE_GOLDEN=1 si el cambio es intencional)"
                )
        raise AssertionError(
            f"snapshot '{name}' difiere en longitud "
            f"({len(a_lines)} vs {len(e_lines)} líneas)"
        )


_PROGRAMA = """\
struct { int x; Nodo ptr? sig; } Nodo;

fn crea(int v) -> Nodo ptr? {
    var Nodo n = Nodo{ x: v, sig: null };
    return &n;
};

fn suma(Nodo ptr? n) -> error int {
    if (n == null) { throw 0; };
    return n.x;
};

fn main() -> int {
    var Nodo ptr? cabeza = crea(7);
    try {
        var int t = suma(cabeza);
    } catch (e) { };
    return 0;
};
"""


def test_snapshot_ast_tipado():
    """La forma del AST-tipado (nodos + restype) no cambia por accidente."""
    from include.ast_json import to_json
    program, _, errors = analyze(_PROGRAMA)
    assert not errors, errors
    _compare("programa.ast.json", to_json(program) + "\n")


def test_snapshot_tabla_de_simbolos():
    from include.ast_json import to_json
    from src.frontend.semantic.symbol_table import to_debug_dict
    _, table, errors = analyze(_PROGRAMA)
    assert not errors, errors
    _compare("programa.symbols.json", to_json(to_debug_dict(table)) + "\n")


def test_snapshot_hir_texto():
    """El HIR en texto protobuf: el contrato con los targets (C++/intérprete)."""
    try:
        import google.protobuf  # noqa: F401
    except ImportError:
        return  # sin protobuf esta fase no aplica (el frontend no lo exige)

    from src.HIR.emmit_IR import build_module, module_to_text
    program, table, errors = analyze(_PROGRAMA)
    assert not errors, errors
    module, hir_errors = build_module(program, table, source_file="snapshot.srcx")
    assert not hir_errors, [e.message for e in hir_errors]
    text = module_to_text(module)
    # la ruta del fuente varía por máquina: se normaliza antes de congelar
    text = re.sub(r'source_file: ".*"', 'source_file: "<normalizado>"', text)
    _compare("programa.hir.txt", text)


def test_esquema_hir_compila_y_su_version_es_estable():
    """``schema_version`` es el fail-fast de la frontera: si cambia, TODOS
    los lectores (C++ e intérprete) deben actualizarse a la vez."""
    try:
        import google.protobuf  # noqa: F401
    except ImportError:
        return
    from src.HIR.emmit_IR import SCHEMA_VERSION
    assert SCHEMA_VERSION == 1, (
        f"schema_version cambió a {SCHEMA_VERSION}: actualiza los lectores "
        "(runtime/interpreter/loader.SUPPORTED_SCHEMA_VERSIONS y el lector C++)"
    )


def test_codigos_de_error_estables():
    """Los códigos son el contrato con las herramientas (extensión, CI)."""
    from error_handler import ASTError, SemanticError
    esperados = {
        SemanticError.UndefinedSymbolError: "SEM001",
        SemanticError.DuplicateSymbolError: "SEM002",
        SemanticError.ImmutableAssignmentError: "SEM003",
        SemanticError.UseAfterMoveError: "SEM004",
        SemanticError.DoubleMoveError: "SEM005",
        SemanticError.InvalidHookSignatureError: "SEM006",
        SemanticError.DuplicateHookError: "SEM007",
        SemanticError.CallArityError: "SEM008",
        SemanticError.InvalidAddressOfError: "SEM013",
        SemanticError.InvalidFreeTargetError: "SEM014",
        SemanticError.ReadOnlyPointerWriteError: "SEM015",
        SemanticError.InvalidCastError: "SEM016",
        ASTError.UnknownTypeError: "AST005",
        ASTError.TypeMismatchError: "AST006",
    }
    for cls, code in esperados.items():
        assert cls("x").code == code, (
            f"{cls.__name__} cambió de código: {cls('x').code} != {code}"
        )
