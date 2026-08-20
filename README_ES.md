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
`suriaX --version` y el release), asi que no puede contradecir a lo publicado.

[**X**] definicion de la sintaxis del lenguaje y gramatica mediante EBNF

[**X**] frontend(anilisis lexico, analisis sintantico y generacion del AST)

[**/**] Representaciones intermedias(HIR, MIR & lowering)

[ ] Back-end VM JIT

[ ] suriniX build system, playground web y documentacion usado LLVM - **Planeado**

*para un listado de todas las futuras implementaciones lease: [ROADMAP.md](ROADMAP.md).*

## arquitectura & pipeline interno

[architecture](ARCHITECTURE.md)

## contributing

actualmente no se aceptan contribuciones


## License

Distributed under the MIT License. See [`LICENSE`](LICENSE) for more information.
