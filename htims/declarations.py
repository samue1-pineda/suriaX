"""Escaneo ESTÁTICO de las declaraciones de hooks en Python (``calls_dir``).

El usuario declara sus hooks en Python::

    from htims import hook

    PROJECT = "MiJuego"

    @hook("__gravity__", owner="Body",
          params=["Body ptr mutable", "float"], returns="void",
          logic="gravity_cpp")
    def gravity(body, dt):
        ...

y este módulo los extrae **sin importar ni ejecutar el archivo**: lo lee con
``ast.parse`` y mira la forma del decorador. Es la diferencia entre leer una
declaración y correr código arbitrario del proyecto en tiempo de compilación
— compilar un ``.srcx`` jamás debe ejecutar el ``.py`` de nadie.

Corolario del escaneo estático: **todo argumento del decorador tiene que ser
un literal**. ``owner=NOMBRE_CALCULADO`` no es declarable (EXT025); no es una
limitación del parser, es la condición para no ejecutar nada.

La firma se escribe en tipos del LENGUAJE (``"Body ptr mutable"``, no un tipo
de Python) porque su destinatario es la Semántica de suriaX: es la misma
firma que tendrá que validar contra el ``hook fn __gravity__(...)`` escrito
en ``.srcx``. Aquí solo se comprueba que esté PRESENTE y sea una cadena; el
parseo del tipo pertenece al frontend, que es quien tiene la gramática.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .errors import (EXT010, EXT011, EXT012, EXT020, EXT021, EXT022, EXT023,
                     EXT024, EXT025, EXT026, EXT027, ExtensionError)

#: nombre del decorador reconocido, en cualquiera de sus formas de import:
#: ``@hook(...)``, ``@htims.hook(...)``, ``@suriax.hook(...)``.
_DECORATOR = "hook"

#: constante de módulo que da nombre al proyecto (lo define el ``.py``, no el
#: nombre de los archivos).
_PROJECT_CONST = "PROJECT"

#: argumentos aceptados por el decorador.
_ARGS = ("name", "owner", "params", "returns", "logic")

#: Vocabulario FIJO del compilador (``V0/src/frontend/semantic/hooks.py``).
#: Está duplicado a propósito: importar la Semántica desde aquí rompería la
#: frontera del módulo (ver ``readme.md``). La sincronización no queda al
#: azar — ``test/unit/test_htims_declarations.py`` compara esta tupla contra
#: ``HOOK_SPECS`` y falla si alguien añade un hook y olvida este archivo.
RESERVED_HOOKS: Tuple[str, ...] = (
    "__free__", "__sizeof__", "__print__", "__len__",
    "__cast__", "__index__", "__index_set__", "__eq__",
    "__min__", "__max__",
)


@dataclass(frozen=True)
class HookDecl:
    """Una declaración de hook leída de un ``.py``.

    Es el dato que la Semántica consumirá para ampliar su vocabulario y que
    el HIR transportará como ``HookKind.EXTENDED`` + ``hook_name``.
    """

    name: str                    #: '__gravity__'
    owner: str                   #: tipo nominal dueño ('Body')
    params: Tuple[str, ...]      #: firma en tipos del LENGUAJE
    returns: str                 #: tipo de retorno del LENGUAJE
    logic: str                   #: símbolo en logic_dir (C++); '' si no hay
    func: str                    #: nombre de la función Python que lo declara
    module: str                  #: nombre de la extensión (basename sin .py)
    file: str                    #: ruta absoluta del .py
    line: int
    column: int

    @property
    def key(self) -> Tuple[str, str]:
        """Clave de despacho: ``(dueño, nombre)`` — la misma que el HIR."""
        return (self.owner, self.name)


def _is_hook_decorator(node: ast.expr) -> bool:
    """``@hook(...)``, ``@htims.hook(...)``, ``@suriax.hook(...)``.

    Solo la forma LLAMADA: un ``@hook`` sin paréntesis no trae ni dueño ni
    firma, así que no es una declaración utilizable.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == _DECORATOR
    if isinstance(func, ast.Attribute):
        return func.attr == _DECORATOR
    return False


