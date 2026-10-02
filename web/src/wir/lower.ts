/**
 * Lowering HIR -> WIR: la única fase del target web que TOMA DECISIONES.
 *
 * Resuelve nombres a índices, tipos nominales a tipos de máquina, y las
 * llamadas a la librería permitida a primitivas del host. Lo que no cabe en
 * el alcance v1 no se traduce "como se pueda": se rechaza con un diagnóstico
 * `WEB1xx` en su línea y columna, y el módulo no se genera. Misma disciplina
 * que la contención (`target/restrictions.ts`) y que el emisor del frontend.
 *
 * ### Sobre la librería `IO`
 * `stdp.println("hola")` no se compila bajando el cuerpo de `println` (esa
 * unidad es del host, ver `target/policy.ts`): se traduce al intrínseco
 * correspondiente. La tabla {@link IO_INTRINSICS} es la fuente única de esa
 * correspondencia — añadir `printf` fue una línea, y quitar `print` sería
 * otra.
 *
 * ### Sobre las sentencias de nivel de módulo
 * suriaX permite código suelto fuera de `main` (`a.srcx` es exactamente eso).
 * El intérprete lo ejecuta antes de la entrada; aquí se agrupa en una función
 * sintética `__module_init` que el host llama primero. Así el orden de
 * ejecución del web es el MISMO que el del intérprete, que es lo único que
 * hace comparables los dos.
 */

import { Severity, WebCode, DiagnosticBag, type Diagnostic } from "../diagnostics.ts";
import {
  TypeKind,
  type Block,
  type CaseArm,
  type Expr,
  type FunctionDecl,
  type IfStmt,
  type Module,
  type Stmt,
  type Type,
} from "../hir/schema.ts";
import type { Image } from "../hir/link.ts";
import { encodeUtf8 } from "../hir/write.ts";
import {
  WirBinOp,
  WirType,
  WirUnOp,
  isComparison,
  type WirExpr,
  type WirFunc,
  type WirGlobal,
  type WirHostImport,
  type WirLocal,
  type WirModule,
  type WirStmt,
  type WirString,
} from "./wir.ts";

/** Nombre de la función sintética que agrupa las sentencias de módulo. */
export const MODULE_INIT = "__module_init";

/**
 * Primitivas que aporta el host.
 *
 * `__write__` escribe `len` bytes de la memoria lineal; las demás escriben un
 * VALOR y **es el host quien lo formatea**. Esa es la decisión: formatear en
 * WASM exigiría escribir a mano la conversión de `float` a texto con las
 * mismas reglas que el intérprete (representación más corta que hace
 * round-trip, punto decimal siempre, exponente de dos dígitos), y una
 * divergencia de un dígito rompe el diferencial. Con el formateo en el host
 * hay UN solo sitio que decide cómo se ve un valor, y los dos backends del
 * web lo comparten.
 *
 * Se declaran solo las que el programa USA, en orden de primer uso: un
 * programa que solo imprime literales importa una sola función, igual que
 * antes de que las demás existieran. El objeto de imports del host va por
 * NOMBRE, así que el orden no le afecta.
 */
const HOST_IMPORTS: readonly WirHostImport[] = [
  { module: "env", name: "__write__", params: [WirType.I32, WirType.I32], result: WirType.VOID },
  { module: "env", name: "__write_int__", params: [WirType.I64], result: WirType.VOID },
  { module: "env", name: "__write_float__", params: [WirType.F64], result: WirType.VOID },
  { module: "env", name: "__write_bool__", params: [WirType.I32], result: WirType.VOID },
  { module: "env", name: "__write_char__", params: [WirType.I32], result: WirType.VOID },
  // Escribe una cadena por su ÍNDICE en la tabla de constantes del módulo.
  // No toma (puntero, longitud) como '__write__' porque el que la escribe es
  // el que la tiene guardada en una variable, y una variable no puede llevar
  // dos números; ver 'str' en `#valueType`.
  { module: "env", name: "__write_str__", params: [WirType.I32], result: WirType.VOID },
];

/** Identidad de cada primitiva en {@link HOST_IMPORTS}. */
export const Host = {
  WRITE: 0,
  WRITE_INT: 1,
  WRITE_FLOAT: 2,
  WRITE_BOOL: 3,
  WRITE_CHAR: 4,
  WRITE_STR: 5,
} as const;

/**
 * Funciones de la librería `IO` y su traducción. `newline` indica si tras
 * escribir el argumento hay que escribir un salto de línea — es toda la
 * diferencia entre `print` y `println` en `lib/io/stdp.libsrx`.
 */
export const IO_INTRINSICS: ReadonlyMap<string, { readonly newline: boolean }> = new Map([
  ["print", { newline: false }],
  ["println", { newline: true }],
  ["printf", { newline: false }],
]);

/** Un trozo de lo que se imprime: texto constante o un valor ya bajado. */
type PrintItem = { readonly text: string } | { readonly write: WirExpr };

export interface LowerResult {
  /** Módulo WIR listo para los backends, o `null` si hubo diagnósticos. */
  readonly module: WirModule | null;
  readonly diagnostics: readonly Diagnostic[];
}

/** Operadores de suriaX -> operadores del WIR. */
const BINARY_OPS: ReadonlyMap<string, WirBinOp> = new Map([
  ["+", WirBinOp.ADD], ["-", WirBinOp.SUB], ["*", WirBinOp.MUL],
  ["/", WirBinOp.DIV], ["%", WirBinOp.REM],
  ["==", WirBinOp.EQ], ["!=", WirBinOp.NE],
  ["<", WirBinOp.LT], ["<=", WirBinOp.LE],
  [">", WirBinOp.GT], [">=", WirBinOp.GE],
  // 'and'/'or' NO están: son de cortocircuito, y traducirlos a i32.and/i32.or
  // evaluaría siempre los dos lados. Un programa con 'a() and b()' se
  // comportaría distinto que en el intérprete. Entran cuando el WIR tenga
  // 'if' estructurado, no antes: mientras tanto dan WEB100.
]);

/**
 * Baja una imagen ya contenida y optimizada: la unidad principal Y las
 * librerías que la acompañan.
 *
 * Antes esto devolvía `lowerModule(image.main.module)` — las librerías se
 * tiraban. Por eso la única librería ejecutable era `IO`, y no porque el web
 * no pudiera traducirla: la sustituía el host. Una librería de funciones
 * corrientes (`math`) no tenía forma de llegar al WIR aunque no usara nada
 * que el target prohíba.
 *
 * Las unidades CONFIABLES (`policy.trustedUnits`, hoy el paquete `IO`) siguen
 * sin traducirse: su implementación la aporta el host, y sus cuerpos usan
 * punteros que el web no representa. `trusted` dice cuáles son.
 */
