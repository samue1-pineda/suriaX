/**
 * Declaraciones mínimas de node para el CLI y las pruebas.
 *
 * El backend web se compila con `"types": []` porque `src/` NO puede
 * depender de node: corre en el navegador. Pero `main.ts` (el CLI) y
 * `test/` sí necesitan leer archivos y afirmar. Instalar `@types/node`
 * arrastraría un `package.json` y un `npm install` a un paquete que hoy no
 * tiene ninguno; en su lugar, aquí está la superficie exacta que se usa —
 * si algún día crece de veinte líneas, es la señal para instalar los tipos
 * de verdad.
 */

/** `import.meta.url` de ESM: lo usan las pruebas para localizar sus fixtures. */
interface ImportMeta {
  readonly url: string;
}

/**
 * Superficie mínima de WebAssembly y TextDecoder. `src/` no las usa (el
 * codegen solo PRODUCE bytes y texto); las necesitan las pruebas, que
 * ejecutan lo generado, y por eso viven aquí y no en el paquete.
 */
declare namespace WebAssembly {
  interface Memory {
    readonly buffer: ArrayBuffer;
  }
  interface Instance {
    readonly exports: Record<string, unknown>;
  }
  function instantiate(
    bytes: Uint8Array,
    imports?: Record<string, Record<string, unknown>>,
  ): Promise<{ instance: Instance; module: unknown }>;
  function validate(bytes: Uint8Array): boolean;
}

declare class TextDecoder {
  constructor(label?: string);
  decode(input?: Uint8Array): string;
}

declare class TextEncoder {
  encode(input?: string): Uint8Array;
}

declare module "node:url" {
  /** `file://...` -> ruta del sistema de archivos. */
  export function fileURLToPath(url: string): string;
}

declare module "node:fs" {
  export function readFileSync(path: string): Uint8Array;
  export function existsSync(path: string): boolean;
  export function writeFileSync(path: string, data: string | Uint8Array): void;
}

declare module "node:path" {
  export function join(...parts: string[]): string;
  export function dirname(path: string): string;
  export function basename(path: string, ext?: string): string;
  export function resolve(...parts: string[]): string;
}

declare module "node:process" {
  const process: {
    argv: string[];
    exit(code?: number): never;
    stdout: { write(chunk: string): boolean };
    stderr: { write(chunk: string): boolean };
  };
  export default process;
}

declare module "node:test" {
  type TestFn = (name: string, fn: () => void | Promise<void>) => void;
  export const test: TestFn;
  export const it: TestFn;
  export function describe(name: string, fn: () => void): void;
  const defaultTest: TestFn;
  export default defaultTest;
}

declare module "node:assert/strict" {
  interface Assert {
    (value: unknown, message?: string): asserts value;
    equal(actual: unknown, expected: unknown, message?: string): void;
    notEqual(actual: unknown, expected: unknown, message?: string): void;
    deepEqual(actual: unknown, expected: unknown, message?: string): void;
    ok(value: unknown, message?: string): asserts value;
    throws(fn: () => unknown, expected?: unknown, message?: string): void;
    match(value: string, regexp: RegExp, message?: string): void;
    fail(message?: string): never;
  }
  const assert: Assert;
  export default assert;
}
