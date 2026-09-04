/**
 * Deserializador del HIR: bytes de un `.phir` -> {@link Module}.
 *
 * Es la contraparte exacta de `V0/src/HIR/emmit_IR.py` y el equivalente web
 * de `runtime/interpreter/loader.py`. Mismo contrato que el loader del
 * intérprete:
 *
 *  1. parsear los bytes como `Module`;
 *  2. **fail-fast de esquema**: una `schema_version` que este lector no
 *     conoce se rechaza ANTES de mirar el contenido — nunca interpretar
 *     bytes con un layout desconocido;
 *  3. dejar el árbol listo para indexar (`link.ts`), sin ejecutar nada.
 *
 * Estructura: **un decoder explícito por message**, con `switch` sobre el
 * *tag* completo (`(campo << 3) | wire`). Es la misma decisión que tomó el
 * emisor Python al descartar la reflexión: el mapeo tiene casos especiales
 * (`oneof`, `map`, presencia) que un decoder genérico complica más de lo
 * que ahorra, y aquí además el `switch` compila a una tabla de saltos.
 *
 * Ningún campo del esquema es "packed": todos los `repeated` del HIR son de
 * `message` o de `string`, que nunca se empaquetan. Por eso basta con
 * despachar el tag completo; cualquier tag que no esté en la tabla se salta
 * (compatibilidad hacia adelante dentro de una misma `schema_version`).
 */

import { Reader, WireError } from "./wire.ts";
import {
  EMPTY_BLOCK,
  EMPTY_SYMBOL_TABLE,
  HookKind,
  SymbolKind,
  TypeKind,
  type Block,
  type CaseArm,
  type CatchClause,
  type Decl,
  type DeclNode,
  type ElseBranch,
  type EnumDecl,
  type EnumItem,
  type Expr,
  type ExprNode,
  type ExternBlock,
  type Field,
  type FromDirective,
  type FunctionDecl,
  type HookEntry,
  type HookRef,
  type IfStmt,
  type ImportDirective,
  type ExportDirective,
  type InterpPart,
  type LibraryRef,
  type Literal,
  type Module,
  type Parameter,
  type Stmt,
  type StmtNode,
  type StructDecl,
  type SymbolInfo,
  type SymbolTable,
  type TestDecl,
  type Type,
} from "./schema.ts";

/**
 * Versiones de esquema que este lector sabe interpretar. Misma lista y
 * misma política que `runtime/interpreter/loader.SUPPORTED_SCHEMA_VERSIONS`:
 * un HIR de una versión futura se RECHAZA en vez de malinterpretarse.
 */
export const SUPPORTED_SCHEMA_VERSIONS: ReadonlySet<number> = new Set([2]);

/** El `.phir` no pudo cargarse: bytes corruptos o esquema no soportado. */
export class HIRLoadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "HIRLoadError";
  }
}

// --------------------------------------------------------------------------- //
// placeholders de campos requeridos ausentes
// --------------------------------------------------------------------------- //

/**
 * Un submensaje obligatorio que no llegó (HIR malformado) NO se adivina: se
 * sustituye por un nodo `none` que el módulo de restricciones reporta como
 * `WEB901`. Así el resto del árbol se sigue leyendo y el usuario recibe
 * TODOS los problemas de una vez, en lugar de un `null` que revienta tres
 * fases más adelante.
 */
const MISSING_EXPR: Expr = { ln: 0, col: 0, restype: null, node: { case: "none" } };
const MISSING_STMT: Stmt = { ln: 0, col: 0, node: { case: "none" } };

function emptySymbol(name: string): SymbolInfo {
  return {
    name,
    kind: SymbolKind.SYMBOL_UNSPECIFIED,
    ln: 0,
    col: 0,
    type: null,
    mutable: false,
    movedAt: 0,
    paramTypes: [],
    members: new Map(),
    hookKind: HookKind.HOOK_UNSPECIFIED,
    hookOwner: "",
  };
}

// --------------------------------------------------------------------------- //
// tipos y símbolos
// --------------------------------------------------------------------------- //

