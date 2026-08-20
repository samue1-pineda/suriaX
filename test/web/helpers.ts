/**
 * Utilidades de la suite del backend web.
 *
 * Dos formas de conseguir un HIR para probar, y cada una cubre lo que la
 * otra no:
 *
 *  - **fixtures reales** (`fixtures/*.phir`): bytes emitidos por el
 *    compilador Python. Son la única prueba de que el lector entiende el
 *    formato DE VERDAD y no una interpretación propia del `.proto`.
 *  - **{@link Writer}**: un codificador mínimo de protobuf, solo para
 *    pruebas, con el que se construyen casos que el frontend hoy no puede
 *    emitir (RBMM ya rechazado, un `oneof` vacío, bytes truncados, un
 *    `schema_version` futuro) o que exigirían un `.libsrx` entero.
 *
 * El `Writer` NO vive en `src/`: el backend web solo LEE HIR. El día que
 * haga falta re-serializar (por ejemplo para cachear el HIR optimizado en
 * `.web/`), este es el punto de partida, pero mientras no haga falta no
 * paga su peso en el bundle.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import type { PhirResolver } from "../../web/src/hir/link.ts";

/** Directorio de fixtures, relativo a ESTE archivo (no al cwd del runner). */
const FIXTURES = fileURLToPath(import.meta.url).replace(/helpers\.ts$/, "fixtures/");

/** Bytes de un fixture (`prog.phir`). */
export function fixture(name: string): Uint8Array {
  return new Uint8Array(readFileSync(FIXTURES + name));
}

/** Ruta absoluta de un fixture (la que se usa como `mainPath`). */
export function fixturePath(name: string): string {
  return FIXTURES + name;
}

/** Resolutor de unidades sobre el directorio de fixtures. */
export const fixtureResolver: PhirResolver = (relativePath) => {
  try {
    return fixture(relativePath);
  } catch {
    return null;
  }
};

// --------------------------------------------------------------------------- //
// codificador mínimo (solo pruebas)
// --------------------------------------------------------------------------- //

function encodeUtf8(text: string): number[] {
  const out: number[] = [];
  for (let i = 0; i < text.length; i++) {
    let cp = text.charCodeAt(i);
    if (cp >= 0xd800 && cp <= 0xdbff && i + 1 < text.length) {
      const low = text.charCodeAt(i + 1);
      if (low >= 0xdc00 && low <= 0xdfff) {
        cp = 0x10000 + ((cp - 0xd800) << 10) + (low - 0xdc00);
        i++;
      }
    }
    if (cp < 0x80) out.push(cp);
    else if (cp < 0x800) out.push(0xc0 | (cp >> 6), 0x80 | (cp & 0x3f));
    else if (cp < 0x10000) {
      out.push(0xe0 | (cp >> 12), 0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f));
    } else {
      out.push(
        0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 0x3f),
        0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f),
      );
    }
  }
  return out;
}

/** Escritor de wire-format: la contraparte de `Reader`, para pruebas. */
export class Writer {
  readonly #out: number[] = [];

  varint(value: number | bigint): this {
    let v = typeof value === "bigint" ? value : BigInt(Math.trunc(value));
    if (v < 0n) v = BigInt.asUintN(64, v);
    do {
      const byte = Number(v & 0x7fn);
      v >>= 7n;
      this.#out.push(v > 0n ? byte | 0x80 : byte);
    } while (v > 0n);
    return this;
  }

  tag(field: number, wire: number): this {
    return this.varint((field << 3) | wire);
  }

  uint32(field: number, value: number): this {
    return this.tag(field, 0).varint(value);
  }

  int64(field: number, value: bigint): this {
    return this.tag(field, 0).varint(value);
  }

  bool(field: number, value: boolean): this {
    return this.tag(field, 0).varint(value ? 1 : 0);
  }

  double(field: number, value: number): this {
    this.tag(field, 1);
    const buf = new DataView(new ArrayBuffer(8));
    buf.setFloat64(0, value, true);
    for (let i = 0; i < 8; i++) this.#out.push(buf.getUint8(i));
    return this;
  }

