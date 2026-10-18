/**
 * Lector del *wire format* de protobuf — cero dependencias.
 *
 * El backend web NO usa `protobufjs` ni stubs generados: el `.phir` llega al
 * navegador como bytes y se decodifica con este lector de ~200 líneas. Las
 * razones son las mismas que llevaron al frontend a un emisor explícito
 * (`emmit_IR.py`) en vez de reflexión:
 *
 *  - **cero pasos de build**: no hay que correr `protoc` ni publicar stubs
 *    JS para compilar en el navegador; el esquema vive en `schema.ts` y se
 *    revisa contra `proto/hir.proto` como cualquier otro espejo del
 *    proyecto (igual que `include/types_ast.py` ↔ `message Type`);
 *  - **cero peso muerto**: un runtime genérico de protobuf pesa más que
 *    todo este backend, y el 90% de su superficie (Any, extensiones,
 *    grupos, JSON, reflexión) no la usa este esquema;
 *  - **fail-fast real**: cada error de bytes trae el OFFSET donde ocurrió.
 *
 * El lector es de un solo sentido y sin copias: los mensajes anidados se
 * leen moviendo un límite (`#limit`) sobre el MISMO buffer, no cortando
 * sub-arrays. Solo las cadenas materializan memoria nueva.
 *
 * Referencia del formato: cada campo va precedido de un *tag* varint
 * `(field_number << 3) | wire_type`.
 */

/** Tipos de *wire* de proto3 (los grupos 3/4 están retirados del formato). */
export const WireType = {
  VARINT: 0,
  I64: 1,
  LEN: 2,
  I32: 5,
} as const;
export type WireType = (typeof WireType)[keyof typeof WireType];

/**
 * Profundidad máxima de mensajes anidados. Un `.phir` puede venir de un
 * archivo que el usuario soltó en el navegador: sin este tope, un buffer
 * hecho a mano con 100.000 mensajes anidados desborda la pila de JS.
 *
 * El valor sale del límite del LENGUAJE: el parser rechaza (`PAR025`) lo que
 * anide más de 500 niveles (`MAX_NESTING`, en `grammar/program.py`), y cada
 * nivel del árbol son como mucho DOS mensajes en el HIR (el envoltorio y su
 * variante): 1000 medidos en el peor caso. Si el frontend sube su límite,
 * este sube con él — antes valía 200 "porque el frontend no produce árboles
 * tan profundos", y sí los producía: una suma de 100 términos ya no se leía.
 */
export const MAX_NESTING_DEPTH = 1024;

/** Los bytes no son un mensaje protobuf válido (o se acabaron a media lectura). */
export class WireError extends Error {
  readonly offset: number;

  constructor(message: string, offset: number) {
    super(`${message} (offset ${offset})`);
    this.name = "WireError";
    this.offset = offset;
  }
}

// --------------------------------------------------------------------------- //
// decodificado UTF-8
// --------------------------------------------------------------------------- //

interface Utf8Decoder {
  decode(input: Uint8Array): string;
}

/**
 * `TextDecoder` del entorno si existe (navegador, node, deno). No se
 * declara como dependencia de tipos (`types: []` en el tsconfig): se
 * consulta en `globalThis` con su forma mínima, y si no está, el decodificador
 * manual de abajo cubre el caso. Así el paquete compila y corre igual en un
 * runtime pelado.
 */
const nativeDecoder: Utf8Decoder | null = (() => {
  const ctor = (globalThis as { TextDecoder?: new (label?: string) => Utf8Decoder })
    .TextDecoder;
  return ctor === undefined ? null : new ctor("utf-8");
})();

/** A partir de aquí conviene el decodificador nativo; por debajo, no. */
const NATIVE_DECODE_THRESHOLD = 32;

/**
 * `Uint8Array[start, end)` -> string. Los nombres del HIR (identificadores,
 * claves de `map`) son cortos y casi siempre ASCII: esa ruta se resuelve sin
 * tocar `TextDecoder`, que en cadenas de pocos bytes cuesta más que el bucle.
 */
