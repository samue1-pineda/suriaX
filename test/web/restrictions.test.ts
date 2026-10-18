/**
 * Pruebas de la contención: lo que el target web NO puede correr tiene que
 * rechazarse SIEMPRE, con código y posición, y lo permitido tiene que pasar
 * sin ruido.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { WebCode } from "../../web/src/diagnostics.ts";
import { loadModule } from "../../web/src/hir/decode.ts";
import { linkImage } from "../../web/src/hir/link.ts";
import {
  Capability,
  PLAYGROUND_POLICY,
  POLICIES,
  UNRESTRICTED_POLICY,
  WEB_V1_POLICY,
  withCapabilities,
  withUnits,
  type Policy,
} from "../../web/src/target/policy.ts";
import { checkImage, checkModule } from "../../web/src/target/restrictions.ts";
import {
  Writer,
  buildModule,
  exprStmt,
  fixture,
  fixturePath,
  fixtureResolver,
  identifier,
  intLiteral,
  TYPE_EXTRA,
  TYPE_INT,
} from "./helpers.ts";

/** Envuelve un `Decl` con una `FunctionDecl` cuyo cuerpo son `body`. */
function fnWith(name: string, build: (fn: Writer) => void) {
  return (d: Writer): void => {
    d.uint32(1, 10);
    d.uint32(2, 1);
    d.message(10, (fn) => {
      fn.string(1, name);
      build(fn);
    });
  };
}

const codes = (report: { diagnostics: readonly { code: string }[] }): string[] =>
  report.diagnostics.map((d) => d.code);

test("el programa de ejemplo (solo IO) pasa la contención", () => {
  const image = linkImage(fixture("prog.phir"), fixturePath("prog.phir"), fixtureResolver);
  const report = checkImage(image, WEB_V1_POLICY);
  assert.deepEqual(report.diagnostics, [], "ningún diagnóstico");
  assert.ok(report.ok);
  assert.equal(report.denied.size, 0);
});

test("IO viaja aunque use punteros: es una unidad confiable del host", () => {
  // 'fn __print__(String ptr s)' dispara WEB002 si la unidad NO es confiable...
  const module = loadModule(fixture("IO.stdp.phir"), "IO.stdp.phir");
  const asUserCode = checkModule(module, WEB_V1_POLICY, "");
  assert.ok(asUserCode.diagnostics.length > 0, "como código de usuario se rechaza");
  assert.ok(codes(asUserCode).includes(WebCode.POINTER_TYPE));

  // ...y no dispara nada cuando se revisa con su alias real.
  const asLibrary = checkModule(module, WEB_V1_POLICY, "IO.stdp");
  assert.deepEqual(asLibrary.diagnostics, []);
  assert.ok(asLibrary.ok);
});

/** Módulo que importa una librería llamada 'MATH' y la referencia. */
function importaMath() {
  return buildModule((w) => {
    w.message(4, (d) => {
      d.uint32(1, 1);
      d.uint32(2, 1);
      d.message(15, (imp) => {
        imp.string(1, "math");
        imp.string(3, "MATH");
        imp.string(4, "math");
      });
    });
    w.message(5, (lib) => {
      lib.string(1, "MATH");
      lib.string(2, "MATH.phir");
    });
  });
}

test("una librería fuera de la allowlist se rechaza con su posición", () => {
  // La allowlist sigue existiendo y una política PUEDE usarla; lo que cambió
  // es que el perfil v1 ya no la usa (ver el test siguiente).
  const soloIO: Policy = { ...WEB_V1_POLICY, allowAllUnits: false };
  const report = checkModule(loadModule(importaMath()), soloIO);
  assert.ok(!report.ok);
  assert.ok(codes(report).includes(WebCode.LIBRARY_DENIED));
  assert.ok(report.deniedUnits.includes("MATH"));
  const first = report.diagnostics[0]!;
  assert.match(first.message, /solo puede ejecutarse/);
  // UNA vez, y en su '#import': la referencia de 'Module.libraries' nombra la
  // misma unidad y antes salía otra vez, sin línea.
  assert.equal(report.diagnostics.length, 1);
  assert.ok(first.line === 1 && first.column === 1);
});

