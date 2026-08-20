/**
 * Lowering HIR -> WIR: la única fase del target web que TOMA DECISIONES.
 *
 * Resuelve nombres a índices, tipos nominales a tipos de máquina, y las
 * llamadas a la librería permitida a primitivas del host. Lo que no cabe en
 * el alcance v1 no se traduce "como se pueda": se rechaza con un diagnóstico
 * `WEB1xx` en su línea y columna, y el módulo no se genera. Misma disciplina
 * que la contención (`target/restrictions.ts`) y que el emisor del frontend.
 *
 * ### Sobre la librería `IO`
 * `stdp.println("hola")` no se compila bajando el cuerpo de `println` (esa
 * unidad es del host, ver `target/policy.ts`): se traduce al intrínseco
 * correspondiente. La tabla {@link IO_INTRINSICS} es la fuente única de esa
 * correspondencia — añadir `printf` fue una línea, y quitar `print` sería
 * otra.
 *
 * ### Sobre las sentencias de nivel de módulo
 * suriaX permite código suelto fuera de `main` (`a.srcx` es exactamente eso).
 * El intérprete lo ejecuta antes de la entrada; aquí se agrupa en una función
 * sintética `__module_init` que el host llama primero. Así el orden de
 * ejecución del web es el MISMO que el del intérprete, que es lo único que
 * hace comparables los dos.
 */

import { Severity, WebCode, DiagnosticBag, type Diagnostic } from "../diagnostics.ts";
import {
  TypeKind,
  type Block,
  type Expr,
  type FunctionDecl,
  type IfStmt,
  type Module,
  type Stmt,
  type Type,
} from "../hir/schema.ts";
import type { Image } from "../hir/link.ts";
import { encodeUtf8 } from "../hir/write.ts";
import {
  WirBinOp,
  WirType,
  WirUnOp,
  isComparison,
  type WirExpr,
  type WirFunc,
  type WirHostImport,
  type WirLocal,
  type WirModule,
  type WirStmt,
  type WirString,
} from "./wir.ts";

/** Nombre de la función sintética que agrupa las sentencias de módulo. */
export const MODULE_INIT = "__module_init";

/** Primitiva del host: escribe `len` bytes desde `ptr` de la memoria lineal. */
const HOST_WRITE: WirHostImport = {
  module: "env",
  name: "__write__",
  params: [WirType.I32, WirType.I32],
  result: WirType.VOID,
};

/**
 * Funciones de la librería `IO` y su traducción. `newline` indica si tras
 * escribir el argumento hay que escribir un salto de línea — es toda la
 * diferencia entre `print` y `println` en `lib/io/stdp.libsrx`.
 */
export const IO_INTRINSICS: ReadonlyMap<string, { readonly newline: boolean }> = new Map([
  ["print", { newline: false }],
  ["println", { newline: true }],
  ["printf", { newline: false }],
]);

export interface LowerResult {
  /** Módulo WIR listo para los backends, o `null` si hubo diagnósticos. */
  readonly module: WirModule | null;
  readonly diagnostics: readonly Diagnostic[];
}

/** Operadores de suriaX -> operadores del WIR. */
const BINARY_OPS: ReadonlyMap<string, WirBinOp> = new Map([
  ["+", WirBinOp.ADD], ["-", WirBinOp.SUB], ["*", WirBinOp.MUL],
  ["/", WirBinOp.DIV], ["%", WirBinOp.REM],
  ["==", WirBinOp.EQ], ["!=", WirBinOp.NE],
  ["<", WirBinOp.LT], ["<=", WirBinOp.LE],
  [">", WirBinOp.GT], [">=", WirBinOp.GE],
  // 'and'/'or' NO están: son de cortocircuito, y traducirlos a i32.and/i32.or
  // evaluaría siempre los dos lados. Un programa con 'a() and b()' se
  // comportaría distinto que en el intérprete. Entran cuando el WIR tenga
  // 'if' estructurado, no antes: mientras tanto dan WEB100.
]);

/** Baja la unidad principal de una imagen ya contenida y optimizada. */
export function lowerImage(image: Image): LowerResult {
  return lowerModule(image.main.module);
}

/** Baja un módulo HIR al WIR. */
export function lowerModule(module: Module): LowerResult {
  const lowering = new Lowering(module);
  return lowering.run();
}

