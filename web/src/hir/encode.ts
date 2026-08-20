/**
 * Re-serializador del HIR: {@link Module} -> bytes `.phir`.
 *
 * Espejo exacto de `decode.ts`, campo por campo. Cierra el ciclo del puente:
 * hasta ahora el HIR solo se podía LEER en el web, así que cualquier
 * transformación (el DCE, y mañana el lowering) moría en memoria.
 *
 * Para qué sirve, en concreto:
 *  - **cachear** en `.web/` el HIR ya validado y optimizado, para no repetir
 *    trabajo entre recargas del playground;
 *  - **verificar** el propio lector: `decode(encode(m))` tiene que ser `m`, y
 *    el `protobuf` de Python tiene que aceptar lo que este escritor produce
 *    (lo comprueba `test/unit/test_web_backend.py`);
 *  - dejar la puerta abierta a que el web devuelva HIR a otra herramienta
 *    (un `.phir` recortado para un ejemplo, por ejemplo).
 *
 * Sobre la igualdad byte a byte con el emisor Python: se consigue en todo lo
 * que este escritor controla (orden ascendente de campos, omisión de
 * defectos, `oneof` siempre presentes). Lo único que puede diferir es el
 * orden de las entradas de un `map`, que protobuf no fija en NINGUNA
 * implementación; por eso las pruebas comparan el módulo decodificado —o el
 * texto canónico de protobuf— y no los bytes crudos.
 */

import { Writer } from "./write.ts";
import {
  TypeKind,
  type Block,
  type Decl,
  type EnumDecl,
  type Expr,
  type FunctionDecl,
  type HookEntry,
  type HookRef,
  type IfStmt,
  type Literal,
  type Module,
  type Stmt,
  type StructDecl,
  type SymbolInfo,
  type SymbolTable,
  type TestDecl,
  type Type,
  typeKey,
} from "./schema.ts";

/**
 * Pool de tipos que se está construyendo (esquema v2).
 *
 * Los ids se asignan SOBRE LA MARCHA mientras se escriben los nodos, y el
 * pool se vuelca al final: funciona porque `Module.types` es el campo 6 y los
 * `items` el 4, así que escribirlo después mantiene el orden ascendente de
 * campos que este escritor garantiza.
 */
let POOL: { readonly ids: Map<string, number>; readonly types: Type[] } | null = null;

/** Tipo -> su índice en el pool, creándolo si es nuevo. `null` -> 0. */
function typeId(type: Type | null): number {
  if (type === null || POOL === null) return 0;
  const key = typeKey(type);
  const found = POOL.ids.get(key);
  if (found !== undefined) return found;
  const id = POOL.types.length + 1; // 0 queda para el tipo vacío
  POOL.ids.set(key, id);
  POOL.types.push(type);
  return id;
}

/** `Module` -> bytes de un `.phir`. */
export function encodeModule(module: Module): Uint8Array {
  const anterior = POOL;
  POOL = { ids: new Map(), types: [] };
  try {
    return encodeModuleBody(module);
  } finally {
    POOL = anterior;
  }
}

function encodeModuleBody(module: Module): Uint8Array {
  const w = new Writer(4096);
  w.uint32(1, module.schemaVersion);
  w.string(2, module.sourceFile);
  if (hasSymbols(module.symbols)) {
    w.message(3, (t) => encodeSymbolTable(module.symbols, t));
  }
  for (const decl of module.items) w.message(4, (d) => encodeDecl(decl, d));
  for (const lib of module.libraries) {
    w.message(5, (l) => {
      l.string(1, lib.alias);
      l.string(2, lib.phir);
    });
  }

  // POOL (campo 6), al final: para entonces 'typeId' ya lo ha llenado con
  // todo lo que los nodos referenciaron. La entrada 0 es el tipo VACIO, que
  // es lo que significa 'type_id = 0'.
  w.message(6, () => {});
  for (const type of POOL?.types ?? []) w.message(6, (t) => encodeType(type, t));
  return w.finish();
}

function hasSymbols(table: SymbolTable): boolean {
  return (
    table.types.size > 0 || table.values.size > 0 ||
    table.hooks.length > 0 || table.casts.length > 0
  );
}

// --------------------------------------------------------------------------- //
// tipos y símbolos
// --------------------------------------------------------------------------- //

