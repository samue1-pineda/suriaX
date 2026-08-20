/**
 * Backend WASM: WIR -> binario `.wasm`.
 *
 * Escribe el módulo a mano, sección por sección. Es el mismo criterio que
 * llevó al lector de protobuf propio: un ensamblador de WebAssembly de
 * terceros pesa más que todo este backend y su superficie útil aquí cabe en
 * un archivo. El formato está fijado por la especificación y no cambia.
 *
 * ### El binario que se produce
 * ```
 *   magic "\0asm" · versión 1
 *   1 type    · las firmas (deduplicadas)
 *   2 import  · env.__write__(i32 ptr, i32 len) -> ()
 *   3 function· qué firma tiene cada función
 *   5 memory  · 1 página (64 KiB) si el programa usa cadenas
 *   7 export  · "memory" y cada función
 *  10 code    · los cuerpos
 *  11 data    · las constantes de cadena
 * ```
 *
 * ### Por qué emitir es un post-orden
 * WASM es una máquina de PILA: el resultado de cada instrucción queda encima
 * y la siguiente lo consume. Traducir `a + b * 2` es recorrer el árbol del
 * WIR en post-orden y escribir un opcode por nodo — sin registros, sin
 * temporales y sin decidir nada. Ese es justo el trabajo que el WIR ya dejó
 * hecho (ver `wir/wir.ts`).
 */

import {
  WirBinOp,
  WirType,
  WirUnOp,
  type WirExpr,
  type WirFunc,
  type WirModule,
  type WirStmt,
} from "../wir/wir.ts";

// --------------------------------------------------------------------------- //
// opcodes usados (los nombres son los de la especificación)
// --------------------------------------------------------------------------- //

const OP = {
  BLOCK: 0x02,
  LOOP: 0x03,
  IF: 0x04,
  ELSE: 0x05,
  END: 0x0b,
  BR: 0x0c,
  BR_IF: 0x0d,
  RETURN: 0x0f,
  CALL: 0x10,
  DROP: 0x1a,
  LOCAL_GET: 0x20,
  LOCAL_SET: 0x21,

  I32_CONST: 0x41,
  I64_CONST: 0x42,
  F64_CONST: 0x44,

  I32_EQZ: 0x45,
  I32_EQ: 0x46, I32_NE: 0x47,
  I32_LT_S: 0x48, I32_GT_S: 0x4a, I32_LE_S: 0x4c, I32_GE_S: 0x4e,

  I64_EQZ: 0x50,
  I64_EQ: 0x51, I64_NE: 0x52,
  I64_LT_S: 0x53, I64_GT_S: 0x55, I64_LE_S: 0x57, I64_GE_S: 0x59,

  F64_EQ: 0x61, F64_NE: 0x62,
  F64_LT: 0x63, F64_GT: 0x64, F64_LE: 0x65, F64_GE: 0x66,

  I32_ADD: 0x6a, I32_SUB: 0x6b, I32_MUL: 0x6c,
  I32_DIV_S: 0x6d, I32_REM_S: 0x6f,
  I32_AND: 0x71, I32_OR: 0x72,

  I64_ADD: 0x7c, I64_SUB: 0x7d, I64_MUL: 0x7e,
  I64_DIV_S: 0x7f, I64_REM_S: 0x81,

  F64_ADD: 0xa0, F64_SUB: 0xa1, F64_MUL: 0xa2, F64_DIV: 0xa3,
  F64_NEG: 0x9a,
} as const;

/** Codificación de los tipos de valor en el binario. */
const VALTYPE: ReadonlyMap<WirType, number> = new Map([
  [WirType.I32, 0x7f],
  [WirType.I64, 0x7e],
  [WirType.F64, 0x7c],
]);

const SECTION = {
  TYPE: 1, IMPORT: 2, FUNCTION: 3, MEMORY: 5, EXPORT: 7, CODE: 10, DATA: 11,
} as const;

/** Tamaño de una página de memoria lineal de WASM. */
const PAGE_SIZE = 65536;

/** `blocktype` vacío: el bloque no deja nada en la pila. */
const BLOCK_EMPTY = 0x40;

/**
 * Etiquetas abiertas, de fuera hacia dentro. WASM no salta a nombres sino a
 * PROFUNDIDADES RELATIVAS: `br 0` sale de la construcción más interna, `br 1`
 * de la siguiente. Como `break` y `continue` pueden estar dentro de varios
 * `if` anidados, la profundidad no se puede escribir a mano: se calcula
 * contando cuántas etiquetas hay entre el salto y su destino. Esta pila es
 * ese contador.
 */
