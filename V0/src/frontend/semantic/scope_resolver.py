"""Pasada 3 — Resolución de scopes, nombres, mutabilidad y llamadas.

Recorre el cuerpo de cada función (y los statements de nivel superior) UNA
sola vez: un scope ``BLOCK`` por bloque. En el MISMO
punto donde se resuelve cada símbolo se validan (cero recorridos extra, ver
``ARQUITECTURA.md`` secc. 7):

 - uso de nombres (``UndefinedSymbolError``),
 - mutabilidad (reasignar un ``const`` -> ``ImmutableAssignmentError``),
 - aridad de llamadas (``CallArityError``) y TIPO de cada argumento contra
   su parámetro (``TypeMismatchError``, sin coerciones implícitas),
 - miembros de librerías importadas (``IO.printf`` -> exports reales del
   ``.libsrx``; ``UnknownLibraryMemberError``),
 - compatibilidad de tipos donde ya se conocen ambos lados (vía
   ``type_service`` — nunca comparando ``Type`` a mano),
 - y el DESPACHO de hooks de tipo: ``free x;`` -> ``__free__`` del tipo de
   ``x``; ``print(x)``/``x.print()``
   -> ``__print__``; ``len(x)``/``x.len()`` -> ``__len__``. El enlace queda
   anotado en el nodo (``.hook``) listo para el HIR.

La inferencia de tipos es DELIBERADAMENTE mínima (la Fase 3 aún no existe):
el visitor de expresiones devuelve el tipo cuando es gratis conocerlo
(literales, símbolos anotados, retornos de función) y ``None`` cuando no.
Ante ``None`` la pasada NUNCA reporta error (cero falsos positivos, mismo
principio que ``memory_check``, secc. 4.2).
"""

from __future__ import annotations

import dataclasses
import os
from typing import Callable, Dict, List, Optional, Tuple

try:
    from include import ast_nodes as ast
    from include.ast_walk import walk as _walk
    from include.types_ast import (META_TYPE, PRIMITIVE_TYPES, Type, TypeKind,
                                   is_function, function_of, is_meta, nominal,
                                   pointer_of)
    from error_handler import ASTError, SemanticError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from include.ast_walk import walk as _walk  # type: ignore
    from types_ast import (META_TYPE, PRIMITIVE_TYPES, Type,  # type: ignore
                           TypeKind, is_function, function_of, is_meta,
                           nominal, pointer_of)
    import ASTError  # type: ignore
    import SemanticError  # type: ignore

from . import bounds as _bounds
from . import collect, type_service
from . import traits as _traits
from .bounds import BoundRef, bounds_text
from .extensions import format_type
from .type_resolver import TypeBinder
from .context import SemanticContext
from .hooks import CALL_HOOKS, HookKind
from .symbol_table import ScopeKind, Symbol, SymbolKind

_BOOL = PRIMITIVE_TYPES["bool"]
_STR = PRIMITIVE_TYPES["str"]
_VOID = PRIMITIVE_TYPES["void"]
_INT = PRIMITIVE_TYPES["int"]
_CHAR = PRIMITIVE_TYPES["char"]
_ERROR = Type(TypeKind.ERROR)  # tipo del binding de un 'catch (e)'

#: Tipos que NUNCA pueden indexarse: no tienen dónde declarar '__index__'.
_NO_INDEXABLES = frozenset({
    TypeKind.VOID, TypeKind.BOOL, TypeKind.INT, TypeKind.FLOAT,
    TypeKind.CHAR, TypeKind.STR, TypeKind.META, TypeKind.BYTE,
    TypeKind.FUNCTION,
})

#: lo que no se puede NEGAR con '-' (un 'byte' tiene su propio mensaje)
_NOT_NEGATABLE = frozenset({
    TypeKind.FUNCTION, TypeKind.STR, TypeKind.CHAR, TypeKind.BOOL,
    TypeKind.POINTER,
})

# operadores que producen bool sin importar los operandos
_BOOL_OPS = frozenset({"==", "!=", "<", "<=", ">", ">=", "and", "or"})


def _comparable(t: Type) -> Type:
    """El tipo que decide si dos valores se pueden comparar: sin el '?' ni
    el 'error' que lo envuelven y sin la mutabilidad de un puntero."""
    while t.kind in (TypeKind.NULLABLE, TypeKind.ERROR) and t.inner is not None:
        t = t.inner
    if t.kind is TypeKind.POINTER and t.inner is not None:
        return Type(TypeKind.POINTER, inner=_comparable(t.inner))
    return t


#: operadores de BITS: entre 'int' (y los tres que no desbordan, entre 'byte')
_BITS = frozenset({"&", "|", "^", "<<", ">>"})
_BITS_DE_BYTE = frozenset({"&", "|", "^"})


def _aritmetico(t: Type, operador: str) -> bool:
    """¿'operador' se aplica a valores de tipo 't'?

    Un ``byte`` es un DATO (un octeto de un archivo, de un protocolo), no un
    numero con el que se calcula: se compara y se enmascara (``&``, ``|``,
    ``^``, ``~``), que nunca sale de 0..255. Sumar o desplazar se hace en
    ``int`` (``cast<int>(b)``): asi un desborde no puede pasar sin verse."""
    if t.kind is TypeKind.BYTE:
        return operador in _BITS_DE_BYTE
    if operador in _BITS:
        return t.kind is TypeKind.INT
    if t.kind in (TypeKind.INT, TypeKind.FLOAT):
        return True
    return operador == "+" and t.kind is TypeKind.STR

# pares (origen, destino) de 'cast<T>(x)' NATIVOS entre primitivos. Tabla
# O(1) construida una vez (mismo patron que KEYWORDS del lexer). La
# identidad T->T no esta aqui: se acepta antes de consultar la tabla.
_NATIVE_CASTS = frozenset({
    (TypeKind.INT, TypeKind.FLOAT), (TypeKind.FLOAT, TypeKind.INT),
    (TypeKind.INT, TypeKind.CHAR), (TypeKind.CHAR, TypeKind.INT),
    (TypeKind.BOOL, TypeKind.INT),
    # 'byte': de 'int' TRUNCA (modulo 256, como 'cast<dt.int8>'); a 'int' es
    # exacto
    (TypeKind.INT, TypeKind.BYTE), (TypeKind.BYTE, TypeKind.INT),
    (TypeKind.BYTE, TypeKind.STR),
    # cualquier primitivo -> 'str': total y SIN perdida, la unica conversion de
    # la que eso se puede decir. La sabia hacer el interpolador de f-strings y
    # no habia forma de pedirla: sin ella, imprimir algo que no fuera ya una
    # cadena obligaba a envolverlo en un f-string. La vuelta ('str' -> int) NO
    # es nativa: puede fallar, y una conversion que falla necesita decir como.
    (TypeKind.INT, TypeKind.STR), (TypeKind.FLOAT, TypeKind.STR),
    (TypeKind.BOOL, TypeKind.STR), (TypeKind.CHAR, TypeKind.STR),
})


def run(program: ast.Program, ctx: SemanticContext) -> None:
    resolver = _ScopeResolver(ctx)
    # Las FIRMAS de todas las funciones se enlazan ANTES de resolver ningún
    # cuerpo: una llamada se comprueba contra la firma del Symbol, y con
    # recursión mutua ('factor' llama a 'expresion', declarada antes o
    # después) el llamado todavía no se había enlazado — su firma seguía tal
    # como se escribió y no unificaba con los tipos canónicos del llamador.
    for item in program.items:
        fn = item.target if isinstance(item, ast.DecoratorDecl) else item
        if isinstance(fn, ast.FunctionDecl):
            resolver.bind_signature(fn)
            _no_narrower_type_in_signature(fn, ctx)
        elif isinstance(item, ast.VarDecl):
            resolver.bind_global_type(item)
    # las globales se inician EN ORDEN: mientras no se llega a su
    # declaracion, una global no existe todavia (ver 'GlobalUsedTooEarlyError')
    pending = {item.name: item for item in program.items
               if isinstance(item, ast.VarDecl)}
    for position, item in enumerate(program.items):
        if isinstance(item, ast.DecoratorDecl):
            item = item.target
        if isinstance(item, ast.Statement) and pending:
            _no_global_before_declaration(item, pending, ctx)
            if isinstance(item, ast.VarDecl):
                pending.pop(item.name, None)
        if isinstance(item, ast.FunctionDecl):
            resolver.resolve_function(item)
        elif isinstance(item, ast.TestDecl):
            resolver.resolve_test(item)
        elif isinstance(item, ast.StructDecl):
            resolver.bind_struct(item)
        elif isinstance(item, ast.EnumDecl):
            resolver.bind_enum(item)
        elif isinstance(item, ast.Statement):
            resolver.visit_top_level_stmt(item)
            # 'print(a, b)' suelto en modo script: su bloque lo reemplaza
            expanded = resolver._print_expansions.pop(id(item), None)
            if expanded is not None:
                program.items[position] = expanded
        # enum/directivas: sus items no llevan tipos escritos por el usuario
    # con TODOS los cuerpos vistos: que copia cada generico y que instancia
    # copiaria un valor con destructor (SEM038)
    resolver.verificar_copias()
    resolver.unconsumed_expansions()


def run_generics(program: ast.Program, ctx: SemanticContext) -> None:
    """Resuelve SOLO los cuerpos GENERICOS de ``program`` y calcula que copia
    cada uno (``Symbol.copias``).

    La usa el linker al cargar una libreria: el import solo llega a la pasada
    1 (las firmas), y el consumidor necesita saber, al instanciar
    ``Vector<R>.get``, que ese cuerpo copia su ``T`` (SEM038). El resto de
    los cuerpos no dice nada de eso y no se mira. Los diagnosticos de esta
    pasada los descarta quien llama: la unidad se analiza completa al emitir
    su ``.phir``, y ahi salen, una sola vez.
    """
    resolver = _ScopeResolver(ctx)
    funciones = []
    for item in program.items:
        fn = item.target if isinstance(item, ast.DecoratorDecl) else item
        if isinstance(fn, ast.FunctionDecl):
            resolver.bind_signature(fn)
            funciones.append(fn)
        elif isinstance(fn, ast.StructDecl):
            resolver.bind_struct(fn)
        elif isinstance(fn, ast.EnumDecl):
            resolver.bind_enum(fn)
    for fn in funciones:
        if _es_generica(fn):
            resolver.resolve_function(fn)
    resolver.verificar_copias()
    resolver.unconsumed_expansions()


#: cuanto se ve cada reserva de visibilidad (sin token = publico)
_VISIBILITY_RANK = {"internal": 0, "private": 1, "public": 2, None: 2}
_VISIBILITY_TEXT = {"internal": "'internal' (solo su archivo)",
                    "private": "'private' (solo su paquete)"}


def _no_narrower_type_in_signature(fn: ast.FunctionDecl,
                                   ctx: SemanticContext) -> None:
    """AVISO (SEM049): una funcion de una LIBRERIA que se ve mas de lo que se
    ve un tipo de su firma (``fn f() -> P`` con ``private struct P``).

    Quien puede llamar a ``f`` no puede NOMBRAR ``P``: sin inferencia, ni
    siquiera guardar el resultado en una variable (``var P x = lib.f();`` es
    ``SEM011``); solo usarlo de paso (``lib.f().n``, ``lib.g(lib.f())``).
    Es un AVISO y no un error, como el lint ``private_interfaces`` de Rust
    (que fue el error E0446 hasta que se vio que rechazaba codigo correcto):
    el programa es valido, y la API casi nunca es la que se queria. Solo en
    una libreria: un programa no lo importa nadie."""
    if not (ctx.unit or (ctx.source_path or "").endswith(".libsrx")):
        return
    if fn.specifier in ("hook", "dunder") or fn.name.startswith("__"):
        return      # un hook se despacha por su tipo, no se llama por nombre
    rank = _VISIBILITY_RANK.get(fn.visibility, 2)
    if rank == 0:
        return
    firma = [(f"el parametro '{p.name}'", p.restype) for p in fn.params]
    firma.append(("el retorno", fn.return_restype))
    # los parametros de tipo ('T') se registran como tipos 'internal' (ver
    # collect), pero no son tipos de la firma: el consumidor pone el suyo
    own_params = set(fn.type_params or ()) | set(
        getattr(fn, "impl_type_params", None) or ())
    for where, typ in firma:
        for name in _nominal_names(typ):
            if name in own_params:
                continue
            symbol = ctx.table.global_scope.types.get(name.rsplit(".", 1)[-1]) \
                if "." not in name or name.startswith(f"{ctx.unit}.") else None
            if symbol is None or symbol.kind not in (
                    SymbolKind.STRUCT, SymbolKind.ENUM, SymbolKind.TYPE):
                continue
            if _VISIBILITY_RANK.get(symbol.visibility, 2) >= rank:
                continue
            ctx.error(SemanticError.NarrowerTypeInSignatureWarning(
                f"'{fn.name}' se ve fuera de "
                f"{'su paquete' if rank == 2 else 'su archivo'}, pero {where} "
                f"es de tipo '{symbol.name}', que es "
                f"{_VISIBILITY_TEXT[symbol.visibility]}: quien llama a "
                f"'{fn.name}' no puede nombrar ese tipo (ni guardar el valor "
                f"en una variable). Haz '{symbol.name}' tan visible como "
                f"'{fn.name}', o restringe '{fn.name}'",
                line=fn.ln, column=fn.col,
            ))
            return


def _nominal_names(t: Optional[Type]):
    """Los nombres nominales que aparecen en ``t`` (envoltorios, argumentos
    de tipo, parametros y retorno de un tipo funcion incluidos)."""
    pending = [t]
    while pending:
        t = pending.pop()
        if t is None:
            continue
        if t.kind is TypeKind.NOMINAL and t.name:
            yield t.name
        pending.extend(t.args)
        pending.append(t.inner)


def _no_global_before_declaration(stmt: ast.Statement, pending: dict,
                                  ctx: SemanticContext) -> None:
    """``var int a = b + 1;`` con ``b`` declarada DESPUES: SEM045.

    El nivel superior se ejecuta en el orden en que se escribe: al iniciar
    ``a``, ``b`` todavia no tiene valor. Antes compilaba y era ``RT006`` al
    ejecutar ("'b' no esta ligado"). Solo se mira el uso DIRECTO (el nombre
    escrito en la sentencia de nivel superior): una funcion llamada desde ahi
    que lee una global posterior sigue siendo ``RT006``, porque decidirlo
    exige saber que camino toma la funcion al ejecutar."""
    global_values = ctx.table.global_scope.values
    for node in _walk(stmt):
        if node.__class__ is not ast.Identifier:
            continue
        later = pending.get(node.name)
        if later is None:
            continue
        symbol = global_values.get(node.name)
        if symbol is None or symbol.kind is not SymbolKind.VAR \
                or (symbol.ln, symbol.col) != (later.ln, later.col):
            continue
        if later is stmt:
            why = (f"'{node.name}' se usa en su propio valor inicial: cuando se "
                   "evalua, todavia no tiene valor")
        else:
            user = (f"el valor inicial de '{stmt.name}'"
                    if isinstance(stmt, ast.VarDecl) else "esta sentencia")
            why = (f"'{node.name}' se usa en {user} pero se declara despues "
                   f"(linea {later.ln}): las globales se inician en el orden en "
                   f"que se escriben, y aqui '{node.name}' todavia no existe. "
                   f"Declara '{node.name}' antes")
        ctx.error(SemanticError.GlobalUsedTooEarlyError(
            why, line=node.ln, column=node.col))


def _es_generica(fn: ast.FunctionDecl) -> bool:
    """¿El cuerpo de ``fn`` habla de un parametro de tipo? Los suyos, los de
    su ``@impl``, o los de un receptor generico (``__index__(Vector<T> ptr
    self, ...)``)."""
    if fn.type_params or getattr(fn, "impl_type_params", None):
        return True
    receptor = _core(fn.params[0].restype) if fn.params else None
    return receptor is not None and receptor.kind is TypeKind.NOMINAL \
        and bool(receptor.args)


#: primitivas GENÉRICAS de las librerías (prototipos, sin cuerpo que mirar)
#: que COPIAN su ``T``. ``mem.copy`` copia celda a celda: con un ``T`` que
#: tiene destructor, cada celda quedaría con dos dueños.
_PRIMITIVAS_QUE_COPIAN = {
    "__copy__": "'__copy__' copia celda a celda (para mover, 'mem.move')",
}


class _LambdaFrame:
    """Una lambda cuyo cuerpo se esta resolviendo.

    ``sid`` es el scope de la lambda (el de sus parametros): todo lo que el
    cuerpo resuelve en un scope ANTERIOR que no es el global es del entorno,
    una CAPTURA. Los scopes se numeran al crearse, y los del cuerpo nacen
    despues que el de la lambda, asi que la comparacion es un entero."""

    __slots__ = ("node", "sid", "captures")

    def __init__(self, node: ast.Lambda, sid: int) -> None:
        self.node = node
        self.sid = sid
        self.captures: List[str] = []