function decodeType(r: Reader): Type {
  let kind: TypeKind = TypeKind.TYPE_UNSPECIFIED;
  let name = "";
  let inner: Type | null = null;
  let mut = false;
  const args: Type[] = [];
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 8: kind = r.readEnum() as TypeKind; break;
      case 18: name = r.readString(); break;
      case 26: inner = r.readMessage(decodeType); break;
      case 32: mut = r.readBool(); break;
      case 42: args.push(r.readMessage(decodeType)); break;
      default: r.skip(tag);
    }
  }
  return { kind, name, inner, mut, args };
}

function decodeSymbol(r: Reader): SymbolInfo {
  let name = "";
  let kind: SymbolKind = SymbolKind.SYMBOL_UNSPECIFIED;
  let ln = 0;
  let col = 0;
  let type: Type | null = null;
  let mutable = false;
  let movedAt = 0;
  let paramTypes: Type[] | null = null;
  let members: Map<string, SymbolInfo> | null = null;
  let hookKind: HookKind = HookKind.HOOK_UNSPECIFIED;
  let hookOwner = "";
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: name = r.readString(); break;
      case 16: kind = r.readEnum() as SymbolKind; break;
      case 24: ln = r.readUint32(); break;
      case 32: col = r.readUint32(); break;
      case 42: type = r.readMessage(decodeType); break;
      case 48: mutable = r.readBool(); break;
      case 64: movedAt = r.readUint32(); break;
      case 74: (paramTypes ??= []).push(r.readMessage(decodeType)); break;
      case 82: r.readMessage((sub) => decodeSymbolMapEntry(sub, (members ??= new Map()))); break;
      case 88: hookKind = r.readEnum() as HookKind; break;
      case 98: hookOwner = r.readString(); break;
      default: r.skip(tag);
    }
  }
  return {
    name, kind, ln, col, type, mutable, movedAt,
    paramTypes: paramTypes ?? [],
    members: members ?? new Map(),
    hookKind, hookOwner,
  };
}

/** Entrada de `map<string, Symbol>`: un message con `key = 1`, `value = 2`. */
function decodeSymbolMapEntry(r: Reader, into: Map<string, SymbolInfo>): void {
  let key = "";
  let value: SymbolInfo | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: key = r.readString(); break;
      case 18: value = r.readMessage(decodeSymbol); break;
      default: r.skip(tag);
    }
  }
  into.set(key, value ?? emptySymbol(key));
}

function decodeHookEntry(r: Reader): HookEntry {
  let ownerType = "";
  let kind: HookKind = HookKind.HOOK_UNSPECIFIED;
  let symbol: SymbolInfo | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: ownerType = r.readString(); break;
      case 16: kind = r.readEnum() as HookKind; break;
      case 26: symbol = r.readMessage(decodeSymbol); break;
      default: r.skip(tag);
    }
  }
  return { ownerType, kind, symbol };
}

function decodeSymbolTable(r: Reader): SymbolTable {
  const types = new Map<string, SymbolInfo>();
  const values = new Map<string, SymbolInfo>();
  const hooks: HookEntry[] = [];
  const casts: SymbolInfo[] = [];
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: r.readMessage((sub) => decodeSymbolMapEntry(sub, types)); break;
      case 18: r.readMessage((sub) => decodeSymbolMapEntry(sub, values)); break;
      case 26: hooks.push(r.readMessage(decodeHookEntry)); break;
      case 34: casts.push(r.readMessage(decodeSymbol)); break;
      default: r.skip(tag);
    }
  }
  return { types, values, hooks, casts };
}

function decodeHookRef(r: Reader): HookRef {
  let ownerType = "";
  let kind: HookKind = HookKind.HOOK_UNSPECIFIED;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: ownerType = r.readString(); break;
      case 16: kind = r.readEnum() as HookKind; break;
      default: r.skip(tag);
    }
  }
  return { ownerType, kind };
}

// --------------------------------------------------------------------------- //
// expresiones
// --------------------------------------------------------------------------- //

