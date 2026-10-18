/**
 * suriaX — playground.
 *
 * Todas las fases las produce el COMPILADOR (`POST /api/compile`); aquí no se
 * analiza nada. Esta capa solo decide cómo se ve cada artefacto, que es la
 * misma frontera que el proyecto mantiene entre `driver/` y `cli/`.
 *
 * Cada fase se dibuja con la forma que mejor la explica, y no todas quieren
 * la misma:
 *
 *   - tokens        una lista, donde pasar el ratón SUBRAYA su línea en el
 *                   fuente — que es la pregunta que uno le hace al análisis
 *                   léxico: "¿de dónde salió este token?";
 *   - AST / tipado  un GRAFO de cajas conectadas (`grafo.js`): un árbol
 *                   indentado esconde justo lo que uno mira en un AST, que
 *                   es su forma — cuánto se ramifica y dónde está el peso;
 *   - símbolos      un diagrama de clases (Mermaid), que es como se dibuja
 *                   una tabla de tipos con sus miembros y sus relaciones;
 *   - HIR y wasm    DOS vistas cada uno: la legible, para leer el programa,
 *                   y la cruda, para depurar el formato. Son preguntas
 *                   distintas y un solo volcado no responde bien a las dos.
 *
 * Sin dependencias ni build: un módulo ES que el navegador carga tal cual.
 */

import { dibujarGrafo } from "/grafo.js";

const $ = (id) => document.getElementById(id);

const codigo = $("codigo");
const numeros = $("numeros");
const resalte = $("resalte");
const estado = $("estado");
const contenido = $("contenido");
const pestanas = $("pestanas");
const panelDiag = $("diagnosticos");
const listaDiag = $("lista-diagnosticos");
const controles = $("controles");
const girando = $("girando");
const estadoTexto = $("estado-texto");

/**
 * Fases en el orden del pipeline: es el orden en el que se explican.
 *
 * Varias tienen DOS vistas, y la distinción es siempre la misma: una para
 * LEER el programa y otra para depurar el formato. Son preguntas distintas y
 * mezclarlas en un solo volcado no responde bien a ninguna.
 */
const FASES = [
  { id: "tokens", titulo: "Léxico", dibuja: verTokens },
  { id: "ast", titulo: "AST", grafo: true, dibuja: (d) => dibujarGrafo(d.tree) },
  { id: "typed_ast", titulo: "AST-tipado", grafo: true,
    dibuja: (d) => dibujarGrafo(d.tree) },
  {
    id: "symbols", titulo: "Símbolos",
    vistas: [
      { id: "tabla", titulo: "tabla", dibuja: verTablaSimbolos },
      { id: "uml", titulo: "diagrama", dibuja: verSimbolos },
    ],
  },
  {
    id: "hir", titulo: "HIR",
    vistas: [
      { id: "pretty", titulo: "legible", dibuja: (d) => verTexto(d.pretty) },
      { id: "text", titulo: "protobuf", dibuja: (d) => verTexto(d.text) },
    ],
  },
  { id: "link", titulo: "Enlace", dibuja: verEnlace },
  {
    id: "wasm", titulo: "WebAssembly",
    vistas: [
      { id: "pretty", titulo: "legible", dibuja: (d) => verTexto(d.pretty) },
      { id: "wat", titulo: "wat", dibuja: (d) => verTexto(d.wat) },
    ],
  },
];

const EJEMPLOS = {
  "Hola mundo": `#from io #import stdp

fn main() -> int {
    stdp.println("hola, suriaX");
    return 0;
}
`,
  "Tipos y control": `#from io #import stdp

fn clasificar(int n) -> int {
    if (n < 0) { return 1; }
    else if (n == 0) { return 2; }
    return 3;
}

fn main() -> int {
    var int total = 0;
    var int i = 0;
    while (i < 5) {
        i += 1;
        if (i == 2) { continue; }
        total = total + clasificar(i - 3);
    }
    stdp.println(f"total {total}");
    return total;
}
`,
  "Structs y enums": `#from io #import stdp

struct { int x; int y; } Punto;

enum Color { ROJO, VERDE, AZUL };

enum Dato { Vacio, Numero(int) };

fn area(Punto ptr p) -> int { return p.x * p.y; }

fn main() -> int {
    var Punto p = Punto{ x: 3, y: 4 };
    var Color c = Color.VERDE;
    match (c) {
        case Color.ROJO: { stdp.println("rojo"); }
        case Color.VERDE: { stdp.println("verde"); }
        case Color.AZUL: { stdp.println("azul"); }
    }
    stdp.println(f"area {area(&p)}");
    return 0;
}
`,
  "Propiedad y destrucción": `#from io #import stdp

struct { int id; } Recurso;

hook fn __free__(Recurso ptr r) -> void {
    stdp.println(f"libera {r.id}");
}

fn main() -> int {
    var Recurso a = Recurso{ id: 1 };
    // ligar a otro nombre dejaría DOS dueños: se transfiere
    var Recurso b = move a;
    stdp.println("fin del ambito");
    return 0;
}
`,
  "Genéricos": `#from io #import stdp

struct { T valor; } Caja<T>;

fn main() -> int {
    var Caja<int> numero = Caja<int>{ valor: 7 };
    var Caja<str> texto = Caja<str>{ valor: "siete" };
    stdp.println(f"{numero.valor} = {texto.valor}");
    return 0;
}
`,
  "Errores (try / catch)": `#from io #import stdp

fn puede_fallar(int n) -> error int {
    if (n < 0) { throw "negativo"; }
    return n;
}

fn main() -> int {
    try {
        var int r = puede_fallar(-1);
        stdp.println("no llega");
    } catch (str e) {
        stdp.println("capturado");
    }
    return 0;
}
`,
};

let ultimo = null;      // el último payload del compilador
let faseActiva = "tokens";

// --------------------------------------------------------------------------- //
// editor: numeración y resaltado de línea
// --------------------------------------------------------------------------- //