export function lowerImage(image: Image,
                           trusted: (alias: string) => boolean = () => false)
    : LowerResult {
  // Orden: librerías primero y el main al final, el MISMO que sigue el
  // intérprete al ejecutar el nivel de módulo (runtime/interpreter/
  // interpreter.run). Que los dos consumidores inicialicen en el mismo orden
  // es lo que hace comparables sus salidas.
  const units = [...image.units.values(), image.main]
    .filter((unit) => !trusted(unit.alias));
  return new Lowering(units, image.main.alias).run();
}

/** Baja un módulo HIR suelto al WIR (una sola unidad, sin librerías). */
export function lowerModule(module: Module): LowerResult {
  return new Lowering([{ alias: "", module } as LowerUnit], "").run();
}

/** Lo que el lowering necesita de una unidad: su alias y su HIR. */
interface LowerUnit {
  readonly alias: string;
  readonly module: Module;
}

/**
 * Cómo un nombre local de una unidad llega a otra unidad o a una función.
 *
 * Es la resolución que la Semántica YA hizo y que viaja en el HIR
 * (`ImportDirective.binding`/`unit`, `FromDirective`): aquí no se re-decide
 * nada, se lee. Es la misma regla que aplica `interpreter._run_module_level`,
 * y tiene que serlo — dos consumidores que ligan nombres distintos ejecutan
 * programas distintos.
 */
interface Bindings {
  /** nombre local -> alias de la unidad que nombra (`basic` -> `math.basic`). */
  readonly modules: Map<string, string>;
  /** nombre local -> función concreta de otra unidad (`#from m #import f`). */
  readonly functions: Map<string, { unit: string; name: string }>;
}

/** Alcance léxico: nombre -> índice de local. Se apila por bloque. */
interface Scope {
  readonly names: Map<string, number>;
  readonly parent: Scope | null;
}

function lookup(scope: Scope | null, name: string): number | null {
  for (let s = scope; s !== null; s = s.parent) {
    const index = s.names.get(name);
    if (index !== undefined) return index;
  }
  return null;
}

class Lowering {
  readonly #units: readonly LowerUnit[];
  readonly #mainAlias: string;
  /** alias de unidad -> cómo resuelve sus nombres importados. */
  readonly #bindings = new Map<string, Bindings>();
  /** alias de unidad -> sus funciones con cuerpo, por nombre. */
  readonly #byUnit = new Map<string, Map<string, FunctionDecl>>();
  /** unidad cuyo cuerpo se está bajando: decide contra qué se resuelve un nombre. */
  #unit = "";
  readonly #bag: DiagnosticBag;
  /** clave `unidad::función` -> índice en `funcs`. */
  readonly #funcIndex = new Map<string, number>();
  /** Firmas, para tipar las llamadas sin volver a mirar el HIR. */
  readonly #signatures: { params: WirType[]; result: WirType }[] = [];
  /** primitiva canónica -> su índice en `#hostImports` (orden de primer uso). */
  readonly #hostUsed = new Map<number, number>();
  readonly #hostImports: WirHostImport[] = [];
  /**
   * `Enum.ITEM` -> su entero, por nombre de enum.
   *
   * Un enum SIN payload es un entero con nombre: `Color.VERDE` no lleva datos,
   * así que en el WIR es una constante y `match` es una cadena de
   * comparaciones. El que SÍ lleva payload (`Numero(int)`) es otra cosa —un
   * tipo suma— y no se traduce: se rechaza con su posición, porque
   * representarlo como entero perdería el dato que transporta.
   */
  readonly #enums = new Map<string, Map<string, bigint>>();
  /** clave `unidad::nombre` -> índice en `#globals`. */
  readonly #globalIndex = new Map<string, number>();
  readonly #globals: WirGlobal[] = [];
  readonly #strings: WirString[] = [];
  readonly #stringByText = new Map<string, number>();
  #dataSize = 0;

  // --- estado de la función que se está bajando ---
  /**
   * Marco de la función: parámetros PRIMERO y variables después, en un solo
   * espacio de índices — que es exactamente como los numera WebAssembly
   * (`local.get 0` es el primer parámetro). Tener una sola lista evita el
   * clásico desajuste de mantener dos y sumarles el offset a mano.
   */
  #frame: WirLocal[] = [];
  #paramCount = 0;
  #scope: Scope | null = null;
  #result: WirType = WirType.VOID;
  /** Bucles abiertos: 'break'/'continue' sin bucle no tienen a dónde saltar. */
  #loopDepth = 0;

  constructor(units: readonly LowerUnit[], mainAlias: string) {
    this.#units = units;
    this.#mainAlias = mainAlias;
    const main = units.find((u) => u.alias === mainAlias) ?? units[units.length - 1];
    this.#bag = new DiagnosticBag(main?.module.sourceFile || "<módulo>");
  }

