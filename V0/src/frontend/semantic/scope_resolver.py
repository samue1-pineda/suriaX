"""Pasada 3 — Resolución de scopes, nombres, mutabilidad y llamadas.

Recorre el cuerpo de cada función (y los statements de nivel superior) UNA
sola vez: scope ``BLOCK`` por bloque, ``REGION`` por región. En el MISMO
punto donde se resuelve cada símbolo se validan (cero recorridos extra, ver
``ARQUITECTURA.md`` secc. 7):

 - uso de nombres (``UndefinedSymbolError``),
 - mutabilidad (reasignar un ``const`` -> ``ImmutableAssignmentError``),
 - aridad de llamadas (``CallArityError``) y TIPO de cada argumento contra
   su parámetro (``TypeMismatchError``, sin coerciones implícitas),
 - miembros de librerías importadas (``IO.printf`` -> exports reales del
   ``.libsrx``; ``UnknownLibraryMemberError``),
 - existencia de regiones (``make T in r`` / ``x at r`` ->
   ``UndefinedRegionError``),
 - compatibilidad de tipos donde ya se conocen ambos lados (vía
   ``type_service`` — nunca comparando ``Type`` a mano),
 - y el DESPACHO de hooks de tipo: ``free x;`` -> ``__free__`` del tipo de
   ``x``; ``make T in r`` -> ``__make__`` de T; ``print(x)``/``x.print()``
   -> ``__print__``; ``len(x)``/``x.len()`` -> ``__len__``. El enlace queda
   anotado en el nodo (``.hook``) listo para el HIR.

La inferencia de tipos es DELIBERADAMENTE mínima (la Fase 3 aún no existe):
el visitor de expresiones devuelve el tipo cuando es gratis conocerlo
(literales, símbolos anotados, retornos de función) y ``None`` cuando no.
Ante ``None`` la pasada NUNCA reporta error (cero falsos positivos, mismo
principio que ``memory_check``, secc. 4.2).
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

try:
    from include import ast_nodes as ast
    from include.types_ast import PRIMITIVE_TYPES, Type, TypeKind, pointer_of
    from error_handler import ASTError, SemanticError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from types_ast import PRIMITIVE_TYPES, Type, TypeKind, pointer_of  # type: ignore
    import ASTError  # type: ignore
    import SemanticError  # type: ignore

from . import collect, type_service
from .context import SemanticContext
from .hooks import CALL_HOOKS, HookKind
from .symbol_table import ScopeKind, Symbol, SymbolKind

_BOOL = PRIMITIVE_TYPES["bool"]
_STR = PRIMITIVE_TYPES["str"]
_VOID = PRIMITIVE_TYPES["void"]
_INT = PRIMITIVE_TYPES["int"]
_ERROR = Type(TypeKind.ERROR)  # tipo del binding de un 'catch (e)'

# operadores que producen bool sin importar los operandos
_BOOL_OPS = frozenset({"==", "!=", "<", "<=", ">", ">=", "and", "or"})

# pares (origen, destino) de 'cast<T>(x)' NATIVOS entre primitivos. Tabla
# O(1) construida una vez (mismo patron que KEYWORDS del lexer). La
# identidad T->T no esta aqui: se acepta antes de consultar la tabla.
_NATIVE_CASTS = frozenset({
    (TypeKind.INT, TypeKind.FLOAT), (TypeKind.FLOAT, TypeKind.INT),
    (TypeKind.INT, TypeKind.CHAR), (TypeKind.CHAR, TypeKind.INT),
    (TypeKind.BOOL, TypeKind.INT),
})


def run(program: ast.Program, ctx: SemanticContext) -> None:
    resolver = _ScopeResolver(ctx)
    for item in program.items:
        if isinstance(item, ast.DecoratorDecl):
            item = item.target
        if isinstance(item, ast.FunctionDecl):
            resolver.resolve_function(item)
        elif isinstance(item, ast.TestDecl):
            resolver.resolve_test(item)
        elif isinstance(item, ast.Statement):
            resolver.visit_top_level_stmt(item)
        # struct/enum/directivas: sin cuerpos que resolver aqui


class _ScopeResolver:
    __slots__ = ("ctx", "locals", "_stmt_dispatch", "_expr_dispatch")

    def __init__(self, ctx: SemanticContext) -> None:
        self.ctx = ctx
        # mapa nombre -> Symbol de los locales de la funcion EN CURSO
        # (se publica en ctx.fn_locals para memory_check, pasada 4).
        self.locals: Optional[Dict[str, Symbol]] = None
        self._stmt_dispatch: Dict[type, Callable] = {
            ast.Block: self._stmt_block,
            ast.VarDecl: self._stmt_var_decl,
            ast.ImportBinding: self._stmt_import_binding,
            ast.RegionStmt: self._stmt_region,
            ast.NewStmt: self._stmt_new,
            ast.DeleteStmt: self._stmt_delete,
            ast.InRegionStmt: self._stmt_in_region,
            ast.MoveRegionStmt: self._stmt_move_region,
            ast.IfStmt: self._stmt_if,
            ast.WhileStmt: self._stmt_while,
            ast.MatchStmt: self._stmt_match,
            ast.CaseArm: self._stmt_case_arm,
            ast.ReturnStmt: self._stmt_return,
            ast.MoveStmt: self._stmt_move,
            ast.FreeStmt: self._stmt_free,
            ast.ExprStmt: self._stmt_expr,
            ast.ThrowStmt: self._stmt_throw,
            ast.TryStmt: self._stmt_try,
            ast.BreakStmt: self._stmt_noop,
            ast.ContinueStmt: self._stmt_noop,
        }
        self._expr_dispatch: Dict[type, Callable] = {
            ast.Literal: self._expr_literal,
            ast.InterpolatedString: self._expr_interp,
            ast.Identifier: self._expr_identifier,
            ast.UnaryOp: self._expr_unary,
            ast.AddrOf: self._expr_addrof,
            ast.BinaryOp: self._expr_binary,
            ast.Assignment: self._expr_assignment,
            ast.Placement: self._expr_placement,
            ast.Call: self._expr_call,
            ast.Index: self._expr_index,
            ast.MemberAccess: self._expr_member,
            ast.MakeExpr: self._expr_make,
            ast.SizeofExpr: self._expr_restype,
            ast.CastExpr: self._expr_cast,
            ast.StructLiteral: self._expr_struct_literal,
        }

    # ------------------------------------------------------------------ #
    # funciones y statements
    # ------------------------------------------------------------------ #
    def resolve_function(self, fn: ast.FunctionDecl) -> None:
        # prototipo (sin cuerpo): no hay statements que resolver. La firma ya
        # la valido collect (simbolo) y type_resolver (tipos de params/retorno).
        if fn.body is None:
            return
        ctx = self.ctx
        ctx.current_fn = fn
        self.locals = {}
        ctx.fn_locals[id(fn)] = self.locals

        ctx.push_scope(ScopeKind.FUNCTION)
        for p in fn.params:
            symbol = Symbol(name=p.name, kind=SymbolKind.PARAM, ln=p.ln,
                            col=p.col, type=p.restype, mutable=True)
            if not ctx.scope.define_value(symbol):
                ctx.error(SemanticError.DuplicateSymbolError(
                    f"parámetro duplicado '{p.name}'", line=p.ln, column=p.col,
                ))
            else:
                self.locals[p.name] = symbol
        # el cuerpo comparte el scope FUNCTION (los params son visibles);
        # cada '{}' interno anida su propio BLOCK.
        for stmt in fn.body.statements:
            self.visit_stmt(stmt)
        ctx.pop_scope()

        ctx.current_fn = None
        self.locals = None

    def resolve_test(self, test: ast.TestDecl) -> None:
        """Cuerpo de un ``test "..." { }``: se valida como un scope propio
        (sin params, sin retorno), igual que el cuerpo de una funcion. El
        runner lo ejecuta; la compilacion normal solo lo valida."""
        ctx = self.ctx
        prev_fn = ctx.current_fn
        ctx.current_fn = None  # un 'return' dentro de un test no tiene retorno
        self.locals = {}
        ctx.push_scope(ScopeKind.FUNCTION)
        for stmt in test.body.statements:
            self.visit_stmt(stmt)
        ctx.pop_scope()
        ctx.current_fn = prev_fn
        self.locals = None

    def visit_top_level_stmt(self, stmt: ast.Statement) -> None:
        """Statement suelto a nivel de ``Program``: se resuelve contra el
        scope global. Un ``VarDecl``/``ImportBinding`` global ya fue definido
        por la pasada 1 (para permitir referencias hacia adelante); aquí solo
        se validan sus expresiones, sin redefinirlo."""
        cls = stmt.__class__
        if cls is ast.VarDecl:
            self._check_var_init(stmt)
        elif cls is ast.ImportBinding:
            pass  # resuelto por collect (pasada 1)
        else:
            self.visit_stmt(stmt)

    def visit_stmt(self, stmt: ast.Statement) -> None:
        handler = self._stmt_dispatch.get(stmt.__class__)
        if handler is not None:
            handler(stmt)

    def _stmt_noop(self, stmt) -> None:
        pass  # break/continue: posicion ya validada por el parser

    def _stmt_block(self, node: ast.Block) -> None:
        self.ctx.push_scope(ScopeKind.BLOCK)
        for stmt in node.statements:
            self.visit_stmt(stmt)
        self.ctx.pop_scope()

    def _stmt_var_decl(self, node: ast.VarDecl) -> None:
        self._check_var_init(node)
        symbol = Symbol(name=node.name, kind=SymbolKind.VAR, ln=node.ln,
                        col=node.col, type=node.restype,
                        mutable=(node.qualifier != "const"),
                        region=self._enclosing_region_name())
        if not self.ctx.scope.define_value(symbol):
            self.ctx.error(SemanticError.DuplicateSymbolError(
                f"'{node.name}' ya está declarado en este scope",
                line=node.ln, column=node.col,
            ))
        elif self.locals is not None:
            self.locals[node.name] = symbol

    def _check_var_init(self, node: ast.VarDecl) -> None:
        if node.value is None:
            return
        value_type = self.visit_expr(node.value)
        if _is_null_literal(node.value):
            if not type_service.unify_literal_null(node.restype):
                self.ctx.error(ASTError.TypeMismatchError(
                    f"'null' no es asignable a '{node.restype!r}' (no es nullable)",
                    line=node.ln, column=node.col,
                ))
        elif not type_service.is_assignable(node.restype, value_type):
            self.ctx.error(ASTError.TypeMismatchError(
                f"no se puede inicializar '{node.name}' ({node.restype!r}) "
                f"con un valor de tipo '{value_type!r}'",
                line=node.ln, column=node.col,
            ))

    def _stmt_import_binding(self, node: ast.ImportBinding) -> None:
        # import dentro de un cuerpo: mismo mecanismo que collect, sobre el
        # scope actual (el simbolo muere con el bloque).
        collect.define_import(node.name, node.source, self.ctx,
                              mutable=(node.qualifier != "const"))

    def _stmt_region(self, node: ast.RegionStmt) -> None:
        ctx = self.ctx
        # los flags (shrd/mutable/na) viajan en el simbolo hacia el HIR; el
        # runtime ejecuta RBMM de verdad (C++/pybind11, agnostico del target).
        # Una region 'na' NO se auto-libera: su nombre PERSISTE en el scope
        # actual para que 'delete(region r)'/'move'/'in region r' la
        # referencien tras el bloque. Una region normal vive solo dentro de su
        # propio scope (se auto-libera al cerrarlo; el escape obvio lo cubre la
        # resolucion normal de nombres, ARQUITECTURA.md secc. 4.1).
        if node.na and not ctx.scope.define_value(self._make_region_symbol(node)):
            ctx.error(SemanticError.DuplicateSymbolError(
                f"región duplicada '{node.name}'", line=node.ln, column=node.col,
            ))
        ctx.push_scope(ScopeKind.REGION)
        ctx.scope.define_value(self._make_region_symbol(node))
        for stmt in node.body.statements:
            self.visit_stmt(stmt)
        ctx.pop_scope()

    def _make_region_symbol(self, node: ast.RegionStmt) -> Symbol:
        return Symbol(name=node.name, kind=SymbolKind.REGION, ln=node.ln,
                      col=node.col, shared=node.shared,
                      region_mutable=node.mutable, region_na=node.na)

    def _stmt_new(self, node: ast.NewStmt) -> None:
        """``new(... region r);`` -- inicializa una region como HANDLE: su
        nombre vive en el scope ACTUAL (persiste hasta 'delete(region r)')."""
        region_sym = Symbol(name=node.name, kind=SymbolKind.REGION, ln=node.ln,
                            col=node.col, shared=node.shared,
                            region_mutable=node.mutable, region_na=node.na)
        if not self.ctx.scope.define_value(region_sym):
            self.ctx.error(SemanticError.DuplicateSymbolError(
                f"'{node.name}' ya está declarado en este scope",
                line=node.ln, column=node.col,
            ))

    def _stmt_delete(self, node: ast.DeleteStmt) -> None:
        if node.name is not None:
            # 'delete(region r)': r debe resolver a una region.
            self._check_region(node.name, node.ln, node.col)
            return
        # 'delete()' sin argumento: solo dentro del bloque de una region.
        if self._enclosing_region_name() is None:
            self.ctx.error(SemanticError.InvalidDeleteError(
                "'delete()' sin argumento solo es válido dentro del bloque de "
                "una región (usa 'delete(region r)' fuera de ella)",
                line=node.ln, column=node.col,
            ))

    def _stmt_in_region(self, node: ast.InRegionStmt) -> None:
        """``in region r: ...`` -- opera EN el contexto de la region r; r debe
        existir. El cuerpo se resuelve por scope lexico normal."""
        self._check_region(node.region, node.ln, node.col)
        self.visit_stmt(node.body)

    def _stmt_move_region(self, node: ast.MoveRegionStmt) -> None:
        """``move region a -> region b`` -- ambas regiones deben existir."""
        self._check_region(node.src, node.ln, node.col)
        self._check_region(node.dst, node.ln, node.col)

    def _stmt_if(self, node: ast.IfStmt) -> None:
        self.visit_expr(node.condition)
        self._stmt_block(node.then_block)
        if node.else_branch is not None:
            if isinstance(node.else_branch, ast.IfStmt):
                self._stmt_if(node.else_branch)
            else:
                self._stmt_block(node.else_branch)

    def _stmt_while(self, node: ast.WhileStmt) -> None:
        self.visit_expr(node.condition)
        self._stmt_block(node.body)

    def _stmt_match(self, node: ast.MatchStmt) -> None:
        self.visit_expr(node.subject)
        for arm in node.cases:
            self._stmt_case_arm(arm)

    def _stmt_case_arm(self, node: ast.CaseArm) -> None:
        self.visit_expr(node.pattern)
        self.visit_stmt(node.body)

    def _stmt_return(self, node: ast.ReturnStmt) -> None:
        fn = self.ctx.current_fn
        expected = fn.return_restype if fn is not None else None
        if node.value is None:
            if expected is not None and expected != _VOID:
                self.ctx.error(ASTError.InvalidReturnTypeError(
                    f"'return;' sin valor en una función que devuelve '{expected!r}'",
                    line=node.ln, column=node.col,
                ))
            return
        value_type = self.visit_expr(node.value)
        if _is_null_literal(node.value):
            if not type_service.unify_literal_null(expected):
                self.ctx.error(ASTError.InvalidReturnTypeError(
                    f"'return null;' en una función que devuelve '{expected!r}' (no nullable)",
                    line=node.ln, column=node.col,
                ))
        elif not type_service.is_assignable(expected, value_type):
            self.ctx.error(ASTError.InvalidReturnTypeError(
                f"se devuelve '{value_type!r}' pero la función declara '{expected!r}'",
                line=node.ln, column=node.col,
            ))

    def _stmt_move(self, node: ast.MoveStmt) -> None:
        self.visit_expr(node.target)

    def _stmt_free(self, node: ast.FreeStmt) -> None:
        target_type = self.visit_expr(node.target)
        # 'free' opera sobre MEMORIA REFERENCIADA: exige un puntero. Con
        # tipo desconocido se deja pasar (permisivo, el MIR verifica).
        unwrapped = target_type
        while unwrapped is not None and unwrapped.kind is TypeKind.NULLABLE:
            unwrapped = unwrapped.inner
        if unwrapped is not None and unwrapped.kind is not TypeKind.POINTER:
            self.ctx.error(SemanticError.InvalidFreeTargetError(
                f"'free' sobre un valor de tipo '{target_type!r}' "
                "(se requiere 'ptr T')",
                line=node.ln, column=node.col,
            ))
            return
        # despacho de '__free__': se hace AQUI (donde el tipo del target ya
        # esta resuelto) y no en memory_check, que trabaja solo con identidad
        # de simbolos — mismo argumento de costo cero que la mutabilidad.
        owner = _nominal_name(target_type)
        if owner is not None:
            node.hook = self.ctx.table.lookup_hook(owner, HookKind.FREE)

    def _stmt_expr(self, node: ast.ExprStmt) -> None:
        self.visit_expr(node.expr)

    def _stmt_throw(self, node: ast.ThrowStmt) -> None:
        # 'throw expr;' valida su expresion; el tipo del valor lanzado es
        # libre (el catch lo recibe sin anotacion). El chequeo profundo de
        # que la funcion declare 'error T' queda para la Fase 3 de tipos.
        self.visit_expr(node.value)

    def _stmt_try(self, node: ast.TryStmt) -> None:
        # 'try { ... }': scope propio del bloque protegido.
        self._stmt_block(node.try_block)
        # 'catch (name) { ... }': el binding del error vive SOLO en el scope
        # del bloque catch (kind, tipo 'error' sin envolver).
        self.ctx.push_scope(ScopeKind.BLOCK)
        symbol = Symbol(name=node.catch_name, kind=SymbolKind.VAR,
                        ln=node.ln, col=node.col, type=_ERROR, mutable=False)
        self.ctx.scope.define_value(symbol)
        if self.locals is not None:
            self.locals[node.catch_name] = symbol
        for stmt in node.catch_block.statements:
            self.visit_stmt(stmt)
        self.ctx.pop_scope()

    # ------------------------------------------------------------------ #
    # expresiones (el visitor devuelve el tipo si es gratis conocerlo)
    # ------------------------------------------------------------------ #
    def visit_expr(self, expr: ast.Expression) -> Optional[Type]:
        handler = self._expr_dispatch.get(expr.__class__)
        if handler is None:
            return None
        restype = handler(expr)
        # anotacion en sitio (mismo patron que typed_ast): el tipo que el
        # visitor ya calculo queda en el arbol para el HIR — costo cero, es
        # un write de atributo sobre informacion que de otro modo se tira.
        expr.restype = restype
        return restype

    def _expr_literal(self, node: ast.Literal) -> Optional[Type]:
        return node.restype

    def _expr_interp(self, node: ast.InterpolatedString) -> Optional[Type]:
        for part in node.parts:
            if not isinstance(part, str):
                self.visit_expr(part)
        return _STR

    def _expr_identifier(self, node: ast.Identifier) -> Optional[Type]:
        symbol = self.ctx.scope.resolve_value(node.name)
        if symbol is None:
            self.ctx.error(SemanticError.UndefinedSymbolError(
                f"'{node.name}' no está declarado",
                line=node.ln, column=node.col,
            ))
            return None
        return symbol.type

    def _expr_unary(self, node: ast.UnaryOp) -> Optional[Type]:
        operand_type = self.visit_expr(node.operand)
        if node.operator == "not":
            return _BOOL
        return operand_type  # '-'

    def _expr_addrof(self, node: ast.AddrOf) -> Optional[Type]:
        """``&expr``: exige un lvalue (un temporal no tiene dirección estable).

        Mutabilidad del puntero resultante: ``&x`` sobre un binding ``var``
        da ``ptr mutable T`` (puedes escribir lo que posees); sobre un
        ``const`` da ``ptr T``. Para campos/índices se asume mutable y el
        MIR refina (permisivo: nunca rechazar un programa válido). La
        decisión queda anotada en ``node.mut`` para el HIR.
        """
        operand = node.operand
        operand_type = self.visit_expr(operand)
        cls = operand.__class__
        if cls is ast.Identifier:
            symbol = self.ctx.scope.resolve_value(operand.name)
            node.mut = symbol.mutable if symbol is not None else True
        elif cls in (ast.MemberAccess, ast.Index):
            node.mut = True
        else:
            self.ctx.error(SemanticError.InvalidAddressOfError(
                f"'&' sobre una expresión temporal ({cls.__name__}): "
                "solo variables, campos o índices tienen dirección",
                line=node.ln, column=node.col,
            ))
            return None
        return pointer_of(operand_type, mut=node.mut) if operand_type is not None else None

    def _expr_binary(self, node: ast.BinaryOp) -> Optional[Type]:
        left = self.visit_expr(node.left)
        right = self.visit_expr(node.right)
        if node.operator in _BOOL_OPS:
            return _BOOL
        # aritmetica: tipado fuerte, sin coerciones implicitas
        # (DESIGN_PRINCIPLES.md secc. 4) — solo si AMBOS lados se conocen.
        if left is not None and right is not None and left != right:
            self.ctx.error(ASTError.TypeMismatchError(
                f"operación '{node.operator}' entre tipos incompatibles "
                f"('{left!r}' y '{right!r}')",
                line=node.ln, column=node.col,
            ))
            return None
        return left if left is not None else right

    def _expr_assignment(self, node: ast.Assignment) -> Optional[Type]:
        value_type = self.visit_expr(node.value)
        target = node.target
        if isinstance(target, ast.Identifier):
            symbol = self.ctx.scope.resolve_value(target.name)
            if symbol is None:
                self.ctx.error(SemanticError.UndefinedSymbolError(
                    f"'{target.name}' no está declarado",
                    line=target.ln, column=target.col,
                ))
                return value_type
            if not symbol.mutable:
                self.ctx.error(SemanticError.ImmutableAssignmentError(
                    f"'{target.name}' es 'const' y no puede reasignarse",
                    line=node.ln, column=node.col,
                ))
            if _is_null_literal(node.value):
                if not type_service.unify_literal_null(symbol.type):
                    self.ctx.error(ASTError.TypeMismatchError(
                        f"'null' no es asignable a '{symbol.type!r}' (no es nullable)",
                        line=node.ln, column=node.col,
                    ))
            elif not type_service.is_assignable(symbol.type, value_type):
                self.ctx.error(ASTError.TypeMismatchError(
                    f"no se puede asignar '{value_type!r}' a "
                    f"'{target.name}' ({symbol.type!r})",
                    line=node.ln, column=node.col,
                ))
            return symbol.type
        # target compuesto (a.b = x, a[i] = x): se valida la base y, si la
        # base es un puntero de SOLO LECTURA ('ptr T' sin 'mutable'), la
        # escritura a traves de el es un error (const-correctness).
        if isinstance(target, (ast.MemberAccess, ast.Index)):
            base_type = self.visit_expr(target.obj)
            if base_type is not None and base_type.kind is TypeKind.POINTER \
                    and not base_type.mut:
                self.ctx.error(SemanticError.ReadOnlyPointerWriteError(
                    f"escritura a través de '{base_type!r}' (solo lectura); "
                    "declara el puntero como 'ptr mutable "
                    f"{base_type.inner!r}'",
                    line=node.ln, column=node.col,
                ))
            # resolver el miembro/indice en si (reusa la logica normal)
            if isinstance(target, ast.MemberAccess):
                return self._resolve_field(base_type, target) or value_type
            self.visit_expr(target.index)
            return value_type
        return self.visit_expr(target) or value_type

    def _expr_placement(self, node: ast.Placement) -> Optional[Type]:
        self._check_region(node.region, node.ln, node.col)
        return self.visit_expr(node.expr)

    def _expr_make(self, node: ast.MakeExpr) -> Optional[Type]:
        self._check_region(node.region, node.ln, node.col)
        owner = _nominal_name(node.restype)
        if owner is not None:
            node.hook = self.ctx.table.lookup_hook(owner, HookKind.MAKE)
        return node.restype

    def _expr_restype(self, node) -> Optional[Type]:
        return node.restype

    def _expr_struct_literal(self, node: ast.StructLiteral) -> Optional[Type]:
        """``T{ campo: expr, ... }``: valida que ``T`` sea un struct y que
        los campos escritos existan (y no se repitan). Los tipos de cada
        valor se dejan a la Fase 3 salvo lo gratis (mismo criterio permisivo).
        El tipo resultante es el nominal ``T`` (``node.restype``).

        ``T`` puede venir CUALIFICADO (``point.Point{ x: 1 }``): se resuelve
        por el mismo camino que una anotación (``lookup_type_path``, que
        atraviesa los miembros del módulo importado) y el nombre se
        CANONICALIZA al que declaró la librería — si no, el literal produce
        un nominal ``point.Point`` que nunca unifica con el ``Point`` que
        devuelven las funciones de esa misma librería."""
        written = node.type_name
        result = type_service.lookup_type_path(written, self.ctx.scope)
        struct_sym = result.symbol if \
            result.status is type_service.TypeLookup.OK else None
        if result.status is type_service.TypeLookup.OPAQUE:
            # librería que no cargó: el error real ya se reportó en el
            # '#import'; callar evita la cascada (mismo criterio que
            # type_resolver._check_nominal).
            for value in node.values:
                self.visit_expr(value)
            return node.restype
        if struct_sym is None:
            self.ctx.error(ASTError.UnknownTypeError(
                f"el tipo '{written}' no está declarado (struct)",
                line=node.ln, column=node.col,
            ))
        elif struct_sym.kind is not SymbolKind.STRUCT:
            self.ctx.error(ASTError.UnknownTypeError(
                f"'{node.type_name}' no es un struct: no puede instanciarse "
                "con '{...}'", line=node.ln, column=node.col,
            ))
        else:
            # nombre CANONICO: el que declaró la librería ('Point'), no el
            # cualificado con el que se escribe aquí ('point.Point'). Es el
            # que viaja al HIR (donde nombra el struct en runtime) y el que
            # usan la tabla de hooks y la identidad de tipos.
            canonical = struct_sym.type.name if (
                struct_sym.type is not None
                and struct_sym.type.kind is TypeKind.NOMINAL) else written
            if canonical != written:
                node.type_name = canonical
                node.restype = Type(TypeKind.NOMINAL, name=canonical)
            fields = struct_sym.members or {}
            seen: set = set()
            for fname, value in zip(node.field_names, node.values):
                self.visit_expr(value)
                if fname in seen:
                    self.ctx.error(SemanticError.DuplicateSymbolError(
                        f"campo '{fname}' repetido en el literal de "
                        f"'{written}'", line=node.ln, column=node.col,
                    ))
                elif fname not in fields:
                    self.ctx.error(SemanticError.UndefinedSymbolError(
                        f"'{written}' no tiene un campo '{fname}'",
                        line=node.ln, column=node.col,
                    ))
                seen.add(fname)
            return node.restype
        for value in node.values:
            self.visit_expr(value)
        return node.restype

    def _expr_cast(self, node: ast.CastExpr) -> Optional[Type]:
        """``cast<T>(x)``: la ÚNICA vía de conversión del lenguaje (cero
        coerciones implícitas, ``int8 b = cast<int8>(10);``).

        Resolución en orden (primer acierto gana):

        1. identidad ``T -> T`` (siempre válida, no-op);
        2. par NATIVO entre primitivos (:data:`_NATIVE_CASTS` — definido por
           el lenguaje, no anulable por librerías);
        3. TABLA DE CONVERSIONES (``SymbolTable.casts``): el ``__cast__``
           registrado para el par exacto ``(origen, destino)`` — cubre
           cualquier par que una librería declare (``int -> int8``,
           ``str -> Estado``, ``Estado -> vec``...). Enlaza ``node.hook``.
        4. nada: ``SEM016`` listando las conversiones declaradas que tocan
           alguno de los dos tipos (accionable).

        El ENCADENAMIENTO es explícito: ``cast<vec>(cast<Estado>(s))`` — la
        tabla nunca busca caminos intermedios. Origen desconocido (``None``):
        permisivo, cero falsos positivos (el par se re-verifica en el MIR).
        """
        value_type = self.visit_expr(node.value)
        target = node.restype
        if target is None or value_type is None:
            return target
        if target == value_type:
            return target
        if (value_type.kind, target.kind) in _NATIVE_CASTS:
            return target
        hook = self.ctx.table.lookup_cast(self._canonical(value_type), target)
        if hook is not None:
            node.hook = hook
            return target

        related = [
            f"{s!r} -> {t!r}" for (s, t) in self.ctx.table.casts
            if s == value_type or t == target
        ]
        detail = f" (declaradas: {', '.join(related)})" if related else \
            " (ninguna conversión declarada involucra estos tipos)"
        self.ctx.error(SemanticError.InvalidCastError(
            f"no existe conversión de '{value_type!r}' a '{target!r}'{detail}",
            line=node.ln, column=node.col,
        ))
        return None

    def _canonical(self, t: Type) -> Type:
        """Nominal CUALIFICADO (``dt.int8``) -> nominal canónico (``int8``).

        La tabla de casts se registra bajo el nombre con el que la librería
        declaró el tipo; un valor anotado con el nombre punteado no
        resolvería el par. Solo reescribe ese caso (una búsqueda O(saltos));
        cualquier otro tipo se devuelve tal cual.
        """
        if t.kind is not TypeKind.NOMINAL or "." not in (t.name or ""):
            return t
        result = type_service.lookup_type_path(t.name, self.ctx.scope)
        if result.status is type_service.TypeLookup.OK and result.symbol.type is not None:
            return result.symbol.type
        return t

    def _expr_index(self, node: ast.Index) -> Optional[Type]:
        obj_type = self.visit_expr(node.obj)
        self.visit_expr(node.index)
        # 'v[i]' sobre un tipo nominal con hook __index__: el tipo de la
        # expresión es el ELEMENTO (el retorno del hook). El indexado crudo de
        # un puntero/bloque no tiene tipo definido en esta fase (None).
        owner = _nominal_name(self._canonical(obj_type)) \
            if obj_type is not None else None
        if owner is not None:
            hook = self.ctx.table.lookup_hook(owner, HookKind.INDEX)
            if hook is not None:
                return hook.type
        return None

    def _expr_call(self, node: ast.Call) -> Optional[Type]:
        callee = node.callee
        # llamada por nombre plano: 'foo(...)', 'print(x)'
        if isinstance(callee, ast.Identifier):
            symbol = self.ctx.scope.resolve_value(callee.name)
            if symbol is not None:
                arg_types = [self.visit_expr(arg) for arg in node.args]
                self._check_call(symbol, node, arg_types)
                return symbol.type
            return self._call_hook_or_undefined(node, callee.name,
                                                node.args[0] if node.args else None,
                                                extra_args=node.args[1:])
        # llamada por member-access: 'IO.printf(...)', 'x.print()'
        if isinstance(callee, ast.MemberAccess):
            return self._call_member(node, callee)
        # cualquier otro callee (p. ej. resultado de otra llamada)
        self.visit_expr(callee)
        for arg in node.args:
            self.visit_expr(arg)
        return None

    def _import_chain_symbol(self, expr: ast.Expression) -> Optional[Symbol]:
        """Resuelve una cadena ``io.string`` / ``io`` a su símbolo IMPORT
        (submódulos incluidos), SIN reportar errores (el llamador decide).
        Devuelve ``None`` si la cadena no es de imports."""
        if isinstance(expr, ast.Identifier):
            symbol = self.ctx.scope.resolve_value(expr.name)
            return symbol if symbol is not None and symbol.kind is SymbolKind.IMPORT else None
        if isinstance(expr, ast.MemberAccess):
            base = self._import_chain_symbol(expr.obj)
            if base is None or base.members is None:
                return None
            member = base.members.get(expr.member)
            return member if member is not None and member.kind is SymbolKind.IMPORT else None
        return None

    def _call_member(self, node: ast.Call, callee: ast.MemberAccess) -> Optional[Type]:
        obj = callee.obj
        # cadena de imports de cualquier profundidad: 'IO.printf(...)',
        # 'io.string.printf(...)' — la base (import o submodulo) valida
        # existencia del miembro y aridad.
        base = self._import_chain_symbol(obj)
        if base is not None:
            member = self._resolve_import_member(base, callee)
            arg_types = [self.visit_expr(arg) for arg in node.args]
            if member is not None:
                self._check_call(member, node, arg_types)
                return member.type
            # si la base es opaca (members None) ya se reporto al importar;
            # si el miembro falta, _resolve_import_member ya reporto SEM011.
            return None
        # no es una libreria: 'x.__next__()' despacha a un DUNDER del usuario
        # (indexado por (tipo, nombre)); 'x.print()' a un hook del set fijo.
        obj_type = self.visit_expr(obj)
        for arg in node.args:
            self.visit_expr(arg)
        # canonicaliza el owner ('vec.Vector' -> 'Vector'): los dunders/hooks se
        # registran bajo el nombre con el que la librería declaró el tipo, pero
        # un valor puede venir anotado con el nombre CUALIFICADO (p. ej. un campo
        # 'vec.Vector buf', que no se canonicaliza en su sitio como sí lo hace
        # una variable). Sin esto, 'self.buf.push(x)' no encontraría el método.
        owner = _nominal_name(self._canonical(obj_type)) if obj_type is not None \
            else None
        # dunder del usuario: 'x.__metodo__()' -> el dunder (owner, member).
        # Anota el nodo (viaja al HIR); la EJECUCION real de dunders del
        # usuario esta diferida al runtime (como las regiones), no al MIR.
        dunder = self.ctx.table.lookup_dunder(owner, callee.member)
        if dunder is not None:
            node.hook = dunder
            return dunder.type
        hook_kind = CALL_HOOKS.get(callee.member)
        if hook_kind is not None and owner is not None:
            hook = self.ctx.table.lookup_hook(owner, hook_kind)
            if hook is not None:
                node.hook = hook
                return hook.type
        return None

    def _call_hook_or_undefined(self, node: ast.Call, name: str,
                                first_arg, extra_args) -> Optional[Type]:
        """``print(x)``/``len(x)`` sin función declarada con ese nombre:
        despacho al hook del tipo del primer argumento. Si el tipo no se
        conoce, se deja pasar en silencio (cero falsos positivos)."""
        hook_kind = CALL_HOOKS.get(name)
        if hook_kind is None:
            self.ctx.error(SemanticError.UndefinedSymbolError(
                f"'{name}' no está declarado",
                line=node.ln, column=node.col,
            ))
            for arg in node.args:
                self.visit_expr(arg)
            return None

        arg_type = self.visit_expr(first_arg) if first_arg is not None else None
        for arg in extra_args:
            self.visit_expr(arg)
        owner = _nominal_name(arg_type)
        if owner is None:
            return None  # tipo desconocido: permisivo
        hook = self.ctx.table.lookup_hook(owner, hook_kind)
        if hook is None:
            self.ctx.error(SemanticError.UndefinedSymbolError(
                f"'{name}' no está declarado y '{owner}' no define '__{name}__'",
                line=node.ln, column=node.col,
            ))
            return None
        node.hook = hook
        return hook.type

    def _expr_member(self, node: ast.MemberAccess) -> Optional[Type]:
        obj = node.obj
        # cadena de imports (submodulos incluidos) en posicion de valor
        import_base = self._import_chain_symbol(obj)
        if import_base is not None:
            member = self._resolve_import_member(import_base, node)
            return member.type if member is not None else None
        if isinstance(obj, ast.Identifier):
            base = self.ctx.scope.resolve_value(obj.name)
            if base is None:
                # acceso estatico a un TIPO: 'Color.Rojo' (enum item)
                base = self.ctx.scope.resolve_type(obj.name)
                if base is None:
                    self.ctx.error(SemanticError.UndefinedSymbolError(
                        f"'{obj.name}' no está declarado",
                        line=obj.ln, column=obj.col,
                    ))
                    return None
            if base.kind is SymbolKind.IMPORT:
                member = self._resolve_import_member(base, node)
                return member.type if member is not None else None
            if base.kind in (SymbolKind.ENUM, SymbolKind.STRUCT):
                return self._resolve_type_member(base, node)
            # instancia: 'p.x' -> campo del struct de su tipo
            return self._resolve_field(base.type, node)
        return self._resolve_field(self.visit_expr(obj), node)

    def _resolve_import_member(self, base: Symbol, node) -> Optional[Symbol]:
        if base.members is None:
            return None  # libreria opaca (no cargada): permisivo, ya reportado
        member = base.members.get(node.member)
        if member is None:
            self.ctx.error(SemanticError.UnknownLibraryMemberError(
                f"'{base.name}' no exporta '{node.member}'",
                line=node.ln, column=node.col,
            ))
        return member

    def _resolve_type_member(self, base: Symbol, node) -> Optional[Type]:
        member = base.members.get(node.member) if base.members else None
        if member is None:
            self.ctx.error(SemanticError.UndefinedSymbolError(
                f"'{base.name}' no define '{node.member}'",
                line=node.ln, column=node.col,
            ))
            return None
        return member.type

    def _resolve_field(self, obj_type: Optional[Type], node) -> Optional[Type]:
        owner = _nominal_name(obj_type)
        if owner is None:
            return None  # tipo desconocido / primitivo: permisivo
        struct_sym = self.ctx.scope.resolve_type(owner)
        if struct_sym is None or not struct_sym.members:
            return None
        member = struct_sym.members.get(node.member)
        if member is None:
            self.ctx.error(SemanticError.UndefinedSymbolError(
                f"'{owner}' no tiene un campo '{node.member}'",
                line=node.ln, column=node.col,
            ))
            return None
        return member.type

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _check_call(self, symbol: Symbol, node: ast.Call,
                    arg_types: list[Optional[Type]]) -> None:
        """Valida una llamada resuelta a un símbolo: ARIDAD (``SEM008``) y, si
        concuerda, el TIPO de cada argumento contra su parámetro (``AST006``,
        misma familia que init/asignación).

        Conservador: un tipo de argumento desconocido (``None``) pasa, igual
        que en init/asignación — cero falsos positivos (ver ``ARQUITECTURA.md``
        secc. 4.2). Sin coerciones implícitas: ``print(int)`` es un error de
        tipos; para imprimir un entero usa una f-string (``print(f"{x}")``) o
        ``cast<str>(x)``. La compatibilidad (incluida la mutabilidad de
        punteros: ``ptr mutable T`` -> ``ptr T`` sí, la inversa no) la decide
        ``type_service.is_assignable`` — nunca se compara ``Type`` a mano."""
        expected = symbol.param_types
        if expected is None:
            return
        if len(node.args) != len(expected):
            self.ctx.error(SemanticError.CallArityError(
                f"'{symbol.name}' espera {len(expected)} argumento(s), "
                f"recibe {len(node.args)}",
                line=node.ln, column=node.col,
            ))
            return
        for index, (arg, param_type, arg_type) in enumerate(
                zip(node.args, expected, arg_types), start=1):
            ln = getattr(arg, "ln", node.ln)
            col = getattr(arg, "col", node.col)
            if _is_null_literal(arg):
                if not type_service.unify_literal_null(param_type):
                    self.ctx.error(ASTError.TypeMismatchError(
                        f"argumento {index} de '{symbol.name}': 'null' no es "
                        f"asignable a '{param_type!r}' (no es nullable)",
                        line=ln, column=col,
                    ))
            elif not self._arg_assignable(param_type, arg_type):
                self.ctx.error(ASTError.TypeMismatchError(
                    f"argumento {index} de '{symbol.name}': se esperaba "
                    f"'{param_type!r}', se encontró '{arg_type!r}'",
                    line=ln, column=col,
                ))

    def _arg_assignable(self, target: Optional[Type],
                        value: Optional[Type]) -> bool:
        """Compatibilidad de un argumento con su parámetro. Delega en
        ``type_service.is_assignable`` y añade la única regla que el checker
        de llamadas necesita y que ``is_assignable`` no puede ver sin la tabla
        de símbolos: un valor de ENUM es asignable a ``int`` (los items de un
        enum son enteros, estilo C — ver ``test_enum_y_match``)."""
        if type_service.is_assignable(target, value):
            return True
        return target == _INT and self._is_enum_type(value)

    def _is_enum_type(self, t: Optional[Type]) -> bool:
        """¿``t`` es un tipo nominal que resuelve a un ``enum`` (simple o
        cualificado, ``Estado`` o ``col.hue.Color``)?"""
        if t is None or t.kind is not TypeKind.NOMINAL or t.name is None:
            return False
        result = type_service.lookup_type_path(t.name, self.ctx.scope)
        return (result.symbol is not None
                and result.symbol.kind is SymbolKind.ENUM)

    def _check_region(self, name: str, ln: int, col: int) -> None:
        symbol = self.ctx.scope.resolve_value(name)
        if symbol is None or symbol.kind is not SymbolKind.REGION:
            self.ctx.error(SemanticError.UndefinedRegionError(
                f"la región '{name}' no está declarada en este punto",
                line=ln, column=col,
            ))

    def _enclosing_region_name(self) -> Optional[str]:
        """Nombre de la región más interna que contiene al scope actual."""
        scope = self.ctx.scope
        while scope is not None:
            if scope.kind is ScopeKind.REGION:
                # el simbolo REGION es el unico kind REGION en 'values'
                for sym in scope.values.values():
                    if sym.kind is SymbolKind.REGION:
                        return sym.name
            scope = scope.parent
        return None


def _is_null_literal(expr: ast.Expression) -> bool:
    return isinstance(expr, ast.Literal) and expr.literal_kind == "null"


def _nominal_name(t: Optional[Type]) -> Optional[str]:
    """Nombre nominal 'nucleo' de un tipo, desenvolviendo ``ptr``/``?``.
    Es la identidad que usan los hooks (``__free__(T ptr)`` aplica tanto a
    ``T`` como a ``ptr T``)."""
    while t is not None and (t.kind is TypeKind.POINTER or t.kind is TypeKind.NULLABLE):
        t = t.inner
    if t is not None and t.kind is TypeKind.NOMINAL:
        return t.name
    return None


__all__ = ["run"]
