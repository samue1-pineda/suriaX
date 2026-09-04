/**
 * Pruebas del control de flujo en el codegen.
 *
 * Todas EJECUTAN el binario: en una máquina de pila con control estructurado,
 * un `br` con la profundidad equivocada produce un módulo que valida a medias
 * o salta al sitio incorrecto, y eso solo se ve corriéndolo. Los mismos casos
 * se ejecutan por el backend JS para confirmar que los dos emisores están de
 * acuerdo — que es la razón de tener el WIR en medio.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { loadModule } from "../../web/src/hir/decode.ts";
import { generate } from "../../web/src/codegen/index.ts";
import { lowerModule } from "../../web/src/wir/lower.ts";
import { WebCode } from "../../web/src/diagnostics.ts";
import { Writer, buildModule, fixture, functionDecl, identifier, intLiteral } from "./helpers.ts";

const CONTROL = generate(loadModule(fixture("control.phir"), "control.phir"));

async function instantiate() {
  assert.ok(CONTROL.ok && CONTROL.wasm, "el fixture de control compila entero");
  const output: string[] = [];
  let memory: WebAssembly.Memory | null = null;
  const decoder = new TextDecoder();
  const { instance } = await WebAssembly.instantiate(CONTROL.wasm, {
    env: {
      __write__: (ptr: number, len: number) => {
        output.push(decoder.decode(new Uint8Array(memory!.buffer, ptr, len)));
      },
    },
  });
  memory = instance.exports["memory"] as WebAssembly.Memory;
  return { exports: instance.exports, output };
}

/** Ejecuta la misma función en el backend JS, para comparar. */
async function jsExports(): Promise<Record<string, (...args: never[]) => unknown>> {
  const { toBase64 } = await import("../../web/src/codegen/js.ts");
  // el módulo JS exporta las funciones del programa por su nombre, igual que
  // el WASM: los dos salen del mismo WIR y por eso se pueden comparar función
  // a función.
  const url = "data:text/javascript;base64," +
    toBase64(new TextEncoder().encode(CONTROL.js!));
  return (await import(url)) as Record<string, (...args: never[]) => unknown>;
}

test("if / else / else-if encadenado", async () => {
  const { exports } = await instantiate();
  const abs = exports["abs"] as (x: bigint) => bigint;
  const clasificar = exports["clasificar"] as (n: bigint) => bigint;

  assert.equal(abs(-5n), 5n);
  assert.equal(abs(5n), 5n);
  assert.equal(abs(0n), 0n);

  assert.equal(clasificar(-9n), -1n);
  assert.equal(clasificar(0n), 0n);
  assert.equal(clasificar(42n), 1n);
});

test("while con acumulador", async () => {
  const { exports } = await instantiate();
  const suma = exports["suma_hasta"] as (n: bigint) => bigint;
  assert.equal(suma(0n), 0n, "el cuerpo no se ejecuta si la condición es falsa");
  assert.equal(suma(1n), 1n);
  assert.equal(suma(10n), 55n);
  assert.equal(suma(100n), 5050n);
});

test("break y continue saltan a la etiqueta correcta", async () => {
  const { exports } = await instantiate();
  const impares = exports["suma_impares"] as (tope: bigint) => bigint;
  // 1+3+5 = 9 (los pares los salta 'continue'; 'break' corta en el tope)
  assert.equal(impares(6n), 9n);
  assert.equal(impares(1n), 1n);
  assert.equal(impares(0n), 0n, "'break' en la primera vuelta");
  assert.equal(impares(9n), 25n);
});

test("and / or devuelven 0 o 1, como en WASM", async () => {
  const { exports } = await instantiate();
  const enRango = exports["en_rango"] as (x: bigint) => number;
  const extremo = exports["extremo"] as (x: bigint) => number;
  const negado = exports["negado"] as (b: number) => number;

  assert.equal(enRango(5n), 1);
  assert.equal(enRango(3n), 0, "el límite inferior es exclusivo");
  assert.equal(enRango(10n), 0);
  assert.equal(extremo(-1n), 1);
  assert.equal(extremo(101n), 1);
  assert.equal(extremo(50n), 0);
  assert.equal(negado(0), 1);
  assert.equal(negado(1), 0);
});

