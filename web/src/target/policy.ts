/**
 * Política de capacidades del target web — el *qué* de la contención.
 *
 * El target web (JS/TS, y el WASM que sale de él) **no puede ejecutar todo
 * suriaX todavía**. Esa lista no puede vivir dispersa en `if`s por el
 * codegen: si lo estuviera, cada construcción sin soporte se descubriría en
 * runtime, en el navegador, con un error del generador y no del lenguaje.
 *
 * Aquí está la lista, **una sola vez**, como datos. `restrictions.ts` la
 * hace cumplir sobre el HIR ANTES de generar una línea de JS; el mismo
 * fichero es lo que hay que editar el día que una capacidad entre en
 * soporte. Es el equivalente web de la tabla `_UNSUPPORTED` de
 * `emmit_IR.py`: fuente única para el error y para los tests.
 *
 * Nota de diseño: la política deniega por LISTA BLANCA. Una capacidad nueva
 * en el lenguaje nace denegada en el web hasta que alguien la habilite a
 * propósito — nunca al revés.
 */

/**
 * Capacidades del lenguaje que el target web contiene temporalmente.
 * El valor es el que aparece en los mensajes y en los reportes.
 */
export const Capability = {
  /** `#extern cpp { ... }`: exigiría un toolchain C++ en el navegador. */
  EXTERN_CPP: "extern-cpp",
  /** Tipos puntero (`ptr T`, `ptr mutable T`) en firmas, campos y bindings. */
  POINTERS: "pointers",
  /** `&x`: JS no expone direcciones. */
  ADDRESS_OF: "address-of",
  /** `free x;`: no hay liberación manual sobre el GC de JS. */
  MANUAL_FREE: "manual-free",
  /** Hooks del modelo de memoria: `__free__` y `__sizeof__`. */
  MEMORY_HOOKS: "memory-hooks",
  /** `move x;` y la invalidación del origen en runtime. */
  MOVE: "move",
  /** `sizeof(T)`: depende del layout nativo, que el web no fija. */
  SIZEOF: "sizeof",
} as const;
export type Capability = (typeof Capability)[keyof typeof Capability];

/** Explicación estable de por qué una capacidad está contenida. */
export const CAPABILITY_REASON: ReadonlyMap<Capability, string> = new Map([
  [Capability.EXTERN_CPP,
   "el target web no compila C++: '#extern cpp' viaja en el HIR pero no tiene " +
   "traducción a JS/WASM en esta versión"],
  [Capability.POINTERS,
   "el target web no representa punteros todavía: JS no tiene direcciones y la " +
   "emulación con celdas cambiaría la semántica de 'ptr mutable'"],
  [Capability.ADDRESS_OF,
   "'&x' produce un puntero, y el target web aún no representa punteros"],
  [Capability.MANUAL_FREE,
   "'free' libera memoria manualmente; en el target web la memoria la gestiona " +
   "el runtime de JS"],
  [Capability.MEMORY_HOOKS,
   "los hooks del modelo de memoria (__free__/__sizeof__) dependen del " +
   "runtime nativo (ownership + pybind11), que no viaja al web"],
  [Capability.MOVE,
   "move-semantics exige invalidar el origen en runtime; el target web aún no " +
   "lo hace cumplir y ejecutarlo daría un programa con otra semántica"],
  [Capability.SIZEOF,
   "'sizeof' depende del layout nativo del tipo, que el target web no fija"],
]);

/**
 * Unidad `.phir` permitida y **confiable**: su implementación la aporta el
 * runtime web (host), no el codegen. Es lo que permite que `print` funcione
 * aunque su `.libsrx` use punteros (`fn __print__(String ptr s)`): esa
 * unidad no se traduce, se SUSTITUYE por la primitiva del host
 * (`__write__` -> la salida del playground).
 */
export interface TrustedUnit {
  /** Alias de la unidad, tal como lo resuelve el linker (`IO.stdp`). */
  readonly alias: string;
  /** Prototipos que el host implementa (`__write__`). */
  readonly hostPrimitives: readonly string[];
}

