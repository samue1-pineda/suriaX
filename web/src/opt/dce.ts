/**
 * DCE — *dead code elimination* sobre el HIR.
 *
 * Primera optimización del target web. Corre sobre el HIR **ya
 * deserializado y ya validado por la política**, antes del codegen, y
 * devuelve un módulo NUEVO (el de entrada no se toca: las pasadas se
 * encadenan sin que ninguna pise a la anterior).
 *
 * Elimina cuatro cosas, en orden de rentabilidad:
 *
 *  1. **declaraciones inalcanzables** — funciones, structs y enums que
 *     ningún camino desde las raíces referencia. En el web esto es lo que
 *     más pesa: una librería aporta su unidad entera y el programa usa tres
 *     funciones;
 *  2. **código tras un terminador** — lo que sigue a `return`/`break`/
 *     `continue`/`throw` dentro del mismo bloque no se ejecuta nunca;
 *  3. **expresiones-sentencia sin efectos** — `x + 1;` como sentencia;
 *  4. **variables locales nunca leídas** con inicializador puro.
 *
 * ### Qué NO hace (a propósito)
 * No pliega condiciones constantes ni propaga copias: eso es otra pasada,
 * con otras pruebas. Y sobre todo, **no adivina pureza**: toda llamada es
 * impura, y también lo es todo lo que pueda despachar un hook de usuario
 * (`v[i]` -> `__index__`, `a == b` entre nominales -> `__eq__`,
 * `cast<T>(x)` con `__cast__`). Un DCE que se equivoca no "optimiza de
 * más": borra un `print`.
 *
 * ### Punto fijo
 * Borrar una sentencia puede dejar muerta una variable, y borrar una
 * función puede dejar inalcanzable a otra. Las rondas se repiten hasta que
 * nada cambia (con tope, {@link DEFAULT_MAX_ROUNDS}); en la práctica
 * convergen en dos o tres.
 */

import {
  TypeKind,
  type Block,
  type Decl,
  type Expr,
  type FunctionDecl,
  type IfStmt,
  type Module,
  type Stmt,
  type SymbolInfo,
  type SymbolTable,
  type Type,
} from "../hir/schema.ts";
import { SymbolKind } from "../hir/schema.ts";
import { Image, Unit } from "../hir/link.ts";

/** Tope de rondas de punto fijo. */
export const DEFAULT_MAX_ROUNDS = 8;

export interface DceOptions {
  /** Función de entrada. `"main"` por defecto. */
  readonly entry?: string;
  /**
   * Nombres que hay que conservar aunque nadie los referencie desde este
   * módulo: los exports que otra unidad usa. Si se omite en una unidad de
   * librería (la que trae un `#export`), se conservan TODAS sus funciones —
   * la visibilidad (`public`/`private`) no viaja en el HIR v1, así que el
   * único supuesto seguro es que cualquiera puede ser llamada desde fuera.
   * Usa {@link crossUnitRoots} para calcular la lista exacta.
   */
  readonly roots?: readonly string[];
  /** Conservar los bloques `test "..." { }`. `false` por defecto. */
  readonly keepTests?: boolean;
  /**
   * Conservar todo cuerpo de hook cuyo tipo dueño sobreviva. `true` por
   * defecto: los hooks se despachan dinámicamente (`print(x)` decide en
   * runtime), así que la alcanzabilidad estática no los ve.
   */
  readonly keepHooks?: boolean;
  readonly maxRounds?: number;
}

/** Qué se eliminó (para el reporte de la CLI y para los tests). */
export interface DceStats {
  readonly functions: number;
  readonly structs: number;
  readonly enums: number;
  readonly tests: number;
  /** Sentencias tras un terminador. */
  readonly unreachableStatements: number;
  /** `ExprStmt` sin efectos observables. */
  readonly pureStatements: number;
  /** `VarDecl` locales nunca leídas. */
  readonly deadVars: number;
  /** Símbolos retirados de la tabla. */
  readonly symbols: number;
  readonly rounds: number;
  /** Nombres de las declaraciones eliminadas, en orden. */
  readonly removed: readonly string[];
}

export interface DceResult {
  readonly module: Module;
  readonly stats: DceStats;
}

