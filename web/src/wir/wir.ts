/**
 * WIR — *WebAssembly Intermediate Representation*. El puente entre el HIR y
 * el target web.
 *
 * ## Su lugar en el proyecto
 *
 * No es "el MIR movido a TypeScript". El **MIR es del backend C++** (VM
 * bytecode/JIT y, en su día, LLVM IR): un IR de registros, pensado para una
 * máquina de registros. El **WIR es de WebAssembly**, y WebAssembly es otra
 * cosa: una **máquina de PILA** con control de flujo **estructurado**. Dos
 * máquinas objetivo distintas piden dos IR distintos; forzar una sola habría
 * dejado a las dos a medias.
 *
 * ```
 *              HIR (protobuf)
 *             /              \
 *      MIR (C++)              WIR (TypeScript)
 *   registros, CFG            pila, control estructurado
 *        │                          │
 *   VM JIT / LLVM             wasm · js · wat
 * ```
 *
 * ## Qué implica que WASM sea una máquina de pila
 *
 * Una función WASM no tiene registros ni destinos: cada instrucción CONSUME
 * lo que hay en la pila y DEJA su resultado encima. `a + b * 2` no es
 * "`t1 = mul b,2` · `t2 = add a,t1`", es la secuencia
 * `local.get a` · `local.get b` · `i64.const 2` · `i64.mul` · `i64.add`.
 *
 * Es decir: **el código de una expresión es su recorrido en post-orden**. Por
 * eso el WIR guarda las expresiones como ÁRBOL con el tipo ya resuelto en
 * cada nodo — emitir es recorrerlo, sin asignación de registros, sin
 * temporales y sin decidir nada. Aplanar el árbol a tripletas (lo que hace un
 * MIR de registros) solo serviría para tener que reconstruirlo después.
 *
 * Y el control de flujo va en el mismo sentido: WASM no admite saltos
 * arbitrarios, solo `block`/`loop`/`if` anidados con salidas a etiquetas. Un
 * IR de bloques básicos obligaría a RECONSTRUIR esa estructura al emitir (el
 * problema del *relooping*, caro y nada trivial). Cuando entren los bucles,
 * el WIR ganará `loop`/`br` estructurados, nunca bloques básicos: la decisión
 * se toma aquí y ahora, a propósito.
 *
 * ## Qué resuelve el lowering (y los backends ya no)
 *
 * ```
 *   HIR                          WIR
 *   ─────────────────            ─────────────────
 *   nombres y scopes     ──▶     índices de local
 *   tipos nominales      ──▶     i32 / i64 / f64
 *   llamadas por nombre  ──▶     índices de función
 *   librería IO          ──▶     intrínsecos del host
 *   restype opcional     ──▶     tipo en TODO nodo
 * ```
 *
 * Después del lowering ya no hay nada que decidir: cada backend es una
 * traducción mecánica. Ese es el otro dividendo del puente — el emisor JS
 * sale gratis del mismo WIR, y ejecutar los dos tiene que dar el mismo
 * resultado (lo comprueba la suite).
 *
 * ## Alcance v1 (deliberado)
 *
 * Variables, aritmética, comparaciones y llamadas. Lo demás lo rechaza el
 * lowering con un diagnóstico posicionado, nunca con código a medias.
 */

/** Tipos de valor del WIR: los mismos que WebAssembly, menos `f32`. */
export const WirType = {
  VOID: 0,
  /** `bool` de suriaX (y los índices/longitudes de las cadenas). */
  I32: 1,
  /** `int` de suriaX: 64 bits con signo. */
  I64: 2,
  /** `float` de suriaX. */
  F64: 3,
} as const;
export type WirType = (typeof WirType)[keyof typeof WirType];

export const WIR_TYPE_NAMES: ReadonlyMap<WirType, string> = new Map([
  [WirType.VOID, "void"],
  [WirType.I32, "i32"],
  [WirType.I64, "i64"],
  [WirType.F64, "f64"],
]);

/** Operadores binarios del WIR. El TIPO va en el nodo, no en el operador. */
export const WirBinOp = {
  ADD: "add",
  SUB: "sub",
  MUL: "mul",
  /** División con signo para enteros. */
  DIV: "div",
  /** Resto con signo para enteros. */
  REM: "rem",
  EQ: "eq",
  NE: "ne",
  LT: "lt",
  LE: "le",
  GT: "gt",
  GE: "ge",
  AND: "and",
  OR: "or",
} as const;
export type WirBinOp = (typeof WirBinOp)[keyof typeof WirBinOp];

