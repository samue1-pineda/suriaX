/**
 * Backend JS: WIR -> módulo ES ejecutable, sin WebAssembly.
 *
 * Dos motivos para tenerlo, y ninguno es "por si acaso":
 *
 *  1. **es el oráculo del backend WASM**. Los dos salen del MISMO WIR, así
 *     que tienen que dar exactamente el mismo resultado; la suite ejecuta
 *     ambos y compara. Cuando difieren, el culpable es el emisor, no el
 *     lowering — que es justo lo que un puente bien puesto permite deducir.
 *  2. **cubre lo que WASM aún no**: el día que el subconjunto crezca con
 *     cadenas o structs, el backend JS los tendrá antes (JS ya trae GC y
 *     strings), y el playground podrá ejecutar programas que el WASM todavía
 *     rechace.
 *
 * ### Fidelidad de los enteros
 * El `int` de suriaX es de 64 bits: en JS eso es `BigInt`, no `number`. Y
 * como WASM envuelve al desbordar, cada operación entera se cierra con
 * `BigInt.asIntN(64, …)`. Sin eso, `int` daría resultados distintos en los
 * dos backends en cuanto un programa desbordara — el bug clásico de los
 * transpiladores a JS.
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
import { FORMAT_RUNTIME } from "./runtime.ts";

/** Identificador JS seguro a partir de un nombre de suriaX. */
function jsName(name: string): string {
  const clean = name.replace(/[^A-Za-z0-9_$]/g, "_");
  return /^[0-9]/.test(clean) ? `_${clean}` : clean;
}

/**
 * Nombre JS de una función, desambiguado por su índice — igual que un local.
 *
 * El WIR ya cualifica las funciones de librería (`math.basic.add`), pero
 * `jsName` colapsa los puntos a `_`, así que dos nombres distintos podrían
 * sanearse al mismo. El índice es la identidad real de una función en el WIR
 * y no depende de que esa colisión no ocurra nunca.
 */
function funcName(index: number, fn: WirFunc): string {
  return `${jsName(fn.name)}$${index}`;
}

function localName(index: number, fn: WirFunc): string {
  const local = index < fn.params.length
    ? fn.params[index]
    : fn.locals[index - fn.params.length];
  return `${jsName(local?.name ?? "tmp")}$${index}`;
}

/** WIR -> código de un módulo ES que exporta `run()`. */
export function emitJs(module: WirModule): string {
  const lines: string[] = [
    "// Generado por el backend web de suriaX (WIR -> JS).",
    `// Fuente: ${module.source || "<memoria>"}`,
    "// int de suriaX = 64 bits: BigInt con envoltura explícita, como en WASM.",
    "",
    "const wrap = (v) => BigInt.asIntN(64, v);",
    // 'i64.trunc_sat_f64_s' de WASM, en JS: trunca hacia cero y satura en los
    // extremos del rango de i64. Sin la saturación, 'BigInt(Infinity)' lanza y
    // el programa moriría donde el WASM habría seguido con INT64_MAX.
    "const __I64_MIN = -(2n ** 63n), __I64_MAX = 2n ** 63n - 1n;",
    "const __truncSat = (v) => {",
    "  if (Number.isNaN(v)) return 0n;",
    "  const t = Math.trunc(v);",
    "  if (t <= -(2 ** 63)) return __I64_MIN;",
    "  if (t >= 2 ** 63) return __I64_MAX;",
    "  return BigInt(t);",
    "};",
    "const __io = { write: (text) => console.log(text) };",
    // Las globales del módulo: en JS son variables de módulo, que es
    // exactamente lo que son en WASM. 'const' se emite como 'let' igual: el
    // que impide reasignarlas es el compilador, y ya lo hizo.
    ...module.globals.map(
      (g) => `let ${jsName(g.name)} = ${g.type === WirType.I64 || g.type === WirType.I32
        ? (g.type === WirType.I64 ? `${g.init}n` : String(g.init))
        : String(g.init)};`),
    // La tabla de cadenas constantes: 'str' es un índice en ella.
    `const __strings = ${JSON.stringify(module.strings.map((s) => s.text))};`,
    "const __fmtStr = (i) => __strings[Number(i)] ?? \"\";",
    FORMAT_RUNTIME,
    "",
  ];

  module.funcs.forEach((fn, i) => {
    lines.push(emitFunction(fn, module, i), "");
  });

  const main = module.entry === null ? null : module.funcs[module.entry] ?? null;
  const init = module.init === null ? null : module.funcs[module.init] ?? null;

  lines.push(
    "/**",
    " * Ejecuta el programa.",
    " * @param {{write?: (text: string) => void}} io salida del host.",
    " */",
    "export function run(io = {}) {",
    "  __io.write = io.write ?? ((text) => console.log(text));",
  );
  if (init !== null) lines.push(`  ${funcName(module.init!, init)}();`);
  lines.push(
    main === null
      ? "  return undefined;"
      : `  return ${funcName(module.entry!, main)}();`,
    "}",
    "",
    "export default run;",
  );

  // Las funciones del programa se exportan por su nombre, igual que hace el
  // WASM: los dos backends salen del MISMO WIR y exponer lo mismo es lo que
  // permite compararlos función a función. El nombre interno lleva el índice
  // (dos unidades pueden declarar 'max'); el export usa el nombre saneado, y
  // si dos se sanean igual gana el primero — no se exporta un nombre
  // ambiguo, se omite.
  const exported = new Map<string, string>();
  module.funcs.forEach((fn, i) => {
    const name = jsName(fn.name);
    if (!exported.has(name)) exported.set(name, funcName(i, fn));
  });
  if (exported.size > 0) {
    const items = [...exported].map(([name, internal]) =>
      name === internal ? name : `${internal} as ${name}`);
    lines.push("", `export { ${items.join(", ")} };`);
  }
  return lines.join("\n") + "\n";
}