interface Counters {
  functions: number;
  structs: number;
  enums: number;
  tests: number;
  unreachableStatements: number;
  pureStatements: number;
  deadVars: number;
  symbols: number;
  removed: string[];
}

function newCounters(): Counters {
  return {
    functions: 0, structs: 0, enums: 0, tests: 0,
    unreachableStatements: 0, pureStatements: 0, deadVars: 0, symbols: 0,
    removed: [],
  };
}

// --------------------------------------------------------------------------- //
// pureza
// --------------------------------------------------------------------------- //

const PRIMITIVE_KINDS: ReadonlySet<TypeKind> = new Set([
  TypeKind.VOID, TypeKind.BOOL, TypeKind.INT,
  TypeKind.FLOAT, TypeKind.CHAR, TypeKind.STR,
]);

/**
 * ¿El tipo es primitivo? Un operando nominal puede disparar un hook de
 * usuario (`__eq__`, `__cast__`), así que la operación deja de ser pura. Un
 * tipo ausente (`null`) cuenta como NO primitivo: sin información, se
 * conserva.
 */
function isPrimitive(type: Type | null): boolean {
  return type !== null && PRIMITIVE_KINDS.has(type.kind);
}

/**
 * ¿Evaluar esta expresión es observable? Conservador por construcción: solo
 * devuelve `true` para lo que con seguridad no llama a nada ni escribe nada.
 */
export function isPure(expr: Expr): boolean {
  const node = expr.node;
  switch (node.case) {
    case "literal":
    case "identifier":
      return true;
    case "member":
      return isPure(node.obj);
    case "addrOf":
      return isPure(node.operand);
    case "unary":
      return isPure(node.operand) && isPrimitive(node.operand.restype);
    case "binary":
      // '==' entre nominales despacha '__eq__': solo es puro entre primitivos.
      return (
        isPure(node.left) && isPure(node.right) &&
        isPrimitive(node.left.restype) && isPrimitive(node.right.restype)
      );
    case "interp":
      return node.parts.every(
        (p) => p.case === "text" || (isPure(p.expr) && isPrimitive(p.expr.restype)),
      );
    case "structLiteral":
      return node.values.every(isPure);
    case "cast":
      // con hook '__cast__' hay una llamada de usuario detrás.
      return node.hook === null && isPure(node.value);
    case "sizeof":
      return node.hook === null;
    case "index":      // puede despachar '__index__'
    case "call":       // cualquier efecto
    case "assignment": // escribe
    case "none":       // nodo malformado: no se toca
      return false;
  }
}

/** ¿La sentencia corta el flujo del bloque que la contiene? */
function isTerminator(stmt: Stmt): boolean {
  switch (stmt.node.case) {
    case "return":
    case "break":
    case "continue":
    case "throw":
      return true;
    default:
      return false;
  }
}

// --------------------------------------------------------------------------- //
// lecturas de variables
// --------------------------------------------------------------------------- //

interface NameUse {
  /** Cuántas veces se LEE cada nombre (el destino de una asignación cuenta). */
  readonly reads: Map<string, number>;
  /** Cuántas veces se DECLARA cada nombre (>1 = sombreado: no se toca). */
  readonly decls: Map<string, number>;
}

function bump(map: Map<string, number>, name: string): void {
  map.set(name, (map.get(name) ?? 0) + 1);
}

/**
 * Cuenta usos de nombres en un cuerpo de función.
 *
 * El destino de una asignación se cuenta como LECTURA a propósito: si `x`
 * se asigna en algún sitio, conservar su declaración es lo correcto (la
 * alternativa —borrar la variable y todas sus escrituras— exige un análisis
 * de flujo que esta pasada no hace).
 */
function collectUses(block: Block, uses: NameUse): void {
  for (const stmt of block.statements) collectStmtUses(stmt, uses);
}