test("una librería que entra sin '#import' propio también se rechaza", () => {
  // La referencia de 'Module.libraries' es por donde llega un import
  // transitivo: no hay declaración que señalar, pero no puede colarse.
  const bytes = buildModule((w) => {
    w.message(5, (lib) => {
      lib.string(1, "MATH");
      lib.string(2, "MATH.phir");
    });
  });
  const soloIO: Policy = { ...WEB_V1_POLICY, allowAllUnits: false };
  const report = checkModule(loadModule(bytes), soloIO);
  assert.ok(!report.ok);
  assert.deepEqual(report.deniedUnits, ["MATH"]);
  assert.equal(report.diagnostics.length, 1);
});

/** Módulo con un único `#import <lib>` que resuelve a la unidad `unit`. */
function importa(lib: string, unit: string) {
  return buildModule((w) => {
    w.message(4, (d) => {
      d.uint32(1, 3);
      d.uint32(2, 1);
      d.message(15, (imp) => {
        imp.string(1, lib);
        imp.string(3, unit);
        imp.string(4, lib);
      });
    });
    w.message(5, (ref) => {
      ref.string(1, unit);
      ref.string(2, `${unit}.phir`);
    });
  });
}

test("el perfil del playground deja pasar solo lo que el target sabe ejecutar", () => {
  for (const unit of ["IO", "IO.stdp", "IO.stdpf", "math", "math.basic",
                      "math.constants", "excepciones"]) {
    const report = checkModule(loadModule(importa(unit, unit)), PLAYGROUND_POLICY);
    assert.deepEqual(report.diagnostics, [], unit);
  }
  // el perfil del target, en cambio, sigue sin mirar el nombre
  assert.ok(checkModule(loadModule(importa("text", "text")), WEB_V1_POLICY).ok);
});

test("el perfil del playground dice POR QUÉ deniega cada librería", () => {
  const casos: [string, RegExp][] = [
    ["sistema.archivos", /no tiene archivos, procesos ni rutas/],
    ["sistema.proceso", /no tiene archivos, procesos ni rutas/],
    ["sistema.rutas", /no tiene archivos, procesos ni rutas/],
    ["text", /todavía no representa/],
    ["array.vector", /todavía no representa/],
    ["collections.dictionary", /todavía no representa/],
    ["d_types", /__sizeof__/],
    ["mem", /runtime nativo/],
  ];
  for (const [unit, motivo] of casos) {
    const report = checkModule(loadModule(importa(unit, unit)), PLAYGROUND_POLICY);
    assert.ok(!report.ok, unit);
    assert.equal(report.diagnostics.length, 1, unit);
    const diag = report.diagnostics[0]!;
    assert.equal(diag.code, WebCode.LIBRARY_DENIED, unit);
    assert.equal(diag.line, 3, unit);
    assert.match(diag.message, motivo, unit);
    assert.match(diag.message, /'playground'/, unit);
  }
});

test("una librería que el playground no conoce nace denegada", () => {
  // Lista blanca: lo nuevo no entra hasta que alguien lo habilite a propósito.
  const report = checkModule(loadModule(importa("math.trig", "math.trig")),
                             PLAYGROUND_POLICY);
  assert.deepEqual(report.deniedUnits, ["math.trig"]);
});

test("una unidad denegada no se revisa por dentro", () => {
  // Antes un '#import' de una librería con punteros daba decenas de WEB002
  // en un archivo que el usuario no escribió; con la unidad ya denegada en
  // su '#import', revisarla por dentro no le dice nada nuevo.
  const image = linkImage(fixture("prog.phir"), fixturePath("prog.phir"), fixtureResolver);
  const sinIO: Policy = {
    ...WEB_V1_POLICY,
    allowAllUnits: false,
    allowedUnits: new Set(),
    trustedUnits: new Map(),
  };
  const report = checkImage(image, sinIO);
  assert.ok(!report.ok);
  assert.ok(!codes(report).includes(WebCode.POINTER_TYPE), codes(report).join(" "));
  // y sin denegarla, la misma unidad sin confianza SÍ da sus punteros
  const sinConfianza: Policy = { ...WEB_V1_POLICY, trustedUnits: new Map() };
  assert.ok(codes(checkImage(image, sinConfianza)).includes(WebCode.POINTER_TYPE));
});