/**
 * Redibuja la numeración y la capa de resaltado.
 *
 * Las TRES capas (números, resaltado y textarea) llevan siempre las mismas
 * líneas y la misma métrica, y el tamaño lo fija la capa de resaltado, que va
 * en flujo. Antes el textarea se estiraba a mano con su `scrollHeight` y los
 * números se desalineaban en cuanto aparecía un scroll: dos alturas
 * calculadas por caminos distintos no coinciden mucho tiempo.
 */
/**
 * Los tokens de la última pasada del lexer, para colorear el editor.
 *
 * Vienen del lexer DE VERDAD (`/api/lex`), no de un resaltador propio. Un
 * resaltador propio vuelve a decidir qué es cada palabra, y entonces hay dos
 * respuestas para la misma pregunta: el editor pinta `move` como un
 * identificador y el compilador lo lee como una transferencia.
 */
let tokensDelEditor = [];

/**
 * Colorea UNA línea partiéndola por los tokens que caen en ella.
 *
 * Los tokens traen `ln`/`col`, así que no hay que buscar el lexema en el
 * texto —que se equivocaría donde aparece dos veces—. Lo que queda entre dos
 * tokens es espacio o comentario: se pinta como comentario, que es lo único
 * que el lexer no emite.
 */
function colorearLinea(texto, numero) {
  const enLinea = tokensDelEditor.filter(
    (t) => t.ln === numero && t.type !== "EOF");
  if (enLinea.length === 0) return escapar(texto) || " ";

  let salida = "";
  let cursor = 0;
  for (const tok of enLinea) {
    const inicio = tok.col - 1;
    if (inicio < cursor || inicio > texto.length) continue;
    const hueco = texto.slice(cursor, inicio);
    if (hueco) {
      // entre dos tokens solo hay espacio o un comentario
      salida += hueco.trim()
        ? `<span class="comentario">${escapar(hueco)}</span>`
        : escapar(hueco);
    }
    const lexema = texto.slice(inicio, inicio + tok.lexeme.length);
    salida += `<span class="${escapar(claseToken(tok.type))}">` +
              `${escapar(lexema)}</span>`;
    cursor = inicio + tok.lexeme.length;
  }
  const resto = texto.slice(cursor);
  if (resto) {
    salida += resto.trim()
      ? `<span class="comentario">${escapar(resto)}</span>`
      : escapar(resto);
  }
  return salida || " ";
}

function pintarLineas(activa = 0) {
  const lineas = codigo.value.split("\n");
  numeros.textContent = lineas.map((_, i) => i + 1).join("\n");
  resalte.innerHTML = lineas
    // una línea vacía necesita un carácter o la caja no ocupa su altura y
    // el resaltado se desplaza de ahí en adelante.
    .map((texto, i) => `<div${i + 1 === activa ? ' class="linea-activa"' : ""}>` +
                       `${colorearLinea(texto, i + 1)}</div>`)
    .join("");
}

/**
 * Pide los tokens y repinta. Va con retardo: se dispara cuando quien escribe
 * hace una pausa, no en cada tecla — el lexer tarda menos de un milisegundo,
 * pero una petición por pulsación es tráfico que no compra nada.
 */
let pendienteLex = null;
function relexar() {
  clearTimeout(pendienteLex);
  pendienteLex = setTimeout(async () => {
    try {
      const r = await fetch("/api/lex", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: codigo.value }),
      });
      if (!r.ok) return;
      tokensDelEditor = (await r.json()).tokens ?? [];
      pintarLineas();
    } catch {
      // sin respuesta se conserva el coloreado anterior: mejor que apagarlo
    }
  }, 250);
}

/**
 * Subraya UNA línea del fuente: la del token (o el nodo, o el diagnóstico)
 * sobre el que está el ratón.
 *
 * Se pinta en la capa de resaltado, que va debajo del textarea transparente:
 * el cursor, la selección y el teclado siguen siendo los del navegador.
 * Reimplementar un editor para poder resaltar habría costado perder todo eso.
 */
const resaltarLinea = (ln) => pintarLineas(ln);

