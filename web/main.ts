/**
 * CLI del backend web — inspecciona un `.phir` sin navegador.
 *
 * Es al target web lo que `--emit-hir`/`--run` son al frontend: la forma de
 * ver qué haría el backend con un módulo, desde la terminal y sin montar el
 * playground.
 *
 * ```
 *   node web/main.ts dumps/a.srcx.phir
 *   node web/main.ts dumps/a.srcx.phir --no-dce --json
 *   node web/main.ts dumps/programa.phir --unrestricted   # sin contención
 * ```
 *
 * Este archivo es el ÚNICO del paquete que toca el sistema de archivos:
 * `src/` es agnóstico del entorno (recibe bytes y un resolutor), que es lo
 * que permite que el mismo código corra en el navegador.
 */

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import process from "node:process";

import { formatDiagnostic } from "./src/diagnostics.ts";
import { encodeModule } from "./src/hir/encode.ts";
import { loadModule } from "./src/hir/decode.ts";
import { resolveRelative, type PhirResolver } from "./src/hir/link.ts";
import { formatStats } from "./src/opt/dce.ts";
import { UNRESTRICTED_POLICY, WEB_V1_POLICY } from "./src/target/policy.ts";
import { compile } from "./src/index.ts";
import { toBase64 } from "./src/codegen/js.ts";
import { SYMBOL_KIND_NAMES, formatType, type Module } from "./src/hir/schema.ts";

/** Resolutor de unidades para node: las `.phir` viajan juntas en un directorio. */
const fsResolver: PhirResolver = (relativePath, fromPath) => {
  const path = resolveRelative(fromPath, relativePath);
  return existsSync(path) ? new Uint8Array(readFileSync(path)) : null;
};

/** Resumen legible de un módulo — espejo de `loader.summarize`. */
function summarize(module: Module): string {
  const lines = [
    `HIR schema v${module.schemaVersion} — ${module.sourceFile}`,
    `  items de nivel superior: ${module.items.length}`,
  ];
  if (module.libraries.length > 0) {
    lines.push(
      `  unidades ligadas (${module.libraries.length}): ` +
        module.libraries.map((l) => l.alias).join(", "),
    );
  }
  if (module.symbols.types.size > 0) {
    lines.push(`  tipos (${module.symbols.types.size}):`);
    for (const name of [...module.symbols.types.keys()].sort()) {
      const sym = module.symbols.types.get(name)!;
      const kind = SYMBOL_KIND_NAMES.get(sym.kind) ?? "?";
      const members = [...sym.members.keys()].sort();
      const detail =
        members.length > 0
          ? ` { ${members.map((m) => `${formatType(sym.members.get(m)!.type)} ${m}`).join(", ")} }`
          : "";
      lines.push(`    ${kind.padEnd(8)} ${name}${detail}`);
    }
  }
  const values = module.symbols.values;
  if (values.size > 0) {
    lines.push(`  valores (${values.size}):`);
    for (const name of [...values.keys()].sort()) {
      const sym = values.get(name)!;
      const kind = SYMBOL_KIND_NAMES.get(sym.kind) ?? "?";
      const params = sym.paramTypes.map(formatType).join(", ");
      lines.push(
        sym.paramTypes.length > 0 || kind === "fn"
          ? `    fn ${name}(${params}) -> ${formatType(sym.type)}`
          : `    ${kind.padEnd(8)} ${name}: ${formatType(sym.type)}`,
      );
    }
  }
  if (module.symbols.hooks.length > 0) {
    lines.push(`  hooks (${module.symbols.hooks.length}):`);
    for (const hook of module.symbols.hooks) {
      lines.push(`    kind ${hook.kind} de ${hook.ownerType}`);
    }
  }
  return lines.join("\n");
}

function usage(): void {
  process.stdout.write(
    "uso: node web/main.ts <archivo.phir> [opciones]\n" +
      "\n" +
      "  --no-dce             no elimina código muerto (solo lee y contiene)\n" +
      "  --json               salida en JSON (diagnósticos + estadísticas)\n" +
      "  --unrestricted       desactiva la contención del target web\n" +
      "  --emit-wat <ruta>    escribe el WebAssembly textual generado\n" +
      "  --emit-js <ruta>     escribe el módulo JS host (con el wasm embebido)\n" +
      "  --emit-wasm <ruta>   escribe el binario .wasm\n" +
      "  --reencode <ruta>    re-serializa el HIR leído a otro .phir\n" +
      "  --run                ejecuta el WebAssembly generado (--run-js usa el backend JS)\n" +
      "  --run-js             ejecuta el módulo JS puro en vez del WebAssembly\n",
  );
}

