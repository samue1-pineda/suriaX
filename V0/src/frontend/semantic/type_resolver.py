"""Enlace de tipos nominales — colaborador de la resolución de scopes.

Fue la **pasada 2** del frontend: un recorrido plano y propio de todo el
árbol. Dejó de serlo porque validar un tipo exige saber QUÉ SCOPE se está
mirando, y un recorrido sin scopes no puede: un ``type`` declarado dentro de
una función no lo veía nadie y su primer uso salía como ``AST005``.

Ahora es un colaborador al que ``scope_resolver`` llama en el punto exacto en
que cada anotación entra en juego. La lógica es la MISMA —no se duplicó nada,
se movió el *cuándo*—, y el frontend hace un recorrido menos.

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

Se valida cada nombre nominal alcanzable desde un ``Type`` que dejó
``typed_ast.py`` (desenvolviendo ``ptr``/``?``/``error``). Los nombres ya
validados se cachean (``seen``) — en un programa con cientos de usos de
``Punto`` la búsqueda en scope se paga una vez; los usos NO válidos no se
cachean, para reportar cada ocurrencia con su posición real.

**La caché es por SCOPE, no por programa.** Cuando era una pasada plana un
nombre resolvía siempre a lo mismo, así que cachearlo de por vida era
correcto. Con scopes deja de serlo: un tipo local puede sombrear a uno
global, y recordar el primero daría el tipo equivocado dentro del bloque. Por
eso ``invalidate()`` la vacía al abrir y cerrar un scope que declara tipos.

Aquí también se enlaza el hook ``__sizeof__`` (tabla de mapeo de
``ARQUITECTURA.md`` secc. 8: ``SizeofExpr`` es responsabilidad de esta
pasada): ``sizeof(T)`` con un ``__sizeof__(T ptr)`` declarado queda anotado
en ``SizeofExpr.hook`` para el HIR.
"""

from __future__ import annotations

from typing import Dict, Optional

try:
    from include import ast_nodes as ast
    from include.types_ast import Type, TypeKind, nullable_of, pointer_of
    from error_handler import ASTError, SemanticError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from types_ast import Type, TypeKind, nullable_of, pointer_of  # type: ignore
    import ASTError  # type: ignore
    import SemanticError  # type: ignore

from . import type_service
from .context import SemanticContext
from .hooks import HookKind
from .symbol_table import Symbol

try:
    from src.frontend.parser.typed_ast import resolve_type_expr
except ImportError:  # pragma: no cover - ejecucion directa
    from frontend.parser.typed_ast import resolve_type_expr  # type: ignore


def _core_nominal(t: Optional[Type]) -> Optional[str]:
    """Nombre del nucleo NOMINAL de ``t``, atravesando ``ptr``/``?``."""
    while t is not None and t.kind in (TypeKind.POINTER, TypeKind.NULLABLE):
        t = t.inner
    return t.name if t is not None and t.kind is TypeKind.NOMINAL else None