const escapar = (t) => t.replace(/[&<>]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// --------------------------------------------------------------------------- //
// fases
// --------------------------------------------------------------------------- //

/**
 * El contrato del lenguaje, tal como lo publica el compilador.
 *
 * Contiene la categoría de CADA token y el catálogo de errores con su
 * explicación. La página no clasifica ni explica nada por su cuenta: aquí
 * hubo una heurística con expresiones regulares que decidía si `INT` era un
 * tipo o un literal, y se equivocaba — `lang_info` existe precisamente para
 * que un editor no tenga que reimplementar la gramática.
 */
let LENGUAJE = { token_categories: {}, errors: [] };

async function cargarLenguaje() {
  try {
    const r = await fetch("/api/language");
    if (r.ok) LENGUAJE = await r.json();
  } catch {
    // sin el contrato la página sigue: los tokens salen sin categoría y los
    // diagnósticos sin su explicación, pero nada se rompe.
  }
}

/** Categoría de un token, según el compilador. */
const claseToken = (tipo) => LENGUAJE.token_categories?.[tipo] ?? "meta";

/** La entrada del catálogo de un código de error, si la hay. */
const explicacionDe = (codigo) =>
  (LENGUAJE.errors ?? []).find((e) => e.code === codigo) ?? null;

/**
 * Los tokens, UNO POR LÍNEA y con su información al lado.
 *
 * Antes iban en fila, como fichas, y lo demás —posición, valor— vivía en el
 * tooltip: había que pasar el ratón por cada uno para leer lo que el lexer
 * había decidido. Un token no es una etiqueta: es una fila de datos
 * (dónde empieza, qué clase le tocó, qué texto ocupó, qué valor produjo), y
 * eso se lee comparando filas, que es justo lo que una lista permite y una
 * nube de fichas no. En columnas alineadas se ve además la corrida del
 * programa: la posición sube monótona y los saltos de línea saltan a la vista.
 *
 * `valor` solo aparece cuando NO es el lexema: es la otra mitad del trabajo
 * del análisis léxico —`"a\nb"` son seis caracteres de fuente y tres de
 * texto— y repetirlo cuando coincide sería ruido en todas las filas.
 */
function verTokens(datos) {
  const caja = document.createElement("div");
  caja.className = "tokens";

  const cabecera = document.createElement("div");
  cabecera.className = "token-cab";
  cabecera.innerHTML = '<span class="pos">ln:col</span>' +
                       '<span class="clase">token</span>' +
                       '<span class="lexema">lexema</span>' +
                       '<span class="valor">valor</span>';
  caja.appendChild(cabecera);

  for (const tok of datos.tokens) {
    if (tok.type === "EOF") continue;
    const valor = tok.value === null || tok.value === undefined
      ? "" : String(tok.value);
    const el = document.createElement("div");
    el.className = `token ${claseToken(tok.type)}`;
    el.innerHTML = `<span class="pos">${tok.ln}:${tok.col}</span>` +
                   `<span class="clase">${escapar(tok.type)}</span>` +
                   `<span class="lexema">${escapar(tok.lexeme)}</span>` +
                   `<span class="valor">` +
                   `${valor === tok.lexeme ? "" : escapar(valor)}</span>`;
    // la pregunta del análisis léxico: de dónde salió este token
    el.addEventListener("mouseenter", () => resaltarLinea(tok.ln));
    el.addEventListener("mouseleave", () => resaltarLinea(0));
    caja.appendChild(el);
  }
  return caja;
}

/**
 * La tabla de símbolos como diagrama de clases.
 *
 * El compilador ya la entrega en Mermaid (`include/symbols_uml.py`), así que
 * aquí solo se pinta. Si la librería no está disponible se muestra el texto
 * del diagrama, que se lee igual y no deja el panel vacío.
 */
// --------------------------------------------------------------------------- //
// tabla de símbolos: árbol de scopes + tabla + inspector
// --------------------------------------------------------------------------- //

/** Scope y símbolo seleccionados; se conservan entre repintados. */
let scopeSel = null;      // null = todos
let simboloSel = null;    // índice en datos.symbols

/** Cómo se nombra cada `SymbolKind` en la tabla. */
const CLASE = {
  function: "fn", var: "var", param: "param", struct: "struct", enum: "enum",
  enum_item: "item", field: "campo", import: "mod", hook: "hook", type: "tipo",
};

/** Cómo se lee la clase de un símbolo: 'const' y 'var' no son el mismo kind
 *  para el compilador, pero para quien lee la tabla son dos clases distintas. */
function claseDe(sym) {
  if (sym.kind === "var" && !sym.mutable) return "const";
  return CLASE[sym.kind] ?? sym.kind;
}

/**
 * La tabla de símbolos como la usa quien la escribe: un ÁRBOL de scopes, la
 * tabla de entradas y el detalle de una.
 *
 * El diagrama de clases (la otra vista) contesta *qué tipos hay y cómo se
 * relacionan*. Esta contesta la otra mitad —*qué nombres conoce el compilador,
 * dónde nació cada uno y dónde se usa*—, y esa mitad no cabe en un diagrama:
 * son datos por símbolo, y lo que se hace con ellos es buscarlos y compararlos.
 *
 * Las tres zonas se miran juntas a propósito: el árbol acota, la tabla
 * enumera y el inspector explica. Un panel con solo la tabla obliga a
 * adivinar a qué scope pertenece cada fila, que es justo lo que el símbolo
 * ya sabe.
 */
function verTablaSimbolos(datos) {
  const scopes = datos.scopes ?? [];
  const simbolos = datos.symbols ?? [];
  const caja = document.createElement("div");
  caja.className = "simbolos";

  // --- zona 1: el árbol de scopes ---
  const arbol = document.createElement("div");
  arbol.className = "scopes";
  arbol.appendChild(titulillo("scope tree"));
  const hijos = new Map();
  for (const sc of scopes) {
    if (!hijos.has(sc.parent)) hijos.set(sc.parent, []);
    hijos.get(sc.parent).push(sc);
  }
  const cuenta = (id) => simbolos.filter((s) => s.scope === id && !s.owner).length;
  const rama = (sc, nivel) => {
    const fila = document.createElement("button");
    fila.type = "button";
    fila.className = "scope" + (scopeSel === sc.id ? " sel" : "");
    fila.style.paddingLeft = `${6 + nivel * 14}px`;
    fila.innerHTML = `<span class="etq">${escapar(sc.label)}</span>` +
                     `<span class="sid">#${sc.id}</span>` +
                     `<span class="cuenta">${cuenta(sc.id)}</span>`;
    fila.addEventListener("click", () => {
      scopeSel = scopeSel === sc.id ? null : sc.id;
      simboloSel = null;
      pintar();
    });
    arbol.appendChild(fila);
    for (const hijo of hijos.get(sc.id) ?? []) rama(hijo, nivel + 1);
  };
  for (const raiz of hijos.get(null) ?? []) rama(raiz, 0);
  if (scopes.length === 0) arbol.appendChild(vacio("sin scopes"));

  // --- zona 2: la tabla ---
  const tabla = document.createElement("div");
  tabla.className = "tabla-simbolos";
  const visibles = simbolos
    .map((s, i) => ({ s, i }))
    .filter(({ s }) => scopeSel === null || s.scope === scopeSel);
  tabla.appendChild(titulillo(
    scopeSel === null
      ? `tabla de símbolos · ${simbolos.length}`
      : `tabla de símbolos · scope #${scopeSel} · ${visibles.length}`));
  const cab = document.createElement("div");
  cab.className = "sim-cab";
  cab.innerHTML = '<span>nombre</span><span>clase</span><span>tipo</span>' +
                  '<span>línea</span><span>scope</span><span>usos</span>';
  tabla.appendChild(cab);
  for (const { s, i } of visibles) {
    const fila = document.createElement("button");
    fila.type = "button";
    fila.className = "sim" + (simboloSel === i ? " sel" : "");
    const nombre = (s.owner ? `${s.owner}.` : "") + s.name;
    fila.innerHTML =
      `<span class="nom">${escapar(nombre)}</span>` +
      `<span class="cls">${escapar(claseDe(s))}</span>` +
      `<span class="tip">${escapar(s.type ?? "—")}</span>` +
      `<span class="num">${s.ln}</span>` +
      `<span class="num">#${s.scope}</span>` +
      `<span class="num">${s.uses.length}</span>`;
    fila.addEventListener("click", () => { simboloSel = i; pintar(); });
    // la misma regla que en el léxico: pasar el ratón enseña DÓNDE está
    fila.addEventListener("mouseenter", () => resaltarLinea(s.ln));
    fila.addEventListener("mouseleave", () => resaltarLinea(0));
    tabla.appendChild(fila);
  }
  if (visibles.length === 0) tabla.appendChild(vacio("este scope no declara nada"));

  // --- zona 3: el inspector ---
  caja.append(arbol, tabla, inspector(simbolos[simboloSel] ?? null));
  return caja;
}

function titulillo(texto) {
  const el = document.createElement("div");
  el.className = "titulillo";
  el.textContent = texto;
  return el;
}

function vacio(texto) {
  const el = document.createElement("p");
  el.className = "intro";
  el.textContent = texto;
  return el;
}

/**
 * El detalle de UN símbolo: lo que el compilador averiguó de él.
 *
 * No enseña un 'offset' ni un 'tamaño': el frontend de suriaX no decide el
 * layout —eso es del backend— e inventar un número aquí sería enseñar algo
 * que el compilador no ha calculado. Enseña, en cambio, lo que este lenguaje
 * sí sabe y otro no tendría: si el valor se TRANSFIRIÓ y en qué línea, de qué
 * tipo es hook, el rango que declara, sus parámetros de tipo.
 */
function inspector(sym) {
  const caja = document.createElement("div");
  caja.className = "inspector";
  caja.appendChild(titulillo("inspector"));
  if (sym === null) {
    caja.appendChild(vacio("elige un símbolo de la tabla"));
    return caja;
  }

  const nombre = document.createElement("div");
  nombre.className = "sim-nombre";
  nombre.textContent = (sym.owner ? `${sym.owner}.` : "") + sym.name;
  caja.appendChild(nombre);

  const campos = [
    ["tipo", sym.type ?? "—"],
    ["clase", claseDe(sym)],
    ["namespace", sym.namespace === "tipo" ? "tipos" : "valores"],
    ["scope", `#${sym.scope}`],
    ["declarado", `línea ${sym.ln}, columna ${sym.col}`],
    ["mutable", sym.kind === "var" || sym.kind === "param"
      ? (sym.mutable ? "sí" : "no (const)") : null],
    ["parámetros", sym.params === null ? null : `(${sym.params.join(", ")})`],
    ["genérico", sym.type_params.length ? `<${sym.type_params.join(", ")}>` : null],
    ["hook", sym.hook === null ? null :
      sym.hook + (sym.hook_owner ? ` de ${sym.hook_owner}` : "")],
    ["valor", sym.const_value === null ? null : String(sym.const_value)],
    ["visibilidad", sym.visibility],
    // el dato que solo tiene un lenguaje con propiedad: el valor ya no está
    ["movido", sym.moved_at === null ? null : `en la línea ${sym.moved_at}`],
  ];
  const lista = document.createElement("dl");
  lista.className = "campos";
  for (const [clave, valor] of campos) {
    if (valor === null || valor === undefined) continue;
    const dt = document.createElement("dt");
    dt.textContent = clave;
    const dd = document.createElement("dd");
    dd.textContent = valor;
    lista.append(dt, dd);
  }
  caja.appendChild(lista);

  // los USOS, uno por uno y clicables: es la mitad de la tabla de símbolos
  // que ningún volcado enseñaba, y la que contesta '¿quién toca esto?'.
  const usos = document.createElement("div");
  usos.className = "usos";
  const cabecera = document.createElement("dt");
  cabecera.textContent = `usos (${sym.uses.length})`;
  usos.appendChild(cabecera);
  if (sym.uses.length === 0) {
    usos.appendChild(vacio("no se usa en ningún sitio"));
  } else {
    const fila = document.createElement("div");
    fila.className = "fila-usos";
    for (const uso of sym.uses) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "uso";
      chip.textContent = `${uso.ln}:${uso.col}`;
      chip.addEventListener("mouseenter", () => resaltarLinea(uso.ln));
      chip.addEventListener("mouseleave", () => resaltarLinea(0));
      fila.appendChild(chip);
    }
    usos.appendChild(fila);
  }
  caja.appendChild(usos);
  return caja;
}