/** Valor de una opción con argumento (`--emit-wat salida.wat`). */
function optionValue(args: readonly string[], name: string): string | null {
  const index = args.indexOf(name);
  if (index < 0) return null;
  const value = args[index + 1];
  return value === undefined || value.startsWith("--") ? null : value;
}

function main(argv: readonly string[]): number {
  const args = argv.slice(2);
  // el primer argumento suelto es el .phir; los demás son valores de opción.
  const optionValues = new Set(
    ["--emit-wat", "--emit-js", "--emit-wasm", "--reencode"]
      .map((name) => optionValue(args, name))
      .filter((value): value is string => value !== null),
  );
  const path = args.find((a) => !a.startsWith("--") && !optionValues.has(a));
  if (path === undefined) {
    usage();
    return args.length === 0 ? 0 : 2;
  }
  if (!existsSync(path)) {
    process.stderr.write(`archivo no encontrado: ${path}\n`);
    return 2;
  }

  const json = args.includes("--json");
  const optimize = !args.includes("--no-dce");
  const policy = args.includes("--unrestricted") ? UNRESTRICTED_POLICY : WEB_V1_POLICY;
  const bytes = new Uint8Array(readFileSync(path));

  // --reencode no necesita ni contención ni codegen: es leer y volver a
  // escribir, que es exactamente lo que se quiere verificar.
  const reencode = optionValue(args, "--reencode");
  if (reencode !== null) {
    try {
      writeFileSync(reencode, encodeModule(loadModule(bytes, path)));
    } catch (exc) {
      process.stderr.write(`${exc instanceof Error ? exc.message : String(exc)}\n`);
      return 3;
    }
    process.stdout.write(`HIR re-serializado en: ${reencode}\n`);
    return 0;
  }

  let result;
  try {
    result = compile(bytes, path, fsResolver, { policy, optimize });
  } catch (exc) {
    process.stderr.write(`${exc instanceof Error ? exc.message : String(exc)}\n`);
    return 3;
  }

  const codegen = result.codegen;
  if (codegen !== null && codegen.ok) {
    const watPath = optionValue(args, "--emit-wat");
    if (watPath !== null && codegen.wat !== null) {
      writeFileSync(watPath, codegen.wat);
      process.stdout.write(`WAT generado en: ${watPath}\n`);
    }
    const jsPath = optionValue(args, "--emit-js");
    if (jsPath !== null && codegen.host !== null) {
      writeFileSync(jsPath, codegen.host);
      process.stdout.write(`módulo JS host generado en: ${jsPath}\n`);
    }
    const wasmPath = optionValue(args, "--emit-wasm");
    if (wasmPath !== null && codegen.wasm !== null) {
      writeFileSync(wasmPath, codegen.wasm);
      process.stdout.write(`binario generado en: ${wasmPath} (${codegen.wasm.length} bytes)\n`);
    }
  }

  if (json) {
    process.stdout.write(
      JSON.stringify(
        {
          file: path,
          policy: policy.name,
          ok: result.restrictions.ok,
          denied: [...result.restrictions.denied],
          deniedUnits: result.restrictions.deniedUnits,
          diagnostics: result.diagnostics,
          dce: Object.fromEntries(result.dce),
          codegen: codegen === null ? null : {
            ok: codegen.ok,
            wasmBytes: codegen.wasm?.length ?? 0,
            funcs: codegen.wir?.funcs.map((f) => f.name) ?? [],
          },
        },
        null,
        2,
      ) + "\n",
    );
    return result.restrictions.ok ? 0 : 1;
  }

  if (result.image !== null) {
    process.stdout.write(summarize(result.image.main.module) + "\n");
    for (const unit of result.image.units.values()) {
      process.stdout.write(`\n[unidad ${unit.alias}]\n${summarize(unit.module)}\n`);
    }
  }

  if (result.diagnostics.length > 0) {
    process.stderr.write(
      `\n=== contención del target '${policy.name}' (${result.diagnostics.length}) ===\n`,
    );
    for (const d of result.diagnostics) {
      process.stderr.write(`  ${formatDiagnostic(d)}\n`);
    }
  }

  if (result.dce.size > 0) {
    process.stdout.write("\n=== DCE ===\n");
    for (const [alias, stats] of result.dce) {
      process.stdout.write(`  ${(alias || "<principal>").padEnd(12)} ${formatStats(stats)}\n`);
    }
  }

  if (codegen !== null) {
    process.stdout.write("\n=== codegen (WIR -> wasm) ===\n");
    if (codegen.ok && codegen.wir !== null) {
      process.stdout.write(
        `  ${codegen.wir.funcs.length} funciones, ` +
          `${codegen.wir.strings.length} cadenas (${codegen.wir.dataSize} bytes), ` +
          `binario de ${codegen.wasm?.length ?? 0} bytes\n`,
      );
    } else {
      process.stdout.write(
        `  no generado: ${codegen.diagnostics.length} construcciones fuera del ` +
          "subconjunto v1\n",
      );
      for (const d of codegen.diagnostics) {
        process.stderr.write(`  ${formatDiagnostic(d)}\n`);
      }
    }
  }

  return result.restrictions.ok ? 0 : 1;
}

