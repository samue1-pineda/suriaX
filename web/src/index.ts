/**
 * API pública del backend web de suriaX.
 *
 * Orden del pipeline (y razón de ese orden):
 *
 * ```
 *   .phir (bytes)
 *      │  decodificar        hir/decode.ts    fail-fast de esquema
 *      ▼
 *   Module ── ligar ──▶ Image                 hir/link.ts
 *      │  contener          target/           lo que el web NO puede correr,
 *      ▼                                      ANTES de optimizar nada
 *   Image validada
 *      │  optimizar         opt/dce.ts
 *      ▼
 *   Image lista para el codegen JS/TS
 * ```
 *
 * La contención va **antes** del DCE a propósito: el DCE puede borrar la
 * función que contenía la construcción no soportada, y entonces el programa
 * pasaría el filtro por accidente — el mismo código, compilado dos veces,
 * daría resultados distintos según lo que estuviera vivo. Un target que
 * acepta o rechaza según el nivel de optimización no es un target, es una
 * lotería.
 *
 * El codegen a JS/TS **no está en este módulo todavía**: esta entrega cubre
 * el lector, la contención y la primera optimización.
 */

export {
  HIRLoadError,
  SUPPORTED_SCHEMA_VERSIONS,
  decodeModule,
  loadModule,
} from "./hir/decode.ts";
export {
  Image,
  LinkError,
  Unit,
  findHook,
  indexCasts,
  indexDunders,
  indexHooks,
  linkImage,
  resolveRelative,
  type BoundFunction,
  type PhirResolver,
} from "./hir/link.ts";
export * from "./hir/schema.ts";
export { Reader, WireError, decodeUtf8 } from "./hir/wire.ts";
export {
  Severity,
  WebCode,
  formatDiagnostic,
  type Diagnostic,
} from "./diagnostics.ts";
export {
  CAPABILITY_REASON,
  Capability,
  UNRESTRICTED_POLICY,
  WEB_V1_POLICY,
  unitAllowed,
  unitKey,
  unitTrusted,
  withCapabilities,
  withUnits,
  type Policy,
  type TrustedUnit,
} from "./target/policy.ts";
export {
  checkImage,
  checkModule,
  checkUnit,
  type RestrictionReport,
} from "./target/restrictions.ts";
export {
  crossUnitRoots,
  eliminateDeadCode,
  eliminateDeadCodeInImage,
  formatStats,
  isPure,
  type DceOptions,
  type DceResult,
  type DceStats,
  type ImageDceResult,
} from "./opt/dce.ts";
export { encodeModule } from "./hir/encode.ts";
export { Writer, encodeUtf8 } from "./hir/write.ts";
export * from "./wir/wir.ts";
export {
  IO_INTRINSICS,
  MODULE_INIT,
  lowerImage,
  lowerModule,
  wirTypeOf,
  type LowerResult,
} from "./wir/lower.ts";
export {
  emitHostModule,
  emitJs,
  emitWasm,
  emitWat,
  generate,
  generateFromImage,
  toBase64,
  WasmEmitError,
  type CodegenResult,
} from "./codegen/index.ts";

import type { Diagnostic } from "./diagnostics.ts";
import { Image, linkImage, type PhirResolver } from "./hir/link.ts";
import { eliminateDeadCodeInImage, type DceOptions, type DceStats } from "./opt/dce.ts";
import { WEB_V1_POLICY, type Policy } from "./target/policy.ts";
import { checkImage, type RestrictionReport } from "./target/restrictions.ts";
import { generateFromImage, type CodegenResult } from "./codegen/index.ts";

export interface PrepareOptions {
  /** Política del target. {@link WEB_V1_POLICY} por defecto. */
  readonly policy?: Policy;
  /** Opciones del DCE. */
  readonly dce?: DceOptions;
  /** `false` para saltarse el DCE (depuración del codegen). */
  readonly optimize?: boolean;
}

export interface PrepareResult {
  /** Imagen lista para el codegen, o `null` si la contención la rechazó. */
  readonly image: Image | null;
  readonly diagnostics: readonly Diagnostic[];
  readonly restrictions: RestrictionReport;
  /** Estadísticas del DCE por unidad (`""` = la principal). Vacío si no se optimizó. */
  readonly dce: ReadonlyMap<string, DceStats>;
}

/**
 * Pipeline completo hasta la puerta del codegen: decodificar, ligar,
 * contener y optimizar.
 *
 * Devuelve `image: null` cuando hay diagnósticos críticos — **nada de HIR
 * parcial cruza al codegen**, la misma regla que aplica el emisor del
 * frontend al no serializar un programa con errores.
 *
 * @throws {HIRLoadError} bytes corruptos o esquema no soportado.
 * @throws {LinkError} falta una unidad `.phir` referenciada.
 */
export function prepare(
  mainBytes: Uint8Array,
  mainPath: string,
  resolve: PhirResolver,
  options: PrepareOptions = {},
): PrepareResult {
  const policy = options.policy ?? WEB_V1_POLICY;
  const linked = linkImage(mainBytes, mainPath, resolve);
  const restrictions = checkImage(linked, policy);

  if (!restrictions.ok) {
    return {
      image: null,
      diagnostics: restrictions.diagnostics,
      restrictions,
      dce: new Map(),
    };
  }
  if (options.optimize === false) {
    return {
      image: linked,
      diagnostics: restrictions.diagnostics,
      restrictions,
      dce: new Map(),
    };
  }
  const optimized = eliminateDeadCodeInImage(linked, options.dce ?? {});
  return {
    image: optimized.image,
    diagnostics: restrictions.diagnostics,
    restrictions,
    dce: optimized.stats,
  };
}

/** Resultado de {@link compile}: la tubería entera, de bytes a artefactos. */
export interface CompileResult extends PrepareResult {
  readonly codegen: CodegenResult | null;
}

/**
 * Tubería completa del target web: `.phir` -> artefactos ejecutables.
 *
 * `decodificar -> ligar -> contener -> optimizar -> bajar a WIR -> emitir`.
 * Si la contención rechaza el programa, el codegen NI SE INTENTA: los
 * diagnósticos de "no puedo ejecutar esto" y los de "no sé traducir esto"
 * son problemas distintos y mezclarlos solo confunde a quien lee el error.
 */
export function compile(
  mainBytes: Uint8Array,
  mainPath: string,
  resolve: PhirResolver,
  options: PrepareOptions = {},
): CompileResult {
  const prepared = prepare(mainBytes, mainPath, resolve, options);
  if (prepared.image === null) return { ...prepared, codegen: null };

  // la MISMA política que contuvo la imagen decide qué unidades son del host
  // y no se traducen: si las dos discreparan, el codegen intentaría bajar el
  // cuerpo de una librería que la contención dio por confiable.
  const codegen = generateFromImage(prepared.image,
                                    options.policy ?? WEB_V1_POLICY);
  return {
    ...prepared,
    diagnostics: [...prepared.diagnostics, ...codegen.diagnostics],
    codegen,
  };
}
