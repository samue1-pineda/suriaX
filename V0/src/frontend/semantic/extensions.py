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
    from error_handler.error import CompilerError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from include.types_ast import Type  # type: ignore
    from error import CompilerError  # type: ignore

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


def format_type(t: Optional[Type]) -> str:
    """``Type`` -> notación POSTFIJA del lenguaje (``Body ptr mutable``).

    Delega en ``Type.__repr__``, que es el ÚNICO formateador: hubo dos (este,
    postfijo, y el ``repr``, prefijo) y los diagnósticos salían en una u otra
    notación según quién los escribiera. Este además perdía los argumentos de
    tipo (``Vector<int>`` salía ``Vector``). Se conserva el nombre porque es
    la forma explícita de pedirlo, y acepta ``None`` (``'?'``).
    """
    return "?" if t is None else repr(t)


def parse_declared_type(texto: str) -> Optional[Type]:
    """``"Body ptr mutable"`` -> ``Type``, o ``None`` si no es un tipo válido.

    Usa el lexer y la gramática de tipos REALES: lo que aquí se acepta es
    exactamente lo que se aceptaría escrito en un ``.srcx``. Para saber POR
    QUÉ no lo es, :func:`parse_declared_type_reason`.
    """
    return parse_declared_type_reason(texto)[0]


def parse_declared_type_reason(texto: str) -> Tuple[Optional[Type], Optional[str]]:
    """Como :func:`parse_declared_type`, con el MOTIVO cuando no es un tipo.

    Solo se atrapa lo que esperamos que pase con un texto que no es un tipo:
    los diagnósticos del lexer y del parser (``CompilerError``). Antes era un
    ``except Exception`` que devolvía ``None`` sin más: un fallo interno del
    compilador salía como "la firma usa tipos que no existen", y un error de
    sintaxis de la firma, sin decir cuál. Cualquier otra excepción es un
    defecto del compilador y sube (``ICE000``, con su traza).
    """
    from ..lexer.lexer import Lexer
    from ..parser.context import ParserContext
    from ..parser.cursor import Cursor
    from ..parser.grammar.types import parse_type
    from ..parser.typed_ast import resolve_type_expr

    texto = (texto or "").strip()
    if not texto:
        return None, "está vacío"
    try:
        lexer = Lexer(texto, file="<extends.srcx>")
        tokens = lexer.tokenize()
        if lexer.errors:
            return None, _motivo(lexer.errors[0])
        ctx = ParserContext()
        cursor = Cursor(tokens)
        type_expr = parse_type(cursor, ctx)
        if ctx.errors:
            return None, _motivo(ctx.errors[0])
        if type_expr is None:
            return None, "no es un tipo"
        # sobra texto = la cadena no era UN tipo ('int foo' no es un tipo)
        if not cursor.at_end():
            return None, "sobra texto después del tipo"
        return resolve_type_expr(type_expr), None
    except CompilerError as exc:  # el texto no es un tipo: se dice por qué
        return None, _motivo(exc)


def _motivo(diagnostico) -> str:
    """El mensaje de un diagnóstico del lexer/parser, sin su posición (que
    sería la de la cadena suelta, no la del ``.py`` que la declaró)."""
    mensaje = getattr(diagnostico, "message", None) or str(diagnostico)
    codigo = getattr(diagnostico, "code", None)
    return f"{codigo}: {mensaje}" if codigo else mensaje


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
            resuelto, motivo = parse_declared_type_reason(texto)
            if resuelto is None:
                malos.append(f"{texto!r} ({motivo})")
            else:
                params.append(resuelto)
        retorno, motivo = parse_declared_type_reason(decl.returns)
        if retorno is None:
            malos.append(f"{decl.returns!r} ({motivo})")
        if malos:
            problemas.append({
                "code": EXT030,
                "message": (f"la firma declarada de '{decl.name}' usa tipos que "
                            f"no existen en el lenguaje: {', '.join(malos)}"),
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
           "format_type", "parse_declared_type", "parse_declared_type_reason"]