const SANS = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

function verSimbolos(datos) {
  const caja = document.createElement("div");
  // Se devuelve YA, con un aviso: dibujar el diagrama exige traer Mermaid, y
  // eso tarda. Un panel en blanco durante dos segundos parece un fallo.
  const aviso = document.createElement("p");
  aviso.className = "intro";
  aviso.textContent = "dibujando el diagrama…";
  caja.appendChild(aviso);

  (async () => {
    try {
      // La versión EXACTA, no '@11': con un rango, el código de un tercero
      // que entra en la página cambia el día que publican otra, sin que
      // nadie aquí lo haya visto. Subirla es editar esta línea a propósito.
      const mermaid = (await import(
        "https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.esm.min.mjs")).default;
      // La fuente es la SANS de la página, no la monoespaciada del editor, y
      // no por gusto: Mermaid decide el ancho de cada etiqueta midiéndola con
      // SU tipografía y la dibuja con la que se le pase. Una pila monoespaciada
      // sale más ancha que esa medida, así que las líneas largas se partían en
      // dos dentro de una fila calculada para una — y se montaban unas sobre
      // otras. Con la sans el texto cabe siempre dentro de lo medido.
      // (El diagrama no es código: es la tabla de símbolos.)
      mermaid.initialize({ startOnLoad: false, theme: "dark",
                           themeVariables: { fontFamily: SANS } });
      // Se mide con la fuente DEFINITIVA: si Mermaid midiera con la de
      // reemplazo y la real llegara después, las cajas quedarían estrechas.
      if (document.fonts && document.fonts.ready) await document.fonts.ready;
      const { svg } = await mermaid.render("uml-" + Date.now(), datos.mermaid);
      caja.innerHTML = svg;
      // A TAMAÑO NATURAL. Mermaid entrega el SVG con 'max-width', así que un
      // diagrama grande se encoge hasta caber en el panel y su texto queda
      // ilegible. El panel ya tiene barras de desplazamiento: es mejor mover
      // un diagrama que se lee que ver entero uno que no.
      const dibujo = caja.querySelector("svg");
      if (dibujo && dibujo.viewBox && dibujo.viewBox.baseVal) {
        const vb = dibujo.viewBox.baseVal;
        dibujo.style.maxWidth = "none";
        dibujo.setAttribute("width", String(vb.width));
        dibujo.setAttribute("height", String(vb.height));
      }
    } catch (exc) {
      // Sin Mermaid el panel NO se queda vacío: el texto del diagrama se lee
      // igual, y además dice por qué no se dibujó.
      caja.replaceChildren();
      const p = document.createElement("p");
      p.className = "motivo";
      p.textContent = "no se pudo dibujar el diagrama (" + exc.message +
                      "); este es su texto, que el compilador generó igual:";
      caja.append(p, verTexto(datos.mermaid));
    }
  })();
  return caja;
}

