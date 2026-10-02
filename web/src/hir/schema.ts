/**
 * Modelo TypeScript del HIR — espejo 1:1 de `V0/src/HIR/proto/hir.proto`.
 *
 * Reglas del espejo (las mismas que sigue `include/types_ast.py` respecto a
 * `message Type`):
 *
 *  - **un tipo por message**, con el mismo nombre. Única excepción:
 *    `message Symbol` -> {@link SymbolInfo}, porque `Symbol` ya existe en el
 *    global de JS y sombrearlo es una trampa esperando a alguien.
 *  - **`oneof` -> unión discriminada** por la propiedad `case`, cuyo valor
 *    es el nombre del campo en el `.proto`. El equivalente exacto de
 *    `WhichOneof("node")` en Python y de `node_case()` en C++: el consumidor
 *    despacha con un `switch` exhaustivo que el compilador de TS verifica —
 *    si el esquema gana una variante, todo `switch` sin ella deja de
 *    compilar. Eso es justo lo que se quiere de un puente versionado.
 *  - **`null` = campo ausente** en el wire (presencia explícita de proto3
 *    para los `message`). Nunca `undefined`: un solo valor para "no está".
 *  - los escalares ausentes traen su DEFAULT de proto3 (`""`, `0`, `false`),
 *    igual que los vería el lector C++ o Python.
 *  - todo es `readonly`: el HIR decodificado es un valor inmutable. Las
 *    pasadas (DCE) devuelven un módulo NUEVO compartiendo los subárboles que
 *    no tocaron, en vez de mutar el que les llega.
 *
 * Las variantes `{ case: "none" }` no existen en el `.proto`: son lo que el
 * lector produce cuando un `oneof` llega SIN ninguna variante (HIR
 * malformado, o emitido por un frontend más nuevo). No se adivina nada; el
 * módulo de restricciones lo reporta como `WEB901`.
 */

// --------------------------------------------------------------------------- //
// enums
// --------------------------------------------------------------------------- //

/**
 * `enum TypeKind`. Objeto `as const` en vez de `enum` de TypeScript: los
 * `enum` no son sintaxis BORRABLE (generan código), y estos `.ts` se
 * ejecutan directamente con el borrado de tipos de node.
 */
export const TypeKind = {
  TYPE_UNSPECIFIED: 0,
  VOID: 1,
  BOOL: 2,
  INT: 3,
  FLOAT: 4,
  CHAR: 5,
  STR: 6,
  POINTER: 7,
  NULLABLE: 8,
  NOMINAL: 9,
  META: 10,
  ERROR: 11,
  BYTE: 12,
} as const;
export type TypeKind = (typeof TypeKind)[keyof typeof TypeKind];

export const SymbolKind = {
  SYMBOL_UNSPECIFIED: 0,
  FUNCTION: 1,
  STRUCT: 2,
  ENUM: 3,
  ENUM_ITEM: 4,
  PARAM: 5,
  VAR: 6,
  FIELD: 7,
  IMPORT: 8,
  HOOK: 10,
  TYPE: 11,
  // 9 = REGION: retirado de v1 junto con RBMM (tag 'reserved' en el .proto).
} as const;
export type SymbolKind = (typeof SymbolKind)[keyof typeof SymbolKind];

// Espejo EXACTO de 'HookKind' en 'V0/src/HIR/proto/hir.proto'. El 2 no está:
// era '__make__', que se retiró con el modelo por regiones y quedó 'reserved'
// — un número retirado no se reutiliza nunca (ver PROTOBUF_BRIDGE.md).
export const HookKind = {
  HOOK_UNSPECIFIED: 0,
  FREE: 1,
  SIZEOF: 3,
  PRINT: 4,
  LEN: 5,
  CAST: 6,
  INDEX: 7,
  INDEX_SET: 8,
  EQ: 9,
  MIN: 10,
  MAX: 11,
  HASH: 12,
  /** Hook declarado por el proyecto (HTIMS): su identidad es el NOMBRE. */
  EXTENDED: 100,
} as const;
export type HookKind = (typeof HookKind)[keyof typeof HookKind];

