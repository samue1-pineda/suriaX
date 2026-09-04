/**
 * Pruebas del codegen. No comprueban "el binario tiene tal byte": **ejecutan
 * lo generado**. Un emisor de WASM se puede equivocar de mil formas que un
 * `deepEqual` sobre bytes no distingue, y el propio motor de WebAssembly es
 * el mejor validador que hay: si el módulo está mal formado, no instancia.
 *
 * Y como los dos backends (WASM y JS) salen del MISMO WIR, cada programa se
 * ejecuta por los dos caminos y se comparan los resultados: es lo que
 * justifica que exista el puente.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { loadModule } from "../../web/src/hir/decode.ts";
import { compile } from "../../web/src/index.ts";
import { generate } from "../../web/src/codegen/index.ts";
import { emitJs, emitHostModule, toBase64 } from "../../web/src/codegen/js.ts";
import { emitWasm } from "../../web/src/codegen/wasm.ts";
import { emitWat } from "../../web/src/codegen/wat.ts";
import { lowerModule, MODULE_INIT } from "../../web/src/wir/lower.ts";
import { WirType } from "../../web/src/wir/wir.ts";
import { WebCode } from "../../web/src/diagnostics.ts";
import {
  Writer,
  buildModule,
  fixture,
  fixturePath,
  fixtureResolver,
  functionDecl,
  identifier,
  intLiteral,
  TYPE_EXTRA,
  TYPE_INT,
  TYPE_STR,
  TYPE_VOID,
} from "./helpers.ts";

/** Compila un fixture entero (contención + DCE + codegen). */
function compileFixture(name: string, optimize = true) {
  return compile(fixture(name), fixturePath(name), fixtureResolver, { optimize });
}

/** Instancia el WASM y devuelve exports + lo que el programa escribió. */
async function instantiate(wasm: Uint8Array) {
  const output: string[] = [];
  let memory: WebAssembly.Memory | null = null;
  const decoder = new TextDecoder();
  const { instance } = await WebAssembly.instantiate(wasm, {
    env: {
      __write__: (ptr: number, len: number) => {
        const buffer = memory!.buffer;
        output.push(decoder.decode(new Uint8Array(buffer, ptr, len)));
      },
    },
  });
  memory = instance.exports["memory"] as WebAssembly.Memory | undefined ?? null;
  return { exports: instance.exports, output };
}

/** Importa un módulo ES generado (JS puro o host del WASM) y lo ejecuta. */
async function runGenerated(source: string): Promise<{ result: unknown; output: string[] }> {
  const output: string[] = [];
  const url = "data:text/javascript;base64," + toBase64(new TextEncoder().encode(source));
  const module = (await import(url)) as {
    run: (io: { write: (text: string) => void }) => unknown | Promise<unknown>;
  };
  const result = await module.run({ write: (text: string) => output.push(text) });
  return { result, output };
}

// --------------------------------------------------------------------------- //
// lowering: HIR -> WIR
// --------------------------------------------------------------------------- //

test("el lowering resuelve nombres a índices y tipos a i64/f64/i32", () => {
  const { module } = lowerModule(loadModule(fixture("calc.phir"), "calc.phir"));
  assert.ok(module, "el fixture entero está dentro del subconjunto");

  const suma = module.funcs.find((f) => f.name === "suma");
  assert.ok(suma);
  assert.deepEqual(suma.params.map((p) => p.type), [WirType.I64, WirType.I64]);
  assert.equal(suma.result, WirType.I64);

  const area = module.funcs.find((f) => f.name === "area");
  assert.ok(area);
  assert.deepEqual(area.params.map((p) => p.type), [WirType.F64, WirType.F64]);

  const mayor = module.funcs.find((f) => f.name === "mayor");
  assert.equal(mayor?.result, WirType.I32, "bool viaja como i32");

  // las variables se numeran DESPUÉS de los parámetros, en un solo espacio.
  const main = module.funcs.find((f) => f.name === "main");
  assert.ok(main);
  assert.equal(main.params.length, 0);
  assert.deepEqual(main.locals.map((l) => l.name), ["a", "b", "total", "cociente"]);

  // la sentencia de nivel de módulo va a la función sintética.
  assert.ok(module.funcs.some((f) => f.name === MODULE_INIT));
  assert.equal(module.init, module.funcs.findIndex((f) => f.name === MODULE_INIT));
  assert.equal(module.entry, module.funcs.findIndex((f) => f.name === "main"));

  // la cadena del println vive en el data segment, con su salto de línea.
  assert.equal(module.strings.length, 1);
  assert.equal(module.strings[0]!.text, "suriaX en WebAssembly\n");
  assert.equal(module.dataSize, module.strings[0]!.bytes.length);
});

