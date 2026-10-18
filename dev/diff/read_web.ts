/**
 * LECTURA en el target web: decodifica un .phir y liga sus unidades, SIN
 * contener, optimizar, generar WebAssembly ni ejecutar.
 *
 * Usa las mismas piezas que el CLI del web ('web/src/hir/decode.ts' a través
 * de 'linkImage' de 'web/src/hir/link.ts') con un resolutor de archivos igual
 * al de 'web/main.ts'. 'node web/main.ts x.phir' sin '--run' no sirve para
 * esto: además contiene, hace DCE y genera el wasm.
 *
 * Uso: node dev/diff/read_web.ts dumps/prog.srcx.phir
 */

import { existsSync, readFileSync } from "node:fs";
import process from "node:process";

import { linkImage, resolveRelative, type PhirResolver } from "../../web/src/hir/link.ts";

const fsResolver: PhirResolver = (relativePath, fromPath) => {
  const path = resolveRelative(fromPath, relativePath);
  return existsSync(path) ? new Uint8Array(readFileSync(path)) : null;
};

function main(argv: readonly string[]): number {
  const path = argv[2];
  if (path === undefined || !existsSync(path)) {
    process.stderr.write(`archivo no encontrado: ${path ?? "(ninguno)"}\n`);
    return 2;
  }
  try {
    const image = linkImage(new Uint8Array(readFileSync(path)), path, fsResolver);
    process.stdout.write(`imagen ligada: ${1 + image.units.size} unidad(es)\n`);
  } catch (exc) {
    process.stderr.write(`${exc instanceof Error ? exc.message : String(exc)}\n`);
    return 3;
  }
  return 0;
}

process.exit(main(process.argv));