/** Política completa del target. */
export interface Policy {
  readonly name: string;
  /** Capacidades HABILITADAS. Todo lo que no esté aquí, se rechaza. */
  readonly allowed: ReadonlySet<Capability>;
  /** Unidades importables, en minúsculas (la comparación ignora mayúsculas). */
  readonly allowedUnits: ReadonlySet<string>;
  /**
   * `true` = cualquier librería puede importarse y `allowedUnits` se ignora.
   * Es un campo propio y no "la lista vacía" a propósito: una allowlist
   * vacía significa *ninguna librería*, que es una política legítima y muy
   * distinta de *todas*.
   */
  readonly allowAllUnits: boolean;
  /** Unidades cuya implementación aporta el host (no se traducen ni se revisan). */
  readonly trustedUnits: ReadonlyMap<string, TrustedUnit>;
  /**
   * Por qué se deniega un PAQUETE (clave: su nombre en minúsculas, `sistema`
   * para `sistema.archivos`). Opcional: sin entrada, el diagnóstico solo dice
   * qué está permitido. Con ella dice además si es "todavía no" o "nunca",
   * que es lo que quien lo lee necesita para saber si esperar o cambiar.
   */
  readonly deniedReasons?: ReadonlyMap<string, string>;
}

/** Clave de comparación de una unidad/librería (los alias no distinguen caja). */
export function unitKey(name: string): string {
  return name.trim().toLowerCase();
}

/**
 * Las tres unidades del paquete `IO`: lo ÚNICO ejecutable en la primera
 * versión del target web. `IO` es el padre del paquete (solo `#export
 * package as IO`), `IO.stdp` trae `print`/`println` y `IO.stdpf` el
 * `printf` orientado a f-strings. Las tres se apoyan en la misma primitiva
 * del host, `__write__`.
 *
 * Para dejar fuera `printf`, borra su entrada: no hay ningún otro sitio que
 * tocar.
 */
const IO_UNITS: readonly TrustedUnit[] = [
  { alias: "IO", hostPrimitives: [] },
  { alias: "IO.stdp", hostPrimitives: ["__write__"] },
  { alias: "IO.stdpf", hostPrimitives: ["__write__"] },
];

/**
 * **Perfil del target web v1.**
 *
 * Cero capacidades habilitadas, pero **cualquier librería puede importarse**.
 *
 * Antes solo `IO`, y no porque el target no pudiera traducir las demás: el
 * lowering tiraba las unidades y bajaba solo la principal, así que ninguna
 * librería tenía forma de llegar al WIR. Con la imagen entera bajando, una
 * librería de funciones corrientes (`math`) se traduce como cualquier otro
 * código.
 *
 * Lo que decide ahora es la CAPACIDAD, no la identidad de la unidad: una
 * librería que usa punteros se rechaza por `WEB002` señalando la línea
 * exacta, no por llamarse como se llama. Es un diagnóstico mejor y una regla
 * más honesta — lo que el target no sabe hacer es lo que no puede ejecutar.
 *
 * `IO` sigue siendo **confiable**: su implementación la aporta el host
 * (`__write__`), así que su cuerpo no se traduce ni se revisa. Es lo que le
 * permite declarar `fn __print__(String ptr s)` sin violar `WEB002`.
 */
export const WEB_V1_POLICY: Policy = {
  name: "web-v1",
  allowed: new Set<Capability>(),
  allowedUnits: new Set(IO_UNITS.map((u) => unitKey(u.alias))),
  allowAllUnits: true,
  trustedUnits: new Map(IO_UNITS.map((u) => [unitKey(u.alias), u])),
};

/**
 * Librerías que el playground deja importar: las que el target web **sabe
 * ejecutar hoy**. Unidad a unidad, sin comodines: una unidad nueva de un
 * paquete permitido nace denegada, igual que una capacidad nueva.
 */
const PLAYGROUND_UNITS: readonly string[] = [
  "IO", "IO.stdp", "IO.stdpf",
  "math", "math.basic", "math.constants",
  "excepciones",
];

const POINTERS_PENDING =
  "su implementación usa punteros, que el target web todavía no representa; " +
  "entrará cuando el target los soporte";