/**
 * Ejecuta el artefacto generado, igual que `python V0/main.py --run` hace con
 * el intérprete. Sirve para comparar los dos: mismo programa, mismo `.phir`,
 * dos ejecutores — y la salida tiene que coincidir (lo comprueba
 * `test/e2e/test_web_wasm.py`).
 *
 * Se importa el MÓDULO generado, no una versión adaptada: si esto funciona,
 * el archivo que produce `--emit-js` funciona igual en cualquier sitio.
 */
async function runGenerated(argv: readonly string[]): Promise<number> {
  const args = argv.slice(2);
  const path = args.find((a) => !a.startsWith("--"));
  if (path === undefined || !existsSync(path)) {
    process.stderr.write(`archivo no encontrado: ${path ?? "(ninguno)"}\n`);
    return 2;
  }
  const useJs = args.includes("--run-js");
  const policy = args.includes("--unrestricted") ? UNRESTRICTED_POLICY : WEB_V1_POLICY;

  let result;
  try {
    result = compile(new Uint8Array(readFileSync(path)), path, fsResolver, {
      policy,
      optimize: !args.includes("--no-dce"),
    });
  } catch (exc) {
    process.stderr.write(`${exc instanceof Error ? exc.message : String(exc)}\n`);
    return 3;
  }

  const codegen = result.codegen;
  if (codegen === null || !codegen.ok) {
    for (const d of result.diagnostics) process.stderr.write(`  ${formatDiagnostic(d)}\n`);
    process.stderr.write("no se puede ejecutar: el target web rechazó el programa\n");
    return 1;
  }

  const source = useJs ? codegen.js! : codegen.host!;
  const url = "data:text/javascript;base64," + toBase64(new TextEncoder().encode(source));
  const module = (await import(url)) as {
    run: (io: { write: (text: string) => void }) => unknown | Promise<unknown>;
  };
  const value = await module.run({ write: (text) => process.stdout.write(text) });

  // MISMO contrato que 'python V0/main.py --run': por stdout sale SOLO lo que
  // el programa imprime, y el valor de 'main' es el código de salida. Así las
  // dos ejecuciones son comparables byte a byte (test/e2e/test_web_wasm.py);
  // cualquier cosa que el ejecutor tenga que contar va por stderr.
  if (value === undefined || value === null) return 0;
  process.stderr.write(`[${useJs ? "js" : "wasm"}] main() -> ${String(value)}\n`);
  const numeric = typeof value === "bigint" ? value : BigInt(Math.trunc(Number(value)));
  return Number(BigInt.asUintN(8, numeric));
}

if (process.argv.includes("--run") || process.argv.includes("--run-js")) {
  process.exit(await runGenerated(process.argv));
}
process.exit(main(process.argv));