function collectStmtUses(stmt: Stmt, uses: NameUse): void {
  const node = stmt.node;
  switch (node.case) {
    case "block":
      collectUses(node.block, uses);
      return;
    case "varDecl":
      bump(uses.decls, node.name);
      if (node.value !== null) collectExprUses(node.value, uses);
      return;
    case "typeDecl":
      bump(uses.decls, node.name);
      if (node.value !== null) collectExprUses(node.value, uses);
      return;
    case "if":
      collectIfUses(node.ifStmt, uses);
      return;
    case "while":
      collectExprUses(node.condition, uses);
      collectUses(node.body, uses);
      return;
    case "match":
      collectExprUses(node.subject, uses);
      for (const arm of node.cases) {
        collectExprUses(arm.pattern, uses);
        collectStmtUses(arm.body, uses);
      }
      return;
    case "return":
      if (node.value !== null) collectExprUses(node.value, uses);
      return;
    case "move":
      collectExprUses(node.target, uses);
      return;
    case "free":
      collectExprUses(node.target, uses);
      return;
    case "expr":
      collectExprUses(node.expr, uses);
      return;
    case "throw":
      collectExprUses(node.value, uses);
      return;
    case "try":
      collectUses(node.tryBlock, uses);
      for (const rama of node.catches) {
        bump(uses.decls, rama.name);
        collectUses(rama.block, uses);
      }
      return;
    case "importBinding":
      bump(uses.decls, node.name);
      return;
    case "break":
    case "continue":
    case "none":
      return;
  }
}

function collectIfUses(node: IfStmt, uses: NameUse): void {
  collectExprUses(node.condition, uses);
  collectUses(node.thenBlock, uses);
  switch (node.elseBranch.case) {
    case "block": collectUses(node.elseBranch.block, uses); return;
    case "if": collectIfUses(node.elseBranch.ifStmt, uses); return;
    case "none": return;
  }
}

function collectExprUses(expr: Expr, uses: NameUse): void {
  const node = expr.node;
  switch (node.case) {
    case "identifier":
      bump(uses.reads, node.name);
      return;
    case "literal":
    case "none":
      return;
    case "interp":
      for (const part of node.parts) {
        if (part.case === "expr") collectExprUses(part.expr, uses);
      }
      return;
    case "unary":
      collectExprUses(node.operand, uses);
      return;
    case "addrOf":
      collectExprUses(node.operand, uses);
      return;
    case "binary":
      collectExprUses(node.left, uses);
      collectExprUses(node.right, uses);
      return;
    case "assignment":
      collectExprUses(node.target, uses); // escribir cuenta como usar
      collectExprUses(node.value, uses);
      return;
    case "call":
      collectExprUses(node.callee, uses);
      for (const arg of node.args) collectExprUses(arg, uses);
      return;
    case "index":
      collectExprUses(node.obj, uses);
      collectExprUses(node.index, uses);
      return;
    case "member":
      collectExprUses(node.obj, uses);
      return;
    case "structLiteral":
      for (const value of node.values) collectExprUses(value, uses);
      return;
    case "cast":
      collectExprUses(node.value, uses);
      return;
    case "sizeof":
      return;
  }
}

// --------------------------------------------------------------------------- //
// limpieza de bloques
// --------------------------------------------------------------------------- //

interface CleanCtx {
  readonly uses: NameUse;
  readonly counters: Counters;
}

/**
 * Limpia un bloque. Devuelve **el mismo objeto** si no hubo cambios, para
 * no reconstruir árboles intactos (el 90% de los bloques de un programa).
 */
function cleanBlock(block: Block, ctx: CleanCtx): Block {
  let out: Stmt[] | null = null;

  for (let i = 0; i < block.statements.length; i++) {
    const stmt = block.statements[i]!;
    const cleaned = cleanStmt(stmt, ctx);

    if (cleaned === null) {
      out ??= block.statements.slice(0, i);
      continue;
    }
    if (out !== null) out.push(cleaned);
    else if (cleaned !== stmt) {
      out = block.statements.slice(0, i);
      out.push(cleaned);
    }

    // todo lo que siga a un terminador es inalcanzable.
    if (isTerminator(cleaned) && i + 1 < block.statements.length) {
      out ??= block.statements.slice(0, i + 1);
      ctx.counters.unreachableStatements += block.statements.length - i - 1;
      break;
    }
  }
  return out === null ? block : { statements: out };
}