export function decodeUtf8(buf: Uint8Array, start: number, end: number): string {
  const length = end - start;
  if (length === 0) return "";

  if (length < NATIVE_DECODE_THRESHOLD || nativeDecoder === null) {
    // ruta rápida ASCII: un solo barrido, sin acumuladores intermedios.
    let ascii = true;
    for (let i = start; i < end; i++) {
      if (buf[i]! > 0x7f) {
        ascii = false;
        break;
      }
    }
    if (ascii) {
      let out = "";
      for (let i = start; i < end; i++) out += String.fromCharCode(buf[i]!);
      return out;
    }
    if (nativeDecoder === null) return decodeUtf8Slow(buf, start, end);
  }
  return nativeDecoder!.decode(buf.subarray(start, end));
}

/** Decodificador UTF-8 completo para runtimes sin `TextDecoder`. */
function decodeUtf8Slow(buf: Uint8Array, start: number, end: number): string {
  let out = "";
  let i = start;
  while (i < end) {
    const b0 = buf[i++]!;
    if (b0 < 0x80) {
      out += String.fromCharCode(b0);
    } else if (b0 < 0xe0) {
      out += String.fromCharCode(((b0 & 0x1f) << 6) | (buf[i++]! & 0x3f));
    } else if (b0 < 0xf0) {
      out += String.fromCharCode(
        ((b0 & 0x0f) << 12) | ((buf[i++]! & 0x3f) << 6) | (buf[i++]! & 0x3f),
      );
    } else {
      // fuera del BMP: se emite como par suplente (lo que hace el propio JS).
      const cp =
        (((b0 & 0x07) << 18) |
          ((buf[i++]! & 0x3f) << 12) |
          ((buf[i++]! & 0x3f) << 6) |
          (buf[i++]! & 0x3f)) -
        0x10000;
      out += String.fromCharCode(0xd800 + (cp >> 10), 0xdc00 + (cp & 0x3ff));
    }
  }
  return out;
}

// --------------------------------------------------------------------------- //
// lector
// --------------------------------------------------------------------------- //

/**
 * Lector posicional sobre un `Uint8Array`.
 *
 * Invariante: `#pos <= #limit <= buf.length`. `#limit` es el final del
 * mensaje que se está leyendo AHORA (no el del buffer): así `eof` significa
 * "se acabó este mensaje", que es la condición del bucle de cada decoder.
 */
export class Reader {
  readonly #buf: Uint8Array;
  readonly #view: DataView;
  #pos: number;
  #limit: number;
  #depth = 0;

  constructor(buf: Uint8Array) {
    this.#buf = buf;
    this.#view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
    this.#pos = 0;
    this.#limit = buf.length;
  }

  /** Offset actual (para diagnósticos). */
  get pos(): number {
    return this.#pos;
  }

  /** ¿Se agotó el mensaje en curso? */
  get eof(): boolean {
    return this.#pos >= this.#limit;
  }

  fail(message: string): WireError {
    return new WireError(message, this.#pos);
  }

  #byte(): number {
    if (this.#pos >= this.#limit) {
      throw this.fail("los bytes terminaron a mitad de un campo");
    }
    return this.#buf[this.#pos++]!;
  }

