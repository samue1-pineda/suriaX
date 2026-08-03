# suriaX

<div align="center">
  <picture>
  <img src="./assets/suri_banner_.png" alt="Banner" />
  </picture>
  
  [Español] | [website] | [getting started] | [current_errors] | [Documentation] 
  
</div>


[website]:TODO

[Español]:README_ES.md

[getting started]:how_to_run.md

[current_errors]:c_errorstfix.md

[Documentation]:./docs/ 
<br>

suriaX is a programming language whit the following goals:
- **compiler internals & visualization:** built for those students & enthusiasts who ask ¿what does every phase of the compiler give?
- **friendly syntax:** based on python and c++ suriaX always look for a easier syntax 
- **c++ interoperabilty:** by using custom [Bindings] suriaX let c++ run on your standar code
- **c Philosophy([libsrX]):** suriaX trust on less reserved tokens & calls to libsrX
  
[Bindings]:suriaX-lang/Documentation/bindings
[LibsrX]:suriaX-lang/LibsrX

## project status

**FROZEN**, working on [iriscX](https://github.com/samue1-pineda/iriscx) and [myrscX](https://github.com/samue1-pineda/MyrscX) nexts versions **aren't implementations but changes to the documentation**.

the project is currently on **V.0.1.0 (Pre-Alpha Preview)**,

[**x**] language syntax & EBNF grammar

[**x**] frontend(lexer,parser and AST generation) -**In progress**

[**/**] Intermediate Representations(HIR, MIR & lowering)

[ ] LLVM Back-end Integration

[ ] suriniX build system, web documentation & playground -**planned**

*For the  full list of tasks, see [ROADMAP.md](ROADMAP.md).*

## architecture & internal pipeline

[architecture](ARCHITECTURE.md)

## Contributing

currently not accepting contributions 

## License

Distributed under the MIT License. See [`LICENSE`](LICENSE) for more information.
