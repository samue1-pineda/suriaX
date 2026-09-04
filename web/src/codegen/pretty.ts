/**
 * Vista LEGIBLE del WIR: qué va a ejecutar el WebAssembly, escrito para leer.
 *
 * El `.wat` es el artefacto de DEPURACIÓN: dice qué instrucción va después de
 * cuál, que es lo que uno mira cuando sospecha del emisor. Pero para saber
 * *qué hace el programa* obliga a reconstruir mentalmente cada expresión a
 * partir de su post-orden — tres líneas de pila para leer `total = 40 + 2`.
 *
 * Esta vista responde la otra pregunta. Sale del MISMO WIR, así que no es una
 * aproximación: es el mismo árbol que el emisor recorre, impreso con las
 * expresiones en línea. Es el equivalente, para esta IR, de lo que
 * `V0/src/HIR/pretty.py` es para el HIR — y por el mismo motivo: un volcado
 * que sirve para depurar el formato rara vez sirve para leer el programa.
 *
 * Las dos vistas se mantienen juntas a propósito: si el WIR gana una forma
 * nueva, este archivo deja de compilar (el `switch` no tiene `default`) y hay
 * que decidir cómo se lee, en vez de que aparezca en el `.wat` y aquí no.
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

/** Operadores tal como se escriben en suriaX, no como los nombra el WIR. */
const OPERADOR: ReadonlyMap<WirBinOp, string> = new Map([
  [WirBinOp.ADD, "+"], [WirBinOp.SUB, "-"], [WirBinOp.MUL, "*"],
  [WirBinOp.DIV, "/"], [WirBinOp.REM, "%"],
  [WirBinOp.EQ, "=="], [WirBinOp.NE, "!="],
  [WirBinOp.LT, "<"], [WirBinOp.LE, "<="],
  [WirBinOp.GT, ">"], [WirBinOp.GE, ">="],
]);

/** Columna donde se alinean las posiciones, igual que en la vista del HIR. */
const COLUMNA_POS = 62;

function nombreLocal(fn: WirFunc, indice: number): string {
  const local = indice < fn.params.length
    ? fn.params[indice]
    : fn.locals[indice - fn.params.length];
  return local?.name ?? `local${indice}`;
}

function literal(valor: bigint | number, tipo: WirType): string {
  if (tipo === WirType.F64) {
    // se ve que es un float aunque sea entero: '1' y '1.0' son cosas distintas
    return Number.isInteger(valor) ? `${valor}.0` : String(valor);
  }
  return String(valor);
}

function expresion(expr: WirExpr, fn: WirFunc, module: WirModule): string {
  switch (expr.kind) {
    case "const":
      return literal(expr.value, expr.type);
    case "local.get":
      return nombreLocal(fn, expr.index);
    case "binary":
      return `(${expresion(expr.left, fn, module)} ` +
             `${OPERADOR.get(expr.op) ?? expr.op} ` +
             `${expresion(expr.right, fn, module)})`;
    case "unary":
      return expr.op === WirUnOp.NOT
        ? `(not ${expresion(expr.operand, fn, module)})`
        : `(- ${expresion(expr.operand, fn, module)})`;
    case "call": {
      const destino = module.funcs[expr.func]?.name ?? `func${expr.func}`;
      const args = expr.args.map((a) => expresion(a, fn, module)).join(", ");
      return `${destino}(${args})`;
    }
    case "call.host": {
      const primitiva = module.imports[expr.host]?.name ?? `host${expr.host}`;
      // '__write__(offset, len)' se resuelve al TEXTO que escribe: el offset
      // no le dice nada a quien lee el programa.
      if (primitiva === "__write__") {
        return `escribe(${JSON.stringify(textoDe(expr, module))})`;
      }
      // '__write_str__(i)' escribe la constante número i: si el índice es
      // conocido al compilar (lo es siempre que se imprime un literal) se
      // enseña la cadena, que es lo que el programa dice.
      if (primitiva === "__write_str__") {
        const indice = expr.args[0];
        const texto = indice?.kind === "const"
          ? module.strings[Number(indice.value)]?.text
          : undefined;
        return texto === undefined
          ? `escribe(cadena #${expresion(expr.args[0]!, fn, module)})`
          : `escribe(${JSON.stringify(texto)})`;
      }
      const args = expr.args.map((a) => expresion(a, fn, module)).join(", ");
      return `${primitiva.replace(/^__|__$/g, "")}(${args})`;
    }
    case "seq":
      return expr.exprs.map((e) => expresion(e, fn, module)).join("; ");
    case "logical":
      return `(${expresion(expr.left, fn, module)} ${expr.op} ` +
             `${expresion(expr.right, fn, module)})`;
    case "convert":
      // se lee como se escribió en suriaX: 'cast<int>(x)'
      return `cast<${typeName(expr.type)}>(` +
             `${expresion(expr.value, fn, module)})`;
    case "global.get":
      return module.globals[expr.index]?.name ?? `global${expr.index}`;
  }
}