function emitFunction(fn: WirFunc, module: WirModule, index: number): string {
  const params = fn.params.map((_, i) => localName(i, fn)).join(", ");
  const lines = [`function ${funcName(index, fn)}(${params}) {`];
  for (let i = 0; i < fn.locals.length; i++) {
    const index = fn.params.length + i;
    const local = fn.locals[i]!;
    // WASM inicializa los locales a cero: el JS tiene que hacer lo mismo.
    lines.push(`  let ${localName(index, fn)} = ${zeroOf(local.type)};`);
  }
  for (const stmt of fn.body) emitStmt(stmt, fn, module, lines, 1);
  if (fn.result !== WirType.VOID && !endsWithReturn(fn.body)) {
    lines.push(`  return ${zeroOf(fn.result)};`);
  }
  lines.push("}");
  return lines.join("\n");
}

function endsWithReturn(body: readonly WirStmt[]): boolean {
  return body.length > 0 && body[body.length - 1]!.kind === "return";
}

function zeroOf(type: WirType): string {
  switch (type) {
    case WirType.I64: return "0n";
    case WirType.F64: return "0";
    case WirType.I32: return "0";
    default: return "undefined";
  }
}

function emitStmt(
  stmt: WirStmt, fn: WirFunc, module: WirModule, out: string[], depth: number,
): void {
  const pad = "  ".repeat(depth);
  switch (stmt.kind) {
    case "local.set":
      out.push(`${pad}${localName(stmt.index, fn)} = ${emitExpr(stmt.value, fn, module)};`);
      return;
    case "global.set":
      out.push(`${pad}${jsName(module.globals[stmt.index]?.name ?? String(stmt.index))}` +
               ` = ${emitExpr(stmt.value, fn, module)};`);
      return;
    case "drop":
      out.push(`${pad}${emitExpr(stmt.value, fn, module)};`);
      return;
    case "return":
      out.push(stmt.value === null
        ? `${pad}return;`
        : `${pad}return ${emitExpr(stmt.value, fn, module)};`);
      return;
    case "if": {
      // la condición es i32 (0/1), como en WASM: se compara con 0 explícito
      // para no depender de la veracidad de JS.
      out.push(`${pad}if (${emitExpr(stmt.condition, fn, module)} !== 0) {`);
      for (const inner of stmt.then) emitStmt(inner, fn, module, out, depth + 1);
      if (stmt.otherwise.length > 0) {
        out.push(`${pad}} else {`);
        for (const inner of stmt.otherwise) emitStmt(inner, fn, module, out, depth + 1);
      }
      out.push(`${pad}}`);
      return;
    }
    case "while":
      out.push(`${pad}while (${emitExpr(stmt.condition, fn, module)} !== 0) {`);
      for (const inner of stmt.body) emitStmt(inner, fn, module, out, depth + 1);
      out.push(`${pad}}`);
      return;
    case "break":
      out.push(`${pad}break;`);
      return;
    case "continue":
      out.push(`${pad}continue;`);
      return;

    default:
      throw new Error(
        `sentencia del WIR sin traducción a JS: ${(stmt satisfies never as { kind: string }).kind}`,
      );
  }
}

