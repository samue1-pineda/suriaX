// @ts-check
'use strict';
/**
 * Arnés de `test_cliente_vscode.py`: carga el cliente de la extensión
 * (`tooling/vscode/extension.js`) con un módulo `vscode` FALSO y lo hace
 * hablar con el servidor de lenguaje de verdad.
 *
 * El `vscode` falso guarda lo que la extensión registra (proveedores,
 * oyentes, la colección de diagnósticos) para que el arnés haga de editor:
 * abre un documento, espera sus diagnósticos, pide hover/definición/símbolos/
 * completar, cambia el texto y desactiva la extensión. Al final escribe en
 * stdout UN JSON con lo que vio; las comprobaciones están en Python.
 *
 * No es VS Code: prueba que el cliente traduce bien el protocolo a la API,
 * no que la API se comporte como la del editor.
 *
 *     node arnes.js <carpeta de la extensión> <python> <raíz del compilador> <entrada.json>
 */

const Module = require('module');
const fs = require('fs');
const path = require('path');

const [, , carpetaExtension, python, raizCompilador, rutaEntrada] = process.argv;
const entrada = JSON.parse(fs.readFileSync(rutaEntrada, 'utf8'));

// -------------------------------------------------------------------------
// el vscode falso
// -------------------------------------------------------------------------

class Uri {
  /** @param {string} texto @param {string} [fsPath] */
  constructor(texto, fsPath) {
    this._texto = texto;
    this.fsPath = fsPath || '';
    this.scheme = texto.split(':')[0];
  }
  /** @param {string} texto */
  static parse(texto) { return new Uri(texto); }
  /** @param {string} ruta */
  static file(ruta) {
    const barras = ruta.replace(/\\/g, '/');
    return new Uri('file://' + (barras.startsWith('/') ? '' : '/') + encodeURI(barras), ruta);
  }
  toString() { return this._texto; }
}

class Range {
  /** @param {number} l1 @param {number} c1 @param {number} l2 @param {number} c2 */
  constructor(l1, c1, l2, c2) {
    this.start = { line: l1, character: c1 };
    this.end = { line: l2, character: c2 };
  }
}

const registrados = {
  /** @type {Record<string, any>} */ proveedores: {},
  /** @type {Record<string, Function[]>} */ oyentes: {},
  /** @type {any} */ fabricaDepurador: null,
  /** @type {string[]} */ comandos: [],
  /** @type {string[]} */ avisos: [],
  /** @type {string[]} */ registro: [],
};
/** @type {Map<string, any[]>} */
const diagnosticos = new Map();
/** @type {((uri: string) => void)[]} */
let alPublicar = [];

/** @param {string} nombre */
function oyente(nombre) {
  return (/** @type {Function} */ f) => {
    (registrados.oyentes[nombre] = registrados.oyentes[nombre] || []).push(f);
    return { dispose() {} };
  };
}
/** @param {string} nombre */
function proveedor(nombre) {
  return (/** @type {any} */ _selector, /** @type {any} */ p) => {
    registrados.proveedores[nombre] = p;
    return { dispose() {} };
  };
}
const avisa = (/** @type {string} */ m) => { registrados.avisos.push(m); return Promise.resolve(undefined); };

const vscode = {
  Uri, Range,
  DiagnosticSeverity: { Error: 0, Warning: 1, Information: 2, Hint: 3 },
  Diagnostic: class {
    /** @param {any} rango @param {string} mensaje @param {number} severidad */
    constructor(rango, mensaje, severidad) { this.range = rango; this.message = mensaje; this.severity = severidad; }
  },
  DiagnosticRelatedInformation: class {
    /** @param {any} lugar @param {string} mensaje */
    constructor(lugar, mensaje) { this.location = lugar; this.message = mensaje; }
  },
  Location: class {
    /** @param {Uri} uri @param {Range} rango */
    constructor(uri, rango) { this.uri = uri; this.range = rango; }
  },
  MarkdownString: class {
    /** @param {string} valor */
    constructor(valor) { this.value = valor; }
  },
  Hover: class {
    /** @param {any} contenido @param {Range} [rango] */
    constructor(contenido, rango) { this.contents = [contenido]; this.range = rango; }
  },
  DocumentSymbol: class {
    /** @param {string} nombre @param {string} detalle @param {number} tipo @param {Range} r @param {Range} s */
    constructor(nombre, detalle, tipo, r, s) {
      this.name = nombre; this.detail = detalle; this.kind = tipo; this.range = r; this.selectionRange = s;
      /** @type {any[]} */ this.children = [];
    }
  },
  CompletionItem: class {
    /** @param {string} etiqueta @param {number} tipo */
    constructor(etiqueta, tipo) { this.label = etiqueta; this.kind = tipo; }
  },
  DebugAdapterExecutable: class {
    /** @param {string} orden @param {string[]} args @param {any} opciones */
    constructor(orden, args, opciones) { this.command = orden; this.args = args; this.options = opciones; }
  },
  window: {
    createOutputChannel: () => ({
      appendLine: (/** @type {string} */ t) => registrados.registro.push(t),
      append: (/** @type {string} */ t) => registrados.registro.push(t),
      show() {}, dispose() {},
    }),
    showErrorMessage: avisa, showWarningMessage: avisa, showInformationMessage: avisa,
  },
  languages: {
    createDiagnosticCollection: () => ({
      set(/** @type {Uri} */ uri, /** @type {any[]} */ lista) {
        diagnosticos.set(uri.toString(), lista);
        alPublicar.forEach((f) => f(uri.toString()));
      },
      delete(/** @type {Uri} */ uri) { diagnosticos.delete(uri.toString()); },
      clear() { diagnosticos.clear(); },
      dispose() {},
    }),
    registerHoverProvider: proveedor('hover'),
    registerDefinitionProvider: proveedor('definicion'),
    registerDocumentSymbolProvider: proveedor('simbolos'),
    registerCompletionItemProvider: proveedor('completar'),
  },
  workspace: {
    isTrusted: true,
    workspaceFolders: [{ uri: Uri.file(entrada.carpeta), name: 'prueba', index: 0 }],
    /** @type {any[]} */ textDocuments: [],
    getConfiguration: () => ({
      get: (/** @type {string} */ clave) => ({ pythonPath: python, compilerRoot: raizCompilador })[clave],
    }),
    onDidOpenTextDocument: oyente('abre'),
    onDidChangeTextDocument: oyente('cambia'),
    onDidCloseTextDocument: oyente('cierra'),
    onDidChangeConfiguration: oyente('configuracion'),
    onDidGrantWorkspaceTrust: oyente('confianza'),
  },
  commands: {
    registerCommand: (/** @type {string} */ nombre) => { registrados.comandos.push(nombre); return { dispose() {} }; },
  },
  debug: {
    registerDebugAdapterDescriptorFactory: (/** @type {string} */ _tipo, /** @type {any} */ f) => {
      registrados.fabricaDepurador = f;
      return { dispose() {} };
    },
  },
};