function encodeType(type: Type, w: Writer): void {
  w.enum(1, type.kind);
  w.string(2, type.name);
  if (type.inner !== null) w.message(3, (t) => encodeType(type.inner!, t));
  w.bool(4, type.mut);
}

function encodeSymbol(sym: SymbolInfo, w: Writer): void {
  w.string(1, sym.name);
  w.enum(2, sym.kind);
  w.uint32(3, sym.ln);
  w.uint32(4, sym.col);
  if (sym.type !== null) w.message(5, (t) => encodeType(sym.type!, t));
  w.bool(6, sym.mutable);
  w.uint32(8, sym.movedAt);
  for (const t of sym.paramTypes) w.message(9, (out) => encodeType(t, out));
  for (const [name, member] of sym.members) {
    w.message(10, (entry) => {
      entry.rawString(1, name);
      entry.message(2, (value) => encodeSymbol(member, value));
    });
  }
  w.enum(11, sym.hookKind);
  w.string(12, sym.hookOwner);
}

function encodeSymbolTable(table: SymbolTable, w: Writer): void {
  for (const [name, sym] of table.types) {
    w.message(1, (entry) => {
      entry.rawString(1, name);
      entry.message(2, (value) => encodeSymbol(sym, value));
    });
  }
  for (const [name, sym] of table.values) {
    w.message(2, (entry) => {
      entry.rawString(1, name);
      entry.message(2, (value) => encodeSymbol(sym, value));
    });
  }
  for (const hook of table.hooks) w.message(3, (h) => encodeHookEntry(hook, h));
  for (const cast of table.casts) w.message(4, (c) => encodeSymbol(cast, c));
}

function encodeHookEntry(entry: HookEntry, w: Writer): void {
  w.string(1, entry.ownerType);
  w.enum(2, entry.kind);
  if (entry.symbol !== null) w.message(3, (s) => encodeSymbol(entry.symbol!, s));
}

function encodeHookRef(hook: HookRef, w: Writer): void {
  w.string(1, hook.ownerType);
  w.enum(2, hook.kind);
}

// --------------------------------------------------------------------------- //
// expresiones
// --------------------------------------------------------------------------- //

function encodeLiteral(literal: Literal, w: Writer): void {
  // el VALOR va en un oneof: se escribe siempre, aunque sea 0/""/false.
  switch (literal.kind) {
    case "int":
      w.string(1, "int");
      w.int64Always(2, literal.value);
      return;
    case "float":
      w.string(1, "float");
      w.doubleAlways(3, literal.value);
      return;
    case "str":
      w.string(1, "str");
      w.rawString(4, literal.value);
      return;
    case "char":
      w.string(1, "char");
      w.rawString(4, literal.value);
      return;
    case "bool":
      w.string(1, "bool");
      w.boolAlways(5, literal.value);
      return;
    case "null":
      w.string(1, "null");
      return;
    case "unknown":
      w.string(1, literal.raw);
      return;
  }
}

