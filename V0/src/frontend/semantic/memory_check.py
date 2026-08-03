"""Pasada 4 — Verificación LIGERA de move-semantics (intra-función).

Implementa exactamente el punto intermedio deliberado de
``ARQUITECTURA.md`` secc. 4: una pasada lineal O(n), conservadora, SIN punto
fijo y SIN análisis inter-función. Detecta los errores lineales y obvios
(el caso típico del público objetivo educativo):

 - ``move x;`` seguido de un uso de ``x`` en el mismo camino ->
   ``UseAfterMoveError`` (SEM004);
 - ``move x;`` dos veces -> ``DoubleMoveError`` (SEM005);
 - en ``if``/``else`` y ``match`` cada rama se analiza con una COPIA del
   conjunto ``moved``; al cerrar, el resultado es la UNIÓN conservadora
   (movido en alguna rama => tratado como movido después, nunca al revés);
 - un ``while`` se analiza con una sola pasada de su cuerpo (sin iterar
   hasta punto fijo): el move de una iteración anterior es un falso
   negativo ACEPTADO — el MIR (C++) hace la verificación definitiva.

Identidad por NOMBRE de símbolo, no por tipo (independiente de la Fase 3):
volver a declarar (``int x = ...;``) o reasignar (``x = ...;``) un nombre lo
"revive" — un binding nuevo/valor nuevo no está movido. Esto elimina los
falsos positivos por shadowing sin construir scopes de nuevo.

**Nunca rechaza un programa válido** (cero falsos positivos); sí puede
dejar pasar lo que el MIR rechazará después (falsos negativos documentados).

``Symbol.moved_at`` se anota en sitio sobre los símbolos que la pasada 3
publicó en ``ctx.fn_locals`` (secc. 4.4: mutación en sitio, cero
estructuras duplicadas).
"""

from __future__ import annotations

from typing import Dict, List, Optional

try:
    from include import ast_nodes as ast
    from include.ast_walk import child_fields
    from error_handler import SemanticError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from include.ast_walk import child_fields  # type: ignore
    import SemanticError  # type: ignore

from .context import SemanticContext
from .symbol_table import Symbol

# PATH movido -> linea del 'move'. Una clave es un nombre simple ('x') o una
# cadena de campos ('o.it', 'o.it.v'): mover 'o.it' invalida 'o.it' y todo lo
# que cuelga de el ('o.it.v'), pero NO 'o' entero ni sus hermanos ('o.other').
# Solo cadenas ESTATICAS (Identifier + MemberAccess); el indexado 'a[i]' es
# dinamico y no se rastrea aqui (queda para el MIR) — asi no hay falsos
# positivos por no distinguir 'a[0]' de 'a[1]'.
_Moved = Dict[str, int]


def _path(expr) -> Optional[str]:
    """La ruta estatica de ``expr`` (``o.it.v``) o ``None`` si no es una cadena
    pura de campo (contiene indexado, deref dinamico, una llamada, etc.)."""
    parts: List[str] = []
    node = expr
    while True:
        if isinstance(node, ast.Identifier):
            parts.append(node.name)
            parts.reverse()
            return ".".join(parts)
        if isinstance(node, ast.MemberAccess):
            parts.append(node.member)
            node = node.obj
            continue
        return None


def _moved_ancestor(moved: _Moved, path: str) -> Optional[int]:
    """La línea del ``move`` si ``path`` —o algún ANCESTRO suyo— está movido
    (mover ``o`` invalida ``o.it``; mover ``o.it`` invalida ``o.it.v``).
    Nunca al revés: mover ``o.it`` NO invalida el padre ``o`` (conservador)."""
    prefix = path
    while True:
        line = moved.get(prefix)
        if line is not None:
            return line
        cut = prefix.rfind(".")
        if cut == -1:
            return None
        prefix = prefix[:cut]


def _revive(moved: _Moved, base: str) -> None:
    """Un binding/valor NUEVO en ``base`` lo revive junto con sus descendientes
    (reasignar ``o`` revive ``o.it``; reasignar ``o.it`` revive ``o.it.v``)."""
    moved.pop(base, None)
    dead = [k for k in moved if k.startswith(base + ".")]
    for key in dead:
        del moved[key]


def run(program: ast.Program, ctx: SemanticContext) -> None:
    for item in program.items:
        if isinstance(item, ast.DecoratorDecl):
            item = item.target
        if isinstance(item, ast.FunctionDecl) and item.body is not None:
            # prototipo (body None): sin cuerpo no hay moves que verificar.
            checker = _MoveChecker(ctx, ctx.fn_locals.get(id(item), {}))
            checker.check_block(item.body.statements, {})
        elif isinstance(item, ast.TestDecl):
            # el cuerpo de un 'test' se verifica igual que una funcion
            # (scope_resolver no publico sus locales; el checker no los
            # necesita -- solo rastrea nombres movidos).
            _MoveChecker(ctx, {}).check_block(item.body.statements, {})


