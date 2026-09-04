/**
 * Diagnósticos del backend web — códigos `WEBxxx`.
 *
 * Misma disciplina que `V0/error_handler/`: cada regla tiene un CÓDIGO
 * estable, un mensaje accionable y una posición. Ninguna fase del backend
 * web lanza por construcciones del programa: **acumula** diagnósticos y
 * devuelve `(resultado | null, diagnósticos)`, igual que
 * `semantic.analyze` / `emmit_IR.build_module`. Solo los bytes corruptos
 * (un `.phir` que no es un `.phir`) lanzan, porque ahí no hay programa del
 * que hablar.
 *
 * La forma del objeto es la MISMA que `CompilerError.to_dict()` del
 * frontend Python, así el canal en vivo del LSP (`--emit-diagnostics`)
 * puede mezclar diagnósticos del compilador y del target web sin traducir
 * nada en medio.
 */

/** Severidades del proyecto (espejo de `error_handler/error.py`). */
export const Severity = {
  CRITICAL: "critical",
  WARNING: "warning",
  NOTE: "note",
} as const;
export type Severity = (typeof Severity)[keyof typeof Severity];

/**
 * Códigos del target web. El rango `WEB0xx` es de CONTENCIÓN (una
 * capacidad que el target no puede ejecutar todavía); `WEB9xx` es del
 * lector (bytes/esquema).
 */
export const WebCode = {
  /** `.phir` ilegible o `schema_version` no soportada. */
  DECODE: "WEB900",
  /** Nodo del HIR sin variante de `oneof`: HIR malformado o de un frontend más nuevo. */
  MALFORMED_NODE: "WEB901",

  /** `#extern cpp { ... }`: no hay toolchain C++ en el navegador. */
  EXTERN_CPP: "WEB001",
  /** Tipo puntero (`ptr T` / `ptr mutable T`) en una firma o binding. */
  POINTER_TYPE: "WEB002",
  /** `&x`: JS no tiene direcciones. */
  ADDRESS_OF: "WEB003",
  /** `free x;`: sin modelo de memoria manual en el target web. */
  FREE: "WEB004",
  /** Hook de memoria (`__free__` / `__sizeof__`). */
  MEMORY_HOOK: "WEB005",
  /** `move x;` (y `Symbol.moved_at`). */
  MOVE: "WEB006",
  /** Librería fuera de la allowlist del target. */
  LIBRARY_DENIED: "WEB007",
  /** `sizeof(T)`: depende del layout nativo. */
  SIZEOF: "WEB008",

  // --- WEB1xx: alcance del codegen (WIR -> wasm/js) ---------------------- //
  // Distintos de los WEB0xx a propósito: un WEB0xx dice "el target web no
  // puede ejecutar esto"; un WEB1xx dice "todavía no lo TRADUZCO". El primero
  // es una decisión de diseño, el segundo es trabajo pendiente.

  /** Construcción fuera del subconjunto que el codegen v1 traduce. */
  CODEGEN_UNSUPPORTED: "WEB100",
  /**
   * Tipo que el WIR no representa: int, float, bool, char, void, `str` y los
   * `enum` SIN payload sí caben; un struct o un puntero, no.
   */
  CODEGEN_TYPE: "WEB101",
  /**
   * Cadena CALCULADA (`a + b`, `cast<str>(x)`) donde hace falta su valor.
   *
   * Las CONSTANTES sí son valores de pleno derecho: se guardan en variables,
   * se pasan, se devuelven y se comparan con `==`, porque cada una viaja como
   * el índice de su constante en el módulo. Lo que falta es *fabricar* una
   * —concatenar, formatear—, que necesita un runtime con memoria dinámica; y
   * con ello el orden (`a < b`), que sobre índices contestaría por orden de
   * aparición en el fuente en vez de alfabético.
   */
  CODEGEN_STRING: "WEB102",
} as const;
export type WebCode = (typeof WebCode)[keyof typeof WebCode];

/** Un diagnóstico del backend web. */
export interface Diagnostic {
  readonly code: string;
  readonly message: string;
  /** 1-based; `0` cuando el nodo del HIR no transporta posición. */
  readonly line: number;
  /** 1-based; `0` cuando el nodo del HIR no transporta posición. */
  readonly column: number;
  /** Fuente `.srcx`/`.libsrx` de origen (`Module.source_file`). */
  readonly file: string;
  readonly severity: Severity;
  /** Fase que lo levantó: siempre `"web"` (para agrupar en el editor). */
  readonly phase: "web";
}

/** Posición mínima que comparte todo nodo del HIR. */
export interface HasPos {
  readonly ln: number;
  readonly col: number;
}

/**
 * Acumulador de diagnósticos. Existe para que ninguna pasada tenga que
 * decidir *cómo* se reporta: solo *qué* está mal y *dónde*.
 */
export class DiagnosticBag {
  readonly #items: Diagnostic[] = [];
  readonly #file: string;

  // sin 'parameter properties' (`constructor(private x)`) en TODO el paquete:
  // node ejecuta estos .ts BORRANDO tipos, y esa forma exige generar código.
  constructor(file: string) {
    this.#file = file;
  }

  /** Diagnósticos acumulados, en orden de descubrimiento. */
  get items(): readonly Diagnostic[] {
    return this.#items;
  }

  get length(): number {
    return this.#items.length;
  }

  /** ¿Hay al menos un diagnóstico que impide continuar? */
  get hasCritical(): boolean {
    return this.#items.some((d) => d.severity === Severity.CRITICAL);
  }

  add(
    code: string,
    message: string,
    pos: HasPos | null,
    severity: Severity = Severity.CRITICAL,
  ): void {
    this.#items.push({
      code,
      message,
      line: pos?.ln ?? 0,
      column: pos?.col ?? 0,
      file: this.#file,
      severity,
      phase: "web",
    });
  }
}

/** Una línea legible por humanos (CLI). */
export function formatDiagnostic(d: Diagnostic): string {
  const where = d.line > 0 ? `${d.file}:${d.line}:${d.column}` : d.file;
  return `[${d.severity}] ${d.code}: ${d.message}  (${where})`;
}