/**
 * Un diagnóstico, con las CUATRO cosas que el proyecto exige de un error.
 *
 * Qué falló (el mensaje), dónde (la línea del fuente con una marca bajo la
 * columna), por qué y qué hacer — esto último sale del catálogo del
 * compilador, que publica el docstring de cada clase de error: el sitio donde
 * el proyecto ya explicaba por qué existe cada uno.
 */
function verError(diag) {
  const el = document.createElement("div");
  el.className = `error ${diag.severity ?? "critical"}`;

  const cabeza = document.createElement("div");
  cabeza.className = "encabezado";
  cabeza.innerHTML =
    `<span class="codigo">${escapar(diag.code || diag.phase || "")}</span>` +
    `<span class="lugar">${diag.line}:${diag.column}</span>` +
    `<span class="texto">${escapar(diag.message)}</span>`;
  el.appendChild(cabeza);

  // el fuente señalado: la línea tal cual y una marca bajo la columna
  const lineas = codigo.value.split("\n");
  const fuente = lineas[diag.line - 1];
  if (fuente !== undefined) {
    const ancho = String(diag.line).length;
    const marca = " ".repeat(Math.max(0, (diag.column ?? 1) - 1)) + "^";
    const pre = document.createElement("pre");
    pre.className = "fragmento";
    pre.innerHTML =
      `<span class="num">${diag.line} │ </span>${escapar(fuente)}\n` +
      `<span class="num">${" ".repeat(ancho)} │ </span>` +
      `<span class="marca">${marca}</span>`;
    el.appendChild(pre);
  }

  const catalogo = explicacionDe(diag.code);
  if (catalogo?.explanation) {
    const detalle = document.createElement("details");
    detalle.className = "porque";
    const resumen = document.createElement("summary");
    resumen.textContent = `por qué existe ${diag.code}`;
    const cuerpo = document.createElement("div");
    cuerpo.className = "cuerpo";
    // el docstring viene en reStructuredText: los ``dobles acentos`` se
    // quedan como están salvo el marcador, que aquí solo es ruido.
    cuerpo.textContent = catalogo.explanation.replace(/``/g, "");
    detalle.append(resumen, cuerpo);
    el.appendChild(detalle);
  }

  el.addEventListener("mouseenter", () => resaltarLinea(diag.line));
  el.addEventListener("mouseleave", () => resaltarLinea(0));
  return el;
}

/** El panel de una fase que no produjo nada: el motivo Y sus diagnósticos. */
function verFallo(datos, fase) {
  const caja = document.createElement("div");
  caja.className = "panel-errores";
  // Un fallo INTERNO no es un error del programa, y si se enseñara igual
  // que uno, quien escribió el programa se pondría a buscar qué hizo mal.
  if (datos?.status === "error_interno") {
    caja.classList.add("interno");
    const rotulo = document.createElement("p");
    rotulo.className = "rotulo-interno";
    rotulo.textContent = "FALLO INTERNO — no es un error de tu programa";
    caja.appendChild(rotulo);
  }
  const intro = document.createElement("p");
  intro.className = "intro";
  intro.textContent = datos?.reason ?? "esta fase no produjo nada";
  caja.appendChild(intro);
  if (datos?.detail) {
    // lo que el proceso escribió al fallar: es lo que hay que copiar en el
    // reporte, así que va tal cual y seleccionable.
    const detalle = document.createElement("pre");
    detalle.className = "detalle-interno";
    detalle.textContent = datos.detail;
    caja.appendChild(detalle);
  }

  const diags = diagnosticosDe(fase, datos);
  // Los dos motivos por los que un programa no llega al target dicen cosas
  // distintas, y la acción que sugieren también: uno es definitivo, el otro
  // es trabajo pendiente del compilador. Van separados y etiquetados.
  const grupos = [
    ["NO SOPORTADO — el target web decidió no ejecutar esto",
     diags.filter((d) => d.kind === "unsupported")],
    ["NO SE PUDO COMPILAR — el codegen del target todavía no llega aquí",
     diags.filter((d) => d.kind === "not-compiled")],
    ["", diags.filter((d) => d.kind === undefined)],
  ];
  for (const [titulo, lista] of grupos) {
    if (lista.length === 0) continue;
    if (titulo) {
      const h = document.createElement("p");
      h.className = "intro";
      h.textContent = titulo;
      caja.appendChild(h);
    }
    for (const diag of lista) caja.appendChild(verError(diag));
  }
  return caja;
}