function encodeExpr(expr: Expr, w: Writer): void {
  w.uint32(1, expr.ln);
  w.uint32(2, expr.col);
  if (expr.restype !== null) w.uint32(4, typeId(expr.restype));

  const node = expr.node;
  switch (node.case) {
    case "literal":
      w.message(10, (l) => encodeLiteral(node.literal, l));
      return;
    case "interp":
      w.message(11, (i) => {
        for (const part of node.parts) {
          i.message(1, (p) => {
            if (part.case === "text") p.rawString(1, part.text);
            else p.message(2, (e) => encodeExpr(part.expr, e));
          });
        }
      });
      return;
    case "identifier":
      w.message(12, (id) => id.rawString(1, node.name));
      return;
    case "unary":
      w.message(13, (u) => {
        u.rawString(1, node.op);
        u.message(2, (e) => encodeExpr(node.operand, e));
      });
      return;
    case "binary":
      w.message(14, (b) => {
        b.rawString(1, node.op);
        b.message(2, (e) => encodeExpr(node.left, e));
        b.message(3, (e) => encodeExpr(node.right, e));
      });
      return;
    case "assignment":
      w.message(15, (a) => {
        a.message(1, (e) => encodeExpr(node.target, e));
        a.message(2, (e) => encodeExpr(node.value, e));
      });
      return;
    case "call":
      w.message(17, (c) => {
        c.message(1, (e) => encodeExpr(node.callee, e));
        for (const arg of node.args) c.message(2, (e) => encodeExpr(arg, e));
        if (node.hook !== null) c.message(3, (h) => encodeHookRef(node.hook!, h));
      });
      return;
    case "index":
      w.message(18, (i) => {
        i.message(1, (e) => encodeExpr(node.obj, e));
        i.message(2, (e) => encodeExpr(node.index, e));
      });
      return;
    case "member":
      w.message(19, (m) => {
        m.message(1, (e) => encodeExpr(node.obj, e));
        m.rawString(2, node.member);
      });
      return;
    case "sizeof":
      w.message(22, (s) => {
        if (node.type !== null) s.message(1, (t) => encodeType(node.type!, t));
        if (node.hook !== null) s.message(2, (h) => encodeHookRef(node.hook!, h));
      });
      return;
    case "addrOf":
      w.message(23, (a) => {
        a.message(1, (e) => encodeExpr(node.operand, e));
        a.bool(2, node.mut);
      });
      return;
    case "cast":
      w.message(24, (c) => {
        if (node.type !== null) c.message(1, (t) => encodeType(node.type!, t));
        c.message(2, (e) => encodeExpr(node.value, e));
        if (node.hook !== null) c.message(3, (h) => encodeHookRef(node.hook!, h));
      });
      return;
    case "structLiteral":
      w.message(25, (s) => {
        s.string(1, node.typeName);
        for (const name of node.fieldNames) s.rawString(2, name);
        for (const value of node.values) s.message(3, (e) => encodeExpr(value, e));
      });
      return;
    case "none":
      // sin variante: se escriben solo posición y restype (lo que había).
      return;
  }
}

// --------------------------------------------------------------------------- //
// sentencias
// --------------------------------------------------------------------------- //

function encodeBlock(block: Block, w: Writer): void {
  for (const stmt of block.statements) w.message(1, (s) => encodeStmt(stmt, s));
}

function encodeIfStmt(node: IfStmt, w: Writer): void {
  w.message(1, (e) => encodeExpr(node.condition, e));
  w.message(2, (b) => encodeBlock(node.thenBlock, b));
  switch (node.elseBranch.case) {
    case "block":
      w.message(3, (b) => encodeBlock((node.elseBranch as { block: Block }).block, b));
      return;
    case "if":
      w.message(4, (i) => encodeIfStmt((node.elseBranch as { ifStmt: IfStmt }).ifStmt, i));
      return;
    case "none":
      return;
  }
}

function encodeStmt(stmt: Stmt, w: Writer): void {
  w.uint32(1, stmt.ln);
  w.uint32(2, stmt.col);

  const node = stmt.node;
  switch (node.case) {
    case "block":
      w.message(10, (b) => encodeBlock(node.block, b));
      return;
    case "varDecl":
      w.message(11, (v) => {
        v.string(1, node.qualifier);
        if (node.type !== null) v.uint32(5, typeId(node.type));
        v.string(3, node.name);
        if (node.value !== null) v.message(4, (e) => encodeExpr(node.value!, e));
      });
      return;
    case "if":
      w.message(13, (i) => encodeIfStmt(node.ifStmt, i));
      return;
    case "while":
      w.message(14, (wh) => {
        wh.message(1, (e) => encodeExpr(node.condition, e));
        wh.message(2, (b) => encodeBlock(node.body, b));
      });
      return;
    case "match":
      w.message(15, (m) => {
        m.message(1, (e) => encodeExpr(node.subject, e));
        for (const arm of node.cases) {
          m.message(2, (c) => {
            c.message(1, (e) => encodeExpr(arm.pattern, e));
            c.message(2, (s) => encodeStmt(arm.body, s));
          });
        }
      });
      return;
    case "return":
      // 'return;' se escribe como submensaje VACÍO: marca la variante.
      w.message(16, (r) => {
        if (node.value !== null) r.message(1, (e) => encodeExpr(node.value!, e));
      });
      return;
    case "break":
      w.message(17, () => {});
      return;
    case "continue":
      w.message(18, () => {});
      return;
    case "move":
      w.message(19, (m) => m.message(1, (e) => encodeExpr(node.target, e)));
      return;
    case "free":
      w.message(20, (f) => {
        f.message(1, (e) => encodeExpr(node.target, e));
        if (node.hook !== null) f.message(2, (h) => encodeHookRef(node.hook!, h));
      });
      return;
    case "expr":
      w.message(21, (e) => e.message(1, (inner) => encodeExpr(node.expr, inner)));
      return;
    case "importBinding":
      w.message(22, (i) => {
        i.string(1, node.qualifier);
        i.string(2, node.name);
        i.string(3, node.lib);
        i.string(4, node.member);
      });
      return;
    case "typeDecl":
      w.message(23, (t) => {
        t.string(1, node.qualifier);
        t.string(2, node.name);
        if (node.value !== null) t.message(3, (e) => encodeExpr(node.value!, e));
      });
      return;
    case "throw":
      w.message(24, (t) => t.message(1, (e) => encodeExpr(node.value, e)));
      return;
    case "try":
      w.message(25, (t) => {
        t.message(1, (b) => encodeBlock(node.tryBlock, b));
        // los tags 2 y 3 quedaron 'reserved' al pasar de un catch unico a N
        // ramas filtradas: las ramas van todas en el 4.
        for (const rama of node.catches) {
          t.message(4, (c) => {
            c.string(1, rama.name);
            c.message(2, (b) => encodeBlock(rama.block, b));
            if (rama.type !== null) c.message(3, (ty) => encodeType(rama.type!, ty));
          });
        }
      });
      return;
    case "none":
      return;
  }
}