/** Alcance léxico: nombre -> índice de local. Se apila por bloque. */
interface Scope {
  readonly names: Map<string, number>;
  readonly parent: Scope | null;
}

function lookup(scope: Scope | null, name: string): number | null {
  for (let s = scope; s !== null; s = s.parent) {
    const index = s.names.get(name);
    if (index !== undefined) return index;
  }
  return null;
}

class Lowering {
  readonly #hir: Module;
  readonly #bag: DiagnosticBag;
  /** nombre de función -> índice en `funcs`. */
  readonly #funcIndex = new Map<string, number>();
  /** Firmas, para tipar las llamadas sin volver a mirar el HIR. */
  readonly #signatures: { params: WirType[]; result: WirType }[] = [];
  readonly #strings: WirString[] = [];
  readonly #stringByText = new Map<string, number>();
  #dataSize = 0;

  // --- estado de la función que se está bajando ---
  /**
   * Marco de la función: parámetros PRIMERO y variables después, en un solo
   * espacio de índices — que es exactamente como los numera WebAssembly
   * (`local.get 0` es el primer parámetro). Tener una sola lista evita el
   * clásico desajuste de mantener dos y sumarles el offset a mano.
   */
  #frame: WirLocal[] = [];
  #paramCount = 0;
  #scope: Scope | null = null;
  #result: WirType = WirType.VOID;
  /** Bucles abiertos: 'break'/'continue' sin bucle no tienen a dónde saltar. */
  #loopDepth = 0;

  constructor(hir: Module) {
    this.#hir = hir;
    this.#bag = new DiagnosticBag(hir.sourceFile || "<módulo>");
  }

