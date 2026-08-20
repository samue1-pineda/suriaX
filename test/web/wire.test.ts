/** Pruebas del lector de wire-format: el suelo sobre el que todo lo demás se apoya. */

import test from "node:test";
import assert from "node:assert/strict";

import { MAX_NESTING_DEPTH, Reader, WireError, decodeUtf8 } from "../../web/src/hir/wire.ts";
import { Writer } from "./helpers.ts";

test("varint: 1 byte, multibyte y el límite de 32 bits", () => {
  const w = new Writer();
  w.uint32(1, 0);
  w.uint32(2, 127);
  w.uint32(3, 128);
  w.uint32(4, 300);
  w.uint32(5, 0xffffffff);
  const r = new Reader(w.finish());
  const read = (): number => {
    r.readUint32(); // tag
    return r.readUint32();
  };
  assert.equal(read(), 0);
  assert.equal(read(), 127);
  assert.equal(read(), 128);
  assert.equal(read(), 300);
  assert.equal(read(), 0xffffffff);
  assert.ok(r.eof);
});

test("int64: positivos, negativos y los extremos de 64 bits", () => {
  const values = [0n, 1n, -1n, 42n, -42n, 9007199254740993n,
                  9223372036854775807n, -9223372036854775808n];
  const w = new Writer();
  for (const v of values) w.int64(1, v);
  const r = new Reader(w.finish());
  for (const v of values) {
    r.readUint32();
    assert.equal(r.readInt64(), v, `int64 ${v}`);
  }
});

test("double: little-endian, incluidos los valores especiales", () => {
  const values = [0, 1, -1, 3.14159, 1e308, -0.5];
  const w = new Writer();
  for (const v of values) w.double(1, v);
  const r = new Reader(w.finish());
  for (const v of values) {
    r.readUint32();
    assert.equal(r.readDouble(), v);
  }
});

test("cadenas: ASCII, multibyte y fuera del BMP", () => {
  const values = ["", "hola", "añoñü", "日本語のテキスト", "emoji 🚀 al final",
                  "una cadena bastante larga para forzar el decodificador nativo"];
  const w = new Writer();
  for (const v of values) w.string(1, v);
  const r = new Reader(w.finish());
  for (const v of values) {
    r.readUint32();
    assert.equal(r.readString(), v);
  }
});

test("decodeUtf8 sobre una porción del buffer", () => {
  const w = new Writer();
  w.string(1, "abc");
  const bytes = w.finish();
  // salta tag + longitud: quedan los 3 bytes de la cadena.
  assert.equal(decodeUtf8(bytes, 2, 5), "abc");
  assert.equal(decodeUtf8(bytes, 2, 2), "");
});

test("los campos desconocidos se saltan, no rompen", () => {
  const w = new Writer();
  w.uint32(1, 7);
  w.string(400, "campo de una versión futura");
  w.double(401, 1.5);
  w.uint32(402, 9);
  w.message(403, (m) => m.string(1, "anidado"));
  w.string(2, "el que sí interesa");
  const r = new Reader(w.finish());
  let known = 0;
  let last = "";
  while (!r.eof) {
    const tag = r.readUint32();
    if (tag === 8) known = r.readUint32();
    else if (tag === 18) last = r.readString();
    else r.skip(tag);
  }
  assert.equal(known, 7);
  assert.equal(last, "el que sí interesa");
});

test("submensaje: acota el límite y restaura la posición", () => {
  const w = new Writer();
  w.message(1, (m) => {
    m.string(1, "dentro");
    m.uint32(2, 5);
  });
  w.string(2, "fuera");
  const r = new Reader(w.finish());
  assert.equal(r.readUint32(), 10);
  const inner = r.readMessage((sub) => {
    sub.readUint32();
    const value = sub.readString();
    assert.ok(!sub.eof, "el submensaje aún tiene campos");
    return value;
  });
  assert.equal(inner, "dentro");
  assert.equal(r.readUint32(), 18);
  assert.equal(r.readString(), "fuera");
  assert.ok(r.eof);
});

test("bytes truncados: WireError con offset, nunca un valor inventado", () => {
  const w = new Writer();
  w.string(1, "cadena completa");
  const truncated = w.finish().subarray(0, 6);
  const r = new Reader(truncated);
  assert.throws(() => {
    r.readUint32();
    r.readString();
  }, WireError);
});

test("un submensaje más largo que su padre se rechaza", () => {
  // tag 10 (campo 1, LEN) con longitud 99 pero sin contenido.
  const r = new Reader(new Uint8Array([10, 99, 1, 2, 3]));
  assert.throws(() => {
    r.readUint32();
    r.readMessage(() => null);
  }, WireError);
});

test("anidamiento excesivo: se rechaza en vez de desbordar la pila", () => {
  // Cadena de submensajes de campo 1, más profunda que el tope.
  const depth = MAX_NESTING_DEPTH + 5;
  let inner = new Writer().finish();
  for (let i = 0; i < depth; i++) {
    inner = new Writer().raw(1, inner).finish();
  }
  const r = new Reader(inner);
  const recurse = (reader: Reader): void => {
    while (!reader.eof) {
      const tag = reader.readUint32();
      if (tag === 10) reader.readMessage(recurse);
      else reader.skip(tag);
    }
  };
  assert.throws(() => {
    const tag = r.readUint32();
    assert.equal(tag, 10);
    r.readMessage(recurse);
  }, /anidamiento/);
});

test("un tipo de wire inválido se rechaza", () => {
  const r = new Reader(new Uint8Array([0x0b])); // campo 1, wire 3 (grupo)
  assert.throws(() => r.skip(r.readUint32()), WireError);
});
