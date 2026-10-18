/**
 * Lambdas (`LambdaExpr`, campo 27 del `oneof` de `Expr`) y `print(x)` de un
 * primitivo, en el target web.
 *
 * - Una lambda se LEE (su firma, su cuerpo y lo que captura) y se RECHAZA
 *   siempre con `WEB104`, sea cual sea la política: el codegen no sabe
 *   traducirla. Antes de que el lector la conociera llegaba como un nodo sin
 *   variante (`WEB901`, "el .phir está corrupto"), que no decía qué pasaba.
 * - `print(5)` (decisión del mantenedor: `print` escribe un primitivo en todas
 *   partes) el web ya lo traducía como sus `print` del host: aquí se fija que
 *   escribe lo mismo que el intérprete.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { WebCode } from "../../web/src/diagnostics.ts";
import { loadModule } from "../../web/src/hir/decode.ts";
import { encodeModule } from "../../web/src/hir/encode.ts";
import { linkImage } from "../../web/src/hir/link.ts";
import { compile } from "../../web/src/index.ts";
import { toBase64 } from "../../web/src/codegen/js.ts";
import {
  PLAYGROUND_POLICY,
  UNRESTRICTED_POLICY,
  WEB_V1_POLICY,
} from "../../web/src/target/policy.ts";
import { checkImage } from "../../web/src/target/restrictions.ts";
import { fixture, fixturePath, fixtureResolver } from "./helpers.ts";

const LAMBDA_MESSAGE =
  "una lambda (una función sin nombre que lee su entorno): el target web " +
  "todavía no las ejecuta; ejecútalo con el intérprete (python V0/main.py " +
  "<fuente>.srcx --run interpreter)";

function lambdaOfMain() {
  const module = loadModule(fixture("lambdas.phir"), "lambdas.phir");
  const main = module.items.find(
    (d) => d.node.case === "function" && d.node.fn.name === "main");
  assert.ok(main !== undefined && main.node.case === "function");
  const ret = main.node.fn.body!.statements[1]!;
  assert.ok(ret.node.case === "return" && ret.node.value !== null);
  const call = ret.node.value.node;
  assert.ok(call.case === "call");
  return { module, lambda: call.args[0]! };
}

test("the reader understands a lambda: signature, body and captures", () => {
  const { lambda } = lambdaOfMain();
  const node = lambda.node;
  assert.equal(node.case, "lambdaExpr");
  assert.ok(node.case === "lambdaExpr");
  assert.deepEqual(node.params.map((p) => [p.name, p.type?.kind]), [["x", 3]]);
  assert.equal(node.returnType?.kind, 3);       // int
  assert.deepEqual(node.captures, ["k"]);
  // la forma corta llega como '{ return x * k; }'
  assert.equal(node.body?.statements.length, 1);
  assert.equal(node.body?.statements[0]!.node.case, "return");
  assert.equal([lambda.ln, lambda.col].join(":"), "9:18");
});

test("a lambda is rejected with WEB104 at its position, not WEB901", () => {
  const image = linkImage(fixture("lambdas.phir"), fixturePath("lambdas.phir"),
                          fixtureResolver);
  const report = checkImage(image, WEB_V1_POLICY);
  assert.ok(!report.ok);
  // el parámetro 'f' de 'apply' es una función como valor (WEB103); la
  // lambda, WEB104 y nada más en su línea
  assert.deepEqual(
    report.diagnostics.map((d) => [d.code, d.line, d.column]),
    [[WebCode.FUNCTION_VALUE, 5, 1], [WebCode.LAMBDA, 9, 18]],
  );
  assert.equal(report.diagnostics[1]!.message, LAMBDA_MESSAGE);
  assert.equal(report.denied.size, 0);
});

test("WEB104 does not depend on the policy: not even unrestricted lets a lambda through", () => {
  const image = linkImage(fixture("lambdas.phir"), fixturePath("lambdas.phir"),
                          fixtureResolver);
  for (const policy of [UNRESTRICTED_POLICY, PLAYGROUND_POLICY]) {
    const report = checkImage(image, policy);
    assert.ok(!report.ok, policy.name);
    assert.ok(report.diagnostics.some((d) => d.code === WebCode.LAMBDA), policy.name);
    assert.ok(!report.diagnostics.some((d) => d.code === WebCode.MALFORMED_NODE),
              policy.name);
  }
});

test("re-encoding a lambda keeps its signature, body and captures", () => {
  const { module } = lambdaOfMain();
  const again = loadModule(encodeModule(module), "lambdas.phir");
  const main = again.items.find(
    (d) => d.node.case === "function" && d.node.fn.name === "main");
  assert.ok(main !== undefined && main.node.case === "function");
  const ret = main.node.fn.body!.statements[1]!;
  assert.ok(ret.node.case === "return" && ret.node.value !== null);
  const call = ret.node.value.node;
  assert.ok(call.case === "call");
  const node = call.args[0]!.node;
  assert.ok(node.case === "lambdaExpr");
  assert.deepEqual(node.captures, ["k"]);
  assert.deepEqual(node.params.map((p) => p.name), ["x"]);
  assert.equal(node.body?.statements.length, 1);
});

test("print(x) of a primitive writes what the interpreter writes", async () => {
  const result = compile(fixture("primitive_print.phir"),
                         fixturePath("primitive_print.phir"), fixtureResolver);
  assert.deepEqual(result.diagnostics, []);
  for (const source of [result.codegen?.js, result.codegen?.host]) {
    assert.ok(source);
    const output: string[] = [];
    const url = "data:text/javascript;base64," + toBase64(new TextEncoder().encode(source));
    const module = (await import(url)) as {
      run: (io: { write: (text: string) => void }) => unknown | Promise<unknown>;
    };
    await module.run({ write: (text: string) => output.push(text) });
    assert.equal(output.join(""), "7 2.5 true z");
  }
});