function emitExpr(expr: WirExpr, fn: WirFunc, module: WirModule): string {
  switch (expr.kind) {
    case "const":
      if (expr.type === WirType.I64) return `${BigInt(expr.value).toString()}n`;
      if (expr.type === WirType.F64) return formatF64(Number(expr.value));
      return Number(expr.value).toString();

    case "local.get":
      return localName(expr.index, fn);

    case "binary": {
      const left = emitExpr(expr.left, fn, module);
      const right = emitExpr(expr.right, fn, module);
      const op = JS_BINARY.get(expr.op);
      if (op === undefined) return "undefined";
      const raw = `(${left} ${op} ${right})`;
      if (expr.type === WirType.I32 && expr.operandType !== WirType.I32) {
        // una comparación devuelve bool: en WASM es i32 (0/1), aquí también,
        // para que los dos backends devuelvan lo mismo.
        return `(${raw} ? 1 : 0)`;
      }
      if (expr.operandType === WirType.I64) {
        if (expr.op === WirBinOp.DIV || expr.op === WirBinOp.REM) {
          return `wrap(${raw})`;  // BigInt ya trunca hacia cero, como WASM
        }
        return `wrap(${raw})`;
      }
      if (expr.type === WirType.I32) return `(${raw} ? 1 : 0)`;
      return raw;
    }

    case "unary":
      if (expr.op === WirUnOp.NOT) {
        return `(${emitExpr(expr.operand, fn, module)} ? 0 : 1)`;
      }
      return expr.operand.type === WirType.I64
        ? `wrap(-${emitExpr(expr.operand, fn, module)})`
        : `(-${emitExpr(expr.operand, fn, module)})`;

    case "call": {
      const target = module.funcs[expr.func];
      const args = expr.args.map((a) => emitExpr(a, fn, module)).join(", ");
      if (target !== undefined) {
        return `${funcName(expr.func, target)}(${args})`;
      }
      return `${jsName(target?.name ?? "desconocida")}(${args})`;
    }

    case "call.host": {
      const primitive = module.imports[expr.host];
      // '__write__(ptr, len)': en JS no hay memoria lineal, así que la cadena
      // se resuelve en tiempo de GENERACIÓN mirando el data segment. Es el
      // camino de todo texto constante, y el más barato de los dos.
      if (primitive === undefined || primitive.name === "__write__") {
        return `__io.write(${JSON.stringify(hostText(expr, module))})`;
      }
      // ...y las demás escriben un VALOR, formateado por el runtime del host.
      const value = emitExpr(expr.args[0]!, fn, module);
      const format = HOST_FORMATTERS.get(primitive.name);
      if (format === undefined) {
        throw new Error(`primitiva del host sin traducción a JS: ${primitive.name}`);
      }
      return `__io.write(${format}(${value}))`;
    }

    case "seq": {
      // el valor es el de la última; en JS, el operador coma.
      const parts = expr.exprs.map((e) => emitExpr(e, fn, module));
      return parts.length === 1 ? parts[0]! : `(${parts.join(", ")})`;
    }

    case "logical": {
      // se conserva el CORTOCIRCUITO y el resultado 0/1 de WASM: el operador
      // ternario evalúa el lado derecho solo cuando hace falta.
      const left = emitExpr(expr.left, fn, module);
      const right = emitExpr(expr.right, fn, module);
      return expr.op === "and"
        ? `(${left} !== 0 ? (${right} !== 0 ? 1 : 0) : 0)`
        : `(${left} !== 0 ? 1 : (${right} !== 0 ? 1 : 0))`;
    }

    case "global.get":
      return jsName(module.globals[expr.index]?.name ?? `global${expr.index}`);

    case "convert": {
      // Las mismas reglas que emite WASM, porque los dos backends tienen que
      // dar el MISMO resultado (este es el oráculo del otro):
      //   int -> float   BigInt a Number
      //   float -> int   trunca hacia cero y SATURA (i64.trunc_sat_f64_s):
      //                  ni NaN ni un infinito pueden abortar el programa
      //   int <-> char/bool   los anchos de la máquina de pila (i64 <-> i32)
      const valor = emitExpr(expr.value, fn, module);
      if (expr.from === WirType.I64 && expr.type === WirType.F64) {
        return `Number(${valor})`;
      }
      if (expr.from === WirType.F64 && expr.type === WirType.I64) {
        return `__truncSat(${valor})`;
      }
      if (expr.from === WirType.I64 && expr.type === WirType.I32) {
        return `Number(BigInt.asIntN(32, ${valor}))`;
      }
      if (expr.from === WirType.I32 && expr.type === WirType.I64) {
        return `BigInt(${valor})`;
      }
      return valor;   // mismo tipo: el lowering ya no debería pedirla
    }

    default:
      throw new Error(
        `expresión del WIR sin traducción a JS: ${(expr satisfies never as { kind: string }).kind}`,
      );
  }
}

