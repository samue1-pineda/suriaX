/**
 * Backend WAT: WIR -> WebAssembly en formato TEXTO.
 *
 * No se ensambla ni se ejecuta: es el artefacto **legible** del target web,
 * la vista que responde "¿en qué se convirtió mi programa?". El proyecto
 * existe para enseñar qué entrega cada fase (`ARCHITECTURE.md`), y un binario
 * no enseña nada; este texto sí, y además hace evidente el carácter de PILA
 * de WASM: cada línea empuja o consume.
 *
 * El texto es WAT válido —se puede pegar en wat2wasm o en las herramientas
 * del navegador— pero el binario que se ejecuta lo produce `wasm.ts`
 * directamente, no este archivo: una sola fuente de verdad para la ejecución.
 */

import {
  WirBinOp,
  WirType,
  WirUnOp,
  typeName,
  type WirExpr,
  type WirFunc,
  type WirModule,
  type WirStmt,
} from "../wir/wir.ts";

/**
 * Instrucción de conversión, por par origen->destino.
 *
 * La clave se arma con los números de `WirType` porque es la forma directa de
 * indexar un par; el emisor binario tiene la MISMA tabla en opcodes, y las
 * dos salen del mismo sitio del lowering.
 */
const CONVERSION: Readonly<Record<string, string>> = {
  [`${WirType.I64}->${WirType.F64}`]: "f64.convert_i64_s",
  // saturante: un NaN o un infinito no pueden abortar el módulo
  [`${WirType.F64}->${WirType.I64}`]: "i64.trunc_sat_f64_s",
  [`${WirType.I64}->${WirType.I32}`]: "i32.wrap_i64",
  [`${WirType.I32}->${WirType.I64}`]: "i64.extend_i32_s",
};

/** WIR -> texto WAT. */
export function emitWat(module: WirModule): string {
  const lines: string[] = [
    `;; Generado por el backend web de suriaX (WIR -> WAT).`,
    `;; Fuente: ${module.source || "<memoria>"}`,
    ";; WebAssembly es una máquina de PILA: cada instrucción consume lo que",
    ";; hay encima y deja su resultado. Una expresión es su post-orden.",
    "(module",
  ];

  for (const imported of module.imports) {
    const params = imported.params.map((p) => typeName(p)).join(" ");
    const result = imported.result === WirType.VOID ? "" : ` (result ${typeName(imported.result)})`;
    lines.push(
      `  (import "${imported.module}" "${imported.name}" ` +
        `(func $${imported.name}${params === "" ? "" : ` (param ${params})`}${result}))`,
    );
  }

  if (module.dataSize > 0) {
    lines.push(`  (memory (export "memory") 1)`);
    for (const str of module.strings) {
      lines.push(`  (data (i32.const ${str.offset}) ${JSON.stringify(str.text)})`);
    }
  }

  for (const global of module.globals) {
    const tipo = typeName(global.type);
    const decl = global.mutable ? `(mut ${tipo})` : tipo;
    const valor = global.type === WirType.F64
      ? `f64.const ${global.init}` : `${tipo}.const ${global.init}`;
    lines.push(`  (global $${global.name} ${decl} (${valor}))`);
  }

  for (const fn of module.funcs) {
    lines.push("", ...emitFunction(fn, module).map((l) => "  " + l));
  }

  lines.push(")");
  return lines.join("\n") + "\n";
}

function emitFunction(fn: WirFunc, module: WirModule): string[] {
  const header: string[] = [`(func $${fn.name}`];
  if (fn.exported) header.push(`  (export "${fn.name}")`);
  for (const param of fn.params) {
    header.push(`  (param $${param.name} ${typeName(param.type)})`);
  }
  if (fn.result !== WirType.VOID) header.push(`  (result ${typeName(fn.result)})`);
  for (const local of fn.locals) {
    header.push(`  (local $${local.name} ${typeName(local.type)})`);
  }

  const body: string[] = [];
  for (const stmt of fn.body) emitStmt(stmt, fn, module, body, 1);
  if (fn.result !== WirType.VOID && !endsWithReturn(fn.body)) {
    body.push(`  ${constOf(fn.result)}   ;; valor por defecto del retorno`);
  }
  return [...header, ...body, ")"];
}

function endsWithReturn(body: readonly WirStmt[]): boolean {
  return body.length > 0 && body[body.length - 1]!.kind === "return";
}

function constOf(type: WirType): string {
  switch (type) {
    case WirType.I64: return "i64.const 0";
    case WirType.F64: return "f64.const 0";
    default: return "i32.const 0";
  }
}

function localRef(index: number, fn: WirFunc): string {
  const local = index < fn.params.length
    ? fn.params[index]
    : fn.locals[index - fn.params.length];
  return `$${local?.name ?? index}`;
}