test("los perfiles se piden por nombre", () => {
  assert.deepEqual([...POLICIES.keys()].sort(),
                   ["playground", "unrestricted", "web-v1"]);
  assert.equal(POLICIES.get("playground"), PLAYGROUND_POLICY);
});

test("el perfil v1 no rechaza una librería por su nombre", () => {
  // Antes solo 'IO' podía importarse, y no porque el target no supiera
  // traducir las demás: el lowering tiraba las unidades antes de llegar al
  // WIR. Ahora decide la CAPACIDAD — una librería que usa punteros se rechaza
  // por WEB002 señalando la línea, no por llamarse como se llama.
  const report = checkModule(loadModule(importaMath()), WEB_V1_POLICY);
  assert.deepEqual(report.deniedUnits, []);
  assert.ok(!codes(report).includes(WebCode.LIBRARY_DENIED));
  assert.ok(report.ok);
});

test("la librería permitida se reconoce por unidad resuelta, no por lo escrito", () => {
  const bytes = buildModule((w) => {
    w.message(4, (d) => {
      d.uint32(1, 1);
      d.uint32(2, 1);
      d.message(17, (from) => {
        from.string(1, "io");     // lo escrito
        from.string(2, "stdp");
        from.string(4, "IO");     // la unidad resuelta
      });
    });
  });
  assert.deepEqual(checkModule(loadModule(bytes), WEB_V1_POLICY).diagnostics, []);
});

test("#extern cpp: rechazado con WEB001", () => {
  const bytes = buildModule((w) => {
    w.message(4, (d) => {
      d.uint32(1, 4);
      d.uint32(2, 1);
      d.message(13, (ext) => {
        ext.string(1, "cpp");
        ext.string(2, "int x = 1;");
      });
    });
  });
  const report = checkModule(loadModule(bytes), WEB_V1_POLICY);
  assert.deepEqual(codes(report), [WebCode.EXTERN_CPP]);
  assert.ok(report.denied.has(Capability.EXTERN_CPP));
  assert.equal(report.diagnostics[0]!.line, 4);
  assert.equal(report.diagnostics[0]!.severity, "critical");
});

const PTR_MUT_INT = TYPE_EXTRA;
const PTR_INT = TYPE_EXTRA + 1;

test("punteros: en parámetro, en campo y en variable — uno por declaración", () => {
  const bytes = buildModule((w) => {
    w.message(4, fnWith("f", (fn) => {
      fn.message(2, (param) => {
        param.uint32(3, PTR_MUT_INT);          // 'int ptr mutable'
        param.string(2, "p");
      });
      fn.message(4, (block) => {
        block.message(1, (stmt) => {
          stmt.uint32(1, 12);
          stmt.uint32(2, 5);
          stmt.message(11, (vd) => {           // VarDecl
            vd.string(1, "var");
            vd.string(3, "q");
            vd.uint32(5, PTR_INT);             // 'int ptr'
          });
        });
      });
    }));
  }, 2, [
    // los dos punteros del caso, en el pool: 'int ptr mutable' e 'int ptr'
    (t) => { t.uint32(1, 7); t.message(3, (inner) => inner.uint32(1, 3)); t.bool(4, true); },
    (t) => { t.uint32(1, 7); t.message(3, (inner) => inner.uint32(1, 3)); },
  ]);
  const report = checkModule(loadModule(bytes), WEB_V1_POLICY);
  assert.deepEqual(codes(report), [WebCode.POINTER_TYPE, WebCode.POINTER_TYPE]);
  assert.match(report.diagnostics[0]!.message, /int ptr mutable/);
  assert.match(report.diagnostics[1]!.message, /la variable 'q'/);
  assert.equal(report.diagnostics[1]!.line, 12);
});