  /**
   * Índice de import de una primitiva del host, reservándolo al primer uso.
   *
   * Declarar las cinco siempre habría obligado a todo embebedor a aportar
   * cinco funciones para ejecutar un `println("hola")`. Reservar al usar
   * mantiene el contrato mínimo y no cuesta nada: el emisor pregunta por la
   * primitiva, no por su número.
   */
  #hostIndex(primitive: number): number {
    const existing = this.#hostUsed.get(primitive);
    if (existing !== undefined) return existing;
    const index = this.#hostImports.length;
    this.#hostUsed.set(primitive, index);
    this.#hostImports.push(HOST_IMPORTS[primitive]!);
    return index;
  }

  /** Clave del índice global de funciones. Un solo sitio la construye. */
  #key(unit: string, name: string): string {
    return `${unit}::${name}`;
  }

  /**
   * Lee del HIR cómo cada unidad ligó los nombres que importó.
   *
   * Espejo exacto de `interpreter._run_module_level`: el nombre local sale de
   * `binding || alias || lib` y la unidad de `unit || lib`; un `#from` cuyo
   * miembro es a su vez una unidad (`#from math #import basic` -> `math.basic`)
   * liga el SUBMÓDULO, que es la regla que hace funcionar los paquetes.
   */
  #collectBindings(): void {
    const known = new Set(this.#units.map((u) => u.alias));
    for (const unit of this.#units) {
      const modules = new Map<string, string>();
      const functions = new Map<string, { unit: string; name: string }>();
      for (const decl of unit.module.items) {
        if (decl.node.case === "import") {
          const d = decl.node.directive;
          const local = d.binding || d.alias || d.lib;
          if (local !== "") modules.set(local, d.unit || d.lib);
        } else if (decl.node.case === "from") {
          const d = decl.node.directive;
          const from = d.unit || d.lib;
          const local = d.alias || d.name;
          if (local === "") continue;
          const submodule = `${from}.${d.name}`;
          if (known.has(submodule)) modules.set(local, submodule);
          else functions.set(local, { unit: from, name: d.name });
        }
      }
      this.#bindings.set(unit.alias, { modules, functions });
    }
  }

  /**
   * Los enums de todas las unidades, con el entero de cada item.
   *
   * El valor lo fija el HIR cuando es explícito (`ROJO = 10`) y, cuando no,
   * es el ordinal — la misma regla del intérprete: el siguiente al anterior
   * empezando en cero. Recalcularla aquí es inevitable (el HIR guarda el
   * `Expr` solo del explícito) pero no es reinventarla: es la de C, la que
   * el lenguaje ya documenta.
   */
  #collectEnums(): void {
    for (const unit of this.#units) {
      for (const decl of unit.module.items) {
        if (decl.node.case !== "enum") continue;
        const items = new Map<string, bigint>();
        let siguiente = 0n;
        for (const item of decl.node.enumDecl.items) {
          if (item.payloadTypeIds.length > 0) {
            this.#unsupported(
              `el item '${decl.node.enumDecl.name}.${item.name}' lleva datos ` +
                "(el enum es un tipo suma, no un entero)",
              decl,
            );
            continue;
          }
          if (item.value !== null) {
            const literal = item.value.node;
            if (literal.case !== "literal" || literal.literal.kind !== "int") {
              this.#unsupported(
                `el valor de '${decl.node.enumDecl.name}.${item.name}' no es ` +
                  "un literal entero",
                decl,
              );
              continue;
            }
            siguiente = literal.literal.value;
          }
          items.set(item.name, siguiente);
          siguiente += 1n;
        }
        this.#enums.set(decl.node.enumDecl.name, items);
      }
    }
  }

  /**
   * Las variables de nivel de módulo -> globales del WIR.
   *
   * Antes se bajaban como LOCALES de `__module_init`, y por eso una función
   * no las veía: un local muere con su función. Son globales de verdad —las
   * ve todo el módulo y viven lo que él—, así que van a la sección de
   * globales, que es donde WebAssembly las guarda.
   *
   * El valor inicial de una global de WASM tiene que ser una CONSTANTE. Si
   * lo es, se pone ahí y no cuesta nada; si es una expresión (`LIMITE * 2`),
   * la global arranca a cero y `__module_init` le asigna el valor calculado,
   * que es lo mismo que hace el intérprete al ejecutar esa sentencia.
   */
  #collectGlobals(): void {
    for (const unit of this.#units) {
      this.#unit = unit.alias;
      for (const decl of unit.module.items) {
        if (decl.node.case !== "statement") continue;
        const stmt = decl.node.stmt.node;
        if (stmt.case !== "varDecl") continue;
        const type = this.#valueType(stmt.type, `la global '${stmt.name}'`, decl);
        const constante = this.#constanteDe(stmt.value, type, stmt.type);
        this.#globalIndex.set(this.#key(unit.alias, stmt.name),
                              this.#globals.length);
        this.#globals.push({
          name: this.#wirName(unit.alias, stmt.name),
          type,
          // mutable si el programa la reasigna O si su valor hay que
          // calcularlo: sin eso, el 'global.set' del init no validaría.
          mutable: stmt.qualifier !== "const" || constante === null,
          init: constante ?? (type === WirType.F64 ? 0 : 0n),
        });
      }
    }
    this.#unit = "";
  }

  /** El valor de `expr` si es una CONSTANTE que WASM admite como init. */
  #constanteDe(expr: Expr | null, tipo: WirType,
               declarado: Type | null): bigint | number | null {
    if (expr === null) return null;
    if (expr.node.case !== "literal") return null;
    const literal = expr.node.literal;
    if (literal.kind === "int") {
      return tipo === WirType.F64 ? Number(literal.value) : literal.value;
    }
    if (literal.kind === "float") return literal.value;
    if (literal.kind === "bool") return literal.value ? 1n : 0n;
    if (literal.kind === "char") {
      return BigInt(String(literal.value).codePointAt(0) ?? 0);
    }
    if (literal.kind === "str" && declarado?.kind === TypeKind.STR) {
      // una cadena es el ÍNDICE de su constante: eso sí es un entero
      return BigInt(this.#intern(String(literal.value)));
    }
    return null;
  }

  run(): LowerResult {
    this.#collectBindings();
    this.#collectEnums();
    this.#collectGlobals();

    // 1) índice de funciones de TODAS las unidades ANTES de bajar ningún
    //    cuerpo: una función puede llamar a otra declarada más abajo, o de
    //    otra unidad (el frontend ya lo validó).
    const declared: { unit: string; fn: FunctionDecl }[] = [];
    for (const unit of this.#units) {
      const funcs = new Map<string, FunctionDecl>();
      this.#byUnit.set(unit.alias, funcs);
      for (const decl of unit.module.items) {
        if (decl.node.case !== "function") continue;
        const fn = decl.node.fn;
        if (fn.body === null) continue;  // prototipo: lo aporta el host
        if (fn.dunder !== "") {
          this.#unsupported(`la función '${fn.name}' es un hook/dunder`, decl);
          continue;
        }
        funcs.set(fn.name, fn);
        this.#funcIndex.set(this.#key(unit.alias, fn.name), declared.length);
        declared.push({ unit: unit.alias, fn });
        this.#unit = unit.alias;
        this.#signatures.push({
          params: fn.params.map((p) => this.#valueType(p.type, `el parámetro '${p.name}'`, decl)),
          result: this.#valueType(fn.returnType, `el retorno de '${fn.name}'`, decl, true),
        });
      }
    }

    // 2) sentencias de nivel de módulo -> UN `__module_init` que las corre
    //    todas, librerías primero y el main al final: el mismo orden que el
    //    intérprete. El índice se reserva ANTES de bajar, por si alguna de
    //    ellas llama a una función.
    const withStmts = this.#units
      .map((unit) => ({
        unit,
        stmts: unit.module.items.filter((d) => d.node.case === "statement"),
      }))
      .filter((entry) => entry.stmts.length > 0);
    let initIndex: number | null = null;
    if (withStmts.length > 0) {
      initIndex = declared.length;
      this.#funcIndex.set(this.#key(this.#mainAlias, MODULE_INIT), initIndex);
      this.#signatures.push({ params: [], result: WirType.VOID });
    }

    // 3) cuerpos
    const funcs: WirFunc[] = [];
    for (let i = 0; i < declared.length; i++) {
      const entry = declared[i]!;
      this.#unit = entry.unit;
      funcs.push(this.#lowerFunction(entry.fn, this.#signatures[i]!,
                                     entry.unit));
    }
    if (initIndex !== null) {
      this.#frame = [];
      this.#paramCount = 0;
      this.#scope = { names: new Map(), parent: null };
      this.#result = WirType.VOID;
      this.#loopDepth = 0;
      const body: WirStmt[] = [];
      for (const { unit, stmts } of withStmts) {
        this.#unit = unit.alias;
        for (const decl of stmts) {
          if (decl.node.case !== "statement") continue;
          const stmt = decl.node.stmt.node;
          const global = stmt.case === "varDecl"
            ? this.#globalIndex.get(this.#key(unit.alias, stmt.name))
            : undefined;
          if (global !== undefined) {
            // ya está declarada como global; aquí solo se le da su valor, y
            // solo si no cabía como constante de inicialización.
            const entrada = this.#globals[global]!;
            if (stmt.case === "varDecl" && stmt.value !== null &&
                this.#constanteDe(stmt.value, entrada.type, stmt.type) === null) {
              body.push({
                kind: "global.set", pos: decl.node.stmt, index: global,
                value: this.#lowerExpr(stmt.value, entrada.type),
              });
            }
            continue;
          }
          this.#lowerStmt(decl.node.stmt, body);
        }
      }
      funcs.push({
        name: MODULE_INIT, params: [], locals: this.#frame,
        result: WirType.VOID, body, exported: true,
      });
    }

    const diagnostics = this.#bag.items;
    if (diagnostics.some((d) => d.severity === Severity.CRITICAL)) {
      return { module: null, diagnostics };
    }
    // la entrada es SIEMPRE la de la unidad principal: una librería puede
    // traer su propia 'main' sin que eso cambie qué programa se ejecuta.
    const entry = this.#funcIndex.get(this.#key(this.#mainAlias, "main"));
    return {
      module: {
        source: this.#units.find((u) => u.alias === this.#mainAlias)
                    ?.module.sourceFile ?? "",
        // solo las primitivas que el programa usa: un 'println("hola")'
        // importa una función, no cinco.
        imports: this.#hostImports,
        funcs,
        strings: this.#strings,
        globals: this.#globals,
        dataSize: this.#dataSize,
        entry: entry === undefined ? null : entry,
        init: initIndex,
      },
      diagnostics,
    };
  }

  // ------------------------------------------------------------------ //
  // diagnósticos
  // ------------------------------------------------------------------ //

  #unsupported(what: string, pos: { ln: number; col: number }): void {
    this.#bag.add(
      WebCode.CODEGEN_UNSUPPORTED,
      `${what}: el codegen del target web v2 traduce variables (locales y de ` +
        "módulo), aritmética, comparaciones, llamadas, control de flujo, " +
        "'match', 'cast' entre numéricos, enums sin payload y cadenas " +
        "constantes",
      pos,
    );
  }

  #badType(what: string, type: Type | null, pos: { ln: number; col: number }): void {
    const shown = type === null ? "desconocido" : `'${describeType(type)}'`;
    this.#bag.add(
      WebCode.CODEGEN_TYPE,
      `${what} es de tipo ${shown}, que el codegen del target web v2 no ` +
        "representa (int, float, bool, char, void, 'str' constante y los " +
        "'enum' sin payload sí; un struct o un puntero, no)",
      pos,
    );
  }

  // ------------------------------------------------------------------ //
  // tipos
  // ------------------------------------------------------------------ //

  #valueType(
    type: Type | null,
    what: string,
    pos: { ln: number; col: number },
    allowVoid = false,
  ): WirType {
    if (type === null) {
      this.#badType(what, type, pos);
      return WirType.I64;
    }
    switch (type.kind) {
      case TypeKind.INT: return WirType.I64;
      case TypeKind.FLOAT: return WirType.F64;
      case TypeKind.BOOL: return WirType.I32;
      case TypeKind.CHAR: return WirType.I32;
      case TypeKind.VOID:
        if (allowVoid) return WirType.VOID;
        this.#badType(what, type, pos);
        return WirType.I64;
      case TypeKind.STR: return WirType.I32;
      case TypeKind.NOMINAL:
        // Un enum SIN payload es un entero con nombre: cabe en el WIR tal
        // cual. Cualquier otro nominal (un struct) no, y por eso se pregunta
        // por la tabla en vez de aceptar todo lo nominal.
        if (this.#enums.has(type.name)) return WirType.I64;
        this.#badType(what, type, pos);
        return WirType.I64;
      default:
        this.#badType(what, type, pos);
        return WirType.I64;
    }
  }

  // ------------------------------------------------------------------ //
  // funciones
  // ------------------------------------------------------------------ //

  /**
   * Nombre de la función en el WIR.
   *
   * Las de una librería van CUALIFICADAS con su unidad (`math.basic.add`).
   * No es cosmético: dos unidades pueden declarar `max`, y el nombre acaba
   * siendo el del export de WebAssembly, donde repetirlo produce un módulo
   * inválido. Un identificador de suriaX no puede contener `.`, así que
   * cualificar es suficiente para que nunca choque con un nombre del usuario.
   */
  #wirName(unit: string, name: string): string {
    return unit === this.#mainAlias ? name : `${unit}.${name}`;
  }

  #lowerFunction(fn: FunctionDecl, signature: { params: WirType[]; result: WirType },
                 unit: string): WirFunc {
    const params: WirLocal[] = fn.params.map((p, i) => ({
      name: p.name,
      type: signature.params[i] ?? WirType.I64,
    }));
    this.#frame = [...params];
    this.#paramCount = params.length;
    this.#result = signature.result;
    this.#loopDepth = 0;
    const names = new Map<string, number>();
    params.forEach((p, i) => names.set(p.name, i));
    this.#scope = { names, parent: null };

    const body: WirStmt[] = [];
    if (fn.body !== null) this.#lowerBlock(fn.body, body);

    return {
      name: this.#wirName(unit, fn.name),
      params,
      // solo los declarados: los parámetros ya viajan aparte y WASM los
      // numera antes que ellos.
      locals: this.#frame.slice(this.#paramCount),
      result: signature.result,
      body,
      exported: true,
    };
  }

  #lowerBlock(block: Block, out: WirStmt[]): void {
    const saved = this.#scope;
    this.#scope = { names: new Map(), parent: saved };
    for (const stmt of block.statements) this.#lowerStmt(stmt, out);
    this.#scope = saved;
  }

  /**
   * Declara un local NUEVO aunque el nombre ya exista: dos `var x` en bloques
   * distintos son dos locales distintos, y el scope decide cuál ve cada uso.
   * WASM no tiene scopes, así que aquí es donde se resuelve el sombreado.
   */
  #declareLocal(name: string, type: WirType): number {
    const index = this.#frame.length;
    this.#frame.push({ name, type });
    this.#scope?.names.set(name, index);
    return index;
  }

  // ------------------------------------------------------------------ //
  // sentencias
  // ------------------------------------------------------------------ //

  #lowerStmt(stmt: Stmt, out: WirStmt[]): void {
    const node = stmt.node;
    switch (node.case) {
      case "varDecl": {
        const type = this.#valueType(node.type, `la variable '${node.name}'`, stmt);
        // El inicializador se baja ANTES de declarar el local: 'var int x = x'
        // debe resolver la 'x' de fuera, no la que se está declarando.
        const value = node.value === null
          // Una cadena es un ÍNDICE, y el índice 0 es la primera constante
          // del programa, no la vacía: 'var str s;' se inicializa internando
          // "" en vez de heredar el texto que otro escribió antes.
          ? (node.type?.kind === TypeKind.STR
              ? { kind: "const", type: WirType.I32,
                  value: BigInt(this.#intern("")) } as WirExpr
              : zeroOf(type))
          : this.#lowerExpr(node.value, type);
        const index = this.#declareLocal(node.name, type);
        // Sin inicializador se emite el cero EXPLÍCITO. WASM solo pone a cero
        // los locales al ENTRAR en la función, y un 'var' dentro de un bucle
        // se declara en cada vuelta: sin este local.set conservaría el valor
        // de la iteración anterior.
        out.push({ kind: "local.set", pos: stmt, index, value });
        return;
      }

      case "expr": {
        const expr = node.expr;
        // 'x = 1;' llega como ExprStmt(Assignment): es una asignación, no un
        // valor que se descarta.
        if (expr.node.case === "assignment") {
          const target = expr.node.target;
          if (target.node.case !== "identifier") {
            this.#unsupported("asignar a algo que no es una variable", expr);
            return;
          }
          const index = lookup(this.#scope, target.node.name);
          if (index === null) {
            const global = this.#globalIndex.get(
              this.#key(this.#unit, target.node.name));
            if (global === undefined) {
              this.#unsupported(
                `la variable '${target.node.name}' no está en alcance`, expr);
              return;
            }
            out.push({
              kind: "global.set", pos: stmt, index: global,
              value: this.#lowerExpr(expr.node.value, this.#globals[global]!.type),
            });
            return;
          }
          const type = this.#typeOfLocal(index);
          out.push({
            kind: "local.set", pos: stmt, index,
            value: this.#lowerExpr(expr.node.value, type),
          });
          return;
        }
        const value = this.#lowerExpr(expr, null);
        out.push({ kind: "drop", pos: stmt, value });
        return;
      }

      case "return":
        out.push({
          kind: "return", pos: stmt,
          value: node.value === null ? null : this.#lowerExpr(node.value, this.#result),
        });
        return;

      case "block":
        this.#lowerBlock(node.block, out);
        return;

      case "if":
        out.push(this.#lowerIf(node.ifStmt, stmt));
        return;

      case "while": {
        const condition = this.#condition(node.condition, "la condición del 'while'");
        const body: WirStmt[] = [];
        this.#loopDepth++;
        this.#lowerBlock(node.body, body);
        this.#loopDepth--;
        out.push({ kind: "while", pos: stmt, condition, body });
        return;
      }

      case "match": {
        out.push(...this.#lowerMatch(node.subject, node.cases, stmt));
        return;
      }

      case "break":
      case "continue":
        if (this.#loopDepth === 0) {
          // la Semántica ya lo habría rechazado; aquí es defensa en
          // profundidad: sin bucle no hay etiqueta a la que saltar y el
          // binario saldría mal formado.
          this.#unsupported(`'${node.case}' fuera de un bucle`, stmt);
          return;
        }
        out.push({ kind: node.case, pos: stmt });
        return;

      case "none":
        this.#bag.add(
          WebCode.MALFORMED_NODE,
          "una sentencia llegó sin variante en el HIR", stmt,
        );
        return;

      default:
        this.#unsupported(`la sentencia '${node.case}'`, stmt);
        return;
    }
  }

  /**
   * El entero de `Enum.ITEM`, o `null` si eso no es un item de enum.
   *
   * `obj` tiene que ser el NOMBRE del enum: `Color.VERDE` sí, `p.campo` no.
   * Que un local se llame igual que un enum no puede confundirlos, porque un
   * local se resuelve como `identifier` antes de llegar aquí.
   */
  #enumMember(obj: Expr, member: string): bigint | null {
    if (obj.node.case !== "identifier") return null;
    const items = this.#enums.get(obj.node.name);
    if (items === undefined) return null;
    return items.get(member) ?? null;
  }

  /**
   * `match` -> el sujeto en un local y una cadena de `if / else if`.
   *
   * WebAssembly no tiene una tabla de saltos que sirva aquí: `br_table` es
   dense —una entrada por cada valor entre el mínimo y el máximo— y un enum
   * con valores explícitos (`ROJO = 1, AZUL = 400`) generaría cuatrocientas
   * entradas para tres casos. La cadena de comparaciones no tiene ese
   * problema y es lo que el `if/else` ya sabe emitir.
   *
   * El sujeto se evalúa UNA vez y se guarda: `match (siguiente())` no puede
   * llamar a `siguiente` una vez por caso. Ese local es el único que este
   * lowering inventa, y lleva un nombre que no puede chocar con uno del
   * programa (`match` es palabra reservada, así que `match$N` no es
   * escribible en suriaX).
   *
   * No inserta ningún caso por defecto: la exhaustividad la comprueba la
   * Semántica (SEM030), y añadir aquí una rama vacía sería taparle el
   * trabajo. Un `match` no exhaustivo simplemente no hace nada — que es lo
   * mismo que hace el intérprete.
   */
  #lowerMatch(subject: Expr, cases: readonly CaseArm[],
              pos: { ln: number; col: number }): WirStmt[] {
    const tipo = this.#valueType(subject.restype, "el sujeto del 'match'", pos);
    if (tipo === WirType.F64) {
      // comparar floats por igualdad es una trampa, y ningún 'match' del
      // lenguaje lo necesita: los sujetos son enteros, chars, bools o enums.
      this.#unsupported("un 'match' sobre un 'float'", pos);
      return [];
    }
    const index = this.#declareLocal(`match$${this.#frame.length}`, tipo);
    const salida: WirStmt[] = [
      { kind: "local.set", pos, index, value: this.#lowerExpr(subject, tipo) },
    ];

    // se construye de ATRÁS hacia adelante: cada caso envuelve al siguiente
    // en su rama 'else', que es la forma que tiene el WIR de encadenarlos.
    let resto: WirStmt[] = [];
    for (let i = cases.length - 1; i >= 0; i--) {
      const arm = cases[i]!;
      const cuerpo: WirStmt[] = [];
      this.#lowerStmt(arm.body, cuerpo);
      const condicion: WirExpr = {
        kind: "binary",
        type: WirType.I32,
        op: WirBinOp.EQ,
        operandType: tipo,
        left: { kind: "local.get", type: tipo, index },
        right: this.#lowerExpr(arm.pattern, tipo),
      };
      resto = [{
        kind: "if", pos: arm.pattern, condition: condicion,
        then: cuerpo, otherwise: resto,
      }];
    }
    salida.push(...resto);
    return salida;
  }

  /** Tipo del local `index` (parámetros y variables, mismo espacio). */
  #typeOfLocal(index: number): WirType {
    return this.#frame[index]?.type ?? WirType.I64;
  }

  /**
   * `if` con su cadena de `else if`. El HIR la trae anidada
   * (`elseBranch.case === "if"`) y aquí se conserva anidada: en WASM un
   * `else if` ES un `if` dentro del `else`, no hay forma más plana.
   */
  /**
   * Condición de un `if`/`while`. WebAssembly exige **i32** ahí: si llegara
   * un `i64` o un `f64`, el binario no validaría. La Semántica ya obliga a
   * que sea `bool`, así que esto es defensa en profundidad — pero un
   * diagnóstico con posición es infinitamente mejor que un módulo que el
   * navegador rechaza con un offset de bytes.
   */
  #condition(expr: Expr, what: string): WirExpr {
    const lowered = this.#lowerExpr(expr, WirType.I32);
    if (lowered.type !== WirType.I32) {
      this.#badType(what, expr.restype, expr);
    }
    return lowered;
  }

  #lowerIf(node: IfStmt, at: Stmt): WirStmt {
    const condition = this.#condition(node.condition, "la condición del 'if'");
    const then: WirStmt[] = [];
    this.#lowerBlock(node.thenBlock, then);

    const otherwise: WirStmt[] = [];
    switch (node.elseBranch.case) {
      case "block":
        this.#lowerBlock(node.elseBranch.block, otherwise);
        break;
      case "if":
        otherwise.push(this.#lowerIf(node.elseBranch.ifStmt, at));
        break;
      case "none":
        break;
    }
    return { kind: "if", pos: at, condition, then, otherwise };
  }

  // ------------------------------------------------------------------ //
  // expresiones
  // ------------------------------------------------------------------ //

  /**
   * @param expected tipo que el contexto espera (`null` = el que salga). No
   *   se COERCIONA nada —suriaX no tiene coerciones implícitas—: sirve para
   *   tipar los literales enteros que también valen como `float`.
   */
  #lowerExpr(expr: Expr, expected: WirType | null): WirExpr {
    const node = expr.node;
    switch (node.case) {
      case "literal": {
        const literal = node.literal;
        switch (literal.kind) {
          case "int":
            return expected === WirType.F64
              ? { kind: "const", type: WirType.F64, value: Number(literal.value) }
              : { kind: "const", type: WirType.I64, value: literal.value };
          case "float":
            return { kind: "const", type: WirType.F64, value: literal.value };
          case "bool":
            return { kind: "const", type: WirType.I32, value: literal.value ? 1n : 0n };
          case "char": {
            // el code point, no la unidad UTF-16: 'codePointAt' respeta los
            // pares suplentes y un char de suriaX es siempre uno solo.
            const text = String(literal.value);
            return {
              kind: "const", type: WirType.I32,
              value: BigInt(text.codePointAt(0) ?? 0),
            };
          }
          case "str":
            // el índice de la constante, no su texto: ver `#valueType`.
            return {
              kind: "const", type: WirType.I32,
              value: BigInt(this.#intern(String(literal.value))),
            };
          default:
            this.#unsupported(`el literal '${literal.kind}'`, expr);
            return { kind: "const", type: WirType.I64, value: 0n };
        }
      }

      case "identifier": {
        const index = lookup(this.#scope, node.name);
        if (index !== null) {
          return { kind: "local.get", type: this.#typeOfLocal(index), index };
        }
        const global = this.#globalIndex.get(this.#key(this.#unit, node.name));
        if (global !== undefined) {
          return {
            kind: "global.get", type: this.#globals[global]!.type, index: global,
          };
        }
        this.#unsupported(`'${node.name}' no es una variable en alcance`, expr);
        return { kind: "const", type: WirType.I64, value: 0n };
      }

      case "binary": {
        // 'and'/'or' NO son binarios: cortocircuitan (ver WirExpr.logical).
        if (node.op === "and" || node.op === "or") {
          return {
            kind: "logical",
            type: WirType.I32,
            op: node.op,
            left: this.#condition(node.left, `el lado izquierdo de '${node.op}'`),
            right: this.#condition(node.right, `el lado derecho de '${node.op}'`),
          };
        }
        const op = BINARY_OPS.get(node.op);
        if (op === undefined) {
          this.#unsupported(`el operador '${node.op}'`, expr);
          return { kind: "const", type: WirType.I64, value: 0n };
        }
        // Sobre CADENAS solo valen '=='/'!='. Una cadena es el índice de una
        // constante, y sobre índices la igualdad SÍ da la respuesta correcta
        // (dos literales de igual texto comparten índice: se interna por
        // texto) pero el orden no: los índices van por orden de APARICIÓN en
        // el programa, no alfabético, y 'a < b' contestaría que sí según
        // dónde se escribió cada literal. Y '+' es concatenar, que necesita
        // memoria dinámica. Emitir una suma de índices habría dado un número
        // que parece una cadena y no lo es — un error mudo, el peor de todos.
        if (node.left.restype?.kind === TypeKind.STR ||
            node.right.restype?.kind === TypeKind.STR) {
          if (op !== WirBinOp.EQ && op !== WirBinOp.NE) {
            this.#bag.add(
              WebCode.CODEGEN_STRING,
              `el operador '${node.op}' sobre cadenas: el target web v1 ` +
                "representa cada cadena por su índice de constante, con el " +
                "que solo '=='/'!=' contestan bien; concatenar y comparar " +
                "por orden necesitan el runtime de cadenas, que aún no existe",
              expr,
            );
            return { kind: "const", type: WirType.I32, value: 0n };
          }
        }
        // el tipo de los OPERANDOS manda: en 'a < b' el resultado es bool
        // pero la instrucción depende de si a y b son i64 o f64.
        const operandType = this.#operandType(node.left, node.right, expr);
        const left = this.#lowerExpr(node.left, operandType);
        const right = this.#lowerExpr(node.right, operandType);
        return {
          kind: "binary",
          type: isComparison(op) ? WirType.I32 : operandType,
          op, operandType, left, right,
        };
      }

      case "unary": {
        if (node.op === "not" || node.op === "!") {
          return {
            kind: "unary", type: WirType.I32, op: WirUnOp.NOT,
            operand: this.#lowerExpr(node.operand, WirType.I32),
          };
        }
        if (node.op === "-") {
          const operand = this.#lowerExpr(node.operand, expected);
          return { kind: "unary", type: operand.type, op: WirUnOp.NEG, operand };
        }
        this.#unsupported(`el operador unario '${node.op}'`, expr);
        return { kind: "const", type: WirType.I64, value: 0n };
      }

      case "call":
        return this.#lowerCall(expr, node.callee, node.args);

      case "assignment":
        this.#unsupported("una asignación usada como valor", expr);
        return { kind: "const", type: WirType.I64, value: 0n };

      case "member": {
        // 'Color.VERDE': el único acceso a miembro que el codegen traduce.
        // Un enum sin payload es un entero con nombre, así que su item ES una
        // constante; el acceso a un campo de struct es otra cosa (una lectura
        // de memoria) y sigue sin traducirse.
        const valor = this.#enumMember(node.obj, node.member);
        if (valor !== null) {
          return { kind: "const", type: WirType.I64, value: valor };
        }
        this.#unsupported(`el acceso al miembro '${node.member}'`, expr);
        return { kind: "const", type: WirType.I64, value: 0n };
      }

      case "cast": {
        const destino = this.#valueType(node.type, "el destino del 'cast'", expr);
        const origen = this.#valueType(
          node.value.restype, "el valor del 'cast'", expr);
        if (node.hook !== null) {
          // un '__cast__' declarado por el usuario es una LLAMADA, no un
          // cambio de representación: el web todavía no la resuelve.
          this.#unsupported(
            "un 'cast' que invoca un '__cast__' declarado", expr);
          return { kind: "const", type: destino, value: 0n };
        }
        if (node.type?.kind === TypeKind.STR ||
            node.value.restype?.kind === TypeKind.STR) {
          // 'cast<str>(7)' FABRICA una cadena: no cambia de representación,
          // la construye. Sin runtime de cadenas no hay dónde ponerla — y
          // como aquí 'str' es un índice, convertir el 7 daría el índice 7,
          // que apunta a una constante cualquiera del programa.
          this.#bag.add(
            WebCode.CODEGEN_STRING,
            "un 'cast' de o hacia 'str': el target web v1 solo maneja " +
              "cadenas CONSTANTES (las que están escritas en el programa); " +
              "fabricar una necesita el runtime de cadenas, que aún no existe",
            expr,
          );
          return { kind: "const", type: destino, value: 0n };
        }
        const value = this.#lowerExpr(node.value, origen);
        if (origen === destino) return value;   // 'cast<int>(int)': nada que hacer
        return { kind: "convert", type: destino, from: origen, value };
      }

      case "none":
        this.#bag.add(WebCode.MALFORMED_NODE, "una expresión llegó sin variante", expr);
        return { kind: "const", type: WirType.I64, value: 0n };

      default:
        this.#unsupported(`la expresión '${node.case}'`, expr);
        return { kind: "const", type: WirType.I64, value: 0n };
    }
  }

  /** Tipo común de los operandos de un binario, tomado de sus `restype`. */
  #operandType(left: Expr, right: Expr, at: Expr): WirType {
    const fromLeft = wirTypeOf(left.restype);
    const fromRight = wirTypeOf(right.restype);
    if (fromLeft !== null) return fromLeft;
    if (fromRight !== null) return fromRight;
    this.#badType("el operando", left.restype, at);
    return WirType.I64;
  }

  // ------------------------------------------------------------------ //
  // llamadas
  // ------------------------------------------------------------------ //

  #lowerCall(expr: Expr, callee: Expr, args: readonly Expr[]): WirExpr {
    const bindings = this.#bindings.get(this.#unit);

    // 'basic.add(2.0, 3.0)' / 'stdp.println("hola")': el nombre de la
    // izquierda es una UNIDAD ligada. Si la unidad no se tradujo (es
    // confiable: la implementa el host) la llamada va a su intrínseco; si sí
    // se tradujo, es una llamada normal a su función.
    if (callee.node.case === "member") {
      const member = callee.node.member;
      const base = callee.node.obj;
      // Una VARIABLE le gana al import que se llame igual: 'var int stdp = 3;
      // stdp.println(...)' no es una llamada al módulo, es un acceso a miembro
      // sobre un entero — y el intérprete lo rechaza con RT011. Sin esta
      // comprobación el web resolvía el módulo igual y ejecutaba el println,
      // así que el mismo programa hacía cosas distintas según quién lo
      // corriera.
      const sombreado = base.node.case === "identifier" &&
        lookup(this.#scope, base.node.name) !== null;
      const unit = base.node.case === "identifier" && !sombreado
        ? bindings?.modules.get(base.node.name)
        : undefined;
      if (unit !== undefined) {
        const index = this.#funcIndex.get(this.#key(unit, member));
        if (index !== undefined) return this.#call(index, expr, args);
      }
      const intrinsic = sombreado ? undefined : IO_INTRINSICS.get(member);
      if (intrinsic === undefined) {
        this.#unsupported(
          sombreado
            ? `'${(base.node as { name: string }).name}' es una variable, no un ` +
              `módulo: '.${member}' sobre su valor`
            : `la llamada a '${member}'`,
          expr);
        return { kind: "const", type: WirType.VOID, value: 0n };
      }
      return this.#lowerPrint(expr, args, intrinsic.newline);
    }

    if (callee.node.case !== "identifier") {
      this.#unsupported("una llamada cuyo destino no es un nombre", expr);
      return { kind: "const", type: WirType.I64, value: 0n };
    }

    const name = callee.node.name;
    // Un nombre pelado se busca en ESTA unidad primero: una función propia
    // gana siempre sobre lo que se importó, que es la misma regla del
    // frontend (una función del usuario con el nombre de una de librería
    // gana).
    const own = this.#funcIndex.get(this.#key(this.#unit, name));
    if (own !== undefined) return this.#call(own, expr, args);

    // ...y si no, contra lo que un '#from lib #import f' trajo al ámbito.
    const imported = bindings?.functions.get(name);
    if (imported !== undefined) {
      const index = this.#funcIndex.get(this.#key(imported.unit, imported.name));
      if (index !== undefined) return this.#call(index, expr, args);
    }

    // 'print(x)' sin cualificar (import de miembro) también es del host.
    const intrinsic = IO_INTRINSICS.get(name);
    if (intrinsic !== undefined) {
      return this.#lowerPrint(expr, args, intrinsic.newline);
    }

    this.#unsupported(`la llamada a '${name}' (sin cuerpo en esta imagen)`, expr);
    return { kind: "const", type: WirType.I64, value: 0n };
  }

  /** Llamada ya resuelta a un índice del WIR. */
  #call(index: number, expr: Expr, args: readonly Expr[]): WirExpr {
    const signature = this.#signatures[index]!;
    const lowered = args.map((arg, i) => this.#lowerExpr(arg, signature.params[i] ?? null));
    return { kind: "call", type: signature.result, func: index, args: lowered };
  }

  /**
   * `print`/`println`/`printf` de un literal de cadena. El texto va a la
   * memoria lineal y la llamada pasa `(offset, longitud)` al host — el mismo
   * contrato que `__write__` en `lib/io/stdp.libsrx`.
   */
  /**
   * `print` / `println` / `printf`: escribe el argumento y, si toca, el salto.
   *
   * No construye una cadena: ESCRIBE en orden. Un f-string se convierte en
   * una secuencia —texto literal, valor, texto literal…— y cada valor va a la
   * primitiva del host que corresponde a su tipo, que es quien lo formatea.
   * Sin runtime de cadenas (memoria dinámica, concatenación y formateo de
   * `float` a mano en WASM) esta es la forma honesta de imprimir un valor
   * calculado, y de paso ahorra la reserva que ese runtime haría solo para
   * tirarla al terminar la sentencia.
   *
   * Una cadena guardada en una variable SÍ viaja: es el índice de su
   * constante y el host la escribe mirando la tabla (`__write_str__`). Lo que
   * sigue sin soporte es la cadena CALCULADA (`a + b`, `cast<str>(x)`): esa
   * hay que fabricarla, y fabricarla necesita el runtime. Da `WEB102`.
   */
  #lowerPrint(expr: Expr, args: readonly Expr[], newline: boolean): WirExpr {
    const items: PrintItem[] = [];
    const first = args[0];
    if (first !== undefined) this.#printItems(first, items);
    if (newline) items.push({ text: "\n" });

    // Los textos CONTIGUOS se funden en uno: 'println("hola")' sigue siendo
    // una sola escritura de "hola\n" —exactamente lo que hacía antes— y un
    // f-string no paga una llamada por segmento. La fusión va aquí y no en
    // los emisores porque es una propiedad del programa, no del target.
    const writes: WirExpr[] = [];
    let pending = "";
    const flush = () => {
      if (pending !== "") {
        writes.push(this.#writeText(pending));
        pending = "";
      }
    };
    for (const item of items) {
      if ("text" in item) pending += item.text;
      else { flush(); writes.push(item.write); }
    }
    flush();

    if (writes.length === 0) return { kind: "const", type: WirType.VOID, value: 0n };
    if (writes.length === 1) return writes[0]!;
    return { kind: "seq", type: WirType.VOID, exprs: writes };
  }

  /** Descompone lo que se va a imprimir en textos constantes y valores. */
  #printItems(value: Expr, out: PrintItem[]): void {
    if (value.node.case === "literal" &&
        (value.node.literal.kind === "str" || value.node.literal.kind === "char")) {
      out.push({ text: String(value.node.literal.value) });
      return;
    }
    // f-string: sus segmentos, en orden.
    if (value.node.case === "interp") {
      for (const part of value.node.parts) {
        if (part.case === "text") {
          out.push({ text: part.text });
        } else if (part.repr || (part.spec ?? "") !== "") {
          // ignorarlo imprimiría otro texto sin decir nada
          this.#bag.add(
            WebCode.CODEGEN_STRING,
            "el formato de una interpolación ('!r', ':08b', ':.2f'...) todavía " +
              "no lo tiene el target web v2",
            part.expr,
          );
        } else {
          this.#printItems(part.expr, out);
        }
      }
      return;
    }
    // cualquier otra expresión: se evalúa y su VALOR va al host, que lo
    // formatea.
    const host = this.#writeHostFor(value);
    if (host === null) {
      this.#bag.add(
        WebCode.CODEGEN_STRING,
        "el codegen del target web v2 imprime literales, f-strings y valores " +
          "de tipo int/float/bool/char/str" +
          (value.restype === null
            ? ""
            : `; '${describeType(value.restype)}' no es ninguno de ellos`),
        value,
      );
      return;
    }
    out.push({
      write: {
        kind: "call.host",
        type: WirType.VOID,
        host: this.#hostIndex(host.host),
        args: [this.#lowerExpr(value, host.type)],
      },
    });
  }

  /**
   * Primitiva del host que sabe escribir este valor, según su tipo de
   * suriaX — no el del WIR: `bool` y `char` son los dos `i32`, y el host
   * tiene que escribir `true`, no `1`.
   */
  #writeHostFor(value: Expr): { host: number; type: WirType } | null {
    switch (value.restype?.kind) {
      case TypeKind.INT: return { host: Host.WRITE_INT, type: WirType.I64 };
      case TypeKind.FLOAT: return { host: Host.WRITE_FLOAT, type: WirType.F64 };
      case TypeKind.BOOL: return { host: Host.WRITE_BOOL, type: WirType.I32 };
      case TypeKind.CHAR: return { host: Host.WRITE_CHAR, type: WirType.I32 };
      case TypeKind.STR: return { host: Host.WRITE_STR, type: WirType.I32 };
      default: return null;
    }
  }

  /** Escritura de un texto CONSTANTE: al data segment y por offset/longitud. */
  #writeText(text: string): WirExpr {
    const id = this.#intern(text);
    const entry = this.#strings[id]!;
    return {
      kind: "call.host",
      type: WirType.VOID,
      host: this.#hostIndex(Host.WRITE),
      args: [
        { kind: "const", type: WirType.I32, value: BigInt(entry.offset) },
        { kind: "const", type: WirType.I32, value: BigInt(entry.bytes.length) },
      ],
    };
  }

  /** Constantes de cadena deduplicadas: dos `println("hola")` comparten bytes. */
  #intern(text: string): number {
    const existing = this.#stringByText.get(text);
    if (existing !== undefined) return existing;
    const bytes = encodeUtf8(text);
    const id = this.#strings.length;
    this.#strings.push({ offset: this.#dataSize, bytes, text });
    this.#stringByText.set(text, id);
    this.#dataSize += bytes.length;
    return id;
  }
}