class _ScopeResolver:
    __slots__ = ("ctx", "locals", "types", "_stmt_dispatch", "_expr_dispatch",
                 "_del_patron", "_writable_bindings", "_pattern_read_only",
                 "_subject_read_only", "_optional_content", "_match_subject",
                 "_bound_env", "_env_params", "_lambdas", "_fn_args_pending",
                 "_fn_args_ok", "_fn_args_bad", "_print_expansions",
                 "_globals_bound", "_signature_fn",
                 "_pattern_subjects", "_match_subject_text")

    def __init__(self, ctx: SemanticContext) -> None:
        self.ctx = ctx
        # enlace de tipos nominales: era la pasada 2, y ahora se invoca en el
        # punto donde cada anotacion entra en juego. Asi VE el scope, que es
        # lo que permite que un 'type' declarado dentro de una funcion exista.
        self.types = TypeBinder(ctx)
        # mapa nombre -> Symbol de los locales de la funcion EN CURSO
        # (se publica en ctx.fn_locals para memory_check, pasada 4).
        self.locals: Optional[Dict[str, Symbol]] = None
        # los Symbol (por id) que liga un 'case Nodo.A(x)': son el PAYLOAD
        # mismo, prestado. Cederlos es SEM036 (ver '_prestamo_de').
        self._del_patron: set = set()
        # los Symbol (por id) que no se REASIGNAN ('mutable=False') pero cuyo
        # contenido SI se modifica: lo atrapado por un 'catch' (una copia
        # propia: 'c.n = 50' vale) y lo que liga un patron sobre un sujeto
        # que se puede modificar ('k.n = 99' cambia el payload)
        self._writable_bindings: set = set()
        # lo que liga un patron sobre un sujeto que NO se puede modificar (un
        # 'const', algo detras de un 'T ptr'): id -> el motivo del sujeto
        self._pattern_read_only: dict = {}
        # el motivo del sujeto del 'match' en curso (None: se puede modificar)
        self._subject_read_only = None
        # el 'T' del sujeto del 'match' en curso si es un 'T?' (None si no lo
        # es): entonces 'case v' LIGA el contenido en vez de comparar
        self._optional_content: Optional[Type] = None
        # el tipo con que se comparan los patrones del 'match' en curso (el
        # contenido si el sujeto es un 'T?'): una variante de un enum
        # GENERICO tiene que ser de la MISMA instancia
        self._match_subject: Optional[Type] = None
        # las COTAS que ve la declaracion en curso: parametro -> {BoundRef}
        # (las escritas y las implicitas por su receptor), y sus parametros
        # de tipo. Fuera de un generico, vacios. Ver '_bound_env_of'.
        self._bound_env: Dict[str, frozenset] = {}
        self._env_params: frozenset = frozenset()
        # las LAMBDAS abiertas, de fuera hacia dentro (ver '_expr_lambda'): lo
        # que el cuerpo resuelve en un scope ANTERIOR al de la lambda (y que
        # no es global) es una CAPTURA, de solo lectura
        self._lambdas: List[_LambdaFrame] = []
        # FUNCIONES PRESTADAS que aparecen como argumento de una llamada en
        # curso: una lambda o un parametro de tipo 'fn(...) -> R'. Solo valen
        # ahi si el parametro que las recibe esta ESCRITO como tipo funcion
        # ('_mark_function_args'); lo que la llamada no confirma se rechaza
        # al cerrarla (SEM050/SEM051). id(arg) -> arg | parametro que no es
        # funcion (para el mensaje)
        self._fn_args_pending: Dict[int, ast.Expression] = {}
        self._fn_args_ok: set = set()
        self._fn_args_bad: Dict[int, tuple] = {}
        # 'print(a, b, c)' como sentencia: id(ExprStmt) -> el bloque de
        # 'print' de UN argumento que lo reemplaza (ver '_variadic_print').
        # Lo consume quien recorre la lista de sentencias
        # ('_visit_statements'); uno que quede sin consumir es un fallo del
        # compilador y se reporta al terminar (nunca se pierde en silencio).
        self._print_expansions: Dict[int, ast.Block] = {}
        # las globales (por id del VarDecl) cuyo tipo ya enlazo
        # 'bind_global_type', antes de los cuerpos
        self._globals_bound: set = set()
        # la funcion cuya FIRMA se enlaza ahora ('bind_signature'): una
        # anotacion 'Box<U>' en un parametro anota su cota 'Ord'/'Hash' POR
        # INSTANCIA en ella, como el cuerpo (A06)
        self._signature_fn: Optional[ast.FunctionDecl] = None
        # lo que liga un patron (id del Symbol) -> el texto del sujeto de su
        # 'match', para el mensaje de SEM036 (A04); y el del 'match' en curso
        self._pattern_subjects: Dict[int, str] = {}
        self._match_subject_text = ""
        # una anotacion 'Arbol<K, V>' comprueba las cotas de 'Arbol' con el
        # entorno de la declaracion que la escribe
        self.types.bound_check = self._check_type_bounds
        self._stmt_dispatch: Dict[type, Callable] = {
            ast.Block: self._stmt_block,
            ast.VarDecl: self._stmt_var_decl,
            ast.TypeDecl: self._stmt_type_decl,
            ast.ImportBinding: self._stmt_import_binding,
            ast.IfStmt: self._stmt_if,
            ast.WhileStmt: self._stmt_while,
            ast.MatchStmt: self._stmt_match,
            ast.CaseArm: self._stmt_case_arm,
            ast.ReturnStmt: self._stmt_return,
            ast.MoveStmt: self._stmt_move,
            ast.FreeStmt: self._stmt_free,
            ast.ExprStmt: self._stmt_expr,
            ast.ThrowStmt: self._stmt_throw,
            ast.ExpectStmt: self._stmt_expect,
            ast.TryStmt: self._stmt_try,
            ast.BreakStmt: self._stmt_noop,
            ast.ContinueStmt: self._stmt_noop,
        }
        self._expr_dispatch: Dict[type, Callable] = {
            ast.Literal: self._expr_literal,
            ast.InterpolatedString: self._expr_interp,
            ast.FormattedValue: self._expr_formatted,
            ast.Identifier: self._expr_identifier,
            ast.UnaryOp: self._expr_unary,
            ast.AddrOf: self._expr_addrof,
            ast.BinaryOp: self._expr_binary,
            ast.Assignment: self._expr_assignment,
            ast.Call: self._call_with_hint,
            ast.Index: self._expr_index,
            ast.MemberAccess: self._expr_member,
            ast.SizeofExpr: self._expr_sizeof,
            ast.CastExpr: self._expr_cast,
            ast.MoveExpr: self._expr_move,
            ast.StructLiteral: self._expr_struct_literal,
            ast.Lambda: self._expr_lambda,
        }

    # ------------------------------------------------------------------ #
    # funciones y statements
    # ------------------------------------------------------------------ #
    def bind_signature(self, fn: ast.FunctionDecl) -> None:
        """Enlaza y canoniza la FIRMA de ``fn`` (ver :func:`run`).

        Se valida siempre, cuerpo o no: un prototipo con un tipo inexistente
        en sus parametros es igual de erroneo, y es la forma en que una
        libreria declara lo que el host implementa.
        """
        previous = self._enter_bounds(fn)
        self._signature_fn = fn
        try:
            for p in fn.params:
                self.types.bind(p)
            self.types.bind_return(fn)
        finally:
            self._signature_fn = None
        self._firma_canonica(fn)
        self._bound_env, self._env_params = previous

    def resolve_function(self, fn: ast.FunctionDecl) -> None:
        # la firma ya se enlazó en 'bind_signature' (primera vuelta de 'run').
        # prototipo (sin cuerpo): no hay statements que resolver.
        if fn.body is None:
            copia = _PRIMITIVAS_QUE_COPIAN.get(fn.name)
            if copia is not None and fn.type_params:
                self.ctx.copias[id(fn)] = [
                    (nominal(p), copia) for p in fn.type_params]
            return
        ctx = self.ctx
        ctx.current_fn = fn
        self.locals = {}
        ctx.fn_locals[id(fn)] = self.locals
        previous = self._enter_bounds(fn)

        ctx.push_scope(ScopeKind.FUNCTION, f"fn {fn.name}")
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
        self._visit_statements(fn.body.statements)
        # el cuerpo comparte el scope FUNCTION, asi que sus drops -- y la
        # cuenta de capacidad -- se hacen aqui y no en '_stmt_block' (que
        # nunca lo visita).
        self._capacidad_desbordada(fn.body.statements)
        self._unreachable_after_exit(fn.body.statements)
        self._campos_sin_soltar(fn)
        self._anotar_drops(fn.body)
        self._pop_scope()

        ctx.current_fn = None
        self.locals = None
        self._bound_env, self._env_params = previous

    def bind_struct(self, node: ast.StructDecl) -> None:
        """Valida los tipos de los campos de un ``struct``.

        No hay cuerpo que recorrer, pero sus campos SI llevan anotaciones del
        usuario; cuando esto era una pasada aparte las alcanzaba su recorrido
        plano.
        """
        previous = self._enter_type_bounds(node)
        for field in node.fields:
            self.types.bind(field)
        self._bound_env, self._env_params = previous
        # TAMANO FINITO. Se comprueba aqui y no en 'collect' porque la
        # recursion mutua ('A' contiene 'B', 'B' contiene 'A') exige que los
        # dos esten ya declarados, y eso lo garantiza la pasada anterior.
        ciclo = type_service.infinite_size_path(node.name, self.ctx.scope)
        if ciclo is not None:
            camino = f"{node.name}." + ".".join(ciclo)
            self.ctx.error(SemanticError.InfiniteSizeTypeError(
                f"'{node.name}' se contiene a si mismo por valor "
                f"({camino}): no tiene tamano finito. Para una estructura "
                f"recursiva usa un puntero ('{node.name} ptr'), que se refiere "
                f"en vez de contener",
                line=node.ln, column=node.col,
            ))

    def bind_enum(self, node: ast.EnumDecl) -> None:
        """Valida el PAYLOAD de las variantes de un ``enum``.

        Un enum de solo variantes unidad no tiene nada que validar aqui —son
        enteros— y por eso esta pasada no lo miraba. Con payload si: sus tipos
        los escribe el usuario, y valen las mismas reglas que un campo de
        struct.
        """
        previous = self._enter_type_bounds(node)
        for item in node.items:
            for indice, tipo in enumerate(item.payload_restypes):
                self._bind_payload(node, item, indice, tipo)
        self._bound_env, self._env_params = previous
        # el SIMBOLO de cada variante lleva el payload con el que se la
        # construye y se la desestructura: tiene que ser el canonico, igual
        # que el del arbol. 'collect' lo registro como estaba escrito ('P'),
        # y dentro de una libreria el literal de struct ya es 'lib.P': los
        # dos no unificaban y 'E.Uno(P{...})' era un AST006 falso en la
        # misma libreria que declara 'E' y 'P'. En el programa (sin unidad)
        # no pasaba porque los dos nombres coinciden.
        simbolo = self.ctx.scope.resolve_type(node.name)
        if simbolo is not None and simbolo.kind is SymbolKind.ENUM and simbolo.members:
            for item in node.items:
                variante = simbolo.members.get(item.name)
                if variante is not None and item.payload_restypes:
                    variante.param_types = tuple(item.payload_restypes)

    def _bind_payload(self, node: ast.EnumDecl, item: ast.EnumItem,
                      indice: int, tipo: Type) -> None:
        donde = f"el valor {indice + 1} de '{node.name}.{item.name}'"
        canonico = self.types.check_type(tipo, item.ln, item.col)
        if canonico is not None:
            item.payload_restypes[indice] = canonico
            tipo = canonico
        if tipo is not None and tipo.kind is TypeKind.VOID:
            self.ctx.error(SemanticError.InvalidValueTypeError(
                f"'void' significa \"no hay valor\": no puede ser {donde}",
                line=item.ln, column=item.col,
            ))
            return
        # TAMANO FINITO: 'enum E { V(E) }' se contiene a si mismo por valor,
        # igual que un campo de struct. La recursion legitima va por puntero
        # ('V(E ptr)'), que es como se escribe un arbol.
        if tipo is not None and tipo.kind is TypeKind.NOMINAL \
                and _leaf_igual(tipo.name, node.name):
            self.ctx.error(SemanticError.InfiniteSizeTypeError(
                f"'{node.name}' se contiene a si mismo por valor en "
                f"'{item.name}': no tiene tamano finito. Usa un puntero "
                f"('{item.name}({node.name} ptr)'), que se refiere en vez de "
                "contener",
                line=item.ln, column=item.col,
            ))
            return
        # PROPIEDAD: un payload con destructor se destruye con el valor, POR
        # SU TIPO (la variante que haya al ejecutar). Era SEM029 mientras el
        # drop solo sabia recorrer rutas estaticas de campos.

    def resolve_test(self, test: ast.TestDecl) -> None:
        """Cuerpo de un ``test "..." { }``: se valida como un scope propio
        (sin params, sin retorno), igual que el cuerpo de una funcion. El
        runner lo ejecuta; la compilacion normal solo lo valida."""
        ctx = self.ctx
        prev_fn = ctx.current_fn
        ctx.current_fn = None  # un 'return' dentro de un test no tiene retorno
        self.locals = {}
        ctx.push_scope(ScopeKind.FUNCTION, f"test {test.name}")
        self._visit_statements(test.body.statements)
        # lo que muere al terminar el cuerpo, como en una funcion: sin esto un
        # local con destructor declarado en una prueba no se destruia nunca
        self._capacidad_desbordada(test.body.statements)
        self._unreachable_after_exit(test.body.statements)
        self._anotar_drops(test.body)
        self._pop_scope()
        # las clausulas: cada una un bloque corriente, con SU ambito (no ven
        # los locales del cuerpo, que ya murieron)
        for clausula in (test.errfinally, test.finally_block):
            if clausula is not None:
                self._stmt_block(clausula)
        ctx.current_fn = prev_fn
        self.locals = None

    def _pop_scope(self) -> None:
        """Cierra el scope actual, invalidando la cache de tipos si hacia falta.

        Un tipo declarado dentro de un bloque deja de existir al salir, pero la
        cache del binder recuerda nombre -> Symbol: sin vaciarla, ese tipo
        seguiria resolviendo en el resto del archivo y sombrearia al global.
        Seria el error mas silencioso posible — el programa compilaria, con el
        tipo equivocado. Solo se paga cuando el scope declaro tipos, que es el
        caso raro.
        """
        if self.ctx.scope.types:
            self.types.invalidate()
        self.ctx.pop_scope()

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
        """Despacha ``stmt`` a su handler.

        La tabla cubre TODAS las subclases de ``ast.Statement`` y un test lo
        verifica; si aun así llega una que no está, se reporta en vez de
        saltarla. Un nodo ignorado en silencio significa que nadie resolvió
        sus nombres ni anotó sus tipos, y eso no se nota hasta que el
        programa se ejecuta —fue exactamente lo que pasó con el inicializador
        de ``type_decl``.
        """
        handler = self._stmt_dispatch.get(stmt.__class__)
        if handler is None:
            self._sin_handler(stmt, "sentencia")
            return
        handler(stmt)

    def _visit_statements(self, statements: list) -> None:
        """Visita una lista de sentencias y aplica, EN SU SITIO, los
        reemplazos que pidio una sentencia al visitarse: hoy solo el de
        ``print(a, b, c)`` (ver :meth:`_variadic_print`)."""
        for index, stmt in enumerate(statements):
            self.visit_stmt(stmt)
            expanded = self._print_expansions.pop(id(stmt), None)
            if expanded is not None:
                statements[index] = expanded

    def unconsumed_expansions(self) -> None:
        """Un ``print`` variadico cuyo reemplazo nadie aplico: llego por un
        camino que no recorre una lista de sentencias. Seria escribir solo
        el primer argumento en silencio; se reporta como fallo interno."""
        for block in self._print_expansions.values():
            self.ctx.error(SemanticError.MissingHandlerError(
                "'print' con varios argumentos en una posicion que la "
                "resolucion de scopes no reemplazo: es un fallo del "
                "compilador, no del programa",
                line=block.ln, column=block.col,
            ))
        self._print_expansions.clear()

    def _stmt_noop(self, stmt) -> None:
        pass  # break/continue: posicion ya validada por el parser

    def _stmt_block(self, node: ast.Block) -> None:
        self.ctx.push_scope(ScopeKind.BLOCK, f"bloque @{node.ln}")
        self._visit_statements(node.statements)
        self._capacidad_desbordada(node.statements)
        self._unreachable_after_exit(node.statements)
        self._anotar_drops(node)
        self._pop_scope()

    #: sentencias tras las cuales el resto del MISMO bloque no se ejecuta
    _EXITS = {ast.ReturnStmt: "return", ast.ThrowStmt: "throw",
              ast.BreakStmt: "break", ast.ContinueStmt: "continue"}

    def _unreachable_after_exit(self, statements) -> None:
        """AVISO (SEM048): sentencias detras de un ``return``, ``throw``,
        ``break`` o ``continue`` del mismo bloque, que nunca se ejecutan.

        Es un aviso y no un error (decision del mantenedor): el programa es
        valido y hace lo que dice; lo que probablemente no es, es lo que su
        autor quiso. Solo el MISMO bloque, que es lo que se ve sin analizar
        el flujo: un ``if`` cuyas dos ramas devuelven no cuenta. Se avisa una
        vez, en la primera sentencia muerta."""
        for index, stmt in enumerate(statements[:-1]):
            exit_word = self._EXITS.get(stmt.__class__)
            if exit_word is None:
                continue
            dead = statements[index + 1]
            self.ctx.error(SemanticError.UnreachableCodeWarning(
                f"esta sentencia nunca se ejecuta: el '{exit_word}' de la "
                f"linea {stmt.ln} sale antes del bloque. Quitala, o mueve el "
                f"'{exit_word}' al final",
                line=dead.ln, column=dead.col,
            ))
            return

    def _capacidad_desbordada(self, statements) -> None:
        """``int vec.Vector v[2];`` con tres ``push`` seguidos: SEM033.

        Se cuenta lo que NO depende de la ejecucion: los ``push`` que estan
        uno detras de otro en este mismo bloque, sin condicion ni bucle de por
        medio. Cualquier otro (dentro de un ``if``, de un ``while``, tras una
        llamada que pudo hacer lo suyo) no se mira — afirmar ahi que no cabe
        rechazaria programas correctos, y el vector ya lanza en ejecucion.

        Es una comprobacion LOCAL a proposito: no hay analisis de flujo en el
        frontend, y montarlo para esto seria pagar una infraestructura entera
        por el caso que se escribe al aprender.
        """
        capacidad: dict = {}
        for stmt in statements:
            if isinstance(stmt, ast.VarDecl):
                literal = _entero_literal(stmt.capacity)
                if literal is not None:
                    capacidad[stmt.name] = [literal, 0, stmt]
                else:
                    capacidad.pop(stmt.name, None)
                continue
            objetivo = _push_sobre(stmt)
            if objetivo is None:
                continue
            entrada = capacidad.get(objetivo)
            if entrada is None:
                continue
            entrada[1] += 1
            if entrada[1] > entrada[0]:
                self.ctx.error(SemanticError.ContainerOverflowError(
                    f"'{objetivo}' reservo {entrada[0]} espacio(s) y este es "
                    f"el push numero {entrada[1]}: esta fuera de los limites. "
                    f"Reserva mas en su declaracion "
                    f"('{objetivo}[{entrada[1]}]') o quita los que sobran",
                    line=stmt.ln, column=stmt.col,
                ))
                # una sola vez por variable: el resto de la cuenta diria lo
                # mismo con otro numero.
                capacidad.pop(objetivo, None)

    #: aviso de un '__free__' que se olvida de un campo con recursos.
    NOTE_CAMPO_SIN_SOLTAR = "NOTE002"

    def _campos_sin_soltar(self, fn: ast.FunctionDecl) -> None:
        """``__free__`` que no suelta un campo que posee recursos: NOTE002.

        Un tipo que declara ``__free__`` se hace cargo de TODO lo suyo, sus
        campos incluidos: el compilador deja de bajar a ellos (ver
        ``_aplanar_drops``). Es una regla razonable —quien escribe el
        destructor sabe en qué orden hay que soltar— pero silenciosa: si se
        olvida un campo, ese campo no se destruye nunca y nada lo dice.

        Se avisa, no se rechaza: el campo puede soltarse por una vía que esta
        comprobación no ve (una función auxiliar, un ``move``). Buscar un
        ``free`` que lo nombre cubre la forma en que se escribe siempre y no
        inventa un análisis de flujo que el frontend no tiene.
        """
        if fn.dunder != "free" or not fn.params:
            return
        dueno = _nominal_name(self._canonical(fn.params[0].restype))
        if dueno is None:
            return
        simbolo = type_service.lookup_type_path(dueno, self.ctx.scope).symbol
        if simbolo is None or not simbolo.members:
            return
        soltados = _nombres_liberados(fn.body)
        for nombre, campo in simbolo.members.items():
            if campo.kind is not SymbolKind.FIELD:
                continue
            if not type_service.owns_resources(campo.type, self.ctx.scope,
                                               self.ctx.table):
                continue
            if nombre in soltados:
                continue
            self.ctx.notes.append({
                "code": self.NOTE_CAMPO_SIN_SOLTAR,
                "message": (
                    f"'{fn.name}' de '{dueno}' no suelta el campo '{nombre}', "
                    f"que posee recursos. Al declarar '__free__' el tipo se "
                    f"hace cargo de sus campos y el compilador ya no baja a "
                    f"ellos: escribe 'free &{fn.params[0].name}.{nombre};' o "
                    f"quita el '__free__' para que se destruyan solos"),
                "file": self.ctx.source_path, "line": fn.ln, "column": fn.col,
            })

    def _anotar_drops(self, block: ast.Block) -> None:
        """Anota que valores mueren al cerrar ``block``.

        Se hace AQUI, con el scope todavia abierto, por dos razones: el scope
        ES la lista de locales del bloque en orden de declaracion, y es el
        unico momento en que un tipo declarado dentro del bloque
        (``const type T;``) todavia resuelve. Despues de esta pasada los
        scopes se descartan y la pregunta ya no se puede hacer.

        Los ``VAR`` y los PARAMETROS por valor que la funcion posee (ver
        :meth:`_parametro_propio`): pasar por valor algo con destructor exige
        ``move`` en la llamada (SEM032), asi que el parametro es el UNICO
        dueño y, si no lo transfiere antes, lo destruye al salir. Antes los
        parametros no se destruian nunca y ``consumir(move x)`` perdia el
        recurso en silencio: el llamador ya no era dueño y el llamado tampoco.
        El orden es INVERSO al de declaracion — lo ultimo que nace es lo
        primero que muere, para que un valor pueda depender de otro declarado
        antes (los parametros, declarados primero, mueren al final).

        Que la lista sea estatica no significa que el drop sea incondicional:
        el runtime la recorre y solo destruye lo que siga vivo (la celda sabe
        si fue movida o liberada). Por eso un ``move`` dentro de un ``if`` no
        necesita nada especial aqui.
        """
        ctx = self.ctx
        drops: List[ast.Drop] = []
        genericos = self._genericos()
        for symbol in ctx.scope.values.values():
            if symbol.kind is SymbolKind.PARAM:
                if not self._parametro_propio(symbol):
                    continue
            elif symbol.kind is not SymbolKind.VAR:
                continue
            tipo = symbol.type
            if genericos and type_service.mentions_param(tipo, genericos):
                # un 'T' (o un 'Caja<T>'): si hay algo que destruir lo dice
                # la instancia, no la declaracion. Se destruye POR SU TIPO.
                # Un 'T ptr' es un prestamo, como cualquier puntero.
                if not _es_puntero(tipo):
                    drops.append(ast.Drop(path=[symbol.name], by_type=True))
                continue
            if symbol.kind is SymbolKind.VAR and type_service.es_desconocido(tipo):
                # 'catch (e)' sin tipo: lo atrapado es suyo, y de que tipo es
                # se sabe recien al ejecutar
                drops.append(ast.Drop(path=[symbol.name], by_type=True))
                continue
            if not type_service.owns_resources(tipo, ctx.scope, ctx.table):
                continue
            self._aplanar_drops(tipo, [symbol.name], drops)
        drops.reverse()
        block.drops = drops

    def _firma_canonica(self, fn: ast.FunctionDecl) -> None:
        """Guarda en el Symbol la firma YA enlazada (canonica).

        'collect' registra la funcion con las anotaciones tal como se
        escribieron, porque en la pasada 1 todavia no se pueden resolver todas.
        Las variables y los campos se canonicalizan al enlazarse, y la firma
        no: 'fn hace() -> vec.Vector<int>' devolvia 'vec.Vector<int>', y
        guardarlo en un 'var vec.Vector<int>' (canonico: 'vector.Vector<int>')
        era AST006 entre dos nombres del MISMO tipo. Pasaba con cualquier
        funcion cuya firma usara un generico de una libreria — el
        contenedor mas usado de la stdlib.

        Se hace aqui, con el scope de QUIEN DECLARA la funcion: canonizar en
        cada llamada usaria los alias del llamador, que pueden no existir o
        significar otra cosa. Los parametros de tipo ('T') quedan tal cual.
        """
        firma = self.ctx.fn_symbols.get(id(fn))
        if firma is None:
            return
        firma.param_types = tuple(p.restype for p in fn.params
                                  if p.restype is not None)
        if fn.return_restype is not None:
            firma.type = fn.return_restype

    def _parametro_propio(self, symbol: Symbol) -> bool:
        """¿Este parametro lo posee (y lo destruye) la funcion que lo declara?

        Solo cuando TODA llamada esta obligada a transferirlo con ``move``,
        porque solo entonces el llamador ya no es dueño:

        - un ``hook`` NO: lo invoca el compilador (``cast<T>(x)``,
          ``v[i] = x``) pasando el valor por nombre, y ahi nadie puede
          escribir ``move``. Su parametro sigue siendo una copia prestada.
        - el RECEPTOR de un metodo (primer parametro de un ``dunder``) NO:
          ``x.m()`` lo pasa implicitamente.

        Un parametro ``T`` SI: en la llamada ``T`` ya es un tipo concreto y
        SEM032 exige ``move`` si tiene destructor, asi que la funcion es su
        dueña. Su drop es POR TIPO (``_anotar_drops``).
        """
        if self._lambdas and symbol.scope_id == self._lambdas[-1].sid:
            # un parametro de la LAMBDA: quien la llama le cede lo que pasa
            # por valor con 'move' (SEM032), como a cualquier 'fn(R) -> X'
            return True
        fn = self.ctx.current_fn
        if fn is None or fn.specifier == "hook":
            return False
        if fn.specifier == "dunder" and fn.params and fn.params[0].name == symbol.name:
            return False
        return True

    def _genericos(self) -> frozenset:
        """Los parametros de tipo que ve el cuerpo en curso: los suyos, los de
        su ``@impl`` y los del RECEPTOR generico (``hook fn __index__(Vector<T>
        ptr self, ...)`` nombra ``T`` sin declararlo: es el de ``Vector``)."""
        return self._generics_of(self.ctx.current_fn)

    def _generics_of(self, fn) -> frozenset:
        """:meth:`_genericos` de una funcion cualquiera (no solo la que se
        esta resolviendo): la firma se enlaza antes que el cuerpo."""
        if fn is None:
            return frozenset()
        nombres = set(fn.type_params or ()) | \
            set(getattr(fn, "impl_type_params", None) or ())
        receptor = _core(fn.params[0].restype) if fn.params else None
        if receptor is not None and receptor.kind is TypeKind.NOMINAL:
            for arg in receptor.args:
                if arg.kind is TypeKind.NOMINAL and not arg.args and arg.name:
                    # un parametro de tipo se declara como un tipo OPACO del
                    # archivo (collect._declarar_parametros)
                    simbolo = self.ctx.scope.resolve_type(arg.name)
                    if simbolo is not None and simbolo.kind is SymbolKind.TYPE:
                        nombres.add(arg.name)
        return frozenset(nombres)

    def _aplanar_drops(self, t: Optional[Type], ruta: List[str],
                       salida: List[ast.Drop]) -> None:
        """Traduce "este valor posee recursos" a las destrucciones CONCRETAS.

        Dos casos, y la regla que los separa es de quien es la
        responsabilidad:

         - el tipo declara ``__free__``  -> ESE destructor se hace cargo de
           todo lo suyo, incluidos sus campos. Se emite una sola destruccion y
           no se baja mas.
         - no lo declara -> posee solo por sus campos (regla 3 de
           ``owns_resources``), asi que se baja a ellos, en orden INVERSO al de
           declaracion. La recursion termina porque ``owns_resources`` solo es
           cierto si en algun punto del arbol POR VALOR hay un ``__free__``, y
           los punteros —por donde se cierran los tipos recursivos— no poseen.

        Aplanar aqui y no en ejecucion es lo mismo que se hizo con la lista de
        drops: que campos poseen recursos es una pregunta sobre el TIPO.
        """
        hook = self._destructor_de(t)
        if hook is not None:
            salida.append(ast.Drop(path=list(ruta), hook=hook))
            return
        simbolo = self._nominal_symbol(t)
        # Lo que no se puede aplanar aqui se destruye POR SU TIPO: un bloque
        # de un campo (sus celdas no tienen ruta), un enum (el payload depende
        # de la variante que haya al ejecutar) y un 'T' de un generico.
        genericos = self._genericos()
        if t is not None and (
                t.kind is TypeKind.POINTER
                or (simbolo is not None and simbolo.kind is SymbolKind.ENUM)
                or (genericos and type_service.mentions_param(t, genericos))):
            salida.append(ast.Drop(path=list(ruta), by_type=True))
            return
        if simbolo is None or not simbolo.members:
            return
        # El campo de un generico se declara como 'T'; el tipo CONCRETO de
        # este valor sale de sustituir sus argumentos. Sin eso, 'Caja<R>' no
        # bajaba a su campo y el destructor de 'R' no se ejecutaba nunca —
        # una fuga silenciosa, que es justo lo que el modelo promete evitar.
        mapa = type_service.bindings(simbolo, self._nominal_de(t))
        # NO se invierte aqui: '_anotar_drops' invierte la lista COMPLETA al
        # final, asi que emitir en orden de declaracion es lo que produce el
        # orden inverso de verdad. Invertir en los dos sitios se cancelaba.
        for campo in simbolo.members.values():
            concreto = type_service.substitute(campo.type, mapa)
            # un CAMPO puntero posee si guarda el bloque de algo que posee
            # (regla 4 de 'owns_resources')
            if type_service.field_owns_resources(concreto, self.ctx.scope,
                                                 self.ctx.table):
                self._aplanar_drops(concreto, ruta + [campo.name], salida)

    @staticmethod
    def _nominal_de(t: Optional[Type]) -> Optional[Type]:
        """El nominal bajo ``t``, desenvolviendo ``T?`` y ``error T``.

        Se necesita el TIPO (no su símbolo) porque los argumentos del genérico
        viven en él: ``Caja<R>`` los lleva, ``Caja`` no.
        """
        while t is not None and (t.kind is TypeKind.NULLABLE
                                 or t.kind is TypeKind.ERROR):
            t = t.inner
        return t

    def _nominal_symbol(self, t: Optional[Type]):
        """El ``Symbol`` del tipo nominal bajo ``t``, desenvolviendo ``T?`` y
        ``error T`` (envoltorios) pero nunca ``ptr`` (prestamo)."""
        while t is not None and (t.kind is TypeKind.NULLABLE
                                 or t.kind is TypeKind.ERROR):
            t = t.inner
        if t is None or t.kind is not TypeKind.NOMINAL or t.name is None:
            return None
        # por nombre CANONICO: un tipo de libreria viaja como 'caja.Caja'
        # aunque se haya importado como 'cj', y buscarlo como ruta no lo
        # encontraba — 'Caja<R>' de libreria no bajaba a su campo 'R' y el
        # destructor de 'R' no corria nunca.
        return type_service.resolve_canonical(t.name, self.ctx.scope)

    def _destructor_de(self, t: Optional[Type]):
        """El ``__free__`` declarado por el tipo nominal bajo ``t``, o ``None``."""
        return self._hook_de_tipo(t, HookKind.FREE)

    def _stmt_var_decl(self, node: ast.VarDecl) -> None:
        self._check_var_init(node)
        symbol = Symbol(name=node.name, kind=SymbolKind.VAR, ln=node.ln,
                        col=node.col, type=node.restype,
                        mutable=(node.qualifier != "const"))
        if not self.ctx.scope.define_value(symbol):
            self.ctx.error(SemanticError.DuplicateSymbolError(
                f"'{node.name}' ya está declarado en este scope",
                line=node.ln, column=node.col,
            ))
        elif self.locals is not None:
            self.locals[node.name] = symbol

    def _stmt_type_decl(self, node: ast.TypeDecl) -> None:
        """``[const] type T [= <expr>];`` — valida el INICIALIZADOR.

        El NOMBRE lo registra ``collect`` (pasada 1) contra el scope global;
        aquí solo se resuelve la expresión, igual que ``visit_top_level_stmt``
        hace con un ``VarDecl`` global.

        Sin esta entrada en el despacho el inicializador no lo visitaba nadie:
        un nombre inexistente cruzaba el frontend entero sin un solo
        diagnóstico y solo aparecía al ejecutar (``RT006``), con el
        ``restype`` de la expresión sin anotar dentro del HIR — que promete
        lo contrario a TODOS los backends, no solo al intérprete.
        """
        if self.ctx.scope is not self.ctx.table.global_scope:
            self._define_local_type(node)
        if node.value is None:
            return
        value_type = self.visit_expr(node.value)
        # 'type' es de primera clase: el inicializador tiene que PRODUCIR un
        # tipo. Con 'value_type' desconocido (None) no se reporta nada — misma
        # regla de cero falsos positivos que el resto de la pasada.
        if value_type is not None and not is_meta(value_type):
            self.ctx.error(ASTError.TypeMismatchError(
                f"el inicializador de 'type {node.name}' debe producir un "
                f"tipo, no '{value_type!r}': 'type' es un metatipo, así que "
                f"el valor tiene que salir de una expresión de tipo 'type' "
                f"(por ejemplo una llamada a una 'fn ... -> type')",
                line=node.ln, column=node.col,
            ))

    def _define_local_type(self, node: ast.TypeDecl) -> None:
        """``type T;`` dentro de una función: registra T en el scope ACTUAL.

        En el nivel superior lo hace ``collect`` (pasada 1), que solo recorre
        ``program.items``; aquí dentro no llegaba nadie y la declaración se
        descartaba EN SILENCIO —el fallo salía lejos, como un ``AST005`` en el
        primer uso—. Poder declararlo aquí es lo que hace de ``type`` un
        constructo de primera clase y no solo una entrada de librería.

        Se registra en los DOS namespaces por el mismo motivo que el global
        (ver ``collect._collect_type_decl``): ``type`` es un tipo de primera
        clase, así que el nombre vale como tipo (``const T x;``) y como valor
        (``return T;`` en una ``fn ... -> type``).

        La cache del binder se invalida porque este nombre puede SOMBREAR a un
        tipo global homónimo: lo cacheado antes de esta línea ya no vale.
        """
        mutable = node.qualifier != "const"
        symbol = Symbol(name=node.name, kind=SymbolKind.TYPE, ln=node.ln,
                        col=node.col, type=nominal(node.name), mutable=mutable)
        if not self.ctx.scope.define_type(symbol):
            self.ctx.error(SemanticError.DuplicateSymbolError(
                f"el tipo '{node.name}' ya está declarado en este scope",
                line=node.ln, column=node.col,
            ))
            return
        as_value = Symbol(name=node.name, kind=SymbolKind.TYPE, ln=node.ln,
                          col=node.col, type=META_TYPE, mutable=mutable)
        if not self.ctx.scope.define_value(as_value):
            self.ctx.error(SemanticError.DuplicateSymbolError(
                f"'{node.name}' colisiona con otro símbolo del mismo scope",
                line=node.ln, column=node.col,
            ))
            return
        self.types.invalidate()
        if self.locals is not None:
            self.locals[node.name] = as_value

    def bind_global_type(self, node: ast.VarDecl) -> None:
        """El tipo ESCRITO de una global, canonicalizado ANTES de resolver
        ningun cuerpo, y llevado a su ``Symbol``.

        El ``Symbol`` lo crea la pasada 1 con el tipo tal como se escribio
        (``exc.ValorInvalido`` con ``#import excepciones as exc``), y un
        cuerpo que la lee lo compara con tipos canonicos
        (``excepciones.ValorInvalido``): un falso AST006 (A01). Sin alias
        coincidian por casualidad. Se hace con las firmas, porque una funcion
        puede usar una global declarada mas abajo."""
        if node.inferido:
            return
        self.types.bind(node)
        self._globals_bound.add(id(node))
        symbol = self.ctx.scope.resolve_value(node.name)
        if symbol is not None and symbol.kind is SymbolKind.VAR \
                and symbol.ln == node.ln and symbol.col == node.col:
            symbol.type = node.restype

    def _check_var_init(self, node: ast.VarDecl) -> None:
        if node.inferido:
            # el guardian sin nombre de un 'with': su tipo es el de su valor
            node.restype = self.visit_expr(node.value)
            self._tiene_dueno(node.value)
            return
        # el tipo escrito se valida y canonicaliza PRIMERO: la comparacion de
        # abajo usa 'node.restype', y 'point.Point' y 'Point' son nominales
        # distintos que nunca unificarian. Una global ya lo hizo
        # ('bind_global_type'): enlazarla dos veces repetiria sus errores.
        if id(node) not in self._globals_bound:
            self.types.bind(node)
        if node.value is None:
            self._variable_sin_valor(node)
            return
        value_type = self.visit_expr(node.value)
        self._tiene_dueno(node.value)   # el binding se queda con el valor
        self._sin_copia_de_dueno(node)
        if _is_null_literal(node.value):
            if not type_service.unify_literal_null(node.restype):
                self.ctx.error(ASTError.TypeMismatchError(
                    f"'null' no es asignable a '{node.restype!r}' (no es nullable)",
                    line=node.ln, column=node.col,
                ))
        elif not self._acepta_valor(
                node.restype, node.value, value_type,
                lambda e: setattr(node, "value", e)):
            self.ctx.error(ASTError.TypeMismatchError(
                f"no se puede inicializar '{node.name}' ({node.restype!r}) "
                f"con un valor de tipo '{value_type!r}'"
                f"{self._sugerencia(node.restype, value_type)}",
                line=node.ln, column=node.col,
            ))

    #: el valor con que se sugiere empezar, por tipo primitivo: el NEUTRO de
    #: cada uno. Es solo el texto del consejo; el compilador no lo pone.
    _VALOR_DE_EJEMPLO = {
        TypeKind.INT: "0", TypeKind.FLOAT: "0.0", TypeKind.BOOL: "false",
        TypeKind.STR: '""', TypeKind.CHAR: "' '", TypeKind.BYTE: "0",
    }

    def _variable_sin_valor(self, node: ast.VarDecl) -> None:
        """``var T x;`` sin ``= valor``: SEM040, en cualquier ámbito.

        Lo comparten el ``var`` local y el global (los dos pasan por
        ``_check_var_init``). No se inventa un valor por defecto: ese valor
        nadie lo escribió, y un olvido que corre en silencio es peor que uno
        que no compila (ver el docstring de ``UninitializedVariableError``)."""
        tipo = node.restype
        escrito = format_type(tipo) if tipo is not None else "su tipo"
        if tipo is not None and tipo.kind is TypeKind.NULLABLE:
            consejo = (f"si empieza sin valor, dilo: "
                       f"'{node.qualifier or 'var'} {escrito} {node.name} = null;'")
        elif tipo is not None and tipo.kind in self._VALOR_DE_EJEMPLO:
            consejo = (f"escribe con qué empieza: '{node.qualifier or 'var'} "
                       f"{escrito} {node.name} = "
                       f"{self._VALOR_DE_EJEMPLO[tipo.kind]};'")
        else:
            consejo = (f"escribe con qué empieza ('= ...' con un valor de tipo "
                       f"'{escrito}'), o declárala '{escrito}?' y '= null' si "
                       "todavía no lo hay")
        self.ctx.error(SemanticError.UninitializedVariableError(
            f"'{node.name}' se declara sin valor: toda variable nace con un "
            f"valor de su tipo ('{escrito}'), y sin él valdría 'null'. "
            f"{consejo[0].upper()}{consejo[1:]}",
            line=node.ln, column=node.col,
        ))

    def _argumento_transferido(self, funcion: str, index: int, arg,
                               param_type: Optional[Type]) -> None:
        """Pasar por VALOR algo con destructor exige ``move`` (SEM032).

        Es la misma regla que ``var R b = a;`` (ver :meth:`_sin_copia_de_dueno`)
        aplicada a un argumento: el parametro por valor es dueño de lo que
        recibe y lo destruye al salir, asi que el llamador tiene que ceder la
        propiedad de forma VISIBLE. Pasarlo por nombre dejaria dos dueños del
        mismo recurso. Para solo leerlo, el parametro se declara ``ptr``.

        Antes esta escritura se aceptaba y significaba "el llamador sigue
        siendo dueño", mientras ``move`` significaba "nadie lo es": el recurso
        se perdia en silencio. Un literal o el retorno de una funcion no dejan
        a nadie mas con el valor y no necesitan ``move``.
        """
        if _es_puntero(param_type):
            return
        genericos = self._genericos()
        if genericos and type_service.mentions_param(param_type, genericos):
            # dentro de un generico: el parametro es el dueño (un temporal ya
            # tiene quien lo destruya) y si pasar por nombre COPIA un dueño lo
            # decide la instancia (SEM038)
            self._tiene_dueno(arg)
            if self._es_lugar(arg):
                self._anotar_copia(param_type, arg)
            return
        if not type_service.owns_resources(param_type, self.ctx.scope,
                                           self.ctx.table):
            return
        # El parámetro es DUEÑO de lo que recibe: un temporal
        # ('toma(R{...})', 'toma(fabrica())') ya tiene quien lo destruya, y
        # el llamador no debe soltarlo también al terminar la sentencia.
        self._tiene_dueno(arg)
        if not self._es_lugar(arg):
            return
        nombre = _texto_de(arg)
        self.ctx.error(SemanticError.ImplicitOwnershipCopyError(
            f"argumento {index} de '{funcion}': '{nombre}' es de tipo "
            f"'{param_type!r}', que tiene destructor, y el parametro lo recibe "
            f"por valor (se convierte en su dueño). Transfierelo con 'move' "
            f"('move {nombre}') o declara el parametro como puntero "
            f"('{param_type!r} ptr') si solo lo quieres leer",
            line=getattr(arg, "ln", 0), column=getattr(arg, "col", 0),
        ))

    def _sin_copia_de_dueno(self, node: ast.VarDecl) -> None:
        """Rechaza ``var R b = a;`` cuando ``R`` tiene dueño (SEM032).

        Un ``struct`` es un valor y ligarlo lo copia, pero copiar algo con
        obligación de destrucción no duplica el recurso: duplica al DUEÑO, y
        su destructor corre dos veces. La transferencia se escribe con
        ``move``, que es lo que la documentación del modelo usa.

        Solo se mira lo que NOMBRA a otro dueño (una variable, un campo, un
        elemento): un literal o el retorno de una función no dejan a nadie
        más con el valor, así que ahí ligar es lo correcto.

        NO se aplica al ARGUMENTO de una llamada, y no por olvido: pasar por
        nombre está decidido como "el dueño sigue siendo el llamador, que lo
        destruye una vez" (ver ``test_drop.py::test_un_valor_pasado_por_nombre
        _no_se_destruye_dos_veces``). Que la misma escritura se rechace en un
        ``var`` y se acepte en un argumento es una asimetría real del modelo;
        está anotada como pregunta de diseño, no resuelta aquí.
        """
        valor = node.value
        if not self._es_lugar(valor):
            return
        genericos = self._genericos()
        if genericos and type_service.mentions_param(node.restype, genericos) \
                and not _es_puntero(node.restype):
            self._anotar_copia(node.restype, valor)
            return
        if not type_service.owns_resources(node.restype, self.ctx.scope,
                                           self.ctx.table):
            return
        self.ctx.error(SemanticError.ImplicitOwnershipCopyError(
            f"'{node.name}' recibiría un valor de '{node.restype!r}', que "
            "tiene destructor: ligarlo dejaría DOS dueños del mismo recurso y "
            f"lo destruiría dos veces. Transfiérelo con 'move' "
            f"('var {node.restype!r} {node.name} = move ...;') o toma un "
            "puntero si solo quieres leerlo",
            line=node.ln, column=node.col,
        ))

    def _stmt_import_binding(self, node: ast.ImportBinding) -> None:
        # import dentro de un cuerpo: mismo mecanismo que collect, sobre el
        # scope actual (el simbolo muere con el bloque).
        collect.define_import(node.name, node.source, self.ctx,
                              mutable=(node.qualifier != "const"))

    def _stmt_if(self, node: ast.IfStmt) -> None:
        self._condicion(node.condition, "'if'")
        self._stmt_block(node.then_block)
        if node.else_branch is not None:
            if isinstance(node.else_branch, ast.IfStmt):
                self._stmt_if(node.else_branch)
            else:
                self._stmt_block(node.else_branch)

    def _stmt_while(self, node: ast.WhileStmt) -> None:
        self._condicion(node.condition, "'while'")
        self._stmt_block(node.body)

    def _condicion(self, expr, donde: str) -> None:
        """La condicion de un ``if``/``while`` tiene que ser ``bool``.

        suriaX no tiene VERACIDAD: un ``int`` no es "verdadero si no es cero"
        y una cadena no es "verdadera si no esta vacia". Aceptar ``if (1)``
        era una coercion implicita, justo lo que el lenguaje prohibe en todos
        los demas sitios ('cast<T>(x)' es la unica via de conversion), y las
        consecuencias eran visibles: el frontend lo aceptaba, el interprete lo
        ejecutaba con la veracidad de Python y el target web lo rechazaba
        porque WASM exige un i32 en la condicion. Tres respuestas para el mismo
        programa.

        Tipo desconocido: permisivo, como el resto del frontend (cero falsos
        positivos).
        """
        tipo = self.visit_expr(expr)
        if tipo is None or type_service.es_desconocido(tipo):
            return
        if tipo.kind is TypeKind.BOOL:
            return
        self.ctx.error(ASTError.TypeMismatchError(
            f"la condicion de {donde} es de tipo '{tipo!r}', y tiene que ser "
            "'bool': en suriaX un valor no es verdadero por no ser cero. "
            "Escribe la comparacion ('x != 0')",
            line=getattr(expr, "ln", 0), column=getattr(expr, "col", 0),
        ))

    def _stmt_expect(self, node: ast.ExpectStmt) -> None:
        """``expect (condicion) [bloque]``: la condicion es ``bool``, por lo
        mismo que la de un ``if`` (sin veracidad)."""
        self._condicion(node.condition, "'expect'")
        if node.body is not None:
            self._stmt_block(node.body)

    def _stmt_match(self, node: ast.MatchStmt) -> None:
        subject_type = self.visit_expr(node.subject)
        content = _optional_content(subject_type)
        saved = self._subject_read_only
        saved_content = self._optional_content
        saved_subject = self._match_subject
        self._subject_read_only = self._read_only_reason(node.subject)
        self._optional_content = content
        self._match_subject = content if content is not None else subject_type
        saved_text = self._match_subject_text
        self._match_subject_text = _texto_de(node.subject)
        try:
            for arm in node.cases:
                self._stmt_case_arm(arm)
        finally:
            self._subject_read_only = saved
            self._optional_content = saved_content
            self._match_subject = saved_subject
            self._match_subject_text = saved_text
        if content is None:
            # un sujeto 'E ptr' se desreferencia solo (un arbol con 'Expr
            # ptr'): sus ramas se comprueban como las de 'E' (A05: SEM030
            # callaba sobre el puntero)
            pointee = subject_type
            if pointee is not None and pointee.kind is TypeKind.POINTER:
                pointee = pointee.inner
            self._no_repeated_case(node, pointee)
            self._match_exhaustivo(node, pointee)
            return
        # un 'T?': las variantes de un 'E?' se comparan contra 'E'
        self._no_repeated_case(node, content)
        self._unreachable_after_binding(node)
        self._optional_match_exhaustive(node, subject_type, content)

    def _unreachable_after_binding(self, node: ast.MatchStmt) -> None:
        """SEM046: una rama DETRAS de ``case v`` sobre un ``T?``. ``case v``
        encaja con todo valor que no sea null y gana la primera rama que
        encaja, asi que lo que venga despues no se ejecuta nunca, salvo un
        ``case null``."""
        binding = None
        for arm in node.cases:
            if binding is not None and not _is_null_literal(arm.pattern):
                self.ctx.error(SemanticError.DuplicateCaseError(
                    f"esta rama no se ejecuta nunca: 'case "
                    f"{binding.pattern.name}' (linea {binding.ln}) ya encaja "
                    "con todo valor que no sea null. Pon las ramas concretas "
                    "antes, o quita esta",
                    line=arm.ln, column=arm.col,
                ))
            elif binding is None and arm.binds:
                binding = arm

    def _optional_match_exhaustive(self, node: ast.MatchStmt,
                                   subject_type: Type, content: Type) -> None:
        """SEM030 (aviso) para un ``match`` sobre un ``T?``, con la regla del
        ``match`` sobre un enum: si se SABE que un valor posible no entra en
        ninguna rama, se dice.

        Los valores posibles de un ``T?`` son ``null`` y los de ``T``. ``null``
        lo cubre ``case null``; los de ``T``, ``case v``, o —si ``T`` es un
        enum— una rama por variante. Si ``T`` no es un enum (``int?``), sus
        valores no se exigen, igual que en un ``match`` sobre un ``int``: el
        lenguaje no obliga a cubrir todos los enteros. ``null`` si, porque es
        UN valor y nombrarlo cuesta una rama (``case null { }`` si no hay nada
        que hacer).

        Solo avisa donde sabe: una rama cuyo patron podria valer null (otro
        ``T?``) o cuyo tipo no se conoce la vuelve opaca, como una rama que no
        nombra una variante en el ``match`` sobre un enum."""
        enum = self._enum_de(content)
        null_covered = values_covered = opaque = some_values = False
        variants: set = set()
        for arm in node.cases:
            pattern = arm.pattern
            if arm.binds:
                values_covered = True
                continue
            if _is_null_literal(pattern):
                null_covered = True
                continue
            name = self._variante_del_patron(pattern, enum) \
                if enum is not None else None
            if name is not None:
                variants.add(name)
                continue
            typ = getattr(pattern, "restype", None)
            while typ is not None and typ.kind is TypeKind.ERROR \
                    and typ.inner is not None:
                typ = typ.inner
            if type_service.es_desconocido(typ) \
                    or typ.kind is TypeKind.NULLABLE:
                opaque = True
            else:
                some_values = True
        if opaque:
            return
        missing = [] if null_covered else ["null"]
        if enum is not None and not values_covered and not some_values:
            missing += [v for v in enum.members if v not in variants]
        if not missing:
            return
        self.ctx.error(SemanticError.NonExhaustiveMatchError(
            f"el 'match' sobre '{subject_type!r}' no cubre "
            + ", ".join(f"'{v}'" for v in missing)
            + ": ese valor no entra en ninguna rama y el 'match' no hace "
              "nada. Anade una rama por cada uno ('case null { }' si no hay "
              "nada que hacer; 'case v { }' liga cualquier otro valor)",
            line=node.ln, column=node.col,
        ))

    def _no_repeated_case(self, node: ast.MatchStmt,
                          subject_type: Optional[Type]) -> None:
        """SEM046: dos ramas con el MISMO patron. Gana la primera que encaja
        (el ``match`` no sigue), asi que la segunda no se ejecuta nunca: o
        sobra, o el patron que se queria era otro.

        Se compara lo que se puede afirmar igual sin ejecutar: un literal
        (``case 1`` / ``case 1``), la misma variante de un enum escrita de
        cualquier forma (``ROJO`` / ``Color.ROJO``, ``Nodo.A(x)`` /
        ``Nodo.A(y)``) o el mismo nombre escrito dos veces."""
        enum = self._enum_de(subject_type)
        seen: dict = {}
        for arm in node.cases:
            if arm.binds:
                continue    # no es un valor: lo que tapa lo dice SEM046 aparte
            key = self._case_key(arm.pattern, enum)
            if key is None:
                continue
            first = seen.get(key)
            if first is None:
                seen[key] = arm
                continue
            self.ctx.error(SemanticError.DuplicateCaseError(
                f"este 'case' repite el de la linea {first.ln}: gana la primera "
                "rama que encaja, asi que esta no se ejecuta nunca. Quitala, o "
                "escribe el patron que querias",
                line=arm.ln, column=arm.col,
            ))

    def _case_key(self, pattern, enum: Optional[Symbol]):
        """Lo que identifica a un patron para compararlo con otro, o
        ``None`` si no se puede afirmar nada."""
        if enum is not None:
            variant = self._variante_del_patron(pattern, enum)
            if variant is not None:
                return ("variant", variant)
        if isinstance(pattern, ast.Call):
            return None
        literal = pattern
        sign = 1
        if isinstance(literal, ast.UnaryOp) and literal.operator == "-":
            sign, literal = -1, literal.operand
        if isinstance(literal, ast.Literal) and literal.literal_kind != "null":
            value = literal.value
            if sign == -1 and isinstance(value, (int, float)) \
                    and not isinstance(value, bool):
                value = -value
            elif sign == -1:
                return None
            return ("literal", literal.literal_kind, value)
        if isinstance(pattern, ast.Literal):
            return ("literal", "null", None)
        written = _texto_de_nombre(pattern)
        return ("name", written) if written is not None else None

    def _match_exhaustivo(self, node: ast.MatchStmt,
                          subject_type: Optional[Type]) -> None:
        """Avisa (SEM030) si un ``match`` sobre un ``enum`` deja variantes sin
        cubrir.

        Un ``match`` que no encaja con nada no hace nada, en silencio; y
        anadir una variante a un ``enum`` deja incompletos todos los ``match``
        del proyecto sin que nada lo diga.

        Solo avisa donde SABE. Si el sujeto no es un enum conocido, o si
        alguna rama es una expresion que este analisis no puede leer como una
        variante concreta, calla: el contrato de cero falsos positivos manda
        sobre las ganas de avisar. Por eso ``cubiertas`` se abandona en cuanto
        aparece una rama opaca, en vez de suponer que no cubre nada.
        """
        enum = self._enum_de(subject_type)
        if enum is None:
            return
        cubiertas: set = set()
        for arm in node.cases:
            nombre = self._variante_del_patron(arm.pattern, enum)
            if nombre is None:
                return  # rama opaca: no se puede afirmar nada del conjunto
            cubiertas.add(nombre)
        faltan = [v for v in enum.members if v not in cubiertas]
        if not faltan:
            return
        self.ctx.error(SemanticError.NonExhaustiveMatchError(
            f"el 'match' sobre '{enum.name}' no cubre "
            + ", ".join(f"'{v}'" for v in faltan)
            + f"; anade una rama por cada una o compara con '{enum.name}' "
              "fuera del match",
            line=node.ln, column=node.col,
        ))

    def _enum_de(self, t: Optional[Type]) -> Optional[Symbol]:
        """El ``Symbol`` del enum que nombra ``t``, o ``None`` si no lo es.

        El tipo llega de la tabla de simbolos, asi que NO esta canonicalizado:
        pasa por ``type_service.canonical`` antes de buscar en ninguna tabla.
        """
        if t is None or t.kind is not TypeKind.NOMINAL or not t.name:
            return None
        canonico = type_service.canonical(t, self.ctx.scope)
        # 'resolve_canonical' y no 'resolve_type': un enum de libreria
        # importado con otro alias ('geo.figura as fig') viaja como
        # 'figura.Figura', que el scope del consumidor no tiene registrado.
        # Sin encontrarlo, el aviso de 'match' no exhaustivo (SEM030) callaba.
        simbolo = type_service.resolve_canonical(canonico.name, self.ctx.scope)
        if simbolo is None or simbolo.kind is not SymbolKind.ENUM \
                or not simbolo.members:
            return None
        return simbolo

    def _variante_del_patron(self, patron, enum: Symbol) -> Optional[str]:
        """Nombre de la variante que cubre ``patron``, o ``None`` si el
        patron no es una variante de ``enum`` que se pueda identificar.

        Cubre las tres formas en que se nombra una: cualificada
        (``Color.ROJO``), pelada (``ROJO``) y con desestructuracion
        (``Nodo.Literal(n)``).
        """
        if isinstance(patron, ast.Call):
            patron = patron.callee
        # 'Figura.Nada' o, si el enum viene de una libreria, 'fig.Figura.Nada'
        # (antes esta segunda forma era una rama "opaca" y el match sobre
        # CUALQUIER enum de libreria quedaba sin comprobar: SEM030 callaba).
        if isinstance(patron, ast.MemberAccess):
            if self._enum_por_ruta(patron.obj) is enum \
                    and patron.member in enum.members:
                return patron.member
            return None
        if isinstance(patron, ast.Identifier) and patron.name in enum.members:
            # un nombre pelado puede ser la variante... o una variable que la
            # tapa. Si el scope lo resuelve a otra cosa, no se sabe que cubre.
            simbolo = self.ctx.scope.resolve_value(patron.name)
            if simbolo is not None and simbolo.kind is SymbolKind.ENUM_ITEM:
                return patron.name
        return None

    def _stmt_case_arm(self, node: ast.CaseArm) -> None:
        """``case <patron> ...``.

        Un patron es una EXPRESION corriente —``case 0``, ``case Color.ROJO``—
        salvo uno: ``case Nodo.Literal(n)`` DESESTRUCTURA una variante y liga
        ``n`` al payload. Sintacticamente es la misma llamada que construye la
        variante, asi que la gramatica no cambia; lo que cambia es que aqui
        sus argumentos son nombres que se DECLARAN, no valores que se leen.
        """
        if self._optional_content is not None \
                and self._binds_content(node.pattern):
            # 'case v' sobre un 'T?': 'v' es el contenido, de tipo 'T', y
            # vive solo en la rama. Es la misma ligadura que el payload de
            # 'case E.A(x)': PRESTADO (cederlo es SEM036) y modificable solo
            # si el sujeto lo es.
            node.binds = True
            self.ctx.push_scope(ScopeKind.BLOCK, f"case @{node.ln}")
            self._bind_pattern_name(node.pattern, self._optional_content)
            self._no_shadowed_pattern_names(node.body)
            self.visit_stmt(node.body)
            self._pop_scope()
            return
        variante = (self._variante_nombrada(node.pattern.callee)
                    if isinstance(node.pattern, ast.Call) else None)
        if variante is None:
            self._same_instance(self.visit_expr(node.pattern), node.pattern)
            self.visit_stmt(node.body)
            return
        self._same_instance(variante.type, node.pattern)
        self.ctx.push_scope(ScopeKind.BLOCK, f"case @{node.ln}")
        self._ligar_payload(node.pattern, variante)
        self._no_shadowed_pattern_names(node.body)
        self.visit_stmt(node.body)
        self._pop_scope()

    def _no_shadowed_pattern_names(self, body) -> None:
        """SEM002: la rama declara, en su nivel, un nombre que liga su patron
        (``case v { var str v = ...; }``, ``case F.C(r) { var str r ...}``).

        Lo que liga un patron vive en el ambito del ``case`` y el cuerpo es
        un bloque anidado, asi que se podia TAPAR sin diagnostico (H05),
        mientras que un parametro, lo que atrapa un ``catch`` y el parametro
        de una lambda dan SEM002: los cuatro ligan un nombre para el cuerpo
        que los sigue. No se fusionan los ambitos: lo que liga el patron es
        PRESTADO y no debe entrar en las destrucciones del bloque. Como en
        el ``catch``, un bloque anidado DENTRO de la rama si puede tapar."""
        if not isinstance(body, ast.Block):
            return
        bound = self.ctx.scope.values
        for stmt in body.statements:
            if isinstance(stmt, ast.VarDecl) and stmt.name in bound:
                self.ctx.error(SemanticError.DuplicateSymbolError(
                    f"'{stmt.name}' ya está declarado en este scope: lo liga "
                    "el patron de este 'case'. Usa otro nombre",
                    line=stmt.ln, column=stmt.col,
                ))

    def _ligar_payload(self, patron: ast.Call, variante: Symbol) -> None:
        """Declara los nombres de ``case Nodo.Literal(n)`` con el tipo de su
        payload. Cada uno vive SOLO en el cuerpo de esa rama."""
        esperados = variante.param_types or ()
        if len(patron.args) != len(esperados):
            self.ctx.error(SemanticError.CallArityError(
                f"la variante '{variante.name}' lleva {len(esperados)} "
                f"valor(es) y el patron liga {len(patron.args)}",
                line=patron.ln, column=patron.col,
            ))
            return
        for arg, tipo in zip(patron.args, esperados):
            if not isinstance(arg, ast.Identifier):
                self.ctx.error(SemanticError.UndefinedSymbolError(
                    "un patron de variante liga NOMBRES, no expresiones: "
                    f"escribe 'case {variante.name}(x)' y compara dentro",
                    line=getattr(arg, "ln", patron.ln),
                    column=getattr(arg, "col", patron.col),
                ))
                continue
            if not self._bind_pattern_name(arg, tipo):
                # 'case Par(x, x)': el segundo 'x' tapaba al primero en
                # silencio (se veia el ultimo valor). Es un error de C, de
                # Rust y de Python ('multiple assignments to name')
                self.ctx.error(SemanticError.DuplicateSymbolError(
                    f"el patron liga '{arg.name}' dos veces: cada nombre de un "
                    "patron recibe un valor distinto de la variante. Usa otro "
                    "nombre (y compara dentro de la rama si querias que fueran "
                    "iguales)",
                    line=arg.ln, column=arg.col,
                ))

    def _same_instance(self, pattern_type: Optional[Type], pattern) -> None:
        """AST006: el patron nombra una variante de OTRA instancia del enum
        generico del sujeto (``case Res<str, int>.Ok(x)`` sobre un
        ``Res<int, str>``). Sin esto ``x`` se ligaria con un tipo que no es
        el del payload. Solo se mira un enum generico: el resto de patrones
        sigue la regla de siempre."""
        subject = self._match_subject
        while subject is not None and subject.kind is TypeKind.POINTER:
            subject = subject.inner        # el 'match' desreferencia solo
        if pattern_type is None or subject is None \
                or pattern_type.kind is not TypeKind.NOMINAL \
                or subject.kind is not TypeKind.NOMINAL \
                or not (pattern_type.args or subject.args) \
                or pattern_type.name != subject.name \
                or type_service.same_type(pattern_type, subject):
            return
        self.ctx.error(ASTError.TypeMismatchError(
            f"el patron es una variante de '{pattern_type!r}' y el sujeto es "
            f"'{subject!r}': un enum generico con otros argumentos es otro "
            "tipo. Escribe los argumentos del sujeto",
            line=pattern.ln, column=pattern.col,
        ))

    def _bind_pattern_name(self, name: ast.Identifier,
                           typ: Optional[Type]) -> bool:
        """Declara en el scope de la rama un nombre que liga un patron: el
        payload de ``case E.A(x)`` o el contenido de ``case v`` sobre un
        ``T?``. Las dos ligaduras son la MISMA: lo ligado sigue siendo del
        sujeto (prestado: cederlo es SEM036), no se reasigna, y su contenido
        se modifica solo si el sujeto se puede modificar. ``False`` si el
        nombre ya estaba en ese scope."""
        simbolo = Symbol(name=name.name, kind=SymbolKind.VAR, ln=name.ln,
                         col=name.col, type=typ, mutable=False)
        self._del_patron.add(id(simbolo))
        self._pattern_subjects[id(simbolo)] = self._match_subject_text
        if self._subject_read_only is None:
            self._writable_bindings.add(id(simbolo))
        else:
            self._pattern_read_only[id(simbolo)] = self._subject_read_only
        if not self.ctx.scope.define_value(simbolo):
            return False
        if self.locals is not None:
            self.locals[name.name] = simbolo
        name.restype = typ
        return True

    def _binds_content(self, pattern) -> bool:
        """¿``case <pattern>`` sobre un ``T?`` LIGA el contenido?

        Liga un nombre suelto que no existe. Uno que existe es ambiguo —en
        un ``match`` sobre un ``int`` ``case limite`` COMPARA con la variable
        ``limite``, y aqui LIGARIA uno nuevo que la tapa—, asi que se rechaza
        (SEM002) en vez de elegir en silencio una de las dos lecturas, y se
        liga igual para no encadenar errores en el cuerpo. Una variante de un
        enum escrita sin su tipo (``ROJO``) no entra: es su patron."""
        if not isinstance(pattern, ast.Identifier):
            return False
        existing = self.ctx.scope.resolve_value(pattern.name)
        if existing is None:
            return True
        if existing.kind is SymbolKind.ENUM_ITEM:
            return False
        self.ctx.error(SemanticError.DuplicateSymbolError(
            f"en un 'match' sobre un '{self._optional_content!r}?', 'case "
            f"{pattern.name}' liga un nombre NUEVO al contenido, y "
            f"'{pattern.name}' ya existe (linea {existing.ln}): no se sabe si "
            "querias ligar o comparar con el. Para ligar, usa otro nombre; "
            f"para comparar, escribe un 'if' con '== {pattern.name}' antes "
            "del match",
            line=pattern.ln, column=pattern.col,
        ))
        return True

    def _enum_por_ruta(self, obj) -> Optional[Symbol]:
        """El ``enum`` que nombra ``obj``: ``Figura`` (local) o ``fig.Figura``
        (de una libreria, por la ruta de su import). ``None`` si no es uno.

        Las variantes se nombraban solo con un identificador delante, asi
        que con un enum de libreria nada funcionaba por su ruta: construir o
        desestructurar ``fig.Figura.Circulo(r)`` no ligaba ``r`` (SEM001) y el
        ``match`` no se comprobaba.
        """
        if isinstance(obj, ast.Identifier):
            simbolo = self.ctx.scope.resolve_type(obj.name)
        elif isinstance(obj, ast.MemberAccess):
            simbolo = type_service.lookup_type_path(
                _texto_de(obj), self.ctx.scope).symbol
        else:
            return None
        if simbolo is None or simbolo.kind is not SymbolKind.ENUM:
            return None
        return simbolo

    def _variante_nombrada(self, callee) -> Optional[Symbol]:
        """El ``Symbol`` de la variante que nombra ``callee``, si lo es.

        Cubre las dos formas de nombrarla: cualificada (``Nodo.Literal``) y
        pelada (``Literal``), que es como viven tambien en el namespace de
        valores. Solo devuelve algo para variantes CON payload: una variante
        unidad es un entero y no se invoca.
        """
        simbolo = None
        base = None
        if isinstance(callee, ast.MemberAccess):
            base = self._enum_por_ruta(callee.obj)
            if base is not None and base.members:
                simbolo = base.members.get(callee.member)
        elif isinstance(callee, ast.Identifier):
            simbolo = self.ctx.scope.resolve_value(callee.name)
        if simbolo is not None and simbolo.kind is SymbolKind.ENUM_ITEM \
                and simbolo.param_types:
            return self._variant_instance(simbolo, base, callee)
        return None

    def _variant_instance(self, variant: Symbol, enum: Optional[Symbol],
                          callee) -> Symbol:
        """La variante ``variant`` VISTA desde la instancia que escribe
        ``callee``: ``Res<int, str>.Ok`` construye un ``Res<int, str>`` con un
        payload ``int``. Para un enum que no es generico es la variante tal
        cual. Si faltan los argumentos (o la variante se escribe pelada,
        ``Ok(5)``), SEM027 y una variante de payload desconocido, para no
        encadenar errores en los argumentos."""
        if enum is None:
            enum = self._enum_of_item(variant)
            if enum is None or not enum.type_params:
                return variant
            self.ctx.error(SemanticError.TypeArityError(
                f"'{variant.name}' es una variante del enum GENERICO "
                f"'{enum.name}<{', '.join(enum.type_params)}>': escribela con "
                f"su enum y sus tipos, '{enum.name}<...>.{variant.name}'",
                line=callee.ln, column=callee.col,
            ))
            return dataclasses.replace(
                variant, type=None,
                param_types=tuple(None for _ in variant.param_types))
        if not enum.type_params and not getattr(callee.obj, "type_args", None):
            return variant
        instance, mapa = self._enum_instance(enum, callee.obj, variant.name)
        if instance is None:
            return dataclasses.replace(
                variant, type=None,
                param_types=tuple(None for _ in variant.param_types))
        return dataclasses.replace(
            variant, type=instance,
            param_types=tuple(type_service.substitute(t, mapa)
                              for t in variant.param_types))

    def _enum_instance(self, enum: Symbol, written,
                       member: str) -> Tuple[Optional[Type], dict]:
        """El tipo que nombra ``written`` (``Res<int, str>``) y su mapa
        ``parametro -> argumento``. Un enum generico exige sus argumentos
        escritos (SEM027 si faltan o sobran: sin ellos no se sabe de que
        ``Res`` se trata, y no se deducen). ``(None, {})`` tras un error."""
        written_args = getattr(written, "type_args", None) or []
        if enum.type_params and not written_args:
            self.ctx.error(SemanticError.TypeArityError(
                f"'{enum.name}' es un enum GENERICO "
                f"(<{', '.join(enum.type_params)}>): sus variantes se escriben "
                f"con los tipos, '{_texto_de(written)}<...>.{member}'",
                line=written.ln, column=written.col,
            ))
            return None, {}
        args = self.types.bind_call(written, enum)
        if not enum.type_params or len(args) != len(enum.type_params):
            return None, {}      # SEM027 ya dicho por 'bind_call'
        instance = Type(TypeKind.NOMINAL, name=enum.type.name, args=tuple(args))
        return instance, dict(zip(enum.type_params, args))

    def _enum_of_item(self, item: Symbol) -> Optional[Symbol]:
        """El ``enum`` al que pertenece la variante ``item``."""
        if item.type is None or not item.type.name:
            return None
        enum = type_service.resolve_canonical(item.type.name, self.ctx.scope)
        if enum is None or enum.kind is not SymbolKind.ENUM:
            return None
        return enum

    def _construir_variante(self, node: ast.Call,
                            variante: Symbol) -> Optional[Type]:
        """``Nodo.Literal(5)``: verifica la llamada al CONSTRUCTOR y devuelve
        el tipo del enum. La verificacion es la de cualquier llamada — una
        variante con payload tiene exactamente la forma de una funcion."""
        arg_types = [self.visit_expr(arg) for arg in node.args]
        self._check_call(variante, node, arg_types)
        for arg in node.args:
            self._tiene_dueno(arg)  # el payload pasa a ser del valor construido
        return variante.type


    def _stmt_return(self, node: ast.ReturnStmt) -> None:
        # dentro de una lambda, 'return' devuelve DE LA LAMBDA (su retorno
        # escrito), no de la funcion que la contiene
        fn = self._lambdas[-1].node if self._lambdas else self.ctx.current_fn
        expected = fn.return_restype if fn is not None else None
        if node.value is None:
            if expected is not None and expected != _VOID:
                self.ctx.error(ASTError.InvalidReturnTypeError(
                    f"'return;' sin valor en una función que devuelve '{expected!r}'",
                    line=node.ln, column=node.col,
                ))
            return
        value_type = self.visit_expr(node.value)
        self._tiene_dueno(node.value)   # el valor pasa al llamador
        # ...y si POSEE recursos, quien lo tenia deja de ser su dueno: sin
        # esto el drop del bloque destruiria lo que el llamador acaba de
        # recibir. Solo cuando posee: devolver un 'int' no transfiere nada.
        node.transfers = type_service.owns_resources(
            value_type, self.ctx.scope, self.ctx.table)
        genericos = self._genericos()
        if genericos and not _es_puntero(value_type)                 and type_service.mentions_param(value_type, genericos)                 and self._prestamo_de(node.value) is None:
            # un 'T' PROPIO se destruye por su tipo al cerrar el ambito:
            # devolverlo lo cede igual, o se destruiria lo que el llamador
            # recibe. Uno PRESTADO (lo que liga un 'case' sobre un puntero, un
            # campo por un puntero) no es de esta funcion: se devuelve una
            # COPIA (abajo, '_anotar_copia'), y cederlo vaciaba al dueno
            node.transfers = True
        self._no_cede_un_prestamo(node.value, value_type, "return")
        self._no_copia_una_global_con_dueno(node.value, value_type, "return")
        genericos = self._genericos()
        if genericos and type_service.mentions_param(value_type, genericos) \
                and not _es_puntero(value_type) \
                and self._prestamo_de(node.value) is not None:
            # devolver lo que es de otro (un campo por un puntero, un
            # elemento de un bloque) entrega una COPIA
            self._anotar_copia(value_type, node.value)
        self._no_devuelve_una_direccion_local(node.value)
        if _is_null_literal(node.value):
            if not type_service.unify_literal_null(expected):
                self.ctx.error(ASTError.InvalidReturnTypeError(
                    f"'return null;' en una función que devuelve '{expected!r}' (no nullable)",
                    line=node.ln, column=node.col,
                ))
        elif not self._acepta_valor(expected, node.value, value_type,
                                    lambda e: setattr(node, "value", e)):
            # el mismo punto que las demas posiciones de escritura: un literal
            # que cabe en un 'byte' o en un 'dt.int8' se devuelve sin 'cast'
            self.ctx.error(ASTError.InvalidReturnTypeError(
                f"se devuelve '{value_type!r}' pero la función declara '{expected!r}'",
                line=node.ln, column=node.col,
            ))

    def _no_copia_una_global_con_dueno(self, valor, tipo: Optional[Type],
                                       como: str) -> None:
        """``return g;`` (o ``return g.campo;``, o ``throw g;``) con ``g``
        GLOBAL y un tipo con destructor: SEM032.

        Devolver (o lanzar) por valor entrega una COPIA. De un local no hace
        falta —el local muere al salir, así que devolverlo lo MUEVE—, pero una
        global sigue viva y sigue siendo dueña: la copia y la global serían dos
        dueños del mismo recurso, y su destructor corría dos veces (con
        ``throw``, una al cerrar el ``catch`` y otra al terminar el programa).
        Es la misma regla que ``var R x = g;`` y el mismo código.

        Una ruta que cruza un puntero ya la rechaza ``_no_cede_un_prestamo``
        (SEM036), y un elemento (``g[i]``) también: aquí solo queda la ruta
        propia de punta a punta cuya raíz es una global."""
        if not isinstance(valor, (ast.Identifier, ast.MemberAccess)) \
                or not self._es_lugar(valor) \
                or self._prestamo_de(valor) is not None:
            return
        if not type_service.owns_resources(tipo, self.ctx.scope, self.ctx.table):
            return
        global_ = self._global_de(valor)
        if global_ is None:
            return
        ruta = _texto_de(valor)
        verbo = "devolverla" if como == "return" else "lanzarla"
        leer = (f"; para dejarla leer, devuelve un puntero "
                f"('{format_type(tipo)} ptr') con 'return &{ruta};'"
                if como == "return" else "")
        self.ctx.error(SemanticError.ImplicitOwnershipCopyError(
            f"'{como} {ruta}': '{global_}' es una variable global de tipo con "
            f"destructor ('{format_type(tipo)}'), y {verbo} por valor "
            "entregaría una COPIA: la copia y la global serían dos dueños del "
            "mismo recurso, que se destruiría dos veces. Para entregarla, "
            f"'{como} move {ruta};' (la global queda movida){leer}",
            line=valor.ln, column=valor.col,
        ))

    def _global_de(self, expr) -> Optional[str]:
        """El nombre de la variable GLOBAL en la raíz de la ruta ``expr``
        (``g`` en ``g.a.b``; ``lib.g`` si es la de una librería), o ``None``
        si la raíz es local, un parámetro o no es una variable."""
        raiz = expr
        while isinstance(raiz, ast.MemberAccess):
            base = self._import_chain_symbol(raiz.obj)
            if base is not None:
                # 'lib.g': la variable es MIEMBRO de una librería importada
                miembro = (base.members or {}).get(raiz.member)
                if miembro is not None and miembro.kind is SymbolKind.VAR:
                    return _texto_de(raiz)
                return None
            raiz = raiz.obj
        if not isinstance(raiz, ast.Identifier):
            return None
        simbolo = self.ctx.scope.resolve_value(raiz.name)
        if simbolo is None or simbolo.kind is not SymbolKind.VAR:
            return None
        if self.ctx.table.global_scope.values.get(raiz.name) is not simbolo:
            return None
        return raiz.name

    def _no_devuelve_una_direccion_local(self, valor) -> None:
        """``return &x`` (o ``return &x.campo``) con ``x`` local: SEM037.

        La base es lo que decide: un local o un parametro POR VALOR muere al
        salir. Si la base es un puntero (``&p.campo`` con ``p: T ptr``), lo
        apuntado es de otro y sigue vivo; si es una global, tambien.
        """
        if not isinstance(valor, ast.AddrOf):
            return
        base = valor.operand
        while isinstance(base, (ast.MemberAccess, ast.Index)):
            base = base.obj
        if not isinstance(base, ast.Identifier) or self.locals is None \
                or base.name not in self.locals:
            return
        simbolo = self.locals[base.name]
        if _es_puntero(simbolo.type):
            return
        self.ctx.error(SemanticError.DanglingAddressError(
            f"se devuelve la direccion de '{base.name}', que muere al salir de "
            "la funcion: el llamador recibiria un puntero a algo que ya no "
            "existe. Devuelve el valor, reservalo con 'mem' o guardalo en una "
            "arena y devuelve su indice",
            line=valor.ln, column=valor.col,
        ))

    def _stmt_move(self, node: ast.MoveStmt) -> None:
        tipo = self.visit_expr(node.target)
        if self._captured_read_only(node.target, "mover", node):
            return
        self._no_cede_un_prestamo(node.target, tipo, "move")

    def _expr_move(self, node: ast.MoveExpr) -> Optional[Type]:
        """``move x`` como EXPRESION: el tipo es el del origen.

        El valor se lleva entero, así que quien lo recibe se queda con él y el
        ámbito de origen ya no lo destruye — por eso además deja de ser un
        temporal: su dueño es el destino, no la sentencia."""
        tipo = self.visit_expr(node.operand)
        self._tiene_dueno(node.operand)
        if not self._captured_read_only(node.operand, "mover", node):
            self._no_cede_un_prestamo(node.operand, tipo, "move")
        return tipo

    def _no_cede_un_prestamo(self, expr, tipo: Optional[Type],
                             como: str) -> None:
        """SEM036: ceder (``move``, ``return``, ``throw``) algo con destructor
        a lo que se llega a través de un PUNTERO.

        Un puntero es un préstamo: lo que hay detrás es de otro, y ese otro lo
        destruirá cuando le toque. Cederlo dejaría DOS dueños —el nuevo y el
        de siempre— y el valor se destruiría dos veces (antes pasaba en
        silencio: ``fn f(Caja ptr mutable c) { var R x = move c.dentro; }``).
        """
        prestamo = self._prestamo_de(expr)
        if prestamo is None or not type_service.owns_resources(
                tipo, self.ctx.scope, self.ctx.table):
            return
        ruta = _texto_de(expr)
        captured = self._captured_root(expr)
        if captured is not None:
            self.ctx.error(SemanticError.MoveOutOfBorrowError(
                f"'{como} {ruta}': '{captured[0]}' lo captura la lambda de la "
                f"linea {captured[1].node.ln}, que solo lo tiene PRESTADO (para "
                "leerlo). Cederlo lo destruiria dos veces: aqui y cuando lo "
                "destruya su dueño. Devuelve algo que no tenga destructor (un "
                "campo, una cuenta) o un puntero ('&...')",
                line=expr.ln, column=expr.col,
            ))
            return
        simbolo = self.ctx.scope.resolve_value(prestamo)
        if simbolo is not None and id(simbolo) in self._del_patron:
            # A04: no es un puntero; lo liga un patron y es parte del sujeto
            sujeto = self._pattern_subjects.get(id(simbolo)) or "el sujeto"
            self.ctx.error(SemanticError.MoveOutOfBorrowError(
                f"'{como} {ruta}': '{prestamo}' lo liga el patron de un "
                f"'case': es parte del sujeto del 'match' ('{sujeto}') y aqui "
                "solo esta PRESTADO. Cederlo lo destruiria dos veces: aqui y "
                f"cuando se destruya '{sujeto}'. Para leerlo, usalo sin "
                f"cederlo; para quitarselo, que lo ceda el dueño de '{sujeto}'",
                line=expr.ln, column=expr.col,
            ))
            return
        self.ctx.error(SemanticError.MoveOutOfBorrowError(
            f"'{como} {ruta}': '{ruta}' es de otro, se llega a él a través "
            f"del puntero '{prestamo}' (un préstamo). Cederlo lo destruiría "
            f"dos veces: aquí y cuando lo destruya su dueño. Para leerlo, "
            f"usa el puntero (&{ruta}); para quitárselo, que lo ceda su dueño",
            line=expr.ln, column=expr.col,
        ))

    def _prestamo_de(self, expr) -> Optional[str]:
        """El tramo PUNTERO de la ruta ``expr`` (``c`` en ``c.dentro`` con
        ``c: Caja ptr``), o ``None`` si la ruta es propia de punta a punta.

        Un ELEMENTO (``b[i]``) siempre es de otro: de su bloque, que lo
        destruye al soltarse. Sacarlo es ``mem.take``. Y lo que liga un
        ``case Nodo.A(x)`` es el payload MISMO: lo destruye el enum."""
        if isinstance(expr, ast.Index):
            return _texto_de(expr.obj)
        if isinstance(expr, ast.Identifier):
            if self._es_del_patron(expr.name) \
                    or self._captured_root(expr) is not None:
                return expr.name
            return None
        if not isinstance(expr, ast.MemberAccess):
            return None
        tramo = expr.obj
        while isinstance(tramo, ast.MemberAccess):
            if _es_puntero(getattr(tramo, "restype", None)):
                return _texto_de(tramo)
            tramo = tramo.obj
        if isinstance(tramo, ast.Identifier):
            simbolo = self.ctx.scope.resolve_value(tramo.name)
            if simbolo is not None and simbolo.kind in (
                    SymbolKind.VAR, SymbolKind.PARAM) \
                    and (_es_puntero(simbolo.type) or id(simbolo) in self._del_patron
                         or self._capture_of(simbolo, tramo.name,
                                             record=False) is not None):
                return tramo.name
        return None

    def _es_lugar(self, expr) -> bool:
        """¿``expr`` NOMBRA un valor que ya tiene dueño (una variable, un
        campo, un elemento)? Pasarlo, ligarlo o asignarlo lo COPIA.

        Una variante sin payload (``E.Fin``, ``Fin``) se escribe igual que un
        campo o una variable, pero es una CONSTANTE: cada vez es un valor
        nuevo, y no hay un segundo dueño del que hablar."""
        if not isinstance(expr, (ast.Identifier, ast.MemberAccess, ast.Index)):
            return False
        if isinstance(expr, ast.Identifier):
            simbolo = self.ctx.scope.resolve_value(expr.name)
            return simbolo is None or simbolo.kind is not SymbolKind.ENUM_ITEM
        if isinstance(expr, ast.MemberAccess):
            enum = self._enum_por_ruta(expr.obj)
            if enum is not None and enum.members and expr.member in enum.members:
                return False
        return True

    def _es_del_patron(self, nombre: str) -> bool:
        """¿``nombre`` es lo que ligo un ``case Nodo.A(x)``?"""
        simbolo = self.ctx.scope.resolve_value(nombre)
        return simbolo is not None and id(simbolo) in self._del_patron

    def _stmt_free(self, node: ast.FreeStmt) -> None:
        target_type = self.visit_expr(node.target)
        if self._captured_read_only(node.target, "liberar", node):
            return
        # 'free' opera sobre MEMORIA REFERENCIADA: exige un puntero. Con
        # tipo desconocido se deja pasar (permisivo, el MIR verifica).
        unwrapped = target_type
        while unwrapped is not None and unwrapped.kind is TypeKind.NULLABLE:
            unwrapped = unwrapped.inner
        if unwrapped is not None and unwrapped.kind is not TypeKind.POINTER:
            # La salida es '&': 'free' libera lo que hay DETRAS de un
            # puntero, y a un lvalue se le puede tomar la direccion. Sin
            # decirlo, el caso mas comun —el '__free__' de un contenedor
            # soltando su propio campo— parecia imposible y el campo se
            # quedaba sin liberar, en silencio.
            escrito = _texto_de_nombre(node.target)
            como = f"'free &{escrito};'" if escrito else "'free &<lvalue>;'"
            self.ctx.error(SemanticError.InvalidFreeTargetError(
                f"'free' sobre un valor de tipo '{target_type!r}' "
                f"(se requiere 'T ptr'): toma su direccion, {como}",
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
        expanded = self._variadic_print(node)
        if expanded is not None:
            self._stmt_block(expanded)
            self._print_expansions[id(node)] = expanded
            return
        typ = self.visit_expr(node.expr)
        self._no_effect_statement(node, typ)

    def _variadic_print(self, node: ast.ExprStmt) -> Optional[ast.Block]:
        """``print(a, b, c);`` -> ``{ print(a); print(" "); print(b); ... }``.

        ``print`` es VARIADICO (decision del mantenedor, H02): escribe cada
        argumento separado por UN espacio, sin salto de linea al final, igual
        que el ``print`` de un argumento. Se DESCOMPONE aqui en ``print`` de
        un argumento, y cada uno se comprueba como siempre (``Print``: un
        primitivo, un tipo con ``__print__`` o un ``T: Print``). Asi el HIR
        no cambia: la VM y el web reciben las mismas llamadas de siempre.

        Consecuencia de descomponer (decision de esta sesion, documentada):
        los argumentos se evaluan y escriben EN ORDEN, uno tras otro; si el
        segundo lanza, el primero ya se escribio.

        Solo la llamada a la NATIVA: si el programa declara su propia
        ``print`` (una funcion o un valor), esa manda y su aridad la
        comprueba la llamada normal. ``None`` si no aplica."""
        call = node.expr
        if not isinstance(call, ast.Call) or len(call.args) < 2 \
                or not isinstance(call.callee, ast.Identifier) \
                or call.callee.name != "print" or call.type_args \
                or self.ctx.scope.resolve_value("print") is not None:
            return None
        statements: list = []
        for index, arg in enumerate(call.args):
            ln = getattr(arg, "ln", call.ln)
            col = getattr(arg, "col", call.col)
            if index > 0:
                statements.append(_print_statement(
                    ast.Literal(ln=ln, col=col, value=" ", literal_kind="str",
                                restype=PRIMITIVE_TYPES["str"]),
                    ln, col))
            statements.append(_print_statement(arg, ln, col))
        return ast.Block(ln=node.ln, col=node.col, statements=statements,
                         azucar="'print(a, b, ...)': un 'print' por argumento, "
                                "separados por un espacio")

    #: comparaciones: como sentencia solo calculan un 'bool' y lo tiran
    _COMPARISONS = frozenset({"==", "!=", "<", "<=", ">", ">="})

    def _no_effect_statement(self, node: ast.ExprStmt,
                             typ: Optional[Type]) -> None:
        """SEM047: una sentencia que solo calcula un valor y lo tira.

        ``f;`` nombra la funcion sin llamarla; ``a == b;`` compara y descarta
        el ``bool`` (casi siempre era ``a = b;``). Compilaban y no hacian
        nada. Tambien un nombre, un campo o un literal sueltos (``x;``,
        ``p.n;``, ``5;``), que no hacen nada por la misma razon. Lo que puede
        hacer algo no entra: una llamada, una asignacion, un indexado (puede
        lanzar), la aritmetica (``a / b`` puede lanzar) y ``and``/``or`` (el
        lado derecho puede ser una llamada)."""
        expr = node.expr
        if isinstance(expr, ast.BinaryOp) and expr.operator in self._COMPARISONS:
            hint = (" Si querias asignar, es '=' ('a = b;')"
                    if expr.operator == "==" else "")
            what = (f"compara ('{expr.operator}') y tira el resultado: no hace "
                    f"nada.{hint}")
        elif isinstance(expr, (ast.Identifier, ast.MemberAccess)) \
                and _texto_de_nombre(expr) is not None:
            written = _texto_de_nombre(expr)
            if is_function(typ):
                what = (f"nombra la funcion '{written}' sin llamarla: no hace "
                        f"nada. Para llamarla, '{written}(...)'")
            else:
                what = f"solo nombra '{written}': no hace nada"
        elif isinstance(expr, ast.Literal):
            what = "es un literal suelto: no hace nada"
        else:
            return
        self.ctx.error(SemanticError.ExpressionWithoutEffectError(
            f"esta sentencia {what}",
            line=node.ln, column=node.col,
        ))

    def _stmt_throw(self, node: ast.ThrowStmt) -> None:
        # 'throw expr;' valida su expresion; el tipo del valor lanzado es
        # libre (el catch lo recibe sin anotacion). El chequeo profundo de
        # que la funcion declare 'error T' queda para la Fase 3 de tipos.
        tipo = self.visit_expr(node.value)
        fn = self.ctx.current_fn
        if fn is not None and fn.specifier == "hook" and fn.name == "__free__":
            # un destructor nunca lanza (regla de C++): durante el
            # desenrollado habria DOS excepciones en vuelo y una se perderia.
            # Lo indirecto (llamar a algo que lanza) lo corta la ejecucion
            # con RT021.
            self.ctx.error(SemanticError.ThrowInDestructorError(
                "'throw' dentro de un __free__: un destructor nunca puede "
                "lanzar (si ya hay un throw subiendo, habria dos a la vez). "
                "Si liberar puede fallar, registra el fallo y termina el "
                "__free__ normalmente",
                line=node.ln, column=node.col,
            ))
        # 'throw r;' CEDE 'r' sin escribir 'move', igual que 'return r;': la
        # variable no puede volver a usarse despues, asi que el 'move' no le
        # diria nada nuevo al lector (decision del mantenedor: simplicidad).
        # El compilador lo inserta y el HIR lo muestra ('throw move r'), asi
        # que un 'throw' no es magia: es un 'move' que se ve en --emit-stage.
        # Sin esto 'r' se destruia DOS veces: al salir de su ambito y al
        # cerrar el 'catch'.
        self._no_cede_un_prestamo(node.value, tipo, "throw")
        self._no_copia_una_global_con_dueno(node.value, tipo, "throw")
        if self._es_local_con_dueno(node.value, tipo):
            movido = ast.MoveExpr(ln=node.value.ln, col=node.value.col,
                                  operand=node.value,
                                  azucar="throw cede el valor: 'move' implicito")
            movido.restype = tipo
            node.value = movido
        # El valor lanzado pasa al 'catch' que lo atrape (que lo destruye al
        # cerrar su bloque): un temporal ('throw R{...}') ya tiene dueño y la
        # sentencia no debe destruirlo al terminar. Sin esto se destruia DOS
        # veces, y la primera antes de que el 'catch' lo leyera.
        self._tiene_dueno(node.value)

    def _es_local_con_dueno(self, expr, tipo: Optional[Type]) -> bool:
        """¿``expr`` es algo que un ``throw`` puede CEDER: una variable local
        (o un parametro por valor), o un campo suyo (``throw c.dentro``), con
        un tipo que tiene destructor?

        La ruta tiene que ser PROPIA de punta a punta: una global, o cualquier
        tramo a traves de un puntero (``throw p.x`` con ``p`` prestado), no se
        ceden — su dueño es otro y sigue vivo despues del ``throw``.
        """
        if not type_service.owns_resources(tipo, self.ctx.scope,
                                           self.ctx.table):
            return False
        raiz = expr
        while isinstance(raiz, ast.MemberAccess):
            raiz = raiz.obj
            if isinstance(raiz, ast.MemberAccess) and \
                    _es_puntero(getattr(raiz, "restype", None)):
                return False
        if not isinstance(raiz, ast.Identifier):
            return False
        simbolo = self.ctx.scope.resolve_value(raiz.name)
        if simbolo is None or simbolo.kind not in (SymbolKind.VAR,
                                                   SymbolKind.PARAM):
            return False
        if self.ctx.table.global_scope.values.get(raiz.name) is simbolo:
            return False
        if self._capture_of(simbolo, raiz.name, record=False) is not None:
            return False    # lo capturado es prestado: no se cede
        return raiz is expr or not _es_puntero(simbolo.type)

    def _stmt_try(self, node: ast.TryStmt) -> None:
        # 'try { ... }': scope propio del bloque protegido.
        self._stmt_block(node.try_block)
        for clausula in node.catches:
            self._stmt_catch(clausula)
        # 'finally': un bloque corriente, con su scope y sus destrucciones
        if node.finally_block is not None:
            self._stmt_block(node.finally_block)

    def _stmt_catch(self, node: ast.CatchClause) -> None:
        """``catch ([tipo] nombre) { ... }``: el binding vive SOLO en su bloque.

        Con tipo escrito, el binding vale ESE tipo y se puede usar sin
        convertirlo. Sin tipo, vale ``error`` sin envolver — que significa
        DESCONOCIDO, no un tipo concreto (ver ``type_service.es_desconocido``).
        """
        if node.restype is not None:
            self.types.bind(node)
        self.ctx.push_scope(ScopeKind.BLOCK, f"catch @{node.ln}")
        symbol = Symbol(name=node.name, kind=SymbolKind.VAR, ln=node.ln,
                        col=node.col, type=node.restype or _ERROR,
                        mutable=False)
        self._writable_bindings.add(id(symbol))
        self.ctx.scope.define_value(symbol)
        if self.locals is not None:
            self.locals[node.name] = symbol
        self._visit_statements(node.block.statements)
        self._unreachable_after_exit(node.block.statements)
        # Las destrucciones del bloque del 'catch' (su binding incluido, si
        # su tipo posee recursos): antes no se anotaban y cualquier valor con
        # destructor declarado dentro de un 'catch' no se destruia nunca.
        self._anotar_drops(node.block)
        self._pop_scope()

    # ------------------------------------------------------------------ #
    # expresiones (el visitor devuelve el tipo si es gratis conocerlo)
    # ------------------------------------------------------------------ #
    def _sin_handler(self, node, clase: str) -> None:
        """Reporta un nodo que esta pasada no sabe recorrer (defecto interno)."""
        self.ctx.error(SemanticError.MissingHandlerError(
            f"{clase} '{node.__class__.__name__}' sin handler en la resolución "
            f"de scopes: sus nombres no se resolvieron y su tipo no se anotó. "
            f"Es un fallo del compilador, no del programa — añade su entrada "
            f"en el despacho de 'scope_resolver'",
            line=getattr(node, "ln", None), column=getattr(node, "col", None),
        ))

    def visit_expr(self, expr: ast.Expression) -> Optional[Type]:
        handler = self._expr_dispatch.get(expr.__class__)
        if handler is None:
            # sin handler no hay tipo que anotar: se reporta en vez de
            # devolver None en silencio, que dejaria la expresion sin
            # 'restype' dentro del HIR (ver 'visit_stmt').
            self._sin_handler(expr, "expresión")
            return None
        restype = handler(expr)
        # anotacion en sitio (mismo patron que typed_ast): el tipo que el
        # visitor ya calculo queda en el arbol para el HIR — costo cero, es
        # un write de atributo sobre informacion que de otro modo se tira.
        expr.restype = restype
        # TEMPORALES. Una llamada o un literal de struct PRODUCEN un valor; si
        # ese valor posee recursos y nadie se queda con el, no lo destruye
        # nadie. Se marca aqui —el unico punto por el que pasan todas las
        # expresiones— y las tres posiciones que SI le dan dueno (binding,
        # asignacion y 'return') lo desmarcan despues. Marcar de mas y quitar
        # es mas seguro que enumerar donde marcar: si aparece una posicion
        # nueva, el valor se destruye de mas... y por eso el desmarcado se
        # prueba (test_temporales.py), en vez de fiarse.
        cls = expr.__class__
        if (cls is ast.Call or cls is ast.StructLiteral) and restype is not None:
            expr.temp_drop = self._destructor_de(restype)
            if expr.temp_drop is None and not _es_puntero(restype):
                # posee sin declarar '__free__' (por sus campos, su payload),
                # o es un 'T': se destruye POR SU TIPO. Antes 'Caja{ r: R{} };'
                # descartado no destruia su 'R' en ningun motor.
                genericos = self._genericos()
                expr.temp_by_type = (
                    (bool(genericos) and type_service.mentions_param(restype, genericos))
                    or type_service.owns_resources(restype, self.ctx.scope,
                                                   self.ctx.table))
        return restype

    @staticmethod
    def _tiene_dueno(expr: Optional[ast.Expression]) -> None:
        """El valor de ``expr`` pasa a manos de alguien: no es un temporal."""
        if expr is not None and getattr(expr, "temp_drop", None) is not None:
            expr.temp_drop = None
        if expr is not None and getattr(expr, "temp_by_type", False):
            expr.temp_by_type = False

    #: Rango de 'int': 64 bits CON SIGNO, como declara el sistema de tipos.
    #: No es simetrico (el minimo existe, su opuesto no), y por eso el parser
    #: pliega el '-' pegado a un literal antes de llegar aqui.
    _INT_MIN = -(1 << 63)
    _INT_MAX = (1 << 63) - 1

    def _expr_literal(self, node: ast.Literal) -> Optional[Type]:
        # Un literal entero que no cabe en 'int' no llegaba a ser un error:
        # el frontend lo aceptaba y el emisor del HIR reventaba con un
        # 'ValueError' de protobuf sin posicion ni mensaje del lenguaje. Un
        # numero escrito mas grande de lo que el tipo puede guardar es un
        # error del programa, y se reporta como tal.
        if node.literal_kind == "int" and isinstance(node.value, int) \
                and not (self._INT_MIN <= node.value <= self._INT_MAX):
            self.ctx.error(ASTError.TypeMismatchError(
                f"el literal {node.value} no cabe en 'int' "
                f"(rango [{self._INT_MIN}, {self._INT_MAX}])",
                line=node.ln, column=node.col,
            ))
        return node.restype

    def _expr_interp(self, node: ast.InterpolatedString) -> Optional[Type]:
        for part in node.parts:
            if not isinstance(part, str):
                self.visit_expr(part)
        return _STR

    def _expr_formatted(self, node: ast.FormattedValue) -> Optional[Type]:
        """``{x!r:08b}``: el formato tiene que tener sentido para el TIPO.

        Un formato que no corresponde no produce un texto raro: es un error.
        ``d x X b o`` son de enteros (``int``, ``byte``), ``f`` y la precision
        de ``float``, el ``0`` de relleno de un numero; el ancho, de todo. La
        representacion (``!r``) de algo con un puntero no se sabe escribir: lo
        apuntado puede volver a apuntar al mismo sitio y el texto no
        terminaria."""
        tipo = self.visit_expr(node.value)
        if tipo is None or type_service.es_desconocido(tipo):
            return tipo
        import re
        m = re.fullmatch(r"(0?)([1-9][0-9]*)?(\.[0-9]+)?([dxXbof]?)", node.format_spec)
        cero, _ancho, precision, clase = m.groups() if m else ("", None, None, "")
        def mal(motivo: str) -> None:
            self.ctx.error(ASTError.TypeMismatchError(
                f"'{{...:{node.format_spec}}}' sobre un '{tipo!r}': {motivo}",
                line=node.ln, column=node.col,
            ))
        base = tipo
        numerico = base.kind in (TypeKind.INT, TypeKind.BYTE, TypeKind.FLOAT)
        if clase in ("d", "x", "X", "b", "o") and base.kind not in (TypeKind.INT, TypeKind.BYTE):
            mal(f"'{clase}' es un formato de enteros ('int', 'byte')")
        elif clase == "f" and base.kind is not TypeKind.FLOAT:
            mal("'f' es un formato de 'float'")
        elif precision and clase != "f":
            mal("la precision ('.2') va con 'f', que es de 'float'")
        elif cero and not numerico:
            mal("el relleno con ceros es de numeros")
        elif node.conversion == "r" and clase:
            mal("'!r' ya da un texto: con el va solo el ancho")
        if node.conversion == "r" and self._tiene_puntero(tipo, set()):
            self.ctx.error(ASTError.TypeMismatchError(
                f"'!r' de un '{tipo!r}', que lleva un puntero: lo apuntado puede "
                "volver a apuntar a si mismo y la representacion no terminaria. "
                "Escribe los campos que quieras ver",
                line=node.ln, column=node.col,
            ))
        return tipo

    def _tiene_puntero(self, t: Optional[Type], vistos: set) -> bool:
        """¿Un valor de tipo ``t`` lleva un puntero (en si, o en un campo, un
        payload o lo que envuelve)?"""
        if t is None or t in vistos:
            return False
        vistos.add(t)
        if t.kind is TypeKind.POINTER:
            return True
        if t.kind in (TypeKind.NULLABLE, TypeKind.ERROR):
            return self._tiene_puntero(t.inner, vistos)
        simbolo = self._nominal_symbol(t)
        if simbolo is None or not simbolo.members:
            return False
        mapa = type_service.bindings(simbolo, self._nominal_de(t))
        if simbolo.kind is SymbolKind.STRUCT:
            return any(self._tiene_puntero(type_service.substitute(c.type, mapa), vistos)
                       for c in simbolo.members.values())
        if simbolo.kind is SymbolKind.ENUM:
            return any(self._tiene_puntero(p, vistos)
                       for item in simbolo.members.values()
                       for p in (item.param_types or ()))
        return False

    def _expr_identifier(self, node: ast.Identifier) -> Optional[Type]:
        symbol = self.ctx.scope.resolve_value(node.name)
        if symbol is not None:
            self.ctx.usar(symbol, node.ln, node.col)
        if symbol is None:
            self.ctx.error(SemanticError.UndefinedSymbolError(
                f"'{node.name}' no está declarado",
                line=node.ln, column=node.col,
            ))
            return None
        if symbol.kind is SymbolKind.ENUM_ITEM:
            enum = self._enum_of_item(symbol)
            if enum is not None and enum.type_params:
                self.ctx.error(SemanticError.TypeArityError(
                    f"'{node.name}' es una variante del enum GENERICO "
                    f"'{enum.name}<{', '.join(enum.type_params)}>': escribela "
                    f"con su enum y sus tipos, '{enum.name}<...>.{node.name}'",
                    line=node.ln, column=node.col,
                ))
                return None
        if symbol.kind is SymbolKind.FUNCTION:
            # el NOMBRE de una funcion usado como valor es la funcion misma, y
            # su tipo es 'fn(params) -> retorno'. Antes era su tipo de RETORNO:
            # 'var int g = doble;' compilaba y 'g + 1' era un fallo interno.
            return self._function_value(symbol, node.name, node)
        if self._borrowed_function(symbol) \
                and id(node) not in self._fn_args_pending:
            self._function_parameter_escapes(node, None)
        if self._capture_of(symbol, node.name) is not None:
            # lo que la lambda captura lo LEE: un 'ptr mutable' capturado se
            # ve como 'ptr' (no se escribe a traves de el, ni se entrega a
            # quien escribiria)
            return _read_only_view(symbol.type)
        return symbol.type

    # ------------------------------------------------------------------ #
    # lambdas y funciones prestadas
    # ------------------------------------------------------------------ #
    def _expr_lambda(self, node: ast.Lambda) -> Optional[Type]:
        """``lambda (A a) -> R: e`` / ``lambda (A a) -> R { ... }``.

        Su tipo es ``fn(A) -> R``, con lo ESCRITO (sin inferencia), y se
        comprueba contra el parametro que la recibe como una funcion con
        nombre: aridad, tipos exactos, sin conversiones, y si el parametro es
        generico la lambda participa en la deduccion con sus tipos.

        El cuerpo se resuelve como el de una funcion, en un scope propio que
        cuelga del de la llamada: un nombre resuelve primero a sus parametros
        y a sus locales, y despues al ENTORNO. Lo que lee del entorno (un
        local o un parametro de la funcion que la contiene) es una CAPTURA de
        solo lectura (ver :meth:`_capture_of`). ``return`` devuelve de la
        lambda; ``break``/``continue`` no la cruzan (lo dice el parser).

        Donde puede aparecer lo decide la llamada que la contiene
        (:meth:`_call_with_hint`): fuera de un argumento es ``SEM050`` aqui
        mismo, y el cuerpo se resuelve igual para no esconder sus errores."""
        ctx = self.ctx
        if id(node) not in self._fn_args_pending:
            self._lambda_out_of_place(node, None)
        for p in node.params:
            self.types.bind(p)
        self.types.bind_return(node)
        outer_locals = self.locals
        self.locals = {}
        ctx.fn_locals[id(node)] = self.locals
        scope = ctx.push_scope(ScopeKind.FUNCTION, f"lambda @{node.ln}:{node.col}")
        frame = _LambdaFrame(node, scope.sid)
        for p in node.params:
            symbol = Symbol(name=p.name, kind=SymbolKind.PARAM, ln=p.ln,
                            col=p.col, type=p.restype, mutable=True)
            if not scope.define_value(symbol):
                ctx.error(SemanticError.DuplicateSymbolError(
                    f"parámetro duplicado '{p.name}'", line=p.ln, column=p.col,
                ))
            else:
                self.locals[p.name] = symbol
        self._lambdas.append(frame)
        try:
            # como en una funcion, el cuerpo comparte el scope de los
            # parametros: sus drops se anotan aqui
            self._visit_statements(node.body.statements)
            self._capacidad_desbordada(node.body.statements)
            self._unreachable_after_exit(node.body.statements)
            self._anotar_drops(node.body)
        finally:
            self._lambdas.pop()
            self._pop_scope()
            self.locals = outer_locals
        node.captures = frame.captures
        if any(p.restype is None for p in node.params) \
                or node.return_restype is None:
            return None
        return function_of(tuple(p.restype for p in node.params),
                           node.return_restype)

    def _capture_of(self, symbol: Optional[Symbol], name: str,
                    record: bool = True) -> Optional[_LambdaFrame]:
        """La lambda MAS EXTERNA que captura ``symbol``, o ``None`` si no es
        una captura (no hay lambda abierta, es suyo o es global).

        Una captura es un local o un parametro de una funcion (o de una
        lambda) de FUERA. Una global no: la ve igual cualquier funcion, y una
        lambda no la "lleva" consigo. Con ``record`` la anota en cada lambda
        que la cruza (una lambda dentro de otra captura a traves de ella)."""
        if not self._lambdas or symbol is None \
                or symbol.kind not in (SymbolKind.VAR, SymbolKind.PARAM) \
                or symbol.scope_id == 0:
            return None
        outermost = None
        for frame in self._lambdas:
            if symbol.scope_id < frame.sid:
                if outermost is None:
                    outermost = frame
                if record and name not in frame.captures:
                    frame.captures.append(name)
        return outermost

    def _captured_root(self, expr):
        """``(nombre, lambda)`` si la RAIZ de la ruta ``expr`` (``c`` en
        ``c.a[i].b``) es una captura, o ``None``."""
        root = expr
        while isinstance(root, (ast.MemberAccess, ast.Index)):
            root = root.obj
        if not isinstance(root, ast.Identifier):
            return None
        frame = self._capture_of(self.ctx.scope.resolve_value(root.name),
                                 root.name, record=False)
        return (root.name, frame) if frame is not None else None

    def _captured_read_only(self, expr, action: str, node) -> bool:
        """SEM003: ``action`` (mover, liberar) algo cuya raiz captura una
        lambda. ``True`` si se reporto."""
        captured = self._captured_root(expr)
        if captured is None:
            return False
        name, frame = captured
        self.ctx.error(SemanticError.ImmutableAssignmentError(
            f"{action} '{_texto_de(expr)}' no se puede: "
            f"{_captured_reason(name, frame)}",
            line=node.ln, column=node.col,
        ))
        return True

    def _borrowed_function(self, symbol: Optional[Symbol]) -> bool:
        """¿``symbol`` es un parametro de tipo ``fn(...) -> R`` (de una
        funcion o de una lambda)? Es PRESTADO: puede ser una lambda que lee
        los locales de quien llama, asi que solo se llama o se pasa a otro
        parametro de tipo funcion (ver :meth:`_function_parameter_escapes`)."""
        return symbol is not None and symbol.kind is SymbolKind.PARAM \
            and symbol.type is not None and symbol.type.kind is TypeKind.FUNCTION

    def _pending_function_arg(self, arg) -> bool:
        """¿``arg`` es una funcion PRESTADA que solo vale si el parametro
        que la recibe esta escrito como tipo funcion?"""
        if arg.__class__ is ast.Lambda:
            return True
        return arg.__class__ is ast.Identifier and self._borrowed_function(
            self.ctx.scope.resolve_value(arg.name))

    def _mark_function_args(self, node: ast.Call, declared,
                            keeps: str = "") -> None:
        """Confirma (o descarta) las funciones prestadas que ``node`` pasa,
        con los parametros DECLARADOS (antes de sustituir los genericos: un
        ``T`` instanciado con un tipo funcion sigue siendo un ``T``, que el
        cuerpo puede guardar). ``keeps`` dice por que el llamado se quedaria
        con ella aunque el parametro sea un tipo funcion: ``"host"`` (un
        prototipo, cuyo cuerpo pone el host) o ``"variant"`` (una variante de
        enum: su "parametro" es el payload que guarda)."""
        if not self._fn_args_pending:
            return
        for arg, param in zip(node.args, declared or ()):
            if id(arg) not in self._fn_args_pending:
                continue
            if not keeps and param is not None \
                    and param.kind is TypeKind.FUNCTION:
                self._fn_args_ok.add(id(arg))
            else:
                self._fn_args_bad[id(arg)] = (param, keeps)

    def _check_function_args(self, node: ast.Call, pending: list,
                             mark: int) -> None:
        """Al cerrar la llamada: cada funcion prestada que paso tiene que
        haber caido en un parametro escrito como ``fn(...) -> R``."""
        for arg in pending:
            self._fn_args_pending.pop(id(arg), None)
            if id(arg) in self._fn_args_ok:
                self._fn_args_ok.discard(id(arg))
                continue
            known = id(arg) in self._fn_args_bad
            param, keeps = self._fn_args_bad.pop(id(arg), (None, ""))
            if not known and any(
                    e.code == "SEM008" and (e.line, e.column) == (node.ln, node.col)
                    for e in self.ctx.errors[mark:]):
                continue    # aridad: el argumento no tiene parametro, ya se dijo
            if not known:
                param = _UNKNOWN_PARAM
            if arg.__class__ is ast.Lambda:
                self._lambda_out_of_place(arg, param, keeps)
            else:
                self._function_parameter_escapes(arg, param, keeps)

    def _lambda_out_of_place(self, node: ast.Lambda, param,
                             keeps: str = "") -> None:
        """SEM050: una lambda fuera del UNICO sitio donde vale."""
        if keeps == "variant":
            where = "la recibe una VARIANTE de enum, que la guarda en su valor"
        elif keeps == "host":
            where = ("el que la recibe es un PROTOTIPO: su cuerpo lo pone el "
                     "host, que podria guardarla")
        elif param is None:
            where = "aqui no es el argumento de una llamada"
        elif param is _UNKNOWN_PARAM:
            where = ("aqui no se puede comprobar que el parametro que la "
                     "recibe sea de tipo funcion (un hook, un 'print')")
        else:
            where = (f"el parametro que la recibe es de tipo "
                     f"'{format_type(param)}', no un tipo funcion escrito "
                     "('fn(...) -> R'), y podria guardarla")
        self.ctx.error(SemanticError.LambdaOutOfPlaceError(
            "una lambda solo puede ser el ARGUMENTO de una llamada cuyo "
            f"parametro esta escrito como 'fn(...) -> R', y {where}. Asi no "
            "escapa: lee los locales de quien la escribe, que siguen vivos "
            "mientras dura la llamada, y nada mas. Para guardarla, devolverla "
            "o compararla, escribe una funcion con nombre "
            "('fn nombre(...) -> R { ... }') y usa su nombre",
            line=node.ln, column=node.col,
        ))

    def _function_parameter_escapes(self, node: ast.Identifier, param,
                                    keeps: str = "") -> None:
        """SEM051: un parametro de tipo funcion usado de otra forma que
        llamarlo o pasarlo a otro parametro de tipo funcion."""
        if keeps == "variant":
            where = "aqui se guarda en una VARIANTE de enum"
        elif keeps == "host":
            where = ("aqui se pasa a un PROTOTIPO, cuyo cuerpo lo pone el host "
                     "y podria guardarlo")
        elif param is None or param is _UNKNOWN_PARAM:
            where = "aqui se usaria como un valor"
        else:
            where = (f"aqui se pasa a un parametro de tipo "
                     f"'{format_type(param)}', que podria guardarlo")
        self.ctx.error(SemanticError.FunctionParameterEscapeError(
            f"'{node.name}' es un parametro de tipo funcion: es PRESTADO "
            "(puede ser una lambda que lee los locales de quien llama) y solo "
            f"se llama ('{node.name}(...)') o se pasa a otro parametro de tipo "
            f"funcion; {where} (guardarlo, devolverlo, compararlo o escribirlo "
            "lo sacaria de la llamada). Para guardar una funcion que recibes, "
            "declara el parametro '(fn(...) -> R)?': ese no admite lambdas y "
            "si se puede guardar",
            line=node.ln, column=node.col,
        ))

    def _function_value(self, symbol: Symbol, written: str,
                       node) -> Optional[Type]:
        """El tipo ``fn(...) -> R`` de una funcion nombrada como VALOR, o
        ``None`` (con ``SEM044``) si esa funcion no puede serlo.

        Solo una funcion CON cuerpo y SIN parametros de tipo: un prototipo no
        tiene una funcion del programa que entregar (su cuerpo lo pone el host
        o un ``#extern``, distinto en cada motor), y una generica necesitaria
        que el valor llevara sus tipos, cosa que el HIR no transporta."""
        if symbol.prototype:
            self.ctx.error(SemanticError.InvalidFunctionValueError(
                f"'{written}' es un PROTOTIPO (se declara sin cuerpo: lo pone "
                "el host o un '#extern') y no se puede usar como valor. Para "
                "pasarla, envuelvela en una funcion con cuerpo que la llame",
                line=node.ln, column=node.col,
            ))
            return None
        if symbol.type_params:
            self.ctx.error(SemanticError.InvalidFunctionValueError(
                f"'{written}' es GENERICA "
                f"(<{', '.join(symbol.type_params)}>) y todavia no se puede "
                "usar como valor, ni instanciada. Envuelvela en una funcion "
                "con los tipos escritos que la llame, y usa esa",
                line=node.ln, column=node.col,
            ))
            return None
        if symbol.param_types is None:
            return symbol.type
        return function_of(symbol.param_types, symbol.type or _VOID)

    def _expr_unary(self, node: ast.UnaryOp) -> Optional[Type]:
        operand_type = self.visit_expr(node.operand)
        if node.operator == "not":
            self._operando_logico(node.operand, operand_type, "not")
            return _BOOL
        if node.operator == "~" and operand_type is not None \
                and not type_service.es_desconocido(operand_type) \
                and operand_type.kind not in (TypeKind.INT, TypeKind.BYTE):
            self.ctx.error(ASTError.TypeMismatchError(
                f"'~' no se aplica a '{operand_type!r}': los operadores de bits "
                "son de 'int' (y de 'byte')",
                line=node.ln, column=node.col,
            ))
            return None
        if node.operator == "-" and operand_type is not None \
                and operand_type.kind in _NOT_NEGATABLE:
            # negar algo que no es un numero no tenia diagnostico y el
            # interprete fallaba por dentro ('-g' con 'g' una funcion)
            self.ctx.error(ASTError.TypeMismatchError(
                f"'-' no se aplica a '{format_type(operand_type)}': se niegan "
                "numeros ('int', 'float')",
                line=node.ln, column=node.col,
            ))
            return None
        if node.operator == "-" and operand_type is not None \
                and operand_type.kind is TypeKind.BYTE:
            self.ctx.error(ASTError.TypeMismatchError(
                "'-' no se aplica a un 'byte' (no tiene signo): convierte con "
                "'cast<int>(...)'",
                line=node.ln, column=node.col,
            ))
            return None
        return operand_type  # '-', '~'

    def _operando_logico(self, expr, tipo: Optional[Type], op: str) -> None:
        """El operando de ``and``/``or``/``not`` tiene que ser ``bool``.

        Misma regla que la condicion de un ``if`` y por el mismo motivo: sin
        veracidad, ``1 and 2`` no significa nada. Tipo desconocido: permisivo.
        """
        if tipo is None or type_service.es_desconocido(tipo) \
                or tipo.kind is TypeKind.BOOL:
            return
        self.ctx.error(ASTError.TypeMismatchError(
            f"el operando de '{op}' es de tipo '{tipo!r}', y tiene que ser "
            "'bool': en suriaX un valor no es verdadero por no ser cero",
            line=getattr(expr, "ln", 0), column=getattr(expr, "col", 0),
        ))

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
            # '&f' sobre una FUNCION no es un puntero a la funcion: suriaX no
            # tiene tipos funcion. Sin esta comprobacion salia el puntero al
            # tipo de RETORNO ('fn f(int) -> int' daba 'ptr int'), que es un
            # tipo perfectamente valido y completamente equivocado — se podia
            # pasar donde se esperaba un 'ptr int' y nadie decia nada.
            if symbol is not None and symbol.kind in (
                    SymbolKind.FUNCTION, SymbolKind.HOOK, SymbolKind.DUNDER):
                # una funcion no es una VARIABLE: no tiene direccion. Su
                # nombre ya es el valor que se pasa ('aplica(doble, 3)').
                self.ctx.error(SemanticError.InvalidAddressOfError(
                    f"'&' sobre la funcion '{operand.name}': una funcion no es "
                    "una variable y no tiene direccion. Para usarla como valor "
                    f"escribe su nombre sin '&' ('{operand.name}'); su tipo "
                    "es 'fn(...) -> ...'",
                    line=node.ln, column=node.col,
                ))
                return None
            node.mut = symbol.mutable if symbol is not None else True
            if node.mut and self._capture_of(symbol, operand.name,
                                             record=False) is not None:
                node.mut = False    # '&x' de algo capturado: solo lectura
        elif cls in (ast.MemberAccess, ast.Index):
            if cls is ast.Index and self._element_borrow(node, operand,
                                                         operand_type):
                return None
            # mutable solo si el LUGAR lo es: antes era siempre 'ptr mutable',
            # y '&c.n' con 'c' un 'const' (o '&p.n' con 'p' un 'C ptr') daba
            # un puntero por el que escribir lo que no se puede escribir
            node.mut = self._read_only_reason(operand.obj) is None
        else:
            self.ctx.error(SemanticError.InvalidAddressOfError(
                f"'&' sobre una expresión temporal ({cls.__name__}): "
                "solo variables, campos o índices tienen dirección",
                line=node.ln, column=node.col,
            ))
            return None
        return pointer_of(operand_type, mut=node.mut) if operand_type is not None else None

    def _element_borrow(self, node: ast.AddrOf, operand: ast.Index,
                        element: Optional[Type]) -> bool:
        """``&b[i]``: ¿el elemento se puede PRESTAR? ``True`` si se reporto
        que no.

        Solo se presta un elemento que es un OBJETO (un struct, un enum con
        datos): ningun motor tiene punteros al interior de un bloque, y la
        direccion de un escalar era ``RT011`` al ejecutar, en los dos. Con un
        escalar CONCRETO se dice aqui (``SEM013``); con un parametro de tipo
        (``&self.datos[i]`` en ``Vector.at``) lo decide cada instancia, como
        ``SEM038``. ``s[i]`` de un ``str`` es un ``char``: tampoco."""
        obj_type = getattr(operand.obj, "restype", None)
        if obj_type is None or element is None:
            return False
        if obj_type.kind is not TypeKind.STR and _pointer_core(obj_type) is None:
            return False        # '&v[i]' con '__index__': no es una celda
        if _es_parametro_desnudo(element, self._genericos()):
            self._note_per_instance("elem_borrows", element,
                                    f"'&{_texto_de(operand)}'", node)
            return False
        if not self._is_scalar(element):
            return False
        self.ctx.error(SemanticError.InvalidAddressOfError(
            f"'&{_texto_de(operand)}' toma la direccion de un elemento de tipo "
            f"'{format_type(element)}', que es un escalar: solo se presta un "
            "elemento que es un objeto (un struct, un enum con datos), porque "
            "ningun motor tiene punteros al interior de un bloque. Lee el "
            f"valor ('{_texto_de(operand)}') o escribelo ('... = x'); para "
            "pasarlo por puntero, copialo a una variable y presta la variable",
            line=node.ln, column=node.col,
        ))
        return True

    def _is_scalar(self, t: Optional[Type]) -> bool:
        """¿Un valor de tipo ``t`` (concreto) es SEGURO un escalar en
        ejecucion: nunca un objeto (struct, enum con datos)?

        Los primitivos, un puntero, una funcion y un enum sin datos (un
        entero); un ``T?`` si ``T`` lo es (o es null, o es el escalar). Un
        tipo opaco (``const type int8;``) o desconocido NO: no se sabe."""
        while t is not None and t.kind is TypeKind.NULLABLE:
            t = t.inner
        if t is None:
            return False
        if t.kind in (TypeKind.INT, TypeKind.FLOAT, TypeKind.BOOL,
                      TypeKind.CHAR, TypeKind.BYTE, TypeKind.STR,
                      TypeKind.POINTER, TypeKind.FUNCTION):
            return True
        if t.kind is not TypeKind.NOMINAL:
            return False
        symbol = self._nominal_symbol(t)
        return symbol is not None and symbol.kind is SymbolKind.ENUM \
            and bool(symbol.members) and not any(
                m.param_types for m in symbol.members.values())

    def _note_per_instance(self, field: str, typ: Type, what: str, node,
                           fn=None) -> None:
        """Anota que el cuerpo generico en curso hace ``what`` con un valor de
        ``typ`` (un parametro de tipo); cada instancia decide si puede
        (``verificar_copias``). ``field`` es la lista del contexto. ``fn``
        es la funcion que lo anota si no es la del cuerpo en curso (una
        firma)."""
        fn = fn if fn is not None else self.ctx.current_fn
        if fn is None:
            return
        archivo = os.path.basename(self.ctx.source_path or "") or "?"
        donde = f"{archivo}:{getattr(node, 'ln', 0)}: {what}"
        getattr(self.ctx, field).setdefault(id(fn), []).append((typ, donde))

    def _expr_binary(self, node: ast.BinaryOp) -> Optional[Type]:
        if node.operator == "??":
            return self._expr_null_coalesce(node)
        left = self.visit_expr(node.left)
        right = self.visit_expr(node.right)
        left, right = self._literal_como_byte(node, left, right)
        if node.operator in ("and", "or"):
            # los operandos de un LOGICO son 'bool', por lo mismo que la
            # condicion de un 'if': no hay veracidad que convierta un 'int' en
            # verdadero. Las COMPARACIONES no entran aqui: sus operandos son
            # del tipo que se compara y el resultado es el bool.
            self._operando_logico(node.left, left, node.operator)
            self._operando_logico(node.right, right, node.operator)
            return _BOOL
        if node.operator in _BOOL_OPS:
            self._comparacion(node, left, right)
            return _BOOL
        # aritmetica: tipado fuerte, sin coerciones implicitas
        # (DESIGN_PRINCIPLES.md secc. 4) — solo si AMBOS lados se conocen. El
        # valor de un 'catch (e)' NO se conoce (tipo 'error' sin envolver),
        # asi que operar con el no se rechaza: ver 'type_service.es_desconocido'.
        if not type_service.es_desconocido(left) \
                and not type_service.es_desconocido(right) and left != right:
            self.ctx.error(ASTError.TypeMismatchError(
                f"operación '{node.operator}' entre tipos incompatibles "
                f"('{left!r}' y '{right!r}')",
                line=node.ln, column=node.col,
            ))
            return None
        if left is not None and not type_service.es_desconocido(left) and \
                not _aritmetico(left, node.operator):
            # 'P + P' pasaba la Semantica (los dos lados son del mismo tipo) y
            # reventaba al ejecutar (ICE000). Un operador aritmetico es de los
            # numeros —y '+' tambien de las cadenas—; un tipo propio no lo
            # tiene, porque no hay hooks de operadores.
            self.ctx.error(ASTError.TypeMismatchError(
                f"el operador '{node.operator}' no se aplica a '{left!r}': "
                + ("un 'byte' se compara y se enmascara ('&', '|', '^', '~'); "
                   "para calcular con el, 'cast<int>(...)'"
                   if left.kind is TypeKind.BYTE
                   else "los operadores de bits son de 'int'" if node.operator in _BITS
                   else "la aritmetica es de 'int' y 'float' ('+' tambien une "
                        "'str'); para un tipo propio, escribe una funcion"),
                line=node.ln, column=node.col,
            ))
            return None
        if node.operator in ("/", "%") and _entero_literal(node.right) == 0:
            # 'x / 0' escrito: se sabe sin ejecutar que no tiene resultado. Un
            # divisor que VALE cero al ejecutar es otra cosa -una excepcion
            # que el programa puede atrapar (EXC001)-; este no hay 'try' que
            # lo arregle, es un error del texto. (Entre float, IEEE-754 da
            # inf/nan: '0.0' no es un literal entero y no entra aqui.)
            self.ctx.error(SemanticError.LiteralDivisionByZeroError(
                f"'{node.operator} 0': división entre un cero literal, que no "
                "tiene resultado. Si el divisor puede valer cero al ejecutar, "
                "usa una variable y atrapa 'excepciones.DivisionPorCero'",
                line=node.ln, column=node.col,
            ))
        return left if left is not None else right

    def _expr_null_coalesce(self, node: ast.BinaryOp) -> Optional[Type]:
        """``x ?? d``: el contenido de ``x`` (un ``T?``) si no es null, y si
        lo es, ``d``. El resultado es un ``T``: es la forma corta de
        desenvolver un opcional cuando hay un valor por defecto (la larga es
        ``match`` con ``case null`` y ``case v``).

        Reglas, cada una con su diagnostico:

        * ``x`` tiene que ser un ``T?`` (AST006). Sobre un ``int`` el ``??``
          no desenvuelve nada y el defecto no se usaria nunca: casi siempre
          es otra variable la que se queria.
        * ``d`` es EXACTAMENTE ``T`` (AST006): sin conversiones (ni la de un
          literal a un tipo de rango, ni soltar mutabilidad) y sin ``null``,
          porque entonces el resultado no seria un ``T``.
        * ``d`` solo se evalua si ``x`` es null (cortocircuito, como ``or``).
        * PROPIEDAD: el resultado es una COPIA del contenido de ``x``. Si
          ``T`` tiene destructor, dos dueños del mismo recurso: SEM032, la
          misma regla que ``var R b = a;``. Para eso esta ``match``, cuyo
          ``case v`` PRESTA el contenido. Dentro de un generico lo decide la
          instancia (SEM038), como cualquier copia de un ``T``.
        """
        left = self.visit_expr(node.left)
        right = self.visit_expr(node.right)
        if _is_null_literal(node.left):
            self.ctx.error(ASTError.TypeMismatchError(
                "'null ?? ...' vale siempre el defecto: el lado izquierdo de "
                "'??' tiene que ser un valor 'T?' que pueda no ser null",
                line=node.left.ln, column=node.left.col,
            ))
            return right
        if type_service.es_desconocido(left):
            return right
        opcional = left
        while opcional.kind is TypeKind.ERROR and opcional.inner is not None:
            opcional = opcional.inner      # 'error T?': transparente
        if opcional.kind is not TypeKind.NULLABLE or opcional.inner is None:
            self.ctx.error(ASTError.TypeMismatchError(
                f"el lado izquierdo de '??' es de tipo '{left!r}', que no "
                "puede valer null: '??' desenvuelve un 'T?' y aqui el valor "
                "por defecto no se usaria nunca. Usa el valor directamente",
                line=node.ln, column=node.col,
            ))
            return left
        contenido = opcional.inner
        if _is_null_literal(node.right):
            self.ctx.error(ASTError.TypeMismatchError(
                f"el valor por defecto de '??' no puede ser 'null': el "
                f"resultado es un '{contenido!r}', el contenido de "
                f"'{left!r}'",
                line=node.right.ln, column=node.right.col,
            ))
        elif not type_service.es_desconocido(right) \
                and not type_service.same_type(contenido, right):
            mutabilidad = ""
            if contenido.kind is TypeKind.POINTER \
                    and right.kind is TypeKind.POINTER \
                    and type_service.same_type(contenido.inner, right.inner):
                mutabilidad = (": tampoco suelta 'mutable' (liga antes el "
                               f"puntero a un '{contenido!r}', o declara el "
                               f"opcional como '{right!r}?')")
            self.ctx.error(ASTError.TypeMismatchError(
                f"el valor por defecto de '??' es de tipo '{right!r}' y tiene "
                f"que ser exactamente '{contenido!r}' (el contenido de "
                f"'{left!r}'): '??' no convierte"
                f"{mutabilidad or self._sugerencia(contenido, right)}",
                line=node.right.ln, column=node.right.col,
            ))
        self._null_coalesce_ownership(node, contenido)
        return contenido

    def _null_coalesce_ownership(self, node: ast.BinaryOp,
                                 contenido: Type) -> None:
        """``x ?? d`` COPIA el contenido de ``x``: con destructor es SEM032
        (y en un generico, una copia de ``T`` que decide la instancia)."""
        if _es_puntero(contenido):
            return
        genericos = self._genericos()
        if genericos and type_service.mentions_param(contenido, genericos):
            self._anotar_copia(contenido, node.left)
            return
        if not type_service.owns_resources(contenido, self.ctx.scope,
                                           self.ctx.table):
            return
        escrito = _texto_de_nombre(node.left) or "x"
        self.ctx.error(SemanticError.ImplicitOwnershipCopyError(
            f"'{escrito} ?? ...' entregaria una COPIA del "
            f"contenido, de tipo '{contenido!r}', que tiene destructor: el "
            "original y la copia serian dos dueños del mismo recurso, que se "
            "destruiria dos veces. Desenvuelvelo con 'match', que lo PRESTA "
            "('match (x) { case null { ... } case v { ... } }')",
            line=node.ln, column=node.col,
        ))

    def _literal_como_byte(self, node: ast.BinaryOp, left, right):
        """``b == 0xFF``, ``b & 0x0F``: un LITERAL entero junto a un ``byte``
        es un ``byte`` si cabe (y si no cabe, lo dice). Es la misma regla que
        ligarlo (``_coercion_literal``); sin ella no habria forma de escribir
        un octeto sin un ``cast``."""
        if left is not None and right is not None:
            if left.kind is TypeKind.BYTE and right.kind is TypeKind.INT:
                nuevo = self._coercion_literal(left, node.right, right)
                if nuevo is not None:
                    node.right = nuevo
                    right = left
            elif right.kind is TypeKind.BYTE and left.kind is TypeKind.INT:
                nuevo = self._coercion_literal(right, node.left, left)
                if nuevo is not None:
                    node.left = nuevo
                    left = right
        return left, right

    def _comparacion(self, node: ast.BinaryOp, left, right) -> None:
        """Una COMPARACION compara dos valores del MISMO tipo: sin
        conversiones implicitas, igual que la aritmetica. Antes 'int == float'
        pasaba sin decir nada (el interprete comparaba 1 == 1.0 y la VM leia
        los bits del entero como un double). Se admite comparar un 'T?' o un
        'error T' con su 'T', y 'ptr mutable T' con 'ptr T'; 'null' no tiene
        tipo propio y no se rechaza. Ordenar ('<', '>'...) es de los numeros,
        los caracteres, las cadenas y los bytes; de un enum sin datos (un
        entero), y de un tipo nominal que declare ``__cmp__``. Sobre un
        PARAMETRO de tipo se acepta y se anota: lo decide cada instancia
        (SEM039), igual que las copias (SEM038)."""
        if left is None or right is None or type_service.es_desconocido(left) \
                or type_service.es_desconocido(right):
            return
        a, b = _comparable(left), _comparable(right)
        if a != b:
            self.ctx.error(ASTError.TypeMismatchError(
                f"comparación '{node.operator}' entre tipos distintos "
                f"('{left!r}' y '{right!r}'): no hay conversiones implícitas; "
                "convierte uno con 'cast<T>(...)'",
                line=node.ln, column=node.col,
            ))
            return
        if node.operator not in ("<", "<=", ">", ">="):
            return
        if _es_parametro_desnudo(a, self._genericos()):
            # 'a < b' con 'a: T': el cuerpo no sabe con que se instanciara.
            # Antes era un error sin mas —T no estaba en la lista de los que
            # se ordenan—, y por eso no se podia escribir un 'sort' generico.
            # Ahora se anota y cada instancia comprueba su tipo concreto. Con
            # la cota 'T: Ord' ya esta comprobado aqui, en la definicion: cada
            # instancia la cumplio en su llamada.
            if not self._has_bound(a.name, _ORD):
                self._anotar_orden(a, node)
        elif not self._ordenable(a):
            self.ctx.error(ASTError.TypeMismatchError(
                f"'{node.operator}' no ordena valores de tipo '{left!r}': "
                "se ordenan números, caracteres, cadenas, bytes y enums sin "
                "datos; un tipo propio se ordena declarando "
                f"'hook fn __cmp__({a!r} ptr a, {a!r} ptr b) -> int'"
                if a.kind is TypeKind.NOMINAL else
                f"'{node.operator}' no ordena valores de tipo '{left!r}': "
                "se ordenan números, caracteres, cadenas, bytes y enums sin "
                "datos",
                line=node.ln, column=node.col,
            ))
            return
        # un 'T?' puede ser null, y null no es menor ni mayor que nada: antes
        # pasaba y el interprete caia (ICE000) al comparar null con un numero
        for lado in (left, right):
            while lado.kind is TypeKind.ERROR and lado.inner is not None:
                lado = lado.inner
            if lado.kind is TypeKind.NULLABLE:
                self.ctx.error(ASTError.TypeMismatchError(
                    f"'{node.operator}' no ordena un '{lado!r}': puede valer "
                    "null, y null no es menor ni mayor que nada",
                    line=node.ln, column=node.col,
                ))
                return

    def _expr_assignment(self, node: ast.Assignment) -> Optional[Type]:
        value_type = self.visit_expr(node.value)
        self._tiene_dueno(node.value)   # el destino se queda con el valor
        target = node.target
        if isinstance(target, ast.Identifier):
            symbol = self.ctx.scope.resolve_value(target.name)
            if symbol is not None:
                self.ctx.usar(symbol, target.ln, target.col)
            if symbol is None:
                self.ctx.error(SemanticError.UndefinedSymbolError(
                    f"'{target.name}' no está declarado",
                    line=target.ln, column=target.col,
                ))
                return value_type
            frame = self._capture_of(symbol, target.name, record=False)
            if frame is not None:
                self.ctx.error(SemanticError.ImmutableAssignmentError(
                    f"asignar a '{target.name}' no se puede: "
                    f"{_captured_reason(target.name, frame)}",
                    line=node.ln, column=node.col,
                ))
            elif not symbol.mutable:
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
            elif not self._acepta_valor(
                    symbol.type, node.value, value_type,
                    lambda e: setattr(node, "value", e)):
                self.ctx.error(ASTError.TypeMismatchError(
                    f"no se puede asignar '{value_type!r}' a "
                    f"'{target.name}' ({symbol.type!r})"
                    f"{self._sugerencia(symbol.type, value_type)}",
                    line=node.ln, column=node.col,
                ))
            self._asignacion_de_dueno(node, symbol.type)
            return symbol.type
        # target compuesto (a.b = x, a[i] = x): se valida la base y, si la
        # base es un puntero de SOLO LECTURA ('ptr T' sin 'mutable'), la
        # escritura a traves de el es un error (const-correctness).
        if isinstance(target, (ast.MemberAccess, ast.Index)):
            base_type = self.visit_expr(target.obj)
            self._no_escribe_en_una_copia(target.obj, "asignar a", target)
            # a traves de un puntero de SOLO LECTURA ('T ptr' sin 'mutable'),
            # de un 'const' o de lo que liga un patron o un 'catch', a
            # cualquier profundidad ('c.n', 'd.c.n', 'p.dentro.n')
            self._check_writable(target.obj, f"asignar a '{_texto_de(target)}'",
                                 node)
            # resolver el miembro/indice en si (reusa la logica normal)
            if isinstance(target, ast.MemberAccess):
                field_type = self._resolve_field(base_type, target)
                self._check_escritura(node, f"'{target.member}'", field_type,
                                      value_type)
                self._asignacion_de_dueno(node, field_type)
                return field_type or value_type
            index_type = self.visit_expr(target.index)
            if base_type is not None and base_type.kind is TypeKind.STR:
                # una cadena se LEE por indice ('s[i]' es un 'char') pero no
                # se escribe: los 'str' son inmutables. Era RT014 al ejecutar.
                self.ctx.error(SemanticError.NotIndexableError(
                    f"'{_texto_de(target)} = ...': un 'str' se lee por indice "
                    "pero no se escribe (las cadenas son inmutables). Construye "
                    "otra: concatena las partes ('+') o usa 'text.replace'",
                    line=node.ln, column=node.col,
                ))
                return value_type
            elemento = self._tipo_del_elemento(base_type)
            self._check_escritura(node, "el elemento", elemento, value_type)
            hook = self._hook_de_escritura(base_type)
            if hook is not None:
                # 'v[i] = x' lo escribe el '__index_set__': es una llamada, y
                # su indice se comprueba como un argumento (H01)
                mapa = self._mapa_de(hook, base_type)
                self._check_index_type(
                    target, index_type,
                    type_service.substitute(hook.param_types[1], mapa),
                    "el 2.o parametro del '__index_set__' de "
                    f"'{_nominal_name(self._canonical(base_type))}'")
                self._instancia(hook, mapa, node)
            else:
                self._asignacion_de_dueno(node, elemento)
            return value_type
        return self.visit_expr(target) or value_type

    def _no_escribe_en_una_copia(self, base, accion: str, destino,
                                 llamadas: bool = True) -> None:
        """SEM041: escribir en algo que cuelga de una COPIA temporal.

        ``base`` es lo que se modifica (la base de un ``a.b = x`` / ``a[i] =
        x``, o el receptor de un método que muta). Si bajo ella hay una copia
        —un ``v[i]`` que despacha a ``__index__``, o el resultado de una
        llamada si ``llamadas``— la escritura cambiaría la copia, que muere al
        terminar la sentencia: compilaría y no haría nada.

        Antes de que devolver por valor copiara, esto "funcionaba": el valor
        devuelto seguía enlazado al guardado. Ahora hace falta pedir el
        elemento PRESTADO y mutable (``at_mut``), y el error dice cómo."""
        copia = self._copia_temporal(base, llamadas)
        if copia is None:
            return
        texto = _texto_de(destino) if destino is not None else _texto_de(base)
        if isinstance(copia, ast.Index):
            contenedor = _texto_de(copia.obj)
            tipo_obj = getattr(copia.obj, "restype", None)
            owner = _nominal_name(self._canonical(tipo_obj)) \
                if tipo_obj is not None else None
            if owner is not None and \
                    self.ctx.table.lookup_dunder(owner, "at_mut") is not None:
                arreglo = (f"pide el elemento prestado y mutable: "
                           f"'{contenedor}.at_mut(...)' en vez de "
                           f"'{contenedor}[...]'")
            else:
                arreglo = ("sácalo a una variable, modifícala y vuelve a "
                           f"guardarla ('{contenedor}[i] = ...')")
            que = (f"'{contenedor}[...]' es una COPIA del elemento (el "
                   "'__index__' de su tipo devuelve por valor)")
        else:
            arreglo = ("guarda el resultado en una variable, o haz que la "
                       "función devuelva un puntero ('... ptr mutable')")
            que = "el resultado de esta llamada es una COPIA (se devuelve por valor)"
        self.ctx.error(SemanticError.TemporaryMutationError(
            f"{accion} '{texto}': {que}, y el cambio se perdería al terminar "
            f"la sentencia. Para modificar lo que está guardado, {arreglo}",
            line=copia.ln, column=copia.col,
        ))

    def _copia_temporal(self, expr, llamadas: bool):
        """La sub-expresión de la ruta ``expr`` que produce una COPIA
        temporal, o ``None`` si la ruta llega a un lugar real.

        Se baja por los ``.campo``; la ruta deja de ser de una copia en cuanto
        cruza un PUNTERO (escribir a través de él llega al original). Un
        indexado CRUDO (``b[i]`` con ``b`` un bloque de ``mem``) es una celda
        real; uno que despacha a ``__index__`` es una copia. Con un tipo
        desconocido no se afirma nada (cero falsos positivos)."""
        e = expr
        while True:
            tipo = getattr(e, "restype", None)
            if tipo is None or _es_puntero(tipo):
                return None
            if isinstance(e, ast.MemberAccess):
                e = e.obj
                continue
            if isinstance(e, ast.Index):
                # la misma pregunta con que '_expr_index' decide el despacho
                # (también a través de un puntero al contenedor)
                obj_type = getattr(e.obj, "restype", None)
                owner = _nominal_name(self._canonical(obj_type)) \
                    if obj_type is not None else None
                if owner is not None and \
                        self.ctx.table.lookup_hook(owner, HookKind.INDEX) is not None:
                    return e
                return None
            if llamadas and isinstance(e, (ast.Call, ast.StructLiteral)):
                return e
            return None

    def _check_writable(self, base, action: str, node) -> None:
        """Reporta que se MODIFICA lo que designa ``base`` y no se puede.

        ``SEM015`` si el motivo es un puntero de solo lectura, ``SEM003`` si
        es un nombre que no es mutable (un ``const``, lo que liga un patron o
        un ``catch``). La posicion es la de la sentencia que escribe o la de
        la llamada."""
        reason = self._read_only_reason(base)
        if reason is None:
            return
        error_class, why = reason
        self.ctx.error(error_class(
            f"{action} no se puede: {why}",
            line=node.ln, column=node.col,
        ))

    def _read_only_reason(self, base):
        """¿Se puede MODIFICAR lo que designa ``base``? ``None`` si sí (o si
        no se sabe), o ``(clase de error, motivo)`` si no.

        Se baja por los ``.campo`` y los ``[i]`` crudos hasta lo primero que
        decide: un PUNTERO decide por su ``mutable`` (escribir a traves de el
        llega a lo apuntado, de quien sea: es la regla de ``const``
        superficial de C, la misma que ya aplicaba ``p.n = 7``), y un NOMBRE
        que no es puntero decide por si es mutable. Un temporal (el resultado
        de una llamada) se puede modificar; la copia que entrega un
        ``__index__`` es otro error (``SEM041``). Tipo desconocido: no se
        afirma nada (cero falsos positivos)."""
        e = base
        while True:
            symbol = None
            if isinstance(e, ast.Identifier):
                symbol = self.ctx.scope.resolve_value(e.name)
                if symbol is None or symbol.kind not in (SymbolKind.VAR,
                                                         SymbolKind.PARAM):
                    return None
                frame = self._capture_of(symbol, e.name, record=False)
                if frame is not None:
                    # lo capturado se LEE: ni el valor ni, si es un puntero,
                    # lo apuntado (aunque sea un 'ptr mutable')
                    error_class = (SemanticError.ReadOnlyPointerWriteError
                                   if _pointer_core(symbol.type) is not None
                                   else SemanticError.ImmutableAssignmentError)
                    return (error_class, _captured_reason(e.name, frame))
                typ = symbol.type
            else:
                typ = getattr(e, "restype", None)
            if typ is None or type_service.es_desconocido(typ):
                return None
            pointer = _pointer_core(typ)
            if pointer is not None:
                if pointer.mut:
                    return None
                return (SemanticError.ReadOnlyPointerWriteError,
                        f"'{_texto_de(e)}' es un '{format_type(typ)}' (solo "
                        "lectura); declara el puntero como "
                        f"'{format_type(pointer_of(pointer.inner, mut=True))}'")
            if symbol is not None:
                if symbol.mutable or id(symbol) in self._writable_bindings:
                    return None
                inherited = self._pattern_read_only.get(id(symbol))
                if inherited is not None:
                    error_class, why = inherited
                    return (error_class,
                            f"'{e.name}' lo liga un patron sobre algo que no se "
                            f"puede modificar ({why})")
                return (SemanticError.ImmutableAssignmentError,
                        f"'{e.name}' es 'const', y lo que contiene tampoco se "
                        "modifica")
            if isinstance(e, ast.MemberAccess):
                e = e.obj
                continue
            if isinstance(e, ast.Index) and _pointer_core(
                    getattr(e.obj, "restype", None)) is not None:
                e = e.obj      # una celda de un bloque: decide su puntero
                continue
            return None

    def _check_escritura(self, node: ast.Assignment, que: str,
                         destino: Optional[Type],
                         value_type: Optional[Type]) -> None:
        """El valor que se escribe en un CAMPO o en un ELEMENTO es de su tipo.

        La rama del ``Identifier`` ya lo comprobaba; estas dos no, así que
        ``p.x = "a"`` y ``v[0] = "a"`` cruzaban el frontend enteros. Es la
        misma regla y el mismo diagnóstico: el destino tiene un tipo escrito
        y el valor tiene que caber en él.
        """
        if destino is None:
            return
        # "a el elemento" -> "al elemento" (la contraccion del español)
        a_que = f"al {que[3:]}" if que.startswith("el ") else f"a {que}"
        if _is_null_literal(node.value):
            if not type_service.unify_literal_null(destino):
                self.ctx.error(ASTError.TypeMismatchError(
                    f"'null' no es asignable {a_que} ('{destino!r}': no es "
                    "nullable)", line=node.ln, column=node.col,
                ))
        elif not self._acepta_valor(destino, node.value, value_type,
                                    lambda e: setattr(node, "value", e)):
            self.ctx.error(ASTError.TypeMismatchError(
                f"no se puede asignar '{value_type!r}' {a_que} "
                f"('{destino!r}'){self._sugerencia(destino, value_type)}",
                line=node.ln, column=node.col,
            ))

    def _tipo_del_elemento(self, obj_type: Optional[Type]) -> Optional[Type]:
        """Tipo que ``v[i] = x`` admite: el 3er parámetro de ``__index_set__``.

        No el retorno de ``__index__``: quien decide qué se puede ESCRIBIR es
        el hook de escritura, y un tipo podría declarar solo uno de los dos.
        El indexado crudo de un puntero (un bloque de ``mem``) escribe un
        elemento de lo apuntado.
        """
        hook = self._hook_de_escritura(obj_type)
        if hook is None:
            if obj_type is not None and obj_type.kind is TypeKind.POINTER:
                return obj_type.inner
            return None
        return type_service.substitute(hook.param_types[2],
                                       self._mapa_de(hook, obj_type))

    def _hook_de_escritura(self, obj_type: Optional[Type]) -> Optional[Symbol]:
        """El ``__index_set__`` que escribe ``v[i] = x``, o ``None``."""
        owner = _nominal_name(self._canonical(obj_type)) \
            if obj_type is not None else None
        if owner is None:
            return None
        hook = self.ctx.table.lookup_hook(owner, HookKind.INDEX_SET)
        if hook is None or not hook.param_types or len(hook.param_types) != 3:
            return None
        return hook

    def _asignacion_de_dueno(self, node: ast.Assignment,
                             destino: Optional[Type]) -> None:
        """``destino = valor`` sobre algo que POSEE: el valor viejo muere.

        Sin esto ``a = R{...}`` perdia el destructor del ``R`` que habia (los
        dos motores solo soltaban su memoria). Se destruye por su tipo
        concreto (``drops_old``), despues de evaluar el nuevo: ``a = f(a)``
        todavia puede leerlo. Un puntero no posee lo que apunta y no destruye
        nada al reasignarse.

        Y asignar un dueño por NOMBRE lo copia: SEM032, como ligarlo (dentro
        de un generico lo decide la instancia: SEM038).
        """
        if destino is None or _es_puntero(destino):
            return
        genericos = self._genericos()
        generico = bool(genericos) and type_service.mentions_param(destino, genericos)
        if not generico and not type_service.owns_resources(
                destino, self.ctx.scope, self.ctx.table):
            return
        node.drops_old = True
        valor = node.value
        if not self._es_lugar(valor):
            return
        if generico:
            self._anotar_copia(destino, valor)
            return
        nombre = _texto_de(valor)
        self.ctx.error(SemanticError.ImplicitOwnershipCopyError(
            f"se asigna '{nombre}', de tipo '{destino!r}', que tiene "
            "destructor: asignarlo dejaría DOS dueños del mismo recurso y lo "
            f"destruiría dos veces. Transfiérelo con 'move' ('= move "
            f"{nombre}') o toma un puntero si solo quieres leerlo",
            line=node.ln, column=node.col,
        ))

    def _expr_sizeof(self, node: ast.SizeofExpr) -> Optional[Type]:
        """``sizeof(T)``: valida T y enlaza su ``__sizeof__``.

        El enlace lo hacia la pasada de tipos; vive aqui porque el tipo se
        busca en el scope, y el hook se busca por el nombre CANONICO del tipo
        ('int8'), no por el cualificado con el que se escribe ('dt.int8').
        """
        self.types.bind_sizeof(node)
        if node.hook is None and node.medido is not None:
            # decision del mantenedor: un 'sizeof' que siempre fallaria al
            # ejecutar (RT011) no compila. Sobre un parametro de tipo lo
            # decide cada instancia, como 'hash' y las copias.
            if _es_parametro_desnudo(_core(node.medido), self._genericos()):
                self._note_per_instance("sizes", _core(node.medido),
                                        "'sizeof'", node)
            else:
                message = self._size_problem(node.medido)
                if message is not None:
                    self.ctx.error(SemanticError.UndefinedSymbolError(
                        message, line=node.ln, column=node.col))
        return node.restype

    def _size_problem(self, t: Optional[Type]) -> Optional[str]:
        """Por que ``sizeof`` de un ``t`` no puede responder, o ``None`` si
        puede (su tipo declara ``__sizeof__``) o no se sabe.

        El tamano lo da SIEMPRE el hook ``__sizeof__`` del tipo: el layout de
        un primitivo es cosa de cada motor, y ninguno lo expone. La comparten
        ``sizeof`` con un tipo concreto y cada instancia de un generico que
        lo pide de su ``T``: la misma regla dentro y fuera."""
        if t is None:
            return None
        nucleo = _core(t)
        if nucleo is not None and nucleo.kind is TypeKind.FUNCTION:
            return (f"'sizeof' de un valor funcion ('{format_type(t)}') no "
                    "tiene respuesta: una funcion no es un dato con un layout, "
                    "y no puede declarar '__sizeof__'")
        owner = _nominal_name(t)
        if owner is not None:
            if self.ctx.table.lookup_hook(owner, HookKind.SIZEOF) is not None:
                return None
            return (f"'sizeof' no está declarado para '{owner}': el tamano de "
                    f"un tipo lo da su hook '__sizeof__' (hook fn "
                    f"__sizeof__({owner} ptr x) -> int), y '{owner}' no lo "
                    "declara")
        return (f"'sizeof({format_type(t)})' no tiene respuesta: el tamano de "
                "un tipo lo da su hook '__sizeof__', y un tipo nativo no puede "
                "declararlo (su layout es cosa de cada motor). Para un tamano "
                "fijo usa un tipo de 'd_types' (p. ej. 'sizeof(dt.int32)')")

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
                self._tiene_dueno(value)
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
            # nombre CANONICO ('Point', no 'point.Point') + argumentos de tipo
            # validados y aridad comprobada: la MISMA regla que una anotación,
            # y por eso vive en el binder de tipos y no aquí.
            self.types.bind_struct_literal(node, struct_sym)
            mapa = type_service.bindings(struct_sym, node.restype)
            # un generico SIN argumentos utilizables (aridad ya reportada) no
            # se puede sustituir: comparar contra la 'T' sin ligar produciria
            # una cascada de AST006 derivados del SEM027 que ya se emitio.
            comprobar_valores = bool(mapa) or not struct_sym.type_params
            fields = struct_sym.members or {}
            seen: set = set()
            for indice, (fname, value) in enumerate(
                    zip(node.field_names, node.values)):
                value_type = self.visit_expr(value)
                # el valor pasa a ser el CAMPO de este literal: su dueno es el
                # struct que se esta construyendo, no un temporal suelto.
                self._tiene_dueno(value)
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
                elif comprobar_valores:
                    self._check_field_value(
                        written, fname, value, value_type, fields[fname], mapa,
                        lambda e, i=indice: node.values.__setitem__(i, e))
                    self._campo_de_dueno(
                        fname, value,
                        type_service.substitute(fields[fname].type, mapa))
                seen.add(fname)
            self._check_campos_faltantes(written, struct_sym, seen, node)
            return node.restype
        for value in node.values:
            self.visit_expr(value)
        return node.restype

    def _campo_de_dueno(self, fname: str, valor,
                        tipo: Optional[Type]) -> None:
        """``T{ campo: x }`` con ``x`` un dueño POR NOMBRE lo copia: SEM032,
        la misma regla que ligarlo (en un generico, SEM038 en la instancia)."""
        if tipo is None or _es_puntero(tipo) or not self._es_lugar(valor):
            return
        genericos = self._genericos()
        if genericos and type_service.mentions_param(tipo, genericos):
            self._anotar_copia(tipo, valor)
            return
        if not type_service.owns_resources(tipo, self.ctx.scope, self.ctx.table):
            return
        nombre = _texto_de(valor)
        self.ctx.error(SemanticError.ImplicitOwnershipCopyError(
            f"el campo '{fname}' recibiría '{nombre}', de tipo '{tipo!r}', que "
            "tiene destructor: dejaría DOS dueños del mismo recurso. "
            f"Transfiérelo con 'move' ('{fname}: move {nombre}')",
            line=getattr(valor, "ln", 0), column=getattr(valor, "col", 0),
        ))

    # ------------------------------------------------------------------ #
    # copias en un generico (SEM038)
    # ------------------------------------------------------------------ #
    def _anotar_copia(self, tipo: Optional[Type], valor) -> None:
        """El cuerpo en curso COPIA un valor de ``tipo`` (que nombra un
        parametro de tipo). Si eso esta mal lo decide cada instancia."""
        fn = self.ctx.current_fn
        if fn is None or tipo is None:
            return
        archivo = os.path.basename(self.ctx.source_path or "") or "?"
        donde = (f"{archivo}:{getattr(valor, 'ln', 0)}: se copia "
                 f"'{_texto_de(valor)}'")
        self.ctx.copias.setdefault(id(fn), []).append((tipo, donde))

    def _anotar_orden(self, tipo: Type, node) -> None:
        """El cuerpo en curso ORDENA valores de ``tipo`` (un parametro de
        tipo). Si se puede lo decide cada instancia (SEM039)."""
        fn = self.ctx.current_fn
        if fn is None:
            return
        archivo = os.path.basename(self.ctx.source_path or "") or "?"
        donde = (f"{archivo}:{getattr(node, 'ln', 0)}: "
                 f"'{_texto_de(node.left)} {node.operator} "
                 f"{_texto_de(node.right)}'")
        self.ctx.ordenes.setdefault(id(fn), []).append((tipo, donde))

    def _ordenable(self, t: Optional[Type]) -> bool:
        """¿Los valores de ``t`` (ya concreto) se ordenan con ``<``?

        Los primitivos que tienen un orden natural; un enum SIN datos, que
        en ejecucion es un entero y se ordena por el valor de su variante; y
        un tipo nominal que declara ``__cmp__``. Un ``T?`` no: null no es
        menor ni mayor que nada. Un tipo que no se pudo resolver tampoco se
        rechaza aqui: ese diagnostico ya lo dio quien no lo encontro.
        """
        if t is None or type_service.es_desconocido(t):
            return True
        if t.kind in (TypeKind.INT, TypeKind.FLOAT, TypeKind.CHAR,
                      TypeKind.STR, TypeKind.BYTE):
            return True
        if t.kind is not TypeKind.NOMINAL:
            return False
        simbolo = self._nominal_symbol(t)
        if simbolo is None:
            return True
        if simbolo.kind is SymbolKind.ENUM and not any(
                m.param_types for m in (simbolo.members or {}).values()):
            return True
        return self._hook_de_tipo(t, HookKind.CMP) is not None

    def _hook_de_tipo(self, t: Optional[Type], kind: HookKind):
        """El hook ``kind`` del tipo nominal bajo ``t``, o ``None``. Se busca
        por el nombre del simbolo y por el canonico: un tipo de libreria se
        registra con uno y se nombra con el otro."""
        symbol = self._nominal_symbol(t)
        if symbol is None:
            return None
        return (self.ctx.table.lookup_hook(symbol.name, kind)
                or self.ctx.table.lookup_hook(
                    type_service.canonical_name(symbol, t.name if t else ""),
                    kind))

    def _instancia(self, llamado: Optional[Symbol], mapa: dict, node) -> None:
        """Una llamada a un GENERICO con estos tipos. Se decide al cerrar el
        modulo (``verificar_copias``): el llamado puede estar mas abajo."""
        if llamado is None or not mapa:
            return
        fn = self.ctx.current_fn
        llamador = self.ctx.fn_symbols.get(id(fn)) if fn is not None else None
        self.ctx.instancias.append(
            (llamador, self._genericos(), llamado, dict(mapa),
             llamado.name, getattr(node, "ln", 0), getattr(node, "col", 0)))

    def verificar_copias(self) -> None:
        """Que COPIA y que ORDENA cada generico, y que instancia no puede.

        Tres pasos, los mismos para las dos preguntas:

        1. Lo DIRECTO de cada cuerpo pasa a su Symbol.
        2. Se propaga: si ``f<T>`` llama a ``g<U>`` con ``U = T`` y ``g``
           copia (u ordena) su ``U``, ``f`` copia (u ordena) su ``T``
           (``Vector.grow`` copiaba a traves de ``mem.copy``). Hasta que nada
           cambie, con tope: una recursion polimorfica (``f<T>`` que llama a
           ``f<Caja<T>>``) no terminaria.
        3. Cada instancia con tipos CONCRETOS: si lo que copia tiene
           destructor, SEM038 en la llamada; si lo que ordena no se ordena,
           SEM039 en la llamada.
        """
        ctx = self.ctx
        for fn_id, lista in ctx.copias.items():
            simbolo = ctx.fn_symbols.get(fn_id)
            if simbolo is not None:
                simbolo.copias = tuple(dict.fromkeys(lista))
        for fn_id, lista in ctx.ordenes.items():
            simbolo = ctx.fn_symbols.get(fn_id)
            if simbolo is not None:
                simbolo.ordenes = tuple(dict.fromkeys(lista))
        for field in ("elem_borrows", "hashes", "sizes"):
            for fn_id, lista in getattr(ctx, field).items():
                simbolo = ctx.fn_symbols.get(fn_id)
                if simbolo is not None:
                    setattr(simbolo, field, tuple(dict.fromkeys(lista)))
        # una copia de 'Caja<T>' copia un 'T'; un orden de 'Caja<T>' NO
        # ordena un 'T' (lo ordena el '__cmp__' de Caja, si lo tiene): solo
        # sube al llamador el orden de un parametro DESNUDO.
        self._propagar("copias", type_service.mentions_param)
        self._propagar("ordenes", _es_parametro_desnudo)
        self._propagar("elem_borrows", _es_parametro_desnudo)
        self._propagar("hashes", _es_parametro_desnudo)
        self._propagar("sizes", _es_parametro_desnudo)
        for llamador, genericos, llamado, mapa, nombre, ln, col in ctx.instancias:
            for tipo, donde in llamado.copias:
                concreto = type_service.substitute(tipo, mapa)
                if genericos and type_service.mentions_param(concreto, genericos):
                    continue   # lo decide la instancia del llamador
                if _es_puntero(concreto) or not type_service.owns_resources(
                        concreto, ctx.scope, ctx.table):
                    continue
                ctx.error(SemanticError.GenericOwnerCopyError(
                    f"'{nombre}' copia un valor de tipo '{concreto!r}' "
                    f"({donde}), y '{concreto!r}' tiene destructor: la copia y "
                    "el original serian dos dueños y se destruiria dos veces. "
                    "Usa una operacion que PRESTE (un puntero) o que SAQUE "
                    "el valor ('move', 'mem.take'); en un Vector, 'v.at(i)' o "
                    "'v.take(i)'",
                    line=ln, column=col,
                ))
                break
            for tipo, donde in llamado.ordenes:
                concreto = type_service.substitute(tipo, mapa)
                if genericos and _es_parametro_desnudo(concreto, genericos):
                    continue   # lo decide la instancia del llamador
                if self._ordenable(concreto):
                    continue
                ctx.error(SemanticError.GenericNotOrderableError(
                    f"'{nombre}' ordena valores de tipo '{concreto!r}' "
                    f"({donde}), y '{concreto!r}' no se ordena: "
                    + (f"declara 'hook fn __cmp__({concreto!r} ptr a, "
                       f"{concreto!r} ptr b) -> int' (negativo si 'a' va "
                       "antes, 0 si empatan, positivo si va despues)"
                       if concreto.kind is TypeKind.NOMINAL else
                       "se ordenan números, caracteres, cadenas, bytes, enums "
                       "sin datos y los tipos que declaran '__cmp__'"),
                    line=ln, column=col,
                ))
                break
            self._check_instance_needs(genericos, llamado, mapa, nombre, ln, col)

    def _check_instance_needs(self, genericos, llamado: Symbol, mapa: dict,
                              nombre: str, ln: int, col: int) -> None:
        """Paso 3 de :meth:`verificar_copias` para lo que PRESTA
        (``elem_borrows``) y lo que pide ``hash`` (``hashes``): con el tipo
        concreto de ESTA instancia, el mismo error que fuera de un generico,
        en la llamada y diciendo donde lo hace el generico."""
        for tipo, donde in llamado.elem_borrows:
            concreto = type_service.substitute(tipo, mapa)
            if genericos and _es_parametro_desnudo(concreto, genericos):
                continue   # lo decide la instancia del llamador
            if not self._is_scalar(concreto):
                continue
            self.ctx.error(SemanticError.InvalidAddressOfError(
                f"'{nombre}' presta un elemento de tipo '{format_type(concreto)}' "
                f"({donde}), y '{format_type(concreto)}' es un escalar: solo se "
                "presta un elemento que es un objeto (un struct, un enum con "
                "datos), porque ningun motor tiene punteros al interior de un "
                "bloque. Para un escalar, leelo por valor ('v.get(i)', 'v[i]', "
                "'d.get(k)') y escribelo con 'v.set(i, x)', 'v[i] = x' o "
                "'d.put(k, x)'",
                line=ln, column=col,
            ))
            break
        for tipo, donde in llamado.hashes:
            concreto = type_service.substitute(tipo, mapa)
            if genericos and _es_parametro_desnudo(concreto, genericos):
                continue
            problem = self._hash_problem(concreto)
            if problem is None:
                continue
            error_class, message, _typ = problem
            self.ctx.error(error_class(
                f"'{nombre}' pide el hash de un '{format_type(concreto)}' "
                f"({donde}): {message}",
                line=ln, column=col,
            ))
            break
        for tipo, donde in llamado.sizes:
            concreto = type_service.substitute(tipo, mapa)
            if genericos and _es_parametro_desnudo(_core(concreto), genericos):
                continue
            message = self._size_problem(concreto)
            if message is None:
                continue
            self.ctx.error(SemanticError.UndefinedSymbolError(
                f"'{nombre}' pide el tamano de un '{format_type(concreto)}' "
                f"({donde}): {message}",
                line=ln, column=col,
            ))
            break

    def _propagar(self, campo: str, sigue_abierto) -> None:
        """Paso 2 de :meth:`verificar_copias` para ``campo`` (``copias`` u
        ``ordenes`` del Symbol): lo que el llamado deja abierto en terminos de
        los parametros del llamador pasa al llamador."""
        for _ in range(32):
            cambio = False
            for llamador, genericos, llamado, mapa, *_resto in self.ctx.instancias:
                pendientes = getattr(llamado, campo)
                if llamador is None or not genericos or not pendientes:
                    continue
                cubierto = _CONCEPT_OF_LIST.get(campo)
                env = self._symbol_env(llamador) if cubierto is not None else {}
                for tipo, donde in pendientes:
                    concreto = type_service.substitute(tipo, mapa)
                    actuales = getattr(llamador, campo)
                    if cubierto is not None \
                            and concreto.kind is TypeKind.NOMINAL \
                            and self._has_bound(concreto.name, cubierto, env):
                        # el llamador promete esa cota: cada instancia suya
                        # ya la cumplio en su llamada
                        continue
                    if sigue_abierto(concreto, genericos) \
                            and (concreto, donde) not in actuales:
                        setattr(llamador, campo, actuales + ((concreto, donde),))
                        cambio = True
            if not cambio:
                break

    def _check_field_value(self, written: str, fname: str, value,
                           value_type: Optional[Type], field_sym: Symbol,
                           mapa: dict, poner=None) -> None:
        """El valor escrito para un campo es asignable al TIPO del campo.

        El campo se declaró con los PARÁMETROS del genérico, así que se
        sustituye antes de comparar: el campo ``T d`` visto desde un
        ``Caja<int>{ d: ... }`` exige un ``int``. Sin esta comprobación el
        literal era el agujero por el que un genérico se construía con el
        contenido equivocado — y luego su tipo decía otra cosa.

        Mismo criterio permisivo que init/asignación/llamada: un tipo
        desconocido pasa, y la compatibilidad la decide ``_arg_assignable``.
        """
        esperado = type_service.substitute(field_sym.type, mapa)
        ln = getattr(value, "ln", 0)
        col = getattr(value, "col", 0)
        if _is_null_literal(value):
            if not type_service.unify_literal_null(esperado):
                self.ctx.error(ASTError.TypeMismatchError(
                    f"campo '{fname}' de '{written}': 'null' no es asignable "
                    f"a '{esperado!r}' (no es nullable)", line=ln, column=col,
                ))
        elif not self._acepta_valor(esperado, value, value_type,
                                    poner or (lambda e: None)):
            self.ctx.error(ASTError.TypeMismatchError(
                f"campo '{fname}' de '{written}': se esperaba "
                f"'{esperado!r}', se encontró '{value_type!r}'"
                f"{self._sugerencia(esperado, value_type)}",
                line=ln, column=col,
            ))

    def _check_campos_faltantes(self, written: str, struct_sym: Symbol,
                                escritos: set, node) -> None:
        """Un literal nombra TODOS los campos del struct (``SEM028``).

        No hay valores por defecto: un campo que el literal no escribe no
        existe en el valor construido, y leerlo reventaba en runtime lejos de
        la causa. Solo se comprueba si el struct declara campos — un símbolo
        sin miembros es un tipo opaco de librería, del que no se sabe.
        """
        campos = struct_sym.members
        if not campos:
            return
        faltan = [n for n in campos if n not in escritos]
        if not faltan:
            return
        self.ctx.error(SemanticError.IncompleteStructLiteralError(
            f"el literal de '{written}' no da valor a "
            f"{', '.join(repr(n) for n in faltan)}: un struct se construye "
            "con todos sus campos (no hay valores por defecto)",
            line=node.ln, column=node.col,
        ))

    def _expr_cast(self, node: ast.CastExpr) -> Optional[Type]:  # noqa: D401
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
        # el destino se valida y CANONICALIZA antes de buscar en la tabla:
        # la libreria registro sus conversiones bajo el nombre con el que
        # declaro el tipo ('int8'), no bajo el cualificado ('dt.int8').
        self.types.bind_cast(node)
        value_type = self.visit_expr(node.value)
        target = node.restype
        # origen DESCONOCIDO (incluido el 'error' sin envolver de un
        # 'catch (e)'): permisivo, cero falsos positivos. Es tambien la unica
        # via para sacar el valor capturado a un tipo concreto — el par se
        # re-verifica en el MIR.
        if target is None or type_service.es_desconocido(value_type):
            return target
        if target == value_type:
            return target
        if (value_type.kind, target.kind) in _NATIVE_CASTS:
            return target
        if self._cast_de_enum(value_type, target, node):
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

    def _cast_de_enum(self, origen: Optional[Type], destino: Optional[Type],
                      node: ast.CastExpr) -> bool:
        """``cast<int>(TType.PLUS)`` y ``cast<TType>(10)``.

        Un enum SIN payload es un entero con nombre —lo es en el HIR, en el
        interprete y en el target web—, asi que convertirlo no cambia el
        valor: solo se gana o se pierde el nombre. No entra en
        ``_NATIVE_CASTS`` porque esa tabla va por ``TypeKind`` y un enum es
        NOMINAL: aceptarlo ahi habria abierto la conversion a cualquier
        struct.

        De ``int`` a enum se comprueba que el literal SEA uno de los valores
        declarados. Es la mitad que hace la conversion segura: sin ella,
        ``cast<TType>(999)`` produciria un valor de un tipo que no tiene ese
        valor, y el ``match`` exhaustivo que el compilador verifica dejaria de
        cubrirlo. Un valor calculado no se puede comprobar y pasa.
        """
        hacia_int = self._items_de_enum(origen) is not None and \
            destino is not None and destino.kind is TypeKind.INT
        items = self._items_de_enum(destino)
        desde_int = items is not None and origen is not None \
            and origen.kind is TypeKind.INT
        if not hacia_int and not desde_int:
            return False
        if desde_int and isinstance(node.value, ast.Literal):
            valores = {s.const_value for s in items.values()
                       if s.const_value is not None}
            if node.value.value not in valores:
                declarados = ", ".join(
                    f"{n}={s.const_value}" for n, s in sorted(items.items())
                    if s.const_value is not None)
                self.ctx.error(SemanticError.InvalidCastError(
                    f"{node.value.value} no es un valor de "
                    f"'{destino!r}' ({declarados}): un enum solo tiene los "
                    "valores que declara",
                    line=node.ln, column=node.col,
                ))
                return True   # ya se reporto: no encadenar un SEM016 encima
        return True

    def _items_de_enum(self, t: Optional[Type]) -> Optional[dict]:
        """Los items de ``t`` si es un enum SIN payload; ``None`` si no lo es.

        Con payload el enum es un tipo suma y sus valores dejan de ser
        enteros, asi que la conversion no significa nada.
        """
        if t is None or t.kind is not TypeKind.NOMINAL or not t.name:
            return None
        # Primero por el nombre CANONICO (como '_enum_de'): dentro de la
        # propia libreria el tipo se llama 'frontend.TType', y buscarlo como
        # RUTA tomaba 'frontend' por un alias de import que ahi no existe
        # -> SEM016 sobre un 'cast<int>(t)' valido.
        simbolo = self._enum_de(t)
        if simbolo is None:
            simbolo = type_service.lookup_type_path(t.name, self.ctx.scope).symbol
        if simbolo is None or simbolo.kind is not SymbolKind.ENUM \
                or not simbolo.members:
            return None
        if any(s.param_types for s in simbolo.members.values()):
            return None
        return simbolo.members

    def _canonical(self, t: Optional[Type]) -> Optional[Type]:
        """Nominal CUALIFICADO (``dt.int8``) -> nominal canónico (``int8``).

        Las anotaciones ESCRITAS ya las canonicaliza ``TypeBinder``; esto es
        para los tipos que llegan de la TABLA DE SÍMBOLOS —el retorno de una
        función, el tipo de un campo— que se guardaron tal como se
        escribieron. Sin esto, ``cast<int>(g())`` sobre un ``fn g() -> dt.int8``
        no encontraba el par ``int8 -> int`` que la librería sí declara.

        Atraviesa los envoltorios (``dt.int8 ptr``) y delega la regla del
        nombre en ``type_service``, que es donde vive la identidad de tipos.
        """
        return type_service.canonical(t, self.ctx.scope)

    def _check_index_type(self, node: ast.Index, index_type: Optional[Type],
                          expected: Optional[Type], hook_name: str) -> None:
        """AST006 si el INDICE de ``v[i]`` no es del tipo que el operador pide.

        ``expected`` es el 2.o parametro de ``__index__``/``__index_set__`` ya
        sustituido (``int`` en un ``Vector<T>``), o ``int`` en ``s[i]`` sobre
        un ``str``. Es la misma pregunta que ``v.get("a")`` (argumento 1 de
        ``get``), y antes no se hacia: ``v["a"]`` llegaba al interprete y era
        ICE000 (una traza de Python), y ``v[1.0]`` un EXC002 que decia
        "fuera de rango" de un indice que estaba EN rango (H01). Un tipo
        desconocido (``None``) no se juzga: otro error ya lo dijo."""
        if expected is None or index_type is None \
                or type_service.es_desconocido(index_type):
            return
        if _is_null_literal(node.index):
            ok = type_service.unify_literal_null(expected)
        else:
            ok = self._acepta_valor(expected, node.index, index_type,
                                    lambda e: setattr(node, "index", e))
        if ok:
            return
        self.ctx.error(ASTError.TypeMismatchError(
            f"el indice de '{_texto_de(node)}' debe ser '{expected!r}' "
            f"({hook_name}), se encontró '{index_type!r}'"
            f"{self._sugerencia(expected, index_type)}",
            line=getattr(node.index, "ln", node.ln),
            column=getattr(node.index, "col", node.col),
        ))

    def _expr_index(self, node: ast.Index) -> Optional[Type]:
        obj_type = self.visit_expr(node.obj)
        index_type = self.visit_expr(node.index)
        # 'v[i]' sobre un tipo nominal con hook __index__: el tipo de la
        # expresión es el ELEMENTO (el retorno del hook). El indexado crudo de
        # un puntero/bloque no tiene tipo definido en esta fase (None).
        # 's[i]' sobre un 'str' es NATIVO, por lo mismo que 'len(s)': una
        # cadena se lee sin que ninguna libreria lo declare, y 'str' es
        # primitivo — SEM006 prohibe colgarle un '__index__'. Sin esto una
        # cadena se podia MEDIR pero no LEER, que es media cadena: escribir un
        # lexer en suriaX era imposible.
        if obj_type is not None and obj_type.kind is TypeKind.STR:
            self._check_index_type(node, index_type, _INT,
                                   "una cadena se indexa con 'int'")
            return _CHAR
        if _es_parametro_desnudo(obj_type, self._genericos()):
            self._unbounded_member(obj_type, "'[...]'", node)
            return None
        owner = _nominal_name(self._canonical(obj_type)) \
            if obj_type is not None else None
        if owner is not None:
            hook = self.ctx.table.lookup_hook(owner, HookKind.INDEX)
            if hook is not None:
                mapa = self._mapa_de(hook, obj_type)
                if hook.param_types and len(hook.param_types) >= 2:
                    self._check_index_type(
                        node, index_type,
                        type_service.substitute(hook.param_types[1], mapa),
                        f"el 2.o parametro del '__index__' de '{owner}'")
                self._instancia(hook, mapa, node)
                return type_service.substitute(hook.type, mapa)
        # el indexado CRUDO de un puntero (un bloque de 'mem') lee un
        # elemento de lo apuntado: 'self.datos[i]' con 'T ptr datos' es un 'T'
        if obj_type is not None and obj_type.kind is TypeKind.POINTER \
                and obj_type.inner is not None:
            return obj_type.inner
        # Un PRIMITIVO no se indexa y nunca podrá: no tiene dónde declarar
        # '__index__'. Rechazarlo aquí convierte un fallo de ejecución
        # (RT014, lejos de la causa) en un error de compilación con posición.
        # Lo demás se deja pasar: un nominal sin el hook puede recibirlo de
        # una librería que esta pasada aún no vio.
        if obj_type is not None and obj_type.kind in _NO_INDEXABLES:
            self.ctx.error(SemanticError.NotIndexableError(
                f"'{format_type(obj_type)}' no se puede indexar; "
                "el indexado opera sobre punteros a memoria reservada y sobre "
                "tipos que declaran '__index__'",
                line=node.ln, column=node.col,
            ))
        return None

    def _call_with_hint(self, node: ast.Call) -> Optional[Type]:
        """``_expr_call`` y, si el parser dejo una explicacion de lectura
        ambigua (``dos(a < b, c > (d))``, ver ``ast.Call.ambiguity_hint``),
        se pega al PRIMER error que salga de esta llamada.

        Tambien es el unico sitio por el que pasan TODAS las llamadas, y por
        eso decide aqui donde vale una FUNCION PRESTADA (una lambda o un
        parametro de tipo funcion) como argumento: solo si la llamada la
        confirma contra un parametro escrito ``fn(...) -> R``
        (:meth:`_mark_function_args`)."""
        pending = [arg for arg in node.args if self._pending_function_arg(arg)]
        for arg in pending:
            self._fn_args_pending[id(arg)] = arg
        mark = len(self.ctx.errors)
        if not node.ambiguity_hint:
            typ = self._expr_call(node)
            if pending:
                self._check_function_args(node, pending, mark)
            return typ
        typ = self._expr_call(node)
        if pending:
            self._check_function_args(node, pending, mark)
        if len(self.ctx.errors) > mark:
            err = self.ctx.errors[mark]
            if node.ambiguity_hint not in err.message:
                err.message = f"{err.message}. {node.ambiguity_hint}"
                err.args = (err._build_message(err.message, err.loc),)
        return typ

    def _expr_call(self, node: ast.Call) -> Optional[Type]:
        callee = node.callee
        # llamada por nombre plano: 'foo(...)', 'print(x)'
        if isinstance(callee, ast.Identifier):
            symbol = self.ctx.scope.resolve_value(callee.name)
            if symbol is not None:
                self.ctx.usar(symbol, callee.ln, callee.col)
                arg_types = [self.visit_expr(arg) for arg in node.args]
                if symbol.kind in (SymbolKind.VAR, SymbolKind.PARAM):
                    # 'g(5)' con 'g' una variable: se llama a su VALOR, y lo
                    # que se comprueba es su tipo. El callee lleva ese tipo
                    # al HIR: es lo que le dice a un lector que la llamada es
                    # a traves de un valor 'fn(...) -> R'. Llamar a algo que
                    # captura una lambda es LEERLO.
                    self._capture_of(symbol, callee.name)
                    callee.restype = symbol.type
                    return self._call_through_value(node, symbol.type, callee.name,
                                             arg_types)
                if symbol.kind is not SymbolKind.FUNCTION \
                        and symbol.param_types is None:
                    # un modulo, un item de enum sin datos, un tipo: nada que
                    # llamar. Antes la llamada "devolvia" el tipo del simbolo
                    # y fallaba al ejecutar.
                    self._not_callable(node, callee.name,
                                       f"es {_kind_text(symbol)}")
                    return None
                if symbol.kind is SymbolKind.ENUM_ITEM:
                    # 'Ok(5)' pelada: si su enum es GENERICO falta la
                    # instancia (SEM027)
                    symbol = self._variant_instance(symbol, None, callee)
                return self._check_call(symbol, node, arg_types)
            return self._call_hook_or_undefined(node, callee.name,
                                                node.args[0] if node.args else None,
                                                extra_args=node.args[1:])
        # llamada por member-access: 'IO.printf(...)', 'x.print()'
        if isinstance(callee, ast.MemberAccess):
            return self._call_member(node, callee)
        # cualquier otro callee: el resultado de otra llamada, un elemento
        # ('ops[0](3)'), un parentesis. Se llama a su VALOR.
        typ = self.visit_expr(callee)
        arg_types = [self.visit_expr(arg) for arg in node.args]
        return self._call_through_value(node, typ, _texto_de(callee), arg_types)

    def _call_through_value(self, node: ast.Call, typ: Optional[Type], name: str,
                     arg_types: list) -> Optional[Type]:
        """Una llamada a traves de un VALOR de tipo ``typ``.

        Si es un ``fn(...) -> R`` se comprueba EXACTAMENTE como una llamada
        directa (:meth:`_check_args`: aridad, tipos y propiedad —pasar algo
        con destructor a un parametro por valor exige ``move``—) y produce
        ``R``. Si es otra cosa, no se puede llamar (``SEM042``). Un tipo
        desconocido pasa en silencio, como en todas partes.

        ``(fn(...) -> R)?`` tambien se puede llamar: si vale ``null`` es un
        error de ejecucion, igual que leer un campo por un puntero nulo. (Se
        decidio antes de que el lenguaje desenvolviera un ``T?``; para no
        llegar a ese error, ``match`` con ``case null`` o ``f ?? g``.)
        """
        if typ is None or type_service.es_desconocido(typ):
            return None
        fn_type = typ
        while fn_type.kind is TypeKind.ERROR and fn_type.inner is not None:
            fn_type = fn_type.inner
        if fn_type.kind is TypeKind.NULLABLE and is_function(fn_type.inner):
            fn_type = fn_type.inner
        if not is_function(fn_type):
            hint = ""
            if fn_type.kind is TypeKind.POINTER and is_function(fn_type.inner):
                hint = (f"; es un PUNTERO a una funcion: llama a lo apuntado "
                         f"('{name}[0](...)')")
            self._not_callable(
                node, name,
                f"es de tipo '{format_type(typ)}', no una funcion{hint}")
            return None
        self._mark_function_args(node, fn_type.args)
        self._check_args(name, node, fn_type.args, arg_types)
        return fn_type.inner

    def _member_on_primitive(self, member: ast.MemberAccess,
                             obj_type: Optional[Type], called: bool) -> None:
        """SEM042: un metodo o un campo sobre un PRIMITIVO (``s.len()``,
        ``n.abs()``, ``s.length``), con la forma de suriaX como pista.

        Un primitivo no tiene metodos ni campos y no puede tenerlos (SEM006
        prohibe colgarle un hook). Antes compilaba y era RT011 al ejecutar,
        con un mensaje que nombraba el VALOR y no el tipo (H04). Es el error
        mas comun de quien viene de Python, JS o Rust. A traves de un
        puntero (``str ptr``) es lo mismo."""
        core = _core(obj_type)
        if core is None or core.kind not in _PRINTABLE_PRIMITIVES:
            return
        written = format_type(core)
        receiver = _texto_de(member.obj)
        if obj_type is not None and obj_type.kind is TypeKind.POINTER:
            # la pista habla del valor apuntado: 'len(p[0])', no 'len(p)'
            receiver = f"{receiver}[0]"
        name = member.member
        what = (f"'{receiver}.{name}(...)'" if called
                else f"'{receiver}.{name}'")
        if name in ("print", "len", "hash"):
            hint = f"es una funcion nativa: '{name}({receiver})'"
        elif core.kind is TypeKind.STR:
            hint = (f"su longitud es 'len({receiver})', y las operaciones de "
                    "texto son funciones de la libreria 'text' que reciben la "
                    f"cadena ('#import text' y 'text.upper({receiver})')"
                    if name not in _LENGTH_NAMES
                    else f"su longitud es 'len({receiver})'")
        elif core.kind is TypeKind.FLOAT:
            hint = ("las operaciones son funciones que reciben el valor "
                    f"('#import math' y 'math.abs({receiver})')")
        else:
            hint = ("se opera con operadores y funciones que reciben el "
                    f"valor; para escribirlo, 'print({receiver})' o un f-string")
        self.ctx.error(SemanticError.NotCallableError(
            f"{what}: '{written}' es un tipo primitivo y no tiene "
            f"{'metodos' if called else 'campos'}; {hint}",
            line=member.ln, column=member.col,
        ))

    def _not_callable(self, node: ast.Call, name: str, what: str) -> None:
        self.ctx.error(SemanticError.NotCallableError(
            f"'{name}' no se puede llamar: {what}. Solo se llama a una "
            "funcion: declarada, un valor 'fn(...) -> R' o un metodo del tipo "
            "del receptor",
            line=node.ln, column=node.col,
        ))

    def _unbounded_member(self, typ: Optional[Type], what: str, node) -> None:
        """``SEM043``: pedirle algo por su NOMBRE a un ``T`` sin cota."""
        param = _core(typ)
        name = param.name if param is not None else "T"
        prometido = bounds_text(sorted(self._bound_env.get(name, ()),
                                       key=lambda r: r.name))
        tiene = (f"las cotas de '{name}' ('{name}: {prometido}') no lo prometen"
                 if prometido else f"'{name}' es un parametro de tipo SIN cota")
        self.ctx.error(SemanticError.UnboundedGenericMemberError(
            f"{what} sobre un valor de tipo '{format_type(typ)}': "
            f"{tiene}, y un parametro de tipo solo ofrece lo que prometen sus "
            "cotas (cada instancia fallaria a su manera, o haria otra cosa). "
            "Para un metodo, declara una cota con un trait que lo pida "
            f"('<{name}: Contrato>') o recibe una funcion "
            f"('fn({name}) -> ...'); un campo o un '[]' no los promete "
            "ninguna cota",
            line=node.ln, column=node.col,
        ))

    def _import_chain_symbol(self, expr: ast.Expression) -> Optional[Symbol]:
        """Resuelve una cadena ``io.string`` / ``io`` a su símbolo IMPORT
        (submódulos incluidos), SIN reportar errores (el llamador decide).
        Devuelve ``None`` si la cadena no es de imports."""
        if isinstance(expr, ast.Identifier):
            symbol = self.ctx.scope.resolve_value(expr.name)
            if symbol is not None and symbol.kind is SymbolKind.IMPORT:
                self.ctx.usar(symbol, expr.ln, expr.col)
                return symbol
            return None
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
                escrito = f"{_texto_de(obj)}.{callee.member}"
                if member.kind in (SymbolKind.VAR, SymbolKind.PARAM):
                    # una GLOBAL de la libreria que guarda una funcion
                    callee.restype = member.type
                    return self._call_through_value(node, member.type, escrito,
                                             arg_types)
                if member.kind is SymbolKind.IMPORT:
                    self._not_callable(node, escrito, "es un modulo")
                    return None
                return self._check_call(member, node, arg_types)
            # si la base es opaca (members None) ya se reporto al importar;
            # si el miembro falta, _resolve_import_member ya reporto SEM011.
            return None
        # 'Nodo.Literal(5)': el callee nombra una VARIANTE de un enum, no un
        # metodo de un valor. Se resuelve antes de visitar 'obj' porque un
        # nombre de tipo no es un valor y visitarlo daria SEM001.
        variante = self._variante_nombrada(callee)
        if variante is not None:
            return self._construir_variante(node, variante)
        # 'Punto.distancia(&p)': el objeto nombra un TIPO, no un valor. Es el
        # metodo usado como funcion (el receptor va explicito), asi que se
        # llama a ese valor como a cualquier otro.
        if self._type_with_method(obj, callee.member) is not None:
            typ = self.visit_expr(callee)
            arg_types = [self.visit_expr(arg) for arg in node.args]
            if typ is None:
                return None     # ya se dijo por que (SEM044, metodo inexistente)
            return self._call_through_value(node, typ, _texto_de(callee), arg_types)

        # no es una libreria: 'x.__next__()' despacha a un DUNDER del usuario
        # (indexado por (tipo, nombre)); 'x.print()' a un hook del set fijo.
        obj_type = self.visit_expr(obj)
        arg_types = [self.visit_expr(arg) for arg in node.args]
        if _es_parametro_desnudo(_core(obj_type), self._genericos()):
            # 'f.aplica(x)' con 'f: F': el cuerpo no sabe con que se
            # instanciara. Antes se dejaba pasar y era RT011 al ejecutar. Con
            # una cota que lo promete ('F: Aplicable'), si se puede.
            bounded = self._call_on_bounded_param(node, callee, obj_type,
                                                  arg_types)
            if bounded is not _NOT_BOUND:
                return bounded
            self._unbounded_member(obj_type, f"'.{callee.member}(...)'", node)
            return None
        # canonicaliza el owner ('vec.Vector' -> 'Vector'): los dunders/hooks se
        # registran bajo el nombre con el que la librería declaró el tipo, pero
        # un valor puede venir anotado con el nombre CUALIFICADO (p. ej. un campo
        # 'vec.Vector buf', que no se canonicaliza en su sitio como sí lo hace
        # una variable). Sin esto, 'self.buf.push(x)' no encontraría el método.
        owner = _nominal_name(self._canonical(obj_type)) if obj_type is not None \
            else None
        # dunder del usuario: 'x.__metodo__()' -> el dunder (owner, member).
        # Anota el nodo (viaja al HIR); la EJECUCION real de dunders del
        # usuario esta diferida al runtime, no al MIR.
        dunder = self.ctx.table.lookup_dunder(owner, callee.member)
        if dunder is not None:
            node.hook = dunder
            mapa = self._mapa_de(dunder, obj_type)
            name = f"{owner}.{callee.member}"
            origins = {p: _FROM_RECEIVER for p in mapa}
            if not self._bind_method_params(dunder, node, mapa, origins,
                                            arg_types, name):
                return None
            self._check_bounds(dunder, mapa, node, name, origins)
            self._instancia(dunder, mapa, node)
            receptor = (dunder.param_types or (None,))[0]
            if _es_puntero(receptor) and receptor.mut:
                # 'v[i].push(x)': el metodo modifica su receptor, y el
                # receptor es la COPIA que entrego '__index__'. El resultado
                # de una llamada SI se acepta ('abrir(...).write(...)'): es un
                # valor nuevo, no la copia de algo guardado.
                self._no_escribe_en_una_copia(
                    obj, f"llamar a '{callee.member}' (modifica su receptor) "
                         "sobre", None, llamadas=False)
                # ...y no se modifica lo que no es mutable: 'k.sube()' con 'k'
                # 'const', 'p.sube()' con 'p' un 'C ptr', 'v.push(3)' con 'v'
                # un 'Vector<int> ptr'. Antes solo 'p.n = 7' era un error.
                self._check_writable(
                    obj, f"llamar a '{_texto_de(obj)}.{callee.member}(...)', que "
                         "modifica su receptor (lo declara "
                         f"'{format_type(receptor)}'),", node)
            declarados = tuple(dunder.param_types or ())[1:]
            self._mark_function_args(node, declarados,
                                     "host" if dunder.prototype else "")
            self._check_method_args(f"{owner}.{callee.member}", node, dunder,
                                    declarados, mapa, arg_types)
            for index, (arg, declarado) in enumerate(
                    zip(node.args, declarados), start=2):
                # sustituido: 'v.push(r)' con 'Vector<R>' es un 'T' que se
                # instancia como 'R', y ahi tambien hay que ceder con 'move'.
                instanciado = type_service.substitute(declarado, mapa)                     if mapa else declarado
                self._argumento_transferido(
                    f"{owner}.{callee.member}", index, arg, instanciado)
            if type_service.mentions_param(
                    dunder.type, frozenset(p for p in dunder.type_params
                                           if p not in mapa)):
                return None     # un parametro propio sin deducir (AST007)
            return type_service.substitute(dunder.type, mapa)
        # hook DECLARADO POR EL PROYECTO (HTIMS): se invoca como un método,
        # por su nombre. No hay sintaxis dedicada que lo dispare —el
        # compilador no sabe qué significa '__gravity__'—, así que la llamada
        # explícita es su disparador hasta que la VM+JIT lo ligue a su lógica
        # nativa. Ver htims/readme.md y semantic/extensions.py.
        if owner is not None:
            extendido = self.ctx.table.lookup_hook(
                owner, HookKind.EXTENDED, name=callee.member)
            if extendido is not None:
                node.hook = extendido
                return extendido.type
        hook_kind = CALL_HOOKS.get(callee.member)
        if hook_kind is not None and owner is not None:
            hook = self.ctx.table.lookup_hook(owner, hook_kind)
            if hook is not None:
                node.hook = hook
                return hook.type
        return self._call_field(node, callee, obj_type, owner, arg_types)

    def _call_field(self, node: ast.Call, callee: ast.MemberAccess,
                      obj_type: Optional[Type], owner: Optional[str],
                      arg_types: list) -> Optional[Type]:
        """``s.op(3)`` sin un metodo ``op``: un CAMPO que guarda una funcion.

        Los metodos ganan (se miraron antes); si no hay ninguno, el nombre
        puede ser un campo de tipo ``fn(...) -> R``, y entonces se llama a su
        valor. Si el tipo es CONOCIDO y no tiene ni metodo ni campo con ese
        nombre, la llamada no puede funcionar: antes pasaba en silencio y era
        ``RT011`` al ejecutar.
        """
        text = f"{_texto_de(callee.obj)}.{callee.member}"
        core = _core(obj_type)
        if core is not None and core.kind is TypeKind.FUNCTION:
            self._not_callable(node, text, "un valor funcion no tiene "
                               "metodos; se llama con '(...)'")
            return None
        if owner is None:
            # un PRIMITIVO no tiene metodos (H04); un tipo desconocido se
            # deja pasar (otro error ya lo dijo)
            self._member_on_primitive(callee, obj_type, called=True)
            return None
        sym = type_service.resolve_canonical(owner, self.ctx.scope)
        if sym is None or sym.kind not in (SymbolKind.STRUCT,
                                                   SymbolKind.ENUM):
            return None     # opaco o de una libreria que no cargo
        field_sym = (sym.members or {}).get(callee.member) \
            if sym.kind is SymbolKind.STRUCT else None
        if field_sym is not None:
            typ = type_service.substitute(
                field_sym.type, type_service.bindings(sym, core))
            callee.restype = typ
            return self._call_through_value(node, typ, text, arg_types)
        hook_kind = CALL_HOOKS.get(callee.member)
        detail = (f" ni declara '__{callee.member}__'"
                   if hook_kind is not None else "")
        self._not_callable(
            node, text, f"'{owner}' no tiene un metodo ni un campo "
            f"'{callee.member}'{detail}")
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

        if hook_kind in (HookKind.MIN, HookKind.MAX):
            return self._call_rango(node, name, hook_kind, first_arg,
                                    extra_args)

        # ARIDAD de las nativas (H02). 'print' es variadico, pero solo como
        # SENTENCIA (ahi lo descompone '_variadic_print'): en una expresion
        # 'print' no devuelve nada que usar, y aceptar varios argumentos
        # ahi seria escribir el primero y tirar el resto en silencio. 'len'
        # y 'hash' miden UN valor. Antes 'len("ab", "xyz")' daba 2, 'hash(1,
        # 2)' compilaba y 'print()' era RT006 al ejecutar.
        arity_error = None
        if hook_kind is HookKind.PRINT and not node.args:
            arity_error = ("'print' espera al menos 1 argumento: "
                           "'print(x)' o 'print(a, b, ...)' (separados por "
                           "un espacio)")
        elif hook_kind is HookKind.PRINT and len(node.args) > 1:
            arity_error = ("'print' con varios argumentos se escribe como "
                           "SENTENCIA ('print(a, b);'), no dentro de una "
                           "expresion: no devuelve un valor")
        elif hook_kind in (HookKind.LEN, HookKind.HASH) \
                and len(node.args) != 1:
            arity_error = (f"'{name}' espera 1 argumento, recibe "
                           f"{len(node.args)}")
        if arity_error is not None:
            self.ctx.error(SemanticError.CallArityError(
                arity_error, line=node.ln, column=node.col))
            for arg in node.args:
                self.visit_expr(arg)
            return _VOID if hook_kind is HookKind.PRINT else None

        arg_type = self.visit_expr(first_arg) if first_arg is not None else None
        for arg in extra_args:
            self.visit_expr(arg)
        # 'len' sobre un 'str' es NATIVO: una cadena tiene longitud sin que
        # ninguna libreria la declare, igual que '+' suma sin hook. Es la
        # unica forma de medirla — 'str' es primitivo y SEM006 prohibe
        # colgarle un '__len__'.
        if hook_kind is HookKind.LEN and arg_type is not None \
                and arg_type.kind is TypeKind.STR:
            node.hook = _LEN_DE_STR
            return _INT
        if hook_kind is HookKind.HASH and arg_type is not None:
            return self._hash_de(node, arg_type)
        if is_function(_core(arg_type)):
            # 'print(g)' despacharia a un '__print__' que un valor funcion no
            # tiene: sin esto compilaba y era RT006 al ejecutar
            self.ctx.error(SemanticError.UndefinedSymbolError(
                f"'{name}' no está declarado y un valor función "
                f"('{format_type(arg_type)}') no define '__{name}__'"
                + (": para escribirla, usa un f-string ('{g}' escribe "
                   "'<fn nombre>')" if name == "print" else ""),
                line=node.ln, column=node.col,
            ))
            return None
        if hook_kind is HookKind.PRINT and arg_type is not None \
                and arg_type.kind in _PRINTABLE_PRIMITIVES:
            # 'print(5)': un PRIMITIVO se escribe como en un f-string, sin
            # salto de linea, igual que dentro de un generico con 'T: Print'
            # (decision del mantenedor: 'int' cumple 'Print' en todas
            # partes). Viaja como un HookRef cuyo dueño es el primitivo, la
            # misma forma que 'len' de un 'str'.
            node.hook = _print_of_primitive(arg_type)
            return _VOID
        owner = _nominal_name(arg_type)
        if owner is None:
            if hook_kind in (HookKind.PRINT, HookKind.LEN):
                self._hook_on_non_nominal(node, name, arg_type)
            return None  # tipo desconocido: permisivo
        bare = _es_parametro_desnudo(_core(arg_type), self._genericos())
        if bare and hook_kind is HookKind.PRINT \
                and self._has_bound(owner, _PRINT):
            # 'print(x)' con 'x: T' y 'T: Print': comprobado aqui; lo despacha
            # cada motor con el tipo de la instancia
            node.hook = _bound_print(owner)
            return _VOID
        hook = self.ctx.table.lookup_hook(owner, hook_kind)
        if hook is None:
            hint = (f": '{owner}' es un parametro de tipo; para escribirlo, "
                    f"declara la cota '<{owner}: Print>'"
                    if bare and hook_kind is HookKind.PRINT else "")
            self.ctx.error(SemanticError.UndefinedSymbolError(
                f"'{name}' no está declarado y '{owner}' no define "
                f"'__{name}__'{hint}",
                line=node.ln, column=node.col,
            ))
            return None
        node.hook = hook
        return hook.type

    def _hook_on_non_nominal(self, node: ast.Call, name: str,
                             arg_type: Optional[Type]) -> None:
        """``len(3)``, ``print(p)`` con ``p`` un ``int ptr``: SEM001.

        ``print(x)``/``len(x)`` sin una funcion con ese nombre despachan al
        hook (``__print__``/``__len__``) del TIPO de ``x``, y solo un tipo
        nominal puede declararlo (SEM006 prohibe colgarselo a un primitivo).
        Con un puntero o un ``T?`` no hay hook posible: compilaba y era
        RT006 ("'print' no esta ligado") al ejecutar. Dos excepciones no
        llegan aqui: ``len`` de un ``str`` y ``print`` de un PRIMITIVO
        (``print(5)``), que son nativos. Tipo desconocido: permisivo."""
        if arg_type is None or type_service.es_desconocido(arg_type):
            return
        core = _core(arg_type)
        if core is None or core.kind in (TypeKind.META, TypeKind.SELF,
                                         TypeKind.ERROR, TypeKind.NOMINAL):
            return
        written = format_type(arg_type)
        if name == "print":
            advice = ("'print(x)' escribe un primitivo (como un f-string) o un "
                      "tipo propio con '__print__'; para esto, un f-string "
                      "('#import io.stdp' y 'stdp.println(f\"{x}\")')")
        else:
            advice = ("'len' mide un 'str' y los tipos que declaran "
                      "'__len__'")
        self.ctx.error(SemanticError.UndefinedSymbolError(
            f"'{name}' no está declarado y un '{written}' no tiene "
            f"'__{name}__' (ningun tipo que no sea propio puede declararlo): "
            f"{advice}",
            line=node.ln, column=node.col,
        ))

    def _hash_de(self, node: ast.Call, t: Type) -> Optional[Type]:
        """``hash(x)``: NATIVO sobre ``int``/``bool``/``char``/``str``; un
        tipo propio lo da con su ``__hash__``; sobre un PARAMETRO de tipo
        (``hash(k)`` con ``k: K`` en un generico) lo decide cada motor con el
        tipo concreto, y si ese tipo no tiene hash el error es de ejecucion
        (RT011), igual que en el interprete."""
        while t.kind is TypeKind.ERROR and t.inner is not None:
            t = t.inner
        problem = self._hash_problem(t)
        if problem is not None:
            error_class, message, typ = problem
            self.ctx.error(error_class(message, line=node.ln, column=node.col))
            return typ
        primitivos = {TypeKind.INT: "int", TypeKind.BYTE: "int", TypeKind.BOOL: "bool",
                      TypeKind.CHAR: "char", TypeKind.STR: "str"}
        if t.kind in primitivos:
            node.hook = Symbol(name="__hash__", kind=SymbolKind.HOOK, ln=0, col=0,
                               type=_INT, hook_kind=HookKind.HASH,
                               hook_owner=primitivos[t.kind])
            return _INT
        owner = _nominal_name(t)
        if owner is None:
            return None
        hook = self.ctx.table.lookup_hook(owner, HookKind.HASH)
        if hook is None:
            # un parametro de tipo (lo decide cada instancia: se anota) o un
            # enum sin datos (un entero, y se le calcula como a uno): el
            # backend lo resuelve con el tipo concreto
            if _es_parametro_desnudo(_core(t), self._genericos()) \
                    and not self._has_bound(_core(t).name, _HASH):
                self._note_per_instance("hashes", _core(t),
                                        f"'hash({_texto_de(node.args[0])})'",
                                        node)
            node.hook = Symbol(name="__hash__", kind=SymbolKind.HOOK, ln=0, col=0,
                               type=_INT, hook_kind=HookKind.HASH, hook_owner=owner)
            return _INT
        node.hook = hook
        return hook.type

    def _hash_problem(self, t: Type):
        """Por que un valor de tipo ``t`` NO tiene hash: ``(clase de error,
        mensaje, tipo de la expresion)``, o ``None`` si lo tiene o no se sabe.

        La comparten ``hash(x)`` con un tipo concreto y cada instancia de un
        generico que pide ``hash`` de su ``T`` (un ``Dictionary`` con esa
        clave): la misma regla y el mismo codigo dentro y fuera."""
        nucleo = t.inner if t.kind is TypeKind.NULLABLE and t.inner else t
        if nucleo.kind is TypeKind.FUNCTION:
            # se comparan por IDENTIDAD ('=='), pero un hash tendria que salir
            # de esa identidad, y no hay ninguna estable entre motores (la
            # direccion del codigo cambia de un motor a otro)
            return (ASTError.TypeMismatchError,
                    f"un valor funcion ('{format_type(t)}') no tiene hash: no "
                    "puede ser clave de un diccionario. Usa como clave algo que "
                    "la identifique (su nombre, un enum)", _INT)
        if t.kind is TypeKind.FLOAT:
            return (ASTError.TypeMismatchError,
                    "un 'float' no tiene hash: NaN no es igual a si mismo, y un "
                    "valor que no es igual a si mismo no puede ser clave", _INT)
        owner = _nominal_name(t)
        if owner is None or _es_parametro_desnudo(_core(t), self._genericos()):
            return None
        if self.ctx.table.lookup_hook(owner, HookKind.HASH) is not None:
            return None
        simbolo = self._nominal_symbol(t)
        if simbolo is not None and simbolo.kind is SymbolKind.ENUM and not any(
                m.param_types for m in (simbolo.members or {}).values()):
            return None         # un enum sin datos es un entero
        return (SemanticError.UndefinedSymbolError,
                f"'hash' no está declarado y '{owner}' no define '__hash__'",
                None)

    def _call_rango(self, node: ast.Call, name: str, hook_kind,
                    first_arg, extra_args) -> Optional[Type]:
        """``min(T)`` / ``max(T)``: el rango que el tipo declara.

        No son keywords —no cuestan vocabulario— sino nombres corrientes que
        despachan por convención, igual que ``print`` y ``len``; una ``fn min``
        del usuario tiene prioridad y nunca llega aquí.

        El argumento nombra un TIPO (``min(dt.int8)``) o un VALOR
        (``min(a)``, el rango del tipo de ``a``), exactamente como ``sizeof``.
        Se exige que sea un NOMBRE: el resultado se pliega a una constante, y
        plegar ``min(f())`` tiraría la llamada a ``f`` con sus efectos.

        A diferencia de ``print``/``len``, esto NO despacha en ejecución: el
        rango ya es una constante de compilación —por eso ``__min__``/
        ``__max__`` tienen el cuerpo restringido a un literal— así que la
        llamada se resuelve aquí y viaja al HIR como el entero que es.
        """
        if len(node.args) != 1 or not _es_nombre(first_arg):
            self.ctx.error(SemanticError.CallArityError(
                f"'{name}' toma exactamente un nombre: un tipo "
                f"('{name}(dt.int8)') o una variable ('{name}(x)')",
                line=node.ln, column=node.col,
            ))
            for arg in node.args:
                self.visit_expr(arg)
            return None

        owner = self._duenio_del_nombre(first_arg)
        if owner is None:
            self.ctx.error(SemanticError.UndefinedSymbolError(
                f"'{name}' necesita un tipo nominal: "
                f"'{_texto_de_nombre(first_arg)}' no nombra ninguno",
                line=node.ln, column=node.col,
            ))
            return None

        hook = self.ctx.table.lookup_hook(owner, hook_kind)
        if hook is None or hook.const_value is None:
            self.ctx.error(SemanticError.UndefinedSymbolError(
                f"'{owner}' no declara '__{name}__': un tipo publica su rango "
                f"con 'hook fn __{name}__({owner} ptr _) -> int "
                "{ return <entero>; }'",
                line=node.ln, column=node.col,
            ))
            return None

        node.valor_constante = hook.const_value
        return _INT

    def _duenio_del_nombre(self, expr) -> Optional[str]:
        """Nombre CANONICO del tipo que nombra ``expr``, sea un tipo o un valor.

        Se prueba primero el namespace de TIPOS: un nombre que es tipo no deja
        de serlo porque exista una variable homónima (misma regla que
        ``bind_sizeof``)."""
        escrito = _texto_de_nombre(expr)
        if escrito is None:
            return None
        resultado = type_service.lookup_type_path(escrito, self.ctx.scope)
        if resultado.status is type_service.TypeLookup.OK:
            return type_service.canonical_name(resultado.symbol, escrito)
        valor = self.ctx.scope.resolve_value(escrito) \
            if "." not in escrito else None
        if valor is None or valor.type is None:
            return None
        return _nominal_name(self._canonical(valor.type))

    def _expr_member(self, node: ast.MemberAccess) -> Optional[Type]:
        obj = node.obj
        if node.member == "name":
            item = self._item_de_enum(obj)
            if item is not None:
                # el nombre de un item se conoce al COMPILAR, asi que el nodo
                # se sustituye por su cadena: no hay tabla que consultar en
                # ejecucion ni dato nuevo en el HIR. Es el mismo trato que
                # recibe 'min(int8)', que tambien se resuelve a su literal.
                node.nombre_de_item = item.name
                return _STR
        # cadena de imports (submodulos incluidos) en posicion de valor
        import_base = self._import_chain_symbol(obj)
        if import_base is not None:
            member = self._resolve_import_member(import_base, node)
            return self._member_value_type(member, node)
        if isinstance(obj, ast.MemberAccess):
            # 'pt.Punto.distancia': un metodo de un tipo de libreria. Un
            # ITEM ('lib.Color.Verde') sigue el camino de siempre.
            typ = self._type_with_method(obj, node.member)
            if typ is not None:
                return self._method_value(typ, node)
        if isinstance(obj, ast.Identifier):
            base = self.ctx.scope.resolve_value(obj.name)
            if base is None:
                # acceso estatico a un TIPO: 'Color.Rojo' (enum item)
                base = self.ctx.scope.resolve_type(obj.name)
            if base is None:
                # ni valor ni tipo: el nombre no existe. (Antes este error
                # estaba dentro de 'if base is not None' —no corria nunca— y la
                # linea siguiente usaba None: 'noexiste.x' era un ICE000.)
                self.ctx.error(SemanticError.UndefinedSymbolError(
                    f"'{obj.name}' no está declarado",
                    line=obj.ln, column=obj.col,
                ))
                return None
            self.ctx.usar(base, obj.ln, obj.col)
            if base.kind is SymbolKind.IMPORT:
                member = self._resolve_import_member(base, node)
                return self._member_value_type(member, node)
            if base.kind in (SymbolKind.ENUM, SymbolKind.STRUCT):
                return self._resolve_type_member(base, node)
            # instancia: 'p.x' -> campo del struct de su tipo
            return self._resolve_field(base.type, node)
        if isinstance(obj, ast.MemberAccess):
            # 'lib.Res<int, str>.Nada': la variante UNIDAD de un enum GENERICO
            # de una libreria es de la instancia escrita (y sin argumentos,
            # SEM027), como 'Res<int, str>.Nada' en su propia unidad
            enum = self._enum_por_ruta(obj)
            if enum is not None and (enum.type_params or obj.type_args):
                return self._resolve_type_member(enum, node)
        return self._resolve_field(self.visit_expr(obj), node)

    def _member_value_type(self, member: Optional[Symbol],
                         node: ast.MemberAccess) -> Optional[Type]:
        """El tipo de ``lib.x`` usado como valor: una funcion de la libreria
        es un valor ``fn(...) -> R`` (no su retorno, que era lo que daba)."""
        if member is None:
            return None
        if member.kind is SymbolKind.FUNCTION:
            return self._function_value(
                member, f"{_texto_de(node.obj)}.{node.member}", node)
        return member.type

    def _named_type(self, expr) -> Optional[Symbol]:
        """El ``struct``/``enum`` que NOMBRA ``expr`` (``Punto``,
        ``pt.Punto``) cuando no es un valor; ``None`` si no nombra un tipo.

        Un nombre que es valor gana (``p.x`` con una variable ``p``), igual
        que en el resto del lenguaje."""
        if isinstance(expr, ast.Identifier):
            if self.ctx.scope.resolve_value(expr.name) is not None:
                return None
            sym = self.ctx.scope.resolve_type(expr.name)
        elif isinstance(expr, ast.MemberAccess):
            written = _texto_de_nombre(expr)
            if written is None:
                return None
            result = type_service.lookup_type_path(written, self.ctx.scope)
            if result.status is not type_service.TypeLookup.OK:
                return None
            sym = result.symbol
            self._import_chain_symbol(expr.obj)     # el import se USO
        else:
            return None
        if sym is None or sym.kind not in (SymbolKind.STRUCT,
                                                   SymbolKind.ENUM):
            return None
        return sym

    def _type_with_method(self, expr, member_name: str) -> Optional[Symbol]:
        """El tipo que nombra ``expr`` si ``expr.miembro`` NO es uno de sus
        miembros (un campo, un item): entonces solo puede ser un metodo.

        Un item de enum (``Color.Verde``, ``lib.Figura.Nada``) se queda en el
        camino de siempre; esto solo intercepta lo que antes era un error o,
        peor, un acceso a un campo inexistente."""
        typ = self._named_type(expr)
        if typ is None or member_name in (typ.members or {}):
            return None
        return typ

    def _method_value(self, typ: Symbol,
                           node: ast.MemberAccess) -> Optional[Type]:
        """``Punto.distancia``: un metodo de ``@impl`` como VALOR.

        Su tipo es su firma tal cual, receptor incluido —ya es explicito en
        la declaracion—: ``fn(Punto ptr) -> int``. El objeto (``Punto``) no es
        un valor: se marca con el METATIPO, que es lo que un lector del HIR
        mira para saber que ``Punto.distancia`` nombra un metodo y no lee un
        campo. A quien pertenece lo dice el receptor del propio tipo.
        """
        written = f"{_texto_de(node.obj)}.{node.member}"
        owner = type_service.canonical_name(typ, typ.name)
        method = self.ctx.table.lookup_dunder(owner, node.member)
        if method is None:
            self.ctx.error(SemanticError.UndefinedSymbolError(
                f"'{typ.name}' no define '{node.member}' (ni un "
                f"{'item' if typ.kind is SymbolKind.ENUM else 'metodo'} "
                "con ese nombre)",
                line=node.ln, column=node.col,
            ))
            return None
        reason = None
        if node.member.startswith("__"):
            reason = ("es un dunder: lo invoca el lenguaje o se llama sobre su "
                      "receptor, no se pasa como valor")
        elif typ.type_params:
            reason = (f"es de un tipo GENERICO ('{typ.name}<"
                      f"{', '.join(typ.type_params)}>'), y el valor tendria "
                      "que llevar sus tipos")
        elif method.type_params:
            reason = (f"es un metodo GENERICO ('{node.member}<"
                      f"{', '.join(method.type_params)}>'), como una funcion "
                      "generica: envuelvelo en una funcion con los tipos "
                      "escritos")
        else:
            receiver = (method.param_types or (None,))[0]
            if receiver is not None and not _es_puntero(receiver) \
                    and type_service.owns_resources(receiver, self.ctx.scope,
                                                    self.ctx.table):
                reason = ("recibe su receptor POR VALOR y tiene destructor: "
                          "llamado como funcion, el llamador le cederia un "
                          "dueño que el metodo no destruye. Declara el "
                          f"receptor '{format_type(receiver)} ptr'")
        if reason is not None:
            self.ctx.error(SemanticError.InvalidFunctionValueError(
                f"'{written}' no se puede usar como valor: {reason}",
                line=node.ln, column=node.col,
            ))
            return None
        node.obj.restype = META_TYPE
        return function_of(method.param_types or (), method.type or _VOID)

    def _item_de_enum(self, obj) -> Optional[Symbol]:
        """El ITEM que nombra ``obj`` (``TType.PLUS`` o ``PLUS``), o ``None``.

        Solo la forma ESCRITA: una variable de tipo enum no vale, porque su
        item no se sabe hasta ejecutar y este atributo se resuelve al
        compilar. El diagnostico de ese caso lo da el camino normal ('no
        tiene un campo name'), que ya dice donde mirar.
        """
        if isinstance(obj, ast.Identifier):
            simbolo = self.ctx.scope.resolve_value(obj.name)
        elif isinstance(obj, ast.MemberAccess):
            dueno = self._enum_por_ruta(obj.obj)
            if dueno is None:
                return None
            simbolo = (dueno.members or {}).get(obj.member)
        else:
            return None
        if simbolo is not None and simbolo.kind is SymbolKind.ENUM_ITEM:
            return simbolo
        return None

    def _resolve_import_member(self, base: Symbol, node) -> Optional[Symbol]:
        if base.members is None:
            return None  # libreria opaca (no cargada): permisivo, ya reportado
        member = base.members.get(node.member)
        motivo = (base.ocultos or {}).get(node.member) if member is None else None
        # El CODIGO sigue siendo SEM011 (contrato fijado en test_visibility:
        # lo oculto no se exporta); lo que cambia es que el mensaje dice POR
        # QUE, en vez de sugerir que el simbolo no existe.
        if motivo == "internal":
            self.ctx.error(SemanticError.UnknownLibraryMemberError(
                f"'{base.name}' no exporta '{node.member}': existe, pero es "
                "'internal' (exclusivo de su archivo)",
                line=node.ln, column=node.col,
            ))
        elif motivo == "private":
            self.ctx.error(SemanticError.UnknownLibraryMemberError(
                f"'{base.name}' no exporta '{node.member}' fuera de su paquete: "
                "es 'private' (solo visible dentro del mismo paquete)",
                line=node.ln, column=node.col,
            ))
        elif member is None:
            self.ctx.error(SemanticError.UnknownLibraryMemberError(
                f"'{base.name}' no exporta '{node.member}'",
                line=node.ln, column=node.col,
            ))
        return member

    def _resolve_type_member(self, base: Symbol, node) -> Optional[Type]:
        member = base.members.get(node.member) if base.members else None
        if member is None and self.ctx.table.lookup_dunder(
                type_service.canonical_name(base, base.name),
                node.member) is not None:
            # 'Punto.distancia': no es un campo ni un item, es un METODO
            return self._method_value(base, node)
        if member is None:
            if base.kind is SymbolKind.ENUM and node.member == "name":
                # 'TType.name' no existe: el nombre es de un ITEM, no del enum.
                self.ctx.error(SemanticError.UndefinedSymbolError(
                    f"'{base.name}' es el enum, no uno de sus items: el "
                    f"nombre se pide sobre el item ('{base.name}.ALGO.name')",
                    line=node.ln, column=node.col,
                ))
                return None
            self.ctx.error(SemanticError.UndefinedSymbolError(
                f"'{base.name}' no define '{node.member}'",
                line=node.ln, column=node.col,
            ))
            return None
        if member.kind is SymbolKind.ENUM_ITEM and (
                base.type_params or getattr(node.obj, "type_args", None)):
            # 'Res<int, str>.Nada': una variante UNIDAD de un enum generico
            # es de la instancia que se escribe
            instance, _ = self._enum_instance(base, node.obj, node.member)
            return instance
        return member.type

    def _mapa_de(self, miembro: Symbol, obj_type: Optional[Type]) -> dict:
        """El mapa de sustitucion para un METODO o HOOK sobre ``obj_type``.

        Dos vias, y la segunda existe por las librerias: :meth:`_sustitucion`
        saca los nombres del SIMBOLO del tipo, y eso funciona mientras el tipo
        se resuelva por su nombre. Desde el consumidor de una libreria no se
        resuelve —el tipo llega canonicalizado (``Vector``) y en ese scope lo
        unico visible es el cualificado (``vec.Vector``)—, asi que se leen del
        RECEPTOR que el propio miembro declara, que los nombra igual.
        """
        return self._sustitucion(obj_type) or _mapa_por_receptor(
            miembro, _core(self._canonical(obj_type)))

    def _sustitucion(self, obj_type: Optional[Type]) -> dict:
        """Mapa ``parametro -> argumento`` del tipo de un receptor.

        Un metodo o un hook de ``Vector<T>`` se declaro hablando de ``T``;
        llamado sobre un ``Vector<int>`` devuelve ``int``. El mapa se saca del
        tipo del receptor y sale VACIO —camino rapido— para todo tipo no
        generico, que es la inmensa mayoria.
        """
        core = _core(self._canonical(obj_type)) if obj_type is not None else None
        if core is None or not core.args or core.name is None:
            return {}
        symbol = type_service.lookup_type_path(core.name, self.ctx.scope).symbol
        return type_service.bindings(symbol, core) if symbol is not None else {}

    def _resolve_field(self, obj_type: Optional[Type], node) -> Optional[Type]:
        owner = _nominal_name(obj_type)
        if owner is None:
            # un PRIMITIVO no tiene campos (H04); desconocido: permisivo
            self._member_on_primitive(node, obj_type, called=False)
            return None
        if _es_parametro_desnudo(_core(obj_type), self._genericos()):
            # 'x.campo' con 'x: T': ningun 'T' promete campos
            self._unbounded_member(obj_type, f"'.{node.member}'", node)
            return None
        # por nombre CANONICO: un struct de libreria llega como 'a.Error'.
        # Con 'resolve_type' solo, su campo quedaba sin tipo y todo lo que
        # dependia de el se decidia a ciegas ('len(e.msg)' fallaba en
        # ejecucion con RT006, y un campo mal escrito no se reportaba).
        struct_sym = type_service.resolve_canonical(owner, self.ctx.scope)
        if struct_sym is None or not struct_sym.members:
            return None
        member = struct_sym.members.get(node.member)
        if member is None:
            self.ctx.error(SemanticError.UndefinedSymbolError(
                f"'{owner}' no tiene un campo '{node.member}'",
                line=node.ln, column=node.col,
            ))
            return None
        # el campo se declaro con los PARAMETROS del generico; visto a traves
        # de un uso concreto ('Vector<int>') vale su sustitucion.
        return type_service.substitute(
            member.type, type_service.bindings(struct_sym, _core(obj_type)))

    # ------------------------------------------------------------------ #
    # cotas de los parametros de tipo ('<T: Ord + Contrato>')
    # ------------------------------------------------------------------ #
    def _enter_bounds(self, fn: ast.FunctionDecl):
        """Pone el entorno de cotas de ``fn`` (su firma y su cuerpo) y
        devuelve el anterior, para restaurarlo al salir."""
        previous = (self._bound_env, self._env_params)
        symbol = self.ctx.fn_symbols.get(id(fn))
        receiver = fn.params[0].restype if fn.params else None
        self._bound_env = self._bound_env_for(symbol, receiver)
        self._env_params = self._generics_of(fn)
        return previous

    def _enter_type_bounds(self, node):
        """El entorno de un ``struct``/``enum`` generico mientras se enlazan
        sus campos o su payload: las cotas que el mismo declara."""
        previous = (self._bound_env, self._env_params)
        symbol = self.ctx.scope.resolve_type(node.name)
        self._bound_env = {name: frozenset(refs) for name, refs in
                           (symbol.type_bounds if symbol is not None else ())}
        self._env_params = frozenset(node.type_params or ())
        return previous

    def _bound_env_for(self, symbol: Optional[Symbol],
                       receiver: Optional[Type]) -> Dict[str, frozenset]:
        """Que promete cada parametro de tipo dentro de una funcion.

        Dos fuentes: las cotas ESCRITAS (las suyas y las de su ``@impl``) y
        las IMPLICITAS de su receptor: un metodo o un hook de ``Arbol<K, V>``
        con ``struct ... Arbol<K: Ord, V>`` solo se llama sobre un ``Arbol``
        que ya existe, y no existe ninguno cuya ``K`` no se ordene (la
        anotacion que lo creo ya lo exigio). Por eso no hace falta repetir la
        cota en cada ``@impl``.
        """
        env: Dict[str, set] = {}
        for name, refs in (symbol.type_bounds if symbol is not None else ()):
            env.setdefault(name, set()).update(refs)
        core = _core(receiver)
        if core is not None and core.kind is TypeKind.NOMINAL and core.args:
            declared = self._nominal_symbol(core)
            if declared is not None and declared.type_bounds:
                by_param = dict(declared.type_bounds)
                for param, arg in zip(declared.type_params, core.args):
                    if param in by_param and arg.kind is TypeKind.NOMINAL \
                            and not arg.args and arg.name:
                        env.setdefault(arg.name, set()).update(by_param[param])
        return {name: frozenset(refs) for name, refs in env.items()}

    def _has_bound(self, param: str, ref: BoundRef,
                   env: Optional[Dict[str, frozenset]] = None) -> bool:
        """¿El parametro ``param`` promete ``ref`` en el entorno en curso?
        ``Eq`` lo cumple todo tipo (``==`` es igualdad de valor)."""
        if ref == _EQ:
            return True
        return ref in (self._bound_env if env is None else env).get(param, ())

    def _bound_failure(self, t: Optional[Type], ref: BoundRef):
        """Por que el tipo CONCRETO ``t`` no cumple ``ref``: ``(clase de error,
        motivo)``, o ``None`` si la cumple (o si ``t`` no se conoce: ese error
        ya lo dio quien no lo resolvio).

        Las reglas de los conceptos son las que el lenguaje ya aplica a un
        tipo concreto, y cada concepto falla con el MISMO codigo que la
        operacion que nombra: ordenar sin orden es ``SEM039``, como en la
        comprobacion por instancia; un hash que no existe, ``AST006`` o
        ``SEM001``, como ``hash(x)``; ``print`` sin ``__print__``, ``SEM001``.
        Quien pasa de un generico sin cota a uno con cota ve el mismo codigo.
        """
        if t is None or type_service.es_desconocido(t):
            return None
        shown = format_type(t)
        if ref.kind == _bounds.TRAIT:
            symbol = self._nominal_symbol(t) if t.kind is TypeKind.NOMINAL else None
            if symbol is not None and ref in symbol.traits:
                return None
            if symbol is None:
                why = (f"'{shown}' no es un tipo propio, y un trait solo lo "
                       "cumple un tipo que lo declara")
            else:
                why = (f"'{shown}' no declara '@impl({ref.written})' (un trait "
                       "del usuario se cumple de forma explicita)")
            return SemanticError.TraitNotSatisfiedError, why
        if ref.name == "Eq":
            return None
        if ref.name == "Ord":
            if self._ordenable(t):
                return None
            why = (f"'{shown}' no se ordena: declara 'hook fn __cmp__({shown} "
                   f"ptr a, {shown} ptr b) -> int'"
                   if t.kind is TypeKind.NOMINAL else
                   f"'{shown}' no se ordena (se ordenan numeros, caracteres, "
                   "cadenas, bytes, enums sin datos y los tipos que declaran "
                   "'__cmp__')")
            return SemanticError.GenericNotOrderableError, why
        if ref.name == "Hash":
            return self._hash_failure(t, shown)
        if ref.name == "Print":
            if t.kind in _PRINTABLE_PRIMITIVES:
                return None
            symbol = self._nominal_symbol(t) if t.kind is TypeKind.NOMINAL else None
            if symbol is not None and symbol.kind is SymbolKind.ENUM and not any(
                    m.param_types for m in (symbol.members or {}).values()):
                # al ejecutar es un ENTERO: dentro del generico nada lo
                # distingue de un 'int', y su '__print__' no se llamaria
                return (SemanticError.UndefinedSymbolError,
                        f"'{shown}' es un enum sin datos: al ejecutar es un "
                        "entero, y dentro de un generico se escribiria como "
                        "uno (su '__print__', si lo tiene, no se llamaria). "
                        "Escribelo fuera del generico, o dale datos a una "
                        "variante")
            if t.kind is TypeKind.NOMINAL \
                    and self._hook_de_tipo(t, HookKind.PRINT) is not None:
                return None
            why = (f"'{shown}' no define '__print__'"
                   if t.kind is TypeKind.NOMINAL else
                   f"un '{shown}' no se escribe con 'print' (lo cumplen los "
                   "primitivos y los tipos que declaran '__print__')")
            return SemanticError.UndefinedSymbolError, why
        return None  # pragma: no cover - 'bounds.resolve' no produce otros

    def _hash_failure(self, t: Type, shown: str):
        """``Hash``: ``int``, ``bool``, ``char``, ``str``, ``byte``, un enum
        sin datos y un tipo que declara ``__hash__``; lo mismo que hashea el
        interprete. Un ``float`` y una funcion no tienen hash (``AST006``,
        como ``hash(x)``); un puntero o un ``T?`` tampoco."""
        if t.kind in (TypeKind.INT, TypeKind.BYTE, TypeKind.BOOL,
                      TypeKind.CHAR, TypeKind.STR):
            return None
        if t.kind is TypeKind.NOMINAL:
            problem = self._hash_problem(t)
            if problem is None:
                return None
            return problem[0], f"'{shown}' no define '__hash__'"
        if t.kind in (TypeKind.FLOAT, TypeKind.FUNCTION):
            problem = self._hash_problem(t)
            if problem is not None:
                return problem[0], problem[1]
        return (ASTError.TypeMismatchError,
                f"un '{shown}' no tiene hash (lo tienen int, bool, char, str, "
                "byte, los enums sin datos y los tipos que declaran "
                "'__hash__')")

    def _missing_bound(self, param: str, ref: BoundRef, what: str,
                       ln: int, col: int) -> None:
        """``SEM043``: un parametro de tipo SIN la cota que hace falta.

        Es la regla de siempre —un ``T`` sin cota no promete nada—, ahora
        con la salida escrita: la cota que falta y como se declara."""
        self.ctx.error(SemanticError.UnboundedGenericMemberError(
            f"{what}, y '{param}' es un parametro de tipo que no promete "
            f"'{ref.written}': declara la cota ('<{param}: {ref.written}>')",
            line=ln, column=col,
        ))

    def _check_type_bounds(self, symbol: Symbol, args, ln: int,
                           col: int) -> None:
        """Las cotas de un TIPO generico usado en una anotacion o un literal
        (lo llama ``TypeBinder``): ``Arbol<Punto, int>`` con ``Arbol<K: Ord,
        V>`` es un error ahi mismo, no al usar el arbol."""
        declared = dict(symbol.type_bounds)
        # dentro de una FUNCION (su cuerpo o su firma), 'Ord' y 'Hash' que el
        # parametro no promete se comprueban POR INSTANCIA, como al llamar a
        # una funcion acotada (decision del mantenedor, A06). En la
        # declaracion de un struct o un enum no hay instancia de funcion que
        # lo decida: ahi sigue siendo SEM043.
        fn = self.ctx.current_fn or self._signature_fn
        for param, arg in zip(symbol.type_params, args):
            for ref in declared.get(param, ()):
                if _es_parametro_desnudo(arg, self._env_params):
                    if self._has_bound(arg.name, ref):
                        continue
                    if fn is not None and ref in (_ORD, _HASH):
                        self._note_per_instance(
                            "ordenes" if ref == _ORD else "hashes", arg,
                            f"'{symbol.name}<...>' pide '{param}: "
                            f"{ref.written}'", _Where(ln, col), fn)
                        continue
                    if not self._has_bound(arg.name, ref):
                        self._missing_bound(
                            arg.name, ref,
                            f"'{symbol.name}' pide '{param}: "
                            f"{bounds_text(declared[param])}'", ln, col)
                    continue
                failure = self._bound_failure(arg, ref)
                if failure is not None:
                    error_class, why = failure
                    self.ctx.error(error_class(
                        f"'{symbol.name}<...>' pide '{param}: "
                        f"{bounds_text(declared[param])}', y '{param}' es "
                        f"'{format_type(arg)}': {why}",
                        line=ln, column=col,
                    ))

    def _check_bounds(self, symbol: Symbol, mapa: dict, node, name: str,
                      origins: dict) -> None:
        """Las cotas de un GENERICO instanciado en una llamada, DESPUES de
        ligar (o deducir) sus argumentos de tipo. ``origins`` dice de donde
        salio cada uno que se dedujo ('el argumento 2', 'el receptor').

        Un argumento que es un parametro de tipo del llamador cumple lo que
        el llamador promete. Si no lo promete, ``Ord`` y ``Hash`` pasan a su
        comprobacion POR INSTANCIA (lo de siempre sin cota: un generico sin
        cota que ordena su ``T`` se sigue comprobando en cada instancia); lo
        demas es ``SEM043`` aqui, porque no hay instancia que lo arregle.
        """
        if not symbol.type_bounds or not mapa:
            return
        genericos = self._genericos()
        for param, refs in symbol.type_bounds:
            arg = mapa.get(param)
            if arg is None:
                continue
            for ref in refs:
                if _es_parametro_desnudo(arg, genericos):
                    if self._has_bound(arg.name, ref):
                        continue
                    asks = f"'{name}' pide '{param}: {ref.written}'"
                    if ref == _ORD:
                        self._note_per_instance("ordenes", arg, asks, node)
                    elif ref == _HASH:
                        self._note_per_instance("hashes", arg, asks, node)
                    else:
                        self._missing_bound(arg.name, ref, asks,
                                            node.ln, node.col)
                    continue
                failure = self._bound_failure(arg, ref)
                if failure is None:
                    continue
                error_class, why = failure
                origin = origins.get(param)
                if origin == _FROM_RECEIVER:
                    came = f"es '{format_type(arg)}' (el del receptor)"
                elif origin:
                    came = f"se dedujo como '{format_type(arg)}' desde {origin}"
                else:
                    came = f"es '{format_type(arg)}'"
                self.ctx.error(error_class(
                    f"'{name}' pide '{param}: {bounds_text(refs)}', y "
                    f"'{param}' {came}: {why}",
                    line=node.ln, column=node.col,
                ))

    def _bound_methods(self, param: str, member: str) -> list:
        """``[(BoundRef, TraitSig)]``: los metodos ``member`` que prometen los
        traits de las cotas de ``param``. Un trait se busca en este archivo:
        una cota solo puede nombrar uno de aqui (ver ``bounds``)."""
        found = []
        for ref in self._bound_env.get(param, ()):
            if ref.kind != _bounds.TRAIT:
                continue
            for sig in self.ctx.table.traits.get(ref.written, ()):
                if sig.name == member and sig.params \
                        and _menciona_self(sig.params[0]):
                    found.append((ref, sig))
        return found

    def _call_on_bounded_param(self, node: ast.Call, callee: ast.MemberAccess,
                               obj_type: Type, arg_types: list):
        """``x.metodo(...)`` con ``x: T`` (o ``T ptr``) y ``T`` con cotas.

        Lo que prometen las cotas se puede pedir: el ``print`` de ``Print`` y
        cada metodo de un trait (dunder o de ``@impl``), comprobado aqui, en
        la DEFINICION, con la firma del trait (``self`` -> ``T``). Quien lo
        ejecuta lo despacha por el tipo que ``T`` tenga en esa instancia; el
        HIR lo dice con un ``HookRef`` cuyo dueño es el parametro (``T``),
        igual que ``hash(x)``. Devuelve ``_NOT_BOUND`` si ninguna cota lo
        promete (entonces es ``SEM043``, como sin cota)."""
        param = _core(obj_type).name
        member = callee.member
        if member == "print" and not node.args \
                and self._has_bound(param, _PRINT):
            node.hook = _bound_print(param)
            return _VOID
        found = self._bound_methods(param, member)
        if not found:
            return _NOT_BOUND
        firmas = {(sig.params, sig.ret) for _ref, sig in found}
        if len(firmas) > 1:
            names = ", ".join(sorted({ref.written for ref, _sig in found}))
            self.ctx.error(SemanticError.TraitNotSatisfiedError(
                f"'{member}' sobre un '{param}' lo piden varios traits de sus "
                f"cotas ({names}) con firmas distintas: ningun tipo puede "
                "cumplirlos a la vez",
                line=node.ln, column=node.col,
            ))
            return None
        _ref, sig = found[0]
        me = nominal(param)
        expected = tuple(_traits.subst_self(p, me) for p in sig.params)
        result = _traits.subst_self(sig.ret, me) if sig.ret is not None else _VOID
        receiver = expected[0]
        if _es_puntero(receiver) and receiver.mut:
            self._check_writable(
                callee.obj, f"llamar a '{_texto_de(callee.obj)}.{member}(...)', "
                "que modifica su receptor (lo declara "
                f"'{format_type(receiver)}'),", node)
        self._mark_function_args(node, expected[1:])
        self._check_args(f"{param}.{member}", node, expected[1:], arg_types)
        node.hook = Symbol(name=member, kind=SymbolKind.DUNDER, ln=0, col=0,
                           type=result, param_types=expected,
                           hook_owner=param)
        return result

    def _symbol_env(self, symbol: Symbol) -> Dict[str, frozenset]:
        """El entorno de cotas de una funcion vista por su Symbol (para la
        propagacion de :meth:`verificar_copias`, que no tiene su AST)."""
        receiver = symbol.param_types[0] if symbol.param_types else None
        return self._bound_env_for(symbol, receiver)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _check_call(self, symbol: Symbol, node: ast.Call,
                    arg_types: list[Optional[Type]]) -> Optional[Type]:
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
            return symbol.type
        self._mark_function_args(
            node, expected,
            "host" if symbol.prototype else
            "variant" if symbol.kind is SymbolKind.ENUM_ITEM else "")
        # GENERICO: 'make<int>(4)' o 'primero(1)'. La firma esta escrita con
        # los parametros de tipo sin ligar ('T'), asi que antes de comparar
        # nada hay que sustituirlos. Es la misma operacion que hace un literal
        # de struct generico, con el mismo servicio.
        mapa, origins, failed = self._ligar_generico(symbol, node, arg_types)
        if failed:
            # la deduccion fallo (dos argumentos dan tipos distintos, AST007
            # ya dicho): sin mapa no hay firma con la que comparar nada mas
            # que la aridad
            if len(node.args) != len(expected):
                self.ctx.error(SemanticError.CallArityError(
                    f"'{symbol.name}' espera {len(expected)} argumento(s), "
                    f"recibe {len(node.args)}",
                    line=node.ln, column=node.col,
                ))
            return None
        unbound = self._missing_type_arguments(symbol, node, mapa)
        if unbound:
            return self._check_partial_call(symbol, node, mapa, unbound,
                                            arg_types)
        # el RETORNO se sustituye igual que los parametros: 'make<int>(4)'
        # produce un 'Vector<int>', no un 'Vector<T>'. Sin esto la llamada
        # entregaria un tipo con una 'T' sin ligar y nada unificaria con el.
        retorno = type_service.substitute(symbol.type, mapa) if mapa \
            else symbol.type
        if mapa:
            expected = tuple(type_service.substitute(t, mapa) for t in expected)
            # las COTAS, despues de ligar: el error dice desde que argumento
            # se dedujo el tipo que no las cumple
            self._check_bounds(symbol, mapa, node, _call_name(node, symbol),
                               origins)
            self._instancia(symbol, mapa, node)
        self._check_args(symbol.name, node, expected, arg_types)
        return retorno

    def _missing_type_arguments(self, symbol: Symbol, node: ast.Call,
                                mapa: dict) -> frozenset:
        """Los parametros de tipo que la llamada NO escribio ni se dedujeron,
        si la firma habla de ellos (en un parametro o en el retorno).

        Vacio si no falta nada: la llamada los escribio (``make<int>(4)``;
        si escribio otro numero, ``SEM027`` ya lo dijo) o se dedujeron todos
        de los argumentos (``primero(1)``, ``func.map(&v, f)``)."""
        if not symbol.type_params or node.type_args:
            return frozenset()
        unbound = frozenset(p for p in symbol.type_params if p not in mapa)
        if not unbound:
            return frozenset()
        firma = tuple(symbol.param_types or ()) + (symbol.type,)
        if not any(type_service.mentions_param(t, unbound) for t in firma):
            return frozenset()
        return unbound

    def _check_partial_call(self, symbol: Symbol, node: ast.Call, mapa: dict,
                            unbound: frozenset,
                            arg_types: list) -> Optional[Type]:
        """Faltan argumentos de tipo que no se pueden deducir (AST007).

        Antes la firma se comparaba con sus ``T`` sin ligar y salia un
        ``AST006`` por argumento ("se esperaba 'vector.Vector<T> ptr'") mas
        otro al usar el resultado: tres errores que no decian lo que faltaba.
        Ahora sale UNO, en la llamada, con lo que no se pudo deducir y por
        que (un parametro que solo aparece en el retorno, uno del que solo
        llega un ``null``, un argumento con otra forma). Los argumentos que
        no dependen de lo que falta se siguen comprobando."""
        name = _call_name(node, symbol)
        params = symbol.param_types or ()
        reasons = [self._undeduced_reason(param, params, symbol.type, node,
                                          arg_types)
                   for param in sorted(unbound, key=symbol.type_params.index)]
        written = ", ".join(format_type(mapa[p]) if p in mapa else p
                            for p in symbol.type_params)
        self.ctx.error(ASTError.CannotInferTypeError(
            f"no se pueden deducir los argumentos de tipo de '{name}' "
            f"(<{', '.join(symbol.type_params)}>): {'; '.join(reasons)}. "
            f"Escribelos TODOS en la llamada: '{name}<{written}>(...)' con los "
            f"tipos concretos. {_DEDUCTION_RULE}",
            line=node.ln, column=node.col,
        ))
        if len(node.args) != len(params):
            self.ctx.error(SemanticError.CallArityError(
                f"'{symbol.name}' espera {len(params)} argumento(s), "
                f"recibe {len(node.args)}",
                line=node.ln, column=node.col,
            ))
            return None
        known = frozenset(i for i, t in enumerate(params)
                          if not type_service.mentions_param(t, unbound))
        expected = tuple(type_service.substitute(t, mapa) if mapa else t
                         for t in params)
        self._check_args(symbol.name, node, expected, arg_types, only=known)
        if type_service.mentions_param(symbol.type, unbound):
            return None
        return type_service.substitute(symbol.type, mapa) if mapa \
            else symbol.type

    def _bind_method_params(self, method: Symbol, node: ast.Call, mapa: dict,
                            origins: dict, arg_types: list,
                            name: str) -> bool:
        """Los parametros de tipo PROPIOS de un metodo generico (``fn
        map<U>(...)`` dentro de ``@impl Caja<T>``): escritos
        (``c.map<str>(f)``) o deducidos de los argumentos, con las mismas
        reglas que una funcion. Los del tipo (``T``) ya los dio el receptor.

        Completa ``mapa``/``origins`` en sitio. ``False`` si la deduccion
        fallo (``AST007`` ya dicho). Si falta alguno que no se pudo deducir
        lo dice ``AST007`` aqui y la llamada sigue con lo que se sabe (sus
        argumentos se comparan solo donde no dependen de el)."""
        own = method.type_params
        written = self.types.bind_call(node, method)
        if not own:
            return True     # 'v.push<int>(1)' ya es SEM027 (no es generico)
        if written:
            mapa.update(zip(own, written))
            return True
        declared = tuple(method.param_types or ())[1:]
        deduced, deduced_origins, failed = self._deduce(
            own, declared, node, arg_types, name)
        if failed:
            return False
        mapa.update(deduced)
        origins.update(deduced_origins)
        missing = [p for p in own if p not in mapa and (
            type_service.mentions_param(method.type, frozenset({p}))
            or any(type_service.mentions_param(t, frozenset({p}))
                   for t in declared))]
        if missing:
            reasons = [self._undeduced_reason(p, declared, method.type, node,
                                              arg_types) for p in missing]
            self.ctx.error(ASTError.CannotInferTypeError(
                f"no se pueden deducir los argumentos de tipo del metodo "
                f"'{name}' (<{', '.join(own)}>): {'; '.join(reasons)}. "
                f"Escribelos TODOS en la llamada: '{name}<...>(...)'. "
                f"{_DEDUCTION_RULE}",
                line=node.ln, column=node.col,
            ))
        return True

    def _check_method_args(self, name: str, node: ast.Call, method: Symbol,
                           declared: tuple, mapa: dict,
                           arg_types: list) -> None:
        """ARIDAD (``SEM008``) y TIPO (``AST006``) de los argumentos de
        ``x.metodo(...)``, sin el receptor.

        Antes una llamada a un metodo solo comprobaba la propiedad
        (``move``): ``v.push("hola")`` sobre un ``Vector<int>``,
        ``v.push(1, 2)`` o ``v.sort_by(f)`` con una ``f`` de otro tipo
        compilaban y fallaban (o no) al ejecutar.

        Conservador como el resto de la pasada: un parametro que nombra un
        parametro de tipo del dueño que el mapa NO liga (el receptor llego
        sin argumentos conocidos) no se compara, porque compararlo con su
        ``T`` crudo seria un falso positivo. La propiedad la sigue mirando
        el llamador (no se repite aqui)."""
        if len(node.args) != len(declared):
            self.ctx.error(SemanticError.CallArityError(
                f"'{name}' espera {len(declared)} argumento(s), "
                f"recibe {len(node.args)}",
                line=node.ln, column=node.col,
            ))
            return
        receptor = _core(method.param_types[0]) if method.param_types else None
        propios = {a.name for a in (receptor.args if receptor is not None
                                    and receptor.kind is TypeKind.NOMINAL
                                    else ())
                   if a.kind is TypeKind.NOMINAL and not a.args and a.name}
        # ...y los PROPIOS de un metodo generico que no se pudieron deducir
        propios |= set(method.type_params or ())
        sin_ligar = frozenset(propios - set(mapa or {}))
        for index, (arg, declarado, arg_type) in enumerate(
                zip(node.args, declared, arg_types), start=1):
            if type_service.mentions_param(declarado, sin_ligar):
                continue
            esperado = type_service.substitute(declarado, mapa) if mapa                 else declarado
            ln = getattr(arg, "ln", node.ln)
            col = getattr(arg, "col", node.col)
            if _is_null_literal(arg):
                if not type_service.unify_literal_null(esperado):
                    self.ctx.error(ASTError.TypeMismatchError(
                        f"argumento {index} de '{name}': 'null' no es "
                        f"asignable a '{esperado!r}' (no es nullable)",
                        line=ln, column=col,
                    ))
            elif not self._acepta_valor(
                    esperado, arg, arg_type,
                    lambda e, i=index - 1: node.args.__setitem__(i, e)):
                self.ctx.error(ASTError.TypeMismatchError(
                    f"argumento {index} de '{name}': se esperaba "
                    f"'{esperado!r}', se encontró '{arg_type!r}'"
                    f"{self._sugerencia(esperado, arg_type)}",
                    line=ln, column=col,
                ))

    def _check_args(self, name: str, node: ast.Call, expected,
                    arg_types: list, only: Optional[frozenset] = None) -> None:
        """Aridad y cada argumento contra su parametro, ya sustituido.

        La comparten la llamada directa y la llamada a traves de un VALOR
        funcion: es la misma pregunta, y que tuvieran dos respuestas es como
        un argumento con destructor acabaria pasando sin 'move' por una de
        las dos vias. ``only`` (indices desde 0) limita la comprobacion a esos
        argumentos: los demas dependen de un parametro de tipo sin ligar
        (``_check_partial_call``), y la aridad ya se comprobo."""
        if only is None and len(node.args) != len(expected):
            self.ctx.error(SemanticError.CallArityError(
                f"'{name}' espera {len(expected)} argumento(s), "
                f"recibe {len(node.args)}",
                line=node.ln, column=node.col,
            ))
            return
        for index, (arg, param_type, arg_type) in enumerate(
                zip(node.args, expected, arg_types), start=1):
            if only is not None and index - 1 not in only:
                continue
            ln = getattr(arg, "ln", node.ln)
            col = getattr(arg, "col", node.col)
            if _is_null_literal(arg):
                if not type_service.unify_literal_null(param_type):
                    self.ctx.error(ASTError.TypeMismatchError(
                        f"argumento {index} de '{name}': 'null' no es "
                        f"asignable a '{param_type!r}' (no es nullable)",
                        line=ln, column=col,
                    ))
            elif not self._acepta_valor(
                    param_type, arg, arg_type,
                    lambda e, i=index - 1: node.args.__setitem__(i, e)):
                self.ctx.error(ASTError.TypeMismatchError(
                    f"argumento {index} de '{name}': se esperaba "
                    f"'{param_type!r}', se encontró '{arg_type!r}'"
                    f"{self._sugerencia(param_type, arg_type)}",
                    line=ln, column=col,
                ))
            else:
                # 'param_type' ya esta SUSTITUIDO: un 'T' instanciado con un
                # tipo con destructor tambien exige 'move', y un temporal
                # pasado ahi ya tiene dueño. Sin esto, 'hace<R>(R{...})'
                # destruia el temporal al terminar la sentencia aunque el
                # generico lo hubiera guardado (y 'hace<R>(r)' dejaba DOS
                # dueños).
                self._argumento_transferido(name, index, arg, param_type)

    def _ligar_generico(self, symbol: Symbol, node: ast.Call,
                        arg_types: list):
        """Los parametros de tipo de ``symbol`` -> los tipos de ESTA llamada.

        Devuelve ``(mapa, origenes, fallo)``. Dos vias, y la escrita gana:
        si la llamada trae argumentos de tipo (``make<int>(4)``) se usan
        esos —todos: ``SEM027`` si no son tantos como parametros—; si no,
        se DEDUCEN de los argumentos (:meth:`_deduce`). ``origenes`` dice de
        que argumento salio cada uno, para el error de una cota. Un generico
        que no se puede deducir no se adivina: lo que falte lo dice
        ``AST007`` (:meth:`_check_partial_call`).
        """
        if not symbol.type_params:
            return {}, {}, False
        escritos = self.types.bind_call(node, symbol)
        if escritos:
            return dict(zip(symbol.type_params, escritos)), {}, False
        return self._deduce(symbol.type_params, symbol.param_types or (),
                            node, arg_types, _call_name(node, symbol))

    def _deduce(self, params, declared, node: ast.Call, arg_types: list,
                name: str):
        """DEDUCCION de argumentos de tipo: un subconjunto de la de los
        templates de C++ ([temp.deduct.call], ISO/IEC 14882).

        De cada argumento con tipo ``A`` contra su parametro ``P``, solo en
        las formas ``T``, ``T ptr``, ``T?``, ``Nombre<..T..>`` (tambien
        anidado) y ``fn(..T..) -> R``. Las reglas, y lo que se dejo fuera:

        - Sin conversiones: ``A`` tiene que tener la MISMA forma que ``P`` y
          lo que liga ``T`` sale tal cual. Un ``int`` no liga el ``T`` de un
          ``T?`` (seria convertirlo); un ``int ptr mutable`` si liga el de un
          ``T ptr`` con ``T=int``, porque la mutabilidad es del puntero y no
          de ``T`` —que pueda pasarse ahi lo decide despues la comprobacion
          de siempre—.
        - Dos argumentos que dan tipos distintos para el mismo ``T`` son un
          error (``AST007``): no se elige uno.
        - Contexto no deducido: un ``null`` no da tipo, y un parametro que
          solo aparece en el retorno no sale de ningun argumento.
        - No hay deduccion parcial: o se escriben todos o ninguno.

        Devuelve ``(mapa, origenes, fallo)``; ``fallo`` si hubo conflicto.
        """
        params = frozenset(params)
        mapa: dict = {}
        found_at: dict = {}
        for index, (formal, arg, real) in enumerate(
                zip(declared, node.args, arg_types), start=1):
            if formal is None or real is None or _is_null_literal(arg) \
                    or not type_service.mentions_param(formal, params):
                continue
            conflict = self._deduce_from(formal, real, params, mapa,
                                         found_at, index)
            if conflict is None:
                continue
            param, before, where, now = conflict
            self.ctx.error(ASTError.CannotInferTypeError(
                f"no se puede deducir '{param}' en '{name}': el argumento "
                f"{where} lo da como '{format_type(before)}' y el argumento "
                f"{index} como '{format_type(now)}'. Al deducir no hay "
                "conversiones: tienen que ser el MISMO tipo. Convierte uno, o "
                f"escribe los argumentos de tipo ('{name}<...>(...)')",
                line=node.ln, column=node.col,
            ))
            return mapa, {}, True
        origins = {p: f"el argumento {i}" for p, i in found_at.items()}
        return mapa, origins, False

    def _deduce_from(self, formal: Optional[Type], actual: Optional[Type],
                     params: frozenset, mapa: dict, found_at: dict,
                     index: int):
        """Recorre ``formal`` (``P``) y ``actual`` (``A``) a la vez y liga
        cada parametro de tipo que encuentra. Devuelve ``None``, o el
        conflicto ``(parametro, tipo anterior, argumento anterior, tipo
        nuevo)``. Una forma que no casa no deduce nada de ESTE argumento: si
        el parametro sale de otro, la comprobacion de siempre dira que este
        no encaja; si no sale de ninguno, ``AST007`` dira por que."""
        if formal is None or actual is None \
                or type_service.es_desconocido(actual):
            return None
        kind = formal.kind
        if kind is TypeKind.NOMINAL and not formal.args \
                and formal.name in params:
            before = mapa.get(formal.name)
            if before is None:
                mapa[formal.name] = actual
                found_at[formal.name] = index
                return None
            if before != actual:
                return formal.name, before, found_at[formal.name], actual
            return None
        if actual.kind is not kind:
            return None
        if kind in (TypeKind.POINTER, TypeKind.NULLABLE):
            return self._deduce_from(formal.inner, actual.inner, params, mapa,
                                     found_at, index)
        if kind is TypeKind.NOMINAL:
            if len(formal.args) != len(actual.args) \
                    or not self._same_nominal(formal, actual):
                return None
            pairs = list(zip(formal.args, actual.args))
        elif kind is TypeKind.FUNCTION:
            if len(formal.args) != len(actual.args):
                return None
            pairs = list(zip(formal.args, actual.args))
            pairs.append((formal.inner, actual.inner))
        else:
            return None
        for sub_formal, sub_actual in pairs:
            conflict = self._deduce_from(sub_formal, sub_actual, params, mapa,
                                         found_at, index)
            if conflict is not None:
                return conflict
        return None

    def _same_nominal(self, a: Type, b: Type) -> bool:
        """¿Dos nominales nombran el MISMO tipo? Por su nombre canonico: la
        firma de una libreria dice ``vector.Vector`` y el llamador puede
        haberlo escrito ``vec.Vector``."""
        if a.name == b.name:
            return True
        ca, cb = self._canonical(a), self._canonical(b)
        return ca is not None and cb is not None and ca.name == cb.name

    def _undeduced_reason(self, param: str, declared, ret: Optional[Type],
                          node: ast.Call, arg_types: list) -> str:
        """Por que ``param`` no se dedujo de esta llamada, para ``AST007``."""
        one = frozenset({param})
        uses = [(i, t) for i, t in enumerate(declared, start=1)
                if type_service.mentions_param(t, one)]
        if not uses:
            return (f"'{param}' solo aparece en el retorno "
                    f"('{format_type(ret)}'), y de ahi no se deduce")
        parts = []
        for index, formal in uses:
            if index > len(node.args):
                continue
            arg, real = node.args[index - 1], arg_types[index - 1]
            if _is_null_literal(arg):
                parts.append(f"del argumento {index} solo llega 'null'")
            elif real is None:
                parts.append(f"el argumento {index} no tiene un tipo conocido")
            else:
                parts.append(f"el argumento {index} es '{format_type(real)}' "
                             f"y su parametro '{format_type(formal)}' no tiene "
                             "esa forma")
        return f"'{param}': " + ("; ".join(parts) or "no sale de ningun argumento")

    # ------------------------------------------------------------------ #
    # literales y tipos numericos de libreria
    # ------------------------------------------------------------------ #
    def _acepta_valor(self, target: Optional[Type], expr,
                      value_type: Optional[Type], poner) -> bool:
        """¿El valor cabe en ``target``? Y si solo cabe tras una conversión de
        LITERAL declarada, la INSERTA (vía ``poner``) y responde que sí.

        Un solo punto para las cinco posiciones de escritura, porque la
        alternativa —repetir la regla en cada una— es exactamente cómo un
        enum acabó siendo asignable a ``int`` como argumento y no como
        inicializador.
        """
        if self._asignable(target, value_type):
            return True
        reemplazo = self._coercion_literal(target, expr, value_type)
        if reemplazo is None:
            return False
        poner(reemplazo)
        return True

    def _literal_a_byte(self, target: Type, expr):
        """Un literal entero donde se espera un ``byte``: si cabe (0..255) se
        envuelve en ``cast<byte>`` (el HIR lleva el tipo); si no, es un error
        con el rango. Como un tipo de ancho fijo: la conversion implicita
        exige que quepa, la explicita trunca."""
        literal = _valor_literal(expr)
        if literal is None or isinstance(literal, bool):
            return None
        if not (0 <= literal <= 255):
            self.ctx.error(ASTError.TypeMismatchError(
                f"el literal {literal} no cabe en 'byte' (rango [0, 255]); "
                "para truncarlo, 'cast<byte>(...)'",
                line=getattr(expr, "ln", 0), column=getattr(expr, "col", 0),
            ))
        return ast.CastExpr(ln=expr.ln, col=expr.col,
                            type=ast.PrimitiveTypeExpr(ln=expr.ln, col=expr.col,
                                                       name="byte"),
                            value=expr, restype=target,
                            azucar="un literal que cabe entra en un 'byte': cast implicito")

    def _coercion_literal(self, target: Optional[Type], expr,
                          value_type: Optional[Type]):
        """Un LITERAL escrito donde se espera un tipo numérico de librería.

        ``const dt.int8 a = 10;`` no compilaba: ``int8`` es un nominal opaco y
        ``10`` es un ``int``. Pero el tipo declara ``__cast__(int) -> int8`` y
        —desde ``__min__``/``__max__``— su RANGO, así que la pregunta "¿cabe
        el 10?" sí tiene respuesta en compilación. Si cabe, se envuelve el
        literal en la conversión declarada (el árbol queda igual que si se
        hubiera escrito ``cast<int8>(10)``); si no cabe, es un error que dice
        el rango.

        La asimetría con ``cast<T>(x)`` es deliberada y es la de Rust: la
        conversión IMPLÍCITA exige que quepa; la EXPLÍCITA trunca
        (``cast<dt.int8>(300)`` sigue valiendo 44). Son dos operaciones, no
        una laxa y una estricta.

        ``None`` si no aplica: sin literal, sin conversión declarada o sin
        rango publicado no se inventa nada — el llamador reporta lo suyo.
        """
        if target is not None and target.kind is TypeKind.BYTE:
            return self._literal_a_byte(target, expr)
        if target is None or target.kind is not TypeKind.NOMINAL:
            return None
        literal = _valor_literal(expr)
        if literal is None:
            return None
        canonico = self._canonical(target)
        if self.ctx.table.lookup_cast(value_type, canonico) is None:
            return None
        rango = self._rango_de(canonico)
        if rango is None:
            # el tipo convierte pero no publica su rango: no hay forma de
            # saber si el literal cabe, y aceptarlo seria truncar en silencio.
            return None
        bajo, alto = rango
        if not (bajo <= literal <= alto):
            self.ctx.error(ASTError.TypeMismatchError(
                f"el literal {literal} no cabe en '{target!r}' "
                f"(rango [{bajo}, {alto}])",
                line=getattr(expr, "ln", 0), column=getattr(expr, "col", 0),
            ))
        nodo = ast.CastExpr(ln=expr.ln, col=expr.col,
                            type=ast.NominalTypeExpr(ln=expr.ln, col=expr.col,
                                                     name=canonico.name),
                            value=expr, restype=canonico,
                            azucar=f"un literal que cabe entra en '{target!r}': "
                                   "su __cast__")
        nodo.hook = self.ctx.table.lookup_cast(value_type, canonico)
        return nodo

    def _rango_de(self, t: Optional[Type]):
        """``(min, max)`` que el tipo publica con ``__min__``/``__max__``.

        ``None`` si no los declara: un tipo sin rango publicado no admite
        literales sin convertir, y eso es lo correcto — el compilador sabe que
        ``int8`` mide un byte, pero un byte va de -128 a 127 o de 0 a 255 y la
        firma no dice cuál.
        """
        owner = _nominal_name(t)
        if owner is None:
            return None
        bajo = self.ctx.table.lookup_hook(owner, HookKind.MIN)
        alto = self.ctx.table.lookup_hook(owner, HookKind.MAX)
        if bajo is None or alto is None:
            return None
        if bajo.const_value is None or alto.const_value is None:
            return None
        return bajo.const_value, alto.const_value

    def _sugerencia(self, target: Optional[Type],
                    value_type: Optional[Type]) -> str:
        """Coletilla accionable cuando SÍ existe una conversión entre los dos.

        Un "no se puede asignar X a Y" es un callejón sin salida si el
        programa tiene la conversión declarada a un paso: lo que falta es
        escribirla.
        """
        if target is None or value_type is None:
            return ""
        canonico = self._canonical(target)
        if (value_type.kind, target.kind) in _NATIVE_CASTS \
                or self.ctx.table.lookup_cast(self._canonical(value_type),
                                              canonico) is not None:
            return (f"; existe la conversión '{value_type!r} -> {target!r}': "
                    f"envuelve el valor en "
                    f"'cast<{self._como_se_escribe(canonico)}>(...)'")
        return ""

    def _como_se_escribe(self, t: Optional[Type]) -> str:
        """El tipo tal como se puede NOMBRAR desde el scope actual.

        Un tipo de librería tiene dos nombres: el CANÓNICO, que lo identifica
        sin ambigüedad en todo el programa (``dt_variables.float32``), y el
        que se puede ESCRIBIR desde aquí, que depende de cómo se importara
        (``dt.float32``). Los diagnósticos internos usan el primero, pero una
        sugerencia necesita el segundo — decirle a alguien que escriba
        ``cast<dt_variables.float32>(...)`` cuando en su archivo ese nombre no
        existe es mandarlo a un segundo error.

        Se busca el import que publica el tipo, y se COMPRUEBA que el alias
        encontrado lleve de vuelta al mismo tipo: desde que dos librerías
        pueden declarar un ``Node``, encontrar un miembro con ese nombre no
        basta para saber que es este. Si no aparece ninguno se devuelve el
        canónico, que es lo mejor que se sabe.
        """
        if t is None or t.kind is not TypeKind.NOMINAL:
            return repr(t)
        if type_service.lookup_type_path(t.name, self.ctx.scope).status \
                is type_service.TypeLookup.OK:
            return repr(t)
        hoja = (t.name or "").rsplit(".", 1)[-1]
        scope = self.ctx.scope
        while scope is not None:
            for alias, symbol in scope.values.items():
                if symbol.kind is not SymbolKind.IMPORT or not symbol.members:
                    continue
                miembro = symbol.members.get(hoja)
                if miembro is None:
                    continue
                if type_service.canonical_name(miembro, hoja) == t.name:
                    return f"{alias}.{hoja}"
            scope = scope.parent
        return repr(t)

    def _asignable(self, target: Optional[Type],
                   value: Optional[Type]) -> bool:
        """¿Un valor de tipo ``value`` cabe en un destino de tipo ``target``?

        Delega en ``type_service.is_assignable`` y añade la única regla que
        esta pasada necesita y que ``is_assignable`` no puede ver sin la tabla
        de símbolos: un valor de ENUM es asignable a ``int`` (los items de un
        enum son enteros, estilo C — ver ``test_enum_y_match``).

        Lo usan las CUATRO posiciones de escritura —init, asignación, campo y
        argumento— porque son la misma pregunta: que cada una tuviera su
        propia respuesta era la razón de que un enum se pudiera pasar a un
        ``int`` como argumento y no inicializar uno.
        """
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


#: hook SINTETICO del 'len' nativo de 'str'. No lo declara nadie: existe para
#: que la llamada viaje al HIR por el MISMO camino que cualquier otro
#: '__len__' (una HookRef con dueño), en vez de que el consumidor tenga que
#: reconocer el NOMBRE 'len' en runtime. El dueño 'str' es lo que la marca.
_LEN_DE_STR = Symbol(name="__len__", kind=SymbolKind.HOOK, ln=0, col=0,
                     type=_INT, hook_kind=HookKind.LEN, hook_owner="str")


#: los conceptos nativos como cota resuelta (ver 'bounds')
_EQ = BoundRef(_bounds.CONCEPT, "Eq")
_ORD = BoundRef(_bounds.CONCEPT, "Ord")
_HASH = BoundRef(_bounds.CONCEPT, "Hash")
_PRINT = BoundRef(_bounds.CONCEPT, "Print")

#: los primitivos que cumplen 'Print': dentro de un generico, 'print(x)' los
#: escribe como los escribe un f-string (sin salto de linea)
#: los nombres con que otros lenguajes piden la longitud ('s.len()' en Rust,
#: 's.length' en JS, 's.size()' en C++): la pista es 'len(s)'
_LENGTH_NAMES = frozenset({"len", "length", "size", "count"})

_PRINTABLE_PRIMITIVES = frozenset({
    TypeKind.INT, TypeKind.FLOAT, TypeKind.BOOL, TypeKind.CHAR, TypeKind.STR,
    TypeKind.BYTE,
})

#: lo que devuelve '_call_on_bounded_param' cuando ninguna cota lo promete
_NOT_BOUND = object()

#: origen de un argumento de tipo que no se dedujo: lo dio el receptor
#: ('v.sort()' sobre un 'Vector<P>')
_FROM_RECEIVER = "receptor"

#: la lista por instancia de 'verificar_copias' que una cota hace innecesaria
_CONCEPT_OF_LIST = {"ordenes": _ORD, "hashes": _HASH}

#: la regla de la deduccion, tal como la cita AST007
_DEDUCTION_RULE = (
    "Un argumento de tipo se deduce de un argumento cuyo parametro es 'T', "
    "'T ptr', 'T?', 'Nombre<..T..>' o 'fn(..T..) -> R', con el tipo identico "
    "(sin conversiones); no de un 'null' ni del retorno")


#: parametro que la llamada nunca llego a comparar con un argumento (una
#: variante, un hook, un 'print'): no se sabe si es de tipo funcion
_UNKNOWN_PARAM = object()


def _read_only_view(t: Optional[Type]) -> Optional[Type]:
    """El tipo con el que una lambda VE lo que captura: un ``ptr mutable``
    (tambien dentro de un ``?``) pasa a ``ptr``. Lo capturado se lee; la
    mutabilidad de un puntero puede perderse, nunca ganarse."""
    if t is None:
        return None
    if t.kind is TypeKind.POINTER and t.mut:
        return pointer_of(t.inner, mut=False)
    if t.kind is TypeKind.NULLABLE and t.inner is not None \
            and t.inner.kind is TypeKind.POINTER and t.inner.mut:
        return dataclasses.replace(t, inner=pointer_of(t.inner.inner, mut=False))
    return t


def _captured_reason(name: str, frame) -> str:
    """El porque comun de lo que una lambda no puede hacer con lo capturado."""
    return (f"'{name}' lo captura la lambda de la linea {frame.node.ln}, y una "
            "lambda solo LEE lo que captura (no lo asigna, no lo mueve, no lo "
            "libera, no lo modifica ni escribe a traves de el). Si hace falta "
            "cambiarlo, hazlo fuera de la lambda con lo que ella devuelve, o "
            "usa una funcion con nombre que lo reciba como 'ptr mutable'")


def _call_name(node: ast.Call, symbol: Symbol) -> str:
    """El nombre de lo llamado tal como se escribio (``func.map``), para
    los mensajes; el del simbolo si el callee no es un nombre."""
    if isinstance(node.callee, (ast.Identifier, ast.MemberAccess)):
        return _texto_de_nombre(node.callee) or symbol.name
    return symbol.name


def _print_of_primitive(t: Type) -> Symbol:
    """El ``HookRef`` de ``print(x)`` con ``x`` un PRIMITIVO: el dueño es el
    primitivo (``int``) y no hay cuerpo que llamar. Cada motor lo escribe
    como un f-string escribe ``{x}``, sin salto de linea."""
    return Symbol(name="__print__", kind=SymbolKind.HOOK, ln=0, col=0,
                  type=_VOID, hook_kind=HookKind.PRINT,
                  hook_owner=format_type(t))


def _bound_print(param: str) -> Symbol:
    """El ``HookRef`` de ``print(x)`` con ``x: T`` y ``T: Print``: el dueño es
    el PARAMETRO, y cada motor lo despacha con el tipo de la instancia."""
    return Symbol(name="__print__", kind=SymbolKind.HOOK, ln=0, col=0,
                  type=_VOID, hook_kind=HookKind.PRINT, hook_owner=param)


def _menciona_self(t: Optional[Type]) -> bool:
    """¿El tipo es o envuelve el placeholder ``self`` de un trait?"""
    while t is not None:
        if t.kind is TypeKind.SELF:
            return True
        t = t.inner
    return False


def _leaf_igual(a: Optional[str], b: Optional[str]) -> bool:
    """¿Dos nombres nominales nombran el mismo tipo, salvo calificacion?"""
    if a is None or b is None:
        return False
    return a.rsplit(".", 1)[-1] == b.rsplit(".", 1)[-1]


def _kind_text(symbol: Symbol) -> str:
    """Como se llama, para un mensaje, la clase de un simbolo."""
    return {
        SymbolKind.IMPORT: "un modulo",
        SymbolKind.ENUM_ITEM: "un item de enum sin datos (un valor, no un "
                              "constructor)",
        SymbolKind.TYPE: "un tipo",
        SymbolKind.STRUCT: "un tipo",
        SymbolKind.ENUM: "un tipo",
    }.get(symbol.kind, f"un {symbol.kind.name.lower()}")


def _es_puntero(t: Optional[Type]) -> bool:
    """``ptr T`` o ``ptr T?``: un préstamo, cuyo contenido no es propio."""
    while t is not None and t.kind is TypeKind.NULLABLE:
        t = t.inner
    return t is not None and t.kind is TypeKind.POINTER


def _pointer_core(t: Optional[Type]) -> Optional[Type]:
    """El ``POINTER`` de ``t`` (``C ptr`` o ``C ptr?``), o ``None``."""
    while t is not None and t.kind is TypeKind.NULLABLE:
        t = t.inner
    return t if t is not None and t.kind is TypeKind.POINTER else None


def _es_nombre(expr) -> bool:
    """¿``expr`` es un nombre simple o cualificado (``a`` / ``dt.int8``)?"""
    return _texto_de_nombre(expr) is not None


def _nombres_liberados(block) -> set:
    """Los campos que algun ``free`` del cuerpo nombra ('c.r' -> 'r').

    Recorre los bloques anidados: un destructor puede soltar bajo un ``if``.
    """
    salida: set = set()
    if block is None:
        return salida
    for stmt in getattr(block, "statements", ()):
        if isinstance(stmt, ast.FreeStmt):
            objetivo = stmt.target
            if isinstance(objetivo, ast.AddrOf):
                objetivo = objetivo.operand
            escrito = _texto_de_nombre(objetivo)
            if escrito:
                salida.add(escrito.rsplit(".", 1)[-1])
        elif isinstance(stmt, ast.Block):
            salida |= _nombres_liberados(stmt)
        elif isinstance(stmt, ast.IfStmt):
            # el 'else' (y la cadena de 'else if'). Antes se buscaba en un
            # campo que no existe ('else_block'): un 'free' dentro de un
            # 'else' no contaba y salia un NOTE002 falso
            rama = stmt
            while isinstance(rama, ast.IfStmt):
                salida |= _nombres_liberados(rama.then_block)
                rama = rama.else_branch
            if rama is not None:
                salida |= _nombres_liberados(rama)
        elif isinstance(stmt, ast.WhileStmt):
            salida |= _nombres_liberados(stmt.body)
    return salida


def _texto_de_nombre(expr) -> Optional[str]:
    """El nombre escrito, con sus puntos; ``None`` si no es un nombre."""
    if isinstance(expr, ast.Identifier):
        return expr.name
    if isinstance(expr, ast.MemberAccess):
        base = _texto_de_nombre(expr.obj)
        return f"{base}.{expr.member}" if base is not None else None
    return None


def _valor_literal(expr) -> Optional[int]:
    """El entero que escribe un literal, con el signo unario opcional.

    Solo ENTEROS: un flotante no tiene un "cabe/no cabe" que se pueda decidir
    con dos cotas enteras (el redondeo IEEE no es un recorte de rango), asi
    que no entra en la coercion.
    """
    signo = 1
    if isinstance(expr, ast.UnaryOp) and expr.operator == "-":
        signo, expr = -1, expr.operand
    if isinstance(expr, ast.Literal) and expr.literal_kind == "int":
        return signo * expr.value
    return None


def _optional_content(t: Optional[Type]) -> Optional[Type]:
    """El ``T`` de un sujeto ``T?`` (``error T?`` incluido: el error es
    transparente en la ruta de exito), o ``None`` si el sujeto no es un
    opcional. Un PUNTERO a un ``T?`` (``T? ptr``) no cuenta: el ``match``
    lo desreferencia y compara como siempre."""
    while t is not None and t.kind is TypeKind.ERROR and t.inner is not None:
        t = t.inner
    if t is None or t.kind is not TypeKind.NULLABLE:
        return None
    return t.inner


def _is_null_literal(expr: ast.Expression) -> bool:
    return isinstance(expr, ast.Literal) and expr.literal_kind == "null"


def _es_parametro_desnudo(t: Optional[Type], genericos) -> bool:
    """¿``t`` ES uno de los parametros de tipo ``genericos`` (``T``, no
    ``Caja<T>`` ni ``T ptr``)?"""
    return t is not None and t.kind is TypeKind.NOMINAL and not t.args \
        and t.name in genericos


def _es_parametro_de_tipo(declarado: Optional[Type], type_params) -> bool:
    """¿El tipo DECLARADO de un parametro es un parametro de tipo (``T``)?"""
    return (declarado is not None and declarado.kind is TypeKind.NOMINAL
            and declarado.name in (type_params or ()))


def _texto_de(expr) -> str:
    """El fuente de un nombre, campo o elemento, para citarlo en un mensaje."""
    if isinstance(expr, ast.Identifier):
        return expr.name
    if isinstance(expr, ast.MemberAccess):
        return f"{_texto_de(expr.obj)}.{expr.member}"
    if isinstance(expr, ast.Index):
        return f"{_texto_de(expr.obj)}[...]"
    if isinstance(expr, ast.Call):
        return f"{_texto_de(expr.callee)}(...)"
    return "el argumento"


def _mapa_por_receptor(metodo: Symbol, receptor: Optional[Type]) -> dict:
    """``parametro -> argumento`` leyendo el RECEPTOR declarado del metodo.

    ``_sustitucion`` saca el mapa del SIMBOLO del tipo, y eso funciona
    mientras el tipo se pueda resolver por su nombre. Desde el consumidor de
    una libreria no se puede: el tipo llega canonicalizado (``Vector``) y en
    ese scope lo unico que resuelve es el cualificado (``vec.Vector``), asi
    que un metodo de un generico de libreria devolvia su ``T`` sin ligar.

    El metodo, en cambio, SI dice de que parametros habla: su primer
    parametro es ``Vector<T> ptr mutable self``, y esa ``T`` es el nombre a
    ligar. Se emparejan por posicion con los argumentos del receptor real.
    """
    if receptor is None or not receptor.args or not metodo.param_types:
        return {}
    declarado = _core(metodo.param_types[0])
    if declarado is None or len(declarado.args) != len(receptor.args):
        return {}
    return {p.name: real for p, real in zip(declarado.args, receptor.args)
            if p.kind is TypeKind.NOMINAL and p.name}


def _entero_literal(expr) -> Optional[int]:
    """El valor de ``expr`` si es un literal entero escrito; ``None`` si no.

    Deliberadamente literal: ``v[N]`` con ``N`` una constante ya declarada NO
    cuenta. Resolverla exigiria evaluar en compilacion, y el unico caso que
    esta comprobacion promete cubrir es el que se ve leyendo.
    """
    if isinstance(expr, ast.Literal) and isinstance(expr.value, int) \
            and not isinstance(expr.value, bool):
        return expr.value
    return None


def _push_sobre(stmt) -> Optional[str]:
    """El nombre de la variable de un ``v.push(x);`` suelto, o ``None``."""
    if not isinstance(stmt, ast.ExprStmt):
        return None
    call = stmt.expr
    if not isinstance(call, ast.Call):
        return None
    callee = call.callee
    if not isinstance(callee, ast.MemberAccess) or callee.member != "push":
        return None
    return callee.obj.name if isinstance(callee.obj, ast.Identifier) else None


def _core(t: Optional[Type]) -> Optional[Type]:
    """El nominal 'nucleo' de ``t``, desenvolviendo ``ptr``/``?``. Es donde
    viven los argumentos de tipo de un generico."""
    while t is not None and (t.kind is TypeKind.POINTER
                             or t.kind is TypeKind.NULLABLE):
        t = t.inner
    return t


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


def _print_statement(arg, ln: int, col: int) -> ast.ExprStmt:
    """``print(arg);`` con la posicion del argumento: una pieza de un
    ``print`` variadico (ver ``_ScopeResolver._variadic_print``). La
    posicion es la del argumento, para que un error de ``Print`` senale
    CUAL de ellos no se puede escribir."""
    callee = ast.Identifier(ln=ln, col=col, name="print")
    return ast.ExprStmt(ln=ln, col=col,
                        expr=ast.Call(ln=ln, col=col, callee=callee,
                                      args=[arg]))


class _Where:
    """Una posicion sin nodo (``ln``/``col``), para anotar lo que pide una
    anotacion de tipo: ``TypeBinder`` da la posicion, no el nodo."""
    __slots__ = ("ln", "col")

    def __init__(self, ln: int, col: int) -> None:
        self.ln = ln
        self.col = col