// --------------------------------------------------------------------------- //
// declaraciones
// --------------------------------------------------------------------------- //

function encodeFunction(fn: FunctionDecl, w: Writer): void {
  w.string(1, fn.name);
  for (const param of fn.params) {
    w.message(2, (p) => {
      if (param.type !== null) p.uint32(3, typeId(param.type));
      p.string(2, param.name);
    });
  }
  if (fn.returnType !== null) w.uint32(7, typeId(fn.returnType));
  if (fn.body !== null) w.message(4, (b) => encodeBlock(fn.body!, b));
  w.string(5, fn.dunder);
  w.string(6, fn.decorator);
}

function encodeStruct(struct: StructDecl, w: Writer): void {
  w.string(1, struct.name);
  for (const field of struct.fields) {
    w.message(2, (f) => {
      if (field.type !== null) f.uint32(3, typeId(field.type));
      f.string(2, field.name);
    });
  }
}

function encodeEnum(decl: EnumDecl, w: Writer): void {
  w.string(1, decl.name);
  for (const item of decl.items) {
    w.message(2, (i) => {
      i.string(1, item.name);
      if (item.value !== null) i.message(2, (e) => encodeExpr(item.value!, e));
    });
  }
}

function encodeTest(test: TestDecl, w: Writer): void {
  w.string(1, test.name);
  if (test.body !== null) w.message(2, (b) => encodeBlock(test.body!, b));
}

function encodeDecl(decl: Decl, w: Writer): void {
  w.uint32(1, decl.ln);
  w.uint32(2, decl.col);

  const node = decl.node;
  switch (node.case) {
    case "function":
      w.message(10, (f) => encodeFunction(node.fn, f));
      return;
    case "struct":
      w.message(11, (s) => encodeStruct(node.struct, s));
      return;
    case "enum":
      w.message(12, (e) => encodeEnum(node.enumDecl, e));
      return;
    case "externBlock":
      w.message(13, (e) => {
        e.string(1, node.externBlock.target);
        e.string(2, node.externBlock.raw);
      });
      return;
    case "statement":
      w.message(14, (s) => encodeStmt(node.stmt, s));
      return;
    case "import":
      w.message(15, (i) => {
        i.string(1, node.directive.lib);
        i.string(2, node.directive.alias);
        i.string(3, node.directive.unit);
        i.string(4, node.directive.binding);
      });
      return;
    case "export":
      w.message(16, (e) => {
        e.string(1, node.directive.alias);
        e.bool(2, node.directive.package);
      });
      return;
    case "from":
      w.message(17, (f) => {
        f.string(1, node.directive.lib);
        f.string(2, node.directive.name);
        f.string(3, node.directive.alias);
        f.string(4, node.directive.unit);
      });
      return;
    case "test":
      w.message(18, (t) => encodeTest(node.test, t));
      return;
    case "none":
      return;
  }
}

/** Tipo puntero -> `true`. Utilidad para quien inspeccione lo que reescribe. */
export function isPointer(type: Type | null): boolean {
  return type !== null && type.kind === TypeKind.POINTER;
}