type Label = "if" | "while-exit" | "while-body";

/** El codegen produjo algo que no se puede representar (fallo interno). */
export class WasmEmitError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WasmEmitError";
  }
}

// --------------------------------------------------------------------------- //
// utilidades de bytes
// --------------------------------------------------------------------------- //

/** Buffer de bytes con LEB128, el codificador de enteros de WASM. */
class ByteSink {
  #bytes: number[] = [];

  get length(): number {
    return this.#bytes.length;
  }

  byte(value: number): this {
    this.#bytes.push(value & 0xff);
    return this;
  }

  bytes(values: Iterable<number>): this {
    for (const value of values) this.#bytes.push(value & 0xff);
    return this;
  }

  /** LEB128 sin signo: longitudes, índices y cuentas. */
  u32(value: number): this {
    let v = value >>> 0;
    do {
      const byte = v & 0x7f;
      v >>>= 7;
      this.#bytes.push(v === 0 ? byte : byte | 0x80);
    } while (v !== 0);
    return this;
  }

  /** LEB128 con signo de 32 bits (`i32.const`). */
  i32(value: number): this {
    return this.i64(BigInt(value));
  }

  /** LEB128 con signo de 64 bits (`i64.const`). */
  i64(value: bigint): this {
    let v = BigInt.asIntN(64, value);
    for (;;) {
      const byte = Number(v & 0x7fn);
      v >>= 7n;
      const signBit = (byte & 0x40) !== 0;
      if ((v === 0n && !signBit) || (v === -1n && signBit)) {
        this.#bytes.push(byte);
        return this;
      }
      this.#bytes.push(byte | 0x80);
    }
  }

  /** IEEE-754 de 64 bits, little-endian (`f64.const`). */
  f64(value: number): this {
    const view = new DataView(new ArrayBuffer(8));
    view.setFloat64(0, value, true);
    for (let i = 0; i < 8; i++) this.#bytes.push(view.getUint8(i));
    return this;
  }

  /** Nombre: longitud + UTF-8 (los nombres del esquema son ASCII). */
  name(text: string): this {
    const bytes: number[] = [];
    for (let i = 0; i < text.length; i++) {
      const cp = text.charCodeAt(i);
      if (cp < 0x80) bytes.push(cp);
      else if (cp < 0x800) bytes.push(0xc0 | (cp >> 6), 0x80 | (cp & 0x3f));
      else bytes.push(0xe0 | (cp >> 12), 0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f));
    }
    this.u32(bytes.length);
    return this.bytes(bytes);
  }

  /** Un vector de WASM: cuenta + elementos. */
  vector<T>(items: readonly T[], write: (item: T, sink: ByteSink) => void): this {
    this.u32(items.length);
    for (const item of items) write(item, this);
    return this;
  }

  take(): Uint8Array {
    return new Uint8Array(this.#bytes);
  }
}

/** Firma de función, en la forma en que la sección de tipos la codifica. */
function signatureKey(params: readonly WirType[], result: WirType): string {
  return `${params.join(",")}->${result}`;
}

// --------------------------------------------------------------------------- //
// emisión
// --------------------------------------------------------------------------- //