/** `null` = la sentencia se elimina. */
function cleanStmt(stmt: Stmt, ctx: CleanCtx): Stmt | null {
  const node = stmt.node;
  switch (node.case) {
    case "expr":
      if (isPure(node.expr)) {
        ctx.counters.pureStatements++;
        return null;
      }
      return stmt;

    case "varDecl": {
      const read = ctx.uses.reads.get(node.name) ?? 0;
      const declared = ctx.uses.decls.get(node.name) ?? 0;
      const initPure = node.value === null || isPure(node.value);
      // 'declared > 1' = el nombre se declara en más de un scope del cuerpo:
      // sin resolución de scopes no se puede saber a cuál pertenece cada
      // lectura, así que se conserva.
      if (read === 0 && declared === 1 && initPure) {
        ctx.counters.deadVars++;
        return null;
      }
      return stmt;
    }

    case "block": {
      const cleaned = cleanBlock(node.block, ctx);
      return cleaned === node.block ? stmt : { ln: stmt.ln, col: stmt.col, node: { case: "block", block: cleaned } };
    }

    case "if": {
      const cleaned = cleanIf(node.ifStmt, ctx);
      return cleaned === node.ifStmt ? stmt : { ln: stmt.ln, col: stmt.col, node: { case: "if", ifStmt: cleaned } };
    }

    case "while": {
      const body = cleanBlock(node.body, ctx);
      return body === node.body
        ? stmt
        : { ln: stmt.ln, col: stmt.col, node: { case: "while", condition: node.condition, body } };
    }

    case "match": {
      let changed = false;
      const cases = node.cases.map((arm) => {
        const body = cleanStmt(arm.body, ctx);
        if (body === arm.body) return arm;
        changed = true;
        // un brazo no puede quedarse SIN cuerpo (el esquema lo exige): si su
        // única sentencia era eliminable, queda un bloque vacío.
        const empty: Stmt = {
          ln: arm.body.ln, col: arm.body.col,
          node: { case: "block", block: { statements: [] } },
        };
        return { pattern: arm.pattern, body: body ?? empty };
      });
      return changed
        ? { ln: stmt.ln, col: stmt.col, node: { case: "match", subject: node.subject, cases } }
        : stmt;
    }

    case "try": {
      const tryBlock = cleanBlock(node.tryBlock, ctx);
      const catches = node.catches.map((rama) => {
        const block = cleanBlock(rama.block, ctx);
        return block === rama.block ? rama : { ...rama, block };
      });
      const finallyBlock = node.finallyBlock === null
        ? null
        : cleanBlock(node.finallyBlock, ctx);
      const igual = tryBlock === node.tryBlock &&
        catches.every((rama, i) => rama === node.catches[i]) &&
        finallyBlock === node.finallyBlock;
      return igual
        ? stmt
        : {
            ln: stmt.ln, col: stmt.col,
            node: { case: "try", tryBlock, catches, finallyBlock },
          };
    }

    default:
      return stmt;
  }
}

function cleanIf(node: IfStmt, ctx: CleanCtx): IfStmt {
  const thenBlock = cleanBlock(node.thenBlock, ctx);
  let elseBranch = node.elseBranch;
  switch (node.elseBranch.case) {
    case "block": {
      const block = cleanBlock(node.elseBranch.block, ctx);
      if (block !== node.elseBranch.block) elseBranch = { case: "block", block };
      break;
    }
    case "if": {
      const ifStmt = cleanIf(node.elseBranch.ifStmt, ctx);
      if (ifStmt !== node.elseBranch.ifStmt) elseBranch = { case: "if", ifStmt };
      break;
    }
    case "none":
      break;
  }
  return thenBlock === node.thenBlock && elseBranch === node.elseBranch
    ? node
    : { condition: node.condition, thenBlock, elseBranch };
}

/** Limpia el cuerpo de una función/test con sus propias cuentas de uso. */
function cleanBody(body: Block, counters: Counters): Block {
  const uses: NameUse = { reads: new Map(), decls: new Map() };
  collectUses(body, uses);
  return cleanBlock(body, { uses, counters });
}

// --------------------------------------------------------------------------- //
// alcanzabilidad
// --------------------------------------------------------------------------- //