function decodeLiteral(r: Reader): Literal {
  let kind = "";
  let intValue = 0n;
  let floatValue = 0;
  let strValue = "";
  let boolValue = false;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: kind = r.readString(); break;
      case 16: intValue = r.readInt64(); break;
      case 25: floatValue = r.readDouble(); break;
      case 34: strValue = r.readString(); break;
      case 40: boolValue = r.readBool(); break;
      default: r.skip(tag);
    }
  }
  switch (kind) {
    case "int": return { kind: "int", value: intValue };
    case "float": return { kind: "float", value: floatValue };
    case "str": return { kind: "str", value: strValue };
    case "char": return { kind: "char", value: strValue };
    case "bool": return { kind: "bool", value: boolValue };
    case "null": return { kind: "null" };
    default: return { kind: "unknown", raw: kind };
  }
}

function decodeInterpPart(r: Reader): InterpPart {
  let part: InterpPart = { case: "text", text: "" };
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: part = { case: "text", text: r.readString() }; break;
      case 18: part = { case: "expr", expr: r.readMessage(decodeExpr) }; break;
      default: r.skip(tag);
    }
  }
  return part;
}

/**
 * Pool de tipos del módulo que se está decodificando (esquema v2).
 *
 * Vive en el módulo, y no como parámetro de las ~40 funciones de decodificado,
 * a propósito: el pool es una propiedad del `Module` que se está leyendo, no
 * de cada nodo, y pasarlo a mano habría tocado toda la superficie del lector
 * para no cambiar ni una de sus formas de salida. `decodeModule` lo instala y
 * lo restaura, así que anidar decodificados es seguro.
 *
 * Lo importante: el pool NO se filtra al resto del backend. `Expr.restype`
 * sigue siendo un `Type | null` ya resuelto, así que el DCE, el lowering y los
 * emisores no saben —ni tienen por qué saber— que el HIR los pliega.
 */
let TYPE_POOL: readonly (Type | null)[] = [];

/**
 * Primera pasada: recoge SOLO el pool (campo 6 del `Module`).
 *
 * Hace falta porque los `items` (campo 4) van antes que el pool en el wire, y
 * un nodo no se puede resolver sin él. Saltar el resto es barato: de un campo
 * delimitado solo se lee la longitud y se avanza.
 */
function scanTypePool(bytes: Uint8Array): (Type | null)[] {
  const pool: (Type | null)[] = [];
  const r = new Reader(bytes);
  while (!r.eof) {
    const tag = r.readUint32();
    if (tag === 50) pool.push(r.readMessage(decodeType));
    else r.skip(tag);
  }
  return pool;
}

/** Índice del pool -> tipo. 0 (o fuera de rango) = sin tipo anotado. */
function pooledType(id: number): Type | null {
  if (id <= 0 || id >= TYPE_POOL.length) return null;
  return TYPE_POOL[id];
}

function decodeExpr(r: Reader): Expr {
  let ln = 0;
  let col = 0;
  let restype: Type | null = null;
  let node: ExprNode = { case: "none" };
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 8: ln = r.readUint32(); break;
      case 16: col = r.readUint32(); break;
      case 32: restype = pooledType(r.readUint32()); break;

      case 82: node = { case: "literal", literal: r.readMessage(decodeLiteral) }; break;
      case 90: node = r.readMessage(decodeInterpolated); break;
      case 98: node = r.readMessage(decodeIdentifier); break;
      case 106: node = r.readMessage(decodeUnary); break;
      case 114: node = r.readMessage(decodeBinary); break;
      case 122: node = r.readMessage(decodeAssignment); break;
      case 138: node = r.readMessage(decodeCall); break;
      case 146: node = r.readMessage(decodeIndex); break;
      case 154: node = r.readMessage(decodeMember); break;
      case 178: node = r.readMessage(decodeSizeof); break;
      case 186: node = r.readMessage(decodeAddrOf); break;
      case 194: node = r.readMessage(decodeCast); break;
      case 202: node = r.readMessage(decodeStructLiteral); break;
      case 210: node = {
        case: "moveExpr",
        operand: r.readMessage((sub) => {
          let operand = MISSING_EXPR;
          while (!sub.eof) {
            const inner = sub.readUint32();
            if (inner === 10) operand = sub.readMessage(decodeExpr);
            else sub.skip(inner);
          }
          return operand;
        }),
      }; break;
      default: r.skip(tag);
    }
  }
  return { ln, col, restype, node };
}

