/**
 * Grafo de nodos: el AST como cajas conectadas, no como una lista indentada.
 *
 * Un árbol indentado esconde justo lo que uno quiere ver de un AST: la
 * FORMA. En un grafo se lee de un vistazo qué cuelga de qué, cuánto se
 * ramifica cada nodo y dónde está el peso del programa.
 *
 * ### Cómo está hecho
 * Las cajas son **HTML** y las aristas un **SVG detrás**. Dibujar el texto
 * dentro del SVG habría costado poder seleccionarlo y copiarlo, y habría
 * obligado a medir cada cadena a mano; así el navegador mide las cajas y este
 * módulo solo las coloca.
 *
 * ### El reparto
 * Un JSON es un árbol, así que basta un *tidy tree* clásico y no hace falta
 * un algoritmo de grafos generales:
 *
 *  - la **columna** de un nodo es su profundidad;
 *  - una **hoja** ocupa la siguiente altura libre de su columna;
 *  - un nodo **interno** se centra sobre sus hijos, y si eso lo solapa con
 *    algo ya colocado en su columna, baja lo justo (y arrastra su subárbol).
 *
 * Sin dependencias: ni librería de grafos ni build.
 */

/** Campos que ya se muestran en el título y no se repiten como fila. */
const EN_TITULO = new Set(["__node__", "node", "kind", "ln", "col", "restype",
                           "return_restype"]);

const SEPARACION_X = 56;   // hueco entre columnas
const SEPARACION_Y = 14;   // hueco entre cajas de una misma columna

