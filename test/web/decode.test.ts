/**
 * Pruebas del deserializador contra `.phir` REALES (emitidos por el
 * compilador Python) y contra casos que solo se pueden construir a mano.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { HIRLoadError, decodeModule, loadModule } from "../../web/src/hir/decode.ts";
import { Image, Unit, linkImage, resolveRelative } from "../../web/src/hir/link.ts";
import {
  HookKind,
  SymbolKind,
  TypeKind,
  formatType,
  typeKey,
  type Type,
} from "../../web/src/hir/schema.ts";
import { Writer, buildModule, fixture, fixturePath, fixtureResolver } from "./helpers.ts";

test("fixture real: cabecera, símbolos e items", () => {
  const module = loadModule(fixture("prog.phir"), "prog.phir");

  assert.equal(module.schemaVersion, 2);
  assert.match(module.sourceFile, /\.srcx$/);
  assert.deepEqual(
    module.libraries.map((l) => l.alias).sort(),
    ["IO", "IO.stdp", "IO.stdpf"],
  );

  const functions = module.items
    .filter((d) => d.node.case === "function")
    .map((d) => (d.node.case === "function" ? d.node.fn.name : ""));
  assert.deepEqual(functions, ["suma", "nunca_usada", "main"]);

  // la tabla de símbolos viaja completa y con las firmas resueltas.
  const suma = module.symbols.values.get("suma");
  assert.ok(suma, "el símbolo 'suma' viaja en la tabla");
  assert.equal(suma.kind, SymbolKind.FUNCTION);
  assert.deepEqual(suma.paramTypes.map(formatType), ["int", "int"]);
  assert.equal(formatType(suma.type), "int");

  const punto = module.symbols.types.get("Punto");
  assert.ok(punto, "el struct 'Punto' viaja en el namespace de tipos");
  assert.equal(punto.kind, SymbolKind.STRUCT);
  assert.deepEqual([...punto.members.keys()].sort(), ["x", "y"]);
});

test("fixture real: el árbol de una función se reconstruye entero", () => {
  const module = loadModule(fixture("prog.phir"), "prog.phir");
  const decl = module.items.find(
    (d) => d.node.case === "function" && d.node.fn.name === "suma",
  );
  assert.ok(decl && decl.node.case === "function");
  const body = decl.node.fn.body;
  assert.ok(body, "'suma' tiene cuerpo");

  // return a + b;  (y una sentencia inalcanzable detrás)
  assert.equal(body.statements.length, 2);
  const first = body.statements[0]!;
  assert.equal(first.node.case, "return");
  if (first.node.case !== "return" || first.node.value === null) {
    assert.fail("el return trae valor");
  }
  const value = first.node.value;
  assert.equal(value.node.case, "binary");
  if (value.node.case !== "binary") return;
  assert.equal(value.node.op, "+");
  assert.equal(value.node.left.node.case, "identifier");
  assert.equal(formatType(value.restype), "int");
  assert.ok(first.ln > 0 && first.col > 0, "las posiciones viajan");
});

test("fixture real: literales, struct literal e interpolación de miembros", () => {
  const module = loadModule(fixture("prog.phir"), "prog.phir");
  const main = module.items.find(
    (d) => d.node.case === "function" && d.node.fn.name === "main",
  );
  assert.ok(main && main.node.case === "function" && main.node.fn.body);
  const stmts = main.node.fn.body.statements;

  const varDecl = stmts[0]!;
  assert.equal(varDecl.node.case, "varDecl");
  if (varDecl.node.case !== "varDecl") return;
  assert.equal(varDecl.node.name, "p");
  assert.equal(formatType(varDecl.node.type), "Punto");
  assert.equal(varDecl.node.value?.node.case, "structLiteral");
  if (varDecl.node.value?.node.case === "structLiteral") {
    assert.deepEqual([...varDecl.node.value.node.fieldNames], ["x", "y"]);
    assert.equal(varDecl.node.value.node.values.length, 2);
  }
});

test("fixture real: unidad de librería con hooks y punteros", () => {
  const module = loadModule(fixture("IO.stdp.phir"), "IO.stdp.phir");
  const unit = new Unit("IO.stdp", fixturePath("IO.stdp.phir"), module);

  assert.deepEqual(
    [...unit.functions.keys()].sort(),
    ["__len__", "__print__", "__write__", "print", "println"],
  );
  // los hooks viajan como (owner, kind) y su cuerpo se resuelve por (nombre, línea)
  const kinds = module.symbols.hooks.map((h) => h.kind).sort();
  assert.deepEqual(kinds, [HookKind.PRINT, HookKind.LEN].sort());
  const image = new Image(unit, new Map());
  assert.equal(image.hooks.size, 2, "ambos hooks quedan ligados a su cuerpo");
  assert.ok(image.dunders.has("String#__print__"));

  // 'String ptr s': el puntero llega con su mutabilidad y su inner.
  const printDecl = unit.functions.get("__print__");
  assert.ok(printDecl);
  const param = printDecl.params[0]!;
  assert.equal(param.type?.kind, TypeKind.POINTER);
  assert.equal(formatType(param.type), "String ptr");
  assert.equal(param.type?.inner?.name, "String");
});

test("linkImage liga la imagen completa desde el .phir principal", () => {
  const image = linkImage(fixture("prog.phir"), fixturePath("prog.phir"), fixtureResolver);
  assert.deepEqual([...image.units.keys()].sort(), ["IO", "IO.stdp", "IO.stdpf"]);
  assert.equal(image.everyUnit.length, 4);
  // los índices de la imagen combinan las unidades, como en el intérprete.
  assert.ok(image.dunders.has("String#__print__"));
  assert.ok(image.units.get("IO.stdp")!.functions.has("println"));
});

test("resolveRelative: nombres planos, ./ y ../", () => {
  assert.equal(resolveRelative("dumps/a.phir", "IO.phir"), "dumps/IO.phir");
  assert.equal(resolveRelative("dumps/a.phir", "./IO.phir"), "dumps/IO.phir");
  assert.equal(resolveRelative("dumps/sub/a.phir", "../IO.phir"), "dumps/IO.phir");
  assert.equal(resolveRelative("a.phir", "IO.phir"), "IO.phir");
});

test("schema_version desconocida: se rechaza antes de mirar el contenido", () => {
  const bytes = buildModule((w) => w.message(4, (d) => d.uint32(1, 1)), 99);
  assert.throws(() => loadModule(bytes, "futuro.phir"), (exc: unknown) => {
    assert.ok(exc instanceof HIRLoadError);
    assert.match(exc.message, /schema_version 99/);
    assert.match(exc.message, /futuro\.phir/);
    return true;
  });
  // decodeModule sí lo lee: es la vía explícita para inspeccionar.
  assert.equal(decodeModule(bytes).schemaVersion, 99);
});

test("bytes que no son un .phir: HIRLoadError con el origen", () => {
  const garbage = new Uint8Array([0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
                                  0xff, 0xff, 0xff, 0xff]);
  assert.throws(() => loadModule(garbage, "basura.bin"), (exc: unknown) => {
    assert.ok(exc instanceof HIRLoadError);
    assert.match(exc.message, /basura\.bin/);
    return true;
  });
});

test("módulo vacío: defaults de proto3, sin nulls sorpresa", () => {
  const module = decodeModule(new Writer().uint32(1, 1).finish());
  assert.equal(module.sourceFile, "");
  assert.equal(module.items.length, 0);
  assert.equal(module.libraries.length, 0);
  assert.equal(module.symbols.values.size, 0);
  assert.equal(module.symbols.hooks.length, 0);
});

test("un oneof sin variante se marca 'none', no se adivina", () => {
  const bytes = buildModule((w) => {
    w.message(4, (d) => {
      d.uint32(1, 3);
      d.uint32(2, 1);
      // ninguna variante del oneof
    });
  });
  const module = loadModule(bytes);
  assert.equal(module.items[0]!.node.case, "none");
  assert.equal(module.items[0]!.ln, 3);
});

test("typeKey distingue lo que el sistema de tipos distingue", () => {
  const int = { kind: TypeKind.INT, name: "", inner: null, mut: false, args: [] };
  const ptr = { kind: TypeKind.POINTER, name: "", mut: false, inner: int, args: [] };
  const ptrMut = { ...ptr, mut: true };
  assert.notEqual(typeKey(ptr), typeKey(ptrMut), "'ptr T' y 'ptr mutable T' difieren");
  assert.equal(typeKey(null), "");

  // Regresión: los argumentos de un genérico participan de la identidad del
  // tipo. Sin ellos en la clave, 'Vector<int>' y 'Vector<str>' compartían
  // entrada en el índice de conversiones y el genérico era decorativo.
  const str = { kind: TypeKind.STR, name: "", inner: null, mut: false, args: [] };
  const vecInt = { kind: TypeKind.NOMINAL, name: "Vector", inner: null,
                   mut: false, args: [int] };
  const vecStr = { ...vecInt, args: [str] };
  assert.notEqual(typeKey(vecInt), typeKey(vecStr),
                  "'Vector<int>' y 'Vector<str>' son tipos distintos");
  assert.equal(formatType(vecInt), "Vector<int>");
});

// --------------------------------------------------------------------------- //
// funciones como valores y métodos homónimos
// --------------------------------------------------------------------------- //

test("fixture real: el tipo función se lee y se escribe 'fn(A) -> R'", () => {
  const module = loadModule(fixture("funciones_valor.phir"), "funciones_valor.phir");
  const aplica = module.items.find(
    (d) => d.node.case === "function" && d.node.fn.name === "aplica");
  assert.ok(aplica !== undefined && aplica.node.case === "function");
  const f = aplica.node.fn.params[0]!.type!;
  assert.equal(f.kind, TypeKind.FUNCTION_TYPE);
  assert.equal(f.args.length, 1);
  assert.equal(f.inner!.kind, TypeKind.INT);
  assert.equal(formatType(f), "fn(int) -> int");
});

test("formatType: un tipo función envuelto va entre paréntesis (espejo de pretty.py)", () => {
  const t = (kind: TypeKind, inner: Type | null = null, args: Type[] = [], mut = false,
             name = ""): Type => ({ kind, name, inner, mut, args });
  const fn = t(TypeKind.FUNCTION_TYPE, t(TypeKind.INT), [t(TypeKind.INT), t(TypeKind.STR)]);
  assert.equal(formatType(fn), "fn(int, str) -> int");
  assert.equal(formatType(t(TypeKind.FUNCTION_TYPE, t(TypeKind.VOID))), "fn() -> void");
  assert.equal(formatType(t(TypeKind.NULLABLE, fn)), "(fn(int, str) -> int)?");
  assert.equal(formatType(t(TypeKind.POINTER, fn, [], true)), "(fn(int, str) -> int) ptr mutable");
  assert.equal(formatType(t(TypeKind.ERROR, fn)), "error (fn(int, str) -> int)");
  // dentro de los argumentos de un genérico o de otra función, sin paréntesis
  assert.equal(formatType(t(TypeKind.NOMINAL, null, [fn], false, "Caja")),
               "Caja<fn(int, str) -> int>");
  assert.equal(formatType(t(TypeKind.FUNCTION_TYPE, fn, [fn])),
               "fn(fn(int, str) -> int) -> fn(int, str) -> int");
});

test("un método de '@impl' de nombre llano no pisa a la 'fn' homónima del módulo", () => {
  // el método va DESPUÉS de la función en el fuente: con 'Map.set' a secas
  // quedaba el último declarado, que es el método
  const unit = new Unit("", "metodo_homonimo.phir",
                        loadModule(fixture("metodo_homonimo.phir"), "metodo_homonimo.phir"));
  const fn = unit.functions.get("distancia");
  assert.ok(fn !== undefined);
  assert.equal(fn.dunder, "");
  assert.equal(fn.params[0]!.type!.kind, TypeKind.INT);
});
