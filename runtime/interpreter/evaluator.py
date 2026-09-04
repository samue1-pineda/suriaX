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

import math
from typing import Any, List, Optional

from .enviroment.environment import Frame
from .errors import (
    DivisionByZeroError, MissingReturnError,
    IndexOutOfRangeError, InvalidCastRuntimeError, InvalidFreeError,
    MissingIntrinsicError, NotCallableError, NotIndexableError,
    NullDereferenceError, StepLimitError, SuriaXRuntimeError,
    UnsupportedNodeError,
)
from .hook.dispatch import hook_key, ref_key, type_key
from . import intrinsics
from .memory.block import Block
from .memory.pointer import Cell, CellState, Pointer
from .values import (
    EnumNamespace, EnumValue, FunctionValue, Namespace, StructValue,
    TypeValue, VariantCtor,
    copy_on_bind, format_value,
)


class _Return(Exception):
    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value


def _void_kind_value() -> int:
    """El valor de ``TypeKind.VOID``, leído del esquema (no cableado)."""
    from V0.src.HIR.stubs import load_hir_pb2
    return load_hir_pb2().TypeKind.Value("VOID")


#: se resuelven una vez por proceso: el enum del esquema no cambia en caliente.
_VOID_KIND = None
_POINTER_KIND = None


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
_TK_NOMINAL = 9   # espejo de TypeKind.NOMINAL en el esquema del HIR
_SK_ENUM = 3      # espejo de SymbolKind.ENUM