/**
 * Recolecta los nombres que una declaración referencia: identificadores,
 * nombres de miembro (una llamada entre unidades es `stdp.println`) y
 * nombres de tipos nominales. Sobre-aproximar es seguro; sub-aproximar
 * borraría código vivo.
 */
function collectNames(decl: Decl, out: Set<string>): void {
  switch (decl.node.case) {
    case "function": {
      const fn = decl.node.fn;
      for (const p of fn.params) typeNames(p.type, out);
      typeNames(fn.returnType, out);
      if (fn.body !== null) blockNames(fn.body, out);
      return;
    }
    case "struct":
      for (const f of decl.node.struct.fields) typeNames(f.type, out);
      return;
    case "enum":
      for (const item of decl.node.enumDecl.items) {
        if (item.value !== null) exprNames(item.value, out);
      }
      return;
    case "test":
      if (decl.node.test.body !== null) blockNames(decl.node.test.body, out);
      return;
    case "statement":
      stmtNames(decl.node.stmt, out);
      return;
    default:
      return;
  }
}

function typeNames(type: Type | null, out: Set<string>): void {
  for (let t = type; t !== null; t = t.inner) {
    if (t.kind === TypeKind.NOMINAL && t.name !== "") out.add(t.name);
  }
}

function blockNames(block: Block, out: Set<string>): void {
  for (const stmt of block.statements) stmtNames(stmt, out);
}

function stmtNames(stmt: Stmt, out: Set<string>): void {
  const node = stmt.node;
  switch (node.case) {
    case "block": blockNames(node.block, out); return;
    case "varDecl":
      typeNames(node.type, out);
      if (node.value !== null) exprNames(node.value, out);
      return;
    case "typeDecl":
      if (node.value !== null) exprNames(node.value, out);
      return;
    case "if": ifNames(node.ifStmt, out); return;
    case "while":
      exprNames(node.condition, out);
      blockNames(node.body, out);
      return;
    case "match":
      exprNames(node.subject, out);
      for (const arm of node.cases) {
        exprNames(arm.pattern, out);
        stmtNames(arm.body, out);
      }
      return;
    case "return":
      if (node.value !== null) exprNames(node.value, out);
      return;
    case "move": exprNames(node.target, out); return;
    case "free": exprNames(node.target, out); return;
    case "expr": exprNames(node.expr, out); return;
    case "throw": exprNames(node.value, out); return;
    case "try":
      blockNames(node.tryBlock, out);
      for (const rama of node.catches) blockNames(rama.block, out);
      return;
    case "importBinding":
      out.add(node.name);
      if (node.member !== "") out.add(node.member);
      return;
    case "break":
    case "continue":
    case "none":
      return;
  }
}

function ifNames(node: IfStmt, out: Set<string>): void {
  exprNames(node.condition, out);
  blockNames(node.thenBlock, out);
  switch (node.elseBranch.case) {
    case "block": blockNames(node.elseBranch.block, out); return;
    case "if": ifNames(node.elseBranch.ifStmt, out); return;
    case "none": return;
  }
}

function exprNames(expr: Expr, out: Set<string>): void {
  typeNames(expr.restype, out);
  const node = expr.node;
  switch (node.case) {
    case "identifier": out.add(node.name); return;
    case "literal":
    case "none":
      return;
    case "interp":
      for (const part of node.parts) {
        if (part.case === "expr") exprNames(part.expr, out);
      }
      return;
    case "unary": exprNames(node.operand, out); return;
    case "addrOf": exprNames(node.operand, out); return;
    case "binary":
      exprNames(node.left, out);
      exprNames(node.right, out);
      return;
    case "assignment":
      exprNames(node.target, out);
      exprNames(node.value, out);
      return;
    case "call":
      exprNames(node.callee, out);
      for (const arg of node.args) exprNames(arg, out);
      if (node.hook !== null) out.add(node.hook.ownerType);
      return;
    case "index":
      exprNames(node.obj, out);
      exprNames(node.index, out);
      return;
    case "member":
      // el nombre del miembro puede ser una función de otra unidad
      // ('stdp.println') o un item de enum ('Color.RED').
      out.add(node.member);
      exprNames(node.obj, out);
      return;
    case "structLiteral":
      out.add(node.typeName);
      for (const value of node.values) exprNames(value, out);
      return;
    case "cast":
      typeNames(node.type, out);
      exprNames(node.value, out);
      if (node.hook !== null) out.add(node.hook.ownerType);
      return;
    case "sizeof":
      typeNames(node.type, out);
      if (node.hook !== null) out.add(node.hook.ownerType);
      return;
  }
}