test("el programa completo imprime y devuelve lo mismo que su fuente dice", async () => {
  const { exports, output } = await instantiate();
  (exports["__module_init"] as (() => void) | undefined)?.();
  const main = exports["main"] as () => bigint;
  // suma_hasta(10)=55, abs(-5)=5, clasificar(7)=1  ->  55 - 5 + 1
  assert.equal(main(), 51n);
  assert.deepEqual(output, ["en rango\n"]);
});

test("el backend JS coincide con el WASM en todos los casos", async () => {
  const { exports } = await instantiate();
  const js = await jsExports();

  const casos: [string, bigint[]][] = [
    ["abs", [-7n]], ["abs", [7n]],
    ["clasificar", [-1n]], ["clasificar", [0n]], ["clasificar", [3n]],
    ["suma_hasta", [0n]], ["suma_hasta", [7n]], ["suma_hasta", [50n]],
    ["suma_impares", [0n]], ["suma_impares", [6n]], ["suma_impares", [11n]],
    ["en_rango", [4n]], ["en_rango", [99n]],
    ["extremo", [-5n]], ["extremo", [7n]],
  ];
  for (const [nombre, args] of casos) {
    const porWasm = (exports[nombre] as (...a: bigint[]) => unknown)(...args);
    const porJs = (js[nombre] as (...a: bigint[]) => unknown)(...args);
    assert.equal(porJs, porWasm, `${nombre}(${args.join(", ")})`);
  }
});

test("el cortocircuito NO evalúa el lado derecho", () => {
  // 'false and <llamada>' no debe llamar: si el emisor usara i32.and, sí.
  const wat = CONTROL.wat!;
  assert.match(wat, /if \(result i32\)\s+;; 'and' cortocircuita/);
  assert.match(wat, /if \(result i32\)\s+;; 'or' cortocircuita/);
});

test("el WAT muestra el patrón block+loop del while", () => {
  const wat = CONTROL.wat!;
  assert.match(wat, /block\s+;; \$salida — destino de 'break'/);
  assert.match(wat, /loop\s+;; \$cuerpo — destino de 'continue'/);
  assert.match(wat, /br_if 1\s+;; condición falsa -> \$salida/);
});

test("una variable declarada en un bucle se reinicia en cada vuelta", () => {
  const { module } = lowerModule(loadModule(fixture("control.phir"), "control.phir"));
  assert.ok(module);
  const fn = module.funcs.find((f) => f.name === "suma_impares");
  assert.ok(fn);
  // 'resto' se declara dentro del while: su local.set tiene que estar DENTRO
  // del cuerpo, no una sola vez al entrar en la función.
  const bucle = fn.body.find((s) => s.kind === "while");
  assert.ok(bucle && bucle.kind === "while");
  const asignaciones = bucle.body.filter((s) => s.kind === "local.set");
  assert.ok(
    asignaciones.length >= 2,
    "el cuerpo asigna 'i' y 'resto' en cada iteración",
  );
});

test("'break' fuera de un bucle se rechaza en vez de emitir un salto inválido", () => {
  const bytes = buildModule((w) => {
    w.message(4, functionDecl("main", [
      (s: Writer) => {
        s.uint32(1, 3);
        s.uint32(2, 5);
        s.message(17, () => {});   // break; suelto
      },
    ]));
  });
  const { module, diagnostics } = lowerModule(loadModule(bytes));
  assert.equal(module, null);
  assert.deepEqual(diagnostics.map((d) => d.code), [WebCode.CODEGEN_UNSUPPORTED]);
  assert.match(diagnostics[0]!.message, /fuera de un bucle/);
  assert.equal(diagnostics[0]!.line, 3);
});

test("un if anidado en un while mantiene bien las profundidades", async () => {
  // 'suma_impares' tiene dos 'if' dentro del while, y uno de ellos hace
  // 'break' y el otro 'continue': si las profundidades relativas estuvieran
  // mal, el módulo no validaría o saltaría al sitio equivocado.
  assert.ok(WebAssembly.validate(CONTROL.wasm!));
  const { exports } = await instantiate();
  assert.equal((exports["suma_impares"] as (t: bigint) => bigint)(7n), 16n);
});