test("las cadenas repetidas comparten bytes", () => {
  const bytes = buildModule((w) => {
    const print = (text: string) => (s: Writer) => {
      s.uint32(1, 1);
      s.message(21, (st) => st.message(1, (e) => {
        e.uint32(1, 1);
        e.message(17, (call) => {
          call.message(1, (callee) => {
            callee.message(19, (m) => {
              m.message(1, identifier("stdp"));
              m.string(2, "println");
            });
          });
          call.message(2, (arg) => {
            arg.message(10, (lit) => {
              lit.string(1, "str");
              lit.string(4, text);
            });
          });
        });
      }));
    };
    w.message(4, functionDecl("main", [print("hola"), print("hola"), print("adiós")]));
  });
  const { module } = lowerModule(loadModule(bytes));
  assert.ok(module);
  assert.equal(module.strings.length, 2, "'hola' se interna una sola vez");
});

// --------------------------------------------------------------------------- //
// backend WASM
// --------------------------------------------------------------------------- //

test("el binario generado es un módulo WebAssembly válido", () => {
  const result = compileFixture("calc.phir");
  assert.ok(result.codegen?.wasm);
  assert.ok(WebAssembly.validate(result.codegen.wasm), "el motor lo valida");
  assert.deepEqual(
    [...result.codegen.wasm.subarray(0, 8)],
    [0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00],
    "magic \\0asm y versión 1",
  );
});

test("ejecutar el WASM da el resultado del programa y su salida", async () => {
  const result = compileFixture("calc.phir");
  assert.ok(result.codegen?.wasm);
  const { exports, output } = await instantiate(result.codegen.wasm);

  (exports[MODULE_INIT] as () => void)();
  assert.deepEqual(output, ["suriaX en WebAssembly\n"]);

  // main: total = suma(20,22) = 42; total += doble(1) = 2 -> 44;
  //       cociente = 44 / 4 = 11;  return 44 + 11 = 55
  assert.equal((exports["main"] as () => bigint)(), 55n);
});

test("aritmética entera, real, comparaciones y unario, ejecutadas", async () => {
  // sin DCE para que sobrevivan las funciones que 'main' no llama.
  const result = compileFixture("calc.phir", false);
  assert.ok(result.codegen?.wasm);
  const { exports } = await instantiate(result.codegen.wasm);

  const suma = exports["suma"] as (a: bigint, b: bigint) => bigint;
  const doble = exports["doble"] as (x: bigint) => bigint;
  const area = exports["area"] as (b: number, h: number) => number;
  const mayor = exports["mayor"] as (a: bigint, b: bigint) => number;
  const negativo = exports["negativo"] as (x: bigint) => bigint;

  assert.equal(suma(2n, 3n), 5n);
  assert.equal(suma(-8n, 3n), -5n);
  assert.equal(doble(21n), 42n);
  assert.equal(area(3, 4), 6);
  assert.equal(area(2.5, 5), 6.25);
  assert.equal(mayor(5n, 2n), 1);
  assert.equal(mayor(2n, 5n), 0);
  assert.equal(negativo(7n), -7n);
  assert.equal(negativo(-7n), 7n);
});

test("el int de suriaX es de 64 bits de verdad", async () => {
  const result = compileFixture("calc.phir", false);
  const { exports } = await instantiate(result.codegen!.wasm!);
  const suma = exports["suma"] as (a: bigint, b: bigint) => bigint;
  // más allá de Number.MAX_SAFE_INTEGER: con 'number' esto daría mal.
  assert.equal(suma(9007199254740992n, 1n), 9007199254740993n);
  // y envuelve como i64, no como BigInt infinito.
  assert.equal(suma(9223372036854775807n, 1n), -9223372036854775808n);
});

// --------------------------------------------------------------------------- //
// backend JS y módulo host
// --------------------------------------------------------------------------- //

test("el JS puro da EXACTAMENTE lo mismo que el WASM", async () => {
  const result = compileFixture("calc.phir");
  assert.ok(result.codegen?.js && result.codegen.wasm);

  const viaJs = await runGenerated(result.codegen.js);
  const { exports, output } = await instantiate(result.codegen.wasm);
  (exports[MODULE_INIT] as () => void)();
  const viaWasm = (exports["main"] as () => bigint)();

  assert.equal(viaJs.result, viaWasm, "mismo valor de retorno");
  assert.deepEqual(viaJs.output, output, "misma salida");
});

test("el módulo host embebe el WASM y se ejecuta solo", async () => {
  const result = compileFixture("calc.phir");
  assert.ok(result.codegen?.host);
  const { result: value, output } = await runGenerated(result.codegen.host);
  assert.equal(value, 55n);
  assert.deepEqual(output, ["suriaX en WebAssembly\n"]);
});

