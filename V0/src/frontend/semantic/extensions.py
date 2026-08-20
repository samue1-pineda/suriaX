"""Vocabulario de hooks aportado por el PROYECTO (HTIMS) -> ``HookSpec``.

Aquí se cierra el círculo que abrió ``htims/``: aquel módulo descubre qué
declara el usuario (leyendo su Python **sin ejecutarlo**) y este traduce esa
declaración al vocabulario que la Semántica hace cumplir. A partir de ahí,
``hook fn __gravity__(Body ptr mutable b, float dt) -> void`` es un hook de
primera clase: se valida contra la firma declarada, viaja en el HIR con su
nombre y el intérprete lo despacha.

**Por qué la traducción vive aquí y no en** ``htims/``. La declaración escribe
los tipos en el lenguaje (``"Body ptr mutable"``), y decidir qué significa esa
cadena es competencia de la gramática — que vive en el frontend. ``htims/``
comprueba la FORMA (que haya nombre, dueño, params y retorno, y que sean
literales); este módulo comprueba el SIGNIFICADO. Así la capa de extensiones
sigue sin depender de ``V0/``.

**Se parsea, no se compara como texto.** Cada tipo declarado pasa por el mismo
lexer y la misma gramática de tipos que el compilador usa para el ``.srcx``, y
lo que se comparan son ``Type`` resueltos. Un ``"Body  ptr   mutable"`` con
espacios de más, o un ``"int?"``, valen exactamente lo que valdrían escritos
en el fuente — y una firma que no es un tipo del lenguaje se reporta con su
posición en el ``.py``, no se ignora.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

try:
    from include import ast_nodes as ast
    from include.types_ast import Type
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from include.types_ast import Type  # type: ignore

from .hooks import HookKind, HookSpec

#: código de los diagnósticos que produce esta traducción. Comparte la familia
#: EXT con ``htims/`` porque el problema es el mismo —una extensión mal
#: declarada— aunque lo detecte el frontend.
EXT030 = "EXT030"  # un tipo de la firma declarada no es un tipo del lenguaje
EXT031 = "EXT031"  # el hook declarado no puede pertenecer a un tipo (dueño)


@dataclass(frozen=True)
class DeclaredSignature:
    """La firma que la extensión PROMETIÓ, ya resuelta a tipos del lenguaje."""

    name: str                       #: '__gravity__'
    owner: str                      #: tipo nominal dueño ('Body')
    params: Tuple[Type, ...]        #: tipos de los parámetros, en orden
    returns: Type                   #: tipo de retorno
    module: str                     #: extensión que lo declaró ('physics')
    file: str
    line: int

    def describe(self) -> str:
        """La firma tal como se leería escrita en suriaX."""
        params = ", ".join(format_type(t) for t in self.params)
        return f"fn {self.name}({params}) -> {format_type(self.returns)}"


def format_type(t: Type) -> str:
    """``Type`` -> notación POSTFIJA del lenguaje (``Body ptr mutable``).

    ``Type.__repr__`` es prefija (``ptr mutable Body``) por historia del
    frontend; un diagnóstico dirigido al usuario tiene que hablar como se
    escribe el lenguaje.
    """
    from include.types_ast import TypeKind

    if t.kind is TypeKind.POINTER:
        return format_type(t.inner) + (" ptr mutable" if t.mut else " ptr")
    if t.kind is TypeKind.NULLABLE:
        return format_type(t.inner) + "?"
    if t.kind is TypeKind.NOMINAL:
        return t.name
    if t.kind is TypeKind.ERROR:
        return f"error {format_type(t.inner)}" if t.inner is not None else "error"
    return t.kind.name.lower()


def parse_declared_type(texto: str) -> Optional[Type]:
    """``"Body ptr mutable"`` -> ``Type``, o ``None`` si no es un tipo válido.

    Usa el lexer y la gramática de tipos REALES: lo que aquí se acepta es
    exactamente lo que se aceptaría escrito en un ``.srcx``.
    """
    from ..lexer.lexer import Lexer
    from ..parser.context import ParserContext
    from ..parser.cursor import Cursor
    from ..parser.grammar.types import parse_type
    from ..parser.typed_ast import resolve_type_expr

    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        lexer = Lexer(texto, file="<extends.srcx>")
        tokens = lexer.tokenize()
        if lexer.errors:
            return None
        ctx = ParserContext()
        cursor = Cursor(tokens)
        type_expr = parse_type(cursor, ctx)
        if ctx.errors or type_expr is None:
            return None
        # sobra texto = la cadena no era UN tipo ('int foo' no es un tipo)
        if not cursor.at_end():
            return None
        return resolve_type_expr(type_expr)
    except Exception:  # una firma rara no puede tumbar la compilación
        return None


def _spec_for(firma: DeclaredSignature) -> HookSpec:
    """El ``HookSpec`` de un hook de usuario.

    Los campos genéricos (``return_primitive``, ``owner_from_return``) no
    aplican: la firma declarada es MÁS estricta que cualquier convención, así
    que la validación se hace contra ``declared`` y estos quedan neutros.
    """
    return HookSpec(
        kind=HookKind.EXTENDED,
        owner_from_return=False,
        return_primitive=None,
        exact_params=len(firma.params),
        declared=firma,
    )


def build_vocabulary(extensions) -> Tuple[Dict[str, HookSpec], List[dict]]:
    """``ExtensionSet`` -> ``(specs por nombre sin guiones, diagnósticos)``.

    Las claves son el nombre SIN guiones (``gravity``), igual que
    ``HOOK_SPECS``: es lo que trae ``FunctionDecl.dunder``.

    Los diagnósticos son dicts (``code``/``message``/``file``/``line``) y no
    excepciones del frontend: describen un problema del PROYECTO, y el
    llamador los enruta como notas o errores según su contexto.
    """
    specs: Dict[str, HookSpec] = {}
    problemas: List[dict] = []
    if extensions is None:
        return specs, problemas

    for decl in getattr(extensions, "hooks", ()):  # duck-typing: htims.HookDecl
        crudo = decl.name.strip("_")
        params: List[Type] = []
        malos: List[str] = []
        for texto in decl.params:
            resuelto = parse_declared_type(texto)
            if resuelto is None:
                malos.append(texto)
            else:
                params.append(resuelto)
        retorno = parse_declared_type(decl.returns)
        if retorno is None:
            malos.append(decl.returns)
        if malos:
            problemas.append({
                "code": EXT030,
                "message": (f"la firma declarada de '{decl.name}' usa tipos que "
                            f"no existen en el lenguaje: {', '.join(repr(m) for m in malos)}"),
                "file": decl.file, "line": decl.line, "column": decl.column,
            })
            continue
        if not params:
            problemas.append({
                "code": EXT031,
                "message": (f"'{decl.name}' no declara parámetros: un hook "
                            "pertenece a un tipo, y el dueño es su primer "
                            "parámetro"),
                "file": decl.file, "line": decl.line, "column": decl.column,
            })
            continue

        specs[crudo] = _spec_for(DeclaredSignature(
            name=decl.name, owner=decl.owner, params=tuple(params),
            returns=retorno, module=decl.module, file=decl.file,
            line=decl.line,
        ))

    return specs, problemas


__all__ = ["EXT030", "EXT031", "DeclaredSignature", "build_vocabulary",
           "format_type", "parse_declared_type"]