function emitStmt(
  stmt: WirStmt, fn: WirFunc, module: WirModule, out: string[], depth: number,
): void {
  const pad = "  ".repeat(depth);
  switch (stmt.kind) {
    case "local.set":
      emitExpr(stmt.value, fn, module, out, depth);
      out.push(`${pad}local.set ${localRef(stmt.index, fn)}   ;; línea ${stmt.pos.ln}`);
      return;
    case "global.set":
      emitExpr(stmt.value, fn, module, out, depth);
      out.push(`${pad}global.set $${module.globals[stmt.index]?.name ?? stmt.index}` +
               `   ;; línea ${stmt.pos.ln}`);
      return;
    case "drop":
      emitExpr(stmt.value, fn, module, out, depth);
      if (stmt.value.type !== WirType.VOID) out.push(`${pad}drop`);
      return;
    case "return":
      if (stmt.value !== null) emitExpr(stmt.value, fn, module, out, depth);
      out.push(`${pad}return`);
      return;

    case "if":
      emitExpr(stmt.condition, fn, module, out, depth);
      out.push(`${pad}if   ;; línea ${stmt.pos.ln}`);
      for (const inner of stmt.then) emitStmt(inner, fn, module, out, depth + 1);
      if (stmt.otherwise.length > 0) {
        out.push(`${pad}else`);
        for (const inner of stmt.otherwise) emitStmt(inner, fn, module, out, depth + 1);
      }
      out.push(`${pad}end`);
      return;

    case "while":
      // el patrón canónico: block (salida) + loop (repetición).
      out.push(`${pad}block   ;; $salida — destino de 'break'`);
      out.push(`${pad}  loop   ;; $cuerpo — destino de 'continue'`);
      emitExpr(stmt.condition, fn, module, out, depth + 2);
      out.push(`${pad}    i32.eqz`);
      out.push(`${pad}    br_if 1   ;; condición falsa -> $salida`);
      for (const inner of stmt.body) emitStmt(inner, fn, module, out, depth + 2);
      out.push(`${pad}    br 0   ;; otra vuelta`);
      out.push(`${pad}  end`);
      out.push(`${pad}end`);
      return;

    case "break":
      out.push(`${pad}br ${depthTo(out, "exit")}   ;; break`);
      return;

    case "continue":
      out.push(`${pad}br ${depthTo(out, "body")}   ;; continue`);
      return;

    default:
      out.push(`${pad};; (sin representación WAT: ${(stmt satisfies never as { kind: string }).kind})`);
      return;
  }
}

/**
 * El WAT es una VISTA: las profundidades exactas de `break`/`continue` las
 * calcula el emisor binario, que es el que manda. Aquí se anota la etiqueta
 * de destino por nombre, que es lo que un humano quiere leer.
 */
function depthTo(_out: readonly string[], target: "exit" | "body"): string {
  return target === "exit" ? "$salida" : "$cuerpo";
}

function emitExpr(
  expr: WirExpr, fn: WirFunc, module: WirModule, out: string[], depth: number,
): void {
  const pad = "  ".repeat(depth);
  switch (expr.kind) {
    case "const":
      out.push(`${pad}${typeName(expr.type)}.const ${expr.value}`);
      return;
    case "local.get":
      out.push(`${pad}local.get ${localRef(expr.index, fn)}`);
      return;
    case "binary":
      emitExpr(expr.left, fn, module, out, depth);
      emitExpr(expr.right, fn, module, out, depth);
      out.push(`${pad}${typeName(expr.operandType)}.${watOp(expr.op, expr.operandType)}`);
      return;
    case "unary":
      if (expr.op === WirUnOp.NOT) {
        emitExpr(expr.operand, fn, module, out, depth);
        out.push(`${pad}i32.eqz`);
        return;
      }
      if (expr.operand.type === WirType.F64) {
        emitExpr(expr.operand, fn, module, out, depth);
        out.push(`${pad}f64.neg`);
        return;
      }
      out.push(`${pad}${typeName(expr.operand.type)}.const 0`);
      emitExpr(expr.operand, fn, module, out, depth);
      out.push(`${pad}${typeName(expr.operand.type)}.sub`);
      return;
    case "call": {
      for (const arg of expr.args) emitExpr(arg, fn, module, out, depth);
      const target = module.funcs[expr.func];
      out.push(`${pad}call $${target?.name ?? expr.func}`);
      return;
    }
    case "call.host": {
      for (const arg of expr.args) emitExpr(arg, fn, module, out, depth);
      const imported = module.imports[expr.host];
      out.push(`${pad}call $${imported?.name ?? expr.host}`);
      return;
    }

    case "logical":
      // el cortocircuito en una máquina de pila es una rama, no un operador.
      emitExpr(expr.left, fn, module, out, depth);
      out.push(`${pad}if (result i32)   ;; '${expr.op}' cortocircuita`);
      if (expr.op === "and") {
        emitExpr(expr.right, fn, module, out, depth + 1);
        out.push(`${pad}else`);
        out.push(`${pad}  i32.const 0`);
      } else {
        out.push(`${pad}  i32.const 1`);
        out.push(`${pad}else`);
        emitExpr(expr.right, fn, module, out, depth + 1);
      }
      out.push(`${pad}end`);
      return;

    case "global.get":
      out.push(`${pad}global.get $${module.globals[expr.index]?.name ?? expr.index}`);
      return;

    case "convert": {
      emitExpr(expr.value, fn, module, out, depth);
      out.push(`${pad}${CONVERSION[`${expr.from}->${expr.type}`] ?? ";; conversión desconocida"}`);
      return;
    }

    default:
      out.push(`${pad};; (sin representación WAT: ${(expr satisfies never as { kind: string }).kind})`);
      return;
  }
}

/** Sufijo de la instrucción en texto (`add`, `div_s`, `lt_s`…). */
function watOp(op: WirBinOp, type: WirType): string {
  const signed = type === WirType.I32 || type === WirType.I64;
  switch (op) {
    case WirBinOp.ADD: return "add";
    case WirBinOp.SUB: return "sub";
    case WirBinOp.MUL: return "mul";
    case WirBinOp.DIV: return signed ? "div_s" : "div";
    case WirBinOp.REM: return signed ? "rem_s" : "rem";
    case WirBinOp.EQ: return "eq";
    case WirBinOp.NE: return "ne";
    case WirBinOp.LT: return signed ? "lt_s" : "lt";
    case WirBinOp.LE: return signed ? "le_s" : "le";
    case WirBinOp.GT: return signed ? "gt_s" : "gt";
    case WirBinOp.GE: return signed ? "ge_s" : "ge";
    case WirBinOp.AND: return "and";
    case WirBinOp.OR: return "or";
  }
}
