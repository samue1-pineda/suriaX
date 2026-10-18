/**
 * Índices y *module linker* del HIR — espejo de
 * `runtime/interpreter/loader.py` (Unit/Image/load_image) y
 * `runtime/interpreter/hook/dispatch.py` (índices de hooks/casts/dunders).
 *
 * Cada `.srcx`/`.libsrx` compila a SU propio `.phir`; un programa es la
 * unidad principal más las que referencia (`Module.libraries`), ligadas por
 * alias. Esa forma no es negociable desde el web: es la que emite el
 * frontend. Lo que sí cambia es el ACCESO al disco — en un navegador no
 * hay: las unidades llegan por un {@link PhirResolver} que el hospedador
 * implementa (fetch, IndexedDB, un `Map` en memoria, `fs` en node).
 *
 * Nada aquí ejecuta código: el linker resuelve NOMBRES, igual que el del
 * intérprete.
 */

import { loadModule } from "./decode.ts";
import {
  TypeKind,
  hookKey,
  typeKey,
  type FunctionDecl,
  type HookKind,
  type Module,
  type TestDecl,
  type Type,
} from "./schema.ts";

/** Una función con la unidad cuyos globales necesita (espejo de `BoundFunction`). */
export interface BoundFunction {
  readonly unit: Unit;
  readonly fn: FunctionDecl;
}

/** Cómo conseguir los bytes de una unidad referenciada. */
export type PhirResolver = (
  /** Ruta del `LibraryRef.phir`, relativa a `fromPath`. */
  relativePath: string,
  /** Ruta del `.phir` que la referencia. */
  fromPath: string,
) => Uint8Array | null;

/** El grafo de unidades no pudo cerrarse (falta un `.phir` referenciado). */
export class LinkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LinkError";
  }
}

/**
 * Une la ruta de un `.phir` con la de otro relativo a él. No se apoya en
 * `path` de node: el backend web corre en el navegador. Solo maneja lo que
 * el frontend emite (nombres planos y, a lo sumo, `./` o `../`).
 */
export function resolveRelative(fromPath: string, relative: string): string {
  if (relative.startsWith("/")) return relative;
  const slash = Math.max(fromPath.lastIndexOf("/"), fromPath.lastIndexOf("\\"));
  const dir = slash < 0 ? "" : fromPath.slice(0, slash);
  const parts: string[] = dir === "" ? [] : dir.split(/[/\\]/);
  for (const part of relative.split(/[/\\]/)) {
    if (part === "" || part === ".") continue;
    if (part === "..") parts.pop();
    else parts.push(part);
  }
  return parts.join("/");
}

/**
 * Una unidad HIR cargada, con los índices que el resto del backend
 * consulta en O(1). Se construyen UNA vez al cargar, no en cada consulta.
 */
export class Unit {
  /** Alias público (`IO.stdp`); la unidad principal usa `""`. */
  readonly alias: string;
  readonly path: string;
  readonly module: Module;
  /** Toda función invocable por nombre (incluidos los dunder; no los métodos de nombre llano). */
  readonly functions: ReadonlyMap<string, FunctionDecl>;
  /** Cuerpos de hook por `nombre#línea`: dos `__cast__` comparten nombre. */
  readonly dunderDecls: ReadonlyMap<string, FunctionDecl>;
  /** `enum` -> `{item -> valor}`, auto-numerado estilo C. */
  readonly enumValues: ReadonlyMap<string, ReadonlyMap<string, number>>;
  /** Bloques `test "..." { }` en orden de declaración. */
  readonly tests: readonly TestDecl[];

  constructor(alias: string, path: string, module: Module) {
    this.alias = alias;
    this.path = path;
    this.module = module;

    const functions = new Map<string, FunctionDecl>();
    const dunderDecls = new Map<string, FunctionDecl>();
    const enumValues = new Map<string, Map<string, number>>();
    const tests: TestDecl[] = [];

    for (const decl of module.items) {
      switch (decl.node.case) {
        case "function": {
          const fn = decl.node.fn;
          // un METODO de '@impl' de nombre llano ('dunder' igual al nombre)
          // no se llama por nombre: se despacha por (tipo, nombre), y aquí
          // pisaría a una 'fn' homónima del módulo. Misma regla que
          // 'runtime/interpreter/loader.py' (Unit.functions).
          if (fn.dunder === "" || fn.dunder !== fn.name) functions.set(fn.name, fn);
          if (fn.dunder !== "") dunderDecls.set(`${fn.name}#${decl.ln}`, fn);
          break;
        }
        case "test":
          tests.push(decl.node.test);
          break;
        case "enum": {
          // auto-numerado estilo C: el literal explícito reancla la cuenta.
          const values = new Map<string, number>();
          let next = 0;
          for (const item of decl.node.enumDecl.items) {
            const value = item.value;
            if (value !== null && value.node.case === "literal" &&
                value.node.literal.kind === "int") {
              next = Number(value.node.literal.value);
            }
            values.set(item.name, next);
            next++;
          }
          enumValues.set(decl.node.enumDecl.name, values);
          break;
        }
        default:
          break;
      }
    }

    this.functions = functions;
    this.dunderDecls = dunderDecls;
    this.enumValues = enumValues;
    this.tests = tests;
  }
}