class TypeBinder:
    """Valida y canonicaliza los tipos nominales que escribe el usuario.

    Lo usa ``scope_resolver`` contra el scope ACTUAL; cada método se llama en
    el punto donde su anotación empieza a importar.
    """

    __slots__ = ("ctx", "seen")

    def __init__(self, ctx: SemanticContext) -> None:
        self.ctx = ctx
        # nombre escrito -> Symbol del tipo (ya validado). Se cachea el
        # SIMBOLO, no solo el hecho de existir, porque los usuarios del
        # nombre cualificado ('dt.int8') necesitan el nombre CANONICO del
        # tipo ('int8') para buscar sus hooks.
        self.seen: Dict[str, Symbol] = {}

    def invalidate(self) -> None:
        """Olvida lo cacheado: se entra o se sale de un scope con tipos propios.

        Sin esto un tipo local sobreviviria a su bloque y sombrearia al global
        en el resto del archivo — el error mas silencioso posible, porque el
        programa compilaria con el tipo equivocado.
        """
        self.seen.clear()

    def bind(self, node) -> None:
        """Canonicaliza el ``restype`` de una declaracion o expresion.

        Es el punto por el que pasan las TRES posiciones de valor —variable,
        parametro y campo de struct—, asi que la regla de que ``void`` no es
        el tipo de ningun valor se comprueba aqui una vez y no puede quedar
        una posicion sin cubrir. ``bind_return`` es otro metodo justamente
        porque ahi ``void`` SI es valido.
        """
        node.restype = self._check_type(node.restype, node.ln, node.col)
        if node.restype is not None and node.restype.kind is TypeKind.VOID:
            self.ctx.error(SemanticError.InvalidValueTypeError(
                "'void' significa \"no hay valor\": no puede ser el tipo de "
                f"'{getattr(node, 'name', '?')}'. Solo es valido como tipo de "
                "retorno",
                line=node.ln, column=node.col,
            ))

    def bind_return(self, node: ast.FunctionDecl) -> None:
        node.return_restype = self._check_type(
            node.return_restype, node.ln, node.col)

    def bind_sizeof(self, node: ast.SizeofExpr) -> None:
        """``sizeof(X)``: resuelve QUE se mide y enlaza su ``__sizeof__``.

        ``X`` puede nombrar un TIPO (``sizeof(int8)``) o un VALOR
        (``sizeof(a)``, el tamaño del tipo de ``a``). Se prueba primero el
        namespace de tipos: un nombre que es tipo no deja de serlo porque
        exista una variable homónima. Sin la segunda vía no había forma de
        preguntar el tamaño de algo sin saber ya su tipo — y por tanto ninguna
        de imprimirlo.

        El resultado va a ``node.medido`` (el tipo REAL medido, canonicalizado);
        ``node.type`` sigue siendo lo escrito.
        """
        # el Type interno ('sizeof(Punto)' -> Punto) no queda en restype
        # (restype de sizeof es 'int'); se valida desde el TypeExpr sintactico.
        inner = node.type
        while isinstance(inner, (ast.PointerTypeExpr, ast.NullableTypeExpr)):
            inner = inner.inner
        if not isinstance(inner, ast.NominalTypeExpr):
            node.medido = resolve_type_expr(node.type)
            return

        result = type_service.lookup_type_path(inner.name, self.ctx.scope)
        if result.status is type_service.TypeLookup.OK:
            medido = resolve_type_expr(node.type)
            canonical = type_service.canonical_name(result.symbol, inner.name)
            node.medido = self._recanonicalizar(medido, canonical)
            node.hook = self.ctx.table.lookup_hook(canonical, HookKind.SIZEOF)
            return
        if result.status is type_service.TypeLookup.OPAQUE:
            return  # libreria que no cargo: ya se reporto en el '#import'

        valor = self.ctx.scope.resolve_value(inner.name)
        if valor is None or valor.type is None:
            # ni tipo ni valor: el error de TIPO es el util, porque es la
            # posicion en la que se escribio.
            self._check_nominal(inner.name, node.ln, node.col)
            return
        # el tipo del simbolo viene de la TABLA, donde se guardo tal como se
        # escribio ('dt.int32'); el hook esta registrado bajo el canonico.
        node.medido = type_service.canonical(
            self._envolver(valor.type, node.type), self.ctx.scope)
        nucleo = _core_nominal(node.medido)
        if nucleo is not None:
            node.hook = self.ctx.table.lookup_hook(nucleo, HookKind.SIZEOF)

    @staticmethod
    def _recanonicalizar(t: Optional[Type], canonical: str) -> Optional[Type]:
        """Reescribe el NUCLEO nominal de ``t`` con su nombre canonico,
        conservando los envoltorios (``T ptr``, ``T?``) tal como se escribieron."""
        if t is None:
            return None
        if t.kind is TypeKind.NOMINAL:
            return Type(TypeKind.NOMINAL, name=canonical, args=t.args)
        if t.inner is None:
            return t
        return Type(t.kind, name=t.name, mut=t.mut,
                    inner=TypeBinder._recanonicalizar(t.inner, canonical))

    @staticmethod
    def _envolver(t: Type, escrito: ast.TypeExpr) -> Type:
        """Aplica a ``t`` los sufijos que se escribieron sobre el nombre.

        ``sizeof(a ptr)`` mide un puntero al tipo de ``a``. Los sufijos se
        recogen de fuera hacia dentro, asi que se aplican al reves."""
        sufijos = []
        cur = escrito
        while isinstance(cur, (ast.PointerTypeExpr, ast.NullableTypeExpr)):
            sufijos.append(cur)
            cur = cur.inner
        for suf in reversed(sufijos):
            t = (pointer_of(t, mut=suf.mutable)
                 if isinstance(suf, ast.PointerTypeExpr) else nullable_of(t))
        return t

    def bind_struct_literal(self, node: ast.StructLiteral,
                            symbol: Symbol) -> None:
        """``T{...}`` / ``Caja<int>{...}``: canonicaliza el nominal que produce
        el literal y valida sus ARGUMENTOS de tipo.

        El símbolo lo resolvió el llamador (necesita distinguir "no existe" de
        "no es un struct" con sus propios mensajes); aquí se aplica lo que le
        falta y que una anotación sí recibe: los argumentos son tipos y se
        validan/canonicalizan como tales, y la aridad se comprueba con la
        MISMA regla —``_check_arity``— que ``Caja<int>`` en una anotación. Sin
        esto, ``Caja<int>{...}`` y ``Caja{...}`` producirían tipos que no
        unifican con la anotación que los recibe.
        """
        t = node.restype
        if t is None or t.kind is not TypeKind.NOMINAL:
            return
        args = tuple(self._check_type(a, node.ln, node.col) or a
                     for a in t.args)
        self._check_arity(symbol, args, node.ln, node.col)
        canonical = type_service.canonical_name(symbol, t.name)
        if canonical != t.name or args != t.args:
            # el nombre CANONICO es el que viaja al HIR y el que usan la tabla
            # de hooks y la identidad de tipos; los argumentos, la identidad
            # del generico instanciado.
            node.type_name = canonical
            node.restype = Type(TypeKind.NOMINAL, name=canonical, args=args)

    def bind_cast(self, node: ast.CastExpr) -> None:
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
        canonical = type_service.canonical_name(symbol, t.name)
        if canonical != t.name:
            # reescritura EN SITIO (mismo patron que restype): el lookup en
            # la tabla de casts y el HIR usan el nombre canonico.
            node.restype = Type(TypeKind.NOMINAL, name=canonical)

    def check_type(self, t: Optional[Type], ln: int,
                   col: int) -> Optional[Type]:
        """Valida y canonicaliza un tipo escrito en una posicion que no es una
        declaracion con nombre — hoy, el payload de una variante de ``enum``.

        Envoltorio publico de la misma regla que usan las anotaciones: el
        payload son tipos del usuario y tienen que validarse igual, pero no
        cuelgan de un nodo con ``restype``, asi que ``bind`` no sirve.
        """
        return self._check_type(t, ln, col)

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

        # los ARGUMENTOS de un generico son tipos como cualquier otro: se
        # validan y canonicalizan igual (un 'Vector<point.Point>' tiene que
        # quedar como 'Vector<Point>' o no unificaria con nada).
        args = tuple(self._check_type(a, ln, col) or a for a in core.args)
        self._check_arity(symbol, args, ln, col)

        canonical = type_service.canonical_name(symbol, core.name)
        if canonical == core.name and args == core.args:
            return t

        rebuilt = Type(TypeKind.NOMINAL, name=canonical, args=args)
        for wrapper in reversed(wrappers):
            rebuilt = Type(wrapper.kind, name=wrapper.name, inner=rebuilt,
                           mut=wrapper.mut)
        return rebuilt

    def _check_arity(self, symbol, args, ln: int, col: int) -> None:
        """El uso de un generico trae tantos argumentos como parametros declara.

        Un parametro de tipo se salta la comprobacion consigo mismo: dentro de
        la libreria que declara ``Vector<T>``, la ``T`` de sus propias firmas
        es un tipo opaco sin parametros y no se esta instanciando nada.
        """
        esperados = len(symbol.type_params)
        if esperados == len(args):
            return
        if esperados == 0:
            self.ctx.error(SemanticError.TypeArityError(
                f"'{symbol.name}' no es un tipo generico: no admite argumentos "
                f"de tipo, y se le pasaron {len(args)}",
                line=ln, column=col))
            return
        firma = f"{symbol.name}<{', '.join(symbol.type_params)}>"
        self.ctx.error(SemanticError.TypeArityError(
            f"'{symbol.name}' declara {esperados} parametro(s) de tipo "
            f"({firma}) y se usa con {len(args)}",
            line=ln, column=col))

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


__all__ = ["TypeBinder"]