/** Nombre bajo el que una declaración se referencia (o `null` si no se nombra). */
function declName(decl: Decl): string | null {
  switch (decl.node.case) {
    case "function": return decl.node.fn.name;
    case "struct": return decl.node.struct.name;
    case "enum": return decl.node.enumDecl.name;
    default: return null;
  }
}

/**
 * Una declaración que SIEMPRE se conserva: directivas (el linker las
 * necesita), sentencias de nivel de módulo (se ejecutan), `#extern` (lo
 * revisa la política, no el DCE) y nodos malformados (que se reporten,
 * no que desaparezcan).
 */
function isAnchor(decl: Decl): boolean {
  switch (decl.node.case) {
    case "function":
    case "struct":
    case "enum":
    case "test":
      return false;
    default:
      return true;
  }
}

// --------------------------------------------------------------------------- //
// pasada
// --------------------------------------------------------------------------- //

/**
 * Nombres que OTRAS unidades de la imagen referencian: las raíces de una
 * unidad de librería. Con esto, `IO.stdp` conserva `println` porque el
 * programa lo llama, y descarta `print` si nadie lo usa.
 *
 * Son NOMBRES, no símbolos resueltos: una llamada entre unidades es
 * `stdp.println`, y saber a qué unidad pertenece exige rehacer el binding
 * de imports que ya hizo la Semántica. Consecuencia asumida: si dos
 * unidades tienen una función con el mismo nombre (`__write__` está en
 * `IO.stdp` y en `IO.stdpf`), usar una conserva la otra. Sobra código, no
 * falta — que es el único lado por el que un DCE puede equivocarse.
 */
export function crossUnitRoots(image: Image, alias: string): readonly string[] {
  const names = new Set<string>();
  for (const unit of image.everyUnit) {
    if (unit.alias === alias) continue;
    for (const decl of unit.module.items) collectNames(decl, names);
  }
  return [...names];
}

/** ¿La unidad declara un `#export`? (entonces es una librería, no un programa). */
function isLibrary(module: Module): boolean {
  return module.items.some((d) => d.node.case === "export");
}

/**
 * Elimina el código muerto de un módulo.
 *
 * @returns el módulo nuevo y las estadísticas de lo eliminado.
 */
export function eliminateDeadCode(module: Module, options: DceOptions = {}): DceResult {
  const entry = options.entry ?? "main";
  const keepTests = options.keepTests ?? false;
  const keepHooks = options.keepHooks ?? true;
  const maxRounds = options.maxRounds ?? DEFAULT_MAX_ROUNDS;
  const counters = newCounters();

  // raíces fijas: la entrada, lo que pida el llamador y —en una librería sin
  // raíces explícitas— todas sus funciones (la visibilidad no viaja en v1).
  const fixedRoots = new Set<string>([entry, ...(options.roots ?? [])]);
  if (options.roots === undefined && isLibrary(module)) {
    for (const decl of module.items) {
      if (decl.node.case === "function") fixedRoots.add(decl.node.fn.name);
    }
  }
  // los hooks se despachan en runtime: sus cuerpos son raíces por sí mismos.
  if (keepHooks) {
    for (const entryHook of module.symbols.hooks) {
      if (entryHook.symbol !== null) fixedRoots.add(entryHook.symbol.name);
    }
    for (const cast of module.symbols.casts) fixedRoots.add(cast.name);
  }

  let current = module;
  let rounds = 0;
  for (; rounds < maxRounds; rounds++) {
    const cleaned = cleanBodies(current, counters, keepTests);
    const pruned = pruneUnreachable(cleaned, fixedRoots, keepTests, counters);
    if (pruned === current) break;
    current = pruned;
  }

  return {
    module: current,
    stats: {
      functions: counters.functions,
      structs: counters.structs,
      enums: counters.enums,
      tests: counters.tests,
      unreachableStatements: counters.unreachableStatements,
      pureStatements: counters.pureStatements,
      deadVars: counters.deadVars,
      symbols: counters.symbols,
      rounds,
      removed: counters.removed,
    },
  };
}

