"""Fase 5 — Emisor del HIR: AST validado + SymbolTable -> protobuf (bytes).

Implementa el plan de ``PROTOBUF_BRIDGE.md`` secc. 2: **emisor explícito por
clase** (no reflexivo — el mapeo tiene casos especiales que la reflexión
complica más de lo que ahorra), un solo recorrido O(n) del árbol con
despacho por ``type(node)`` (mismo patrón de tabla que todo el frontend), y
cada hijo escrito DENTRO del message de su padre (cero copias intermedias).

Contrato con el resto del pipeline (mismo que ``semantic.analyze``): el
emisor **no lanza** por construcciones del programa — acumula
``HIRError`` y devuelve ``(bytes | None, errores)``. Solo hay bytes si no
hubo NINGÚN error: un HIR parcial no cruza la frontera (fail-fast).

**POOL DE TIPOS** (``SCHEMA_VERSION == 2``). Un programa mediano emitía
decenas de miles de mensajes ``Type`` sobre unas pocas decenas de formas
distintas (medido en ``dev/bench_hir.py``: 21 065 mensajes de 43 formas, el
20 % del artefacto). Ahora cada tipo viaja UNA vez en ``Module.types`` y los
nodos lo referencian por índice (``Expr.type_id`` y hermanos). La
``SymbolTable`` NO participa: es el 4 % de los bytes y la parte que una
persona lee al depurar (ver :meth:`_Emitter._type_id`).

Las construcciones del modelo por REGIONES se retiraron del lenguaje en
v0.2.0; el emisor ya no necesita rechazarlas. Un nodo sin handler se sigue
rechazando con ``HIR005`` (:meth:`_Emitter._error_unsupported`), que es el
fail-fast contra un AST que la Semántica acepta y el esquema no transporta.

La dependencia ``google.protobuf`` se carga de forma PEREZOSA (``stubs.py``):
importar este módulo no la exige, ejecutar :func:`emit` sí.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

try:
    from include import ast_nodes as ast
    from include.types_ast import Type
    from error_handler import HIRError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from include.types_ast import Type  # type: ignore
    import HIRError  # type: ignore

from src.frontend.semantic.symbol_table import Symbol, SymbolTable
from src.frontend.semantic.symbol_table import SymbolKind as PySymbolKind

SCHEMA_VERSION = 2

def build_module(
    program: ast.Program,
    table: SymbolTable,
    *,
    source_file: str = "",
    libraries: Optional[dict] = None,
) -> Tuple[Optional[object], List]:
    """Construye el message ``Module`` del programa VALIDADO (sin serializar).

    Precondición (la garantiza el llamador, ver ``V0/main.py``): la fase
    Semántica terminó SIN errores — nunca se cruza la frontera con un
    programa inválido. Devuelve ``(Module, [])`` o ``(None, errores)``.

    ``libraries`` (``alias -> ruta fuente``, de ``semantic.analyze``) llena
    ``Module.libraries``: cada unidad importada se REFERENCIA por su
    ``<alias>.phir`` (emitido aparte, ver ``V0/main.py``) — los exports no
    se re-embeben en este módulo (Symbol IMPORT opaco).

    Es la primitiva de la fase: :func:`emit` (binario ``.phir``) y
    :func:`module_to_text` (``.phir.txt`` / ``#test hir``) derivan de un
    MISMO ``Module`` — un solo recorrido del árbol aunque se pidan ambos.
    """
    emitter = _Emitter(source_file)
    module = emitter.emit_module(program, table)
    if libraries:
        for alias in libraries:
            ref = module.libraries.add()
            ref.alias = alias
            ref.phir = f"{alias}.phir"
    if emitter.errors:
        return None, emitter.errors
    return module, []


def module_to_text(module) -> str:
    """``Module`` -> formato de TEXTO de protobuf (debugging del formato).

    El conocimiento de ``google.protobuf`` se queda en este paquete: los
    llamadores (``V0/main.py``, el parser) nunca lo importan directamente.
    """
    from google.protobuf import text_format  # perezoso, como los stubs
    return text_format.MessageToString(module)


def serialize(module) -> bytes:
    """Serializa un ``Module`` a bytes. **Único** sitio del repositorio que
    llama a ``SerializeToString``.

    Usa la serialización DETERMINISTA de protobuf porque los ``map<>`` de la
    ``SymbolTable`` se escriben en orden no especificado: sin esto, compilar
    dos veces el mismo archivo daba artefactos con los mismos datos y bytes
    distintos. Eso invalidaba los golden ``.phir``, cualquier caché por hash y
    el diferencial que ``docs/plan_hir_v2.md`` necesita para demostrar que un
    cambio del emisor no alteró la salida. Lo sostiene
    ``test/unit/test_hir_reproducible.py``, incluido un test que compila en
    tres procesos y compara hashes.
    """
    return module.SerializeToString(deterministic=True)


def emit(
    program: ast.Program,
    table: SymbolTable,
    *,
    source_file: str = "",
) -> Tuple[Optional[bytes], List]:
    """Atajo: :func:`build_module` + serialización a bytes."""
    module, errors = build_module(program, table, source_file=source_file)
    if module is None:
        return None, errors
    return serialize(module), []


def emit_text(program: ast.Program, table: SymbolTable, *, source_file: str = "") -> Tuple[Optional[str], List]:
    """Atajo: :func:`build_module` + formato de texto (``#test hir``)."""
    module, errors = build_module(program, table, source_file=source_file)
    if module is None:
        return None, errors
    return module_to_text(module), []


class _Emitter:
    """Estado de UNA emisión: stubs cargados, tablas de despacho y errores."""

    __slots__ = ("pb", "errors", "source_file", "_expr_dispatch",
                 "_stmt_dispatch", "_type_kind", "_symbol_kind", "_hook_kind",
                 "_types", "_pool_por_id", "_pool_por_valor", "_anclas")

    def __init__(self, source_file: str) -> None:
        from .stubs import load_hir_pb2
        self.pb = load_hir_pb2()
        self.errors: List = []
        self.source_file = source_file
        # POOL DE TIPOS (ver _type_id). '_types' se liga al Module en
        # emit_module; hasta entonces no hay donde escribir.
        self._types = None
        self._pool_por_id: Dict[int, int] = {}
        self._pool_por_valor: Dict[Type, int] = {}
        self._anclas: List[Type] = []

        # enums espejo: mismo NOMBRE en Python y en el .proto — el mapeo se
        # construye una vez por emision consultando el descriptor (O(1) después).
        self._type_kind = {k: self.pb.TypeKind.Value(k.name)
                           for k in _py_type_kinds()
                           if k.name != "SELF"}  # placeholder de trait, solo-frontend
        self._symbol_kind = {k: self.pb.SymbolKind.Value(k.name)
                             for k in _py_symbol_kinds()
                             if k.name != "DUNDER"}
        # DUNDER: hook del usuario, vive en 'SymbolTable.dunders'; nunca se
        # emite como simbolo proto (su runtime esta diferido).
        self._hook_kind = {k: self.pb.HookKind.Value(k.name)
                           for k in _py_hook_kinds()}

        self._expr_dispatch: Dict[type, Callable] = {
            ast.Literal: self._expr_literal,
            ast.InterpolatedString: self._expr_interp,
            ast.Identifier: self._expr_identifier,
            ast.UnaryOp: self._expr_unary,
            ast.AddrOf: self._expr_addr_of,
            ast.BinaryOp: self._expr_binary,
            ast.Assignment: self._expr_assignment,
            ast.Call: self._expr_call,
            ast.Index: self._expr_index,
            ast.MemberAccess: self._expr_member,
            ast.SizeofExpr: self._expr_sizeof,
            ast.CastExpr: self._expr_cast,
            ast.StructLiteral: self._expr_struct_literal,
        }
        self._stmt_dispatch: Dict[type, Callable] = {
            ast.Block: self._stmt_block,
            ast.VarDecl: self._stmt_var_decl,
            ast.TypeDecl: self._stmt_type_decl,
            ast.IfStmt: self._stmt_if,
            ast.WhileStmt: self._stmt_while,
            ast.MatchStmt: self._stmt_match,
            ast.ReturnStmt: self._stmt_return,
            ast.BreakStmt: self._stmt_break,
            ast.ContinueStmt: self._stmt_continue,
            ast.MoveStmt: self._stmt_move,
            ast.FreeStmt: self._stmt_free,
            ast.ExprStmt: self._stmt_expr,
            ast.ImportBinding: self._stmt_import_binding,
            ast.ThrowStmt: self._stmt_throw,
            ast.TryStmt: self._stmt_try,
        }

    # ------------------------------------------------------------------ #
    # raiz
    # ------------------------------------------------------------------ #
    def emit_module(self, program: ast.Program, table: SymbolTable):
        module = self.pb.Module(
            schema_version=SCHEMA_VERSION, source_file=self.source_file,
        )
        # la entrada 0 del pool es el tipo VACIO: 'type_id = 0' significa "sin
        # tipo anotado", que es exactamente el default de proto3 — asi la
        # ausencia no necesita un campo de presencia y un nodo sin tipo no
        # ocupa ningun byte.
        self._types = module.types
        module.types.add()
        self._emit_symbol_table(table, module.symbols)
        for item in program.items:
            # un trait es un CONTRATO verificado en la Semantica; no tiene
            # representacion en el HIR v1 (sin slot vacio que confunda al lector).
            if item.__class__ is ast.TraitDecl:
                continue
            self._emit_decl(item, module.items.add())
        return module

    # ------------------------------------------------------------------ #
    # tabla de simbolos
    # ------------------------------------------------------------------ #
    def _emit_symbol_table(self, table: SymbolTable, msg) -> None:
        for name, sym in table.global_scope.types.items():
            self._emit_symbol(sym, msg.types[name])
        for name, sym in table.global_scope.values.items():
            self._emit_symbol(sym, msg.values[name])
        # la clave es la TERNA (dueno, kind, nombre): los hooks del
        # vocabulario fijo la cierran con "" porque el 'kind' ya los
        # distingue; los declarados por el proyecto (EXTENDED) necesitan el
        # nombre — sin el, dos hooks de usuario del mismo tipo colisionarian.
        for (owner, kind, name), sym in table.hooks.items():
            entry = msg.hooks.add()
            entry.owner_type = owner
            entry.kind = self._hook_kind[kind]
            if name:
                entry.hook_name = name
            # procedencia: de que extension salio este vocabulario. Solo sirve
            # para que un diagnostico lo diga; el despacho no la mira.
            if sym.hook_module:
                entry.extension = sym.hook_module
            self._emit_symbol(sym, entry.symbol)
        # tabla de conversiones: la clave (origen, destino) es derivable de
        # la firma de cada Symbol (param_types[0] -> type), no se duplica.
        for cast_sym in table.casts.values():
            self._emit_symbol(cast_sym, msg.casts.add())

    def _emit_symbol(self, sym: Symbol, msg) -> None:
        kind = self._symbol_kind.get(sym.kind)
        if kind is None:  # DUNDER: no llega aqui, se emite por otra via
            self.errors.append(HIRError.HIRUnsupportedInstructionError(
                f"el simbolo '{sym.name}' es de una clase que el esquema HIR no "
                f"transporta ({sym.kind.name}). Es un fallo del compilador.",
                line=sym.ln, column=sym.col, file=self.source_file,
            ))
            return
        msg.name = sym.name
        msg.kind = kind
        msg.ln = sym.ln
        msg.col = sym.col
        msg.mutable = sym.mutable
        if sym.moved_at is not None:
            msg.moved_at = sym.moved_at
        if sym.type is not None:
            self._emit_type(sym.type, msg.type)
        if sym.param_types:
            for t in sym.param_types:
                self._emit_type(t, msg.param_types.add())
        if sym.members and sym.kind is not PySymbolKind.IMPORT:
            # un IMPORT viaja OPACO: sus exports viven en el .phir de su
            # propia unidad (Module.libraries) — no se re-embeben aqui.
            for name, member in sym.members.items():
                self._emit_symbol(member, msg.members[name])
        if sym.hook_kind is not None:
            msg.hook_kind = self._hook_kind[sym.hook_kind]
        if sym.hook_owner is not None:
            msg.hook_owner = sym.hook_owner
        if sym.hook_name:
            msg.hook_name = sym.hook_name

    # ------------------------------------------------------------------ #
    # tipos y hooks
    # ------------------------------------------------------------------ #
    def _type_id(self, t: Optional[Type]) -> int:
        """Indice de ``t`` en ``Module.types``; 0 si no hay tipo.

        INDICE DOBLE, y el porque importa. La clave natural seria el VALOR
        (``Type`` es frozen, hashea recursivo), pero medido cuesta 472 ns por
        aparicion frente a 115 ns de ``id()`` — y el frontend REUTILIZA sus
        objetos ``Type``: 19 666 apariciones sobre 805 instancias que colapsan
        a 43 formas. Asi que la ruta caliente va por identidad y solo el
        primer encuentro de cada objeto paga el hash estructural, que es lo
        que garantiza el dedupe por valor (dos ``int`` construidos por
        separado comparten entrada).

        ``_anclas`` mantiene VIVOS los objetos que llegaron por la ruta de
        valor. Sin eso, uno podria recolectarse, su ``id()`` reutilizarse para
        un ``Type`` nuevo de otra forma, y ``_pool_por_id`` devolveria el
        indice equivocado: un artefacto con un tipo mentido y ningun error.
        """
        if t is None:
            return 0
        clave = id(t)
        tid = self._pool_por_id.get(clave)
        if tid is not None:
            return tid
        tid = self._pool_por_valor.get(t)
        if tid is None:
            tid = len(self._types)
            self._emit_type(t, self._types.add())
            self._pool_por_valor[t] = tid
        else:
            self._anclas.append(t)
        self._pool_por_id[clave] = tid
        return tid

    def _emit_type(self, t: Type, msg) -> None:
        msg.kind = self._type_kind[t.kind]
        if t.name is not None:
            msg.name = t.name
        if t.inner is not None:
            self._emit_type(t.inner, msg.inner)
        if t.mut:
            msg.mut = True
        for arg in t.args:
            self._emit_type(arg, msg.args.add())

    def _emit_hook_ref(self, hook: Optional[Symbol], msg) -> None:
        """Anotación ``.hook`` de la Semántica -> referencia (owner, kind, name).

        El ``Symbol`` completo ya viaja en ``SymbolTable.hooks``; aquí solo
        la CLAVE para el lookup O(1) del lector (PROTOBUF_BRIDGE.md secc. 1).
        El ``hook_name`` es lo que distingue a dos hooks de usuario del mismo
        tipo: sin él serían la misma referencia.
        """
        if hook is None:
            return
        msg.owner_type = hook.hook_owner or ""
        if hook.hook_kind is not None:
            msg.kind = self._hook_kind[hook.hook_kind]
        if hook.hook_name:
            msg.hook_name = hook.hook_name

    # ------------------------------------------------------------------ #
    # declaraciones top-level
    # ------------------------------------------------------------------ #
    def _emit_decl(self, node, msg) -> None:
        msg.ln = node.ln
        msg.col = node.col
        cls = node.__class__

        if cls is ast.DecoratorDecl:
            # el wrapper se aplana (PROTOBUF_BRIDGE.md secc. 1): el MIR no
            # necesita la indireccion, solo el nombre del decorador. El target
            # puede ser una funcion ('@inline fn') o un struct/enum
            # ('@impl(trait) struct'): la conformidad del trait ya se verifico
            # en Semantica; aqui se emite la declaracion decorada tal cual.
            if node.target.__class__ is ast.FunctionDecl:
                self._emit_function(node.target, msg.function, decorator=node.name)
            else:
                self._emit_decl(node.target, msg)
        elif cls is ast.FunctionDecl:
            self._emit_function(node, msg.function)
        elif cls is ast.StructDecl:
            msg.struct_decl.name = node.name
            for f in node.fields:
                field = msg.struct_decl.fields.add()
                field.name = f.name
                field.type_id = self._type_id(f.restype)
        elif cls is ast.EnumDecl:
            msg.enum_decl.name = node.name
            for item in node.items:
                entry = msg.enum_decl.items.add()
                entry.name = item.name
                if item.value is not None:
                    self._emit_expr(item.value, entry.value)
                # el PAYLOAD es lo que separa un entero con nombre de un
                # constructor: sin el, el consumidor no sabria que 'Literal'
                # hay que invocarlo.
                for t in item.payload_restypes:
                    entry.payload_type_ids.append(self._type_id(t))
        elif cls is ast.TestDecl:
            msg.test_decl.name = node.name
            self._emit_block(node.body, msg.test_decl.body)
        elif cls is ast.ExternBlock:
            msg.extern_block.target = node.target
            msg.extern_block.raw = node.raw
        elif cls is ast.ImportDirective:
            msg.import_directive.lib = node.lib
            msg.import_directive.alias = node.alias or ""
            # 'unit'/'binding' los anoto la Semantica al resolver el import
            # (collect.define_import): viajan para que el consumidor del HIR
            # ligue el mismo nombre a la misma unidad sin re-resolver nada.
            msg.import_directive.unit = node.unit or ""
            msg.import_directive.binding = node.binding or ""
        elif cls is ast.ExportDirective:
            msg.export_directive.alias = node.alias
            msg.export_directive.package = node.package
        elif cls is ast.FromDirective:
            msg.from_directive.lib = node.lib
            msg.from_directive.name = node.name
            msg.from_directive.alias = node.alias or ""
            msg.from_directive.unit = node.unit or ""
        elif isinstance(node, ast.Statement):
            self._emit_stmt(node, msg.statement)
        else:  # pragma: no cover - el parser no produce otra Declaration
            self._error_unsupported(node)

    def _emit_function(self, fn: ast.FunctionDecl, msg, *, decorator: str = "") -> None:
        msg.name = fn.name
        for p in fn.params:
            param = msg.params.add()
            param.name = p.name
            param.type_id = self._type_id(p.restype)
        msg.return_type_id = self._type_id(fn.return_restype)
        if fn.body is not None:  # ausente = prototipo (msg.body queda unset)
            # SetInParent marca el campo como PRESENTE aunque el bloque quede
            # vacio. Sin esto, 'fn f() -> void { }' emitia un 'body' que
            # protobuf considera ausente —un submensaje sin campos escritos es
            # indistinguible del default— y el lector lo tomaba por un
            # PROTOTIPO: fallaba en ejecucion con 'no tiene intrinseco
            # registrado', que no tiene nada que ver con lo que pasaba.
            msg.body.SetInParent()
            self._emit_block(fn.body, msg.body)
        if fn.dunder is not None:
            msg.dunder = fn.dunder
        if decorator:
            msg.decorator = decorator

    # ------------------------------------------------------------------ #
    # sentencias
    # ------------------------------------------------------------------ #
    def _emit_stmt(self, node, msg) -> None:
        msg.ln = node.ln
        msg.col = node.col
        handler = self._stmt_dispatch.get(node.__class__)
        if handler is None:
            self._error_unsupported(node)
            return
        handler(node, msg)

    def _emit_block(self, block: ast.Block, msg) -> None:
        for stmt in block.statements:
            self._emit_stmt(stmt, msg.statements.add())
        # destrucciones al cerrar: las decidio la Semantica (ver
        # scope_resolver._anotar_drops); aqui solo viajan.
        for drop in block.drops:
            out = msg.drops.add()
            out.path.extend(drop.path)
            self._emit_hook_ref(drop.hook, out.hook)

    def _stmt_block(self, node: ast.Block, msg) -> None:
        self._emit_block(node, msg.block)

    def _stmt_var_decl(self, node: ast.VarDecl, msg) -> None:
        out = msg.var_decl
        out.qualifier = node.qualifier or ""
        out.name = node.name
        out.type_id = self._type_id(node.restype)
        if node.value is not None:
            self._emit_expr(node.value, out.value)

    def _stmt_type_decl(self, node: ast.TypeDecl, msg) -> None:
        out = msg.type_decl
        out.qualifier = node.qualifier or ""
        out.name = node.name
        if node.value is not None:
            self._emit_expr(node.value, out.value)

    def _stmt_if(self, node: ast.IfStmt, msg) -> None:
        out = msg.if_stmt
        self._emit_expr(node.condition, out.condition)
        self._emit_block(node.then_block, out.then_block)
        branch = node.else_branch
        if isinstance(branch, ast.IfStmt):
            self._stmt_if_into(branch, out.else_if)
        elif branch is not None:
            self._emit_block(branch, out.else_block)

    def _stmt_if_into(self, node: ast.IfStmt, out) -> None:
        """``else if`` encadenado: mismo cuerpo que ``_stmt_if`` pero sobre un
        message ``IfStmt`` directo (sin contenedor ``Stmt``)."""
        self._emit_expr(node.condition, out.condition)
        self._emit_block(node.then_block, out.then_block)
        branch = node.else_branch
        if isinstance(branch, ast.IfStmt):
            self._stmt_if_into(branch, out.else_if)
        elif branch is not None:
            self._emit_block(branch, out.else_block)

    def _stmt_while(self, node: ast.WhileStmt, msg) -> None:
        self._emit_expr(node.condition, msg.while_stmt.condition)
        self._emit_block(node.body, msg.while_stmt.body)

    def _stmt_match(self, node: ast.MatchStmt, msg) -> None:
        out = msg.match_stmt
        self._emit_expr(node.subject, out.subject)
        for arm in node.cases:
            case = out.cases.add()
            self._emit_expr(arm.pattern, case.pattern)
            self._emit_stmt(arm.body, case.body)

    def _stmt_return(self, node: ast.ReturnStmt, msg) -> None:
        out = msg.return_stmt
        out.SetInParent()  # 'return;' no asigna campos: marcar el oneof igual
        if node.value is not None:
            self._emit_expr(node.value, out.value)

        if node.transfers:
            msg.return_stmt.transfers = True
    def _stmt_break(self, node: ast.BreakStmt, msg) -> None:
        msg.break_stmt.SetInParent()  # marca la variante del oneof (sin campos)

    def _stmt_continue(self, node: ast.ContinueStmt, msg) -> None:
        msg.continue_stmt.SetInParent()

    def _stmt_move(self, node: ast.MoveStmt, msg) -> None:
        self._emit_expr(node.target, msg.move_stmt.target)

    def _stmt_free(self, node: ast.FreeStmt, msg) -> None:
        self._emit_expr(node.target, msg.free_stmt.target)
        self._emit_hook_ref(node.hook, msg.free_stmt.hook)

    def _stmt_expr(self, node: ast.ExprStmt, msg) -> None:
        self._emit_expr(node.expr, msg.expr_stmt.expr)

    def _stmt_throw(self, node: ast.ThrowStmt, msg) -> None:
        self._emit_expr(node.value, msg.throw_stmt.value)

    def _stmt_try(self, node: ast.TryStmt, msg) -> None:
        out = msg.try_stmt
        self._emit_block(node.try_block, out.try_block)
        for clausula in node.catches:
            rama = out.catches.add()
            rama.name = clausula.name
            self._emit_block(clausula.block, rama.block)
            if clausula.restype is not None:
                self._emit_type(clausula.restype, rama.type)

    def _stmt_import_binding(self, node: ast.ImportBinding, msg) -> None:
        out = msg.import_binding
        out.qualifier = node.qualifier or ""
        out.name = node.name
        out.lib = node.source.lib
        if isinstance(node.source, ast.FromDirective):
            out.member = node.source.name

    # ------------------------------------------------------------------ #
    # expresiones
    # ------------------------------------------------------------------ #
    def _emit_expr(self, node, msg) -> None:
        handler = self._expr_dispatch.get(node.__class__)
        if handler is None:
            # se sale ANTES de tocar 'node.restype': lo que no esta en la
            # tabla puede no ser siquiera una Expression.
            self._error_unsupported(node)
            return
        msg.ln = node.ln
        msg.col = node.col
        # lectura DIRECTA, no 'getattr' defensivo: toda Expression declara
        # 'restype', y quien no lo declare ya salio por la rama de arriba.
        # Medido: el getattr costaba ~5 % del tiempo de emision.
        msg.type_id = self._type_id(node.restype)
        handler(node, msg)

    def _expr_literal(self, node: ast.Literal, msg) -> None:
        out = msg.literal
        kind = node.literal_kind
        out.kind = kind
        if kind == "int":
            out.int_value = node.value
        elif kind == "float":
            out.float_value = node.value
        elif kind in ("str", "char"):
            out.str_value = node.value
        elif kind == "bool":
            out.bool_value = node.value
        # 'null': ningun campo del oneof presente (por diseño del esquema)

    def _expr_interp(self, node: ast.InterpolatedString, msg) -> None:
        for part in node.parts:
            entry = msg.interp.parts.add()
            if isinstance(part, str):
                entry.text = part
            else:
                self._emit_expr(part, entry.expr)

    def _expr_identifier(self, node: ast.Identifier, msg) -> None:
        msg.identifier.name = node.name

    def _expr_unary(self, node: ast.UnaryOp, msg) -> None:
        msg.unary.op = node.operator
        self._emit_expr(node.operand, msg.unary.operand)

    def _expr_addr_of(self, node: ast.AddrOf, msg) -> None:
        # la REGLA de mutabilidad viaja resuelta: True (var -> ptr mutable T)
        # o False (const -> ptr T). Ver proto/hir.proto (AddrOf).
        msg.addr_of.SetInParent()  # mut=False no marcaria el oneof por si solo
        msg.addr_of.mut = bool(node.mut)
        self._emit_expr(node.operand, msg.addr_of.operand)

    def _expr_binary(self, node: ast.BinaryOp, msg) -> None:
        msg.binary.op = node.operator
        self._emit_expr(node.left, msg.binary.left)
        self._emit_expr(node.right, msg.binary.right)

    def _expr_assignment(self, node: ast.Assignment, msg) -> None:
        self._emit_expr(node.target, msg.assignment.target)
        self._emit_expr(node.value, msg.assignment.value)

    def _expr_call(self, node: ast.Call, msg) -> None:
        # 'min(T)'/'max(T)' se resolvieron a un entero en compilacion (el
        # rango que el tipo declara): viajan como el LITERAL que son. Ningun
        # consumidor del HIR necesita saber que hubo una llamada, y asi el
        # rango no depende de que el destino sepa despachar un hook.
        if node.valor_constante is not None:
            msg.literal.kind = "int"
            msg.literal.int_value = node.valor_constante
            return
        self._emit_expr(node.callee, msg.call.callee)
        for arg in node.args:
            self._emit_expr(arg, msg.call.args.add())
        self._emit_hook_ref(node.hook, msg.call.hook)
        self._emit_hook_ref(node.temp_drop, msg.call.temp_drop)

    def _expr_index(self, node: ast.Index, msg) -> None:
        self._emit_expr(node.obj, msg.index.obj)
        self._emit_expr(node.index, msg.index.index)

    def _expr_member(self, node: ast.MemberAccess, msg) -> None:
        self._emit_expr(node.obj, msg.member.obj)
        msg.member.member = node.member

    def _expr_cast(self, node: ast.CastExpr, msg) -> None:
        out = msg.cast_expr
        if node.restype is not None:  # el T escrito ya resuelto (typed_ast)
            self._emit_type(node.restype, out.type)
        self._emit_expr(node.value, out.value)
        self._emit_hook_ref(node.hook, out.hook)

    def _expr_struct_literal(self, node: ast.StructLiteral, msg) -> None:
        out = msg.struct_literal
        out.type_name = node.type_name
        for name, value in zip(node.field_names, node.values):
            out.field_names.append(name)
            self._emit_expr(value, out.values.add())
        self._emit_hook_ref(node.temp_drop, msg.struct_literal.temp_drop)

    def _expr_sizeof(self, node: ast.SizeofExpr, msg) -> None:
        # el tipo CONSULTADO ('sizeof(Punto)' -> Punto) lo dejo resuelto la
        # Semantica en 'medido': es la unica que sabe si lo escrito nombraba
        # un tipo o un VALOR ('sizeof(a)' mide el tipo de 'a'). El fallback
        # re-resuelve el TypeExpr para los nodos que no pasaron por ella.
        medido = node.medido
        if medido is None:
            from src.frontend.parser.typed_ast import resolve_type_expr
            medido = resolve_type_expr(node.type)
        self._emit_type(medido, msg.sizeof.type)
        self._emit_hook_ref(node.hook, msg.sizeof.hook)

    # ------------------------------------------------------------------ #
    # rechazo v1
    # ------------------------------------------------------------------ #
    def _error_unsupported(self, node) -> None:
        """Nodo del AST sin handler en el emisor: se RECHAZA con su posicion en
        vez de degradarse en silencio. Es el fail-fast que garantiza que todo
        lo que la Semantica acepta, o viaja al HIR, o dice por que no."""
        self.errors.append(HIRError.HIRUnsupportedInstructionError(
            f"el nodo '{node.__class__.__name__}' no tiene correspondencia en "
            "el esquema HIR: el emisor no sabe serializarlo. Es un fallo del "
            "compilador, no del programa.",
            line=node.ln, column=node.col, file=self.source_file,
        ))


def _py_type_kinds():
    from include.types_ast import TypeKind
    return TypeKind


def _py_symbol_kinds():
    from src.frontend.semantic.symbol_table import SymbolKind
    return SymbolKind


def _py_hook_kinds():
    from src.frontend.semantic.hooks import HookKind
    return HookKind


__all__ = ["build_module", "serialize", "module_to_text", "emit", "emit_text",
           "SCHEMA_VERSION"]
