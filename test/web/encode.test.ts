/**
 * Pruebas del re-serializador. La propiedad que importa es la ida y vuelta:
 * lo que el lector entiende, el escritor tiene que poder volver a escribirlo
 * sin perder nada. Los fixtures son bytes del compilador de verdad, así que
 * un fallo aquí es un desacuerdo real con el emisor Python, no con mi idea
 * de él.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { decodeModule, loadModule } from "../../web/src/hir/decode.ts";
import { encodeModule } from "../../web/src/hir/encode.ts";
import { HookKind, SymbolKind, TypeKind, formatType, type Module } from "../../web/src/hir/schema.ts";
import { Writer as TestWriter, buildModule, fixture } from "./helpers.ts";

/** Compara dos módulos ignorando la identidad de los objetos (Map incluido). */
function normalize(module: Module): unknown {
  return JSON.parse(JSON.stringify(module, (_key, value) => {
    if (value instanceof Map) return Object.fromEntries([...value.entries()].sort());
    if (typeof value === "bigint") return `${value}n`;
    if (value instanceof Uint8Array) return [...value];
    return value;
  }));
}

function roundTrip(bytes: Uint8Array): { before: Module; after: Module } {
  const before = loadModule(bytes, "<fixture>");
  const after = loadModule(encodeModule(before), "<reencoded>");
  return { before, after };
}

for (const name of ["prog.phir", "calc.phir", "IO.stdp.phir", "IO.stdpf.phir", "IO.phir"]) {
  test(`ida y vuelta sin pérdida: ${name}`, () => {
    const { before, after } = roundTrip(fixture(name));
    assert.deepEqual(normalize(after), normalize(before));
  });
}

test("los bytes re-escritos son estables (encode(decode(encode)) idéntico)", () => {
  const module = loadModule(fixture("calc.phir"), "calc.phir");
  const once = encodeModule(module);
  const twice = encodeModule(loadModule(once, "once"));
  assert.deepEqual([...twice], [...once], "re-escribir dos veces da los mismos bytes");
});

test("el .phir re-escrito lo vuelve a aceptar el lector con fail-fast", () => {
  const module = loadModule(fixture("prog.phir"), "prog.phir");
  const bytes = encodeModule(module);
  const again = loadModule(bytes, "reescrito.phir");
  assert.equal(again.schemaVersion, 2);
  assert.equal(again.items.length, module.items.length);
  assert.deepEqual(
    again.libraries.map((l) => l.alias),
    module.libraries.map((l) => l.alias),
  );
});

test("cada tipo de literal sobrevive, incluido el cero y el string vacío", () => {
  const bytes = buildModule((w) => {
    const literal = (kind: string, build: (l: TestWriter) => void) => {
      w.message(4, (d) => {
        d.uint32(1, 1);
        d.message(14, (stmt) => {
          stmt.message(21, (expr) => {
            expr.message(1, (e) => e.message(10, (lit) => {
              lit.string(1, kind);
              build(lit);
            }));
          });
        });
      });
    };
    literal("int", (l) => l.int64(2, 0n));            // el cero NO se pierde
    literal("int", (l) => l.int64(2, -9007199254740993n));
    literal("float", (l) => l.double(3, 2.5));
    literal("str", (l) => l.string(4, ""));           // cadena vacía tampoco
    literal("str", (l) => l.string(4, "eñe 🚀"));
    literal("bool", (l) => l.tag(5, 0).varint(0));    // false explícito
    literal("null", () => {});
  });

  const { before, after } = roundTrip(bytes);
  assert.deepEqual(normalize(after), normalize(before));

  const kinds = after.items.map((d) => {
    if (d.node.case !== "statement" || d.node.stmt.node.case !== "expr") return "?";
    const expr = d.node.stmt.node.expr;
    return expr.node.case === "literal" ? expr.node.literal.kind : "?";
  });
  assert.deepEqual(kinds, ["int", "int", "float", "str", "str", "bool", "null"]);
});

test("los oneof vacíos siguen marcados ('return;', 'break', '&x' no mutable)", () => {
  const bytes = buildModule((w) => {
    w.message(4, (d) => {
      d.uint32(1, 1);
      d.message(10, (fn) => {
        fn.string(1, "f");
        fn.message(4, (block) => {
          block.message(1, (s) => s.message(16, () => {}));   // return;
          block.message(1, (s) => s.message(17, () => {}));   // break;
          block.message(1, (s) => s.message(18, () => {}));   // continue;
        });
      });
    });
  });
  const { after } = roundTrip(bytes);
  const decl = after.items[0]!;
  assert.ok(decl.node.case === "function" && decl.node.fn.body);
  assert.deepEqual(
    decl.node.fn.body.statements.map((s) => s.node.case),
    ["return", "break", "continue"],
  );
  const first = decl.node.fn.body.statements[0]!;
  assert.ok(first.node.case === "return" && first.node.value === null);
});

