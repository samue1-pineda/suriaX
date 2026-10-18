/**
 * Contención de restricciones — el *cómo* de la política del target web.
 *
 * Recorre un `Module` (o una `Image` completa) y reporta TODA construcción
 * que la {@link Policy} no permite, con su código `WEBxxx` y su posición en
 * el `.srcx` original. Es la puerta que el pipeline web cruza ANTES de
 * generar JS: si hay un solo diagnóstico crítico, no se genera nada.
 *
 * Tres decisiones heredadas del frontend, a propósito:
 *
 *  - **acumula, no lanza** (como `semantic.analyze` y `build_module`): el
 *    usuario ve de una vez todo lo que su programa usa y el web no soporta,
 *    no el primer problema y a adivinar el resto;
 *  - **una tabla, no `if`s repartidos**: qué está denegado vive en
 *    `policy.ts`; aquí solo está dónde mirar;
 *  - **posición siempre**: cada diagnóstico apunta a la línea/columna que la
 *    Semántica anotó, para que el editor lo subraye igual que un error de
 *    tipos.
 *
 * ### Granularidad de los punteros
 * Un `ptr T` se reporta en su **declaración** (parámetro, campo, `var`,
 * `cast<T>`), no en cada expresión cuyo `restype` sea puntero: un solo
 * `int ptr p` produciría si no una decena de diagnósticos idénticos por sus
 * usos. Es la misma regla que sigue la Semántica al reportar un binding.
 *
 * ### Unidades confiables
 * Las unidades de `policy.trustedUnits` (hoy el paquete `IO`) NO se revisan:
 * su implementación la aporta el runtime web, no el codegen. `IO.stdp`
 * declara `fn __print__(String ptr s)` —un puntero— y aun así es la única
 * librería ejecutable: lo que viaja al navegador es la primitiva del host
 * (`__write__`), no la traducción de ese cuerpo. Lo que sí se revisa de una
 * unidad confiable son sus IMPORTS: una librería permitida no puede colar
 * una denegada.
 */

import {
  Severity,
  WebCode,
  DiagnosticBag,
  type Diagnostic,
  type HasPos,
} from "../diagnostics.ts";
import {
  HookKind,
  TypeKind,
  findFunctionType,
  formatType,
  hookName,
  testBlocks,
  type Block,
  type Decl,
  type Expr,
  type IfStmt,
  type Module,
  type Stmt,
  type SymbolInfo,
  type Type,
} from "../hir/schema.ts";
import type { Image, Unit } from "../hir/link.ts";
import {
  CAPABILITY_REASON,
  Capability,
  WEB_V1_POLICY,
  unitAllowed,
  unitDeniedReason,
  unitKey,
  unitTrusted,
  type Policy,
} from "./policy.ts";

/** Resultado de revisar un módulo o una imagen. */
export interface RestrictionReport {
  /** Todo lo que impide (o desaconseja) generar código, en orden de aparición. */
  readonly diagnostics: readonly Diagnostic[];
  /** Capacidades denegadas que el programa REALMENTE usa. */
  readonly denied: ReadonlySet<Capability>;
  /** Unidades importadas fuera de la allowlist (alias tal como se escribieron). */
  readonly deniedUnits: readonly string[];
  /** `true` si el programa puede pasar al codegen. */
  readonly ok: boolean;
}

/** Hooks que dependen del modelo de memoria nativo. */
const MEMORY_HOOK_KINDS: ReadonlySet<HookKind> = new Set([
  HookKind.FREE,
  HookKind.SIZEOF,
]);

/**
 * Revisa un módulo contra la política.
 *
 * @param module módulo decodificado.
 * @param policy política del target (por defecto {@link WEB_V1_POLICY}).
 * @param unitAlias alias de la unidad; `""` para la principal (código de usuario).
 */
export function checkModule(
  module: Module,
  policy: Policy = WEB_V1_POLICY,
  unitAlias = "",
): RestrictionReport {
  const checker = new RestrictionChecker(policy);
  checker.checkUnit(module, unitAlias);
  return checker.report();
}

/**
 * Revisa la imagen completa: la unidad principal y cada librería ligada.
 * Es lo que el pipeline web ejecuta de verdad — una librería denegada puede
 * entrar por un import transitivo que el `.srcx` nunca nombró.
 */