const escapar = (t) => String(t).replace(/[&<>]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

/** ¿Este valor merece una caja propia, o cabe como una fila? */
function esRama(valor) {
  if (valor === null || typeof valor !== "object") return false;
  if (Array.isArray(valor)) return valor.some((v) => v !== null && typeof v === "object");
  return true;
}

/** Texto corto de un valor escalar (se recorta: la caja no es un visor). */
function comoTexto(valor) {
  if (typeof valor === "string") return valor.length > 40 ? valor.slice(0, 39) + "…" : valor;
  if (Array.isArray(valor)) return valor.length === 0 ? "[]" : `[${valor.join(", ")}]`;
  return String(valor);
}

/**
 * Construye el árbol de nodos a dibujar a partir del JSON del compilador.
 *
 * Un array de nodos NO produce una caja intermedia: sus elementos cuelgan
 * directamente del padre con la etiqueta `campo[i]`. Una caja "items" que
 * solo contiene otras cajas sería una fila de ruido en cada nivel.
 */
function construir(valor, etiqueta, padre) {
  const nodo = {
    etiqueta,
    titulo: valor.__node__ ?? valor.node ?? valor.kind ?? "objeto",
    tipo: valor.restype ?? valor.return_restype ?? null,
    ln: valor.ln ?? 0,
    col: valor.col ?? 0,
    filas: [],
    hijos: [],
    padre,
    plegado: false,
  };
  for (const [clave, hijo] of Object.entries(valor)) {
    if (EN_TITULO.has(clave)) continue;
    if (!esRama(hijo)) {
      nodo.filas.push([clave, comoTexto(hijo)]);
      continue;
    }
    if (Array.isArray(hijo)) {
      hijo.forEach((elem, i) => {
        if (elem !== null && typeof elem === "object") {
          nodo.hijos.push(construir(elem, `${clave}[${i}]`, nodo));
        } else {
          nodo.filas.push([`${clave}[${i}]`, comoTexto(elem)]);
        }
      });
    } else {
      nodo.hijos.push(construir(hijo, clave, nodo));
    }
  }
  return nodo;
}

function cajaDe(nodo, esRaiz) {
  const el = document.createElement("div");
  el.className = "caja" + (esRaiz ? " raiz" : "");

  const titulo = document.createElement("div");
  titulo.className = "titulo";
  titulo.innerHTML =
    (nodo.etiqueta ? `<span class="clave">${escapar(nodo.etiqueta)}</span>` : "") +
    `<span class="nombre">${escapar(nodo.titulo)}</span>` +
    (nodo.tipo ? `<span class="tipo">:${escapar(nodo.tipo)}</span>` : "") +
    (nodo.hijos.length ? `<span class="contador">${nodo.hijos.length}</span>` : "") +
    (nodo.ln ? `<span class="lugar">${nodo.ln}:${nodo.col}</span>` : "");
  el.appendChild(titulo);

  if (nodo.filas.length) {
    const campos = document.createElement("div");
    campos.className = "campos";
    for (const [clave, dato] of nodo.filas) {
      const fila = document.createElement("div");
      fila.className = "fila";
      fila.innerHTML = `<span class="clave">${escapar(clave)}:</span>` +
                       `<span class="dato">${escapar(dato)}</span>`;
      campos.appendChild(fila);
    }
    el.appendChild(campos);
  }
  nodo.el = el;
  nodo.titulo_el = titulo;
  return el;
}

/** Reparte el árbol: columna por profundidad, y cada nodo centrado sobre sus hijos. */
function repartir(raiz) {
  const columnas = [];   // ancho máximo de cada columna
  const libre = [];      // siguiente altura libre de cada columna

  (function medir(nodo, prof) {
    nodo.prof = prof;
    nodo.w = nodo.el.offsetWidth;
    nodo.h = nodo.el.offsetHeight;
    columnas[prof] = Math.max(columnas[prof] ?? 0, nodo.w);
    if (!nodo.plegado) for (const hijo of nodo.hijos) medir(hijo, prof + 1);
  })(raiz, 0);

  const x = [];
  let acumulado = 0;
  for (let i = 0; i < columnas.length; i++) {
    x[i] = acumulado;
    acumulado += columnas[i] + SEPARACION_X;
  }

  const desplazar = (nodo, dy) => {
    nodo.y += dy;
    libre[nodo.prof] = Math.max(libre[nodo.prof] ?? 0, nodo.y + nodo.h + SEPARACION_Y);
    if (!nodo.plegado) for (const hijo of nodo.hijos) desplazar(hijo, dy);
  };

  (function colocar(nodo) {
    // La columna se fija SIEMPRE y lo primero: el camino en el que un nodo se
    // desplazaba salía antes de asignarla, y ese nodo acababa dibujado en la
    // columna 0 —encima de otro— con un `left` sin valor.
    nodo.x = x[nodo.prof];
    const hijos = nodo.plegado ? [] : nodo.hijos;
    if (hijos.length === 0) {
      nodo.y = libre[nodo.prof] ?? 0;
    } else {
      for (const hijo of hijos) colocar(hijo);
      // centrado sobre sus hijos: lo que hace que el grafo se lea
      const primero = hijos[0];
      const ultimo = hijos[hijos.length - 1];
      nodo.y = (primero.y + (ultimo.y + ultimo.h)) / 2 - nodo.h / 2;
      const minimo = libre[nodo.prof] ?? 0;
      if (nodo.y < minimo) {
        // no cabe donde le tocaría: baja él y TODO su subárbol, para no
        // separar a un padre de sus hijos.
        desplazar(nodo, minimo - nodo.y);
        return;
      }
    }
    libre[nodo.prof] = nodo.y + nodo.h + SEPARACION_Y;
  })(raiz);

  return { ancho: acumulado, alto: Math.max(...libre.filter(Number.isFinite), 0) };
}

/**
 * Dibuja el grafo de `datos` (el JSON de una fase) dentro de un contenedor
 * con pan y zoom. Devuelve los mandos que usa la barra de controles.
 */
export function dibujarGrafo(datos) {
  const marco = document.createElement("div");
  marco.className = "grafo";
  const lona = document.createElement("div");
  lona.className = "lona";
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  lona.appendChild(svg);
  marco.appendChild(lona);

  const raiz = construir(datos, null, null);

  // Un AST grande no se lee entero: se pliega a partir de cierta profundidad
  // y quien quiera baja. Mostrarlo todo de golpe da una maraña ilegible y
  // tarda en repartirse.
  const total = (function contar(n) {
    return 1 + n.hijos.reduce((s, h) => s + contar(h), 0);
  })(raiz);
  if (total > 120) {
    (function plegarHondo(n, prof) {
      if (prof >= 2 && n.hijos.length) n.plegado = true;
      for (const h of n.hijos) plegarHondo(h, prof + 1);
    })(raiz, 0);
  }

  let escala = 1, dx = 0, dy = 0;

  function pintar() {
    // las cajas se crean y se MIDEN antes de repartir: el navegador sabe
    // cuánto ocupa cada texto mejor que cualquier estimación.
    for (const el of lona.querySelectorAll(".caja")) el.remove();
    const visibles = [];
    (function recoger(nodo, esRaiz) {
      visibles.push(nodo);
      lona.appendChild(cajaDe(nodo, esRaiz));
      nodo.el.classList.toggle("plegado", nodo.plegado);
      if (!nodo.plegado) for (const h of nodo.hijos) recoger(h, false);
    })(raiz, true);

    const { ancho, alto } = repartir(raiz);
    svg.setAttribute("width", ancho);
    svg.setAttribute("height", alto);
    let aristas = "";
    for (const nodo of visibles) {
      nodo.el.style.left = `${nodo.x}px`;
      nodo.el.style.top = `${nodo.y}px`;
      nodo.titulo_el.addEventListener("click", () => {
        if (!nodo.hijos.length) return;
        nodo.plegado = !nodo.plegado;
        pintar();
      });
      if (nodo.plegado) continue;
      for (const hijo of nodo.hijos) {
        const x1 = nodo.x + nodo.w, y1 = nodo.y + nodo.h / 2;
        const x2 = hijo.x, y2 = hijo.y + hijo.h / 2;
        const medio = (x1 + x2) / 2;
        aristas += `<path d="M${x1},${y1} C${medio},${y1} ${medio},${y2} ${x2},${y2}"/>`;
      }
    }
    svg.innerHTML = aristas;
    aplicar();
    return { ancho, alto };
  }

  const aplicar = () => {
    lona.style.transform = `translate(${dx}px, ${dy}px) scale(${escala})`;
  };

  // NO se reparte todavía: el navegador mide una caja a 0x0 mientras no está
  // en el documento, y con eso el reparto apila todo en el origen. Se pinta
  // al MONTAR (ver 'montar'), que es cuando las medidas existen.
  const medidas = { ancho: 0, alto: 0 };

  // --- pan y zoom ----------------------------------------------------- //
  let arrastrando = false, x0 = 0, y0 = 0;
  marco.addEventListener("pointerdown", (ev) => {
    if (ev.target.closest(".titulo")) return;   // plegar no es arrastrar
    arrastrando = true;
    x0 = ev.clientX - dx;
    y0 = ev.clientY - dy;
    marco.classList.add("arrastrando");
    marco.setPointerCapture(ev.pointerId);
  });
  marco.addEventListener("pointermove", (ev) => {
    if (!arrastrando) return;
    dx = ev.clientX - x0;
    dy = ev.clientY - y0;
    aplicar();
  });
  const soltar = () => { arrastrando = false; marco.classList.remove("arrastrando"); };
  marco.addEventListener("pointerup", soltar);
  marco.addEventListener("pointercancel", soltar);

  marco.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    // el zoom se ancla en el puntero: acercarse a lo que uno está mirando
    const caja = marco.getBoundingClientRect();
    const px = ev.clientX - caja.left, py = ev.clientY - caja.top;
    const factor = ev.deltaY < 0 ? 1.12 : 1 / 1.12;
    const nueva = Math.min(2.5, Math.max(0.15, escala * factor));
    dx = px - (px - dx) * (nueva / escala);
    dy = py - (py - dy) * (nueva / escala);
    escala = nueva;
    aplicar();
  }, { passive: false });

  /** El tamaño por debajo del cual el texto deja de leerse. */
  const ESCALA_MINIMA = 0.45;

  function ajustar() {
    const caja = marco.getBoundingClientRect();
    if (!caja.width || !medidas.ancho) return;
    // Encuadrar no puede significar "hazlo ilegible": un AST es ancho por
    // naturaleza y forzarlo entero en el panel lo deja en letra que nadie
    // lee. Se encoge hasta un mínimo y a partir de ahí se navega —para eso
    // están el arrastre y la rueda.
    const cabe = Math.min((caja.width - 24) / medidas.ancho,
                          (caja.height - 24) / Math.max(medidas.alto, 1));
    escala = Math.min(1, Math.max(ESCALA_MINIMA, cabe));
    dx = 12;
    dy = 12;
    aplicar();
  }

  function plegarTodo(plegado) {
    (function recorrer(n, prof) {
      if (prof > 0 && n.hijos.length) n.plegado = plegado;
      for (const h of n.hijos) recorrer(h, prof + 1);
    })(raiz, 0);
    Object.assign(medidas, pintar());
    ajustar();
  }

  return {
    elemento: marco,
    /**
     * Reparte y encuadra, YA con el grafo dentro del documento.
     *
     * Es un paso aparte porque el reparto depende de cuánto ocupa cada caja,
     * y eso solo lo sabe el navegador cuando el elemento está montado: hasta
     * entonces todas miden 0x0 y el resultado es una pila en el origen. Se
     * notaba en que el grafo salía revuelto y se ordenaba solo al plegar —
     * que era la primera vez que se repartía con medidas de verdad.
     */
    montar() {
      Object.assign(medidas, pintar());
      // Se abre a TAMAÑO NATURAL, arriba a la izquierda, que es por donde se
      // empieza a leer un árbol. Encuadrarlo entero de entrada dejaba la
      // letra tan pequeña que el grafo no se podía leer, y un grafo que no
      // se lee no explica nada: para la vista general está 'Ajustar'.
      escala = 1;
      // ...y encuadrada EN LA RAÍZ, no en el origen del lienzo: un nodo se
      // centra sobre sus hijos, así que con un subárbol alto la raíz cae muy
      // abajo y la vista arrancaba en un hueco vacío.
      const caja = marco.getBoundingClientRect();
      dx = 12 - raiz.x;
      dy = Math.round((caja.height || 400) / 2 - (raiz.y + raiz.h / 2));
      aplicar();
    },
    ajustar,
    zoom(paso) {
      escala = Math.min(2.5, Math.max(0.15, escala * (paso > 0 ? 1.2 : 1 / 1.2)));
      aplicar();
    },
    plegar: () => plegarTodo(true),
    desplegar: () => plegarTodo(false),
  };
}
