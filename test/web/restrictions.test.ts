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
  UNRESTRICTED_POLICY,
  WEB_V1_POLICY,
  withCapabilities,
  withUnits,
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

test("una librería fuera de la allowlist se rechaza con su posición", () => {
  const bytes = buildModule((w) => {
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
  const report = checkModule(loadModule(bytes), WEB_V1_POLICY);
  assert.ok(!report.ok);
  assert.ok(codes(report).includes(WebCode.LIBRARY_DENIED));
  assert.ok(report.deniedUnits.includes("MATH"));
  const first = report.diagnostics[0]!;
  assert.match(first.message, /solo puede ejecutarse/);
  // la referencia de 'Module.libraries' también se revisa (import transitivo).
  assert.equal(report.diagnostics.length, 2);
  assert.ok(report.diagnostics.some((d) => d.line === 1 && d.column === 1));
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
  assert.ok(!checkModule(module, WEB_V1_POLICY).ok);
  const conMath = withUnits(WEB_V1_POLICY, [{ alias: "MATH", hostPrimitives: [] }]);
  assert.ok(checkModule(module, conMath).ok);
  // el perfil base no se mutó
  assert.ok(!checkModule(module, WEB_V1_POLICY).ok);
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