export function checkImage(
  image: Image,
  policy: Policy = WEB_V1_POLICY,
): RestrictionReport {
  const checker = new RestrictionChecker(policy);
  checker.checkUnit(image.main.module, image.main.alias);
  for (const unit of image.units.values()) {
    // una unidad denegada no se va a compilar: ya se reportó donde se
    // importa, y revisarla por dentro solo añadiría decenas de diagnósticos
    // en un archivo que el usuario no escribió.
    if (!unitAllowed(policy, unit.alias)) continue;
    checker.checkUnit(unit.module, unit.alias);
  }
  return checker.report();
}

/** Comprueba una sola unidad ya ligada (útil para revisar una librería suelta). */
export function checkUnit(unit: Unit, policy: Policy = WEB_V1_POLICY): RestrictionReport {
  return checkModule(unit.module, policy, unit.alias);
}

/**
 * Estado de UNA revisión. Se instancia por análisis (como `_Emitter` en el
 * emisor Python): sin estado global, reentrante, y los diagnósticos salen
 * en orden determinista.
 */
class RestrictionChecker {
  readonly #policy: Policy;
  readonly #diagnostics: Diagnostic[] = [];
  readonly #denied = new Set<Capability>();
  readonly #deniedUnits: string[] = [];
  readonly #seenUnits = new Set<string>();
  #bag: DiagnosticBag;
  /** Evita repetir el MISMO diagnóstico en la misma posición. */
  #seen = new Set<string>();

  constructor(policy: Policy) {
    this.#policy = policy;
    this.#bag = new DiagnosticBag("");
  }

  report(): RestrictionReport {
    return {
      diagnostics: this.#diagnostics,
      denied: this.#denied,
      deniedUnits: this.#deniedUnits,
      ok: !this.#diagnostics.some((d) => d.severity === Severity.CRITICAL),
    };
  }

  checkUnit(module: Module, unitAlias: string): void {
    this.#bag = new DiagnosticBag(module.sourceFile || unitAlias || "<módulo>");
    this.#seen = new Set();
    const trusted = unitTrusted(this.#policy, unitAlias);

    // Las referencias a otras unidades se revisan SIEMPRE, incluso en una
    // unidad confiable: es por donde entraría una librería denegada.
    // Las que además nombra un '#import' de este módulo se reportan ALLÍ, con
    // su posición: aquí saldrían otra vez y sin línea.
    const escritas = new Set<string>();
    for (const decl of module.items) {
      if (decl.node.case !== "import" && decl.node.case !== "from") continue;
      const { unit, lib } = decl.node.directive;
      escritas.add(unitKey(unit !== "" ? unit : lib));
    }
    for (const ref of module.libraries) {
      if (escritas.has(unitKey(ref.alias))) continue;
      this.#checkUnitName(ref.alias, ref.alias, null);
    }

    for (const decl of module.items) {
      if (trusted) this.#checkDirectivesOnly(decl);
      else this.#checkDecl(decl);
    }
    if (!trusted) this.#checkSymbolTable(module);
    this.#flush();
  }

  #flush(): void {
    this.#diagnostics.push(...this.#bag.items);
  }

  // ----------------------------------------------------------------- //
  // reporte
  // ----------------------------------------------------------------- //