/** Valor cero de un tipo, para los locales sin inicializador. */
function zeroOf(type: WirType): WirExpr {
  return type === WirType.F64
    ? { kind: "const", type, value: 0 }
    : { kind: "const", type: type === WirType.VOID ? WirType.I64 : type, value: 0n };
}

/** `Type` del HIR -> tipo del WIR, o `null` si no es representable. */
export function wirTypeOf(type: Type | null): WirType | null {
  if (type === null) return null;
  switch (type.kind) {
    case TypeKind.INT: return WirType.I64;
    case TypeKind.FLOAT: return WirType.F64;
    case TypeKind.BOOL: return WirType.I32;
    // 'char' es UN code point: un i32 lo representa entero (Unicode llega a
    // 0x10FFFF). Que comparta tipo del WIR con 'bool' no los confunde — el
    // tipo de suriaX es el que decide cómo se escribe, no el del WIR.
    case TypeKind.CHAR: return WirType.I32;
    // 'str' es el ÍNDICE de una constante (ver `#valueType`): un i32 más.
    case TypeKind.STR: return WirType.I32;
    case TypeKind.VOID: return WirType.VOID;
    default: return null;
  }
}

function describeType(type: Type): string {
  switch (type.kind) {
    case TypeKind.STR: return "str";
    case TypeKind.CHAR: return "char";
    // 'byte' todavía no baja al WIR (sería un i32 enmascarado): se rechaza
    // con su nombre, en vez de un "no representable" que no dice qué es
    case TypeKind.BYTE: return "byte";
    case TypeKind.NOMINAL: return type.name;
    case TypeKind.POINTER: return "puntero";
    case TypeKind.NULLABLE: return "nullable";
    case TypeKind.ERROR: return "error";
    default: return "no representable";
  }
}