/** Primitiva del host -> formateador del runtime que la implementa. */
const HOST_FORMATTERS: ReadonlyMap<string, string> = new Map([
  ["__write_int__", "__fmtInt"],
  ["__write_float__", "__fmtFloat"],
  ["__write_bool__", "__fmtBool"],
  ["__write_char__", "__fmtChar"],
  // una cadena viaja como el índice de su constante; el formateador la busca
  // en la tabla que este mismo módulo emite.
  ["__write_str__", "__fmtStr"],
]);

/**
 * Recupera el texto de un `__write__(offset, len)` mirando el data segment.
 * Es lo que permite que el JS no necesite memoria lineal para imprimir.
 */
function hostText(expr: Extract<WirExpr, { kind: "call.host" }>, module: WirModule): string {
  const offsetArg = expr.args[0];
  const lengthArg = expr.args[1];
  if (offsetArg?.kind !== "const" || lengthArg?.kind !== "const") return "";
  const offset = Number(offsetArg.value);
  const length = Number(lengthArg.value);
  for (const str of module.strings) {
    if (str.offset === offset && str.bytes.length === length) return str.text;
  }
  return "";
}

const JS_BINARY: ReadonlyMap<WirBinOp, string> = new Map([
  [WirBinOp.ADD, "+"], [WirBinOp.SUB, "-"], [WirBinOp.MUL, "*"],
  [WirBinOp.DIV, "/"], [WirBinOp.REM, "%"],
  [WirBinOp.EQ, "==="], [WirBinOp.NE, "!=="],
  [WirBinOp.LT, "<"], [WirBinOp.LE, "<="],
  [WirBinOp.GT, ">"], [WirBinOp.GE, ">="],
  [WirBinOp.AND, "&&"], [WirBinOp.OR, "||"],
]);

/** Un f64 que vuelva a leerse como el MISMO valor (y que se vea como float). */
function formatF64(value: number): string {
  if (Number.isInteger(value) && Math.abs(value) < 1e21) return `${value}.0`;
  return String(value);
}

// --------------------------------------------------------------------------- //
// módulo host (el que ejecuta el WASM)
// --------------------------------------------------------------------------- //