  /**
   * Varint -> mitades de 32 bits (`lo` = bits 0-31, `hi` = bits 32-63).
   *
   * JS no tiene enteros de 64 bits nativos y `BigInt` por byte sería un
   * orden de magnitud más lento: se acumula en dos enteros de 32 bits y solo
   * los campos que REALMENTE son de 64 bits (`Literal.int_value`) pagan la
   * conversión a `BigInt`.
   */
  #varint(): { lo: number; hi: number } {
    let lo = 0;
    let hi = 0;
    for (let i = 0; i < 10; i++) {
      const b = this.#byte();
      if (i < 4) lo |= (b & 0x7f) << (7 * i);
      else if (i === 4) {
        lo |= (b & 0x0f) << 28; // bits 28-31
        hi |= (b & 0x7f) >>> 4; // bits 32-34
      } else hi |= (b & 0x7f) << (7 * i - 32);
      if ((b & 0x80) === 0) return { lo: lo >>> 0, hi: hi >>> 0 };
    }
    throw this.fail("varint de más de 10 bytes");
  }

  /** Campos `uint32` del esquema (`ln`, `col`, `schema_version`, tags). */
  readUint32(): number {
    return this.#varint().lo;
  }

  readBool(): boolean {
    const { lo, hi } = this.#varint();
    return (lo | hi) !== 0;
  }

  /** Enums de proto3: varint con signo, pero el esquema solo usa valores >= 0. */
  readEnum(): number {
    return this.#varint().lo;
  }

  /** Campos `int64` (`Literal.int_value`): complemento a dos de 64 bits. */
  readInt64(): bigint {
    const { lo, hi } = this.#varint();
    return BigInt.asIntN(64, (BigInt(hi) << 32n) | BigInt(lo));
  }

  /** Campos `double` (`Literal.float_value`): 8 bytes little-endian. */
  readDouble(): number {
    if (this.#pos + 8 > this.#limit) throw this.fail("double incompleto");
    const value = this.#view.getFloat64(this.#pos, true);
    this.#pos += 8;
    return value;
  }

  readString(): string {
    const length = this.readUint32();
    const end = this.#pos + length;
    if (end > this.#limit) throw this.fail("cadena más larga que el mensaje");
    const value = decodeUtf8(this.#buf, this.#pos, end);
    this.#pos = end;
    return value;
  }

  /** Vista (sin copia) sobre un campo `bytes`. */
  readBytes(): Uint8Array {
    const length = this.readUint32();
    const end = this.#pos + length;
    if (end > this.#limit) throw this.fail("bytes más largos que el mensaje");
    const value = this.#buf.subarray(this.#pos, end);
    this.#pos = end;
    return value;
  }

  /**
   * Como {@link readBytes}, pero SIN avanzar: la vista del campo delimitado
   * que viene a continuación. La usa el esquema 1 (`decode.ts`) para mirar
   * el retorno de una lambda antes de leer su cuerpo, que en el wire va
   * antes; el campo se lee después con {@link readMessage}, con el control
   * de profundidad de siempre.
   */
  peekBytes(): Uint8Array {
    const start = this.#pos;
    try {
      return this.readBytes();
    } finally {
      this.#pos = start;
    }
  }

  /**
   * Lee un mensaje anidado: acota `#limit` a su longitud, ejecuta `decode`
   * y restaura. `decode` puede dejar campos sin consumir (desconocidos que
   * ya saltó, o basura al final): el cursor se reposiciona al final exacto
   * del submensaje pase lo que pase.
   */
  readMessage<T>(decode: (r: Reader) => T): T {
    const length = this.readUint32();
    const end = this.#pos + length;
    if (end > this.#limit) throw this.fail("submensaje más largo que su padre");
    if (++this.#depth > MAX_NESTING_DEPTH) {
      this.#depth--;
      throw this.fail(
        `HIR con más de ${MAX_NESTING_DEPTH} niveles de anidamiento: se rechaza ` +
          "en vez de desbordar la pila",
      );
    }
    const savedLimit = this.#limit;
    this.#limit = end;
    try {
      return decode(this);
    } finally {
      this.#depth--;
      this.#pos = end;
      this.#limit = savedLimit;
    }
  }

  /**
   * Salta un campo cuyo número no conocemos (esquema más nuevo) o cuyo tipo
   * de wire no es el esperado. Es lo que hace que un `.phir` con campos
   * añadidos en una v2 compatible siga leyéndose: se ignora lo que sobra,
   * nunca se malinterpreta.
   */
  skip(tag: number): void {
    switch (tag & 7) {
      case WireType.VARINT:
        this.#varint();
        return;
      case WireType.I64:
        if (this.#pos + 8 > this.#limit) throw this.fail("campo de 64 bits incompleto");
        this.#pos += 8;
        return;
      case WireType.LEN: {
        const length = this.readUint32();
        if (this.#pos + length > this.#limit) {
          throw this.fail("campo delimitado más largo que el mensaje");
        }
        this.#pos += length;
        return;
      }
      case WireType.I32:
        if (this.#pos + 4 > this.#limit) throw this.fail("campo de 32 bits incompleto");
        this.#pos += 4;
        return;
      default:
        throw this.fail(`tipo de wire ${tag & 7} no válido en proto3`);
    }
  }
}
