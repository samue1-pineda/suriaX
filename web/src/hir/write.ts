/**
 * Escritor del *wire format* de protobuf — la contraparte de `wire.ts`.
 *
 * Mismo criterio que el lector: cero dependencias y solo lo que el esquema
 * del HIR usa (varint, 64 bits, delimitados). No hay reflexión ni
 * descriptores; quien serializa un message sabe qué campos tiene, igual que
 * el emisor explícito del frontend (`emmit_IR.py`).
 *
 * ### Reglas de proto3 que este escritor respeta
 *  - un escalar con su valor por DEFECTO (`0`, `""`, `false`) **no se
 *    escribe**: el lector lo repone. Escribirlo produciría bytes distintos
 *    de los del emisor Python para el mismo módulo;
 *  - un campo dentro de un `oneof` **sí se escribe siempre**, aunque valga
 *    el defecto: es lo único que distingue "es un literal `0`" de "no hay
 *    literal" (equivale al `SetInParent()` del emisor Python);
 *  - los campos salen en orden ASCENDENTE de número, que es lo que hace la
 *    implementación de referencia.
 *
 * El buffer crece duplicándose; los submensajes se arman en un escritor
 * propio y se copian con su longitud delante (la longitud no se conoce hasta
 * el final). Para los tamaños de un `.phir` —kilobytes— es intrascendente, y
 * mantiene el código legible.
 */

/** Bytes que se reservan al empezar; crece solo si hace falta. */
const INITIAL_CAPACITY = 1024;

export class Writer {
  #buf: Uint8Array;
  #len = 0;

  constructor(capacity = INITIAL_CAPACITY) {
    this.#buf = new Uint8Array(capacity);
  }

  /** Bytes escritos hasta ahora. */
  get length(): number {
    return this.#len;
  }

  #ensure(extra: number): void {
    const needed = this.#len + extra;
    if (needed <= this.#buf.length) return;
    let capacity = this.#buf.length * 2;
    while (capacity < needed) capacity *= 2;
    const next = new Uint8Array(capacity);
    next.set(this.#buf.subarray(0, this.#len));
    this.#buf = next;
  }

  #push(byte: number): void {
    this.#ensure(1);
    this.#buf[this.#len++] = byte;
  }

  /** Varint sin signo de 32 bits (tags, longitudes, `uint32` del esquema). */
  varint32(value: number): this {
    let v = value >>> 0;
    this.#ensure(5);
    while (v > 0x7f) {
      this.#buf[this.#len++] = (v & 0x7f) | 0x80;
      v >>>= 7;
    }
    this.#buf[this.#len++] = v;
    return this;
  }

  /** Varint de 64 bits en complemento a dos (campos `int64`). */
  varint64(value: bigint): this {
    let v = BigInt.asUintN(64, value);
    this.#ensure(10);
    while (v > 0x7fn) {
      this.#buf[this.#len++] = Number(v & 0x7fn) | 0x80;
      v >>= 7n;
    }
    this.#buf[this.#len++] = Number(v);
    return this;
  }

  tag(field: number, wire: number): this {
    return this.varint32((field << 3) | wire);
  }

  // --- campos con omisión de defectos (proto3) ---------------------------- //

  /** `uint32`; omitido si vale 0. */
  uint32(field: number, value: number): this {
    if (value === 0) return this;
    return this.tag(field, 0).varint32(value);
  }

  /** Enum; omitido si vale 0 (`*_UNSPECIFIED`). */
  enum(field: number, value: number): this {
    if (value === 0) return this;
    return this.tag(field, 0).varint32(value);
  }

  /** `bool`; omitido si es `false`. */
  bool(field: number, value: boolean): this {
    if (!value) return this;
    return this.tag(field, 0).varint32(1);
  }

  /** `string`; omitido si está vacío. */
  string(field: number, value: string): this {
    if (value === "") return this;
    return this.rawString(field, value);
  }

  // --- campos que SIEMPRE se escriben (variantes de un oneof) ------------- //

  /** `int64` incondicional. */
  int64Always(field: number, value: bigint): this {
    return this.tag(field, 0).varint64(value);
  }

  /** `double` incondicional (8 bytes little-endian). */
  doubleAlways(field: number, value: number): this {
    this.tag(field, 1);
    this.#ensure(8);
    new DataView(this.#buf.buffer, this.#buf.byteOffset + this.#len, 8)
      .setFloat64(0, value, true);
    this.#len += 8;
    return this;
  }

  /** `bool` incondicional. */
  boolAlways(field: number, value: boolean): this {
    return this.tag(field, 0).varint32(value ? 1 : 0);
  }

  /** `string` incondicional (aunque esté vacío). */
  rawString(field: number, value: string): this {
    const bytes = encodeUtf8(value);
    this.tag(field, 2).varint32(bytes.length);
    this.#ensure(bytes.length);
    this.#buf.set(bytes, this.#len);
    this.#len += bytes.length;
    return this;
  }

  /** Campo delimitado con contenido ya serializado. */
  bytes(field: number, content: Uint8Array): this {
    this.tag(field, 2).varint32(content.length);
    this.#ensure(content.length);
    this.#buf.set(content, this.#len);
    this.#len += content.length;
    return this;
  }

  /**
   * Submensaje. Se escribe SIEMPRE, aunque quede vacío: es lo que marca la
   * variante de un `oneof` sin campos (`break;`, `return;`, `&x` no mutable).
   */
  message(field: number, build: (w: Writer) => void): this {
    const inner = new Writer(256);
    build(inner);
    return this.bytes(field, inner.finish());
  }

  /** Submensaje que se omite si no escribió nada (campos opcionales). */
  messageIfAny(field: number, build: (w: Writer) => void): this {
    const inner = new Writer(256);
    build(inner);
    if (inner.length === 0) return this;
    return this.bytes(field, inner.finish());
  }

  /** Vista sobre los bytes escritos (sin copia extra). */
  finish(): Uint8Array {
    return this.#buf.subarray(0, this.#len);
  }
}

/** String -> UTF-8. Contraparte de `decodeUtf8` de `wire.ts`. */
export function encodeUtf8(text: string): Uint8Array {
  // ruta rápida ASCII: un byte por code unit, sin mirar pares suplentes.
  let ascii = true;
  for (let i = 0; i < text.length; i++) {
    if (text.charCodeAt(i) > 0x7f) {
      ascii = false;
      break;
    }
  }
  if (ascii) {
    const out = new Uint8Array(text.length);
    for (let i = 0; i < text.length; i++) out[i] = text.charCodeAt(i);
    return out;
  }

  const bytes: number[] = [];
  for (let i = 0; i < text.length; i++) {
    let cp = text.charCodeAt(i);
    if (cp >= 0xd800 && cp <= 0xdbff && i + 1 < text.length) {
      const low = text.charCodeAt(i + 1);
      if (low >= 0xdc00 && low <= 0xdfff) {
        cp = 0x10000 + ((cp - 0xd800) << 10) + (low - 0xdc00);
        i++;
      }
    }
    if (cp < 0x80) bytes.push(cp);
    else if (cp < 0x800) bytes.push(0xc0 | (cp >> 6), 0x80 | (cp & 0x3f));
    else if (cp < 0x10000) {
      bytes.push(0xe0 | (cp >> 12), 0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f));
    } else {
      bytes.push(
        0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 0x3f),
        0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f),
      );
    }
  }
  return new Uint8Array(bytes);
}
