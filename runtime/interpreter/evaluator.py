"""El tree-walk: ``exec_stmt`` / ``eval_expr`` por despacho O(1) (secc. 4).

Recorre los messages del HIR despachando por ``WhichOneof`` contra tablas
``str -> método`` construidas UNA vez por instancia (mismo patrón de
tabla-de-despacho que todo el frontend). No re-decide semántica: ejecuta lo
que el HIR trae resuelto — tipos en ``restype``, hooks en ``HookRef``,
mutabilidad en ``AddrOf.mut``.

Las INSTRUCCIONES DE MEMORIA (``&``, deref implícito, ``move``, ``free``)
delegan en :mod:`memory.pointer`: la celda es quien valida su estado
(use-after-move/free) — el evaluator solo enruta.

Control de flujo por señales (excepciones internas ``_Return``/``_Break``/
``_Continue``): coste solo cuando ocurren, cero banderas en el camino
caliente.
"""

from __future__ import annotations

from typing import Any, List, Optional

from .enviroment.environment import Frame
from .errors import (
    IndexOutOfRangeError, InvalidCastRuntimeError, InvalidFreeError,
    MissingIntrinsicError, NotCallableError, NotIndexableError,
    NullDereferenceError, StepLimitError, UnsupportedNodeError,
)
from .hook.dispatch import type_key
from . import intrinsics
from .memory.block import Block
from .memory.pointer import Cell, Pointer
from .values import (
    EnumNamespace, FunctionValue, Namespace, StructValue, TypeValue,
    format_value,
)


class _Return(Exception):
    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class Thrown(Exception):
    """Propagación de un ``throw`` por la pila (modelo de excepciones).

    Distinta de :class:`SuriaXRuntimeError`: esto es control de flujo del
    PROGRAMA (lo captura un ``try``/``catch``), no un fallo del intérprete.
    Si escapa hasta la raíz, ``interpreter.run`` la reporta como error de
    runtime no capturado."""

    __slots__ = ("value", "ln", "col")

    def __init__(self, value: Any, ln: int = 0, col: int = 0) -> None:
        self.value = value
        self.ln = ln
        self.col = col


# TypeKind del esquema (valores estables del .proto; ver hir.proto)
_TK_BOOL, _TK_INT, _TK_FLOAT, _TK_CHAR, _TK_STR = 2, 3, 4, 5, 6


