# suriaX

<div align="center">
  <picture>
  <img src="./assets/suri_banner_.png" alt="Banner" />
  </picture>
  
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

el proyecto se encuentra en **V.0.1.1(Pre-Alpha Preview)**

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