/** Alfabeto base64 estándar. */
const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/** Bytes -> base64, sin `btoa` ni `Buffer` (esto corre en los dos entornos). */
export function toBase64(bytes: Uint8Array): string {
  let out = "";
  let i = 0;
  for (; i + 2 < bytes.length; i += 3) {
    const n = (bytes[i]! << 16) | (bytes[i + 1]! << 8) | bytes[i + 2]!;
    out += B64[(n >> 18) & 63]! + B64[(n >> 12) & 63]! + B64[(n >> 6) & 63]! + B64[n & 63]!;
  }
  if (i + 1 === bytes.length) {
    const n = bytes[i]! << 16;
    out += B64[(n >> 18) & 63]! + B64[(n >> 12) & 63]! + "==";
  } else if (i + 2 === bytes.length) {
    const n = (bytes[i]! << 16) | (bytes[i + 1]! << 8);
    out += B64[(n >> 18) & 63]! + B64[(n >> 12) & 63]! + B64[(n >> 6) & 63]! + "=";
  }
  return out;
}

/**
 * Módulo ES que **embebe el WASM** y lo ejecuta: el artefacto final del
 * target web. Es autosuficiente —no importa nada— así que vale igual en el
 * navegador, en node o guardado en un archivo.
 */
export function emitHostModule(module: WirModule, wasm: Uint8Array): string {
  const main = module.entry === null ? null : module.funcs[module.entry] ?? null;
  const init = module.init === null ? null : module.funcs[module.init] ?? null;

  return `// Generado por el backend web de suriaX (WIR -> WASM + host JS).
// Fuente: ${module.source || "<memoria>"}
// El módulo WebAssembly va embebido en base64: este archivo no depende de nada.

const WASM_BASE64 =
  "${toBase64(wasm)}";

// Las cadenas CONSTANTES del programa, en el orden en que el módulo las
// numera: una cadena guardada en una variable viaja como su índice aquí.
const STRINGS = ${JSON.stringify(module.strings.map((s) => s.text))};

${FORMAT_RUNTIME}

function decodeBase64(text) {
  const table = new Uint8Array(128);
  const alphabet = "${B64}";
  for (let i = 0; i < alphabet.length; i++) table[alphabet.charCodeAt(i)] = i;
  const clean = text.replace(/=+$/, "");
  const out = new Uint8Array((clean.length * 3) >> 2);
  let bits = 0, acc = 0, o = 0;
  for (let i = 0; i < clean.length; i++) {
    acc = (acc << 6) | table[clean.charCodeAt(i)];
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out[o++] = (acc >> bits) & 0xff;
    }
  }
  return out;
}

/**
 * Instancia el módulo y devuelve sus exports.
 * @param {{write?: (text: string) => void}} io salida del host.
 */
export async function instantiate(io = {}) {
  const write = io.write ?? ((text) => console.log(text));
  const bytes = decodeBase64(WASM_BASE64);
  let memory = null;
  const decoder = new TextDecoder();
  const { instance } = await WebAssembly.instantiate(bytes, {
    env: {
      // contrato de lib/io/stdp.libsrx: __write__(puntero, longitud).
      __write__(ptr, len) {
        const view = new Uint8Array(memory.buffer, ptr, len);
        write(decoder.decode(view));
      },
      // ...y las primitivas que escriben un VALOR: el host las formatea, con
      // el MISMO runtime que usa el backend JS puro (web/src/codegen/runtime.ts).
      __write_int__(v) { write(__fmtInt(v)); },
      __write_float__(v) { write(__fmtFloat(v)); },
      __write_bool__(v) { write(__fmtBool(v)); },
      __write_char__(v) { write(__fmtChar(v)); },
      // Una cadena en una VARIABLE viaja como el índice de su constante: el
      // host tiene la tabla, así que escribirla es mirarla. (Los literales
      // siguen yendo por '__write__': ahí el offset y la longitud se conocen
      // al compilar y no hace falta la tabla.)
      __write_str__(i) { write(STRINGS[i] ?? ""); },
    },
  });
  memory = instance.exports.memory;
  return instance.exports;
}

/** Ejecuta el programa: inicialización de módulo y luego la entrada. */
export async function run(io = {}) {
  const exports = await instantiate(io);
${init === null ? "" : `  exports.${init.name}();\n`}${
    main === null ? "  return undefined;" : `  return exports.${main.name}();`
  }
}

export default run;
`;
}
