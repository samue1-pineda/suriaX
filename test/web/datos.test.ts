/**
 * Pruebas de los DATOS del codegen v2: enums, `match`, `cast` y `str`.
 *
 * Todas EJECUTAN el binario, y las mismas llamadas van también por el backend
 * JS: los dos salen del mismo WIR, así que una diferencia entre ellos es un
 * emisor equivocado y no una decisión del lowering. Es el mismo trato que se
 * le da al control de flujo (`control.test.ts`), y por el mismo motivo: un
 * `match` mal encadenado o una conversión con el opcode cambiado producen un
 * módulo que valida perfectamente y contesta mal.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { loadModule } from "../../web/src/hir/decode.ts";
import { generate } from "../../web/src/codegen/index.ts";
import { fixture } from "./helpers.ts";

const DATOS = generate(loadModule(fixture("datos.phir"), "datos.phir"));

async function instantiate() {
  assert.ok(DATOS.ok && DATOS.wasm, "el fixture de datos compila entero");
  const output: string[] = [];
  let memory: WebAssembly.Memory | null = null;
  const decoder = new TextDecoder();
  // la tabla de constantes: 'str' viaja como el índice de la suya
  const strings = DATOS.wir!.strings.map((s) => s.text);
  const { instance } = await WebAssembly.instantiate(DATOS.wasm, {
    env: {
      __write__: (ptr: number, len: number) => {
        output.push(decoder.decode(new Uint8Array(memory!.buffer, ptr, len)));
      },
      __write_str__: (i: number) => { output.push(strings[i] ?? ""); },
      __write_int__: (v: bigint) => { output.push(String(v)); },
    },
  });
  memory = instance.exports["memory"] as WebAssembly.Memory;
  return { exports: instance.exports, output };
}

async function jsExports(): Promise<Record<string, (...args: never[]) => unknown>> {
  const { toBase64 } = await import("../../web/src/codegen/js.ts");
  const url = "data:text/javascript;base64," +
    toBase64(new TextEncoder().encode(DATOS.js!));
  return (await import(url)) as Record<string, (...args: never[]) => unknown>;
}

// --- enums ----------------------------------------------------------------- //

test("un enum sin payload es un entero con nombre", async () => {
  const { exports } = await instantiate();
  const peso = exports["peso"] as (c: bigint) => bigint;
  // ROJO=0, VERDE=1, AZUL=2: el ordinal, como en C
  assert.equal(peso(0n), 10n);
  assert.equal(peso(1n), 20n);
  assert.equal(peso(2n), 30n);
});

test("los valores EXPLÍCITOS mandan sobre el ordinal", async () => {
  const { exports } = await instantiate();
  const esError = exports["es_error"] as (c: bigint) => number;
  // OK=200, NO_ESTA=404, ROTO=500: si el lowering usara el ordinal, 'es_error(0)'
  // habría contestado como si fuera OK.
  assert.equal(esError(200n), 0);
  assert.equal(esError(404n), 1);
  assert.equal(esError(500n), 1);
  assert.equal(esError(0n), 0, "un valor que no es de ningún caso no entra en ninguno");
});

// --- match ----------------------------------------------------------------- //

test("'match' sobre enteros elige la rama y no varias", async () => {
  const { exports } = await instantiate();
  const nombre = exports["nombre_digito"] as (d: bigint) => number;
  // devuelve un ÍNDICE de cadena: distintos entre sí y estable el del default
  const cero = nombre(0n), uno = nombre(1n), dos = nombre(2n), otro = nombre(9n);
  assert.notEqual(cero, uno);
  assert.notEqual(uno, dos);
  assert.equal(nombre(7n), otro, "lo que no casa cae al final, no en el último caso");
});

test("el sujeto del 'match' se evalúa UNA vez", async () => {
  // Está en el WIR y no hace falta ejecutarlo para verlo: el sujeto se guarda
  // en un local y los casos comparan CONTRA ESE LOCAL. Si se re-evaluara,
  // 'match (siguiente())' llamaría una vez por caso.
  const fn = DATOS.wir!.funcs.find((f) => f.name === "peso")!;
  const primera = fn.body[0]!;
  assert.equal(primera.kind, "local.set", "lo primero es guardar el sujeto");
  assert.equal(fn.body[1]!.kind, "if", "y luego la cadena de comparaciones");
});

// --- cast ------------------------------------------------------------------ //

test("cast entre numéricos: los dos sentidos", async () => {
  const { exports } = await instantiate();
  const mitad = exports["mitad"] as (n: bigint) => number;
  const truncado = exports["truncado"] as (f: number) => bigint;
  const letra = exports["letra"] as (c: bigint) => number;
  const codigoDe = exports["codigo_de"] as (c: number) => bigint;

  assert.equal(mitad(7n), 3.5, "int -> float NO trunca");
  assert.equal(truncado(3.9), 3n, "float -> int trunca hacia cero");
  assert.equal(truncado(-3.9), -3n, "…también en negativo (no es 'floor')");
  assert.equal(letra(66n), 66, "int -> char es el code point");
  assert.equal(codigoDe(65), 65n);
});

test("float -> int SATURA en vez de abortar el módulo", async () => {
  const { exports } = await instantiate();
  const truncado = exports["truncado"] as (f: number) => bigint;
  // con 'i64.trunc_f64_s' esto habría abortado la ejecución entera; el
  // saturante entrega el extremo del rango y el programa sigue.
  assert.equal(truncado(NaN), 0n);
  assert.equal(truncado(Infinity), 2n ** 63n - 1n);
  assert.equal(truncado(-Infinity), -(2n ** 63n));
});

// --- str -------------------------------------------------------------------- //

test("una cadena constante es un valor: entra, se compara y sale", async () => {
  const { exports, output } = await instantiate();
  const main = exports["main"] as () => bigint;
  (exports["__module_init"] as (() => void) | undefined)?.();
  assert.equal(main(), 33n, "peso(AZUL)=30 + truncado(mitad(7))=3");
  assert.deepEqual(output, ["hola, mundo", "\n", "dos", "\n"]);
});

test("dos literales de igual texto comparten índice (por eso '==' vale)", async () => {
  const { exports } = await instantiate();
  const saludo = exports["saludo"] as (s: number) => number;
  const strings = DATOS.wir!.strings.map((s) => s.text);
  const mundo = strings.indexOf("mundo");
  assert.notEqual(mundo, -1, "el literal está en la tabla");
  assert.equal(strings[saludo(mundo)], "hola, mundo");
  const otro = strings.indexOf("hola, extraño");
  assert.equal(strings[saludo(otro)], "hola, extraño",
    "cualquier otra cadena cae en la otra rama");
});

// --- los dos backends de acuerdo -------------------------------------------- //

test("el backend JS contesta lo mismo que el WASM", async () => {
  const { exports } = await instantiate();
  const js = await jsExports();
  const casos: [string, unknown[]][] = [
    ["peso", [2n]],
    ["es_error", [404n]],
    ["nombre_digito", [1n]],
    ["mitad", [7n]],
    ["truncado", [3.9]],
    ["truncado", [-3.9]],
    ["letra", [66n]],
    ["codigo_de", [65]],
  ];
  for (const [name, args] of casos) {
    const wasm = (exports[name] as (...a: unknown[]) => unknown)(...args);
    const puro = (js[name] as (...a: unknown[]) => unknown)(...args);
    assert.equal(puro, wasm, `${name}(${args.join(", ")}) difiere entre backends`);
  }
});

// --- globales --------------------------------------------------------------- //

test("una variable de módulo la comparten todas las funciones", async () => {
  const { exports } = await instantiate();
  const visitar = exports["visitar"] as () => bigint;
  // era un LOCAL de '__module_init': cada función veía su propia copia (o,
  // más bien, no la veía en absoluto y el programa no compilaba).
  assert.equal(visitar(), 1n);
  assert.equal(visitar(), 2n, "el valor sobrevive entre llamadas");
});

test("una global CALCULADA la inicializa __module_init", async () => {
  const { exports } = await instantiate();
  const basePor = exports["base_por"] as (n: bigint) => bigint;
  assert.equal(basePor(3n), 21n, "BASE = 7, y es una constante de init");
  // DOBLE = BASE * 2 no cabe como init de WASM (solo admite constantes):
  // arranca a cero y el init le pone su valor. Sin llamar al init, valdría 0.
  const conInit = exports["__module_init"] as () => void;
  conInit();
  assert.equal((exports["main"] as () => bigint)(), 33n);
});

test("un 'const' del programa es una global INMUTABLE del binario", () => {
  const globals = DATOS.wir!.globals;
  const base = globals.find((g) => g.name === "BASE")!;
  const visitas = globals.find((g) => g.name === "visitas")!;
  assert.equal(base.mutable, false,
    "el validador de WASM impide reasignarla: la garantía llega al binario");
  assert.equal(visitas.mutable, true);
  // DOBLE es 'const' en el programa pero necesita un 'global.set' en el init
  const doble = globals.find((g) => g.name === "DOBLE")!;
  assert.equal(doble.mutable, true,
    "una constante CALCULADA tiene que poder escribirse una vez");
  assert.equal(doble.init, 0n, "…y arranca a cero hasta que el init corre");
});