  run(): LowerResult {
    // 1) índice de funciones ANTES de bajar ningún cuerpo: una función puede
    //    llamar a otra declarada más abajo (el frontend ya lo validó).
    const declared: FunctionDecl[] = [];
    for (const decl of this.#hir.items) {
      if (decl.node.case !== "function") continue;
      const fn = decl.node.fn;
      if (fn.body === null) continue;  // prototipo: lo aporta el host
      if (fn.dunder !== "") {
        this.#unsupported(
          `la función '${fn.name}' es un hook/dunder`, decl,
        );
        continue;
      }
      this.#funcIndex.set(fn.name, declared.length);
      declared.push(fn);
      this.#signatures.push({
        params: fn.params.map((p) => this.#valueType(p.type, `el parámetro '${p.name}'`, decl)),
        result: this.#valueType(fn.returnType, `el retorno de '${fn.name}'`, decl, true),
      });
    }

    // 2) sentencias de nivel de módulo -> __module_init (índice reservado
    //    ANTES de bajar, por si alguna de ellas llama a una función).
    const moduleStmts = this.#hir.items.filter((d) => d.node.case === "statement");
    let initIndex: number | null = null;
    if (moduleStmts.length > 0) {
      initIndex = declared.length;
      this.#funcIndex.set(MODULE_INIT, initIndex);
      this.#signatures.push({ params: [], result: WirType.VOID });
    }

    // 3) cuerpos
    const funcs: WirFunc[] = [];
    for (let i = 0; i < declared.length; i++) {
      funcs.push(this.#lowerFunction(declared[i]!, this.#signatures[i]!));
    }
    if (initIndex !== null) {
      this.#frame = [];
      this.#paramCount = 0;
      this.#scope = { names: new Map(), parent: null };
      this.#result = WirType.VOID;
      this.#loopDepth = 0;
      const body: WirStmt[] = [];
      for (const decl of moduleStmts) {
        if (decl.node.case === "statement") this.#lowerStmt(decl.node.stmt, body);
      }
      funcs.push({
        name: MODULE_INIT, params: [], locals: this.#frame,
        result: WirType.VOID, body, exported: true,
      });
    }

    const diagnostics = this.#bag.items;
    if (diagnostics.some((d) => d.severity === Severity.CRITICAL)) {
      return { module: null, diagnostics };
    }
    const entry = this.#funcIndex.get("main");
    return {
      module: {
        source: this.#hir.sourceFile,
        // el import del host se DECLARA siempre, se use o no: así el índice 0
        // de la sección de imports no depende de si el programa imprime, y
        // los índices de función son estables entre compilaciones.
        imports: [HOST_WRITE],
        funcs,
        strings: this.#strings,
        dataSize: this.#dataSize,
        entry: entry === undefined ? null : entry,
        init: initIndex,
      },
      diagnostics,
    };
  }

  // ------------------------------------------------------------------ //
  // diagnósticos
  // ------------------------------------------------------------------ //

  #unsupported(what: string, pos: { ln: number; col: number }): void {
    this.#bag.add(
      WebCode.CODEGEN_UNSUPPORTED,
      `${what}: el codegen del target web v1 solo traduce variables, ` +
        "aritmética, comparaciones y llamadas",
      pos,
    );
  }

  #badType(what: string, type: Type | null, pos: { ln: number; col: number }): void {
    const shown = type === null ? "desconocido" : `'${describeType(type)}'`;
    this.#bag.add(
      WebCode.CODEGEN_TYPE,
      `${what} es de tipo ${shown}, que el codegen del target web v1 no ` +
        "representa (solo int, float, bool y void)",
      pos,
    );
  }

  // ------------------------------------------------------------------ //
  // tipos
  // ------------------------------------------------------------------ //

  #valueType(
    type: Type | null,
    what: string,
    pos: { ln: number; col: number },
    allowVoid = false,
  ): WirType {
    if (type === null) {
      this.#badType(what, type, pos);
      return WirType.I64;
    }
    switch (type.kind) {
      case TypeKind.INT: return WirType.I64;
      case TypeKind.FLOAT: return WirType.F64;
      case TypeKind.BOOL: return WirType.I32;
      case TypeKind.VOID:
        if (allowVoid) return WirType.VOID;
        this.#badType(what, type, pos);
        return WirType.I64;
      default:
        this.#badType(what, type, pos);
        return WirType.I64;
    }
  }

  // ------------------------------------------------------------------ //
  // funciones
  // ------------------------------------------------------------------ //

  #lowerFunction(fn: FunctionDecl, signature: { params: WirType[]; result: WirType }): WirFunc {
    const params: WirLocal[] = fn.params.map((p, i) => ({
      name: p.name,
      type: signature.params[i] ?? WirType.I64,
    }));
    this.#frame = [...params];
    this.#paramCount = params.length;
    this.#result = signature.result;
    this.#loopDepth = 0;
    const names = new Map<string, number>();
    params.forEach((p, i) => names.set(p.name, i));
    this.#scope = { names, parent: null };

    const body: WirStmt[] = [];
    if (fn.body !== null) this.#lowerBlock(fn.body, body);

    return {
      name: fn.name,
      params,
      // solo los declarados: los parámetros ya viajan aparte y WASM los
      // numera antes que ellos.
      locals: this.#frame.slice(this.#paramCount),
      result: signature.result,
      body,
      exported: true,
    };
  }

  #lowerBlock(block: Block, out: WirStmt[]): void {
    const saved = this.#scope;
    this.#scope = { names: new Map(), parent: saved };
    for (const stmt of block.statements) this.#lowerStmt(stmt, out);
    this.#scope = saved;
  }

  /**
   * Declara un local NUEVO aunque el nombre ya exista: dos `var x` en bloques
   * distintos son dos locales distintos, y el scope decide cuál ve cada uso.
   * WASM no tiene scopes, así que aquí es donde se resuelve el sombreado.
   */
  #declareLocal(name: string, type: WirType): number {
    const index = this.#frame.length;
    this.#frame.push({ name, type });
    this.#scope?.names.set(name, index);
    return index;
  }

  // ------------------------------------------------------------------ //
  // sentencias
  // ------------------------------------------------------------------ //

  #lowerStmt(stmt: Stmt, out: WirStmt[]): void {
    const node = stmt.node;
    switch (node.case) {
      case "varDecl": {
        const type = this.#valueType(node.type, `la variable '${node.name}'`, stmt);
        // El inicializador se baja ANTES de declarar el local: 'var int x = x'
        // debe resolver la 'x' de fuera, no la que se está declarando.
        const value = node.value === null
          ? zeroOf(type)
          : this.#lowerExpr(node.value, type);
        const index = this.#declareLocal(node.name, type);
        // Sin inicializador se emite el cero EXPLÍCITO. WASM solo pone a cero
        // los locales al ENTRAR en la función, y un 'var' dentro de un bucle
        // se declara en cada vuelta: sin este local.set conservaría el valor
        // de la iteración anterior.
        out.push({ kind: "local.set", pos: stmt, index, value });
        return;
      }

      case "expr": {
        const expr = node.expr;
        // 'x = 1;' llega como ExprStmt(Assignment): es una asignación, no un
        // valor que se descarta.
        if (expr.node.case === "assignment") {
          const target = expr.node.target;
          if (target.node.case !== "identifier") {
            this.#unsupported("asignar a algo que no es una variable", expr);
            return;
          }
          const index = lookup(this.#scope, target.node.name);
          if (index === null) {
            this.#unsupported(`la variable '${target.node.name}' no es un local`, expr);
            return;
          }
          const type = this.#typeOfLocal(index);
          out.push({
            kind: "local.set", pos: stmt, index,
            value: this.#lowerExpr(expr.node.value, type),
          });
          return;
        }
        const value = this.#lowerExpr(expr, null);
        out.push({ kind: "drop", pos: stmt, value });
        return;
      }

      case "return":
        out.push({
          kind: "return", pos: stmt,
          value: node.value === null ? null : this.#lowerExpr(node.value, this.#result),
        });
        return;

      case "block":
        this.#lowerBlock(node.block, out);
        return;

      case "if":
        out.push(this.#lowerIf(node.ifStmt, stmt));
        return;

      case "while": {
        const condition = this.#condition(node.condition, "la condición del 'while'");
        const body: WirStmt[] = [];
        this.#loopDepth++;
        this.#lowerBlock(node.body, body);
        this.#loopDepth--;
        out.push({ kind: "while", pos: stmt, condition, body });
        return;
      }

      case "break":
      case "continue":
        if (this.#loopDepth === 0) {
          // la Semántica ya lo habría rechazado; aquí es defensa en
          // profundidad: sin bucle no hay etiqueta a la que saltar y el
          // binario saldría mal formado.
          this.#unsupported(`'${node.case}' fuera de un bucle`, stmt);
          return;
        }
        out.push({ kind: node.case, pos: stmt });
        return;

      case "none":
        this.#bag.add(
          WebCode.MALFORMED_NODE,
          "una sentencia llegó sin variante en el HIR", stmt,
        );
        return;

      default:
        this.#unsupported(`la sentencia '${node.case}'`, stmt);
        return;
    }
  }

  /** Tipo del local `index` (parámetros y variables, mismo espacio). */
  #typeOfLocal(index: number): WirType {
    return this.#frame[index]?.type ?? WirType.I64;
  }

  /**
   * `if` con su cadena de `else if`. El HIR la trae anidada
   * (`elseBranch.case === "if"`) y aquí se conserva anidada: en WASM un
   * `else if` ES un `if` dentro del `else`, no hay forma más plana.
   */
  /**
   * Condición de un `if`/`while`. WebAssembly exige **i32** ahí: si llegara
   * un `i64` o un `f64`, el binario no validaría. La Semántica ya obliga a
   * que sea `bool`, así que esto es defensa en profundidad — pero un
   * diagnóstico con posición es infinitamente mejor que un módulo que el
   * navegador rechaza con un offset de bytes.
   */
  #condition(expr: Expr, what: string): WirExpr {
    const lowered = this.#lowerExpr(expr, WirType.I32);
    if (lowered.type !== WirType.I32) {
      this.#badType(what, expr.restype, expr);
    }
    return lowered;
  }

  #lowerIf(node: IfStmt, at: Stmt): WirStmt {
    const condition = this.#condition(node.condition, "la condición del 'if'");
    const then: WirStmt[] = [];
    this.#lowerBlock(node.thenBlock, then);

    const otherwise: WirStmt[] = [];
    switch (node.elseBranch.case) {
      case "block":
        this.#lowerBlock(node.elseBranch.block, otherwise);
        break;
      case "if":
        otherwise.push(this.#lowerIf(node.elseBranch.ifStmt, at));
        break;
      case "none":
        break;
    }
    return { kind: "if", pos: at, condition, then, otherwise };
  }

  // ------------------------------------------------------------------ //
  // expresiones
  // ------------------------------------------------------------------ //

  /**
   * @param expected tipo que el contexto espera (`null` = el que salga). No
   *   se COERCIONA nada —suriaX no tiene coerciones implícitas—: sirve para
   *   tipar los literales enteros que también valen como `float`.
   */
  #lowerExpr(expr: Expr, expected: WirType | null): WirExpr {
    const node = expr.node;
    switch (node.case) {
      case "literal": {
        const literal = node.literal;
        switch (literal.kind) {
          case "int":
            return expected === WirType.F64
              ? { kind: "const", type: WirType.F64, value: Number(literal.value) }
              : { kind: "const", type: WirType.I64, value: literal.value };
          case "float":
            return { kind: "const", type: WirType.F64, value: literal.value };
          case "bool":
            return { kind: "const", type: WirType.I32, value: literal.value ? 1n : 0n };
          default:
            this.#unsupported(`el literal '${literal.kind}'`, expr);
            return { kind: "const", type: WirType.I64, value: 0n };
        }
      }

      case "identifier": {
        const index = lookup(this.#scope, node.name);
        if (index === null) {
          this.#unsupported(
            `'${node.name}' no es una variable local (las globales llegarán con el codegen v2)`,
            expr,
          );
          return { kind: "const", type: WirType.I64, value: 0n };
        }
        return { kind: "local.get", type: this.#typeOfLocal(index), index };
      }

      case "binary": {
        // 'and'/'or' NO son binarios: cortocircuitan (ver WirExpr.logical).
        if (node.op === "and" || node.op === "or") {
          return {
            kind: "logical",
            type: WirType.I32,
            op: node.op,
            left: this.#condition(node.left, `el lado izquierdo de '${node.op}'`),
            right: this.#condition(node.right, `el lado derecho de '${node.op}'`),
          };
        }
        const op = BINARY_OPS.get(node.op);
        if (op === undefined) {
          this.#unsupported(`el operador '${node.op}'`, expr);
          return { kind: "const", type: WirType.I64, value: 0n };
        }
        // el tipo de los OPERANDOS manda: en 'a < b' el resultado es bool
        // pero la instrucción depende de si a y b son i64 o f64.
        const operandType = this.#operandType(node.left, node.right, expr);
        const left = this.#lowerExpr(node.left, operandType);
        const right = this.#lowerExpr(node.right, operandType);
        return {
          kind: "binary",
          type: isComparison(op) ? WirType.I32 : operandType,
          op, operandType, left, right,
        };
      }

      case "unary": {
        if (node.op === "not" || node.op === "!") {
          return {
            kind: "unary", type: WirType.I32, op: WirUnOp.NOT,
            operand: this.#lowerExpr(node.operand, WirType.I32),
          };
        }
        if (node.op === "-") {
          const operand = this.#lowerExpr(node.operand, expected);
          return { kind: "unary", type: operand.type, op: WirUnOp.NEG, operand };
        }
        this.#unsupported(`el operador unario '${node.op}'`, expr);
        return { kind: "const", type: WirType.I64, value: 0n };
      }

      case "call":
        return this.#lowerCall(expr, node.callee, node.args);

      case "assignment":
        this.#unsupported("una asignación usada como valor", expr);
        return { kind: "const", type: WirType.I64, value: 0n };

      case "none":
        this.#bag.add(WebCode.MALFORMED_NODE, "una expresión llegó sin variante", expr);
        return { kind: "const", type: WirType.I64, value: 0n };

      default:
        this.#unsupported(`la expresión '${node.case}'`, expr);
        return { kind: "const", type: WirType.I64, value: 0n };
    }
  }

  /** Tipo común de los operandos de un binario, tomado de sus `restype`. */
  #operandType(left: Expr, right: Expr, at: Expr): WirType {
    const fromLeft = wirTypeOf(left.restype);
    const fromRight = wirTypeOf(right.restype);
    if (fromLeft !== null) return fromLeft;
    if (fromRight !== null) return fromRight;
    this.#badType("el operando", left.restype, at);
    return WirType.I64;
  }

  // ------------------------------------------------------------------ //
  // llamadas
  // ------------------------------------------------------------------ //

  #lowerCall(expr: Expr, callee: Expr, args: readonly Expr[]): WirExpr {
    // 'stdp.println("hola")' -> intrínseco del host.
    if (callee.node.case === "member") {
      const member = callee.node.member;
      const intrinsic = IO_INTRINSICS.get(member);
      if (intrinsic === undefined) {
        this.#unsupported(`la llamada a '${member}'`, expr);
        return { kind: "const", type: WirType.VOID, value: 0n };
      }
      return this.#lowerPrint(expr, args, intrinsic.newline);
    }

    if (callee.node.case !== "identifier") {
      this.#unsupported("una llamada cuyo destino no es un nombre", expr);
      return { kind: "const", type: WirType.I64, value: 0n };
    }

    const name = callee.node.name;
    // 'print(x)' sin cualificar (import de miembro) también es del host.
    const intrinsic = IO_INTRINSICS.get(name);
    if (intrinsic !== undefined && this.#funcIndex.get(name) === undefined) {
      return this.#lowerPrint(expr, args, intrinsic.newline);
    }

    const index = this.#funcIndex.get(name);
    if (index === undefined) {
      this.#unsupported(`la llamada a '${name}' (sin cuerpo en esta unidad)`, expr);
      return { kind: "const", type: WirType.I64, value: 0n };
    }
    const signature = this.#signatures[index]!;
    const lowered = args.map((arg, i) => this.#lowerExpr(arg, signature.params[i] ?? null));
    return { kind: "call", type: signature.result, func: index, args: lowered };
  }

  /**
   * `print`/`println`/`printf` de un literal de cadena. El texto va a la
   * memoria lineal y la llamada pasa `(offset, longitud)` al host — el mismo
   * contrato que `__write__` en `lib/io/stdp.libsrx`.
   */
  #lowerPrint(expr: Expr, args: readonly Expr[], newline: boolean): WirExpr {
    const first = args[0];
    if (first === undefined || first.node.case !== "literal" ||
        (first.node.literal.kind !== "str" && first.node.literal.kind !== "char")) {
      this.#bag.add(
        WebCode.CODEGEN_STRING,
        "el codegen del target web v1 solo imprime literales de cadena " +
          "(las cadenas calculadas y los f-strings llegan con el runtime de strings)",
        expr,
      );
      return { kind: "const", type: WirType.VOID, value: 0n };
    }
    const text = first.node.literal.value + (newline ? "\n" : "");
    const id = this.#intern(text);
    const entry = this.#strings[id]!;
    return {
      kind: "call.host",
      type: WirType.VOID,
      host: 0,
      args: [
        { kind: "const", type: WirType.I32, value: BigInt(entry.offset) },
        { kind: "const", type: WirType.I32, value: BigInt(entry.bytes.length) },
      ],
    };
  }

  /** Constantes de cadena deduplicadas: dos `println("hola")` comparten bytes. */
  #intern(text: string): number {
    const existing = this.#stringByText.get(text);
    if (existing !== undefined) return existing;
    const bytes = encodeUtf8(text);
    const id = this.#strings.length;
    this.#strings.push({ offset: this.#dataSize, bytes, text });
    this.#stringByText.set(text, id);
    this.#dataSize += bytes.length;
    return id;
  }
}

/** Valor cero de un tipo, para los locales sin inicializador. */
function zeroOf(type: WirType): WirExpr {
  return type === WirType.F64
    ? { kind: "const", type, value: 0 }
    : { kind: "const", type: type === WirType.VOID ? WirType.I64 : type, value: 0n };
}

/** `Type` del HIR -> tipo del WIR, o `null` si no es representable. */
export function wirTypeOf(type: Type | null): WirType | null {
  if (type === null) return null;
  switch (type.kind) {
    case TypeKind.INT: return WirType.I64;
    case TypeKind.FLOAT: return WirType.F64;
    case TypeKind.BOOL: return WirType.I32;
    case TypeKind.VOID: return WirType.VOID;
    default: return null;
  }
}

function describeType(type: Type): string {
  switch (type.kind) {
    case TypeKind.STR: return "str";
    case TypeKind.CHAR: return "char";
    case TypeKind.NOMINAL: return type.name;
    case TypeKind.POINTER: return "puntero";
    case TypeKind.NULLABLE: return "nullable";
    case TypeKind.ERROR: return "error";
    default: return "no representable";
  }
}