function decodeInterpolated(r: Reader): ExprNode {
  const parts: InterpPart[] = [];
  while (!r.eof) {
    const tag = r.readUint32();
    if (tag === 10) parts.push(r.readMessage(decodeInterpPart));
    else r.skip(tag);
  }
  return { case: "interp", parts };
}

function decodeIdentifier(r: Reader): ExprNode {
  let name = "";
  while (!r.eof) {
    const tag = r.readUint32();
    if (tag === 10) name = r.readString();
    else r.skip(tag);
  }
  return { case: "identifier", name };
}

function decodeUnary(r: Reader): ExprNode {
  let op = "";
  let operand: Expr | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: op = r.readString(); break;
      case 18: operand = r.readMessage(decodeExpr); break;
      default: r.skip(tag);
    }
  }
  return { case: "unary", op, operand: operand ?? MISSING_EXPR };
}

function decodeBinary(r: Reader): ExprNode {
  let op = "";
  let left: Expr | null = null;
  let right: Expr | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: op = r.readString(); break;
      case 18: left = r.readMessage(decodeExpr); break;
      case 26: right = r.readMessage(decodeExpr); break;
      default: r.skip(tag);
    }
  }
  return { case: "binary", op, left: left ?? MISSING_EXPR, right: right ?? MISSING_EXPR };
}

function decodeAssignment(r: Reader): ExprNode {
  let target: Expr | null = null;
  let value: Expr | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: target = r.readMessage(decodeExpr); break;
      case 18: value = r.readMessage(decodeExpr); break;
      default: r.skip(tag);
    }
  }
  return {
    case: "assignment",
    target: target ?? MISSING_EXPR,
    value: value ?? MISSING_EXPR,
  };
}

function decodeCall(r: Reader): ExprNode {
  let callee: Expr | null = null;
  const args: Expr[] = [];
  let hook: HookRef | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: callee = r.readMessage(decodeExpr); break;
      case 18: args.push(r.readMessage(decodeExpr)); break;
      case 26: hook = r.readMessage(decodeHookRef); break;
      default: r.skip(tag);
    }
  }
  return { case: "call", callee: callee ?? MISSING_EXPR, args, hook };
}

function decodeIndex(r: Reader): ExprNode {
  let obj: Expr | null = null;
  let index: Expr | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: obj = r.readMessage(decodeExpr); break;
      case 18: index = r.readMessage(decodeExpr); break;
      default: r.skip(tag);
    }
  }
  return { case: "index", obj: obj ?? MISSING_EXPR, index: index ?? MISSING_EXPR };
}

function decodeMember(r: Reader): ExprNode {
  let obj: Expr | null = null;
  let member = "";
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: obj = r.readMessage(decodeExpr); break;
      case 18: member = r.readString(); break;
      default: r.skip(tag);
    }
  }
  return { case: "member", obj: obj ?? MISSING_EXPR, member };
}

function decodeSizeof(r: Reader): ExprNode {
  let type: Type | null = null;
  let hook: HookRef | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: type = r.readMessage(decodeType); break;
      case 18: hook = r.readMessage(decodeHookRef); break;
      default: r.skip(tag);
    }
  }
  return { case: "sizeof", type, hook };
}

function decodeAddrOf(r: Reader): ExprNode {
  let operand: Expr | null = null;
  let mut = false;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: operand = r.readMessage(decodeExpr); break;
      case 16: mut = r.readBool(); break;
      default: r.skip(tag);
    }
  }
  return { case: "addrOf", operand: operand ?? MISSING_EXPR, mut };
}

function decodeCast(r: Reader): ExprNode {
  let type: Type | null = null;
  let value: Expr | null = null;
  let hook: HookRef | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: type = r.readMessage(decodeType); break;
      case 18: value = r.readMessage(decodeExpr); break;
      case 26: hook = r.readMessage(decodeHookRef); break;
      default: r.skip(tag);
    }
  }
  return { case: "cast", type, value: value ?? MISSING_EXPR, hook };
}