/** Nombre legible de un `TypeKind` (diagnósticos y volcados). */
export const TYPE_KIND_NAMES: readonly string[] = [
  "<?>", "void", "bool", "int", "float", "char", "str",
  "pointer", "nullable", "nominal", "type", "error", "byte",
];

/** Nombre legible de un `SymbolKind`, indexado por su valor. */
export const SYMBOL_KIND_NAMES: ReadonlyMap<SymbolKind, string> = new Map([
  [SymbolKind.SYMBOL_UNSPECIFIED, "?"],
  [SymbolKind.FUNCTION, "fn"],
  [SymbolKind.STRUCT, "struct"],
  [SymbolKind.ENUM, "enum"],
  [SymbolKind.ENUM_ITEM, "enum item"],
  [SymbolKind.PARAM, "param"],
  [SymbolKind.VAR, "var"],
  [SymbolKind.FIELD, "field"],
  [SymbolKind.IMPORT, "import"],
  [SymbolKind.HOOK, "hook"],
  [SymbolKind.TYPE, "type"],
]);

/** `__nombre__` de cada hook, tal como se escribe en suriaX. */
export const HOOK_KIND_NAMES: ReadonlyMap<HookKind, string> = new Map([
  [HookKind.HOOK_UNSPECIFIED, "__?__"],
  [HookKind.FREE, "__free__"],
  [HookKind.SIZEOF, "__sizeof__"],
  [HookKind.PRINT, "__print__"],
  [HookKind.LEN, "__len__"],
  [HookKind.CAST, "__cast__"],
  [HookKind.INDEX, "__index__"],
  [HookKind.INDEX_SET, "__index_set__"],
  [HookKind.EQ, "__eq__"],
  [HookKind.MIN, "__min__"],
  [HookKind.MAX, "__max__"],
  [HookKind.HASH, "__hash__"],
  [HookKind.EXTENDED, "__extendido__"],
]);

// --------------------------------------------------------------------------- //
// tipos y símbolos
// --------------------------------------------------------------------------- //

/** Posición en el fuente (1-based, como la reporta el lexer). */
export interface Pos {
  readonly ln: number;
  readonly col: number;
}

/** `message Type` — plano con `inner` recursivo. */
export interface Type {
  readonly kind: TypeKind;
  /** Solo `NOMINAL`. */
  readonly name: string;
  /** `POINTER` / `NULLABLE` / `ERROR` (`error` a secas llega sin `inner`). */
  readonly inner: Type | null;
  /** Solo `POINTER`: `ptr mutable T` (escribible) vs `ptr T` (solo lectura). */
  readonly mut: boolean;
  /**
   * Solo `NOMINAL`: los argumentos de un genérico (`Vector<int>`).
   * Participan de la IDENTIDAD del tipo — `Vector<int>` y `Vector<str>` son
   * tipos distintos. El decodificador los descartaba en silencio, así que
   * las dos instanciaciones llegaban al web como el mismo tipo y `typeKey`
   * las metía en la misma entrada del índice de conversiones.
   */
  readonly args: readonly Type[];
}

/** `message Symbol` (renombrado: `Symbol` es un global de JS). */
export interface SymbolInfo extends Pos {
  readonly name: string;
  readonly kind: SymbolKind;
  /** Retorno si `FUNCTION`/`HOOK`; tipo del binding en los demás. */
  readonly type: Type | null;
  readonly mutable: boolean;
  /** Línea del `move` estático (`0` = nunca movido). */
  readonly movedAt: number;
  readonly paramTypes: readonly Type[];
  /** `STRUCT`: campos · `ENUM`: items · `IMPORT`: vacío (viaja opaco). */
  readonly members: ReadonlyMap<string, SymbolInfo>;
  /** Solo `kind === HOOK`. */
  readonly hookKind: HookKind;
  /** Solo `kind === HOOK`: nombre del tipo nominal dueño. */
  readonly hookOwner: string;
}

/** `message HookEntry`. */
export interface HookEntry {
  readonly ownerType: string;
  readonly kind: HookKind;
  readonly symbol: SymbolInfo | null;
}

