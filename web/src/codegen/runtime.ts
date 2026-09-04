/**
 * Runtime del host: cómo se ve un valor cuando el programa lo imprime.
 *
 * Es código JS que se **incrusta** en los dos artefactos —el módulo JS puro y
 * el host del WebAssembly—, y por eso vive aquí como texto en vez de como
 * funciones importables: los artefactos son autocontenidos, no dependen de
 * este paquete en tiempo de ejecución.
 *
 * Que exista un solo sitio es el punto entero. El backend JS y el WASM tienen
 * que imprimir EXACTAMENTE lo mismo (la suite los compara byte a byte), y
 * además los dos tienen que coincidir con el intérprete de Python, que es el
 * oráculo. Con el formateo repartido, una diferencia de un dígito en un
 * `float` aparecería como "el WASM está mal" sin que lo estuviera.
 *
 * ### Por qué el HOST formatea
 * La alternativa era formatear en WebAssembly, lo que obliga a escribir a
 * mano la conversión de `double` a texto con las reglas de CPython
 * (representación más corta que hace round-trip, punto decimal siempre
 * presente en notación fija, exponente de al menos dos dígitos). Es mucho
 * código en WASM crudo para reproducir algo que el host ya sabe hacer, y
 * cualquier desvío rompe la comparación con el intérprete.
 */

/**
 * Formateadores compartidos. Se inserta tal cual en el preámbulo de cada
 * artefacto generado.
 */
export const FORMAT_RUNTIME = `// --- formateo de valores (idéntico en los dos backends y en el intérprete) ---
function __fmtInt(v) { return String(v); }
function __fmtBool(v) { return v ? "true" : "false"; }
function __fmtChar(v) { return String.fromCodePoint(Number(v)); }

/**
 * 'float' tal como lo escribe el intérprete, que usa 'str()' de Python.
 *
 * No vale String(v): JS y Python difieren justo donde importa — String(2.0)
 * es "2" y Python dice "2.0"; String(1e16) es "10000000000000000" y Python
 * dice "1e+16". Se toman los dígitos más cortos que hacen round-trip (eso sí
 * lo da toExponential() sin argumento) y se re-formatean con las reglas de
 * CPython: notación fija salvo que el punto decimal caiga fuera de
 * (-4, 16], punto decimal siempre presente, y exponente de dos dígitos.
 */
function __fmtFloat(v) {
  if (Number.isNaN(v)) return "nan";
  if (v === Infinity) return "inf";
  if (v === -Infinity) return "-inf";
  const negative = v < 0 || Object.is(v, -0);
  const magnitude = negative ? -v : v;
  const [mantissa, exponent] = magnitude.toExponential().split("e");
  const digits = mantissa.replace(".", "");
  const decpt = Number(exponent) + 1;
  let out;
  if (decpt <= -4 || decpt > 16) {
    out = digits.length > 1 ? digits[0] + "." + digits.slice(1) : digits;
    const e = decpt - 1;
    out += "e" + (e < 0 ? "-" : "+") + String(Math.abs(e)).padStart(2, "0");
  } else if (decpt <= 0) {
    out = "0." + "0".repeat(-decpt) + digits;
  } else if (decpt >= digits.length) {
    out = digits + "0".repeat(decpt - digits.length) + ".0";
  } else {
    out = digits.slice(0, decpt) + "." + digits.slice(decpt);
  }
  return negative ? "-" + out : out;
}`;