function decodeStructLiteral(r: Reader): ExprNode {
  let typeName = "";
  const fieldNames: string[] = [];
  const values: Expr[] = [];
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: typeName = r.readString(); break;
      case 18: fieldNames.push(r.readString()); break;
      case 26: values.push(r.readMessage(decodeExpr)); break;
      default: r.skip(tag);
    }
  }
  return { case: "structLiteral", typeName, fieldNames, values };
}

// --------------------------------------------------------------------------- //
// sentencias
// --------------------------------------------------------------------------- //

function decodeBlock(r: Reader): Block {
  const statements: Stmt[] = [];
  while (!r.eof) {
    const tag = r.readUint32();
    if (tag === 10) statements.push(r.readMessage(decodeStmt));
    else r.skip(tag);
  }
  return { statements };
}

function decodeStmt(r: Reader): Stmt {
  let ln = 0;
  let col = 0;
  let node: StmtNode = { case: "none" };
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 8: ln = r.readUint32(); break;
      case 16: col = r.readUint32(); break;

      case 82: node = { case: "block", block: r.readMessage(decodeBlock) }; break;
      case 90: node = r.readMessage(decodeVarDecl); break;
      case 106: node = { case: "if", ifStmt: r.readMessage(decodeIfStmt) }; break;
      case 114: node = r.readMessage(decodeWhile); break;
      case 122: node = r.readMessage(decodeMatch); break;
      case 130: node = r.readMessage(decodeReturn); break;
      case 138: r.readMessage(skipMessage); node = { case: "break" }; break;
      case 146: r.readMessage(skipMessage); node = { case: "continue" }; break;
      case 154: node = r.readMessage(decodeMove); break;
      case 162: node = r.readMessage(decodeFree); break;
      case 170: node = r.readMessage(decodeExprStmt); break;
      case 178: node = r.readMessage(decodeImportBinding); break;
      case 186: node = r.readMessage(decodeTypeDecl); break;
      case 194: node = r.readMessage(decodeThrow); break;
      case 202: node = r.readMessage(decodeTry); break;
      default: r.skip(tag);
    }
  }
  return { ln, col, node };
}

/** Message sin campos (`BreakStmt`, `ContinueStmt`): se consume y ya. */
function skipMessage(r: Reader): void {
  while (!r.eof) r.skip(r.readUint32());
}

function decodeVarDecl(r: Reader): StmtNode {
  let qualifier = "";
  let type: Type | null = null;
  let name = "";
  let value: Expr | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: qualifier = r.readString(); break;
      case 26: name = r.readString(); break;
      case 34: value = r.readMessage(decodeExpr); break;
      case 40: type = pooledType(r.readUint32()); break;
      default: r.skip(tag);
    }
  }
  return { case: "varDecl", qualifier, type, name, value };
}

function decodeTypeDecl(r: Reader): StmtNode {
  let qualifier = "";
  let name = "";
  let value: Expr | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: qualifier = r.readString(); break;
      case 18: name = r.readString(); break;
      case 26: value = r.readMessage(decodeExpr); break;
      default: r.skip(tag);
    }
  }
  return { case: "typeDecl", qualifier, name, value };
}

function decodeIfStmt(r: Reader): IfStmt {
  let condition: Expr | null = null;
  let thenBlock: Block | null = null;
  let elseBranch: ElseBranch = { case: "none" };
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: condition = r.readMessage(decodeExpr); break;
      case 18: thenBlock = r.readMessage(decodeBlock); break;
      case 26: elseBranch = { case: "block", block: r.readMessage(decodeBlock) }; break;
      case 34: elseBranch = { case: "if", ifStmt: r.readMessage(decodeIfStmt) }; break;
      default: r.skip(tag);
    }
  }
  return {
    condition: condition ?? MISSING_EXPR,
    thenBlock: thenBlock ?? EMPTY_BLOCK,
    elseBranch,
  };
}

