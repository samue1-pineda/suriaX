"""Pasada 2 — Enlace de tipos nominales.

Cada tipo NOMINAL escrito en el fuente (``Punto p;``, ``ptr Punto``,
``fn f() -> Nodo?``, ``sizeof(Punto)``, ``make Punto in r``) debe apuntar a
un ``struct``/``enum``/``type`` registrado por la pasada 1. El que no,
produce ``ASTError.UnknownTypeError`` (AST005 — taxonomía reutilizada, ver
``ARQUITECTURA.md`` secc. 2).

El nombre puede venir CUALIFICADO (``const dt.int8 x;``): un tipo publicado
por una librería importada. Ese camino lo recorre
``type_service.lookup_type_path`` — esta pasada solo traduce su resultado al
diagnóstico correspondiente. Un tipo cuya raíz es un import que no cargó NO
produce error aquí (ya se reportó en el ``#import``).

Un solo recorrido O(n) del árbol (``include/ast_walk.py``): se visitan las
posiciones donde ``typed_ast.py`` dejó un ``Type`` resuelto y se valida cada
nombre nominal alcanzable (desenvolviendo ``ptr``/``?``). Los nombres ya
validados se cachean por pasada (``seen``) — en un programa con cientos de
usos de ``Punto`` la búsqueda en scope se paga una vez; los usos NO válidos
no se cachean para reportar cada ocurrencia con su posición real.

Aquí también se enlaza el hook ``__sizeof__`` (tabla de mapeo de
``ARQUITECTURA.md`` secc. 8: ``SizeofExpr`` es responsabilidad de esta
pasada): ``sizeof(T)`` con un ``__sizeof__(T ptr)`` declarado queda anotado
en ``SizeofExpr.hook`` para el HIR.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

try:
    from include import ast_nodes as ast
    from include.ast_walk import dispatch_walk
    from include.types_ast import Type, TypeKind
    from error_handler import ASTError, SemanticError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from include.ast_walk import dispatch_walk  # type: ignore
    from types_ast import Type, TypeKind  # type: ignore
    import ASTError  # type: ignore
    import SemanticError  # type: ignore

from . import type_service
from .context import SemanticContext
from .hooks import HookKind
from .symbol_table import Symbol


def run(program: ast.Program, ctx: SemanticContext) -> None:
    resolver = _TypeResolver(ctx)
    dispatch_walk(program, resolver.handlers)


def _canonical_name(symbol: Symbol, written: str) -> str:
    """Nombre CANONICO del tipo que declara ``symbol``.

    El usuario escribe ``dt.int8``; la libreria registro sus hooks (y su
    tipo de retorno) bajo el nombre con el que DECLARO el tipo (``int8``).

    Para un struct/enum ``Symbol.type`` ES su nominal, de ahi sale el nombre.
    Pero un alias ``const type int8`` tiene ``Symbol.type`` = metatipo
    (``TypeKind.META``), no un nominal — antes eso caia al nombre ESCRITO
    (``dt.int8``) y rompia el despacho de ``sizeof``/``cast`` cross-modulo
    (el hook esta bajo ``int8``, no ``dt.int8``). ``Symbol.name`` YA es el
    nombre declarado (bare) en ambos casos, asi que es la fuente correcta del
    canonico; ``written`` solo queda como red de seguridad si el simbolo no lo
    trae.
    """
    t = symbol.type
    if t is not None and t.kind is TypeKind.NOMINAL:
        return t.name
    return symbol.name or written


class _TypeResolver:
    __slots__ = ("ctx", "seen", "handlers")

    def __init__(self, ctx: SemanticContext) -> None:
        self.ctx = ctx
        # nombre escrito -> Symbol del tipo (ya validado). Se cachea el
        # SIMBOLO, no solo el hecho de existir, porque los usuarios del
        # nombre cualificado ('dt.int8') necesitan el nombre CANONICO del
        # tipo ('int8') para buscar sus hooks.
        self.seen: Dict[str, Symbol] = {}
        self.handlers: Dict[type, Callable] = {
            ast.Parameter: self._check_restype,
            ast.VarDecl: self._check_restype,
            ast.Field: self._check_restype,
            ast.FunctionDecl: self._check_return,
            ast.MakeExpr: self._check_restype,
            ast.SizeofExpr: self._check_sizeof,
            ast.CastExpr: self._check_cast,
        }

    def _check_restype(self, node) -> None:
        node.restype = self._check_type(node.restype, node.ln, node.col)

    def _check_return(self, node: ast.FunctionDecl) -> None:
        node.return_restype = self._check_type(
            node.return_restype, node.ln, node.col)

    def _check_sizeof(self, node: ast.SizeofExpr) -> None:
        # el Type interno ('sizeof(Punto)' -> Punto) no queda en restype
        # (restype de sizeof es 'int'); se valida desde el TypeExpr sintactico.
        inner = node.type
        while isinstance(inner, (ast.PointerTypeExpr, ast.NullableTypeExpr)):
            inner = inner.inner
        if isinstance(inner, ast.NominalTypeExpr):
            symbol = self._check_nominal(inner.name, node.ln, node.col)
            if symbol is not None:
                # el hook lo registro la libreria bajo el nombre CANONICO del
                # tipo ('int8'), no bajo el cualificado con el que se escribe
                # aqui ('dt.int8').
                node.hook = self.ctx.table.lookup_hook(
                    _canonical_name(symbol, inner.name), HookKind.SIZEOF,
                )

    def _check_cast(self, node: ast.CastExpr) -> None:
        """``cast<T>(x)`` con T NOMINAL: valida que T exista y CANONICALIZA
        el destino (``cast<dt.int8>(x)`` -> nominal ``int8``, el nombre bajo
        el que la librería registró sus conversiones). La resolución contra
        la tabla de casts es de ``scope_resolver`` (necesita el tipo del
        VALOR, que esta pasada no conoce)."""
        t = node.restype
        if t is None:
            return
        if t.kind is not TypeKind.NOMINAL:
            # destino primitivo o ENVUELTO (T ptr / T?): validar el nominal
            # del nucleo como cualquier anotacion; sin canonicalizar (la
            # tabla de casts opera sobre nominales planos).
            self._check_type(t, node.ln, node.col)
            return
        symbol = self._check_nominal(t.name, node.ln, node.col)
        if symbol is None:
            return  # tipo inexistente u OPACO: ya reportado (o silenciado)
        canonical = _canonical_name(symbol, t.name)
        if canonical != t.name:
            # reescritura EN SITIO (mismo patron que restype): el lookup en
            # la tabla de casts y el HIR usan el nombre canonico.
            node.restype = Type(TypeKind.NOMINAL, name=canonical)

    def _check_type(self, t: Optional[Type], ln: int,
                    col: int) -> Optional[Type]:
        """Valida el núcleo nominal de ``t`` y devuelve el tipo CANONICALIZADO.

        Devolver el tipo (en vez de solo validarlo) es lo que hace usable un
        tipo de librería escrito cualificado: ``var point.Point p`` se
        escribe con el nombre del módulo, pero la librería declaró su struct
        como ``Point`` y bajo ESE nombre registró sus hooks y el tipo de
        retorno de sus funciones. Sin la reescritura, ``point.Point`` y
        ``Point`` son dos nominales distintos que nunca unifican (AST006 al
        inicializar con ``point.build(...)``). Es la misma canonicalización
        que ya hacían ``cast<T>`` y ``sizeof``, aplicada también a las
        anotaciones corrientes.

        ``Type`` es frozen: la reescritura RECONSTRUYE la cadena de
        envoltorios (``ptr``/``?``/``error``), y solo cuando el nombre
        cambia — el caso común (nominal simple o tipo primitivo) devuelve el
        mismo objeto sin asignar nada.
        """
        # desenvuelve ptr/?/error hasta el nucleo; solo NOMINAL requiere enlace.
        # ('error' puede ir solo -> inner None, sin nada que enlazar.)
        wrappers = []
        core = t
        while core is not None and core.kind in (
            TypeKind.POINTER, TypeKind.NULLABLE, TypeKind.ERROR,
        ):
            wrappers.append(core)
            core = core.inner
        if core is None or core.kind is not TypeKind.NOMINAL:
            return t

        symbol = self._check_nominal(core.name, ln, col)
        if symbol is None:
            return t  # inexistente u opaco: ya reportado (o silenciado)
        canonical = _canonical_name(symbol, core.name)
        if canonical == core.name:
            return t

        rebuilt = Type(TypeKind.NOMINAL, name=canonical)
        for wrapper in reversed(wrappers):
            rebuilt = Type(wrapper.kind, name=wrapper.name, inner=rebuilt,
                           mut=wrapper.mut)
        return rebuilt

    def _check_nominal(self, name: str, ln: int, col: int) -> Optional[Symbol]:
        """El Symbol del tipo ``name``, o ``None`` (reportando el error).

        Los nombres ya validados se cachean: en un programa con cientos de
        usos de ``Punto`` la busqueda se paga una vez. Los NO validos no se
        cachean, para reportar cada ocurrencia con su posicion real.
        """
        cached = self.seen.get(name)
        if cached is not None:
            return cached

        result = type_service.lookup_type_path(name, self.ctx.scope)
        status = result.status

        if status is type_service.TypeLookup.OK:
            self.seen[name] = result.symbol
            return result.symbol
        if status is type_service.TypeLookup.OPAQUE:
            # el tipo viene de una libreria que no cargo: el error real ya se
            # reporto en el '#import'. Callar aqui evita una cascada de
            # errores derivados sobre cada uso del modulo.
            return None

        self.ctx.error(self._describe(result, name, ln, col))
        return None

    @staticmethod
    def _describe(result, name: str, ln: int, col: int):
        """El diagnostico concreto de un tipo que no resolvio."""
        status = result.status
        if status is type_service.TypeLookup.NO_MEMBER:
            detail = (f" (tipos disponibles: {', '.join(result.available)})"
                      if result.available else "")
            return SemanticError.UnknownLibraryMemberError(
                f"'{result.owner}' no publica el tipo '{result.missing}'{detail}",
                line=ln, column=col,
            )
        if status is type_service.TypeLookup.NOT_A_TYPE:
            return ASTError.UnknownTypeError(
                f"'{name}' no nombra un tipo: '{result.missing}' de "
                f"'{result.owner}' es {result.symbol.kind.name.lower()}",
                line=ln, column=col,
            )
        if "." in name:
            return ASTError.UnknownTypeError(
                f"el tipo '{name}' no está declarado: '{result.missing}' no es "
                "un módulo importado en este scope",
                line=ln, column=col,
            )
        return ASTError.UnknownTypeError(
            f"el tipo '{name}' no está declarado (struct/enum/type)",
            line=ln, column=col,
        )


__all__ = ["run"]