/** WIR -> bytes de un módulo WebAssembly válido. */
export function emitWasm(module: WirModule): Uint8Array {
  // --- sección de tipos: firmas deduplicadas ---
  const typeIndex = new Map<string, number>();
  const types: { params: readonly WirType[]; result: WirType }[] = [];
  const internType = (params: readonly WirType[], result: WirType): number => {
    const key = signatureKey(params, result);
    const existing = typeIndex.get(key);
    if (existing !== undefined) return existing;
    const index = types.length;
    typeIndex.set(key, index);
    types.push({ params, result });
    return index;
  };

  const importTypes = module.imports.map((i) => internType(i.params, i.result));
  const funcTypes = module.funcs.map((f) =>
    internType(f.params.map((p) => p.type), f.result));

  const out = new ByteSink();
  out.bytes([0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00]); // "\0asm" v1

  // 1) type
  section(out, SECTION.TYPE, (s) => {
    s.vector(types, (type, sink) => {
      sink.byte(0x60); // functype
      sink.vector(type.params, (p, w) => w.byte(valtype(p)));
      if (type.result === WirType.VOID) sink.u32(0);
      else sink.u32(1).byte(valtype(type.result));
    });
  });

  // 2) import
  if (module.imports.length > 0) {
    section(out, SECTION.IMPORT, (s) => {
      s.u32(module.imports.length);
      module.imports.forEach((imported, i) => {
        s.name(imported.module).name(imported.name);
        s.byte(0x00); // kind: función
        s.u32(importTypes[i]!);
      });
    });
  }

  // 3) function
  section(out, SECTION.FUNCTION, (s) => {
    s.vector(funcTypes, (index, sink) => sink.u32(index));
  });

  // 5) memory — solo si hay cadenas que colocar.
  const pages = module.dataSize > 0 ? Math.ceil(module.dataSize / PAGE_SIZE) : 0;
  if (pages > 0) {
    section(out, SECTION.MEMORY, (s) => {
      s.u32(1);            // una memoria
      s.byte(0x00);        // límites: solo mínimo
      s.u32(Math.max(pages, 1));
    });
  }

  // 7) export
  const importCount = module.imports.length;
  section(out, SECTION.EXPORT, (s) => {
    const exports: { name: string; kind: number; index: number }[] = [];
    if (pages > 0) exports.push({ name: "memory", kind: 0x02, index: 0 });
    module.funcs.forEach((fn, i) => {
      if (fn.exported) {
        exports.push({ name: fn.name, kind: 0x00, index: importCount + i });
      }
    });
    s.vector(exports, (e, sink) => sink.name(e.name).byte(e.kind).u32(e.index));
  });

  // 10) code
  section(out, SECTION.CODE, (s) => {
    s.vector(module.funcs, (fn, sink) => {
      const body = emitFunctionBody(fn, importCount);
      sink.u32(body.length).bytes(body);
    });
  });

  // 11) data
  if (module.strings.length > 0) {
    section(out, SECTION.DATA, (s) => {
      s.vector(module.strings, (str, sink) => {
        sink.u32(0);                       // memoria 0, modo activo
        sink.byte(OP.I32_CONST).i32(str.offset).byte(OP.END);  // offset
        sink.u32(str.bytes.length).bytes(str.bytes);
      });
    });
  }

  return out.take();
}

function valtype(type: WirType): number {
  const code = VALTYPE.get(type);
  if (code === undefined) {
    throw new WasmEmitError(`el tipo ${type} no tiene codificación en WASM`);
  }
  return code;
}

/** Escribe una sección: id + longitud + contenido. */
function section(out: ByteSink, id: number, build: (sink: ByteSink) => void): void {
  const body = new ByteSink();
  build(body);
  const bytes = body.take();
  out.byte(id).u32(bytes.length).bytes(bytes);
}

/**
 * Cuerpo de una función: declaración de locales (agrupados por tipo, como
 * exige el formato) + instrucciones + `end`.
 */
function emitFunctionBody(fn: WirFunc, importCount: number): Uint8Array {
  const sink = new ByteSink();

  // locales: se codifican como pares (cuenta, tipo) de tipos CONSECUTIVOS.
  const groups: { count: number; type: WirType }[] = [];
  for (const local of fn.locals) {
    const last = groups[groups.length - 1];
    if (last !== undefined && last.type === local.type) last.count++;
    else groups.push({ count: 1, type: local.type });
  }
  sink.vector(groups, (group, s) => s.u32(group.count).byte(valtype(group.type)));

  const labels: Label[] = [];
  for (const stmt of fn.body) emitStmt(stmt, sink, importCount, labels);

  // Toda función tiene que dejar en la pila exactamente su tipo de retorno.
  // Si el cuerpo no termina en 'return', se añade el valor por defecto: es el
  // caso de 'fn f() -> int { }' que la semántica permite y el intérprete
  // resuelve con 0.
  if (fn.result !== WirType.VOID && !endsWithReturn(fn.body)) {
    emitDefault(fn.result, sink);
  }
  sink.byte(OP.END);
  return sink.take();
}

function endsWithReturn(body: readonly WirStmt[]): boolean {
  return body.length > 0 && body[body.length - 1]!.kind === "return";
}

function emitDefault(type: WirType, sink: ByteSink): void {
  switch (type) {
    case WirType.I32: sink.byte(OP.I32_CONST).i32(0); return;
    case WirType.I64: sink.byte(OP.I64_CONST).i64(0n); return;
    case WirType.F64: sink.byte(OP.F64_CONST).f64(0); return;
    default: return;
  }
}

/**
 * Profundidad relativa hasta la etiqueta `target` más interna. `br` cuenta
 * desde dentro hacia fuera: 0 es la construcción que rodea al salto.
 */