function decodeWhile(r: Reader): StmtNode {
  let condition: Expr | null = null;
  let body: Block | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: condition = r.readMessage(decodeExpr); break;
      case 18: body = r.readMessage(decodeBlock); break;
      default: r.skip(tag);
    }
  }
  return { case: "while", condition: condition ?? MISSING_EXPR, body: body ?? EMPTY_BLOCK };
}

function decodeCaseArm(r: Reader): CaseArm {
  let pattern: Expr | null = null;
  let body: Stmt | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: pattern = r.readMessage(decodeExpr); break;
      case 18: body = r.readMessage(decodeStmt); break;
      default: r.skip(tag);
    }
  }
  return { pattern: pattern ?? MISSING_EXPR, body: body ?? MISSING_STMT };
}

function decodeMatch(r: Reader): StmtNode {
  let subject: Expr | null = null;
  const cases: CaseArm[] = [];
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: subject = r.readMessage(decodeExpr); break;
      case 18: cases.push(r.readMessage(decodeCaseArm)); break;
      default: r.skip(tag);
    }
  }
  return { case: "match", subject: subject ?? MISSING_EXPR, cases };
}

function decodeReturn(r: Reader): StmtNode {
  let value: Expr | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    if (tag === 10) value = r.readMessage(decodeExpr);
    else r.skip(tag);
  }
  return { case: "return", value };
}

function decodeMove(r: Reader): StmtNode {
  let target: Expr | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    if (tag === 10) target = r.readMessage(decodeExpr);
    else r.skip(tag);
  }
  return { case: "move", target: target ?? MISSING_EXPR };
}

function decodeFree(r: Reader): StmtNode {
  let target: Expr | null = null;
  let hook: HookRef | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: target = r.readMessage(decodeExpr); break;
      case 18: hook = r.readMessage(decodeHookRef); break;
      default: r.skip(tag);
    }
  }
  return { case: "free", target: target ?? MISSING_EXPR, hook };
}

function decodeExprStmt(r: Reader): StmtNode {
  let expr: Expr | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    if (tag === 10) expr = r.readMessage(decodeExpr);
    else r.skip(tag);
  }
  return { case: "expr", expr: expr ?? MISSING_EXPR };
}

function decodeThrow(r: Reader): StmtNode {
  let value: Expr | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    if (tag === 10) value = r.readMessage(decodeExpr);
    else r.skip(tag);
  }
  return { case: "throw", value: value ?? MISSING_EXPR };
}

function decodeTry(r: Reader): StmtNode {
  let tryBlock: Block | null = null;
  const catches: CatchClause[] = [];
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: tryBlock = r.readMessage(decodeBlock); break;
      // los tags 2 y 3 (catch_name/catch_block) quedaron 'reserved' al pasar
      // de un catch unico a N ramas filtradas: se ignoran, nunca se leen como
      // si fueran una rama.
      case 34: catches.push(r.readMessage(decodeCatch)); break;
      default: r.skip(tag);
    }
  }
  return { case: "try", tryBlock: tryBlock ?? EMPTY_BLOCK, catches };
}

function decodeCatch(r: Reader): CatchClause {
  let name = "";
  let block: Block | null = null;
  let type: Type | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: name = r.readString(); break;
      case 18: block = r.readMessage(decodeBlock); break;
      case 26: type = r.readMessage(decodeType); break;
      default: r.skip(tag);
    }
  }
  return { name, block: block ?? EMPTY_BLOCK, type };
}

function decodeImportBinding(r: Reader): StmtNode {
  let qualifier = "";
  let name = "";
  let lib = "";
  let member = "";
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: qualifier = r.readString(); break;
      case 18: name = r.readString(); break;
      case 26: lib = r.readString(); break;
      case 34: member = r.readString(); break;
      default: r.skip(tag);
    }
  }
  return { case: "importBinding", qualifier, name, lib, member };
}

// --------------------------------------------------------------------------- //
// declaraciones top-level
// --------------------------------------------------------------------------- //

function decodeParameter(r: Reader): Parameter {
  let type: Type | null = null;
  let name = "";
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 18: name = r.readString(); break;
      case 24: type = pooledType(r.readUint32()); break;
      default: r.skip(tag);
    }
  }
  return { type, name };
}

