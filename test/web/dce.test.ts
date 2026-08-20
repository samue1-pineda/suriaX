/**
 * Pruebas del DCE. La mitad comprueba que ELIMINA lo muerto; la otra mitad,
 * más importante, que NO elimina lo vivo: un DCE que se pasa de listo borra
 * un `print` y el bug aparece en el navegador del usuario.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { loadModule } from "../../web/src/hir/decode.ts";
import { linkImage } from "../../web/src/hir/link.ts";
import type { Block, Decl, Module } from "../../web/src/hir/schema.ts";
import {
  crossUnitRoots,
  eliminateDeadCode,
  eliminateDeadCodeInImage,
} from "../../web/src/opt/dce.ts";
import {
  Writer,
  buildModule,
  exprStmt,
  fixture,
  fixturePath,
  fixtureResolver,
  functionDecl,
  identifier,
  intLiteral,
} from "./helpers.ts";

const names = (module: Module): string[] =>
  module.items.flatMap((d: Decl) => {
    switch (d.node.case) {
      case "function": return [d.node.fn.name];
      case "struct": return [d.node.struct.name];
      case "enum": return [d.node.enumDecl.name];
      default: return [];
    }
  });

function bodyOf(module: Module, fn: string): Block {
  const decl = module.items.find(
    (d) => d.node.case === "function" && d.node.fn.name === fn,
  );
  assert.ok(decl && decl.node.case === "function" && decl.node.fn.body, `falta ${fn}`);
  return decl.node.fn.body;
}

// --------------------------------------------------------------------------- //
// sobre el fixture real
// --------------------------------------------------------------------------- //

test("elimina funciones y structs inalcanzables desde 'main'", () => {
  const module = loadModule(fixture("prog.phir"), "prog.phir");
  assert.deepEqual(names(module), ["Punto", "Color", "suma", "nunca_usada", "NoUsada", "main"]);

  const { module: out, stats } = eliminateDeadCode(module);
  assert.deepEqual(names(out), ["Punto", "suma", "main"]);
  assert.equal(stats.functions, 1);
  assert.equal(stats.structs, 1);
  assert.equal(stats.enums, 1);
  assert.deepEqual([...stats.removed].sort(), ["Color", "NoUsada", "nunca_usada"]);
});

test("la tabla de símbolos se poda junto al árbol", () => {
  const { module: out, stats } = eliminateDeadCode(
    loadModule(fixture("prog.phir"), "prog.phir"),
  );
  assert.ok(out.symbols.values.has("suma"));
  assert.ok(!out.symbols.values.has("nunca_usada"), "el símbolo muerto se va");
  assert.ok(out.symbols.types.has("Punto"));
  assert.ok(!out.symbols.types.has("NoUsada"));
  assert.ok(stats.symbols >= 3);
});

test("borra lo que sigue a un 'return' y deja el resto intacto", () => {
  const module = loadModule(fixture("prog.phir"), "prog.phir");
  assert.equal(bodyOf(module, "suma").statements.length, 2);

  const { module: out, stats } = eliminateDeadCode(module);
  const body = bodyOf(out, "suma");
  assert.equal(body.statements.length, 1);
  assert.equal(body.statements[0]!.node.case, "return");
  assert.equal(stats.unreachableStatements, 1);
});

test("borra la sentencia sin efectos y la variable nunca leída", () => {
  const { module: out, stats } = eliminateDeadCode(
    loadModule(fixture("prog.phir"), "prog.phir"),
  );
  const body = bodyOf(out, "main");
  const kinds = body.statements.map((s) => s.node.case);
  // quedan: var p, var total, if, return  (se fueron 'total + 1;' y 'muerta')
  assert.deepEqual(kinds, ["varDecl", "varDecl", "if", "return"]);
  assert.equal(stats.pureStatements, 1);
  assert.equal(stats.deadVars, 1);
});

test("no toca las llamadas ni las ramas vivas del if", () => {
  const { module: out } = eliminateDeadCode(
    loadModule(fixture("prog.phir"), "prog.phir"),
  );
  const body = bodyOf(out, "main");
  const ifStmt = body.statements[2]!;
  assert.equal(ifStmt.node.case, "if");
  if (ifStmt.node.case !== "if") return;
  assert.equal(ifStmt.node.ifStmt.thenBlock.statements.length, 1, "el print vive");
  assert.equal(ifStmt.node.ifStmt.elseBranch.case, "block");
  if (ifStmt.node.ifStmt.elseBranch.case === "block") {
    assert.equal(ifStmt.node.ifStmt.elseBranch.block.statements.length, 1);
  }
});

test("es idempotente: una segunda pasada no cambia nada", () => {
  const first = eliminateDeadCode(loadModule(fixture("prog.phir"), "prog.phir"));
  const second = eliminateDeadCode(first.module);
  assert.deepEqual(names(second.module), names(first.module));
  assert.equal(second.stats.functions, 0);
  assert.equal(second.stats.pureStatements, 0);
  assert.equal(second.stats.deadVars, 0);
});

test("no muta el módulo de entrada", () => {
  const module = loadModule(fixture("prog.phir"), "prog.phir");
  const before = names(module);
  eliminateDeadCode(module);
  assert.deepEqual(names(module), before);
  assert.equal(bodyOf(module, "suma").statements.length, 2);
});

// --------------------------------------------------------------------------- //
// conservadurismo
// --------------------------------------------------------------------------- //

test("una llamada como sentencia NUNCA se elimina", () => {
  const bytes = buildModule((w) => {
    w.message(4, functionDecl("main", [
      exprStmt((e) => {
        e.uint32(1, 2);
        e.uint32(2, 1);
        e.message(17, (call) => call.message(1, identifier("efecto")));
      }, 2, 1),
    ]));
    w.message(4, functionDecl("efecto", [], 20));
  });
  const { module: out, stats } = eliminateDeadCode(loadModule(bytes));
  assert.equal(stats.pureStatements, 0);
  assert.equal(bodyOf(out, "main").statements.length, 1);
  assert.deepEqual(names(out).sort(), ["efecto", "main"]);
});

test("una variable leída una sola vez se conserva", () => {
  const bytes = buildModule((w) => {
    w.message(4, functionDecl("main", [
      (s) => {
        s.uint32(1, 2);
        s.uint32(2, 1);
        s.message(11, (vd) => {
          vd.string(1, "var");
          vd.string(3, "x");
          vd.message(4, intLiteral(1));
        });
      },
      exprStmt((e) => {
        e.uint32(1, 3);
        e.uint32(2, 1);
        e.message(17, (call) => {
          call.message(1, identifier("usar"));
          call.message(2, identifier("x", 3, 6));
        });
      }, 3, 1),
    ]));
  });
  const { module: out, stats } = eliminateDeadCode(loadModule(bytes));
  assert.equal(stats.deadVars, 0);
  assert.equal(bodyOf(out, "main").statements.length, 2);
});

test("una variable con inicializador IMPURO se conserva aunque no se lea", () => {
  const bytes = buildModule((w) => {
    w.message(4, functionDecl("main", [
      (s) => {
        s.uint32(1, 2);
        s.uint32(2, 1);
        s.message(11, (vd) => {
          vd.string(1, "var");
          vd.string(3, "sinUso");
          vd.message(4, (e) => {
            e.uint32(1, 2);
            e.uint32(2, 10);
            e.message(17, (call) => call.message(1, identifier("efecto")));
          });
        });
      },
    ]));
  });
  const { module: out, stats } = eliminateDeadCode(loadModule(bytes));
  assert.equal(stats.deadVars, 0, "la llamada del inicializador tiene efectos");
  assert.equal(bodyOf(out, "main").statements.length, 1);
});

test("un nombre declarado dos veces (sombreado) no se toca", () => {
  const varDecl = (name: string, ln: number) => (s: Writer) => {
    s.uint32(1, ln);
    s.uint32(2, 1);
    s.message(11, (vd) => {
      vd.string(1, "var");
      vd.string(3, name);
      vd.message(4, intLiteral(1, ln, 10));
    });
  };
  const bytes = buildModule((w) => {
    w.message(4, functionDecl("main", [
      varDecl("x", 2),
      (s) => {                       // { var x = 1; }
        s.uint32(1, 3);
        s.uint32(2, 1);
        s.message(10, (block) => block.message(1, varDecl("x", 4)));
      },
    ]));
  });
  const { stats } = eliminateDeadCode(loadModule(bytes));
  assert.equal(stats.deadVars, 0, "sin resolución de scopes, se conserva");
});

test("los cuerpos de hook sobreviven aunque nadie los llame por nombre", () => {
  const bytes = buildModule((w) => {
    w.message(3, (table) => {
      table.message(3, (entry) => {
        entry.string(1, "String");
        entry.uint32(2, 4);                      // PRINT
        entry.message(3, (sym) => {
          sym.string(1, "__print__");
          sym.uint32(3, 30);
        });
      });
    });
    w.message(4, (d) => {                        // fn __print__ en la línea 30
      d.uint32(1, 30);
      d.uint32(2, 1);
      d.message(10, (fn) => {
        fn.string(1, "__print__");
        fn.string(5, "print");
        fn.message(4, (block) => {
          block.message(1, exprStmt(intLiteral(1, 31, 5), 31, 5));
        });
      });
    });
    w.message(4, functionDecl("main", [], 40));
  });

  const conservado = eliminateDeadCode(loadModule(bytes));
  assert.ok(names(conservado.module).includes("__print__"), "keepHooks por defecto");

  const podado = eliminateDeadCode(loadModule(bytes), { keepHooks: false });
  assert.ok(!names(podado.module).includes("__print__"));
});

test("los tests se descartan salvo que se pidan", () => {
  const bytes = buildModule((w) => {
    w.message(4, (d) => {
      d.uint32(1, 5);
      d.uint32(2, 1);
      d.message(18, (t) => {
        t.string(1, "suma correcta");
        t.message(2, (block) => {
          block.message(1, exprStmt((e) => {
            e.uint32(1, 6);
            e.uint32(2, 1);
            e.message(17, (call) => call.message(1, identifier("ayuda")));
          }, 6, 1));
        });
      });
    });
    w.message(4, functionDecl("ayuda", [], 10));
    w.message(4, functionDecl("main", [], 20));
  });

  const sinTests = eliminateDeadCode(loadModule(bytes));
  assert.equal(sinTests.stats.tests, 1);
  assert.deepEqual(names(sinTests.module), ["main"], "'ayuda' solo la usaba el test");

  const conTests = eliminateDeadCode(loadModule(bytes), { keepTests: true });
  assert.equal(conTests.stats.tests, 0);
  assert.deepEqual(names(conTests.module).sort(), ["ayuda", "main"]);
});

test("la entrada es configurable", () => {
  const bytes = buildModule((w) => {
    w.message(4, functionDecl("main", [], 10));
    w.message(4, functionDecl("otra_entrada", [], 20));
  });
  assert.deepEqual(names(eliminateDeadCode(loadModule(bytes)).module), ["main"]);
  assert.deepEqual(
    names(eliminateDeadCode(loadModule(bytes), { entry: "otra_entrada" }).module),
    ["otra_entrada"],
  );
});

test("una unidad de librería conserva todo si no se le dan raíces", () => {
  const bytes = buildModule((w) => {
    w.message(4, (d) => {
      d.uint32(1, 1);
      d.uint32(2, 1);
      d.message(16, (exp) => exp.string(1, "MiLib"));   // #export as MiLib
    });
    w.message(4, functionDecl("publica", [], 5));
    w.message(4, functionDecl("interna", [], 9));
  });

  // sin raíces: la visibilidad no viaja en el HIR v1 -> se conserva todo.
  assert.deepEqual(
    names(eliminateDeadCode(loadModule(bytes)).module).sort(),
    ["interna", "publica"],
  );
  // con raíces explícitas: poda de verdad.
  assert.deepEqual(
    names(eliminateDeadCode(loadModule(bytes), { roots: ["publica"] }).module),
    ["publica"],
  );
});

// --------------------------------------------------------------------------- //
// imagen completa
// --------------------------------------------------------------------------- //

test("crossUnitRoots ve las llamadas 'stdp.println' de la unidad principal", () => {
  const image = linkImage(fixture("prog.phir"), fixturePath("prog.phir"), fixtureResolver);
  const roots = crossUnitRoots(image, "IO.stdp");
  assert.ok(roots.includes("println"), "el miembro llamado es una raíz");
  assert.ok(!roots.includes("printf"), "lo que nadie llama, no");
});

test("DCE sobre la imagen: la librería se queda con lo que se usa", () => {
  const image = linkImage(fixture("prog.phir"), fixturePath("prog.phir"), fixtureResolver);
  const { image: out, stats } = eliminateDeadCodeInImage(image);

  const stdp = out.units.get("IO.stdp")!;
  const quedan = names(stdp.module);
  assert.ok(quedan.includes("println"), "la función usada vive");
  assert.ok(quedan.includes("__write__"), "y la primitiva que llama, también");
  assert.ok(!quedan.includes("print"), "'print' no lo usa nadie");

  // 'printf' no lo llama nadie y se va. '__write__' sobrevive porque OTRA
  // unidad (IO.stdp) tiene una función con ese mismo nombre y la llama: las
  // raíces entre unidades son nombres, no símbolos resueltos. Sobrevivir de
  // más es el lado seguro del error (ver crossUnitRoots).
  const stdpf = out.units.get("IO.stdpf")!;
  assert.deepEqual(names(stdpf.module), ["__write__"]);

  assert.ok(stats.get("")!.functions >= 1);
  assert.ok(stats.get("IO.stdp")!.functions >= 1);

  // los índices de la imagen nueva siguen cuadrando
  assert.equal(out.everyUnit.length, 4);
});

test("los hooks de una librería sobreviven al DCE de la imagen", () => {
  const image = linkImage(fixture("prog.phir"), fixturePath("prog.phir"), fixtureResolver);
  const { image: out } = eliminateDeadCodeInImage(image);
  const stdp = out.units.get("IO.stdp")!;
  // '__print__' de String se despacha en runtime: no puede desaparecer.
  assert.ok(names(stdp.module).includes("__print__"));
  assert.ok(out.dunders.has("String#__print__"), "y sigue ligado a su cuerpo");
});
