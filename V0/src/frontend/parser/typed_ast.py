"""Fase **AST-tipado**: resuelve las anotaciones de tipo ESCRITAS en el
codigo (``TypeExpr``) a un :class:`include.types_ast.Type` estructurado, y
adjunta el tipo trivial de cada literal.

NO hace resolucion de simbolos ni inferencia -- eso es Semantica (Fase 4 del
roadmap, aun no implementada): un tipo nominal se resuelve solo hasta su
**nombre** (``include.types_ast.nominal``), sin verificar que exista un
``struct``/``enum`` declarado con ese nombre.

Muta el mismo arbol en sitio (por eso los nodos de ``ast_nodes.py`` son
``@dataclass`` mutables, no ``frozen``) en lugar de reconstruir una copia
completa: evita duplicar el arbol solo para adjuntar tipos explicitos ya
conocidos sintacticamente.
"""

from __future__ import annotations

try:
    from include import ast_nodes as ast
    from include.ast_walk import walk
    from include.types_ast import (
        LITERAL_TYPES, META_TYPE, PRIMITIVE_TYPES, SELF_TYPE, Type, error_of,
        function_of, nominal, nullable_of, pointer_of,
    )
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from include.ast_walk import walk  # type: ignore
    from types_ast import (  # type: ignore
        LITERAL_TYPES, META_TYPE, PRIMITIVE_TYPES, SELF_TYPE, Type, error_of,
        function_of, nominal, nullable_of, pointer_of,
    )


def resolve_type_expr(type_expr: ast.TypeExpr) -> Type:
    """``TypeExpr`` sintactico -> ``Type`` resuelto.

    Puramente estructural: cada forma del EBNF (``type``) tiene una unica
    traduccion, sin ambiguedad ni busqueda de simbolos.
    """
    if isinstance(type_expr, ast.PrimitiveTypeExpr):
        return PRIMITIVE_TYPES[type_expr.name]
    if isinstance(type_expr, ast.PointerTypeExpr):
        return pointer_of(resolve_type_expr(type_expr.inner), mut=type_expr.mutable)
    if isinstance(type_expr, ast.NullableTypeExpr):
        return nullable_of(resolve_type_expr(type_expr.inner))
    if isinstance(type_expr, ast.ErrorTypeExpr):
        inner = resolve_type_expr(type_expr.inner) if type_expr.inner is not None else None
        return error_of(inner)
    if isinstance(type_expr, ast.NominalTypeExpr):
        # el nombre puede venir cualificado ('dt.int8'): se transporta entero,
        # el enlace hasta el simbolo es de la Semantica (type_resolver).
        # Los ARGUMENTOS de un generico ('Vector<int>') se resuelven aqui
        # mismo, recursivamente: son tipos como cualquier otro y participan
        # de la identidad ('Vector<int>' != 'Vector<str>').
        return nominal(type_expr.name,
                       tuple(resolve_type_expr(a) for a in type_expr.args))
    if isinstance(type_expr, ast.MetaTypeExpr):
        return META_TYPE
    if isinstance(type_expr, ast.SelfTypeExpr):
        return SELF_TYPE
    if isinstance(type_expr, ast.FunctionTypeExpr):
        # 'fn(int, str) -> bool': parametros en 'args', retorno en 'inner'
        # (ver include/types_ast.Type)
        return function_of(tuple(resolve_type_expr(p) for p in type_expr.params),
                           resolve_type_expr(type_expr.ret))
    raise TypeError(f"TypeExpr desconocido: {type(type_expr).__name__}")  # inalcanzable


def resolve_types(program: ast.Program) -> ast.Program:
    """Recorre el arbol completo y anota ``restype``/``return_restype`` en
    sitio. Devuelve el mismo objeto ``program`` (mutado), no una copia.

    Usa ``include/ast_walk.py`` (recorrido iterativo con cache de campos por
    clase) en vez de reflexion por nodo: ``dataclasses.fields()`` en cada
    visita era el costo dominante de esta fase en arboles grandes.
    """
    for node in walk(program):
        handler = _RESOLVERS.get(node.__class__)
        if handler is not None:
            handler(node)
    return program