test("&x, free, move y sizeof: cada uno con su código", () => {
  const bytes = buildModule((w) => {
    w.message(4, fnWith("f", (fn) => {
      fn.message(4, (block) => {
        // &x;
        block.message(1, exprStmt((e) => {
          e.uint32(1, 2);
          e.uint32(2, 3);
          e.message(23, (addr) => addr.message(1, identifier("x")));
        }, 2, 3));
        // free x;
        block.message(1, (stmt) => {
          stmt.uint32(1, 3);
          stmt.uint32(2, 1);
          stmt.message(20, (free) => free.message(1, identifier("x")));
        });
        // move x;
        block.message(1, (stmt) => {
          stmt.uint32(1, 4);
          stmt.uint32(2, 1);
          stmt.message(19, (mv) => mv.message(1, identifier("x")));
        });
        // sizeof(int);
        block.message(1, exprStmt((e) => {
          e.uint32(1, 5);
          e.uint32(2, 1);
          e.message(22, (so) => so.message(1, (t) => t.uint32(1, 3)));
        }, 5, 1));
      });
    }));
  });
  const report = checkModule(loadModule(bytes), WEB_V1_POLICY);
  assert.deepEqual(codes(report), [
    WebCode.ADDRESS_OF, WebCode.FREE, WebCode.MOVE, WebCode.SIZEOF,
  ]);
  assert.deepEqual([...report.denied].sort(), [
    Capability.ADDRESS_OF, Capability.MANUAL_FREE,
    Capability.MOVE, Capability.SIZEOF,
  ].sort());
  assert.deepEqual(report.diagnostics.map((d) => d.line), [2, 3, 4, 5]);
});

test("hooks de memoria: se detectan en la tabla de símbolos", () => {
  const bytes = buildModule((w) => {
    w.message(3, (table) => {
      table.message(3, (entry) => {           // HookEntry
        entry.string(1, "Buffer");
        entry.uint32(2, 1);                   // FREE
        entry.message(3, (sym) => {
          sym.string(1, "__free__");
          sym.uint32(2, 10);                  // HOOK
          sym.uint32(3, 7);
          sym.uint32(4, 1);
        });
      });
      table.message(3, (entry) => {
        entry.string(1, "Buffer");
        entry.uint32(2, 4);                   // PRINT: permitido
        entry.message(3, (sym) => {
          sym.string(1, "__print__");
          sym.uint32(3, 12);
        });
      });
    });
  });
  const report = checkModule(loadModule(bytes), WEB_V1_POLICY);
  assert.deepEqual(codes(report), [WebCode.MEMORY_HOOK]);
  assert.equal(report.diagnostics[0]!.line, 7);
  assert.match(report.diagnostics[0]!.message, /__free__.*Buffer/);
});

test("un nodo malformado se reporta, no se ignora", () => {
  const bytes = buildModule((w) => {
    w.message(4, (d) => {
      d.uint32(1, 9);
      d.uint32(2, 2);
    });
  });
  const report = checkModule(loadModule(bytes), WEB_V1_POLICY);
  assert.deepEqual(codes(report), [WebCode.MALFORMED_NODE]);
  assert.equal(report.diagnostics[0]!.line, 9);
});

test("la política es derivable: habilitar una capacidad la deja pasar", () => {
  const bytes = buildModule((w) => {
    w.message(4, (d) => {
      d.uint32(1, 1);
      d.uint32(2, 1);
      d.message(13, (ext) => ext.string(1, "cpp"));
    });
  });
  const module = loadModule(bytes);
  assert.equal(checkModule(module, WEB_V1_POLICY).diagnostics.length, 1);
  const permissive = withCapabilities(WEB_V1_POLICY, [Capability.EXTERN_CPP]);
  assert.deepEqual(checkModule(module, permissive).diagnostics, []);
  assert.deepEqual(checkModule(module, UNRESTRICTED_POLICY).diagnostics, []);
});

test("withUnits añade una librería sin tocar el perfil base", () => {
  const bytes = buildModule((w) => {
    w.message(4, (d) => {
      d.uint32(1, 1);
      d.uint32(2, 1);
      d.message(15, (imp) => {
        imp.string(1, "math");
        imp.string(3, "MATH");
      });
    });
  });
  const module = loadModule(bytes);
  // sobre una política CON allowlist: 'MATH' no está y se rechaza...
  const soloIO: Policy = { ...WEB_V1_POLICY, allowAllUnits: false };
  assert.ok(!checkModule(module, soloIO).ok);
  const conMath = withUnits(soloIO, [{ alias: "MATH", hostPrimitives: [] }]);
  assert.ok(checkModule(module, conMath).ok);
  // el perfil base no se mutó
  assert.ok(!checkModule(module, soloIO).ok);
});