function decodeFunction(r: Reader): FunctionDecl {
  let name = "";
  const params: Parameter[] = [];
  let returnType: Type | null = null;
  let body: Block | null = null;
  let dunder = "";
  let decorator = "";
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: name = r.readString(); break;
      case 18: params.push(r.readMessage(decodeParameter)); break;
      case 56: returnType = pooledType(r.readUint32()); break;
      case 34: body = r.readMessage(decodeBlock); break;
      case 42: dunder = r.readString(); break;
      case 50: decorator = r.readString(); break;
      default: r.skip(tag);
    }
  }
  return { name, params, returnType, body, dunder, decorator };
}

function decodeField(r: Reader): Field {
  let type: Type | null = null;
  let name = "";
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 18: name = r.readString(); break;
      case 24: type = pooledType(r.readUint32()); break;
      default: r.skip(tag);
    }
  }
  return { type, name };
}

function decodeStruct(r: Reader): StructDecl {
  let name = "";
  const fields: Field[] = [];
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: name = r.readString(); break;
      case 18: fields.push(r.readMessage(decodeField)); break;
      default: r.skip(tag);
    }
  }
  return { name, fields };
}

function decodeEnumItem(r: Reader): EnumItem {
  let name = "";
  let value: Expr | null = null;
  const payloadTypeIds: number[] = [];
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: name = r.readString(); break;
      case 18: value = r.readMessage(decodeExpr); break;
      // 'repeated uint32' viaja EMPAQUETADO en proto3 (tag 26), pero un
      // escritor puede emitirlo campo a campo (tag 24): los dos son válidos y
      // los dos se leen, que es lo que exige aceptar cualquier .phir legal.
      case 24: payloadTypeIds.push(r.readUint32()); break;
      case 26: {
        const packed = r.readBytes();
        const inner = new Reader(packed);
        while (!inner.eof) payloadTypeIds.push(inner.readUint32());
        break;
      }
      default: r.skip(tag);
    }
  }
  return { name, value, payloadTypeIds };
}

function decodeEnum(r: Reader): EnumDecl {
  let name = "";
  const items: EnumItem[] = [];
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: name = r.readString(); break;
      case 18: items.push(r.readMessage(decodeEnumItem)); break;
      default: r.skip(tag);
    }
  }
  return { name, items };
}

function decodeTest(r: Reader): TestDecl {
  let name = "";
  let body: Block | null = null;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: name = r.readString(); break;
      case 18: body = r.readMessage(decodeBlock); break;
      default: r.skip(tag);
    }
  }
  return { name, body };
}

function decodeExternBlock(r: Reader): ExternBlock {
  let target = "";
  let raw = "";
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: target = r.readString(); break;
      case 18: raw = r.readString(); break;
      default: r.skip(tag);
    }
  }
  return { target, raw };
}

function decodeImportDirective(r: Reader): ImportDirective {
  let lib = "";
  let alias = "";
  let unit = "";
  let binding = "";
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: lib = r.readString(); break;
      case 18: alias = r.readString(); break;
      case 26: unit = r.readString(); break;
      case 34: binding = r.readString(); break;
      default: r.skip(tag);
    }
  }
  return { lib, alias, unit, binding };
}

function decodeExportDirective(r: Reader): ExportDirective {
  let alias = "";
  let pkg = false;
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: alias = r.readString(); break;
      case 16: pkg = r.readBool(); break;
      default: r.skip(tag);
    }
  }
  return { alias, package: pkg };
}

function decodeFromDirective(r: Reader): FromDirective {
  let lib = "";
  let name = "";
  let alias = "";
  let unit = "";
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: lib = r.readString(); break;
      case 18: name = r.readString(); break;
      case 26: alias = r.readString(); break;
      case 34: unit = r.readString(); break;
      default: r.skip(tag);
    }
  }
  return { lib, name, alias, unit };
}