test("base64: ida y vuelta con todas las longitudes de resto", () => {
  for (let length = 0; length < 12; length++) {
    const bytes = new Uint8Array(length);
    for (let i = 0; i < length; i++) bytes[i] = (i * 37 + 11) & 0xff;
    const encoded = toBase64(bytes);
    const decoded = Uint8Array.from(atobLike(encoded));
    assert.deepEqual([...decoded], [...bytes], `longitud ${length}`);
  }
});

/** Decodificador de base64 independiente (no reusa el del generador). */
function atobLike(text: string): number[] {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const clean = text.replace(/=+$/, "");
  const out: number[] = [];
  let acc = 0;
  let bits = 0;
  for (const char of clean) {
    acc = (acc << 6) | alphabet.indexOf(char);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out.push((acc >> bits) & 0xff);
    }
  }
  return out;
}

// --------------------------------------------------------------------------- //
// WAT
// --------------------------------------------------------------------------- //

test("el WAT muestra el post-orden de la pila", () => {
  const wat = compileFixture("calc.phir").codegen!.wat!;
  assert.match(wat, /\(module/);
  assert.match(wat, /\(import "env" "__write__"/);
  assert.match(wat, /\(memory \(export "memory"\) 1\)/);
  assert.match(wat, /\(data \(i32\.const 0\) "suriaX en WebAssembly/);
  // 'suma(a, b)' -> los dos operandos y luego la operación.
  assert.match(wat, /local\.get \$a\n\s*local\.get \$b\n\s*i64\.add/);
  assert.match(wat, /call \$suma/);
});

// --------------------------------------------------------------------------- //
// alcance: lo que aún no se traduce
// --------------------------------------------------------------------------- //

test("lo que está fuera del subconjunto da WEB100 con su posición", () => {
  const bytes = buildModule((w) => {
    w.message(4, functionDecl("main", [
      (s: Writer) => {                     // match x { }
        s.uint32(1, 7);
        s.uint32(2, 3);
        s.message(15, (m) => m.message(1, identifier("x", 7, 9)));
      },
    ]));
  });
  const { module, diagnostics } = lowerModule(loadModule(bytes));
  assert.equal(module, null, "no se genera un módulo a medias");
  assert.ok(diagnostics.some((d) => d.code === WebCode.CODEGEN_UNSUPPORTED));
  assert.equal(diagnostics[0]!.line, 7);
  assert.match(diagnostics[0]!.message, /match/);
});

test("una condición que no es bool se rechaza en vez de emitir un módulo inválido", () => {
  // WASM exige i32 en la condición: un i64 daría un binario que el navegador
  // rechaza con un offset de bytes en vez de con una línea del fuente.
  const bytes = buildModule((w) => {
    w.message(4, functionDecl("main", [
      (s: Writer) => {                     // while (1) { }  con 1 de tipo int
        s.uint32(1, 4);
        s.uint32(2, 3);
        s.message(14, (wh) => {
          wh.message(1, intLiteral(1, 4, 12));
          wh.message(2, () => {});
        });
      },
    ]));
  });
  const { module, diagnostics } = lowerModule(loadModule(bytes));
  assert.equal(module, null);
  assert.deepEqual(diagnostics.map((d) => d.code), [WebCode.CODEGEN_TYPE]);
  assert.match(diagnostics[0]!.message, /condición del 'while'/);
  assert.equal(diagnostics[0]!.line, 4);
});

test("un tipo que el WIR no representa da WEB101", () => {
  // Un NOMINAL que no es un enum: un 'struct' no cabe en el WIR (no hay
  // memoria donde ponerlo). 'str' sí cabe desde el codegen v2 —viaja como el
  // índice de su constante—, así que ya no sirve como ejemplo de lo que falta.
  const bytes = buildModule(
    (w) => {
      w.message(4, (d) => {
        d.uint32(1, 3);
        d.message(10, (fn) => {
          fn.string(1, "f");
          fn.message(2, (param) => {
            param.uint32(3, TYPE_EXTRA);
            param.string(2, "p");
          });
          fn.uint32(7, TYPE_VOID);                   // -> void
          fn.message(4, () => {});
        });
      });
    },
    2,
    [(t) => { t.uint32(1, 9); t.string(2, "Punto"); }],   // NOMINAL 'Punto'
  );
  const { module, diagnostics } = lowerModule(loadModule(bytes));
  assert.equal(module, null);
  assert.deepEqual(diagnostics.map((d) => d.code), [WebCode.CODEGEN_TYPE]);
  assert.match(diagnostics[0]!.message, /Punto/);
});

test("un parámetro 'str' SÍ se traduce: es el índice de su constante", () => {
  const bytes = buildModule((w) => {
    w.message(4, (d) => {
      d.uint32(1, 3);
      d.message(10, (fn) => {
        fn.string(1, "f");
        fn.message(2, (param) => {
          param.uint32(3, TYPE_STR);
          param.string(2, "s");
        });
        fn.uint32(7, TYPE_VOID);
        fn.message(4, () => {});
      });
    });
  });
  const { module, diagnostics } = lowerModule(loadModule(bytes));
  assert.deepEqual(diagnostics, []);
  assert.equal(module?.funcs[0]?.params[0]?.type, 1);   // WirType.I32
});

test("imprimir algo que no es un literal da WEB102, no código inventado", () => {
  const bytes = buildModule((w) => {
    w.message(4, functionDecl("main", [
      (s: Writer) => {
        s.uint32(1, 4);
        s.message(21, (st) => st.message(1, (e) => {
          e.uint32(1, 4);
          e.message(17, (call) => {
            call.message(1, (callee) => {
              callee.message(19, (m) => {
                m.message(1, identifier("stdp"));
                m.string(2, "println");
              });
            });
            call.message(2, identifier("texto", 4, 15));
          });
        }));
      },
    ]));
  });
  const { module, diagnostics } = lowerModule(loadModule(bytes));
  assert.equal(module, null);
  assert.deepEqual(diagnostics.map((d) => d.code), [WebCode.CODEGEN_STRING]);
});

test("un programa con structs e if se rechaza con diagnósticos, sin romperse", () => {
  const result = compileFixture("prog.phir");
  assert.ok(result.restrictions.ok, "la contención lo acepta: solo usa IO");
  assert.equal(result.codegen?.ok, false, "pero el codegen v1 aún no lo traduce");
  assert.ok(result.codegen!.diagnostics.length > 0);
  assert.ok(
    result.codegen!.diagnostics.every((d) => d.code.startsWith("WEB1")),
    "todos son de alcance del codegen, no de contención",
  );
  assert.equal(result.codegen!.wasm, null, "y no se emite nada a medias");
});

test("un programa denegado por la contención ni siquiera llega al codegen", () => {
  const bytes = buildModule((w) => {
    w.message(4, (d) => {
      d.uint32(1, 1);
      d.message(13, (ext) => ext.string(1, "cpp"));   // #extern cpp
    });
    w.message(4, functionDecl("main", []));
  });
  const result = compile(bytes, "denegado.phir", () => null);
  assert.equal(result.image, null);
  assert.equal(result.codegen, null);
  assert.deepEqual(result.diagnostics.map((d) => d.code), [WebCode.EXTERN_CPP]);
});

test("generate() sobre un módulo suelto produce los cuatro artefactos", () => {
  const result = generate(loadModule(fixture("calc.phir"), "calc.phir"));
  assert.ok(result.ok);
  assert.ok(result.wir && result.wasm && result.js && result.host && result.wat);
  // los emisores son puros: llamarlos otra vez da lo mismo.
  assert.deepEqual([...emitWasm(result.wir)], [...result.wasm]);
  assert.equal(emitJs(result.wir), result.js);
  assert.equal(emitWat(result.wir), result.wat);
  assert.equal(emitHostModule(result.wir, result.wasm), result.host);
});

test("una variable le gana al import que se llama igual", () => {
  // 'var int stdp = 3; stdp.println("?")' no es una llamada al módulo: es un
  // acceso a miembro sobre un entero, y el intérprete lo rechaza con RT011.
  // El web resolvía el módulo igual y ejecutaba el println, así que el mismo
  // programa hacía cosas distintas según quién lo corriera.
  const bytes = buildModule((w) => {
    w.message(4, functionDecl("main", [
      // var int stdp = 3;
      (s: Writer) => {
        s.uint32(1, 2);
        s.message(11, (v) => {
          v.string(3, "stdp");            // name
          v.message(4, intLiteral(3, 2, 18));  // value
          v.uint32(5, TYPE_INT);          // type_id
        });
      },
      // stdp.println("x");
      (s: Writer) => {
        s.uint32(1, 3);
        s.message(21, (st) => st.message(1, (e) => {
          e.uint32(1, 3);
          e.message(17, (call) => {
            call.message(1, (callee) => {
              callee.message(19, (m) => {
                m.message(1, identifier("stdp", 3, 5));
                m.string(2, "println");
              });
            });
            call.message(2, (a) => {
              a.uint32(1, 3);
              a.message(10, (lit) => { lit.string(1, "str"); lit.string(3, "x"); });
            });
          });
        }));
      },
    ]));
  });
  const { module, diagnostics } = lowerModule(loadModule(bytes));
  assert.equal(module, null);
  const sombra = diagnostics.find((d) => /no un módulo/.test(d.message));
  assert.ok(sombra, diagnostics.map((d) => `${d.code} ${d.message}`).join("\n"));
  assert.equal(sombra.code, WebCode.CODEGEN_UNSUPPORTED);
});