/** Fase intra-procedimiento: limpia cuerpos sin tocar la lista de items. */
function cleanBodies(module: Module, counters: Counters, keepTests: boolean): Module {
  let changed = false;
  const items: Decl[] = [];

  for (const decl of module.items) {
    switch (decl.node.case) {
      case "function": {
        const fn = decl.node.fn;
        if (fn.body === null) break;
        const body = cleanBody(fn.body, counters);
        if (body === fn.body) break;
        changed = true;
        const next: FunctionDecl = { ...fn, body };
        items.push({ ln: decl.ln, col: decl.col, node: { case: "function", fn: next } });
        continue;
      }
      case "test": {
        const test = decl.node.test;
        if (!keepTests || test.body === null) break;
        const body = cleanBody(test.body, counters);
        if (body === test.body) break;
        changed = true;
        items.push({
          ln: decl.ln, col: decl.col,
          node: { case: "test", test: { ...test, body } },
        });
        continue;
      }
      case "statement": {
        // el nivel de módulo no tiene 'variables locales': solo se poda lo
        // inalcanzable y lo puro, con cuentas de uso vacías.
        const cleaned = cleanStmt(decl.node.stmt, {
          uses: { reads: new Map(), decls: new Map() },
          counters,
        });
        if (cleaned === decl.node.stmt) break;
        changed = true;
        // una sentencia de módulo que se elimina se va del árbol entera: si
        // dejáramos el 'Decl' con un nodo vacío, la contención lo leería como
        // HIR malformado (WEB901).
        if (cleaned !== null) {
          items.push({
            ln: decl.ln, col: decl.col,
            node: { case: "statement", stmt: cleaned },
          });
        }
        continue;
      }
      default:
        break;
    }
    items.push(decl);
  }
  return changed ? { ...module, items } : module;
}

/** Fase inter-procedimiento: alcanzabilidad desde las raíces. */
function pruneUnreachable(
  module: Module,
  fixedRoots: ReadonlySet<string>,
  keepTests: boolean,
  counters: Counters,
): Module {
  // índice nombre -> declaraciones (un nombre puede repetirse: overloads de
  // '__cast__' comparten nombre y no posición).
  const byName = new Map<string, Decl[]>();
  for (const decl of module.items) {
    const name = declName(decl);
    if (name === null) continue;
    const list = byName.get(name);
    if (list === undefined) byName.set(name, [decl]);
    else list.push(decl);
  }

  const live = new Set<Decl>();
  const worklist: string[] = [...fixedRoots];

  // toda declaración ancla (directivas, sentencias de módulo, #extern) está
  // viva y aporta sus referencias.
  for (const decl of module.items) {
    if (isAnchor(decl) || (keepTests && decl.node.case === "test")) {
      live.add(decl);
      const names = new Set<string>();
      collectNames(decl, names);
      worklist.push(...names);
    }
  }

  const visited = new Set<string>();
  while (worklist.length > 0) {
    const name = worklist.pop()!;
    if (visited.has(name)) continue;
    visited.add(name);
    for (const decl of byName.get(name) ?? []) {
      if (live.has(decl)) continue;
      live.add(decl);
      const names = new Set<string>();
      collectNames(decl, names);
      for (const next of names) if (!visited.has(next)) worklist.push(next);
    }
  }

  const items = module.items.filter((decl) => {
    if (live.has(decl)) return true;
    switch (decl.node.case) {
      case "function": counters.functions++; break;
      case "struct": counters.structs++; break;
      case "enum": counters.enums++; break;
      case "test": counters.tests++; break;
      default: break;
    }
    const name = declName(decl) ?? (decl.node.case === "test" ? decl.node.test.name : "?");
    counters.removed.push(name);
    return false;
  });

  if (items.length === module.items.length) return module;

  const keptFunctions = new Set<string>();
  const keptTypes = new Set<string>();
  const keptBodies = new Set<string>();
  for (const decl of items) {
    switch (decl.node.case) {
      case "function":
        keptFunctions.add(decl.node.fn.name);
        keptBodies.add(`${decl.node.fn.name}#${decl.ln}`);
        break;
      case "struct": keptTypes.add(decl.node.struct.name); break;
      case "enum": keptTypes.add(decl.node.enumDecl.name); break;
      default: break;
    }
  }

  return {
    ...module,
    items,
    symbols: pruneSymbols(module.symbols, keptFunctions, keptTypes, keptBodies, counters),
  };
}