/** Unidad principal + librerías ligadas: lo que el codegen web consume. */
export class Image {
  readonly main: Unit;
  /** alias -> unidad (la principal NO está: su alias es `""`). */
  readonly units: ReadonlyMap<string, Unit>;
  /** `(owner, kind)` -> cuerpo del hook. */
  readonly hooks: ReadonlyMap<string, BoundFunction>;
  /** `(tipo origen, tipo destino)` -> cuerpo del `__cast__`. */
  readonly casts: ReadonlyMap<string, BoundFunction>;
  /** `(owner, nombre)` -> método de usuario (`c.__bump__()`). */
  readonly dunders: ReadonlyMap<string, BoundFunction>;

  constructor(main: Unit, units: ReadonlyMap<string, Unit>) {
    this.main = main;
    this.units = units;
    const every = [main, ...units.values()];
    this.hooks = indexHooks(every);
    this.casts = indexCasts(every);
    this.dunders = indexDunders(every);
  }

  /** Todas las unidades, la principal primero (orden determinista). */
  get everyUnit(): readonly Unit[] {
    return [this.main, ...this.units.values()];
  }
}

/**
 * `HookEntry` de todas las unidades -> índice combinado. El cuerpo vive en
 * los `items` de SU unidad y se resuelve por `(nombre, línea)`. La primera
 * unidad que registra un `(owner, kind)` gana: mismo orden determinista que
 * la fusión de la Semántica.
 */
export function indexHooks(units: readonly Unit[]): ReadonlyMap<string, BoundFunction> {
  const index = new Map<string, BoundFunction>();
  for (const unit of units) {
    for (const entry of unit.module.symbols.hooks) {
      const key = hookKey(entry.ownerType, entry.kind);
      if (index.has(key) || entry.symbol === null) continue;
      const fn = unit.dunderDecls.get(`${entry.symbol.name}#${entry.symbol.ln}`);
      if (fn !== undefined) index.set(key, { unit, fn });
    }
  }
  return index;
}

/**
 * `SymbolTable.casts` -> índice `(origen, destino)`. El par es DERIVABLE de
 * la firma (`origen = paramTypes[0]`, `destino = type`): contrato del
 * esquema, no una convención de este lector.
 */
export function indexCasts(units: readonly Unit[]): ReadonlyMap<string, BoundFunction> {
  const index = new Map<string, BoundFunction>();
  for (const unit of units) {
    for (const sym of unit.module.symbols.casts) {
      const from = sym.paramTypes[0];
      if (from === undefined) continue;
      const key = `${typeKey(from)}->${typeKey(sym.type)}`;
      if (index.has(key)) continue;
      const fn = unit.dunderDecls.get(`${sym.name}#${sym.ln}`);
      if (fn !== undefined) index.set(key, { unit, fn });
    }
  }
  return index;
}

/**
 * Métodos de usuario (`dunder fn __x__(T ptr self, ...)`) -> `(owner,
 * nombre)`. El owner sale del PRIMER parámetro, desenvuelto hasta su
 * nominal; solo entran los que tienen CUERPO y receptor nominal.
 */
export function indexDunders(units: readonly Unit[]): ReadonlyMap<string, BoundFunction> {
  const index = new Map<string, BoundFunction>();
  for (const unit of units) {
    for (const decl of unit.module.items) {
      if (decl.node.case !== "function") continue;
      const fn = decl.node.fn;
      if (fn.dunder === "" || fn.body === null || fn.params.length === 0) continue;
      let receiver: Type | null = fn.params[0]!.type;
      while (
        receiver !== null &&
        (receiver.kind === TypeKind.POINTER || receiver.kind === TypeKind.NULLABLE)
      ) {
        receiver = receiver.inner;
      }
      if (receiver === null || receiver.kind !== TypeKind.NOMINAL) continue;
      const key = `${receiver.name}#${fn.name}`;
      if (!index.has(key)) index.set(key, { unit, fn });
    }
  }
  return index;
}

/** Consulta directa de un hook ligado. */
export function findHook(
  image: Image,
  ownerType: string,
  kind: HookKind,
): BoundFunction | null {
  return image.hooks.get(hookKey(ownerType, kind)) ?? null;
}

/**
 * Carga el `.phir` principal y TODAS sus unidades referenciadas
 * (transitivamente, una sola vez por alias).
 *
 * @param mainBytes bytes del `.phir` principal.
 * @param mainPath ruta con la que se resuelven las referencias relativas.
 * @param resolve cómo obtener cada unidad referenciada.
 * @throws {LinkError} si falta una unidad.
 * @throws {import("./decode.ts").HIRLoadError} si alguna no decodifica.
 */
export function linkImage(
  mainBytes: Uint8Array,
  mainPath: string,
  resolve: PhirResolver,
): Image {
  const main = new Unit("", mainPath, loadModule(mainBytes, mainPath));
  const units = new Map<string, Unit>();
  const pending: { from: Unit; alias: string; phir: string }[] =
    main.module.libraries.map((ref) => ({ from: main, alias: ref.alias, phir: ref.phir }));

  while (pending.length > 0) {
    const next = pending.pop()!;
    if (units.has(next.alias)) continue;
    const bytes = resolve(next.phir, next.from.path);
    if (bytes === null) {
      throw new LinkError(
        `la unidad '${next.alias}' referencia '${next.phir}' y no se pudo ` +
          `obtener junto a '${next.from.path}' — ¿se emitió con --emit-hir? ` +
          "(las unidades .phir viajan juntas)",
      );
    }
    const path = resolveRelative(next.from.path, next.phir);
    const unit = new Unit(next.alias, path, loadModule(bytes, path));
    units.set(next.alias, unit);
    for (const ref of unit.module.libraries) {
      pending.push({ from: unit, alias: ref.alias, phir: ref.phir });
    }
  }
  return new Image(main, units);
}
