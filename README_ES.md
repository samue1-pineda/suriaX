# suriaX

<div align="center">
  <picture>
  <img src="./assets/suri_banner_.png" alt="Banner" />
  </picture>
  
  [![CI](https://github.com/samue1-pineda/suriaX/actions/workflows/ci.yml/badge.svg)](https://github.com/samue1-pineda/suriaX/actions/workflows/ci.yml)
  [![Pruebas](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/samue1-pineda/suriaX/badges/tests.json)](https://github.com/samue1-pineda/suriaX/actions/workflows/tests.yml)
  [![Versión](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/samue1-pineda/suriaX/badges/version.json)](version.py)
  [![Release](https://img.shields.io/github/v/release/samue1-pineda/suriaX?include_prereleases&label=release)](https://github.com/samue1-pineda/suriaX/releases/latest)
  [![Licencia: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

  [![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14168/badge)](https://www.bestpractices.dev/projects/14168)
  [![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/samue1-pineda/suriaX/badge)](https://scorecard.dev/viewer/uri=github.com/samue1-pineda/suriaX)

  [English] | [pagina web] | [getting started] | [errores actuales] | [Documentacion] 
  
</div>

[pagina web]:TODO

[English]:README.md

[getting started]:how_to_run.md

[errores actuales]:c_errorstfix.md

[Documentacion]:./docs/ 

<br>

suriaX es un lenguaje de programacion con los siguientes objetivos:

- **visualizacion de las entrañas del compilador**: escrito para aquellos estudiantes o entusiastas que se pregunta: ¿que hay detras de cada fase del compilador?
- **sintaxis amigable**: basado en python y c++ suriaX siempre esta en busca de tener una sintaxis sencilla de comprender
- **interoperabilidad con c++**: haciendo uso de bindings, suriaX deja que c++ se ejecute en tu codigo estandar
- **filosofia c(libsrX)**:suriaX confia en el uso de pocas palabras reservadas y llamadas a libsrX


## estado del proyecto

**ACTIVO**, mejorando lo que ya funciona e investigando posibles soluciones para multiples errores.

[iriscX] y [myrscX] pasan a 2do plano hasta nuevas versiones

el proyecto es una **Pre-Alpha Preview**. El numero exacto es la medalla
*Version* de arriba: sale de [`version.py`](version.py), la fuente unica que
leen todos los consumidores (CMake, el sitio de documentacion,
`suri --version` y el release), asi que no puede contradecir a lo publicado.
Todo lo que se sabe que falla en la version vigente esta en
[c_errorstfix.md](c_errorstfix.md).

[**X**] definicion de la sintaxis del lenguaje y gramatica mediante EBNF

[**X**] frontend (analisis lexico, analisis sintactico, AST y AST tipado, analisis semantico)

[**X**] HIR (formato protobuf, escrito solo con la biblioteca estandar de Python) y un interprete tree-walk que lo ejecuta

[**X**] bootstrap: el compilador escrito en suriaX (`src/`, la V1) alcanzo el punto fijo en la 0.4.0: se compilaba a si mismo, y cada unidad que producia era identica byte a byte a la del compilador en Python. Hoy la V1 esta atrasada respecto del lenguaje de la 0.4.1 y el punto fijo esta roto hasta que se ponga al dia (ver [c_errorstfix.md](c_errorstfix.md))

[**/**] backend nativo en C++: lector del HIR, lowering a MIR (registros virtuales + CFG), una VM de registros y verificacion de propiedad — sin JIT y sin binarios nativos todavia

[**/**] target web: un subconjunto declarado del lenguaje compilado a WebAssembly

[**/**] tooling suriniX: el comando `suri`, un playground web que muestra cada fase del compilador, un servidor de lenguaje (LSP), un depurador (DAP), una extension de VS Code y el sitio de documentacion — el build system sigue **planeado**

*para un listado de todas las futuras implementaciones lease: [ROADMAP.md](ROADMAP.md).*

## arquitectura & pipeline interno

[architecture](ARCHITECTURE.md)

## contributing

actualmente no se aceptan contribuciones


## License

Distributed under the MIT License. See [`LICENSE`](LICENSE) for more information.
