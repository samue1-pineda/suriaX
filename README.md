# suriaX

<div align="center">
  <picture>
  <img src="./assets/suri_banner_.png" alt="Banner" />
  </picture>

  
  [![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14168/badge)](https://www.bestpractices.dev/projects/14168)
  [![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/samue1-pineda/suriaX/badge)](https://scorecard.dev/viewer/uri=github.com/samue1-pineda/suriaX)
  [![CI](https://github.com/samue1-pineda/suriaX/actions/workflows/ci.yml/badge.svg)](https://github.com/samue1-pineda/suriaX/actions/workflows/ci.yml)
  [![Tests](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/samue1-pineda/suriaX/badges/tests.json)](https://github.com/samue1-pineda/suriaX/actions/workflows/tests.yml)
  [![Version](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/samue1-pineda/suriaX/badges/version.json)](version.py)
  [![Release](https://img.shields.io/github/v/release/samue1-pineda/suriaX?include_prereleases&label=release)](https://github.com/samue1-pineda/suriaX/releases/latest)
  [![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

  
  [Español] | [website] | [getting started] | [current_errors] | [Documentation] 
  
</div>


[website]:TODO

[Español]:README_ES.md

[getting started]:https://samue1-pineda.github.io/suriaX/usage.html#tu-primer-programa

[current_errors]:c_errorstfix.md

[Documentation]:https://samue1-pineda.github.io/suriaX/
<br>

suriaX is a programming language whit the following goals:
- **compiler internals & visualization:** built for those students & enthusiasts who ask ¿what does every phase of the compiler give?
- **friendly syntax:** based on python and c++ suriaX always look for a easier syntax 
- **c++ interoperabilty:** by using custom Bindings suriaX let c++ run on your standar code
- **c Philosophy(libsrX):** suriaX trust on less reserved tokens & calls to libsrX
  

## project status

**ACTIVE**, working on things that already work and looking for alternatives to fix errors that already exists

**First version of the web documentation built**!

the project is currently a **Pre-Alpha Preview**. The exact number is the *Version* badge above: it comes from [`version.py`](version.py), the single source every consumer reads. Everything that is known to fail in the current version is listed in [c_errorstfix.md](c_errorstfix.md).

[**x**] language syntax & EBNF grammar

[**x**] frontend (lexer, parser, AST and typed AST, semantic analysis)

[**x**] HIR (protobuf wire format, written with the Python standard library only) and a tree-walk interpreter that runs it

[**x**] bootstrap: the compiler written in suriaX (`src/`, the V1) compiles itself, and every unit it produces is byte-identical to the Python compiler's (the fixed point) — diagnostics are next

[**/**] native backend in C++: HIR reader, MIR lowering (virtual registers + CFG), a register VM and ownership verification — no JIT and no native binaries yet

[**/**] web target: a declared subset of the language compiled to WebAssembly

[**/**] suriniX tooling: the `suri` command, a web playground that shows every compiler phase and the documentation site — the build system is still **planned**

*For the  full list of tasks, see [ROADMAP.md](ROADMAP.md).*

## architecture & internal pipeline

[architecture](ARCHITECTURE.md)

## Contributing

currently not accepting contributions 

## License

Distributed under the MIT License. See [`LICENSE`](LICENSE) for more information.