def _literal_str(node: ast.expr) -> Optional[str]:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _literal_str_list(node: ast.expr) -> Optional[List[str]]:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    out: List[str] = []
    for item in node.elts:
        text = _literal_str(item)
        if text is None:
            return None
        out.append(text)
    return out


def _valid_hook_name(name: str) -> bool:
    """Forma ``__x__`` con algo en medio (misma que reconoce el lexer)."""
    return (name.startswith("__") and name.endswith("__") and len(name) > 4
            and name[2:-2].isidentifier())


def _scan_decorator(call: ast.Call, *, func_name: str, module: str, path: str
                    ) -> Tuple[Optional[HookDecl], List[ExtensionError]]:
    """Un ``@hook(...)`` -> declaración validada, o sus errores."""
    line, column = call.lineno, call.col_offset + 1
    errors: List[ExtensionError] = []

    def err(code: str, message: str) -> None:
        errors.append(ExtensionError(code, message, file=path, line=line,
                                     column=column))

    raw: dict[str, ast.expr] = {}
    if call.args:
        raw["name"] = call.args[0]
    if len(call.args) > 1:
        err(EXT026, "el decorador 'hook' acepta un solo argumento posicional "
                    "(el nombre); el resto van por palabra clave "
                    f"({', '.join(_ARGS[1:])})")
    for kw in call.keywords:
        if kw.arg is None:  # '**kwargs': no es declarable sin ejecutar
            err(EXT025, "'**' no es declarable: el escaneo no ejecuta el "
                        "archivo, así que cada argumento debe ser un literal")
            continue
        if kw.arg not in _ARGS:
            err(EXT026, f"argumento desconocido '{kw.arg}' en el decorador "
                        f"'hook' (aceptados: {', '.join(_ARGS)})")
            continue
        if kw.arg in raw:
            err(EXT026, f"argumento '{kw.arg}' duplicado")
            continue
        raw[kw.arg] = kw.value

    name = _literal_str(raw["name"]) if "name" in raw else None
    if "name" not in raw:
        err(EXT020, f"el hook declarado en '{func_name}' no tiene nombre: "
                    "@hook(\"__loquesea__\", owner=...)")
    elif name is None:
        err(EXT025, "el nombre del hook debe ser una cadena literal (el "
                    "escaneo no ejecuta el archivo)")
    elif not _valid_hook_name(name):
        err(EXT020, f"'{name}' no tiene la forma de un hook: se escribe entre "
                    "dobles guiones bajos ('__gravity__')")
        name = None

    owner = _literal_str(raw["owner"]) if "owner" in raw else None
    if "owner" not in raw:
        err(EXT021, f"el hook '{name or func_name}' no declara 'owner' (el "
                    "tipo dueño, p. ej. owner=\"Body\")")
    elif owner is None:
        err(EXT025, "'owner' debe ser una cadena literal")
    elif not owner.isidentifier():
        err(EXT021, f"'owner' no es un tipo con nombre válido: {owner!r}")
        owner = None

    returns = _literal_str(raw["returns"]) if "returns" in raw else None
    if "returns" not in raw:
        err(EXT022, f"el hook '{name or func_name}' no declara 'returns' (su "
                    "tipo de retorno, p. ej. returns=\"void\")")
    elif returns is None:
        err(EXT025, "'returns' debe ser una cadena literal")

    params: Optional[List[str]] = []
    if "params" in raw:
        params = _literal_str_list(raw["params"])
        if params is None:
            err(EXT023, "'params' debe ser una lista de cadenas literales con "
                        "los tipos del lenguaje: params=[\"Body ptr\", \"float\"]")

    logic = ""
    if "logic" in raw:
        found = _literal_str(raw["logic"])
        if found is None:
            err(EXT025, "'logic' debe ser una cadena literal (el símbolo de "
                        "la lógica C++ en logic_dir)")
        else:
            logic = found

    if name is not None and name in RESERVED_HOOKS:
        err(EXT027, f"'{name}' pertenece al vocabulario fijo del compilador y "
                    "no puede redefinirse desde una extensión; impleméntalo "
                    "como 'hook fn' en un .libsrx")

    if errors:
        return None, errors

    return HookDecl(
        name=name, owner=owner, params=tuple(params or ()), returns=returns,
        logic=logic, func=func_name, module=module, file=path,
        line=line, column=column,
    ), []