/**
 * Los diagnósticos que pertenecen a una fase.
 *
 * Los del frontend vienen etiquetados con su fase; los del target web viajan
 * dentro de su propio panel. Enseñarlos DONDE ocurrieron es lo que convierte
 * "la compilación falló" en algo que se puede arreglar.
 */
function diagnosticosDe(faseId, datos) {
  if (Array.isArray(datos?.diagnostics)) return datos.diagnostics;
  const fases = { tokens: ["lexer"], ast: ["parser"],
                  typed_ast: ["semantic"], symbols: ["semantic"],
                  hir: ["parser", "semantic", "hir"], link: ["hir"],
                  wasm: ["web"] };
  const suyas = fases[faseId];
  if (suyas === undefined) return [];
  return (ultimo?.diagnostics ?? []).filter((d) => suyas.includes(d.phase));
}

/**
 * La imagen ligada: **qué trajo** el compilador de cada librería.
 *
 * Decir "se resolvió el import de IO" no explica nada. Lo que explica es ver
 * lo que llegó: que `IO.stdp` aporta `println`, que por debajo hay un
 * prototipo `__write__` cuyo cuerpo pone quien ejecuta, y que un hook viaja
 * con su dueño para que `print(x)` sepa a quién llamar.
 */
function verEnlace(datos) {
  const caja = document.createElement("div");
  caja.className = "panel-errores";
  const intro = document.createElement("p");
  intro.className = "intro";
  intro.textContent =
    "Esto no es magia: 'print' no está en el lenguaje. El compilador resolvió " +
    "tu '#import', compiló esa librería a su PROPIA unidad y trajo lo que hay " +
    "debajo. Cada unidad viaja en su .phir junto al tuyo y el consumidor las " +
    "liga al cargar, en vez de copiarlas dentro.";
  caja.appendChild(intro);

  if (datos.libraries.length === 0) {
    const p = document.createElement("p");
    p.className = "intro";
    p.textContent = "Este programa no importa nada: todo lo que usa es del lenguaje.";
    caja.appendChild(p);
    return caja;
  }

  for (const lib of datos.libraries) {
    const uni = document.createElement("div");
    uni.className = "unidad";
    const cab = document.createElement("div");
    cab.className = "encabezado";
    cab.innerHTML =
      `<span class="codigo">${escapar(lib.alias)}</span>` +
      `<span class="lugar">${escapar(lib.phir)}` +
      (lib.bytes ? ` · ${lib.bytes} bytes` : "") + "</span>";
    uni.appendChild(cab);

    if (lib.error) {
      const p = document.createElement("p");
      p.className = "motivo";
      p.textContent = lib.error;
      uni.appendChild(p);
      caja.appendChild(uni);
      continue;
    }

    const cuerpo = document.createElement("div");
    cuerpo.className = "aporta";
    const filas = [];
    for (const fn of lib.functions) {
      filas.push(fn.prototype
        ? `<div class="fila"><span class="sig">${escapar(fn.signature)}</span>` +
          `<span class="nota">prototipo — el cuerpo lo pone quien ejecuta</span></div>`
        : `<div class="fila"><span class="sig">${escapar(fn.signature)}</span></div>`);
    }
    for (const t of lib.types) {
      filas.push(`<div class="fila"><span class="sig">type ${escapar(t)}</span></div>`);
    }
    for (const h of lib.hooks) {
      filas.push(`<div class="fila"><span class="sig">${escapar(h.name)}</span>` +
                 `<span class="nota">hook de ${escapar(h.owner)}</span></div>`);
    }
    cuerpo.innerHTML = filas.length ? filas.join("")
      : '<div class="fila"><span class="nota">no aporta símbolos: es el padre ' +
        'del paquete, y solo agrupa a sus submódulos</span></div>';
    uni.appendChild(cuerpo);
    caja.appendChild(uni);
  }

  // ...y las tablas con las que el programa DESPACHA lo que trajo
  const grupo = document.createElement("div");
  grupo.className = "depuracion";
  const tabla = (titulo, filas) => {
    if (filas.length === 0) return null;
    const t = document.createElement("table");
    t.innerHTML = `<caption>${escapar(titulo)}</caption>` +
      filas.map((f) => `<tr>${f.map((c) => `<td>${escapar(c)}</td>`).join("")}</tr>`).join("");
    return t;
  };
  const partes = [
    tabla(`hooks ligados (${datos.hooks.length})`,
          datos.hooks.map((h) => [h.name, `de ${h.owner}`])),
    tabla(`conversiones (${datos.casts.length})`,
          datos.casts.map((c) => [`${c.from} -> ${c.to}`, "__cast__"])),
  ].filter(Boolean);
  if (partes.length) {
    const p = document.createElement("p");
    p.className = "intro";
    p.textContent = "Y estas son las tablas con las que el programa despacha " +
                    "lo que trajo: 'print(x)' encuentra aquí a quién llamar.";
    caja.append(p);
    grupo.append(...partes);
    caja.appendChild(grupo);
  }
  return caja;
}

/** Lo que el compilador mide de sí mismo (botón "Depurar"). */
function verDepuracion(debug) {
  const caja = document.createElement("div");
  caja.className = "panel-errores";
  const intro = document.createElement("p");
  intro.className = "intro";
  intro.textContent = "La misma compilación, contada: cuánto tardó cada " +
                      "parte y cuánto produjo.";
  caja.appendChild(intro);
  const grupo = document.createElement("div");
  grupo.className = "depuracion";
  const tabla = (titulo, pares, sufijo = "") => {
    const t = document.createElement("table");
    t.innerHTML = `<caption>${escapar(titulo)}</caption>` +
      Object.entries(pares).map(([k, v]) =>
        `<tr><td>${escapar(k)}</td><td>${v}${sufijo}</td></tr>`).join("");
    return t;
  };
  grupo.append(tabla("tiempos", debug.times, " ms"),
               tabla("métricas", debug.metrics));
  caja.appendChild(grupo);
  return caja;
}