test("el mismo diagnóstico no se repite en la misma posición", () => {
  const bytes = buildModule((w) => {
    w.message(4, fnWith("f", (fn) => {
      fn.message(4, (block) => {
        block.message(1, exprStmt((e) => {
          e.uint32(1, 2);
          e.uint32(2, 1);
          // '&x + &x' en la MISMA posición no debe reportar dos veces
          e.message(14, (bin) => {
            bin.string(1, "+");
            bin.message(2, (l) => {
              l.uint32(1, 2);
              l.uint32(2, 1);
              l.message(23, (addr) => addr.message(1, identifier("x")));
            });
            bin.message(3, (r) => {
              r.uint32(1, 2);
              r.uint32(2, 1);
              r.message(23, (addr) => addr.message(1, identifier("x")));
            });
          });
        }, 2, 1));
      });
    }));
  });
  const report = checkModule(loadModule(bytes), WEB_V1_POLICY);
  assert.deepEqual(codes(report), [WebCode.ADDRESS_OF]);
});

test("checkImage revisa también las unidades ligadas", () => {
  const image = linkImage(fixture("prog.phir"), fixturePath("prog.phir"), fixtureResolver);
  // con una política que NO confía en IO, la misma imagen se rechaza:
  // es la prueba de que las librerías se revisan de verdad.
  const sinConfianza = {
    ...WEB_V1_POLICY,
    trustedUnits: new Map(),
  };
  const report = checkImage(image, sinConfianza);
  assert.ok(!report.ok);
  assert.ok(codes(report).includes(WebCode.POINTER_TYPE));
});

test("intLiteral/identifier del helper producen HIR que el lector entiende", () => {
  const bytes = buildModule((w) => {
    w.message(4, fnWith("f", (fn) => {
      fn.message(4, (block) => {
        block.message(1, exprStmt(intLiteral(42, 1, 1), 1, 1));
      });
    }));
  });
  assert.deepEqual(checkModule(loadModule(bytes), WEB_V1_POLICY).diagnostics, []);
});

// --------------------------------------------------------------------------- //
// funciones como valores (TypeKind.FUNCTION_TYPE = 13): WEB103, siempre
// --------------------------------------------------------------------------- //

const FUNCTION_VALUE_MESSAGE =
  "usa una función como valor (tipo 'fn(int) -> int'): el target web todavía " +
  "no ejecuta funciones como valores; ejecútalo con el intérprete " +
  "(python V0/main.py <fuente>.srcx --run interpreter)";

test("una función como valor se rechaza con WEB103, con posición y mensaje exacto", () => {
  const image = linkImage(fixture("funciones_valor.phir"),
                          fixturePath("funciones_valor.phir"), fixtureResolver);
  const report = checkImage(image, WEB_V1_POLICY);
  assert.ok(!report.ok);
  // un diagnóstico por línea: el parámetro (que delata también 'f(v)'), las
  // dos variables y el argumento 'g' de la llamada
  assert.deepEqual(
    report.diagnostics.map((d) => [d.code, d.line, d.column]),
    [
      [WebCode.FUNCTION_VALUE, 7, 1],
      [WebCode.FUNCTION_VALUE, 10, 5],
      [WebCode.FUNCTION_VALUE, 11, 5],
      [WebCode.FUNCTION_VALUE, 12, 19],
    ],
  );
  assert.equal(report.diagnostics[0]!.message,
               `el parámetro 'f' de 'aplica' ${FUNCTION_VALUE_MESSAGE}`);
  // el anidado en un nullable se nombra por la función de adentro
  assert.equal(report.diagnostics[2]!.message, `la variable 'h' ${FUNCTION_VALUE_MESSAGE}`);
  assert.equal(report.diagnostics[3]!.message, `la expresión ${FUNCTION_VALUE_MESSAGE}`);
  // no es una capacidad de la política: no se apunta como denegada
  assert.equal(report.denied.size, 0);
});

test("WEB103 no depende de la política: ni 'unrestricted' deja pasar una función como valor", () => {
  const image = linkImage(fixture("funciones_valor.phir"),
                          fixturePath("funciones_valor.phir"), fixtureResolver);
  for (const policy of [UNRESTRICTED_POLICY, PLAYGROUND_POLICY]) {
    const report = checkImage(image, policy);
    assert.ok(!report.ok, policy.name);
    assert.deepEqual([...new Set(codes(report))], [WebCode.FUNCTION_VALUE], policy.name);
  }
});