/**
 * La tabla de símbolos acompaña al árbol: dejar el símbolo de una función
 * borrada haría que el codegen (o un `--emit-hir` posterior) creyera que
 * existe. Solo se retiran los símbolos cuya DECLARACIÓN se eliminó; los
 * imports, variables globales y demás se conservan tal cual.
 */
function pruneSymbols(
  table: SymbolTable,
  keptFunctions: ReadonlySet<string>,
  keptTypes: ReadonlySet<string>,
  keptBodies: ReadonlySet<string>,
  counters: Counters,
): SymbolTable {
  const values = new Map<string, SymbolInfo>();
  for (const [name, sym] of table.values) {
    if (sym.kind === SymbolKind.FUNCTION && !keptFunctions.has(name)) {
      counters.symbols++;
      continue;
    }
    values.set(name, sym);
  }
  const types = new Map<string, SymbolInfo>();
  for (const [name, sym] of table.types) {
    if (
      (sym.kind === SymbolKind.STRUCT || sym.kind === SymbolKind.ENUM) &&
      !keptTypes.has(name)
    ) {
      counters.symbols++;
      continue;
    }
    types.set(name, sym);
  }
  const hooks = table.hooks.filter(
    (h) => h.symbol === null || keptBodies.has(`${h.symbol.name}#${h.symbol.ln}`),
  );
  const casts = table.casts.filter((s) => keptBodies.has(`${s.name}#${s.ln}`));
  counters.symbols += (table.hooks.length - hooks.length) + (table.casts.length - casts.length);
  return { types, values, hooks, casts };
}

// --------------------------------------------------------------------------- //
// imagen completa
// --------------------------------------------------------------------------- //

export interface ImageDceResult {
  readonly image: Image;
  /** Estadísticas por alias de unidad (`""` = la principal). */
  readonly stats: ReadonlyMap<string, DceStats>;
}

/**
 * DCE sobre la imagen ligada: la unidad principal desde su `entry`, y cada
 * librería desde los nombres que el resto de la imagen realmente usa
 * ({@link crossUnitRoots}). Es donde el DCE rinde de verdad en el web —
 * una unidad de librería aporta todo su contenido y el programa usa una
 * función.
 */
export function eliminateDeadCodeInImage(
  image: Image,
  options: DceOptions = {},
): ImageDceResult {
  const stats = new Map<string, DceStats>();

  const mainResult = eliminateDeadCode(image.main.module, options);
  stats.set("", mainResult.stats);
  const main = new Unit(image.main.alias, image.main.path, mainResult.module);

  const units = new Map<string, Unit>();
  for (const [alias, unit] of image.units) {
    const result = eliminateDeadCode(unit.module, {
      ...options,
      roots: options.roots ?? crossUnitRoots(image, alias),
    });
    stats.set(alias, result.stats);
    units.set(alias, new Unit(alias, unit.path, result.module));
  }

  return { image: new Image(main, units), stats };
}

/** Resumen de una línea por unidad, para la CLI. */
export function formatStats(stats: DceStats): string {
  return (
    `${stats.functions} fn, ${stats.structs} struct, ${stats.enums} enum, ` +
    `${stats.tests} test · ${stats.unreachableStatements} sentencias inalcanzables, ` +
    `${stats.pureStatements} sin efectos, ${stats.deadVars} variables muertas, ` +
    `${stats.symbols} símbolos (${stats.rounds} rondas)`
  );
}