function verTexto(texto) {
  const pre = document.createElement("pre");
  pre.className = "volcado";
  pre.textContent = texto ?? "";
  return pre;
}

// --------------------------------------------------------------------------- //
// pestañas y render
// --------------------------------------------------------------------------- //

/** La vista elegida de cada fase que tiene más de una. */
const vistaDe = {};

function pintarPestanas() {
  pestanas.replaceChildren();
  for (const fase of FASES) {
    const datos = ultimo?.phases?.[fase.id];
    const btn = document.createElement("button");
    btn.type = "button";
    btn.role = "tab";
    btn.textContent = fase.titulo;
    btn.id = `pestana-${fase.id}`;
    btn.setAttribute("aria-selected", String(fase.id === faseActiva));
    btn.setAttribute("aria-controls", "contenido");
    if (fase.id === faseActiva) contenido.setAttribute("aria-labelledby", btn.id);
    if (ultimo && !datos?.ok) btn.classList.add("sin-datos");
    if (ultimo && diagnosticosDe(fase.id, datos).length > 0) {
      btn.classList.add("con-errores");
    }
    btn.addEventListener("click", () => { faseActiva = fase.id; pintar(); });
    pestanas.appendChild(btn);

    // Las dos vistas de una fase se eligen AQUÍ, junto a su pestaña, y no en
    // una barra aparte: pertenecen a la fase, no a la página.
    if (fase.id === faseActiva && fase.vistas) {
      const grupo = document.createElement("span");
      grupo.className = "vistas";
      for (const vista of fase.vistas) {
        const sub = document.createElement("button");
        sub.type = "button";
        sub.className = "vista";
        sub.textContent = vista.titulo;
        // no es una pestaña (no tiene su propio panel): es un botón de dos
        // posiciones, y 'aria-pressed' es lo que lo dice.
        sub.setAttribute("aria-pressed",
                         String((vistaDe[fase.id] ?? fase.vistas[0].id) === vista.id));
        sub.addEventListener("click", () => {
          vistaDe[fase.id] = vista.id;
          pintar();
        });
        grupo.appendChild(sub);
      }
      pestanas.appendChild(grupo);
    }
  }
}

// Con el teclado, las flechas pasan de una pestaña a la siguiente: es lo
// que espera quien no usa ratón (patrón de pestañas de WAI-ARIA).
pestanas.addEventListener("keydown", (ev) => {
  if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
  const lista = [...pestanas.querySelectorAll('[role="tab"]')];
  const actual = lista.indexOf(document.activeElement);
  if (actual < 0) return;
  ev.preventDefault();
  const paso = ev.key === "ArrowRight" ? 1 : -1;
  const destino = FASES[(actual + paso + FASES.length) % FASES.length];
  faseActiva = destino.id;
  pintar().then(() => document.getElementById(`pestana-${destino.id}`)?.focus());
});

/** El grafo visible, si la fase actual usa uno (la barra lo maneja). */
let grafoActivo = null;

async function pintar() {
  pintarPestanas();
  const fase = FASES.find((f) => f.id === faseActiva);
  const datos = ultimo?.phases?.[fase.id];
  contenido.replaceChildren();
  grafoActivo = null;
  controles.hidden = true;

  if (!ultimo) {
    contenido.innerHTML =
      '<p class="vacio">Escribe un programa y pulsa <b>Compilar</b>.</p>';
    return;
  }
  if (!datos || !datos.ok) {
    // "no produjo nada" no dice nada: se enseña el motivo Y los diagnósticos
    // que lo causaron, con la línea del fuente señalada.
    contenido.appendChild(verFallo(datos, fase.id));
    return;
  }

  const dibuja = fase.vistas
    ? (fase.vistas.find((v) => v.id === (vistaDe[fase.id] ?? fase.vistas[0].id))
       ?? fase.vistas[0]).dibuja
    : fase.dibuja;
  const salida = await dibuja(datos);

  if (fase.grafo) {
    grafoActivo = salida;
    controles.hidden = false;
    contenido.appendChild(salida.elemento);
    // el reparto va DESPUÉS de montar: el navegador mide una caja a 0x0
    // mientras no está en el documento.
    salida.montar();
    return;
  }

  // una fase que SÍ produjo su artefacto puede traer avisos: van encima, no
  // escondidos al fondo de la página.
  const avisos = diagnosticosDe(fase.id, null);
  if (avisos.length > 0 && !fase.vistas) {
    const caja = document.createElement("div");
    caja.className = "panel-errores";
    for (const diag of avisos) caja.appendChild(verError(diag));
    contenido.appendChild(caja);
  }
  contenido.appendChild(salida);
}

function pintarDiagnosticos(diags) {
  listaDiag.replaceChildren();
  panelDiag.hidden = diags.length === 0;
  for (const d of diags) {
    const li = document.createElement("li");
    li.className = d.severity;
    li.innerHTML =
      `<span class="codigo">${escapar(d.code || d.phase)}</span>` +
      `<span class="lugar">${d.line}:${d.column}</span>` +
      escapar(d.message);
    li.addEventListener("mouseenter", () => resaltarLinea(d.line));
    li.addEventListener("mouseleave", () => resaltarLinea(0));
    listaDiag.appendChild(li);
  }
}

// --------------------------------------------------------------------------- //
// compilar
// --------------------------------------------------------------------------- //