/** `message SymbolTable` — solo el scope GLOBAL (los de bloque no viajan). */
export interface SymbolTable {
  readonly types: ReadonlyMap<string, SymbolInfo>;
  readonly values: ReadonlyMap<string, SymbolInfo>;
  readonly hooks: readonly HookEntry[];
  /** Tabla de conversiones `__cast__` (origen = `paramTypes[0]`, destino = `type`). */
  readonly casts: readonly SymbolInfo[];
}

/** `message HookRef` — clave (owner, kind) para el lookup O(1). */
export interface HookRef {
  readonly ownerType: string;
  readonly kind: HookKind;
}

// --------------------------------------------------------------------------- //
// expresiones
// --------------------------------------------------------------------------- //

/** `message Literal` — el `kind` del `.proto` decide la variante. */
export type Literal =
  | { readonly kind: "int"; readonly value: bigint }
  | { readonly kind: "float"; readonly value: number }
  | { readonly kind: "str"; readonly value: string }
  | { readonly kind: "char"; readonly value: string }
  | { readonly kind: "bool"; readonly value: boolean }
  | { readonly kind: "null" }
  /** `kind` que este lector no conoce: se transporta crudo, no se adivina. */
  | { readonly kind: "unknown"; readonly raw: string };

/** Parte de un f-string: texto literal o expresión interpolada. */
export type InterpPart =
  | { readonly case: "text"; readonly text: string }
  | {
      readonly case: "expr";
      readonly expr: Expr;
      /** `{x!r}`: la representación (comillas, `Color.Verde`...). */
      readonly repr?: boolean;
      /** `{n:08b}`: el especificador `[0][ancho][.precision][tipo]`. */
      readonly spec?: string;
    };

/** `message Expr`: posición + tipo resuelto + variante del `oneof`. */
export interface Expr extends Pos {
  /** Tipo que resolvió la Semántica; `null` = aún no inferible. */
  readonly restype: Type | null;
  readonly node: ExprNode;
}

export type ExprNode =
  | { readonly case: "literal"; readonly literal: Literal }
  | { readonly case: "interp"; readonly parts: readonly InterpPart[] }
  | { readonly case: "identifier"; readonly name: string }
  | { readonly case: "unary"; readonly op: string; readonly operand: Expr }
  | {
      readonly case: "binary";
      readonly op: string;
      readonly left: Expr;
      readonly right: Expr;
    }
  | { readonly case: "assignment"; readonly target: Expr; readonly value: Expr }
  | {
      readonly case: "call";
      readonly callee: Expr;
      readonly args: readonly Expr[];
      readonly hook: HookRef | null;
    }
  | { readonly case: "index"; readonly obj: Expr; readonly index: Expr }
  | { readonly case: "member"; readonly obj: Expr; readonly member: string }
  | { readonly case: "sizeof"; readonly type: Type | null; readonly hook: HookRef | null }
  /** `&x` con la mutabilidad YA resuelta por la Semántica. */
  | { readonly case: "addrOf"; readonly operand: Expr; readonly mut: boolean }
  /**
   * `move x` en posición de EXPRESIÓN: transfiere y entrega el valor.
   * Distinto de `MoveStmt`, que invalida sin llevarse nada. El target web
   * deniega los dos por igual (`WEB006`): mover exige invalidar el origen en
   * ejecución, y el web aún no lo hace cumplir.
   */
  | { readonly case: "moveExpr"; readonly operand: Expr }
  | {
      readonly case: "cast";
      readonly type: Type | null;
      readonly value: Expr;
      readonly hook: HookRef | null;
    }
  | {
      readonly case: "structLiteral";
      readonly typeName: string;
      /** Paralelo a `values`: mismo índice = mismo campo. */
      readonly fieldNames: readonly string[];
      readonly values: readonly Expr[];
    }
  | { readonly case: "none" };

// --------------------------------------------------------------------------- //
// sentencias
// --------------------------------------------------------------------------- //

export interface Block {
  readonly statements: readonly Stmt[];
}

export interface CaseArm {
  readonly pattern: Expr;
  readonly body: Stmt;
}

/** `message IfStmt`: se referencia a sí mismo por el `else if` encadenado. */
export interface IfStmt {
  readonly condition: Expr;
  readonly thenBlock: Block;
  readonly elseBranch: ElseBranch;
}