  /** Añade un diagnóstico de capacidad, salvo que ya se reportara ahí mismo. */
  #deny(
    capability: Capability,
    code: string,
    what: string,
    pos: HasPos | null,
  ): void {
    if (this.#policy.allowed.has(capability)) return;
    const key = `${code}:${pos?.ln ?? 0}:${pos?.col ?? 0}:${what}`;
    if (this.#seen.has(key)) return;
    this.#seen.add(key);
    this.#denied.add(capability);
    const reason = CAPABILITY_REASON.get(capability) ?? "capacidad no soportada";
    this.#bag.add(code, `${what}: ${reason}`, pos);
  }

  /**
   * `WEB103` si `type` es, o contiene, un tipo función. No es una capacidad
   * de la política: se reporta SIEMPRE (como `WEB901`), porque ningún perfil
   * puede habilitar algo que el codegen no sabe traducir. A lo sumo uno por
   * línea: `var fn(int) -> int g = doble;` es un solo problema aunque lo
   * delaten la variable y la expresión.
   */
  #functionValue(type: Type | null, what: string, pos: HasPos | null): void {
    const found = findFunctionType(type);
    if (found === null) return;
    const key = `${WebCode.FUNCTION_VALUE}:${pos?.ln ?? 0}`;
    if (this.#seen.has(key)) return;
    this.#seen.add(key);
    this.#bag.add(
      WebCode.FUNCTION_VALUE,
      `${what} usa una función como valor (tipo '${formatType(found)}'): el target ` +
        "web todavía no ejecuta funciones como valores; ejecútalo con el " +
        "intérprete (python V0/main.py <fuente>.srcx --run interpreter)",
      pos,
    );
  }

  /**
   * `WEB104`: una lambda. Como `WEB103`, SIEMPRE (ninguna política la
   * habilita: el codegen no sabe traducirla). Ocupa la clave de `WEB103` de
   * su línea, para no decir dos veces lo mismo de la misma expresión.
   */
  #lambda(pos: HasPos): void {
    const key = `${WebCode.LAMBDA}:${pos.ln}:${pos.col}`;
    if (this.#seen.has(key)) return;
    this.#seen.add(key);
    this.#seen.add(`${WebCode.FUNCTION_VALUE}:${pos.ln}`);
    this.#bag.add(
      WebCode.LAMBDA,
      "una lambda (una función sin nombre que lee su entorno): el target web " +
        "todavía no las ejecuta; ejecútalo con el intérprete (python " +
        "V0/main.py <fuente>.srcx --run interpreter)",
      pos,
    );
  }

  #malformed(what: string, pos: HasPos | null): void {
    this.#bag.add(
      WebCode.MALFORMED_NODE,
      `${what} llegó sin variante en el HIR: el .phir está corrupto o lo emitió ` +
        "un frontend más nuevo que este backend",
      pos,
    );
  }

  // ----------------------------------------------------------------- //
  // librerías
  // ----------------------------------------------------------------- //

  /**
   * @param resolved unidad RESUELTA por la Semántica (`IO.stdp`), si la hay.
   * @param written lo que se escribió en el fuente (`io`), para el mensaje.
   */
  #checkUnitName(resolved: string, written: string, pos: HasPos | null): void {
    const name = resolved !== "" ? resolved : written;
    if (name === "" || unitAllowed(this.#policy, name)) return;
    if (!this.#seenUnits.has(name)) {
      this.#seenUnits.add(name);
      this.#deniedUnits.push(name);
    }
    const allowed = [...this.#policy.allowedUnits].join(", ") || "(ninguna)";
    const reason = unitDeniedReason(this.#policy, name);
    this.#bag.add(
      WebCode.LIBRARY_DENIED,
      `la librería '${written}'${resolved !== "" && resolved !== written ? ` (unidad '${resolved}')` : ""} ` +
        `no está permitida en el target web '${this.#policy.name}'` +
        (reason !== null ? `: ${reason}` : "") +
        `: en esta versión solo puede ejecutarse ${allowed}`,
      pos,
    );
  }

  /** En una unidad confiable solo se miran sus propias importaciones. */
  #checkDirectivesOnly(decl: Decl): void {
    switch (decl.node.case) {
      case "import":
        this.#checkUnitName(decl.node.directive.unit, decl.node.directive.lib, decl);
        return;
      case "from":
        this.#checkUnitName(decl.node.directive.unit, decl.node.directive.lib, decl);
        return;
      default:
        return;
    }
  }

  // ----------------------------------------------------------------- //
  // tabla de símbolos
  // ----------------------------------------------------------------- //

  /**
   * De la tabla solo se revisan los HOOKS: son la única información que no
   * está en los `items` con una posición mejor. Los tipos de las firmas se
   * revisan en sus declaraciones, que apuntan al sitio exacto del fuente.
   */
  #checkSymbolTable(module: Module): void {
    for (const entry of module.symbols.hooks) {
      if (!MEMORY_HOOK_KINDS.has(entry.kind)) continue;
      const sym: SymbolInfo | null = entry.symbol;
      this.#deny(
        Capability.MEMORY_HOOKS,
        WebCode.MEMORY_HOOK,
        `el hook '${hookName(entry.kind)}' de '${entry.ownerType}'`,
        sym,
      );
    }
  }

  // ----------------------------------------------------------------- //
  // declaraciones
  // ----------------------------------------------------------------- //

  #checkDecl(decl: Decl): void {
    switch (decl.node.case) {
      case "function": {
        const fn = decl.node.fn;
        for (const param of fn.params) {
          this.#checkType(param.type, `el parámetro '${param.name}' de '${fn.name}'`, decl);
        }
        this.#checkType(fn.returnType, `el retorno de '${fn.name}'`, decl);
        if (fn.body !== null) this.#checkBlock(fn.body);
        return;
      }
      case "struct":
        for (const field of decl.node.struct.fields) {
          this.#checkType(
            field.type,
            `el campo '${decl.node.struct.name}.${field.name}'`,
            decl,
          );
        }
        return;
      case "enum":
        for (const item of decl.node.enumDecl.items) {
          if (item.value !== null) this.#checkExpr(item.value);
        }
        return;
      case "externBlock":
        this.#deny(
          Capability.EXTERN_CPP,
          WebCode.EXTERN_CPP,
          `el bloque '#extern ${decl.node.externBlock.target}'`,
          decl,
        );
        return;
      case "test":
        // las tres partes de una prueba son código del programa: lo que el
        // target no puede ejecutar tampoco puede estar en una cláusula.
        for (const parte of testBlocks(decl.node.test)) this.#checkBlock(parte);
        return;
      case "statement":
        this.#checkStmt(decl.node.stmt);
        return;
      case "import":
        this.#checkUnitName(decl.node.directive.unit, decl.node.directive.lib, decl);
        return;
      case "from":
        this.#checkUnitName(decl.node.directive.unit, decl.node.directive.lib, decl);
        return;
      case "export":
        return;
      case "none":
        this.#malformed("una declaración de nivel superior", decl);
        return;
    }
  }

  // ----------------------------------------------------------------- //
  // tipos
  // ----------------------------------------------------------------- //

  /** Un tipo puntero en cualquier nivel de anidamiento (`int ptr?`, `T ptr ptr`). */
  #checkType(type: Type | null, what: string, pos: HasPos | null): void {
    this.#functionValue(type, what, pos);
    for (let t: Type | null = type; t !== null; t = t.inner) {
      if (t.kind === TypeKind.POINTER) {
        this.#deny(
          Capability.POINTERS,
          WebCode.POINTER_TYPE,
          `${what} es de tipo '${formatType(type)}'`,
          pos,
        );
        return;
      }
    }
  }

  // ----------------------------------------------------------------- //
  // sentencias
  // ----------------------------------------------------------------- //

  #checkBlock(block: Block): void {
    for (const stmt of block.statements) this.#checkStmt(stmt);
  }

  #checkStmt(stmt: Stmt): void {
    const node = stmt.node;
    switch (node.case) {
      case "block":
        this.#checkBlock(node.block);
        return;
      case "varDecl":
        this.#checkType(node.type, `la variable '${node.name}'`, stmt);
        if (node.value !== null) this.#checkExpr(node.value);
        return;
      case "typeDecl":
        if (node.value !== null) this.#checkExpr(node.value);
        return;
      case "if":
        this.#checkIf(node.ifStmt);
        return;
      case "while":
        this.#checkExpr(node.condition);
        this.#checkBlock(node.body);
        return;
      case "match":
        this.#checkExpr(node.subject);
        for (const arm of node.cases) {
          this.#checkExpr(arm.pattern);
          this.#checkStmt(arm.body);
        }
        return;
      case "return":
        if (node.value !== null) this.#checkExpr(node.value);
        return;
      case "break":
      case "continue":
        return;
      case "move":
        this.#deny(Capability.MOVE, WebCode.MOVE, "'move'", stmt);
        this.#checkExpr(node.target);
        return;
      case "free":
        this.#deny(Capability.MANUAL_FREE, WebCode.FREE, "'free'", stmt);
        this.#checkExpr(node.target);
        return;
      case "expr":
        this.#checkExpr(node.expr);
        return;
      case "throw":
        this.#checkExpr(node.value);
        return;
      case "try":
        this.#checkBlock(node.tryBlock);
        for (const rama of node.catches) this.#checkBlock(rama.block);
        if (node.finallyBlock !== null) this.#checkBlock(node.finallyBlock);
        return;
      case "expect":
        this.#checkExpr(node.condition);
        if (node.body !== null) this.#checkBlock(node.body);
        return;
      case "importBinding":
        this.#checkUnitName("", node.lib, stmt);
        return;
      case "none":
        this.#malformed("una sentencia", stmt);
        return;
    }
  }

  #checkIf(node: IfStmt): void {
    this.#checkExpr(node.condition);
    this.#checkBlock(node.thenBlock);
    switch (node.elseBranch.case) {
      case "block":
        this.#checkBlock(node.elseBranch.block);
        return;
      case "if":
        this.#checkIf(node.elseBranch.ifStmt);
        return;
      case "none":
        return;
    }
  }

  // ----------------------------------------------------------------- //
  // expresiones
  // ----------------------------------------------------------------- //

  #checkExpr(expr: Expr): void {
    const node = expr.node;
    if (node.case === "lambdaExpr") {
      // antes que 'WEB103': su tipo es un 'fn(A) -> R', pero lo que no se
      // ejecuta es la lambda entera (el valor y el entorno que lee)
      this.#lambda(expr);
      return;
    }
    // el tipo de TODA expresión: una función nombrada como valor
    // ('aplica(doble, 2)') no tiene declaración propia en esta unidad que
    // la delate, y una llamada a través de un valor ('f(3)') tampoco.
    this.#functionValue(expr.restype, "la expresión", expr);
    switch (node.case) {
      case "literal":
        return;
      case "interp":
        for (const part of node.parts) {
          if (part.case === "expr") this.#checkExpr(part.expr);
        }
        return;
      case "identifier":
        return;
      case "unary":
        this.#checkExpr(node.operand);
        return;
      case "binary":
        this.#checkExpr(node.left);
        this.#checkExpr(node.right);
        return;
      case "assignment":
        this.#checkExpr(node.target);
        this.#checkExpr(node.value);
        return;
      case "call":
        this.#checkExpr(node.callee);
        for (const arg of node.args) this.#checkExpr(arg);
        if (node.hook !== null && MEMORY_HOOK_KINDS.has(node.hook.kind)) {
          this.#deny(
            Capability.MEMORY_HOOKS,
            WebCode.MEMORY_HOOK,
            `la llamada despacha '${hookName(node.hook.kind)}' de '${node.hook.ownerType}'`,
            expr,
          );
        }
        return;
      case "index":
        this.#checkExpr(node.obj);
        this.#checkExpr(node.index);
        return;
      case "member":
        this.#checkExpr(node.obj);
        return;
      case "sizeof":
        this.#deny(
          Capability.SIZEOF,
          WebCode.SIZEOF,
          `'sizeof(${formatType(node.type)})'`,
          expr,
        );
        return;
      case "addrOf":
        this.#deny(
          Capability.ADDRESS_OF,
          WebCode.ADDRESS_OF,
          node.mut ? "'&x' sobre un binding 'var' (ptr mutable)" : "'&x'",
          expr,
        );
        this.#checkExpr(node.operand);
        return;
      case "moveExpr":
        // el mismo motivo que la sentencia 'move x;': transferir exige
        // invalidar el origen en ejecución, y el web aún no lo hace cumplir.
        this.#deny(Capability.MOVE, WebCode.MOVE, "'move' como expresión", expr);
        this.#checkExpr(node.operand);
        return;
      case "cast":
        this.#checkType(node.type, `el destino de 'cast<${formatType(node.type)}>'`, expr);
        this.#checkExpr(node.value);
        return;
      case "structLiteral":
        for (const value of node.values) this.#checkExpr(value);
        return;
      case "lambdaExpr":
        return;     // ya se denegó arriba (WEB104)
      case "none":
        this.#malformed("una expresión", expr);
        return;
    }
  }
}