/**
 * **Perfil del playground.**
 *
 * El del target web (`web-v1`: ninguna capacidad habilitada) y, además, una
 * lista blanca de librerías. `web-v1` deja importar cualquiera y rechaza por
 * capacidad; en el playground eso daba, para un `#import text`, cuarenta
 * diagnósticos `WEB002` dentro de una librería que el usuario no escribió.
 * Aquí es uno, en su `#import`, que dice por qué.
 *
 * Dos clases de denegación, y el motivo las distingue:
 *
 *  - **nunca** (`sistema`): el playground no tiene archivos, procesos ni
 *    rutas. No es una carencia del codegen, es lo que el playground es.
 *  - **todavía no** (`text`, `array`, `collections`, `d_types`, `mem`): el
 *    target no sabe bajarlas. Cuando sepa, se añaden a la lista.
 */
export const PLAYGROUND_POLICY: Policy = {
  name: "playground",
  allowed: new Set<Capability>(),
  allowedUnits: new Set(PLAYGROUND_UNITS.map(unitKey)),
  allowAllUnits: false,
  trustedUnits: new Map(IO_UNITS.map((u) => [unitKey(u.alias), u])),
  deniedReasons: new Map([
    ["sistema",
     "el playground no tiene archivos, procesos ni rutas: el programa no se " +
     "ejecuta en una máquina con sistema de archivos"],
    ["mem", "la memoria manual depende del runtime nativo, que no viaja al web"],
    ["text", POINTERS_PENDING],
    ["array", POINTERS_PENDING],
    ["collections", POINTERS_PENDING],
    ["d_types",
     "sus tipos declaran '__sizeof__', que depende del layout nativo"],
  ]),
};

/**
 * Perfil sin contención: TODO permitido. No es para producción — existe
 * para que los tests del deserializador y del DCE puedan trabajar con
 * programas completos sin que la política los corte antes.
 */
export const UNRESTRICTED_POLICY: Policy = {
  name: "unrestricted",
  allowed: new Set(Object.values(Capability)),
  allowedUnits: new Set(),
  allowAllUnits: true,
  trustedUnits: new Map(),
};

/**
 * Los perfiles que se pueden pedir por nombre (`--policy <nombre>`). Quien
 * invoca el target elige el perfil; el target no adivina dónde corre.
 */
export const POLICIES: ReadonlyMap<string, Policy> = new Map(
  [WEB_V1_POLICY, PLAYGROUND_POLICY, UNRESTRICTED_POLICY].map((p) => [p.name, p]),
);

/** Por qué la política deniega esta unidad, si lo dice. */
export function unitDeniedReason(policy: Policy, name: string): string | null {
  const paquete = unitKey(name).split(".", 1)[0] ?? "";
  return policy.deniedReasons?.get(paquete) ?? null;
}

/**
 * Deriva una política a partir de otra. La forma soportada de "habilitar
 * algo" cuando una capacidad entre en soporte, sin editar el perfil base.
 */
export function withCapabilities(
  base: Policy,
  granted: readonly Capability[],
  name = `${base.name}+`,
): Policy {
  return {
    name,
    allowed: new Set([...base.allowed, ...granted]),
    allowedUnits: base.allowedUnits,
    allowAllUnits: base.allowAllUnits,
    trustedUnits: base.trustedUnits,
    deniedReasons: base.deniedReasons,
  };
}

/** Deriva una política con unidades adicionales permitidas (y confiables). */
export function withUnits(
  base: Policy,
  units: readonly TrustedUnit[],
  name = `${base.name}+units`,
): Policy {
  const trusted = new Map(base.trustedUnits);
  for (const unit of units) trusted.set(unitKey(unit.alias), unit);
  return {
    name,
    allowed: base.allowed,
    allowedUnits: new Set([...base.allowedUnits, ...units.map((u) => unitKey(u.alias))]),
    allowAllUnits: base.allowAllUnits,
    trustedUnits: trusted,
    deniedReasons: base.deniedReasons,
  };
}

/** ¿La unidad puede importarse bajo esta política? */
export function unitAllowed(policy: Policy, name: string): boolean {
  return policy.allowAllUnits || policy.allowedUnits.has(unitKey(name));
}

/** ¿La implementación de esta unidad la aporta el host? */
export function unitTrusted(policy: Policy, alias: string): boolean {
  return policy.trustedUnits.has(unitKey(alias));
}