export type ElseBranch =
  | { readonly case: "none" }
  | { readonly case: "block"; readonly block: Block }
  | { readonly case: "if"; readonly ifStmt: IfStmt };

export interface Stmt extends Pos {
  readonly node: StmtNode;
}

export type StmtNode =
  | { readonly case: "block"; readonly block: Block }
  | {
      readonly case: "varDecl";
      /** `'const'` | `'var'` | `''` (vacío equivale a `var`). */
      readonly qualifier: string;
      readonly type: Type | null;
      readonly name: string;
      readonly value: Expr | null;
    }
  | { readonly case: "if"; readonly ifStmt: IfStmt }
  | { readonly case: "while"; readonly condition: Expr; readonly body: Block }
  | { readonly case: "match"; readonly subject: Expr; readonly cases: readonly CaseArm[] }
  | { readonly case: "return"; readonly value: Expr | null }
  | { readonly case: "break" }
  | { readonly case: "continue" }
  | { readonly case: "move"; readonly target: Expr }
  | { readonly case: "free"; readonly target: Expr; readonly hook: HookRef | null }
  | { readonly case: "expr"; readonly expr: Expr }
  | {
      readonly case: "importBinding";
      readonly qualifier: string;
      readonly name: string;
      readonly lib: string;
      /** Solo `#from lib #import member` (`''` = módulo completo). */
      readonly member: string;
    }
  | {
      readonly case: "typeDecl";
      readonly qualifier: string;
      readonly name: string;
      readonly value: Expr | null;
    }
  | { readonly case: "throw"; readonly value: Expr }
  | {
      readonly case: "try";
      readonly tryBlock: Block;
      /** Ramas 'catch' EN ORDEN; gana la primera cuyo tipo encaje. */
      readonly catches: readonly CatchClause[];
      /** 'finally': corre al salir por cualquier camino; null = no hay. */
      readonly finallyBlock: Block | null;
    }
  | { readonly case: "none" };

/** Una rama 'catch'. Sin `type`, atrapa cualquier valor. */
export interface CatchClause {
  readonly name: string;
  readonly block: Block;
  readonly type: Type | null;
}

// --------------------------------------------------------------------------- //
// declaraciones top-level
// --------------------------------------------------------------------------- //

export interface Parameter {
  readonly type: Type | null;
  readonly name: string;
}

export interface FunctionDecl {
  readonly name: string;
  readonly params: readonly Parameter[];
  readonly returnType: Type | null;
  /** `null` = PROTOTIPO (la implementación la aporta el host/backend). */
  readonly body: Block | null;
  /** Nombre sin guiones si es hook/dunder (`''` = función normal). */
  readonly dunder: string;
  /** Decorador aplicado (`''` = ninguno). */
  readonly decorator: string;
}

export interface Field {
  readonly type: Type | null;
  readonly name: string;
}

export interface StructDecl {
  readonly name: string;
  readonly fields: readonly Field[];
}

export interface EnumItem {
  readonly name: string;
  readonly value: Expr | null;
  /**
   * Tipos del PAYLOAD (`Numero(int)`), como índices en `Module.types`.
   *
   * Vacío = el item es una constante entera. No vacío = el enum es un tipo
   * SUMA y sus valores dejan de ser enteros. El `.proto` lo dice con estas
   * palabras y este lector lo ignoraba: sin el campo, `Numero(int)` y `ROJO`
   * llegaban idénticos y un backend los habría traducido igual — el mismo
   * error que se coló con `Type.args`, donde `Vector<int>` y `Vector<str>`
   * colisionaban por no leer un campo que el `.proto` sí declaraba.
   */
  readonly payloadTypeIds: readonly number[];
}

export interface EnumDecl {
  readonly name: string;
  readonly items: readonly EnumItem[];
}

export interface TestDecl {
  readonly name: string;
  readonly body: Block | null;
}

export interface ExternBlock {
  /** Hoy solo `"cpp"`. */
  readonly target: string;
  readonly raw: string;
}

export interface ImportDirective {
  /** Lo que se ESCRIBIÓ (`io.string`). Solo diagnósticos. */
  readonly lib: string;
  readonly alias: string;
  /** Unidad RESUELTA (`IO.stdp`): la clave de `LibraryRef.alias`. */
  readonly unit: string;
  /** Nombre local que ligó la Semántica. */
  readonly binding: string;
}