const cargar = /** @type {any} */ (Module)._load;
/** @type {any} */ (Module)._load = function (/** @type {string} */ pedido, /** @type {any[]} */ ...resto) {
  return pedido === 'vscode' ? vscode : cargar.call(this, pedido, ...resto);
};

// -------------------------------------------------------------------------
// el editor
// -------------------------------------------------------------------------

/** @param {string} uri @param {(lista: any[]) => boolean} condicion */
function esperaDiagnosticos(uri, condicion) {
  return new Promise((resolver) => {
    const mira = (/** @type {string} */ u) => {
      if (u === uri && condicion(diagnosticos.get(uri) || [])) {
        alPublicar = alPublicar.filter((f) => f !== mira);
        resolver(diagnosticos.get(uri));
      }
    };
    alPublicar.push(mira);
  });
}

/** @param {any} p */
const posicion = (p) => ({ line: p.line, character: p.character });

async function principal() {
  const uri = Uri.file(path.join(entrada.carpeta, 'prog.srcx'));
  let texto = entrada.roto;
  let version = 1;
  const documento = {
    uri, languageId: 'suriax', get version() { return version; }, getText: () => texto,
  };
  vscode.workspace.textDocuments.push(documento);

  const extension = require(path.join(carpetaExtension, 'extension.js'));
  const paquete = JSON.parse(fs.readFileSync(path.join(carpetaExtension, 'package.json'), 'utf8'));
  const contexto = { extensionPath: carpetaExtension, extension: { packageJSON: paquete }, subscriptions: [] };
  const conError = esperaDiagnosticos(uri.toString(), (l) => l.length > 0);
  extension.activate(contexto);
  const diagnosticosRotos = await conError;

  // corregido en el editor (sin guardar): los diagnósticos se vacían
  texto = entrada.programa;
  version = 2;
  const limpio = esperaDiagnosticos(uri.toString(), (l) => l.length === 0);
  registrados.oyentes.cambia.forEach((f) => f({ document: documento }));
  await limpio;

  const nada = { isCancellationRequested: false };
  const hover = await registrados.proveedores.hover.provideHover(documento, posicion(entrada.hover), nada);
  const definicion = await registrados.proveedores.definicion.provideDefinition(documento, posicion(entrada.definicion), nada);
  const simbolos = await registrados.proveedores.simbolos.provideDocumentSymbols(documento, nada);
  const completar = await registrados.proveedores.completar.provideCompletionItems(documento, posicion(entrada.completar), nada);
  const depurador = registrados.fabricaDepurador.createDebugAdapterDescriptor({ workspaceFolder: vscode.workspace.workspaceFolders[0] });

  await extension.deactivate();
  process.stdout.write(JSON.stringify({
    diagnosticosRotos: diagnosticosRotos.map((/** @type {any} */ d) => ({
      code: d.code, severity: d.severity, message: d.message, range: d.range })),
    hover: hover && { valor: hover.contents[0].value, range: hover.range },
    definicion: definicion && { uri: definicion.uri.toString(), range: definicion.range },
    simbolos: simbolos.map((/** @type {any} */ s) => ({ name: s.name, kind: s.kind,
      children: s.children.map((/** @type {any} */ h) => h.name) })),
    completar: completar.map((/** @type {any} */ c) => c.label),
    depurador: { command: depurador.command, args: depurador.args, options: depurador.options },
    comandos: registrados.comandos,
    avisos: registrados.avisos,
    registro: registrados.registro,
  }));
}

// si algo se cuelga, se dice en vez de esperar al límite de la suite
const reloj = setTimeout(() => {
  process.stderr.write('el arnés no terminó en 90 s\n' + registrados.registro.join('\n'));
  process.exit(3);
}, 90000);
principal().then(() => clearTimeout(reloj), (error) => {
  process.stderr.write(`fallo del arnés: ${error && error.stack}\n${registrados.registro.join('\n')}`);
  process.exit(2);
});
