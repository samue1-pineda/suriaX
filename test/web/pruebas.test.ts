/**
 * `test` con `expect`, `errfinally` y `finally` en el target web.
 *
 * El target NO corre pruebas: el DCE las quita y lo que se ejecuta es el
 * programa. Pero las tiene que LEER — un programa válido con una prueba salía
 * como "el .phir está corrupto" (`WEB901`) porque el lector no conocía
 * `expect` ni las dos cláusulas — y lo que hay dentro de una prueba es código
 * del programa: la contención lo revisa igual que el resto.
 *
 * Los fixtures son bytes reales, emitidos por el compilador Python
 * (`python V0/main.py pruebas.srcx --emit-hir pruebas.phir`).
 */

import test from "node:test";
import assert from "node:assert/strict";

import { WebCode } from "../../web/src/diagnostics.ts";
import { loadModule } from "../../web/src/hir/decode.ts";
import { encodeModule } from "../../web/src/hir/encode.ts";
import { testBlocks, type Decl, type Module, type TestDecl } from "../../web/src/hir/schema.ts";
import { compile } from "../../web/src/index.ts";
import { eliminateDeadCode } from "../../web/src/opt/dce.ts";
import { PLAYGROUND_POLICY, WEB_V1_POLICY } from "../../web/src/target/policy.ts";
import { checkModule } from "../../web/src/target/restrictions.ts";
import { fixture, fixturePath, fixtureResolver } from "./helpers.ts";

function prueba(module: Module): TestDecl {
  const decl = module.items.find((d: Decl) => d.node.case === "test");
  assert.ok(decl !== undefined && decl.node.case === "test", "sin 'test'");
  return decl.node.test;
}

const funciones = (module: Module): string[] =>
  module.items.flatMap((d: Decl) => (d.node.case === "function" ? [d.node.fn.name] : []));

test("una prueba se lee entera: sus 'expect' y sus dos cláusulas", () => {
  const module = loadModule(fixture("pruebas.phir"), "pruebas.phir");
  const t = prueba(module);
  assert.equal(t.name, "doble");
  assert.ok(t.body !== null && t.errfinally !== null && t.finallyBlock !== null);
  assert.equal(testBlocks(t).length, 3);

  const casos = t.body.statements.map((s) => s.node.case);
  assert.deepEqual(casos, ["varDecl", "varDecl", "expect", "expect"]);
  const [, , conBloque, sinBloque] = t.body.statements.map((s) => s.node);
  assert.ok(conBloque!.case === "expect" && sinBloque!.case === "expect");
  // el texto de la condición viaja tal cual: es lo que cita el fallo
  assert.equal(conBloque.text, "r == esperado");
  assert.equal(conBloque.condition.node.case, "binary");
  assert.ok(conBloque.body !== null && conBloque.body.statements.length === 1);
  // sin bloque es AUSENTE, no un bloque vacío
  assert.equal(sinBloque.body, null);
  assert.equal(sinBloque.text, "solo_en_pruebas(1) == 3");
});

test("ninguna sentencia de una prueba llega sin variante", () => {
  // Es lo que fallaba: el lector saltaba el tag de 'expect' y la sentencia
  // quedaba en 'none', que la contención reporta como .phir corrupto.
  const module = loadModule(fixture("pruebas.phir"), "pruebas.phir");
  const report = checkModule(module, WEB_V1_POLICY);
  assert.ok(!report.diagnostics.some((d) => d.code === WebCode.MALFORMED_NODE),
            report.diagnostics.map((d) => d.message).join("\n"));
  for (const parte of testBlocks(prueba(module))) {
    assert.ok(parte.statements.every((s) => s.node.case !== "none"));
  }
});

test("leer, escribir y volver a leer una prueba da lo mismo", () => {
  const antes = loadModule(fixture("pruebas.phir"), "pruebas.phir");
  const despues = loadModule(encodeModule(antes), "<reescrito>");
  assert.deepEqual(prueba(despues), prueba(antes));
  assert.deepEqual(despues.items, antes.items);
});

test("un programa con una prueba compila para el web, sin la prueba", () => {
  for (const policy of [WEB_V1_POLICY, PLAYGROUND_POLICY]) {
    const result = compile(fixture("pruebas.phir"), fixturePath("pruebas.phir"),
                           fixtureResolver, { policy });
    assert.deepEqual(result.diagnostics, [], policy.name);
    assert.ok(result.codegen !== null && result.codegen.ok, policy.name);
    // lo que se ejecuta es el programa: 'solo_en_pruebas' no viaja
    assert.deepEqual(result.codegen.wir!.funcs.map((f) => f.name), ["doble", "main"]);
  }
});

test("el DCE cuenta la prueba y lo que solo ella usaba", () => {
  const module = loadModule(fixture("pruebas.phir"), "pruebas.phir");
  const sin = eliminateDeadCode(module);
  assert.equal(sin.stats.tests, 1);
  assert.deepEqual(funciones(sin.module).sort(), ["doble", "main"]);

  // Conservando las pruebas, lo que usa un 'expect' está VIVO: 'doble' se
  // usa en el cuerpo y 'solo_en_pruebas' solo dentro de una condición.
  const con = eliminateDeadCode(module, { keepTests: true });
  assert.equal(con.stats.tests, 0);
  assert.deepEqual(funciones(con.module).sort(), ["doble", "main", "solo_en_pruebas"]);
  assert.equal(testBlocks(prueba(con.module)).length, 3);
  // ...y una variable que solo lee un 'expect' no es una variable muerta
  // ('esperado' tiene un inicializador puro: sin contar ese uso, se borraría)
  assert.equal(con.stats.deadVars, 0);
  assert.deepEqual(prueba(con.module).body!.statements.map((s) => s.node.case),
                   ["varDecl", "varDecl", "expect", "expect"]);
});

test("lo que el target no ejecuta tampoco vale dentro de una cláusula", () => {
  // Un puntero en el 'finally' de una prueba: la contención recorre las
  // cláusulas, no solo el cuerpo.
  const module = loadModule(fixture("pruebas_puntero.phir"), "pruebas_puntero.phir");
  const t = prueba(module);
  assert.ok(t.errfinally === null && t.finallyBlock !== null);
  const report = checkModule(module, PLAYGROUND_POLICY);
  assert.ok(!report.ok);
  const codigos = report.diagnostics.map((d) => d.code);
  // dos punteros: uno en el bloque de un 'expect' (línea 11) y otro en la
  // cláusula (línea 15). Cada uno da su tipo y su '&'.
  for (const code of [WebCode.POINTER_TYPE, WebCode.ADDRESS_OF]) {
    const lineas = report.diagnostics.filter((d) => d.code === code).map((d) => d.line);
    assert.deepEqual(lineas, [11, 15], code);
  }
  assert.ok(!codigos.includes(WebCode.MALFORMED_NODE), codigos.join(" "));
});