function decodeDecl(r: Reader): Decl {
  let ln = 0;
  let col = 0;
  let node: DeclNode = { case: "none" };
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 8: ln = r.readUint32(); break;
      case 16: col = r.readUint32(); break;

      case 82: node = { case: "function", fn: r.readMessage(decodeFunction) }; break;
      case 90: node = { case: "struct", struct: r.readMessage(decodeStruct) }; break;
      case 98: node = { case: "enum", enumDecl: r.readMessage(decodeEnum) }; break;
      case 106: node = { case: "externBlock", externBlock: r.readMessage(decodeExternBlock) }; break;
      case 114: node = { case: "statement", stmt: r.readMessage(decodeStmt) }; break;
      case 122: node = { case: "import", directive: r.readMessage(decodeImportDirective) }; break;
      case 130: node = { case: "export", directive: r.readMessage(decodeExportDirective) }; break;
      case 138: node = { case: "from", directive: r.readMessage(decodeFromDirective) }; break;
      case 146: node = { case: "test", test: r.readMessage(decodeTest) }; break;
      default: r.skip(tag);
    }
  }
  return { ln, col, node };
}

// --------------------------------------------------------------------------- //
// raíz
// --------------------------------------------------------------------------- //

function decodeLibraryRef(r: Reader): LibraryRef {
  let alias = "";
  let phir = "";
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 10: alias = r.readString(); break;
      case 18: phir = r.readString(); break;
      default: r.skip(tag);
    }
  }
  return { alias, phir };
}

function decodeModuleBody(r: Reader): Module {
  let schemaVersion = 0;
  let sourceFile = "";
  let symbols: SymbolTable | null = null;
  const items: Decl[] = [];
  const libraries: LibraryRef[] = [];
  while (!r.eof) {
    const tag = r.readUint32();
    switch (tag) {
      case 8: schemaVersion = r.readUint32(); break;
      case 18: sourceFile = r.readString(); break;
      case 26: symbols = r.readMessage(decodeSymbolTable); break;
      case 34: items.push(r.readMessage(decodeDecl)); break;
      case 42: libraries.push(r.readMessage(decodeLibraryRef)); break;
      default: r.skip(tag);
    }
  }
  return {
    schemaVersion,
    sourceFile,
    symbols: symbols ?? EMPTY_SYMBOL_TABLE,
    items,
    libraries,
  };
}

/**
 * Bytes de un `.phir` -> {@link Module}, **sin** validar la versión del
 * esquema. Úsalo solo para inspeccionar un archivo del que se sospecha;
 * el camino normal es {@link loadModule}.
 *
 * @throws {HIRLoadError} si los bytes no son un `Module` protobuf.
 */
export function decodeModule(bytes: Uint8Array): Module {
  const anterior = TYPE_POOL;
  try {
    TYPE_POOL = scanTypePool(bytes);
    return decodeModuleBody(new Reader(bytes));
  } catch (exc) {
    if (exc instanceof WireError) {
      throw new HIRLoadError(`no contiene un Module HIR válido: ${exc.message}`);
    }
    throw exc;
  } finally {
    TYPE_POOL = anterior;
  }
}

/**
 * Camino normal: decodifica **y** valida `schema_version` (fail-fast).
 *
 * Misma política que `loader.load_module`: un `.phir` de una versión que
 * este lector no conoce se rechaza con un mensaje accionable, jamás se
 * interpreta "a ver si cuela".
 *
 * @param bytes contenido del `.phir`.
 * @param origin nombre del archivo, solo para el mensaje de error.
 * @throws {HIRLoadError}
 */
export function loadModule(bytes: Uint8Array, origin = "<memoria>"): Module {
  let module: Module;
  try {
    module = decodeModule(bytes);
  } catch (exc) {
    if (exc instanceof HIRLoadError) {
      throw new HIRLoadError(`'${origin}' ${exc.message}`);
    }
    throw exc;
  }
  if (!SUPPORTED_SCHEMA_VERSIONS.has(module.schemaVersion)) {
    const supported = [...SUPPORTED_SCHEMA_VERSIONS].sort((a, b) => a - b).join(", ");
    throw new HIRLoadError(
      `schema_version ${module.schemaVersion} no soportada por el backend web ` +
        `(soportadas: ${supported}) en '${origin}'. Regenera el .phir con un ` +
        "frontend compatible o actualiza el backend.",
    );
  }
  return module;
}