/**
 * Compila y redibuja.
 *
 * Compilar no es instantáneo con un programa largo —el frontend entero corre
 * en el servidor—, así que mientras trabaja se dice: un botón que no responde
 * parece roto.
 */
async function compilar({ debug = false } = {}) {
  const botones = [$("compilar"), $("depurar")];
  for (const b of botones) b.disabled = true;
  girando.hidden = false;
  estado.className = "estado";
  estadoTexto.textContent = debug ? "Compilando y midiendo…" : "Compilando…";

  // el panel de salida también: un artefacto viejo junto a un botón recién
  // pulsado parece la respuesta nueva.
  const velo = document.createElement("div");
  velo.className = "generando";
  velo.innerHTML = '<span class="girando"></span><span>generando…</span>';
  contenido.appendChild(velo);

  try {
    const respuesta = await fetch("/api/compile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: codigo.value, debug }),
    });
    const datos = await respuesta.json();
    if (!respuesta.ok) throw new Error(datos.error ?? respuesta.statusText);

    ultimo = datos;

    // Los tokens de la compilación colorean el editor: son los mismos que ya
    // vinieron, así que pedirlos otra vez a '/api/lex' sería trabajo repetido.
    tokensDelEditor = datos.phases?.tokens?.tokens ?? tokensDelEditor;
    pintarLineas();

    // El programa va DIRECTO al backend web: si el target no soporta algo, el
    // programa NO compila para ese target. Se cuenta aparte porque la causa
    // es distinta —no es un error del programa, es el alcance del target— y
    // porque la acción que sugiere también lo es.
    const delTarget = datos.diagnostics.filter((d) => d.phase === "web");
    const propios = datos.diagnostics.filter((d) => d.phase !== "web");
    const errores = propios.filter(
      (d) => d.severity === "critical" || d.severity === "panic").length;
    const avisos = propios.length - errores;

    const partes = [];
    if (errores) partes.push(`${errores} error(es)`);
    if (avisos) partes.push(`${avisos} aviso(s)`);
    if (delTarget.length) {
      const noSoportado = delTarget.some((d) => d.kind === "unsupported");
      partes.push(noSoportado
        ? `${delTarget.length} construcción(es) NO SOPORTADAS por el target web`
        : `no se pudo compilar para el target web (${delTarget.length})`);
    }
    // El estado de la respuesta manda sobre la cuenta de diagnósticos: un
    // fallo interno llega SIN diagnósticos (no es un error del programa), y
    // "Compilado sin diagnósticos" sería justo lo contrario de lo que pasó.
    const proveedores = datos.providers ?? {};
    const interno = datos.status === "error_interno";
    if (interno) {
      const quien = proveedores.compiler?.status === "error_interno"
        ? "compilador" : "target web";
      partes.unshift(`FALLO INTERNO del ${quien}: no es un error de tu programa`);
    } else if (proveedores.web?.status === "no_disponible"
               && proveedores.compiler?.status === "ok") {
      partes.push("WebAssembly no disponible en este servidor");
    }
    const hayDiagnosticos = errores || avisos || delTarget.length;
    estadoTexto.textContent = partes.length
      ? partes.join(" · ") + (hayDiagnosticos
          ? " — cada pestaña marcada (●) lo explica en su sitio"
          : " — su pestaña dice por qué")
      : "Compilado sin diagnósticos.";
    if (errores || delTarget.length || interno) estado.classList.add("error");

    // la fase de depuración solo existe si se pidió: no se enseña una
    // pestaña vacía a quien no la usa.
    const conDebug = FASES.filter((f) => f.id !== "debug");
    if (datos.debug) {
      conDebug.push({ id: "debug", titulo: "Depuración",
                      dibuja: () => verDepuracion(datos.debug) });
      datos.phases.debug = { ok: true };
    }
    FASES.length = 0;
    FASES.push(...conDebug);
    if (!datos.phases[faseActiva]) faseActiva = "tokens";

    pintarDiagnosticos(datos.diagnostics);
    await pintar();
  } catch (exc) {
    estado.className = "estado error";
    estadoTexto.textContent = `No se pudo compilar: ${exc.message}`;
  } finally {
    girando.hidden = true;
    velo.remove();
    for (const b of botones) b.disabled = false;
  }
}

// --------------------------------------------------------------------------- //
// arranque
// --------------------------------------------------------------------------- //

const selector = $("ejemplos");
for (const nombre of Object.keys(EJEMPLOS)) {
  const opcion = document.createElement("option");
  opcion.value = nombre;
  opcion.textContent = nombre;
  selector.appendChild(opcion);
}
selector.addEventListener("change", () => {
  codigo.value = EJEMPLOS[selector.value];
  pintarLineas();
  compilar();
});

controles.addEventListener("click", (ev) => {
  const btn = ev.target.closest("button");
  if (btn === null || grafoActivo === null) return;
  if (btn.dataset.zoom) grafoActivo.zoom(Number(btn.dataset.zoom));
  else if ("ajustar" in btn.dataset) grafoActivo.ajustar();
  else if ("plegar" in btn.dataset) grafoActivo.plegar();
  else if ("desplegar" in btn.dataset) grafoActivo.desplegar();
});

codigo.addEventListener("input", () => { pintarLineas(); relexar(); });
// el textarea NO tiene scroll propio (lo tiene el contenedor de las tres
// capas), así que no hay nada que sincronizar: el navegador lo hace.
$("compilar").addEventListener("click", () => compilar());
$("depurar").addEventListener("click", () => compilar({ debug: true }));
// Ctrl/Cmd + Enter compila: es el atajo que ya espera quien usa un playground
document.addEventListener("keydown", (ev) => {
  if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") {
    ev.preventDefault();
    compilar();
  }
});

codigo.value = EJEMPLOS["Hola mundo"];
pintarLineas();
pintarPestanas();
// el contrato del lenguaje PRIMERO: los tokens se colorean con sus categorías
// y los diagnósticos traen su explicación desde el primer render.
await cargarLenguaje();
await compilar();
