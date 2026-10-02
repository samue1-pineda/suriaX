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

import os
from typing import Callable, Dict, List, Optional

try:
    from include import ast_nodes as ast
    from include.types_ast import (META_TYPE, PRIMITIVE_TYPES, Type, TypeKind,
                                   is_meta, nominal, pointer_of)
    from error_handler import ASTError, SemanticError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from types_ast import (META_TYPE, PRIMITIVE_TYPES, Type,  # type: ignore
                           TypeKind, is_meta, nominal, pointer_of)
    import ASTError  # type: ignore
    import SemanticError  # type: ignore

from . import collect, type_service
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
    for item in program.items:
        if isinstance(item, ast.DecoratorDecl):
            item = item.target
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
        # enum/directivas: sus items no llevan tipos escritos por el usuario
    # con TODOS los cuerpos vistos: que copia cada generico y que instancia
    # copiaria un valor con destructor (SEM038)
    resolver.verificar_copias()


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


class _ScopeResolver:
    __slots__ = ("ctx", "locals", "types", "_stmt_dispatch", "_expr_dispatch",
                 "_del_patron")

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
            ast.Call: self._expr_call,
            ast.Index: self._expr_index,
            ast.MemberAccess: self._expr_member,
            ast.SizeofExpr: self._expr_sizeof,
            ast.CastExpr: self._expr_cast,
            ast.MoveExpr: self._expr_move,
            ast.StructLiteral: self._expr_struct_literal,
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
        for p in fn.params:
            self.types.bind(p)
        self.types.bind_return(fn)
        self._firma_canonica(fn)

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
        for stmt in fn.body.statements:
            self.visit_stmt(stmt)
        # el cuerpo comparte el scope FUNCTION, asi que sus drops -- y la
        # cuenta de capacidad -- se hacen aqui y no en '_stmt_block' (que
        # nunca lo visita).
        self._capacidad_desbordada(fn.body.statements)
        self._campos_sin_soltar(fn)
        self._anotar_drops(fn.body)
        self._pop_scope()

        ctx.current_fn = None
        self.locals = None

    def bind_struct(self, node: ast.StructDecl) -> None:
        """Valida los tipos de los campos de un ``struct``.

        No hay cuerpo que recorrer, pero sus campos SI llevan anotaciones del
        usuario; cuando esto era una pasada aparte las alcanzaba su recorrido
        plano.
        """
        for field in node.fields:
            self.types.bind(field)
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
        for item in node.items:
            for indice, tipo in enumerate(item.payload_restypes):
                self._bind_payload(node, item, indice, tipo)
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
        for stmt in test.body.statements:
            self.visit_stmt(stmt)
        self._pop_scope()
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

    def _stmt_noop(self, stmt) -> None:
        pass  # break/continue: posicion ya validada por el parser

    def _stmt_block(self, node: ast.Block) -> None:
        self.ctx.push_scope(ScopeKind.BLOCK, f"bloque @{node.ln}")
        for stmt in node.statements:
            self.visit_stmt(stmt)
        self._capacidad_desbordada(node.statements)
        self._anotar_drops(node)
        self._pop_scope()

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
        fn = self.ctx.current_fn
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
        symbol = self._nominal_symbol(t)
        if symbol is None:
            return None
        return (self.ctx.table.lookup_hook(symbol.name, HookKind.FREE)
                or self.ctx.table.lookup_hook(
                    type_service.canonical_name(symbol, t.name if t else ""),
                    HookKind.FREE))

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

    def _check_var_init(self, node: ast.VarDecl) -> None:
        if node.inferido:
            # el guardian sin nombre de un 'with': su tipo es el de su valor
            node.restype = self.visit_expr(node.value)
            self._tiene_dueno(node.value)
            return
        # el tipo escrito se valida y canonicaliza PRIMERO: la comparacion de
        # abajo usa 'node.restype', y 'point.Point' y 'Point' son nominales
        # distintos que nunca unificarian.
        self.types.bind(node)
        if node.value is None:
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

    def _stmt_match(self, node: ast.MatchStmt) -> None:
        subject_type = self.visit_expr(node.subject)
        for arm in node.cases:
            self._stmt_case_arm(arm)
        self._match_exhaustivo(node, subject_type)

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
        variante = (self._variante_nombrada(node.pattern.callee)
                    if isinstance(node.pattern, ast.Call) else None)
        if variante is None:
            self.visit_expr(node.pattern)
            self.visit_stmt(node.body)
            return
        self.ctx.push_scope(ScopeKind.BLOCK, f"case @{node.ln}")
        self._ligar_payload(node.pattern, variante)
        self.visit_stmt(node.body)
        self._pop_scope()

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
            simbolo = Symbol(name=arg.name, kind=SymbolKind.VAR, ln=arg.ln,
                             col=arg.col, type=tipo, mutable=False)
            self._del_patron.add(id(simbolo))
            self.ctx.scope.define_value(simbolo)
            if self.locals is not None:
                self.locals[arg.name] = simbolo
            arg.restype = tipo

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
        if isinstance(callee, ast.MemberAccess):
            base = self._enum_por_ruta(callee.obj)
            if base is not None and base.members:
                simbolo = base.members.get(callee.member)
        elif isinstance(callee, ast.Identifier):
            simbolo = self.ctx.scope.resolve_value(callee.name)
        if simbolo is not None and simbolo.kind is SymbolKind.ENUM_ITEM \
                and simbolo.param_types:
            return simbolo
        return None

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
        self._tiene_dueno(node.value)   # el valor pasa al llamador
        # ...y si POSEE recursos, quien lo tenia deja de ser su dueno: sin
        # esto el drop del bloque destruiria lo que el llamador acaba de
        # recibir. Solo cuando posee: devolver un 'int' no transfiere nada.
        node.transfers = type_service.owns_resources(
            value_type, self.ctx.scope, self.ctx.table)
        genericos = self._genericos()
        if genericos and not _es_puntero(value_type)                 and type_service.mentions_param(value_type, genericos):
            # un 'T' se destruye por su tipo al cerrar el ambito: devolverlo
            # lo cede igual, o se destruiria lo que el llamador recibe
            node.transfers = True
        self._no_cede_un_prestamo(node.value, value_type, "return")
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
        self._no_cede_un_prestamo(node.target, tipo, "move")

    def _expr_move(self, node: ast.MoveExpr) -> Optional[Type]:
        """``move x`` como EXPRESION: el tipo es el del origen.

        El valor se lleva entero, así que quien lo recibe se queda con él y el
        ámbito de origen ya no lo destruye — por eso además deja de ser un
        temporal: su dueño es el destino, no la sentencia."""
        tipo = self.visit_expr(node.operand)
        self._tiene_dueno(node.operand)
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
            return expr.name if self._es_del_patron(expr.name) else None
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
                    and (_es_puntero(simbolo.type) or id(simbolo) in self._del_patron):
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
                f"(se requiere 'ptr T'): toma su direccion, {como}",
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
        self.ctx.scope.define_value(symbol)
        if self.locals is not None:
            self.locals[node.name] = symbol
        for stmt in node.block.statements:
            self.visit_stmt(stmt)
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
        return symbol.type

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
                self.ctx.error(SemanticError.InvalidAddressOfError(
                    f"'&' sobre la funcion '{operand.name}': suriaX no tiene "
                    "tipos funcion todavia, asi que una funcion no tiene "
                    "direccion que tomar. Para elegir entre varias en "
                    "ejecucion, usa un 'enum' y un 'match'",
                    line=node.ln, column=node.col,
                ))
                return None
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
        tipo propio y no se rechaza. Ordenar ('<', '>'...) solo tiene sentido
        entre numeros, caracteres y cadenas."""
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
        if a.kind not in (TypeKind.INT, TypeKind.FLOAT, TypeKind.CHAR, TypeKind.STR,
                          TypeKind.BYTE):
            self.ctx.error(ASTError.TypeMismatchError(
                f"'{node.operator}' no ordena valores de tipo '{left!r}': "
                "solo se ordenan números, caracteres y cadenas",
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
                field_type = self._resolve_field(base_type, target)
                self._check_escritura(node, f"'{target.member}'", field_type,
                                      value_type)
                self._asignacion_de_dueno(node, field_type)
                return field_type or value_type
            self.visit_expr(target.index)
            elemento = self._tipo_del_elemento(base_type)
            self._check_escritura(node, "el elemento", elemento, value_type)
            hook = self._hook_de_escritura(base_type)
            if hook is not None:
                # 'v[i] = x' lo escribe el '__index_set__': es una llamada
                self._instancia(hook, self._mapa_de(hook, base_type), node)
            else:
                self._asignacion_de_dueno(node, elemento)
            return value_type
        return self.visit_expr(target) or value_type

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
        if _is_null_literal(node.value):
            if not type_service.unify_literal_null(destino):
                self.ctx.error(ASTError.TypeMismatchError(
                    f"'null' no es asignable a {que} ('{destino!r}': no es "
                    "nullable)", line=node.ln, column=node.col,
                ))
        elif not self._acepta_valor(destino, node.value, value_type,
                                    lambda e: setattr(node, "value", e)):
            self.ctx.error(ASTError.TypeMismatchError(
                f"no se puede asignar '{value_type!r}' a {que} "
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
        """Que COPIA cada generico, y que instancia copiaria un dueño.

        Tres pasos:

        1. Las copias DIRECTAS de cada cuerpo pasan a su Symbol.
        2. Se propagan: si ``f<T>`` llama a ``g<U>`` con ``U = T`` y ``g``
           copia su ``U``, ``f`` copia su ``T`` (``Vector.grow`` copiaba a
           traves de ``mem.copy``). Hasta que nada cambie, con tope: una
           recursion polimorfica (``f<T>`` que llama a ``f<Caja<T>>``) no
           terminaria.
        3. Cada instancia con tipos CONCRETOS: si lo que copia tiene
           destructor, SEM038 en la llamada.
        """
        ctx = self.ctx
        for fn_id, lista in ctx.copias.items():
            simbolo = ctx.fn_symbols.get(fn_id)
            if simbolo is not None:
                simbolo.copias = tuple(dict.fromkeys(lista))
        for _ in range(32):
            cambio = False
            for llamador, genericos, llamado, mapa, *_resto in ctx.instancias:
                if llamador is None or not genericos or not llamado.copias:
                    continue
                for tipo, donde in llamado.copias:
                    concreto = type_service.substitute(tipo, mapa)
                    if type_service.mentions_param(concreto, genericos) \
                            and (concreto, donde) not in llamador.copias:
                        llamador.copias = llamador.copias + ((concreto, donde),)
                        cambio = True
            if not cambio:
                break
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

    def _expr_index(self, node: ast.Index) -> Optional[Type]:
        obj_type = self.visit_expr(node.obj)
        self.visit_expr(node.index)
        # 'v[i]' sobre un tipo nominal con hook __index__: el tipo de la
        # expresión es el ELEMENTO (el retorno del hook). El indexado crudo de
        # un puntero/bloque no tiene tipo definido en esta fase (None).
        # 's[i]' sobre un 'str' es NATIVO, por lo mismo que 'len(s)': una
        # cadena se lee sin que ninguna libreria lo declare, y 'str' es
        # primitivo — SEM006 prohibe colgarle un '__index__'. Sin esto una
        # cadena se podia MEDIR pero no LEER, que es media cadena: escribir un
        # lexer en suriaX era imposible.
        if obj_type is not None and obj_type.kind is TypeKind.STR:
            return _CHAR
        owner = _nominal_name(self._canonical(obj_type)) \
            if obj_type is not None else None
        if owner is not None:
            hook = self.ctx.table.lookup_hook(owner, HookKind.INDEX)
            if hook is not None:
                mapa = self._mapa_de(hook, obj_type)
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

    def _expr_call(self, node: ast.Call) -> Optional[Type]:
        callee = node.callee
        # llamada por nombre plano: 'foo(...)', 'print(x)'
        if isinstance(callee, ast.Identifier):
            symbol = self.ctx.scope.resolve_value(callee.name)
            if symbol is not None:
                self.ctx.usar(symbol, callee.ln, callee.col)
                arg_types = [self.visit_expr(arg) for arg in node.args]
                return self._check_call(symbol, node, arg_types)
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
        # usuario esta diferida al runtime, no al MIR.
        dunder = self.ctx.table.lookup_dunder(owner, callee.member)
        if dunder is not None:
            node.hook = dunder
            mapa = self._mapa_de(dunder, obj_type)
            self._instancia(dunder, mapa, node)
            declarados = tuple(dunder.param_types or ())[1:]
            for index, (arg, declarado) in enumerate(
                    zip(node.args, declarados), start=2):
                # sustituido: 'v.push(r)' con 'Vector<R>' es un 'T' que se
                # instancia como 'R', y ahi tambien hay que ceder con 'move'.
                instanciado = type_service.substitute(declarado, mapa)                     if mapa else declarado
                self._argumento_transferido(
                    f"{owner}.{callee.member}", index, arg, instanciado)
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

    def _hash_de(self, node: ast.Call, t: Type) -> Optional[Type]:
        """``hash(x)``: NATIVO sobre ``int``/``bool``/``char``/``str``; un
        tipo propio lo da con su ``__hash__``; sobre un PARAMETRO de tipo
        (``hash(k)`` con ``k: K`` en un generico) lo decide cada motor con el
        tipo concreto, y si ese tipo no tiene hash el error es de ejecucion
        (RT011), igual que en el interprete."""
        while t.kind is TypeKind.ERROR and t.inner is not None:
            t = t.inner
        primitivos = {TypeKind.INT: "int", TypeKind.BYTE: "int", TypeKind.BOOL: "bool",
                      TypeKind.CHAR: "char", TypeKind.STR: "str"}
        if t.kind in primitivos:
            node.hook = Symbol(name="__hash__", kind=SymbolKind.HOOK, ln=0, col=0,
                               type=_INT, hook_kind=HookKind.HASH,
                               hook_owner=primitivos[t.kind])
            return _INT
        if t.kind is TypeKind.FLOAT:
            self.ctx.error(ASTError.TypeMismatchError(
                "un 'float' no tiene hash: NaN no es igual a si mismo, y un "
                "valor que no es igual a si mismo no puede ser clave",
                line=node.ln, column=node.col,
            ))
            return _INT
        owner = _nominal_name(t)
        if owner is None:
            return None
        fn = self.ctx.current_fn
        genericos = set(getattr(fn, "type_params", None) or ()) | \
            set(getattr(fn, "impl_type_params", None) or ())
        hook = self.ctx.table.lookup_hook(owner, HookKind.HASH)
        simbolo = self._nominal_symbol(t)
        enum_simple = simbolo is not None and simbolo.kind is SymbolKind.ENUM \
            and not any(m.param_types for m in (simbolo.members or {}).values())
        if hook is None and (owner in genericos or enum_simple):
            # el backend lo resuelve con el tipo concreto (un enum sin payload
            # es un entero, y se le calcula como a uno)
            node.hook = Symbol(name="__hash__", kind=SymbolKind.HOOK, ln=0, col=0,
                               type=_INT, hook_kind=HookKind.HASH, hook_owner=owner)
            return _INT
        if hook is None:
            self.ctx.error(SemanticError.UndefinedSymbolError(
                f"'hash' no está declarado y '{owner}' no define '__hash__'",
                line=node.ln, column=node.col,
            ))
            return None
        node.hook = hook
        return hook.type

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
            return member.type if member is not None else None
        if isinstance(obj, ast.Identifier):
            base = self.ctx.scope.resolve_value(obj.name)
            if base is None:
                # acceso estatico a un TIPO: 'Color.Rojo' (enum item)
                base = self.ctx.scope.resolve_type(obj.name)
            if base is not None:
                self.ctx.usar(base, obj.ln, obj.col)
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
            return None  # tipo desconocido / primitivo: permisivo
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
        # GENERICO: 'make<int>(4)' o 'primero(1)'. La firma esta escrita con
        # los parametros de tipo sin ligar ('T'), asi que antes de comparar
        # nada hay que sustituirlos. Es la misma operacion que hace un literal
        # de struct generico, con el mismo servicio.
        mapa = self._ligar_generico(symbol, node, arg_types)
        # el RETORNO se sustituye igual que los parametros: 'make<int>(4)'
        # produce un 'Vector<int>', no un 'Vector<T>'. Sin esto la llamada
        # entregaria un tipo con una 'T' sin ligar y nada unificaria con el.
        retorno = type_service.substitute(symbol.type, mapa) if mapa \
            else symbol.type
        if mapa:
            expected = tuple(type_service.substitute(t, mapa) for t in expected)
            self._instancia(symbol, mapa, node)
        if len(node.args) != len(expected):
            self.ctx.error(SemanticError.CallArityError(
                f"'{symbol.name}' espera {len(expected)} argumento(s), "
                f"recibe {len(node.args)}",
                line=node.ln, column=node.col,
            ))
            return retorno
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
            elif not self._acepta_valor(
                    param_type, arg, arg_type,
                    lambda e, i=index - 1: node.args.__setitem__(i, e)):
                self.ctx.error(ASTError.TypeMismatchError(
                    f"argumento {index} de '{symbol.name}': se esperaba "
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
                self._argumento_transferido(symbol.name, index, arg, param_type)
        return retorno

    def _ligar_generico(self, symbol: Symbol, node: ast.Call,
                        arg_types: list) -> dict:
        """Los parametros de tipo de ``symbol`` -> los tipos de ESTA llamada.

        Dos vias, y la escrita gana: si la llamada trae argumentos de tipo
        (``make<int>(4)``) se usan esos; si no, se DEDUCEN de los argumentos
        cuando un parametro esta declarado exactamente como un parametro de
        tipo (``fn primero<T>(T a)`` con un ``int`` liga ``T=int``).

        La deduccion es deliberadamente literal —no unifica dentro de ``T
        ptr`` ni de ``Caja<T>``—: cubre el caso que se escribe todos los dias
        y deja el resto a los argumentos explicitos, que siempre estan
        disponibles. Un generico que no se puede deducir no se adivina: sin
        mapa, la firma se compara sin sustituir y el error dice que se
        esperaba ``T``, que es exactamente lo que falta escribir.
        """
        if not symbol.type_params:
            return {}
        escritos = self.types.bind_call(node, symbol)
        if escritos:
            return dict(zip(symbol.type_params, escritos))
        mapa: dict = {}
        for declarado, real in zip(symbol.param_types or (), arg_types):
            if real is None or declarado is None:
                continue
            if declarado.kind is TypeKind.NOMINAL and not declarado.args \
                    and declarado.name in symbol.type_params \
                    and declarado.name not in mapa:
                mapa[declarado.name] = real
        return mapa

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


def _leaf_igual(a: Optional[str], b: Optional[str]) -> bool:
    """¿Dos nombres nominales nombran el mismo tipo, salvo calificacion?"""
    if a is None or b is None:
        return False
    return a.rsplit(".", 1)[-1] == b.rsplit(".", 1)[-1]


def _es_puntero(t: Optional[Type]) -> bool:
    """``ptr T`` o ``ptr T?``: un préstamo, cuyo contenido no es propio."""
    while t is not None and t.kind is TypeKind.NULLABLE:
        t = t.inner
    return t is not None and t.kind is TypeKind.POINTER


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
            salida |= _nombres_liberados(stmt.then_block)
            rama = getattr(stmt, "else_block", None)
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


def _is_null_literal(expr: ast.Expression) -> bool:
    return isinstance(expr, ast.Literal) and expr.literal_kind == "null"


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