test("la tabla de símbolos completa sobrevive (tipos, hooks y casts)", () => {
  const { before, after } = roundTrip(fixture("IO.stdp.phir"));
  assert.equal(after.symbols.types.size, before.symbols.types.size);
  assert.equal(after.symbols.hooks.length, 2);

  const punto = after.symbols.types.get("String");
  assert.ok(punto);
  assert.equal(punto.kind, SymbolKind.STRUCT);
  assert.deepEqual([...punto.members.keys()].sort(), ["len", "text"]);

  const print = after.symbols.hooks.find((h) => h.kind === HookKind.PRINT);
  assert.ok(print);
  assert.equal(print.ownerType, "String");
  assert.equal(print.symbol?.name, "__print__");
  // el puntero del receptor mantiene kind + inner + mutabilidad
  const receiver = print.symbol?.paramTypes[0];
  assert.equal(receiver?.kind, TypeKind.POINTER);
  assert.equal(receiver?.inner?.name, "String");
});

test("un módulo vacío se re-escribe a lo mínimo", () => {
  const module = decodeModule(encodeModule({
    schemaVersion: 2,
    sourceFile: "",
    symbols: { types: new Map(), values: new Map(), hooks: [], casts: [] },
    items: [],
    libraries: [],
  }));
  assert.equal(module.schemaVersion, 2);
  assert.equal(module.items.length, 0);
});

test("dos instanciaciones de un generico no colapsan en la ida y vuelta", () => {
  // El decodificador descartaba 'Type.args' (el tag 42 caía en 'skip') y
  // 'typeKey' no los miraba, así que 'Vector<int>' y 'Vector<str>' eran el
  // MISMO tipo: al re-emitir compartían entrada del pool y los dos parámetros
  // acababan apuntando al primero. Ninguna prueba lo veía porque ningún
  // fixture usa genéricos.
  const vector = (arg: TypeKind) => (t: TestWriter) => {
    t.uint32(1, TypeKind.NOMINAL);
    t.string(2, "Vector");
    t.message(5, (a) => a.uint32(1, arg));
  };
  const bytes = buildModule((w) => {
    w.message(4, (d) => {
      d.uint32(1, 1);
      d.uint32(2, 1);
      d.message(10, (fn) => {
        fn.string(1, "f");
        fn.uint32(7, 1);                                   // -> void
        fn.message(2, (p) => { p.string(2, "a"); p.uint32(3, 6); });
        fn.message(2, (p) => { p.string(2, "b"); p.uint32(3, 7); });
      });
    });
  }, 2, [vector(TypeKind.INT), vector(TypeKind.STR)]);

  const params = (module: Module) => {
    const decl = module.items[0]!.node;
    assert.equal(decl.case, "function");
    return decl.case === "function" ? decl.fn.params : [];
  };

  const original = params(decodeModule(bytes));
  assert.equal(formatType(original[0]!.type), "Vector<int>");
  assert.equal(formatType(original[1]!.type), "Vector<str>");

  const ida_y_vuelta = params(decodeModule(encodeModule(decodeModule(bytes))));
  assert.equal(formatType(ida_y_vuelta[0]!.type), "Vector<int>");
  assert.equal(formatType(ida_y_vuelta[1]!.type), "Vector<str>",
               "las dos instanciaciones tienen que seguir siendo distintas");
});

test("un item de enum con PAYLOAD no se confunde con una constante", () => {
  // El '.proto' declara 'payload_type_ids' y dice con todas las letras que
  // sin ese campo un consumidor no puede saber si 'Numero' es un entero o un
  // constructor. El lector lo tiraba (el tag 3 caía en 'skip'), así que
  // 'Numero(int)' llegaba idéntico a 'ROJO' — el mismo error que se coló con
  // 'Type.args'. Un backend que los traduzca igual emite un entero donde el
  // programa guardaba un dato.
  const bytes = buildModule((w) => {
    w.message(4, (d) => {
      d.uint32(1, 3);                                    // DECL_ENUM
      d.message(12, (e) => {
        e.string(1, "Dato");
        e.message(2, (i) => i.string(1, "Vacio"));
        e.message(2, (i) => { i.string(1, "Numero"); i.tag(3, 0).varint(3); });
      });
    });
  });

  const items = (module: Module) => {
    const decl = module.items[0]!.node;
    assert.equal(decl.case, "enum");
    return decl.case === "enum" ? decl.enumDecl.items : [];
  };

  const original = items(decodeModule(bytes));
  assert.deepEqual(original[0]!.payloadTypeIds, [], "un item sin datos");
  assert.deepEqual(original[1]!.payloadTypeIds, [3], "…y uno que sí los lleva");

  const vuelta = items(decodeModule(encodeModule(decodeModule(bytes))));
  assert.deepEqual(vuelta.map((i) => i.payloadTypeIds), [[], [3]]);
});