  string(field: number, value: string): this {
    const bytes = encodeUtf8(value);
    this.tag(field, 2).varint(bytes.length);
    this.#out.push(...bytes);
    return this;
  }

  /** Campo delimitado con contenido ya serializado. */
  raw(field: number, content: Uint8Array): this {
    this.tag(field, 2).varint(content.length);
    for (const byte of content) this.#out.push(byte);
    return this;
  }

  /** Submensaje construido en el sitio. */
  message(field: number, build: (w: Writer) => void): this {
    const inner = new Writer();
    build(inner);
    return this.raw(field, inner.finish());
  }

  finish(): Uint8Array {
    return new Uint8Array(this.#out);
  }
}

/**
 * Ids del POOL de tipos estándar que escribe {@link buildModule} (esquema v2).
 *
 * Un módulo construido a mano no puede llevar sus tipos inline: los nodos los
 * referencian por índice. En vez de obligar a cada prueba a montar su pool,
 * `buildModule` escribe siempre estos cuatro y los helpers los referencian.
 */
export const TYPE_VOID = 1;
export const TYPE_BOOL = 2;
export const TYPE_INT = 3;
export const TYPE_FLOAT = 4;
export const TYPE_STR = 5;
/** Primer id libre: los tipos que una prueba añada con `extraTypes`. */
export const TYPE_EXTRA = 6;

/**
 * Serializa un `Module` v2 con el contenido que indique `build`.
 *
 * `extraTypes` añade tipos al pool a partir de {@link TYPE_EXTRA} — lo que
 * necesita una prueba que hable de punteros o nominales, que no están entre
 * los primitivos fijos.
 */
export function buildModule(
  build: (w: Writer) => void,
  schemaVersion = 2,
  extraTypes: ((t: Writer) => void)[] = [],
): Uint8Array {
  const w = new Writer();
  w.uint32(1, schemaVersion);
  w.string(2, "<test>.srcx");
  build(w);
  // POOL (campo 6): la entrada 0 es el tipo vacío, luego los primitivos fijos
  // en el orden de TYPE_*, y luego los de la prueba. Va al final, igual que
  // en el emisor real (campo 6 > campo 4).
  w.message(6, () => {});
  for (const kind of [1, 2, 3, 4, 6]) w.message(6, (t) => t.uint32(1, kind));
  for (const extra of extraTypes) w.message(6, extra);
  return w.finish();
}

// --- atajos de nodos usados por varias pruebas ---------------------------- //

/** `Expr` con un `Identifier`. */
export function identifier(name: string, ln = 1, col = 1) {
  return (e: Writer): void => {
    e.uint32(1, ln);
    e.uint32(2, col);
    e.message(12, (id) => id.string(1, name));
  };
}

/** `Expr` con un `Literal` entero (con su `restype` INT, para la pureza). */
export function intLiteral(value: number, ln = 1, col = 1) {
  return (e: Writer): void => {
    e.uint32(1, ln);
    e.uint32(2, col);
    e.uint32(4, TYPE_INT); // restype (índice en el pool)
    e.message(10, (lit) => {
      lit.string(1, "int");
      lit.int64(2, BigInt(value));
    });
  };
}

/** `Stmt` que envuelve una expresión (`ExprStmt`). */
export function exprStmt(expr: (e: Writer) => void, ln = 1, col = 1) {
  return (s: Writer): void => {
    s.uint32(1, ln);
    s.uint32(2, col);
    s.message(21, (st) => st.message(1, expr));
  };
}

/** `Decl` con una `FunctionDecl` de cuerpo `body`. */
export function functionDecl(
  name: string,
  body: readonly ((s: Writer) => void)[],
  ln = 1,
) {
  return (d: Writer): void => {
    d.uint32(1, ln);
    d.uint32(2, 1);
    d.message(10, (fn) => {
      fn.string(1, name);
      fn.uint32(7, TYPE_INT); // return_type_id
      fn.message(4, (block) => {
        for (const stmt of body) block.message(1, stmt);
      });
    });
  };
}
