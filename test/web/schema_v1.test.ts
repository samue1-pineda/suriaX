/**
 * El ROLLBACK al esquema 1 del HIR, en el lector web.
 *
 * El esquema está versionado: el 1 (cada tipo inline, sin pool) tiene que
 * seguir funcionando junto al 2 (pool de tipos). Lo que se prueba es que el
 * decodificador lleva un `.phir` v1 a EXACTAMENTE el mismo módulo que su v2 —
 * así nada de lo que viene después (contención, DCE, WIR, codegen) sabe cuál
 * llegó— y que lo que no es un v1 limpio se rechaza.
 *
 * Fixtures (bytes REALES del compilador, ver la cabecera de `rollback.srcx`):
 *   - `rollback.phir` / `rollback_v1.phir`: cada campo de tipo que cambió
 *     entre los dos esquemas (expresión, variable, parámetro, retorno de
 *     función, campo de struct, retorno de lambda, payload de enum);
 *   - `calc.phir` / `calc_v1.phir`: un programa que el target web SÍ compila,
 *     para comparar el WASM. `calc_v1.phir` se regenera desde esta carpeta
 *     emitiendo a OTRA (para no pisar los `IO*.phir`, que siguen en el 2):
 *       python ../../../V0/main.py calc.srcx --emit-hir <tmp>/calc_v1.phir --hir-schema 1
 *     y copiando solo `calc_v1.phir` aquí.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { HIRLoadError, decodeModule, loadModule } from "../../web/src/hir/decode.ts";
import { encodeModule } from "../../web/src/hir/encode.ts";
import { compile } from "../../web/src/index.ts";
import { Reader } from "../../web/src/hir/wire.ts";
import { TypeKind, formatType, type Module } from "../../web/src/hir/schema.ts";
import { buildModule, fixture, fixturePath, fixtureResolver, Writer } from "./helpers.ts";

/** El módulo como valor comparable (Map ordenado, bigint como texto). */
function plain(module: Module): unknown {
  return JSON.parse(JSON.stringify(module, (_key, value) => {
    if (value instanceof Map) return Object.fromEntries([...value.entries()].sort());
    if (typeof value === "bigint") return `${value}n`;
    return value;
  }));
}

/** Los mismos datos, ignorando la versión que se leyó. */
function sinVersion(module: Module): unknown {
  return plain({ ...module, schemaVersion: 0 });
}

/** ¿Lleva el `Module` su campo 6 (el pool de tipos)? Se mira el wire crudo. */
function llevaPool(bytes: Uint8Array): boolean {
  const r = new Reader(bytes);
  while (!r.eof) {
    const tag = r.readUint32();
    if (tag === 50) return true;
    r.skip(tag);
  }
  return false;
}

for (const [v2, v1] of [["rollback.phir", "rollback_v1.phir"], ["calc.phir", "calc_v1.phir"]]) {
  test(`esquema 1: '${v1}' decodifica al MISMO módulo que '${v2}'`, () => {
    const nuevo = loadModule(fixture(v2), v2);
    const viejo = loadModule(fixture(v1), v1);
    assert.equal(nuevo.schemaVersion, 2);
    assert.equal(viejo.schemaVersion, 1);
    assert.deepEqual(sinVersion(viejo), sinVersion(nuevo));
  });

  test(`esquema 1: '${v1}' no lleva pool de tipos y '${v2}' sí`, () => {
    assert.equal(llevaPool(fixture(v1)), false);
    assert.equal(llevaPool(fixture(v2)), true);
  });
}