class _MoveChecker:
    __slots__ = ("ctx", "locals")

    def __init__(self, ctx: SemanticContext, fn_locals: Dict[str, Symbol]) -> None:
        self.ctx = ctx
        self.locals = fn_locals

    # ------------------------------------------------------------------ #
    # statements (camino lineal; las ramas copian y unen 'moved')
    # ------------------------------------------------------------------ #
    def check_block(self, statements: List[ast.Statement], moved: _Moved) -> None:
        for stmt in statements:
            self.check_stmt(stmt, moved)

    def check_stmt(self, stmt: ast.Statement, moved: _Moved) -> None:
        cls = stmt.__class__

        if cls is ast.MoveStmt:
            target = stmt.target
            path = _path(target)
            if path is not None:
                # variable completa ('x') o campo estatico ('o.it'): se rastrea.
                prev = _moved_ancestor(moved, path)
                if prev is not None:
                    self.ctx.error(SemanticError.DoubleMoveError(
                        f"'{path}' ya fue movido (línea {prev})",
                        line=stmt.ln, column=stmt.col,
                    ))
                    return
                moved[path] = stmt.ln
                # solo la variable completa tiene un Symbol que anotar (moved_at
                # viaja al HIR); un campo movido lo rastrea solo esta pasada.
                if isinstance(target, ast.Identifier):
                    symbol = self.locals.get(target.name)
                    if symbol is not None:
                        symbol.moved_at = stmt.ln
            else:
                # 'move a[i].x;' u otra forma dinamica: sus lecturas si se
                # verifican; el tracking fino queda para el MIR.
                self.check_expr(target, moved)
            return

        if cls is ast.ExprStmt:
            self.check_expr(stmt.expr, moved)
        elif cls is ast.VarDecl:
            if stmt.value is not None:
                self.check_expr(stmt.value, moved)
            _revive(moved, stmt.name)  # binding nuevo: revive el nombre y campos
        elif cls is ast.Block:
            self.check_block(stmt.statements, moved)
        elif cls is ast.RegionStmt:
            self.check_block(stmt.body.statements, moved)
        elif cls is ast.InRegionStmt:
            # 'in region r { ... }' puede contener moves; new/delete/
            # move-region no leen identificadores movidos (se ignoran).
            self.check_stmt(stmt.body, moved)
        elif cls is ast.IfStmt:
            self.check_expr(stmt.condition, moved)
            then_moved = dict(moved)
            self.check_block(stmt.then_block.statements, then_moved)
            else_moved = dict(moved)
            branch = stmt.else_branch
            if branch is not None:
                if isinstance(branch, ast.IfStmt):
                    self.check_stmt(branch, else_moved)
                else:
                    self.check_block(branch.statements, else_moved)
            # union conservadora: movido en ALGUNA rama => movido despues
            moved.update(then_moved)
            moved.update(else_moved)
        elif cls is ast.WhileStmt:
            self.check_expr(stmt.condition, moved)
            self.check_block(stmt.body.statements, moved)  # una sola pasada
        elif cls is ast.MatchStmt:
            self.check_expr(stmt.subject, moved)
            arm_results: List[_Moved] = []
            for arm in stmt.cases:
                arm_moved = dict(moved)
                self.check_expr(arm.pattern, arm_moved)
                self.check_stmt(arm.body, arm_moved)
                arm_results.append(arm_moved)
            for result in arm_results:
                moved.update(result)
        elif cls is ast.ReturnStmt:
            if stmt.value is not None:
                self.check_expr(stmt.value, moved)
        elif cls is ast.FreeStmt:
            self.check_expr(stmt.target, moved)
        elif cls is ast.ThrowStmt:
            self.check_expr(stmt.value, moved)
        elif cls is ast.TryStmt:
            # el try y el catch son caminos alternativos: cada uno parte del
            # 'moved' de entrada (copia) y al cerrar se unen conservadoramente
            # (mismo criterio que if/else).
            try_moved = dict(moved)
            self.check_block(stmt.try_block.statements, try_moved)
            catch_moved = dict(moved)
            self.check_block(stmt.catch_block.statements, catch_moved)
            moved.update(try_moved)
            moved.update(catch_moved)
        # Break/Continue/ImportBinding: sin expresiones que verificar

    # ------------------------------------------------------------------ #
    # expresiones: toda lectura de un Identifier movido es un error
    # ------------------------------------------------------------------ #
    def check_expr(self, expr, moved: _Moved) -> None:
        cls = expr.__class__

        if cls is ast.Identifier:
            prev = _moved_ancestor(moved, expr.name)
            if prev is not None:
                self.ctx.error(SemanticError.UseAfterMoveError(
                    f"'{expr.name}' se usa después de 'move' (línea {prev})",
                    line=expr.ln, column=expr.col,
                ))
            return

        if cls is ast.Assignment:
            self.check_expr(expr.value, moved)
            target = expr.target
            if isinstance(target, ast.Identifier):
                # reasignar da un valor NUEVO: el nombre (y sus campos) revive
                # — y escribirlo no es leerlo, no se reporta use-after-move.
                _revive(moved, target.name)
            else:
                path = _path(target)
                if path is not None:
                    # 'o.it = ...' revive ese campo: valor nuevo, no movido.
                    _revive(moved, path)
                else:
                    self.check_expr(target, moved)
            return

        if cls is ast.MemberAccess:
            path = _path(expr)
            if path is not None:
                prev = _moved_ancestor(moved, path)
                if prev is not None:
                    self.ctx.error(SemanticError.UseAfterMoveError(
                        f"'{path}' se usa después de 'move' (línea {prev})",
                        line=expr.ln, column=expr.col,
                    ))
                return
            # ruta dinamica ('a[i].x'): recursion generica de abajo.

        # recursion generica: mismos campos-hijo cacheados que ast_walk
        for name in child_fields(cls):
            child = getattr(expr, name)
            if child.__class__ is list:
                for item in child:
                    if isinstance(item, ast.ASTNode):
                        self.check_expr(item, moved)
            elif isinstance(child, ast.ASTNode):
                self.check_expr(child, moved)


__all__ = ["run"]