/** ¿El operador produce un booleano (i32) en vez del tipo de sus operandos? */
export function isComparison(op: WirBinOp): boolean {
  return op === WirBinOp.EQ || op === WirBinOp.NE || op === WirBinOp.LT ||
         op === WirBinOp.LE || op === WirBinOp.GT || op === WirBinOp.GE;
}

export const WirUnOp = {
  /** Negación aritmética. */
  NEG: "neg",
  /** Negación lógica (`not`). */
  NOT: "not",
} as const;
export type WirUnOp = (typeof WirUnOp)[keyof typeof WirUnOp];

/** Posición en el fuente, conservada para diagnósticos del backend. */
export interface WirPos {
  readonly ln: number;
  readonly col: number;
}

// --------------------------------------------------------------------------- //
// expresiones
// --------------------------------------------------------------------------- //

/**
 * Toda expresión del WIR lleva su TIPO resuelto: ningún backend infiere
 * nada. Es la diferencia práctica con el HIR, donde `restype` puede faltar.
 */
export type WirExpr =
  | { readonly kind: "const"; readonly type: WirType; readonly value: bigint | number }
  | { readonly kind: "local.get"; readonly type: WirType; readonly index: number }
  | {
      readonly kind: "binary";
      readonly type: WirType;
      readonly op: WirBinOp;
      /** Tipo de los OPERANDOS (en una comparación no es el del resultado). */
      readonly operandType: WirType;
      readonly left: WirExpr;
      readonly right: WirExpr;
    }
  | {
      readonly kind: "unary";
      readonly type: WirType;
      readonly op: WirUnOp;
      readonly operand: WirExpr;
    }
  /** Llamada a una función del propio módulo, por índice. */
  | {
      readonly kind: "call";
      readonly type: WirType;
      readonly func: number;
      readonly args: readonly WirExpr[];
    }
  /** Llamada a una primitiva del host (`__write__`), por índice de import. */
  | {
      readonly kind: "call.host";
      readonly type: WirType;
      readonly host: number;
      readonly args: readonly WirExpr[];
    }
  /**
   * Varias expresiones en orden; el valor es el de la última.
   *
   * Existe por los f-strings: `println(f"total {x}")` no construye una cadena
   * sino que ESCRIBE sus segmentos en orden (el texto literal, luego el
   * valor, luego el salto). Sin un runtime de cadenas —memoria dinámica,
   * concatenación y formateo de `float` en WASM a mano— esa es la forma
   * honesta de imprimir un valor calculado, y además evita la reserva que un
   * runtime de cadenas haría solo para tirarla.
   *
   * En una máquina de pila es concatenar el código de cada una; en JS, el
   * operador coma. Ninguno de los dos backends necesita nada nuevo.
   */
  | {
      readonly kind: "seq";
      readonly type: WirType;
      readonly exprs: readonly WirExpr[];
    }
  /**
   * `and` / `or` de CORTOCIRCUITO. No es un `binary` porque no lo es: el
   * lado derecho solo se evalúa si hace falta, y eso en una máquina de pila
   * no es una instrucción sino un `if` con resultado. Modelarlo como binario
   * habría hecho que `a() and b()` llamara siempre a `b`.
   */
  | {
      readonly kind: "logical";
      readonly type: WirType;
      readonly op: "and" | "or";
      readonly left: WirExpr;
      readonly right: WirExpr;
    }
  /**
   * `cast<T>(x)` entre tipos NUMÉRICOS: el valor cambia de representación.
   *
   * No es un `unary`: un unario devuelve el tipo de su operando y esto
   * existe justamente para no devolverlo. Lleva el tipo de ORIGEN además del
   * de destino porque en una máquina de pila la instrucción depende de los
   * dos (`i64 -> f64` no es la misma que `f64 -> i64`), y reconstruir el
   * origen mirando dentro del operando sería adivinar en el emisor lo que el
   * lowering ya sabía.
   */
  | {
      readonly kind: "convert";
      readonly type: WirType;
      readonly from: WirType;
      readonly value: WirExpr;
    }
  /** Lectura de una variable de módulo (`WirModule.globals`). */
  | {
      readonly kind: "global.get";
      readonly type: WirType;
      readonly index: number;
    };

// --------------------------------------------------------------------------- //
// sentencias
// --------------------------------------------------------------------------- //

/**
 * Las sentencias del WIR son un ÁRBOL, no una lista de bloques básicos con
 * saltos. WebAssembly solo admite control estructurado (`block`/`loop`/`if`
 * anidados y saltos a etiquetas de salida), así que un CFG habría que
 * volver a estructurarlo al emitir — el problema del *relooping*. Como los
 * bucles de suriaX son estructurados de origen, se conserva esa forma de
 * punta a punta.
 */
