"""Pasada 3 — Verificación LIGERA de la PROPIEDAD (intra-función).

Implementa exactamente el punto intermedio deliberado de
``ARQUITECTURA.md`` secc. 4: una pasada lineal O(n), conservadora, SIN punto
fijo y SIN análisis inter-función. Detecta los errores lineales y obvios
(el caso típico del público objetivo educativo):

 - ``move x;`` seguido de un uso de ``x`` en el mismo camino ->
   ``UseAfterMoveError`` (SEM004);
 - ``move x;`` dos veces -> ``DoubleMoveError`` (SEM005);
 - ``free x;`` seguido de un uso de ``x`` -> ``UseAfterFreeError`` (SEM023);
 - ``free x;`` dos veces -> ``DoubleFreeError`` (SEM024);
 - en ``if``/``else`` y ``match`` cada rama se analiza con una COPIA del
   conjunto ``muertos``; al cerrar, el resultado es la UNIÓN conservadora
   (movido en alguna rama => tratado como movido después, nunca al revés);
 - un ``while`` se analiza con una sola pasada de su cuerpo (sin iterar
   hasta punto fijo): el move de una iteración anterior es un falso
   negativo ACEPTADO — el MIR (C++) hace la verificación definitiva.

``move`` y ``free`` se rastrean JUNTOS porque son la misma cosa vista de dos
formas: las dos terminan una propiedad, una transfiriéndola y la otra
destruyendo el valor. Un solo conjunto de rutas muertas, con el MOTIVO
guardado — que es lo que decide el diagnóstico (ver ``_ya_no_es_suyo``).

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

from typing import Dict, List, Optional, Tuple

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

# PATH cuyo dueno ya solto el valor -> (MOTIVO, linea). Una clave es un nombre simple ('x') o una
# cadena de campos ('o.it', 'o.it.v'): mover 'o.it' invalida 'o.it' y todo lo
# que cuelga de el ('o.it.v'), pero NO 'o' entero ni sus hermanos ('o.other').
# Solo cadenas ESTATICAS (Identifier + MemberAccess); el indexado 'a[i]' es
# dinamico y no se rastrea aqui (queda para el MIR) — asi no hay falsos
# positivos por no distinguir 'a[0]' de 'a[1]'.
#: motivos por los que un valor deja de ser utilizable. Son dos porque son
#: las dos formas que tiene el lenguaje de terminar una propiedad: 'move' la
#: TRANSFIERE y 'free' la DESTRUYE. El motivo se guarda —en vez de un simple
#: "ya no vale"— porque decide que diagnostico se reporta: usar algo movido y
#: usar algo liberado son errores distintos y se arreglan distinto.
MOVIDO = "move"
LIBERADO = "free"

_Fin = Tuple[str, int]      # (motivo, linea donde ocurrio)
_Muertos = Dict[str, _Fin]


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


def _fin_de_ancestro(muertos: _Muertos, path: str) -> Optional[_Fin]:
    """El ``(motivo, línea)`` si ``path`` —o algún ANCESTRO suyo— dejó de ser
    utilizable (soltar ``o`` invalida ``o.it``; soltar ``o.it`` invalida
    ``o.it.v``). Nunca al revés: soltar ``o.it`` NO invalida el padre ``o``
    (conservador)."""
    prefix = path
    while True:
        fin = muertos.get(prefix)
        if fin is not None:
            return fin
        cut = prefix.rfind(".")
        if cut == -1:
            return None
        prefix = prefix[:cut]


def _sale(statements) -> bool:
    """¿El bloque termina SALIENDO (``return`` o ``throw``)? Entonces lo que
    movio no llega a la sentencia siguiente: por ese camino no hay siguiente.

    Sin esto, ``if (b) { throw r; }; usa(r);`` era SEM004: la union
    conservadora del ``if`` sumaba el ``move`` de una rama que no continua.
    (``break``/``continue`` no cuentan: su camino sigue despues del bucle.)
    """
    return bool(statements) and isinstance(
        statements[-1], (ast.ReturnStmt, ast.ThrowStmt))


def _revive(muertos: _Muertos, base: str) -> None:
    """Un binding/valor NUEVO en ``base`` lo revive junto con sus descendientes
    (reasignar ``o`` revive ``o.it``; reasignar ``o.it`` revive ``o.it.v``)."""
    muertos.pop(base, None)
    dead = [k for k in muertos if k.startswith(base + ".")]
    for key in dead:
        del muertos[key]


def run(program: ast.Program, ctx: SemanticContext) -> None:
    for item in program.items:
        if isinstance(item, ast.DecoratorDecl):
            item = item.target
        if isinstance(item, ast.FunctionDecl) and item.body is not None:
            # prototipo (body None): sin cuerpo no hay moves que verificar.
            checker = _PropiedadChecker(ctx, ctx.fn_locals.get(id(item), {}))
            checker.check_block(item.body.statements, {})
        elif isinstance(item, ast.TestDecl):
            # el cuerpo de un 'test' se verifica igual que una funcion
            # (scope_resolver no publico sus locales; el checker no los
            # necesita -- solo rastrea nombres movidos).
            _PropiedadChecker(ctx, {}).check_block(item.body.statements, {})


class _PropiedadChecker:
    __slots__ = ("ctx", "locals")

    def __init__(self, ctx: SemanticContext, fn_locals: Dict[str, Symbol]) -> None:
        self.ctx = ctx
        self.locals = fn_locals

    # ------------------------------------------------------------------ #
    # statements (camino lineal; las ramas copian y unen 'muertos')
    # ------------------------------------------------------------------ #
    def check_block(self, statements: List[ast.Statement], muertos: _Muertos) -> None:
        for stmt in statements:
            self.check_stmt(stmt, muertos)

    def check_stmt(self, stmt: ast.Statement, muertos: _Muertos) -> None:
        cls = stmt.__class__

        if cls is ast.MoveStmt:
            self._marca_movido(stmt.target, stmt, muertos)
            return
            return

        if cls is ast.ExprStmt:
            self.check_expr(stmt.expr, muertos)
        elif cls is ast.VarDecl:
            if stmt.value is not None:
                self.check_expr(stmt.value, muertos)
            _revive(muertos, stmt.name)  # binding nuevo: revive el nombre y campos
        elif cls is ast.Block:
            self.check_block(stmt.statements, muertos)
        elif cls is ast.IfStmt:
            self.check_expr(stmt.condition, muertos)
            then_muertos = dict(muertos)
            self.check_block(stmt.then_block.statements, then_muertos)
            else_muertos = dict(muertos)
            branch = stmt.else_branch
            if branch is not None:
                if isinstance(branch, ast.IfStmt):
                    self.check_stmt(branch, else_muertos)
                else:
                    self.check_block(branch.statements, else_muertos)
            # union conservadora: movido en ALGUNA rama => movido despues
            # (salvo en una rama que sale: por ella no hay "despues")
            if not _sale(stmt.then_block.statements):
                muertos.update(then_muertos)
            if branch is None or isinstance(branch, ast.IfStmt) \
                    or not _sale(branch.statements):
                muertos.update(else_muertos)
        elif cls is ast.WhileStmt:
            self.check_expr(stmt.condition, muertos)
            self.check_block(stmt.body.statements, muertos)  # una sola pasada
        elif cls is ast.MatchStmt:
            self.check_expr(stmt.subject, muertos)
            arm_results: List[_Muertos] = []
            for arm in stmt.cases:
                arm_muertos = dict(muertos)
                self.check_expr(arm.pattern, arm_muertos)
                self.check_stmt(arm.body, arm_muertos)
                arm_results.append(arm_muertos)
            for result in arm_results:
                muertos.update(result)
        elif cls is ast.ReturnStmt:
            if stmt.value is not None:
                self.check_expr(stmt.value, muertos)
        elif cls is ast.FreeStmt:
            target = stmt.target
            path = _path(target)
            if path is not None:
                fin = _fin_de_ancestro(muertos, path)
                if fin is not None:
                    self._ya_no_es_suyo(path, fin, LIBERADO, stmt)
                    return
                muertos[path] = (LIBERADO, stmt.ln)
            else:
                # 'free a[i].x;': la lectura si se verifica; el rastreo fino
                # de una ruta dinamica queda para el MIR (igual que 'move').
                self.check_expr(target, muertos)
        elif cls is ast.ThrowStmt:
            self.check_expr(stmt.value, muertos)
        elif cls is ast.TryStmt:
            # el try y el catch son caminos alternativos: cada uno parte del
            # 'muertos' de entrada (copia) y al cerrar se unen conservadoramente
            # (mismo criterio que if/else).
            # El catch parte de la ENTRADA del try, no de su final: el throw
            # pudo saltar antes de cualquier 'move' del try. Partir del final
            # (como se hacia) rechazaba un programa valido —'try {
            # verifica(); toma(move r); } catch (int e) { usa r }'— con
            # SEM004; si el move si ocurrio, lo caza la ejecucion (RT001).
            entrada = dict(muertos)
            try_muertos = dict(muertos)
            self.check_block(stmt.try_block.statements, try_muertos)
            muertos.update(try_muertos)
            for clausula in stmt.catches:
                rama = dict(entrada)
                # 'catch (R r)' liga un valor NUEVO (el lanzado), como un
                # 'var': revive el nombre. Sin esto, 'throw move r;' dentro
                # del try dejaba el 'r' del catch "movido" (SEM004 falso).
                _revive(rama, clausula.name)
                self.check_block(clausula.block.statements, rama)
                muertos.update(rama)
            # el 'finally' corre despues de CUALQUIERA de los caminos: parte
            # de su union (lo que cualquiera pudo haber movido)
            if stmt.finally_block is not None:
                self.check_block(stmt.finally_block.statements, muertos)
        # Break/Continue/ImportBinding: sin expresiones que verificar

    # ------------------------------------------------------------------ #
    # diagnostico
    # ------------------------------------------------------------------ #
    def _uso(self, path: str, fin: _Fin, nodo) -> None:
        """Una LECTURA de un valor que su dueno ya solto."""
        motivo, linea = fin
        if motivo is MOVIDO:
            self.ctx.error(SemanticError.UseAfterMoveError(
                f"'{path}' se usa después de 'move' (línea {linea})",
                line=nodo.ln, column=nodo.col))
        else:
            self.ctx.error(SemanticError.UseAfterFreeError(
                f"'{path}' se usa después de 'free' (línea {linea})",
                line=nodo.ln, column=nodo.col))

    def _ya_no_es_suyo(self, path: str, fin: _Fin, operacion: str, nodo) -> None:
        r"""Reporta una operacion sobre un valor que su dueno ya solto.

        QUE codigo se emite lo decide el MOTIVO por el que murio, no la
        operacion que lo encontro: usar algo movido y usar algo liberado son
        problemas distintos y se arreglan distinto (uno se recupera del nuevo
        dueno, el otro no se recupera). La operacion solo decide si ademas es
        un DOBLE de lo mismo, que merece su propio mensaje:

            operacion \ motivo   movido            liberado
            leer / move          SEM004 / SEM005   SEM023
            free                 SEM004            SEM024
        """
        motivo, linea = fin
        doble = (motivo == operacion)
        if motivo is MOVIDO:
            if doble:
                self.ctx.error(SemanticError.DoubleMoveError(
                    f"'{path}' ya fue movido (línea {linea})",
                    line=nodo.ln, column=nodo.col))
            else:
                self.ctx.error(SemanticError.UseAfterMoveError(
                    f"'{path}' se movió en la línea {linea}: ya no es su valor, "
                    f"no se puede liberar desde aquí (lo libera su nuevo dueño)",
                    line=nodo.ln, column=nodo.col))
        elif doble:
            self.ctx.error(SemanticError.DoubleFreeError(
                f"'{path}' ya fue liberado (línea {linea})",
                line=nodo.ln, column=nodo.col))
        else:
            self.ctx.error(SemanticError.UseAfterFreeError(
                f"'{path}' se liberó en la línea {linea}: ya no existe",
                line=nodo.ln, column=nodo.col))

    # ------------------------------------------------------------------ #
    # expresiones: toda lectura de un valor ya soltado es un error
    # ------------------------------------------------------------------ #
    def _marca_movido(self, target, node, muertos: _Muertos) -> None:
        """Anota que ``target`` dejó de pertenecer a quien lo nombraba.

        Lo comparten la sentencia (``move x;``) y la expresión
        (``var b = move x;``): las dos transfieren, y que use-after-move
        (SEM004) o doble move (SEM005) salten no puede depender de en qué
        posición se escribió el ``move``.
        """
        path = _path(target)
        if path is None:
            # 'move a[i].x' u otra forma dinámica: sus lecturas sí se
            # verifican; el tracking fino queda para el MIR.
            self.check_expr(target, muertos)
            return
        # variable completa ('x') o campo estático ('o.it'): se rastrea.
        fin = _fin_de_ancestro(muertos, path)
        if fin is not None:
            self._ya_no_es_suyo(path, fin, MOVIDO, node)
            return
        muertos[path] = (MOVIDO, node.ln)
        # solo la variable completa tiene un Symbol que anotar (moved_at viaja
        # al HIR); un campo movido lo rastrea solo esta pasada.
        if isinstance(target, ast.Identifier):
            symbol = self.locals.get(target.name)
            if symbol is not None:
                symbol.moved_at = node.ln

    def check_expr(self, expr, muertos: _Muertos) -> None:
        cls = expr.__class__

        if cls is ast.MoveExpr:
            # 'move x' en una expresión invalida igual que la sentencia: el
            # valor se va a otro sitio. Comparten la marca para que
            # use-after-move (SEM004) y doble move (SEM005) no dependan de en
            # qué posición se escribió el 'move'.
            self._marca_movido(expr.operand, expr, muertos)
            return

        if cls is ast.Identifier:
            fin = _fin_de_ancestro(muertos, expr.name)
            if fin is not None:
                self._uso(expr.name, fin, expr)
            return

        if cls is ast.Assignment:
            self.check_expr(expr.value, muertos)
            target = expr.target
            if isinstance(target, ast.Identifier):
                # reasignar da un valor NUEVO: el nombre (y sus campos) revive
                # — y escribirlo no es leerlo, no se reporta use-after-move.
                _revive(muertos, target.name)
            else:
                path = _path(target)
                if path is not None:
                    # 'o.it = ...' revive ese campo: valor nuevo, no movido.
                    _revive(muertos, path)
                else:
                    self.check_expr(target, muertos)
            return

        if cls is ast.MemberAccess:
            path = _path(expr)
            if path is not None:
                fin = _fin_de_ancestro(muertos, path)
                if fin is not None:
                    self._uso(path, fin, expr)
                return
            # ruta dinamica ('a[i].x'): recursion generica de abajo.

        # recursion generica: mismos campos-hijo cacheados que ast_walk
        for name in child_fields(cls):
            child = getattr(expr, name)
            if child.__class__ is list:
                for item in child:
                    if isinstance(item, ast.ASTNode):
                        self.check_expr(item, muertos)
            elif isinstance(child, ast.ASTNode):
                self.check_expr(child, muertos)


__all__ = ["run"]