test("esquema 1: cada campo de tipo inline llega resuelto (no se pierde ninguno)", () => {
  const module = loadModule(fixture("rollback_v1.phir"), "rollback_v1.phir");
  const decl = (name: string) => module.items.find(
    (d) => (d.node.case === "function" && d.node.fn.name === name) ||
      (d.node.case === "struct" && d.node.struct.name === name) ||
      (d.node.case === "enum" && d.node.enumDecl.name === name));

  // campo de struct
  const punto = decl("Punto");
  assert.ok(punto?.node.case === "struct");
  assert.deepEqual(punto.node.struct.fields.map((f) => formatType(f.type)), ["int", "int"]);

  // payload de enum: los índices son los que daría el pool del esquema 2
  const forma = decl("Forma");
  assert.ok(forma?.node.case === "enum");
  assert.deepEqual(forma.node.enumDecl.items.map((i) => i.payloadTypeIds.length), [0, 1, 2]);

  // parámetro (de tipo función) y retorno de función
  const aplicar = decl("aplicar");
  assert.ok(aplicar?.node.case === "function");
  assert.equal(aplicar.node.fn.params[0]?.type?.kind, TypeKind.FUNCTION_TYPE);
  assert.equal(formatType(aplicar.node.fn.returnType), "int");

  // variable, expresión y retorno de lambda (dentro de 'main')
  const main = decl("main");
  assert.ok(main?.node.case === "function");
  const stmts = main.node.fn.body?.statements ?? [];
  const r = stmts.find((s) => s.node.case === "varDecl" && s.node.name === "r");
  assert.ok(r?.node.case === "varDecl");
  assert.equal(formatType(r.node.type), "int");
  assert.ok(r.node.value?.node.case === "call");
  assert.equal(formatType(r.node.value.restype), "int");
  const lambda = r.node.value.node.args[0];
  assert.ok(lambda?.node.case === "lambdaExpr");
  assert.equal(formatType(lambda.node.returnType), "int");
});

test("esquema 1: el mismo programa compila al MISMO WASM que en el 2", () => {
  const nuevo = compile(fixture("calc.phir"), fixturePath("calc.phir"), fixtureResolver);
  const viejo = compile(fixture("calc_v1.phir"), fixturePath("calc_v1.phir"), fixtureResolver);
  assert.ok(nuevo.codegen?.wasm && viejo.codegen?.wasm);
  assert.deepEqual([...viejo.codegen.wasm], [...nuevo.codegen.wasm]);
});

test("esquema 1: re-escribirlo da un .phir del 2 equivalente", () => {
  const viejo = loadModule(fixture("rollback_v1.phir"), "rollback_v1.phir");
  const bytes = encodeModule(viejo);
  assert.equal(llevaPool(bytes), true);
  const otra = loadModule(bytes, "reescrito.phir");
  assert.equal(otra.schemaVersion, 2, "el escritor produce SIEMPRE el esquema 2");
  assert.deepEqual(sinVersion(otra), sinVersion(viejo));
});

test("esquema 1 con pool de tipos: se rechaza (mezcla los dos esquemas)", () => {
  // buildModule escribe SIEMPRE el pool: con versión 1 es un archivo mezclado
  const bytes = buildModule((w) => w.message(4, (d) => d.uint32(1, 1)), 1);
  assert.throws(() => loadModule(bytes, "mezcla.phir"), (exc: unknown) => {
    assert.ok(exc instanceof HIRLoadError);
    assert.match(exc.message, /mezcla los dos esquemas/);
    return true;
  });
});

test("esquema 1 con un índice de tipo: se rechaza (mezcla los dos esquemas)", () => {
  const w = new Writer();
  w.uint32(1, 1);
  w.message(4, (d) => {
    d.uint32(1, 1);
    d.message(14, (stmt) => stmt.message(21, (es) => es.message(1, (e) => {
      e.uint32(4, 3); // Expr.type_id: propio del esquema 2
      e.message(12, (id) => id.string(1, "x"));
    })));
  });
  assert.throws(() => decodeModule(w.finish()), (exc: unknown) => {
    assert.ok(exc instanceof HIRLoadError);
    assert.match(exc.message, /mezcla los dos esquemas/);
    return true;
  });
});

for (const version of [0, 3]) {
  test(`schema_version ${version}: se sigue rechazando`, () => {
    const bytes = buildModule((w) => w.message(4, (d) => d.uint32(1, 1)), version);
    assert.throws(() => loadModule(bytes, "otro.phir"), (exc: unknown) => {
      assert.ok(exc instanceof HIRLoadError);
      assert.match(exc.message, new RegExp(`schema_version ${version} no soportada`));
      assert.match(exc.message, /soportadas: 1, 2/);
      return true;
    });
  });
}