export type WirStmt =
  /** Declaración o asignación: `local[index] = value`. */
  | { readonly kind: "local.set"; readonly pos: WirPos; readonly index: number; readonly value: WirExpr }
  /** Escritura de una variable de módulo. */
  | { readonly kind: "global.set"; readonly pos: WirPos; readonly index: number; readonly value: WirExpr }
  /** Expresión evaluada por sus efectos; su resultado se descarta. */
  | { readonly kind: "drop"; readonly pos: WirPos; readonly value: WirExpr }
  | { readonly kind: "return"; readonly pos: WirPos; readonly value: WirExpr | null }
  | {
      readonly kind: "if";
      readonly pos: WirPos;
      readonly condition: WirExpr;
      readonly then: readonly WirStmt[];
      /** Vacío si no hay `else` (un `else if` se anida aquí). */
      readonly otherwise: readonly WirStmt[];
    }
  | {
      readonly kind: "while";
      readonly pos: WirPos;
      readonly condition: WirExpr;
      readonly body: readonly WirStmt[];
    }
  /** `break`: sale del bucle más interno. */
  | { readonly kind: "break"; readonly pos: WirPos }
  /** `continue`: vuelve a evaluar la condición del bucle más interno. */
  | { readonly kind: "continue"; readonly pos: WirPos };

// --------------------------------------------------------------------------- //
// módulo
// --------------------------------------------------------------------------- //

/** Un local (parámetro o variable) ya numerado. */
export interface WirLocal {
  /** Nombre original: solo para el WAT y los mensajes. */
  readonly name: string;
  readonly type: WirType;
}

export interface WirFunc {
  readonly name: string;
  readonly params: readonly WirLocal[];
  /** Locales declarados, DESPUÉS de los parámetros (índices correlativos). */
  readonly locals: readonly WirLocal[];
  readonly result: WirType;
  readonly body: readonly WirStmt[];
  /** Se exporta al host (todas las funciones de usuario, hoy). */
  readonly exported: boolean;
}

/** Primitiva que aporta el host (JS), no el programa. */
export interface WirHostImport {
  /** Módulo de import de WASM (`env`). */
  readonly module: string;
  readonly name: string;
  readonly params: readonly WirType[];
  readonly result: WirType;
}

/** Constante de cadena colocada en la memoria lineal. */
export interface WirString {
  readonly offset: number;
  readonly bytes: Uint8Array;
  /** Texto original, para el WAT y el JS legible. */
  readonly text: string;
}

export interface WirModule {
  /** `.srcx` de origen (diagnósticos y cabecera de los artefactos). */
  readonly source: string;
  readonly imports: readonly WirHostImport[];
  readonly funcs: readonly WirFunc[];
  readonly strings: readonly WirString[];
  /**
   * Variables de nivel de MÓDULO. No son locales de `__module_init`: viven
   * mientras vive el módulo y las ve cualquier función, que es justo lo que
   * un local no puede hacer. WebAssembly tiene su propia sección para esto.
   */
  readonly globals: readonly WirGlobal[];
  /** Bytes de memoria lineal que ocupan las cadenas. */
  readonly dataSize: number;
  /** Índice de `main`, o `null` si el programa no la declara. */
  readonly entry: number | null;
  /**
   * Índice del `__module_init` sintético: las sentencias de nivel de módulo
   * (las que el intérprete ejecuta antes de `main`) agrupadas en una función.
   */
  readonly init: number | null;
}

/**
 * Una variable de módulo.
 *
 * `mutable` no es cosmético: WebAssembly lo lleva en el binario y una global
 * inmutable no admite `global.set`, así que un `const` del programa se
 * convierte en un `const` del módulo y el validador lo hace cumplir. Es de
 * las pocas veces que una garantía del lenguaje sobrevive tal cual hasta el
 * binario.
 */
export interface WirGlobal {
  readonly name: string;
  readonly type: WirType;
  readonly mutable: boolean;
  /** Valor INICIAL: WASM solo admite una constante aquí. */
  readonly init: bigint | number;
}

/** Índice de una función en `WirModule.funcs` a partir de su nombre. */
export function findFunc(module: WirModule, name: string): number | null {
  const index = module.funcs.findIndex((f) => f.name === name);
  return index < 0 ? null : index;
}

/** Nombre legible de un tipo (WAT, mensajes). */
export function typeName(type: WirType): string {
  return WIR_TYPE_NAMES.get(type) ?? "?";
}