export interface ExportDirective {
  readonly alias: string;
  readonly package: boolean;
}

export interface FromDirective {
  readonly lib: string;
  readonly name: string;
  readonly alias: string;
  readonly unit: string;
}

export interface Decl extends Pos {
  readonly node: DeclNode;
}

export type DeclNode =
  | { readonly case: "function"; readonly fn: FunctionDecl }
  | { readonly case: "struct"; readonly struct: StructDecl }
  | { readonly case: "enum"; readonly enumDecl: EnumDecl }
  | { readonly case: "externBlock"; readonly externBlock: ExternBlock }
  | { readonly case: "statement"; readonly stmt: Stmt }
  | { readonly case: "import"; readonly directive: ImportDirective }
  | { readonly case: "export"; readonly directive: ExportDirective }
  | { readonly case: "from"; readonly directive: FromDirective }
  | { readonly case: "test"; readonly test: TestDecl }
  | { readonly case: "none" };

// --------------------------------------------------------------------------- //
// raíz
// --------------------------------------------------------------------------- //

/** Unidad `.libsrx` referenciada (su HIR vive en su propio `.phir`). */
export interface LibraryRef {
  /** Nombre público de la unidad (`IO`, `IO.stdp`), el del `#export`. */
  readonly alias: string;
  /** Archivo relativo al `.phir` que la referencia. */
  readonly phir: string;
}

export interface Module {
  readonly schemaVersion: number;
  readonly sourceFile: string;
  readonly symbols: SymbolTable;
  readonly items: readonly Decl[];
  readonly libraries: readonly LibraryRef[];
}

// --------------------------------------------------------------------------- //
// utilidades del modelo
// --------------------------------------------------------------------------- //

/** Tabla de símbolos vacía (módulo sin `symbols`). */
export const EMPTY_SYMBOL_TABLE: SymbolTable = {
  types: new Map(),
  values: new Map(),
  hooks: [],
  casts: [],
};

export const EMPTY_BLOCK: Block = { statements: [] };

/**
 * `Type` -> notación de suriaX (`int ptr mutable`, `T?`, `Vector<int>`).
 * Espejo de `V0/src/HIR/pretty.format_type`, que es la definición de
 * referencia. Se escribe TODO lo que participa de la identidad del tipo: los
 * argumentos de un genérico incluidos, porque `Vector<int>` y `Vector<str>`
 * son tipos distintos.
 */
export function formatType(t: Type | null): string {
  if (t === null || t.kind === TypeKind.TYPE_UNSPECIFIED) return "<?>";
  switch (t.kind) {
    case TypeKind.POINTER:
      return formatType(t.inner) + (t.mut ? " ptr mutable" : " ptr");
    case TypeKind.NULLABLE:
      return formatType(t.inner) + "?";
    case TypeKind.ERROR:
      return t.inner === null ? "error" : `error ${formatType(t.inner)}`;
    case TypeKind.NOMINAL:
      return t.args.length === 0
        ? t.name
        : `${t.name}<${t.args.map(formatType).join(", ")}>`;
    default:
      return TYPE_KIND_NAMES[t.kind] ?? "<?>";
  }
}

/**
 * Clave estructural de un `Type` — espejo de `hook/dispatch.type_key`.
 * Es la MISMA identidad que usó la Semántica para registrar los `__cast__`,
 * así que el índice de conversiones del web coincide con el del intérprete.
 */
export function typeKey(t: Type | null): string {
  if (t === null || t.kind === TypeKind.TYPE_UNSPECIFIED) return "";
  const args = t.args.map(typeKey).join(",");
  return `${t.kind}:${t.name}:${t.mut ? 1 : 0}:(${typeKey(t.inner)}):[${args}]`;
}

/** Clave del índice de hooks: `(owner, kind)` en una sola cadena. */
export function hookKey(ownerType: string, kind: HookKind): string {
  return `${ownerType}#${kind}`;
}

/** `__print__` etc. tal como se escribe, para los mensajes de error. */
export function hookName(kind: HookKind): string {
  return HOOK_KIND_NAMES.get(kind) ?? `__hook${kind}__`;
}