class Evaluator:
    __slots__ = ("image", "trace", "trace_exec", "max_steps", "steps",
                 "events", "depth", "unit", "_stmt_dispatch", "_expr_dispatch",
                 "_index_kind", "_index_set_kind", "_eq_kind", "_len_kind",
                 "_temporales")

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
        # temporales de la sentencia en curso: (valor, HookRef). Ver
        # 'exec_stmt' y '_registrar_temporal'.
        self._temporales: List[Any] = []
        # unidad cuyo codigo se esta ejecutando. Hace falta porque los tipos
        # de las expresiones viajan como INDICE en el pool de SU unidad
        # (Expr.type_id, esquema v2): resolverlos exige saber de que modulo
        # salio la expresion. La monta 'call_function' y la restaura al salir.
        self.unit = image.main
        # valores enteros de los kinds de hook despachados por sintaxis ('v[i]',
        # 'v[i]=x', 'a==b') contra image.hooks — sin cablear el número del enum.
        from V0.src.HIR.stubs import load_hir_pb2
        _hk = load_hir_pb2().HookKind
        self._index_kind = _hk.Value("INDEX")
        self._index_set_kind = _hk.Value("INDEX_SET")
        self._len_kind = _hk.Value("LEN")
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
            "move_expr": self._expr_move,
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
            # Semántica de VALOR: el llamado recibe SU copia, así que mutar
            # un parámetro no toca lo del llamador. Un parámetro declarado
            # 'ptr' NO se copia: un puntero es un préstamo, y copiarlo
            # rompería justo lo que existe para permitir — que un hook o un
            # método muten el receptor. Lo decide el TIPO DECLARADO, que es
            # quien lo dice en el lenguaje.
            frame.define(param.name,
                         Cell(value if self._es_prestamo(unit, param)
                              else copy_on_bind(value), name=param.name))
        result = None
        devolvio = False
        previa = self.unit
        self.unit = unit
        try:
            self._exec_block(decl.body, Frame(parent=frame))
        except _Return as ret:
            result = ret.value
            devolvio = True
        finally:
            self.unit = previa
            self.depth -= 1
        # Caerse por el final de una función con tipo de retorno entregaba
        # 'null' en silencio. El tipo de retorno viaja en el HIR, así que aquí
        # se sabe que faltaba un valor.
        if not devolvio and self._devuelve_valor(unit, decl):
            raise MissingReturnError(
                f"la función '{decl.name}' terminó sin devolver un valor y su "
                "tipo de retorno no es 'void'",
                ln=ln, col=col,
            )
        if self.trace_exec:
            self.emit(f"[ret ] {decl.name} -> {format_value(result)}")
        return result

    @staticmethod
    def _es_prestamo(unit, param) -> bool:
        """¿El parámetro está declarado como puntero (un préstamo)?

        El pool de tipos es de la UNIDAD, igual que en el retorno: se resuelve
        contra la unidad donde vive la función, no contra la del llamador.
        """
        global _POINTER_KIND
        if _POINTER_KIND is None:
            from V0.src.HIR.stubs import load_hir_pb2
            _POINTER_KIND = load_hir_pb2().TypeKind.Value("POINTER")
        type_id = param.type_id
        types = unit.module.types
        if type_id == 0 or type_id >= len(types):
            return False
        return types[type_id].kind == _POINTER_KIND

    @staticmethod
    def _devuelve_valor(unit, decl) -> bool:
        """¿``decl`` declara un tipo de retorno distinto de ``void``?

        El pool de tipos es de la UNIDAD, así que el ``type_id`` se resuelve
        contra el de la unidad donde vive la función — no contra el del
        llamador. Resolverlo en la unidad equivocada daba a ``printf`` de
        ``IO.stdpf`` un tipo de retorno que no era el suyo.

        El índice 0 del pool es "sin tipo" y ``void`` es un tipo con nombre:
        los dos significan "no hay valor que devolver", pero por motivos
        distintos, así que se preguntan los dos.
        """
        global _VOID_KIND
        if _VOID_KIND is None:
            _VOID_KIND = _void_kind_value()
        type_id = decl.return_type_id
        if type_id == 0:
            return False
        types = unit.module.types
        if type_id >= len(types):
            return False
        return types[type_id].kind != _VOID_KIND

    # ------------------------------------------------------------------ #
    # statements
    # ------------------------------------------------------------------ #
    def _exec_block(self, block, frame: Frame) -> None:
        if not block.drops:
            # camino rapido: la inmensa mayoria de los bloques no destruye
            # nada, y no deben pagar el 'try' ni la llamada extra.
            for stmt in block.statements:
                self.exec_stmt(stmt, frame)
            return
        try:
            for stmt in block.statements:
                self.exec_stmt(stmt, frame)
        finally:
            # 'finally' y no un simple final: el bloque tambien se cierra por
            # 'return', 'break', 'continue' y 'throw', y en todos esos casos
            # los valores mueren igual. Un drop que solo corriera en la salida
            # normal seria una fuga en cuanto hubiera un 'return' temprano.
            self._drop_scope(block, frame)

    def _drop_scope(self, block, frame: Frame) -> None:
        """Destruye los valores del bloque que sigan VIVOS.

        La lista de candidatos es estatica (la decidio la Semantica por el
        TIPO); lo que es dinamico es cuales siguen vivos. Esa pregunta no
        necesita maquinaria nueva: la celda ya lleva su estado, porque es la
        misma que hace cumplir el use-after-move y el use-after-free. Asi un
        'move' dentro de un 'if' sale correcto sin analisis de flujo — si la
        rama corrio, la celda esta MOVED y aqui no se toca.
        """
        for drop in block.drops:
            cell = self._celda_de_ruta(frame, drop.path)
            if cell is None:
                continue
            bound = self.image.hooks.get(ref_key(drop.hook))
            if bound is not None:
                self.call_function(bound[0], bound[1],
                                   [Pointer(cell, mut=True)])
            cell.free()
            if self.trace:
                self.emit(f"[mem] drop -> celda '{'.'.join(drop.path)}'")

    def _celda_de_ruta(self, frame: Frame, path) -> Optional[Cell]:
        """La celda al final de ``path``, o ``None`` si algo por el camino ya
        no esta vivo.

        Comprueba el estado a CADA paso y nunca llama a ``read()``: esto corre
        dentro de un ``finally``, asi que una excepcion aqui taparia la que
        venia en curso (un 'throw' del programa, por ejemplo). Los estados no
        son un error — son la respuesta: si el valor ya se movio o se libero,
        no hay nada que destruir.
        """
        cell = frame.cells.get(path[0])
        for campo in path[1:]:
            if cell is None or cell.state is not CellState.LIVE:
                return None
            valor = cell.value
            if not isinstance(valor, StructValue):
                return None
            cell = valor.fields.get(campo)
        if cell is None or cell.state is not CellState.LIVE:
            return None
        return cell

    def exec_stmt(self, stmt, frame: Frame) -> None:
        self._tick(stmt.ln, stmt.col)
        which = stmt.WhichOneof("node")
        handler = self._stmt_dispatch.get(which)
        if handler is None:
            raise UnsupportedNodeError(
                f"sentencia '{which}' sin soporte de ejecución",
                ln=stmt.ln, col=stmt.col,
            )
        # TEMPORALES. Un valor que posee recursos y que nadie recibe muere al
        # terminar la SENTENCIA que lo produjo — 'recibe(R{...})' no le da
        # dueno a nadie. La marca es el largo de la pila: lo que se apile
        # durante esta sentencia se suelta al salir de ella, tambien si sale
        # por una excepcion (un 'throw' del programa no debe filtrar).
        marca = len(self._temporales)
        try:
            handler(stmt, frame)
        finally:
            if len(self._temporales) > marca:
                self._soltar_temporales(marca)

    def _soltar_temporales(self, marca: int) -> None:
        while len(self._temporales) > marca:
            valor, hook = self._temporales.pop()
            bound = self.image.hooks.get(ref_key(hook))
            if bound is None:
                continue
            self.call_function(bound[0], bound[1],
                               [Pointer(Cell(valor), mut=True)])
            if self.trace:
                self.emit("[mem] drop temporal")

    def _registrar_temporal(self, valor, hook_ref) -> None:
        """Apila un valor sin dueno para destruirlo al cerrar la sentencia."""
        if hook_ref.owner_type:
            self._temporales.append((valor, hook_ref))

    def _stmt_block(self, stmt, frame: Frame) -> None:
        self._exec_block(stmt.block, Frame(parent=frame))

    def _stmt_var_decl(self, stmt, frame: Frame) -> None:
        vd = stmt.var_decl
        value = self.eval_expr(vd.value, frame) if vd.HasField("value") else None
        # ...misma regla que en los parámetros: ligar un struct a un nombre
        # nuevo lo COPIA. El único tipo que refiere a otro sitio es 'ptr'.
        frame.define(vd.name, Cell(copy_on_bind(value), name=vd.name))

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
            propio = Frame(parent=frame)
            if self._encaja(arm.pattern, subject, frame, propio):
                self.exec_stmt(arm.body, propio)
                return

    def _encaja(self, patron, subject, frame: Frame, propio: Frame) -> bool:
        """¿El patrón de una rama describe a ``subject``?

        Dos clases de patrón. La corriente es una EXPRESIÓN que se evalúa y se
        compara (``case 0``, ``case Color.ROJO``). La otra DESESTRUCTURA una
        variante (``case Nodo.Literal(v)``): ahí el patrón no se evalúa —sus
        argumentos son nombres que se van a LIGAR, no valores que leer—, se
        compara la variante y, si coincide, el payload entra en el frame de la
        rama. Que las dos formas se escriban igual es lo que evitó tener que
        inventar sintaxis de patrones.
        """
        ctor = self._constructor_de(patron, frame)
        if ctor is None:
            return self.eval_expr(patron, frame) == subject
        # DEREF IMPLICITO, igual que en '.campo': un arbol recursivo se
        # escribe con punteros ('Suma(Expr ptr, Expr ptr)'), asi que el sujeto
        # de un match casi siempre LLEGA como puntero. Exigir un deref
        # explicito haria imposible escribir el caso que motiva los tipos
        # suma.
        if isinstance(subject, Pointer):
            subject = subject.deref(ln=patron.ln, col=patron.col)
        if not isinstance(subject, EnumValue) or \
                subject.variant != ctor.variant or \
                subject.enum_name != ctor.enum_name:
            return False
        for arg, celda in zip(patron.call.args, subject.fields):
            if arg.WhichOneof("node") == "identifier":
                # se liga la CELDA, no una copia: mutar el payload dentro de
                # la rama se ve fuera, igual que con un campo de struct.
                propio.define(arg.identifier.name, celda)
        return True

    def _constructor_de(self, patron, frame: Frame):
        """El :class:`VariantCtor` que nombra un patrón, o ``None``.

        Se resuelve SIN evaluar los argumentos: evaluarlos es justo lo que no
        se puede hacer, porque todavía no están ligados.
        """
        if patron.WhichOneof("node") != "call":
            return None
        try:
            valor = self._eval_callee(patron.call.callee, frame)
        except SuriaXRuntimeError:
            return None
        return valor if isinstance(valor, VariantCtor) else None

    def _stmt_return(self, stmt, frame: Frame) -> None:
        node = stmt.return_stmt
        if not node.HasField("value"):
            raise _Return(None)
        value = self.eval_expr(node.value, frame)
        # DEVOLVER UN VALOR TRANSFIERE SU PROPIEDAD. Sin esto, el drop del
        # bloque destruiria lo que el llamador acaba de recibir. Solo aplica a
        # un nombre LOCAL: una global se devuelve prestada, no entregada.
        # Vale igual para un campo ('return a.b'): sin esto, el drop del
        # bloque bajaria a 'a.b' y destruiria lo que el llamador recibio.
        # 'transfers' lo decidio el frontend: solo es cierto si el valor
        # POSEE recursos. Devolver un 'int', o un campo de un receptor
        # PRESTADO, no transfiere nada — y marcarlo invalidaria un valor ajeno.
        cell = self._ruta_local(node.value, frame) if node.transfers else None
        if cell is not None and cell.state is CellState.LIVE:
            # 'move_out' es la API que comparten los dos backends de memoria
            # (el nativo expone 'state' como solo lectura).
            cell.move_out(ln=stmt.ln, col=stmt.col)
        raise _Return(value)

    def _ruta_local(self, expr, frame: Frame) -> Optional[Cell]:
        """La celda de una ruta ESTATICA (``a`` o ``a.b.c``) cuya raiz es un
        binding de esta llamada, o ``None``.

        Exigir que la raiz sea local no es un detalle: marcar como movida la
        celda de una global la dejaria inservible para el resto del programa.
        Una global se presta, no se entrega.
        """
        partes = []
        nodo = expr
        while True:
            which = nodo.WhichOneof("node")
            if which == "identifier":
                partes.append(nodo.identifier.name)
                break
            if which != "member":
                return None
            partes.append(nodo.member.member)
            nodo = nodo.member.obj
        partes.reverse()
        cell = self._celda_local(frame, partes[0])
        for campo in partes[1:]:
            if cell is None or cell.state is not CellState.LIVE:
                return None
            valor = cell.value
            if not isinstance(valor, StructValue):
                return None
            cell = valor.fields.get(campo)
        return cell

    def _celda_local(self, frame: Frame, name: str):
        """La celda de ``name`` si vive en ESTA llamada, no en el frame global.

        La distincion importa: marcar una global como movida al devolverla la
        dejaria inservible para el resto del programa."""
        globales = self.unit.globals_frame if self.unit is not None else None
        actual = frame
        while actual is not None and actual is not globales:
            cell = actual.cells.get(name)
            if cell is not None:
                return cell
            actual = actual.parent
        return None

    def _stmt_break(self, stmt, frame: Frame) -> None:
        raise _Break()

    def _stmt_continue(self, stmt, frame: Frame) -> None:
        raise _Continue()

    def _expr_move(self, expr, frame: Frame) -> Any:
        """``move x`` como EXPRESION: LEE el valor y luego invalida el origen.

        El orden importa: leer primero es lo que distingue esta forma de la
        sentencia. Una celda movida no se puede leer (``RT001``), así que
        invalidar antes se llevaría por delante el valor que hay que entregar.

        El valor se devuelve **sin copiar**: es el mismo objeto, que es
        justamente lo que significa transferirlo. Quien lo reciba lo liga tal
        cual — la copia de ``copy_on_bind`` solo aplica a lo que se comparte,
        y aquí no queda nadie con quien compartir.
        """
        target = expr.move_expr.operand
        value = self.eval_expr(target, frame)
        self._invalidar(target, frame, ln=expr.ln, col=expr.col)
        return value

    def _invalidar(self, target, frame: Frame, *, ln: int, col: int) -> None:
        """Marca como MOVIDA la celda que nombra ``target``.

        La comparten la sentencia y la expresión: las dos transfieren, y que
        el drop del bloque respete la transferencia no puede depender de en
        qué posición se escribió el ``move``.
        """
        if target.WhichOneof("node") == "identifier":
            cell = frame.lookup(target.identifier.name, ln=ln, col=col)
            cell.move_out(ln=ln, col=col)
            if self.trace:
                self.emit(f"[mem] move '{cell.name}' (celda invalidada)  "
                          f"{ln}:{col}")
            return
        # forma compuesta ('move p.x'): el CAMPO tiene su propia celda, asi
        # que la transferencia se marca ahi. Sin esto el drop del bloque
        # bajaria a ese campo y destruiria lo que ya se habia entregado.
        cell = self._ruta_local(target, frame)
        if cell is not None:
            cell.move_out(ln=ln, col=col)
            if self.trace:
                self.emit(f"[mem] move campo '{cell.name}' (celda invalidada)  "
                          f"{ln}:{col}")
            return
        # ruta dinamica ('move a[i].x'): sus lecturas si se verifican; el
        # rastreo fino queda para el MIR (mismo criterio que memory_check).
        self.eval_expr(target, frame)

    def _stmt_move(self, stmt, frame: Frame) -> None:
        self._invalidar(stmt.move_stmt.target, frame, ln=stmt.ln, col=stmt.col)

    def _stmt_free(self, stmt, frame: Frame) -> None:
        node = stmt.free_stmt
        value = self.eval_expr(node.target, frame)
        if not isinstance(value, Pointer):
            raise InvalidFreeError(
                f"'free' sobre un valor que no es puntero ({format_value(value)})",
                ln=stmt.ln, col=stmt.col,
            )
        if node.hook.owner_type:
            bound = self.image.hooks.get(ref_key(node.hook))
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
            for rama in node.catches:
                if not self._atrapa(rama, thrown.value):
                    continue
                # el binding de la rama vive SOLO en el scope de su bloque
                catch_frame = Frame(parent=frame)
                catch_frame.define(rama.name,
                                   Cell(thrown.value, name=rama.name))
                if self.trace:
                    self.emit(f"[err] catch '{rama.name}' = "
                              f"{format_value(thrown.value)}  "
                              f"{stmt.ln}:{stmt.col}")
                self._exec_block(rama.block, catch_frame)
                return
            # ninguna rama sabe manejarlo: sigue propagandose. Es lo que hace
            # util filtrar por tipo — un 'catch' que no entiende el fallo no
            # se lo queda.
            raise

    def _atrapa(self, rama, valor: Any) -> bool:
        """¿La rama ``catch`` acepta este valor?

        Sin tipo declarado, cualquiera. Con tipo, hay que preguntar en
        EJECUCION de que es el valor: ``throw`` acepta cualquier cosa, asi que
        el tipo dinamico del valor lanzado es lo unico que hay para decidir.
        """
        if not rama.HasField("type"):
            return True
        return self._es_de_tipo(valor, rama.type)

    def _es_de_tipo(self, valor: Any, tipo) -> bool:
        """¿``valor`` es del tipo ``tipo``? (prueba DINAMICA, solo para catch)

        Es la unica parte del intérprete que pregunta el tipo de un valor: en
        todo lo demas el frontend ya decidió. Aqui no puede, porque lo que
        lanzo el ``throw`` se sabe en ejecucion.
        """
        kind = tipo.kind
        if kind == _TK_NOMINAL:
            nombre = tipo.name.rsplit(".", 1)[-1]
            if isinstance(valor, StructValue):
                return valor.type_name.rsplit(".", 1)[-1] == nombre
            if isinstance(valor, EnumValue):
                return valor.enum_name.rsplit(".", 1)[-1] == nombre
            return False
        if kind == _TK_INT:
            return isinstance(valor, int) and not isinstance(valor, bool)
        if kind == _TK_STR:
            return isinstance(valor, str)
        if kind == _TK_BOOL:
            return isinstance(valor, bool)
        if kind == _TK_FLOAT:
            return isinstance(valor, float)
        if kind == _TK_CHAR:
            return isinstance(valor, str) and len(valor) == 1
        return False

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
        valor = handler(expr, frame)
        # un valor recien producido que POSEE recursos y que nadie recibe se
        # apila para destruirlo al cerrar la sentencia. Quien marco el nodo fue
        # el frontend; aqui solo se obedece.
        if which == "call":
            self._registrar_temporal(valor, expr.call.temp_drop)
        elif which == "struct_literal":
            self._registrar_temporal(valor, expr.struct_literal.temp_drop)
        return valor

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
        return self._arith(-operand)  # '-' (negar INT_MIN también desborda)

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

    @staticmethod
    def _wrap64(value: int) -> int:
        """El ``int`` de suriaX es de 64 bits CON SIGNO: envuelve al desbordar.

        Python no tiene ese límite, así que sin esto el intérprete daba
        9223372036854775808 donde el target web —que sí envuelve, con
        ``BigInt.asIntN(64, …)``— daba el mínimo negativo, y donde una VM
        nativa dará lo mismo que el web. Es el MISMO argumento que ya obligó
        a que ``%`` tome el signo del dividendo: dos targets del mismo
        programa no pueden dar números distintos.

        Y además evitaba un fallo peor: guardar el valor desbordado en una
        celda del backend nativo reventaba con un error de pybind11
        ("Unable to cast Python instance of type int to C++ type"), porque
        ahí una celda es un ``int64_t`` de verdad. Un error del binding no es
        un diagnóstico del lenguaje.
        """
        value &= 0xFFFFFFFFFFFFFFFF
        return value - 0x10000000000000000 if value >= 0x8000000000000000 else value

    @classmethod
    def _arith(cls, value: Any) -> Any:
        """Resultado de una operación aritmética, envuelto si es entero."""
        return cls._wrap64(value) if type(value) is int else value

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
            return self._arith(left + right)
        if op == "-":
            return self._arith(left - right)
        if op == "*":
            return self._arith(left * right)
        if op == "/":
            # división entera para ints (idioma 'i / 3 * 3 == i' de los
            # ejemplos); real para floats — el tipado fuerte ya garantizó
            # operandos homogéneos.
            #
            # Dividir por cero es un ERROR solo entre ENTEROS: ahí no hay
            # respuesta y la instrucción del hardware trapea. Entre flotantes
            # sí la hay y está en la norma que el lenguaje declara seguir —
            # IEEE-754 dice '1.0 / 0.0 == +inf'—, así que lanzar ahí inventaba
            # un error donde el target web (y cualquier FPU) daba un valor.
            if right == 0 and isinstance(left, int) \
                    and not isinstance(left, bool):
                raise DivisionByZeroError(
                    "división por cero", ln=expr.ln, col=expr.col)
            if isinstance(left, int) and not isinstance(left, bool):
                # TRUNCA HACIA CERO (como C y como 'i64.div_s', no como el
                # '//' de Python, que redondea hacia abajo): '-7 / 2' es -3,
                # no -4. Es la misma decisión que ya estaba tomada dos casos
                # más abajo para el resto — y tenía que serlo, porque las dos
                # operaciones se sostienen mutuamente: con este cociente y
                # aquel resto se cumple '(a/b)*b + a%b == a', que con el
                # cociente de Python NO se cumplía ('-9' en vez de '-7').
                cociente = abs(left) // abs(right)
                if (left < 0) != (right < 0):
                    cociente = -cociente
                # ...y la división también desborda, en un solo punto:
                # INT_MIN / -1 no cabe en 64 bits con signo.
                return self._wrap64(cociente)
            # IEEE-754 a mano: el '/' de Python lanza tambien entre flotantes,
            # asi que el infinito con signo (y el NaN de '0.0/0.0') se
            # construyen aqui. Es lo que hace la FPU y lo que ya hacia el
            # target web.
            if right == 0:
                if left == 0:
                    return math.nan
                signo = math.copysign(1.0, left) * math.copysign(1.0, right)
                return math.copysign(math.inf, signo)
            return left / right
        if op == "%":
            # resto CON EL SIGNO DEL DIVIDENDO (como C, no como Python):
            # '-7 % 3' es -1, no 2. El backend nativo bajará a la instrucción
            # de resto del hardware, que hace justo esto; si el intérprete
            # usara el '%' de Python, los dos targets darían números distintos
            # para el mismo programa.
            # mismo criterio que la división: entre flotantes, IEEE-754 da
            # NaN y no hay error que reportar.
            if right == 0 and isinstance(left, int) \
                    and not isinstance(left, bool):
                raise DivisionByZeroError(
                    "resto de una división por cero", ln=expr.ln, col=expr.col)
            if isinstance(left, int) and not isinstance(left, bool):
                resto = abs(left) % abs(right)
                return -resto if left < 0 else resto
            # 'fmod(x, 0.0)' lanza en Python; IEEE-754 dice NaN.
            return math.nan if right == 0 else math.fmod(left, right)
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
            bound = self.image.hooks.get(hook_key(left.type_name, self._eq_kind))
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
                bound = self.image.hooks.get(hook_key(base.type_name, self._index_set_kind))
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
            bound = self.image.hooks.get(ref_key(node.hook))
            if bound is not None:
                # forma 'x.hook(...)': el receptor es el PRIMER argumento y no
                # viaja en 'node.args'. Se detecta por aridad —al cuerpo le
                # falta exactamente un parámetro—, así que vale igual para
                # 'x.print()' (0 argumentos, 1 parámetro) que para un hook del
                # proyecto 'b.__gravity__(dt)' (1 y 2). Antes solo se cubría el
                # caso sin argumentos, y el primer argumento acababa ocupando
                # el sitio del receptor.
                es_miembro = callee.WhichOneof("node") == "member"
                falta_receptor = (es_miembro and
                                  len(node.args) + 1 == len(bound[1].params))
                args = []
                if falta_receptor:
                    # se evalúa ANTES que los argumentos: es el orden en que
                    # está escrito, y el receptor puede tener efectos.
                    args.append(self.eval_expr(callee.member.obj, frame))
                args.extend(self.eval_expr(a, frame) for a in node.args)
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
            # 'len(s)' sobre un 'str': NATIVO, no lo declara ninguna libreria.
            # Llega como una HookRef con dueño 'str' (la marca el frontend),
            # así que se reconoce por TIPO y no por el nombre de la llamada —
            # una 'fn len' del usuario nunca pasa por aquí.
            if node.hook.owner_type == "str" and \
                    node.hook.kind == self._len_kind:
                receptor = (callee.member.obj
                            if callee.WhichOneof("node") == "member"
                            else node.args[0])
                return len(self.eval_expr(receptor, frame))

        callee_value = self._eval_callee(node.callee, frame)
        args = [self.eval_expr(a, frame) for a in node.args]
        if isinstance(callee_value, VariantCtor):
            # 'Nodo.Literal(5)' construye el valor de la variante. El payload
            # va en celdas, como los campos de un struct: asi participa del
            # mismo modelo de memoria que todo lo demas.
            if len(args) != callee_value.arity:
                raise NotCallableError(
                    f"'{callee_value.enum_name}.{callee_value.variant}' lleva "
                    f"{callee_value.arity} valor(es), se pasaron {len(args)}",
                    ln=expr.ln, col=expr.col,
                )
            celdas = [Cell(v, name=f"{callee_value.variant}.{i}")
                      for i, v in enumerate(args)]
            return EnumValue(callee_value.enum_name, callee_value.variant,
                             celdas)
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
        # 's[i]' sobre una CADENA: nativo, igual que 'len(s)'. Una cadena es
        # inmutable y sus elementos son code points, asi que el indice cuenta
        # CARACTERES y no bytes — es lo mismo que cuenta 'len', y contar dos
        # cosas distintas con la misma cadena habria sido la trampa.
        if isinstance(base, str):
            if not isinstance(idx, int) or isinstance(idx, bool):
                raise IndexOutOfRangeError(
                    f"el indice de una cadena es un entero, no "
                    f"{format_value(idx)}", ln=expr.ln, col=expr.col)
            if idx < 0 or idx >= len(base):
                raise IndexOutOfRangeError(
                    f"indice {idx} fuera de la cadena (longitud {len(base)})",
                    ln=expr.ln, col=expr.col)
            return base[idx]
        if isinstance(base, StructValue):
            bound = self.image.hooks.get(hook_key(base.type_name, self._index_kind))
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
            bound = self.image.hooks.get(ref_key(node.hook))
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
        elif kind == _TK_STR and isinstance(value, (str, bool, int, float)):
            # primitivo -> 'str': la MISMA representacion que interpola un
            # f-string ('format_value'), y no 'str()' de Python, porque si
            # divergieran 'cast<str>(true)' y f"{true}" darian dos textos
            # distintos para el mismo valor.
            return value if isinstance(value, str) else format_value(value)

        # tabla de conversiones (__cast__): par (origen estático, destino).
        # El origen es el tipo de la expresión, que viaja como ÍNDICE en el
        # pool de su unidad (Expr.type_id); el destino va inline en el nodo.
        # Hace falta el par completo porque un tipo puede declarar VARIAS
        # conversiones ('int -> int8' y 'float -> int8'), y el HookRef del
        # nodo —(dueño, clase, nombre)— no las distingue.
        # 'cast<TType>(1)' hacia un ENUM sin payload: el valor ya ES el
        # entero, asi que la conversion no transforma nada — solo le pone
        # nombre, y el nombre es cosa de la compilacion. La Semantica ya
        # comprobo que el literal sea uno de los declarados; aqui no queda
        # trabajo. Va ANTES de la tabla para que un enum no necesite declarar
        # un '__cast__' que no haria nada.
        if self._es_enum(node.type) and isinstance(value, int) \
                and not isinstance(value, bool):
            return value

        destino = type_key(node.type)
        bound = self.image.casts.get((self._tipo_de(node.value), destino))
        if bound is not None:
            # un '__cast__' declarado como PROTOTIPO lo resuelve el host. No
            # sirve el registro por NOMBRE de 'call_function': todos se llaman
            # '__cast__' y lo que los distingue es el tipo DESTINO, que solo
            # se conoce aquí (mismo motivo por el que el par viaja en
            # 'image.casts' y no en el HookRef del nodo).
            if not bound[1].HasField("body"):
                nativa = intrinsics.lookup_cast(node.type.name)
                if nativa is not None:
                    try:
                        return nativa(value)
                    except SuriaXRuntimeError as exc:
                        exc.ln, exc.col = expr.ln, expr.col
                        raise
            return self.call_function(bound[0], bound[1], [value],
                                      ln=expr.ln, col=expr.col)
        raise InvalidCastRuntimeError(
            f"sin conversión registrada para este par (valor: "
            f"{format_value(value)})", ln=expr.ln, col=expr.col,
        )

    def _es_enum(self, tipo) -> bool:
        """¿``tipo`` nombra un enum SIN payload de la unidad activa?

        La respuesta esta en la tabla de simbolos que el HIR ya transporta
        (``Module.symbols.types``), asi que no hace falta un dato nuevo en el
        esquema ni que el frontend marque el nodo: el interprete pregunta lo
        mismo que pregunto la Semantica.
        """
        if tipo.kind != _TK_NOMINAL or not tipo.name:
            return False
        sym = self.unit.module.symbols.types.get(tipo.name)
        if sym is None or sym.kind != _SK_ENUM:
            return False
        # con payload el enum es un tipo suma: sus valores no son enteros.
        return not any(m.param_types for m in sym.members.values())

    def _tipo_de(self, expr):
        """Clave del tipo estático de ``expr``, resuelta contra el pool de la
        unidad activa. ``0`` = sin tipo anotado (el esquema lo permite), y
        entonces no hay clave que buscar."""
        if not expr.type_id:
            return None
        return type_key(self.unit.module.types[expr.type_id])

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