function depthTo(labels: readonly Label[], target: Label): number {
  for (let i = labels.length - 1; i >= 0; i--) {
    if (labels[i] === target) return labels.length - 1 - i;
  }
  // el lowering ya rechaza break/continue fuera de un bucle (WEB100).
  throw new WasmEmitError(`no hay ninguna etiqueta '${target}' abierta`);
}

function emitStmt(
  stmt: WirStmt, sink: ByteSink, importCount: number, labels: Label[],
): void {
  switch (stmt.kind) {
    case "local.set":
      emitExpr(stmt.value, sink, importCount, labels);
      sink.byte(OP.LOCAL_SET).u32(stmt.index);
      return;

    case "drop":
      emitExpr(stmt.value, sink, importCount, labels);
      // una llamada 'void' no deja nada en la pila: no hay qué descartar.
      if (stmt.value.type !== WirType.VOID) sink.byte(OP.DROP);
      return;

    case "return":
      if (stmt.value !== null) emitExpr(stmt.value, sink, importCount, labels);
      sink.byte(OP.RETURN);
      return;

    case "if":
      emitExpr(stmt.condition, sink, importCount, labels);
      sink.byte(OP.IF).byte(BLOCK_EMPTY);
      labels.push("if");
      for (const inner of stmt.then) emitStmt(inner, sink, importCount, labels);
      if (stmt.otherwise.length > 0) {
        sink.byte(OP.ELSE);
        for (const inner of stmt.otherwise) emitStmt(inner, sink, importCount, labels);
      }
      labels.pop();
      sink.byte(OP.END);
      return;

    case "while":
      // El patrón canónico de un bucle 'while' en WebAssembly:
      //
      //   block            ;; destino de 'break' y de la salida normal
      //     loop           ;; destino de 'continue'
      //       <cond> i32.eqz
      //       br_if 1      ;; condición falsa -> sale del block
      //       <cuerpo>
      //       br 0         ;; otra vuelta
      //     end
      //   end
      sink.byte(OP.BLOCK).byte(BLOCK_EMPTY);
      labels.push("while-exit");
      sink.byte(OP.LOOP).byte(BLOCK_EMPTY);
      labels.push("while-body");

      emitExpr(stmt.condition, sink, importCount, labels);
      sink.byte(OP.I32_EQZ);
      sink.byte(OP.BR_IF).u32(depthTo(labels, "while-exit"));

      for (const inner of stmt.body) emitStmt(inner, sink, importCount, labels);
      sink.byte(OP.BR).u32(depthTo(labels, "while-body"));

      labels.pop();
      sink.byte(OP.END);
      labels.pop();
      sink.byte(OP.END);
      return;

    case "break":
      sink.byte(OP.BR).u32(depthTo(labels, "while-exit"));
      return;

    case "continue":
      sink.byte(OP.BR).u32(depthTo(labels, "while-body"));
      return;

    default:
      throw new WasmEmitError(
        `sentencia del WIR sin traducción a WASM: ${(stmt satisfies never as { kind: string }).kind}`,
      );
  }
}