/** El texto de un `__write__(offset, len)`, buscándolo en el data segment. */
function textoDe(expr: Extract<WirExpr, { kind: "call.host" }>,
                 module: WirModule): string {
  const [offset, largo] = expr.args;
  if (offset?.kind !== "const" || largo?.kind !== "const") return "";
  for (const cadena of module.strings) {
    if (cadena.offset === Number(offset.value) &&
        cadena.bytes.length === Number(largo.value)) {
      return cadena.text;
    }
  }
  return "";
}

function sentencia(stmt: WirStmt, fn: WirFunc, module: WirModule,
                   sangria: number, salida: string[]): void {
  const escribir = (texto: string, pos?: { ln: number; col: number }) => {
    const cuerpo = "  ".repeat(sangria) + texto;
    if (pos === undefined || pos.ln === 0) { salida.push(cuerpo); return; }
    const relleno = Math.max(1, COLUMNA_POS - cuerpo.length);
    salida.push(`${cuerpo}${" ".repeat(relleno)}@${pos.ln}:${pos.col}`);
  };

  switch (stmt.kind) {
    case "local.set":
      escribir(`${nombreLocal(fn, stmt.index)} = ` +
               expresion(stmt.value, fn, module), stmt.pos);
      return;
    case "global.set":
      escribir(`${module.globals[stmt.index]?.name ?? stmt.index} = ` +
               expresion(stmt.value, fn, module), stmt.pos);
      return;
    case "drop":
      // el valor se calcula y se tira: en la pila hay que sacarlo
      escribir(expresion(stmt.value, fn, module), stmt.pos);
      return;
    case "return":
      escribir("return" + (stmt.value === null
        ? "" : " " + expresion(stmt.value, fn, module)), stmt.pos);
      return;
    case "if":
      escribir(`if ${expresion(stmt.condition, fn, module)}`, stmt.pos);
      for (const s of stmt.then) sentencia(s, fn, module, sangria + 1, salida);
      if (stmt.otherwise.length > 0) {
        escribir("else");
        for (const s of stmt.otherwise) sentencia(s, fn, module, sangria + 1, salida);
      }
      return;
    case "while":
      escribir(`while ${expresion(stmt.condition, fn, module)}`, stmt.pos);
      for (const s of stmt.body) sentencia(s, fn, module, sangria + 1, salida);
      return;
    case "break":
      escribir("break", stmt.pos);
      return;
    case "continue":
      escribir("continue", stmt.pos);
      return;
  }
}

/** El WIR completo, para leerlo. */
export function emitPretty(module: WirModule): string {
  const salida: string[] = [];
  salida.push(
    `unidad ${module.source || "<memoria>"}   ` +
    `${module.funcs.length} funciones · ${module.strings.length} cadenas ` +
    `(${module.dataSize} bytes)`);
  salida.push("");

  if (module.imports.length > 0) {
    salida.push("host   (lo aporta quien ejecuta el módulo)");
    for (const imp of module.imports) {
      const params = imp.params.map(typeName).join(", ");
      salida.push(`  ${imp.name}(${params}) -> ${typeName(imp.result)}`);
    }
    salida.push("");
  }

  if (module.globals.length > 0) {
    salida.push("globales   (viven mientras vive el módulo)");
    for (const g of module.globals) {
      salida.push(`  ${g.mutable ? "var  " : "const"} ` +
                  `${typeName(g.type)} ${g.name} = ${g.init}`);
    }
    salida.push("");
  }

  if (module.strings.length > 0) {
    salida.push("texto   (memoria lineal)");
    for (const cadena of module.strings) {
      salida.push(`  @${String(cadena.offset).padEnd(5)} ` +
                  JSON.stringify(cadena.text));
    }
    salida.push("");
  }

  module.funcs.forEach((fn, i) => {
    const params = fn.params
      .map((p) => `${typeName(p.type)} ${p.name}`).join(", ");
    const marcas = [
      i === module.entry ? "entrada" : "",
      i === module.init ? "inicialización del módulo" : "",
    ].filter(Boolean).join(", ");
    salida.push(`fn ${fn.name}(${params}) -> ${typeName(fn.result)}` +
                (marcas ? `   (${marcas})` : ""));
    for (const local of fn.locals) {
      salida.push(`  var ${typeName(local.type)} ${local.name}`);
    }
    for (const stmt of fn.body) sentencia(stmt, fn, module, 1, salida);
    salida.push("");
  });

  return salida.join("\n");
}
