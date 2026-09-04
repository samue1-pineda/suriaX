/**
 * Fachada del codegen: HIR -> WIR -> artefactos.
 *
 * Un solo lowering, tres emisores. Quien llama pide artefactos, no fases.
 */

import type { Diagnostic } from "../diagnostics.ts";
import type { Image } from "../hir/link.ts";
import type { Module } from "../hir/schema.ts";
import { lowerImage, lowerModule, type LowerResult } from "../wir/lower.ts";
import { WEB_V1_POLICY, unitTrusted, type Policy } from "../target/policy.ts";
import type { WirModule } from "../wir/wir.ts";
import { emitHostModule, emitJs } from "./js.ts";
import { emitWasm } from "./wasm.ts";
import { emitWat } from "./wat.ts";
import { emitPretty } from "./pretty.ts";

export { emitJs, emitHostModule, toBase64 } from "./js.ts";
export { emitWasm, WasmEmitError } from "./wasm.ts";
export { emitWat } from "./wat.ts";
export { emitPretty } from "./pretty.ts";

export interface CodegenResult {
  /** WIR intermedio: útil para inspeccionarlo o emitir otro artefacto. */
  readonly wir: WirModule | null;
  /** Binario WebAssembly listo para `WebAssembly.instantiate`. */
  readonly wasm: Uint8Array | null;
  /** Módulo ES que embebe e instancia ese binario (el artefacto final). */
  readonly host: string | null;
  /** Implementación equivalente en JS puro, sin WASM (oráculo y respaldo). */
  readonly js: string | null;
  /** El mismo módulo en WebAssembly textual, para leerlo. */
  readonly wat: string | null;
  /**
   * La vista LEGIBLE del WIR: el mismo árbol, con las expresiones en línea.
   * El `.wat` dice qué instrucción va después de cuál —la pregunta de quien
   * depura el emisor—; esta dice qué hace el programa.
   */
  readonly pretty: string | null;
  readonly diagnostics: readonly Diagnostic[];
  readonly ok: boolean;
}

const EMPTY: Omit<CodegenResult, "diagnostics" | "ok"> = {
  wir: null, wasm: null, host: null, js: null, wat: null, pretty: null,
};

/** Genera todos los artefactos de un módulo HIR ya contenido. */
export function generate(module: Module): CodegenResult {
  return fromLowering(lowerModule(module));
}

/**
 * Igual, partiendo de la imagen ligada: la unidad principal Y sus librerías.
 *
 * Antes bajaba solo `image.main.module` y las librerías se perdían — por eso
 * la única ejecutable era `IO`, que no se traduce sino que la sustituye el
 * host. Las unidades CONFIABLES de la política siguen sin traducirse; el
 * resto se baja como cualquier otro código.
 */
export function generateFromImage(image: Image,
                                  policy: Policy = WEB_V1_POLICY): CodegenResult {
  return fromLowering(
    lowerImage(image, (alias) => unitTrusted(policy, alias)));
}

function fromLowering(lowered: LowerResult): CodegenResult {
  if (lowered.module === null) {
    return { ...EMPTY, diagnostics: lowered.diagnostics, ok: false };
  }
  const wir = lowered.module;
  const wasm = emitWasm(wir);
  return {
    wir,
    wasm,
    host: emitHostModule(wir, wasm),
    js: emitJs(wir),
    wat: emitWat(wir),
    pretty: emitPretty(wir),
    diagnostics: lowered.diagnostics,
    ok: true,
  };
}