/** Post-orden: primero los operandos (quedan en la pila), luego el opcode. */
function emitExpr(
  expr: WirExpr, sink: ByteSink, importCount: number, labels: Label[],
): void {
  switch (expr.kind) {
    case "const":
      switch (expr.type) {
        case WirType.I32:
          sink.byte(OP.I32_CONST).i32(Number(expr.value));
          return;
        case WirType.I64:
          sink.byte(OP.I64_CONST).i64(BigInt(expr.value));
          return;
        case WirType.F64:
          sink.byte(OP.F64_CONST).f64(Number(expr.value));
          return;
        default:
          throw new WasmEmitError("una constante no puede ser de tipo void");
      }

    case "local.get":
      sink.byte(OP.LOCAL_GET).u32(expr.index);
      return;

    case "binary":
      emitExpr(expr.left, sink, importCount, labels);
      emitExpr(expr.right, sink, importCount, labels);
      sink.byte(binaryOpcode(expr.op, expr.operandType));
      return;

    case "unary":
      if (expr.op === WirUnOp.NOT) {
        emitExpr(expr.operand, sink, importCount, labels);
        sink.byte(OP.I32_EQZ);
        return;
      }
      // negación: 0 - x para enteros (WASM no tiene i64.neg), f64.neg para reales.
      if (expr.operand.type === WirType.F64) {
        emitExpr(expr.operand, sink, importCount, labels);
        sink.byte(OP.F64_NEG);
        return;
      }
      if (expr.operand.type === WirType.I32) sink.byte(OP.I32_CONST).i32(0);
      else sink.byte(OP.I64_CONST).i64(0n);
      emitExpr(expr.operand, sink, importCount, labels);
      sink.byte(expr.operand.type === WirType.I32 ? OP.I32_SUB : OP.I64_SUB);
      return;

    case "call":
      for (const arg of expr.args) emitExpr(arg, sink, importCount, labels);
      sink.byte(OP.CALL).u32(importCount + expr.func);
      return;

    case "call.host":
      for (const arg of expr.args) emitExpr(arg, sink, importCount, labels);
      sink.byte(OP.CALL).u32(expr.host);
      return;

    case "logical": {
      // Cortocircuito: en una máquina de pila no existe un operador que lo
      // haga, hay que RAMIFICAR. 'a and b' es "si a, vale b; si no, 0";
      // 'a or b' es "si a, 1; si no, vale b". El bloque deja un i32, así que
      // su blocktype es i32 y no el vacío.
      emitExpr(expr.left, sink, importCount, labels);
      sink.byte(OP.IF).byte(valtype(WirType.I32));
      labels.push("if");
      if (expr.op === "and") {
        emitExpr(expr.right, sink, importCount, labels);
        sink.byte(OP.ELSE);
        sink.byte(OP.I32_CONST).i32(0);
      } else {
        sink.byte(OP.I32_CONST).i32(1);
        sink.byte(OP.ELSE);
        emitExpr(expr.right, sink, importCount, labels);
      }
      labels.pop();
      sink.byte(OP.END);
      return;
    }

    default:
      // Guarda de exhaustividad: si el WIR gana una variante, ESTO no
      // compila. Sin ella, un `switch` de casos `void` la ignora en
      // silencio y el binario sale mal formado — que es exactamente lo que
      // pasó al añadir 'logical'.
      throw new WasmEmitError(
        `expresión del WIR sin traducción a WASM: ${(expr satisfies never as { kind: string }).kind}`,
      );
  }
}

function binaryOpcode(op: WirBinOp, type: WirType): number {
  switch (type) {
    case WirType.I64:
      switch (op) {
        case WirBinOp.ADD: return OP.I64_ADD;
        case WirBinOp.SUB: return OP.I64_SUB;
        case WirBinOp.MUL: return OP.I64_MUL;
        case WirBinOp.DIV: return OP.I64_DIV_S;
        case WirBinOp.REM: return OP.I64_REM_S;
        case WirBinOp.EQ: return OP.I64_EQ;
        case WirBinOp.NE: return OP.I64_NE;
        case WirBinOp.LT: return OP.I64_LT_S;
        case WirBinOp.LE: return OP.I64_LE_S;
        case WirBinOp.GT: return OP.I64_GT_S;
        case WirBinOp.GE: return OP.I64_GE_S;
        default:
          throw new WasmEmitError(`operador '${op}' no aplicable a i64`);
      }
    case WirType.F64:
      switch (op) {
        case WirBinOp.ADD: return OP.F64_ADD;
        case WirBinOp.SUB: return OP.F64_SUB;
        case WirBinOp.MUL: return OP.F64_MUL;
        case WirBinOp.DIV: return OP.F64_DIV;
        case WirBinOp.EQ: return OP.F64_EQ;
        case WirBinOp.NE: return OP.F64_NE;
        case WirBinOp.LT: return OP.F64_LT;
        case WirBinOp.LE: return OP.F64_LE;
        case WirBinOp.GT: return OP.F64_GT;
        case WirBinOp.GE: return OP.F64_GE;
        default:
          throw new WasmEmitError(`operador '${op}' no aplicable a f64`);
      }
    case WirType.I32:
      switch (op) {
        case WirBinOp.ADD: return OP.I32_ADD;
        case WirBinOp.SUB: return OP.I32_SUB;
        case WirBinOp.MUL: return OP.I32_MUL;
        case WirBinOp.DIV: return OP.I32_DIV_S;
        case WirBinOp.REM: return OP.I32_REM_S;
        case WirBinOp.EQ: return OP.I32_EQ;
        case WirBinOp.NE: return OP.I32_NE;
        case WirBinOp.LT: return OP.I32_LT_S;
        case WirBinOp.LE: return OP.I32_LE_S;
        case WirBinOp.GT: return OP.I32_GT_S;
        case WirBinOp.GE: return OP.I32_GE_S;
        case WirBinOp.AND: return OP.I32_AND;
        case WirBinOp.OR: return OP.I32_OR;
        default:
          throw new WasmEmitError(`operador '${op}' no aplicable a i32`);
      }
    default:
      throw new WasmEmitError(`no hay instrucción '${op}' para el tipo ${type}`);
  }
}