def scan_file(path: str) -> Tuple[str, List[HookDecl], List[ExtensionError]]:
    """Escanea UN ``.py``: devuelve ``(proyecto, declaraciones, errores)``.

    ``proyecto`` es el valor de ``PROJECT`` a nivel de módulo, o ``''``.
    El archivo no se importa en ningún momento.
    """
    module = os.path.splitext(os.path.basename(path))[0]
    try:
        with open(path, "rb") as fh:
            source = fh.read()
    except OSError as exc:
        return "", [], [ExtensionError(
            EXT010, f"no se pudo leer la extensión: {exc}", file=path)]

    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError) as exc:
        line = getattr(exc, "lineno", None) or 1
        column = getattr(exc, "offset", None) or 1
        return "", [], [ExtensionError(
            EXT011, f"la extensión no es Python válido: {exc.msg if isinstance(exc, SyntaxError) else exc}",
            file=path, line=line, column=column)]

    project = ""
    for node in tree.body:  # 'PROJECT' solo a nivel de módulo
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == _PROJECT_CONST:
                value = _literal_str(node.value)
                if value:
                    project = value

    decls: List[HookDecl] = []
    errors: List[ExtensionError] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not _is_hook_decorator(decorator):
                continue
            decl, decl_errors = _scan_decorator(
                decorator, func_name=node.name, module=module, path=path)
            errors.extend(decl_errors)
            if decl is not None:
                decls.append(decl)

    # orden estable por posición: dos corridas dan la misma lista y los
    # diagnósticos de duplicado siempre señalan la MISMA repetición.
    decls.sort(key=lambda d: (d.line, d.column))
    return project, decls, errors


def scan_files(paths: Sequence[str]) -> Tuple[str, List[HookDecl], List[ExtensionError]]:
    """Escanea varios ``.py`` y consolida el resultado.

    Detecta lo que un archivo aislado no puede ver: el mismo ``(dueño,
    hook)`` declarado dos veces (EXT024) y dos ``PROJECT`` en conflicto
    (EXT012).
    """
    project = ""
    project_file = ""
    decls: List[HookDecl] = []
    errors: List[ExtensionError] = []
    by_key: dict[Tuple[str, str], HookDecl] = {}

    for path in paths:
        found_project, found_decls, found_errors = scan_file(path)
        errors.extend(found_errors)
        if found_project:
            if project and found_project != project:
                errors.append(ExtensionError(
                    EXT012, f"el nombre del proyecto se declara dos veces con "
                            f"valores distintos: '{project}' en "
                            f"{os.path.basename(project_file)} y "
                            f"'{found_project}' aquí",
                    file=path))
            else:
                project, project_file = found_project, path
        for decl in found_decls:
            previous = by_key.get(decl.key)
            if previous is not None:
                errors.append(ExtensionError(
                    EXT024, f"el hook '{decl.name}' de '{decl.owner}' ya está "
                            f"declarado en {os.path.basename(previous.file)}:"
                            f"{previous.line}",
                    file=decl.file, line=decl.line, column=decl.column))
                continue
            by_key[decl.key] = decl
            decls.append(decl)

    return project, decls, errors


__all__ = ["RESERVED_HOOKS", "HookDecl", "scan_file", "scan_files"]