class Evaluator:
    __slots__ = ("image", "trace", "trace_exec", "max_steps", "steps",
                 "events", "depth", "_stmt_dispatch", "_expr_dispatch",
                 "_index_kind", "_index_set_kind", "_eq_kind")

    def __init__(self, image, *, trace: bool = False, max_steps: int = 0,
                 trace_exec: bool = False,
                 events: Optional[List[str]] = None) -> None:
        self.image = image
        self.trace = trace          # traza de MEMORIA (&, move, free, catch)
        self.trace_exec = trace_exec  # traza de EJECUCION (llamadas/sentencias)
        self.max_steps = max_steps
        self.steps = 0
        # sumidero de eventos: si el llamador pasa una lista, la traza se
        # ACUMULA ahi (para volcarla a dumps/<f>.debug.txt) en vez de -- o
        # ademas de -- imprimirse. None = solo consola.
        self.events: Optional[List[str]] = events
        self.depth = 0
        # valores enteros de los kinds de hook despachados por sintaxis ('v[i]',
        # 'v[i]=x', 'a==b') contra image.hooks — sin cablear el número del enum.
        from V0.src.HIR.stubs import load_hir_pb2
        _hk = load_hir_pb2().HookKind
        self._index_kind = _hk.Value("INDEX")
        self._index_set_kind = _hk.Value("INDEX_SET")
        self._eq_kind = _hk.Value("EQ")
        self._stmt_dispatch = {
            "block": self._stmt_block,
            "var_decl": self._stmt_var_decl,
            "type_decl": self._stmt_type_decl,
            "if_stmt": self._stmt_if,
            "while_stmt": self._stmt_while,
            "match_stmt": self._stmt_match,
            "return_stmt": self._stmt_return,
            "break_stmt": self._stmt_break,
            "continue_stmt": self._stmt_continue,
            "move_stmt": self._stmt_move,
            "free_stmt": self._stmt_free,
            "expr_stmt": self._stmt_expr,
            "import_binding": self._stmt_import_binding,
            "throw_stmt": self._stmt_throw,
            "try_stmt": self._stmt_try,
        }
        self._expr_dispatch = {
            "literal": self._expr_literal,
            "interp": self._expr_interp,
            "identifier": self._expr_identifier,
            "unary": self._expr_unary,
            "addr_of": self._expr_addr_of,
            "binary": self._expr_binary,
            "assignment": self._expr_assignment,
            "call": self._expr_call,
            "index": self._expr_index,
            "member": self._expr_member,
            "sizeof": self._expr_sizeof,
            "cast_expr": self._expr_cast,
            "struct_literal": self._expr_struct_literal,
        }

    # ------------------------------------------------------------------ #
    # traza (un solo punto de emisión: consola y/o sumidero de eventos)
    # ------------------------------------------------------------------ #
    def emit(self, text: str) -> None:
        line = f"{'  ' * self.depth}{text}"
        if self.events is not None:
            self.events.append(line)
        else:
            print(line)

    # ------------------------------------------------------------------ #
    # funciones
    # ------------------------------------------------------------------ #
    def call_function(self, unit, decl, args: List[Any], *,
                      ln: int = 0, col: int = 0) -> Any:
        """Ejecuta una ``fn`` del HIR (o su intrínseco si es prototipo)."""
        if not decl.HasField("body"):
            native = intrinsics.lookup(decl.name)
            if native is None:
                raise MissingIntrinsicError(
                    f"el prototipo '{decl.name}' no tiene intrínseco "
                    "registrado en el host (runtime/interpreter/intrinsics.py)",
                    ln=ln, col=col,
                )
            if self.trace_exec:
                self.emit(f"[call] {decl.name}(intrinseco) "
                          f"args={[format_value(a) for a in args]}")
            return native(*args)

        if self.trace_exec:
            self.emit(f"[call] {decl.name}("
                      f"{', '.join(format_value(a) for a in args)})  {ln}:{col}")
        self.depth += 1

        frame = Frame(parent=unit.globals_frame)
        for param, value in zip(decl.params, args):
            frame.define(param.name, Cell(value, name=param.name))
        result = None
        try:
            self._exec_block(decl.body, Frame(parent=frame))
        except _Return as ret:
            result = ret.value
        finally:
            self.depth -= 1
        if self.trace_exec:
            self.emit(f"[ret ] {decl.name} -> {format_value(result)}")
        return result

    # ------------------------------------------------------------------ #
    # statements
    # ------------------------------------------------------------------ #
    def _exec_block(self, block, frame: Frame) -> None:
        for stmt in block.statements:
            self.exec_stmt(stmt, frame)

    def exec_stmt(self, stmt, frame: Frame) -> None:
        self._tick(stmt.ln, stmt.col)
        which = stmt.WhichOneof("node")
        handler = self._stmt_dispatch.get(which)
        if handler is None:
            raise UnsupportedNodeError(
                f"sentencia '{which}' sin soporte de ejecución",
                ln=stmt.ln, col=stmt.col,
            )
        handler(stmt, frame)

    def _stmt_block(self, stmt, frame: Frame) -> None:
        self._exec_block(stmt.block, Frame(parent=frame))

    def _stmt_var_decl(self, stmt, frame: Frame) -> None:
        vd = stmt.var_decl
        value = self.eval_expr(vd.value, frame) if vd.HasField("value") else None
        frame.define(vd.name, Cell(value, name=vd.name))

    def _stmt_type_decl(self, stmt, frame: Frame) -> None:
        td = stmt.type_decl
        value: Any = TypeValue(td.name)
        if td.HasField("value"):
            value = self.eval_expr(td.value, frame)
        frame.define(td.name, Cell(value, name=td.name))

    def _stmt_if(self, stmt, frame: Frame) -> None:
        node = stmt.if_stmt
        self._exec_if(node, frame)

    def _exec_if(self, node, frame: Frame) -> None:
        if self.eval_expr(node.condition, frame):
            self._exec_block(node.then_block, Frame(parent=frame))
        elif node.WhichOneof("else_branch") == "else_block":
            self._exec_block(node.else_block, Frame(parent=frame))
        elif node.WhichOneof("else_branch") == "else_if":
            self._exec_if(node.else_if, frame)

    def _stmt_while(self, stmt, frame: Frame) -> None:
        node = stmt.while_stmt
        while self.eval_expr(node.condition, frame):
            try:
                self._exec_block(node.body, Frame(parent=frame))
            except _Break:
                break
            except _Continue:
                continue

    def _stmt_match(self, stmt, frame: Frame) -> None:
        node = stmt.match_stmt
        subject = self.eval_expr(node.subject, frame)
        for arm in node.cases:
            if self.eval_expr(arm.pattern, frame) == subject:
                self.exec_stmt(arm.body, Frame(parent=frame))
                return

    def _stmt_return(self, stmt, frame: Frame) -> None:
        node = stmt.return_stmt
        value = self.eval_expr(node.value, frame) if node.HasField("value") else None
        raise _Return(value)

    def _stmt_break(self, stmt, frame: Frame) -> None:
        raise _Break()

    def _stmt_continue(self, stmt, frame: Frame) -> None:
        raise _Continue()

    def _stmt_move(self, stmt, frame: Frame) -> None:
        target = stmt.move_stmt.target
        if target.WhichOneof("node") == "identifier":
            cell = frame.lookup(target.identifier.name, ln=stmt.ln, col=stmt.col)
            cell.move_out(ln=stmt.ln, col=stmt.col)
            if self.trace:
                self.emit(f"[mem] move '{cell.name}' (celda invalidada)  "
                          f"{stmt.ln}:{stmt.col}")
        else:
            # forma compuesta ('move p.x'): sus lecturas sí se verifican;
            # el tracking fino de campos es del MIR (mismo criterio que
            # memory_check estático).
            self.eval_expr(target, frame)

    def _stmt_free(self, stmt, frame: Frame) -> None:
        node = stmt.free_stmt
        value = self.eval_expr(node.target, frame)
        if not isinstance(value, Pointer):
            raise InvalidFreeError(
                f"'free' sobre un valor que no es puntero ({format_value(value)})",
                ln=stmt.ln, col=stmt.col,
            )
        if node.hook.owner_type:
            bound = self.image.hooks.get((node.hook.owner_type, node.hook.kind))
            if bound is not None:
                self.call_function(bound[0], bound[1], [value],
                                   ln=stmt.ln, col=stmt.col)
        value.cell.free(ln=stmt.ln, col=stmt.col)
        if self.trace:
            self.emit(f"[mem] free -> celda '{value.cell.name}'  "
                      f"{stmt.ln}:{stmt.col}")

    def _stmt_expr(self, stmt, frame: Frame) -> None:
        self.eval_expr(stmt.expr_stmt.expr, frame)

    def _stmt_import_binding(self, stmt, frame: Frame) -> None:
        node = stmt.import_binding
        frame.define(node.name, Cell(Namespace(node.lib), name=node.name))

    def _stmt_throw(self, stmt, frame: Frame) -> None:
        value = self.eval_expr(stmt.throw_stmt.value, frame)
        raise Thrown(value, ln=stmt.ln, col=stmt.col)

    def _stmt_try(self, stmt, frame: Frame) -> None:
        node = stmt.try_stmt
        try:
            self._exec_block(node.try_block, Frame(parent=frame))
        except Thrown as thrown:
            # el binding del catch vive SOLO en el scope de su bloque
            catch_frame = Frame(parent=frame)
            catch_frame.define(node.catch_name,
                               Cell(thrown.value, name=node.catch_name))
            if self.trace:
                self.emit(f"[err] catch '{node.catch_name}' = "
                          f"{format_value(thrown.value)}  {stmt.ln}:{stmt.col}")
            self._exec_block(node.catch_block, catch_frame)

    # ------------------------------------------------------------------ #
    # expresiones
    # ------------------------------------------------------------------ #
    def eval_expr(self, expr, frame: Frame) -> Any:
        self._tick(expr.ln, expr.col)
        which = expr.WhichOneof("node")
        handler = self._expr_dispatch.get(which)
        if handler is None:
            raise UnsupportedNodeError(
                f"expresión '{which}' sin soporte de ejecución",
                ln=expr.ln, col=expr.col,
            )
        return handler(expr, frame)

    def _expr_literal(self, expr, frame: Frame) -> Any:
        lit = expr.literal
        which = lit.WhichOneof("value")
        if which is None:
            return None  # 'null'
        return getattr(lit, which)

    def _expr_interp(self, expr, frame: Frame) -> str:
        parts: List[str] = []
        for part in expr.interp.parts:
            if part.WhichOneof("part") == "text":
                parts.append(part.text)
            else:
                parts.append(format_value(self.eval_expr(part.expr, frame)))
        return "".join(parts)

    def _expr_identifier(self, expr, frame: Frame) -> Any:
        return frame.lookup(expr.identifier.name, ln=expr.ln,
                            col=expr.col).read(ln=expr.ln, col=expr.col)

    def _expr_unary(self, expr, frame: Frame) -> Any:
        node = expr.unary
        operand = self.eval_expr(node.operand, frame)
        if node.op == "not":
            return not operand
        return -operand  # '-'

    def _expr_addr_of(self, expr, frame: Frame) -> Pointer:
        node = expr.addr_of
        operand = node.operand
        which = operand.WhichOneof("node")
        if which == "identifier":
            cell = frame.lookup(operand.identifier.name,
                                ln=expr.ln, col=expr.col)
            if self.trace:
                self.emit(f"[mem] &{cell.name} -> ptr"
                          f"{' mutable' if node.mut else ''}  {expr.ln}:{expr.col}")
            return Pointer(cell, mut=node.mut)
        if which == "member":
            base = self.eval_expr(operand.member.obj, frame)
            cell = self._field_cell(base, operand.member.member,
                                    ln=expr.ln, col=expr.col)
            return Pointer(cell, mut=node.mut)
        raise UnsupportedNodeError(
            f"'&' sobre '{which}' sin soporte de ejecución",
            ln=expr.ln, col=expr.col,
        )

    def _expr_binary(self, expr, frame: Frame) -> Any:
        node = expr.binary
        op = node.op
        if op == "and":  # corto-circuito: el derecho solo si hace falta
            return bool(self.eval_expr(node.left, frame)) and \
                bool(self.eval_expr(node.right, frame))
        if op == "or":
            return bool(self.eval_expr(node.left, frame)) or \
                bool(self.eval_expr(node.right, frame))
        left = self.eval_expr(node.left, frame)
        right = self.eval_expr(node.right, frame)
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            # división entera para ints (idioma 'i / 3 * 3 == i' de los
            # ejemplos); real para floats — el tipado fuerte ya garantizó
            # operandos homogéneos.
            if isinstance(left, int) and not isinstance(left, bool):
                return left // right
            return left / right
        if op == "==":
            eq = self._dispatch_eq(left, right, expr)
            return (left == right) if eq is None else eq
        if op == "!=":
            eq = self._dispatch_eq(left, right, expr)
            return (left != right) if eq is None else (not eq)
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        raise UnsupportedNodeError(f"operador binario '{op}' desconocido",
                                   ln=expr.ln, col=expr.col)

    def _dispatch_eq(self, left: Any, right: Any, expr) -> Optional[bool]:
        """'a == b' entre dos valores nominales del mismo tipo con hook __eq__:
        devuelve su resultado; ``None`` si no aplica (se cae a la identidad)."""
        if isinstance(left, StructValue) and isinstance(right, StructValue) \
                and left.type_name == right.type_name:
            bound = self.image.hooks.get((left.type_name, self._eq_kind))
            if bound is not None:
                return bool(self.call_function(bound[0], bound[1], [left, right],
                                               ln=expr.ln, col=expr.col))
        return None

    def _expr_assignment(self, expr, frame: Frame) -> Any:
        node = expr.assignment
        value = self.eval_expr(node.value, frame)
        target = node.target
        which = target.WhichOneof("node")
        if which == "identifier":
            frame.lookup(target.identifier.name, ln=expr.ln,
                         col=expr.col).write(value, ln=expr.ln, col=expr.col)
            return value
        if which == "member":
            base = self.eval_expr(target.member.obj, frame)
            cell = self._field_cell(base, target.member.member,
                                    ln=expr.ln, col=expr.col)
            cell.write(value, ln=expr.ln, col=expr.col)
            return value
        if which == "index":
            base = self.eval_expr(target.index.obj, frame)
            idx = self.eval_expr(target.index.index, frame)
            # 'v[i] = x' sobre un tipo nominal con hook __index_set__: despacha
            # al hook (el indexado crudo de puntero/bloque sigue por _element_cell).
            if isinstance(base, StructValue):
                bound = self.image.hooks.get((base.type_name, self._index_set_kind))
                if bound is not None:
                    self.call_function(bound[0], bound[1], [base, idx, value],
                                       ln=expr.ln, col=expr.col)
                    return value
            self._element_cell(base, idx, ln=expr.ln, col=expr.col).write(
                value, ln=expr.ln, col=expr.col)
            return value
        raise UnsupportedNodeError(
            f"asignación a '{which}' sin soporte de ejecución",
            ln=expr.ln, col=expr.col,
        )

    def _expr_call(self, expr, frame: Frame) -> Any:
        node = expr.call
        callee = node.callee
        # despacho de hook FIJO ya enlazado (print(x) / x.print() / len(x))
        if node.hook.owner_type:
            bound = self.image.hooks.get((node.hook.owner_type, node.hook.kind))
            if bound is not None:
                args = [self.eval_expr(a, frame) for a in node.args]
                # forma 'x.print()': el receptor es el primer argumento
                if callee.WhichOneof("node") == "member" and not args:
                    args = [self.eval_expr(callee.member.obj, frame)]
                return self.call_function(bound[0], bound[1], args,
                                          ln=expr.ln, col=expr.col)
            # método de usuario 'x.__metodo__(args)' -> dunder (owner, nombre).
            # El receptor va como PRIMER argumento: el struct se COMPARTE (sus
            # campos son celdas), así un método que muta 'x' se propaga al
            # llamante — el mismo modelo que un parámetro 'T ptr mutable'.
            if callee.WhichOneof("node") == "member":
                method = self.image.dunders.get(
                    (node.hook.owner_type, callee.member.member))
                if method is not None:
                    args = [self.eval_expr(callee.member.obj, frame)]
                    args.extend(self.eval_expr(a, frame) for a in node.args)
                    return self.call_function(method[0], method[1], args,
                                              ln=expr.ln, col=expr.col)

        callee_value = self._eval_callee(node.callee, frame)
        args = [self.eval_expr(a, frame) for a in node.args]
        if isinstance(callee_value, FunctionValue):
            unit = self.image.main if callee_value.unit_alias == "" \
                else self.image.units[callee_value.unit_alias]
            return self.call_function(unit, callee_value.decl, args,
                                      ln=expr.ln, col=expr.col)
        raise NotCallableError(
            f"'{format_value(callee_value)}' no es invocable",
            ln=expr.ln, col=expr.col,
        )

    def _eval_callee(self, callee, frame: Frame) -> Any:
        """El callee de una llamada: soporta 'IO.printf' (miembro de un
        namespace) ademas de cualquier expresión que produzca una fn."""
        if callee.WhichOneof("node") == "member":
            base = self.eval_expr(callee.member.obj, frame)
            if isinstance(base, Namespace):
                return self._namespace_member(base, callee.member.member,
                                              ln=callee.ln, col=callee.col)
        return self.eval_expr(callee, frame)

    def _expr_index(self, expr, frame: Frame) -> Any:
        node = expr.index
        base = self.eval_expr(node.obj, frame)
        idx = self.eval_expr(node.index, frame)
        # 'v[i]' sobre un tipo NOMINAL con hook __index__: despacha al hook
        # (v.gr. un vector de librería). El indexado crudo de puntero/bloque
        # sigue por _element_cell.
        if isinstance(base, StructValue):
            bound = self.image.hooks.get((base.type_name, self._index_kind))
            if bound is not None:
                return self.call_function(bound[0], bound[1], [base, idx],
                                          ln=expr.ln, col=expr.col)
        return self._element_cell(base, idx, ln=expr.ln, col=expr.col).read(
            ln=expr.ln, col=expr.col)

    def _expr_member(self, expr, frame: Frame) -> Any:
        node = expr.member
        base = self.eval_expr(node.obj, frame)
        if isinstance(base, Namespace):
            return self._namespace_member(base, node.member,
                                          ln=expr.ln, col=expr.col)
        if isinstance(base, EnumNamespace):
            value = base.items.get(node.member)
            if value is None:
                raise UnsupportedNodeError(
                    f"'{base.name}' no define '{node.member}'",
                    ln=expr.ln, col=expr.col,
                )
            return value
        return self._field_cell(base, node.member,
                                ln=expr.ln, col=expr.col).read(
                                    ln=expr.ln, col=expr.col)

    def _expr_struct_literal(self, expr, frame: Frame) -> Any:
        node = expr.struct_literal
        fields: dict = {}
        for name, value_expr in zip(node.field_names, node.values):
            fields[name] = Cell(self.eval_expr(value_expr, frame), name=name)
        return StructValue(node.type_name, fields)

    def _expr_sizeof(self, expr, frame: Frame) -> Any:
        node = expr.sizeof
        if node.hook.owner_type:
            bound = self.image.hooks.get((node.hook.owner_type, node.hook.kind))
            if bound is not None:
                return self.call_function(bound[0], bound[1], [None],
                                          ln=expr.ln, col=expr.col)
        raise UnsupportedNodeError(
            "sizeof sin '__sizeof__' declarado: el layout nativo es del backend",
            ln=expr.ln, col=expr.col,
        )

    def _expr_cast(self, expr, frame: Frame) -> Any:
        node = expr.cast_expr
        value = self.eval_expr(node.value, frame)
        kind = node.type.kind

        # conversiones NATIVAS entre primitivos (misma tabla que SEM016)
        if kind == _TK_INT:
            if isinstance(value, str):  # char -> int
                return ord(value)
            if isinstance(value, (bool, float, int)):
                return int(value)
        elif kind == _TK_FLOAT and isinstance(value, (int, float)):
            return float(value)
        elif kind == _TK_CHAR and isinstance(value, int):
            return chr(value)
        elif kind == _TK_BOOL and isinstance(value, bool):
            return value
        elif kind == _TK_STR and isinstance(value, str):
            return value

        # tabla de conversiones (__cast__): par (origen estático, destino)
        source_key = type_key(node.value.restype) if node.value.HasField("restype") else None
        bound = self.image.casts.get((source_key, type_key(node.type)))
        if bound is not None:
            return self.call_function(bound[0], bound[1], [value],
                                      ln=expr.ln, col=expr.col)
        raise InvalidCastRuntimeError(
            f"sin conversión registrada para este par (valor: "
            f"{format_value(value)})", ln=expr.ln, col=expr.col,
        )

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _namespace_member(self, ns: Namespace, member: str, *,
                          ln: int, col: int) -> Any:
        unit = self.image.units.get(ns.alias)
        if unit is None:
            raise NotCallableError(
                f"la unidad '{ns.alias}' no está ligada en la imagen",
                ln=ln, col=col,
            )
        decl = unit.functions.get(member)
        if decl is not None:
            return FunctionValue(unit.alias, decl)
        cell = unit.globals_frame.try_lookup(member) if unit.globals_frame else None
        if cell is not None:
            return cell.read(ln=ln, col=col)
        # ...y si la unidad es el PADRE de un paquete, el miembro puede ser un
        # submódulo: son unidades hermanas calificadas ('IO' + 'IO.stdp'), no
        # declaraciones del padre. Una sola búsqueda en dict, sin listar nada.
        sub = self.image.units.get(f"{ns.alias}.{member}")
        if sub is not None:
            return Namespace(sub.alias)
        raise NotCallableError(
            f"'{ns.alias}' no expone '{member}' en runtime", ln=ln, col=col,
        )

    def _element_cell(self, base: Any, index: Any, *, ln: int, col: int) -> Cell:
        """Celda del elemento ``base[index]`` (secc. 8.x — memoria contigua).

        Opera sobre un :class:`Block` de ``__reserve__`` (el caso de los
        vectores) o, por comodidad, sobre un puntero a UNA celda (índice 0).
        Como ``&buf[i]``, lectura y escritura por índice comparten destino con
        el resto del sistema de memoria (la celda es la única dueña del estado).
        """
        if isinstance(base, Block):
            return base.element(index, ln=ln, col=col)
        if isinstance(base, Pointer):
            block = base.cell.read(ln=ln, col=col)
            if isinstance(block, Block):  # puntero al bloque reservado
                return block.element(index, ln=ln, col=col)
            if index == 0:  # puntero a una sola celda: solo [0]
                return base.cell
            raise IndexOutOfRangeError(
                f"índice {index!r} sobre un puntero a una sola celda "
                "(solo [0] es válido)", ln=ln, col=col)
        if base is None:
            raise NullDereferenceError(
                f"indexación '[{index!r}]' sobre null", ln=ln, col=col)
        raise NotIndexableError(
            f"'{format_value(base)}' no es indexable (usa un bloque de "
            "__reserve__)", ln=ln, col=col)

    def _field_cell(self, base: Any, field: str, *, ln: int, col: int) -> Cell:
        """Celda del campo ``base.field`` con DEREF IMPLÍCITO de punteros
        (``s.text`` con ``s: String ptr`` — secc. 8.2)."""
        if isinstance(base, Pointer):
            base = base.deref(ln=ln, col=col)
        if base is None:
            raise NullDereferenceError(
                f"acceso a '.{field}' sobre null", ln=ln, col=col,
            )
        if isinstance(base, StructValue):
            cell = base.fields.get(field)
            if cell is None:
                raise UnsupportedNodeError(
                    f"'{base.type_name}' no tiene campo '{field}'",
                    ln=ln, col=col,
                )
            return cell
        raise UnsupportedNodeError(
            f"acceso a miembro '.{field}' sobre {format_value(base)}",
            ln=ln, col=col,
        )

    def _tick(self, ln: int, col: int) -> None:
        if self.max_steps:
            self.steps += 1
            if self.steps > self.max_steps:
                raise StepLimitError(
                    f"límite de pasos alcanzado ({self.max_steps}); ajusta "
                    "'interpreter.max_steps' en .suriaX_config.yaml",
                    ln=ln, col=col,
                )


__all__ = ["Evaluator"]