def _resolve_var_like(node) -> None:  # Parameter | VarDecl | Field
    # el guardian sin nombre de un 'with' no tiene tipo escrito: se lo da la
    # Semantica a partir de su valor
    if getattr(node, "inferido", False):
        return
    node.restype = resolve_type_expr(node.type)


def _resolve_type_decl(node: ast.TypeDecl) -> None:
    # el tipo del BINDING de 'const type int8;' es el metatipo: 'int8' es un
    # valor de tipo 'type'. El tipo que DECLARA (nominal 'int8') lo construye
    # 'semantic/collect.py' a partir del nombre.
    node.restype = META_TYPE


def _resolve_function(node: ast.FunctionDecl) -> None:
    node.return_restype = resolve_type_expr(node.return_type)


def _resolve_lambda(node: ast.Lambda) -> None:
    # el retorno ESCRITO de la lambda; sus parametros son 'Parameter' y los
    # resuelve su propio handler, como los de una 'fn'
    node.return_restype = resolve_type_expr(node.return_type)


def _resolve_trait_method(node: ast.TraitMethod) -> None:
    """Prototipo de un método de trait: resuelve sus tipos de parámetro (sin
    nombre) y el retorno (``void`` sintético si se omitió). ``self`` queda
    como ``SELF_TYPE`` hasta que la conformidad lo sustituya por el tipo real."""
    node.param_restypes = [resolve_type_expr(t) for t in node.params]
    node.return_restype = (resolve_type_expr(node.return_type)
                           if node.return_type is not None
                           else PRIMITIVE_TYPES["void"])


def _resolve_literal(node: ast.Literal) -> None:
    if node.literal_kind != "null":  # 'null' se unifica en Semantica
        node.restype = LITERAL_TYPES[node.literal_kind]


def _resolve_interp(node: ast.InterpolatedString) -> None:
    node.restype = PRIMITIVE_TYPES["str"]


def _resolve_sizeof(node: ast.SizeofExpr) -> None:
    node.restype = PRIMITIVE_TYPES["int"]


def _resolve_cast(node: ast.CastExpr) -> None:
    # el tipo de 'cast<T>(x)' ES el T escrito: puramente estructural, la
    # validez de la conversion (pares nativos / hook __cast__) es semantica.
    node.restype = resolve_type_expr(node.type)


def _resolve_catch(node: ast.CatchClause) -> None:
    # 'catch (Fallo e)': el filtro es un tipo escrito por el usuario. Sin tipo
    # ('catch (e)') no hay nada que resolver: la rama atrapa cualquier cosa.
    if node.type is not None:
        node.restype = resolve_type_expr(node.type)


def _resolve_enum_item(node: ast.EnumItem) -> None:
    # el PAYLOAD de una variante son tipos como cualquier otro; sin resolver,
    # el constructor de la variante no tendria firma que verificar.
    node.payload_restypes = [resolve_type_expr(t) for t in node.payload]


def _resolve_struct_literal(node: ast.StructLiteral) -> None:
    # 'T{...}' produce un valor de tipo nominal T; la validacion de campos
    # (existencia, tipos) es de la Semantica. 'Caja<int>{...}' produce el
    # nominal CON sus argumentos: es lo que hace que el literal de un
    # generico sea del mismo tipo que la anotacion que lo recibe.
    node.restype = nominal(node.type_name,
                           tuple(resolve_type_expr(a) for a in node.type_args))


# despacho O(1) por clase (mismo patron que el resto del frontend)
_RESOLVERS = {
    ast.Parameter: _resolve_var_like,
    ast.VarDecl: _resolve_var_like,
    ast.Field: _resolve_var_like,
    ast.TypeDecl: _resolve_type_decl,
    ast.FunctionDecl: _resolve_function,
    ast.Lambda: _resolve_lambda,
    ast.TraitMethod: _resolve_trait_method,
    ast.Literal: _resolve_literal,
    ast.InterpolatedString: _resolve_interp,
    ast.SizeofExpr: _resolve_sizeof,
    ast.CastExpr: _resolve_cast,
    ast.StructLiteral: _resolve_struct_literal,
    ast.EnumItem: _resolve_enum_item,
    ast.CatchClause: _resolve_catch,
}


__all__ = ["resolve_types", "resolve_type_expr"]
