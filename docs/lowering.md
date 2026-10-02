# Lowering

Las **bajadas** entre representaciones: de AST a HIR (Python), de HIR a MIR
(C++) y de HIR a WIR (TypeScript). Ver [ARCHITECTURE.md](../ARCHITECTURE.md).

## Etapas

| De → A | Lenguaje | Estado | Dónde | Responsabilidad |
|---|---|---|---|---|
| AST validado → HIR | Python | ✅ | [`V0/src/HIR/emmit_IR.py`](../V0/src/HIR/emmit_IR.py) | Serializa el programa con tipos, símbolos, hooks y destrucciones ya resueltos. Rechaza lo que no sabe serializar con `HIR005`. Ver [hir.md](hir.md). |
| HIR → MIR | C++ | ✅ | [`backend/src/mir.cpp`](../backend/src/mir.cpp) | Control de flujo explícito (CFG), registros virtuales, `move`/`free`/`&` marcados para la verificación de propiedad. Ver [mir.md](mir.md). |
| MIR → código de máquina | C++ | pendiente | — | El JIT. Hoy la VM **interpreta** el MIR directamente. |
| HIR → WIR | TypeScript | ✅ (subconjunto) | [`web/src/wir/lower.ts`](../web/src/wir/lower.ts) | El target web: máquina de pila con control de flujo estructurado. Ver [web/README.md](../web/README.md). |

## `move`, `free` y el drop de ámbito en cada bajada

- **Frontend → HIR:** la Semántica anota los puntos de destrucción
  (`scope_resolver`) y el HIR los transporta (`Drop`, con el drop de CAMPOS
  aplanado en rutas concretas). `--hir-pretty` los muestra (`drop`,
  `⟨transfiere⟩`, `⟨temporal …⟩`).
- **HIR → MIR:** los drops se vuelven un epílogo por salida del ámbito
  (también en un `return` temprano: lo prueba
  `test_un_return_temprano_tambien_destruye`), con una bandera de "vivo" por
  valor que se apaga con `MarkMoved`: así un valor movido no se destruye dos
  veces (`test_move_cede_el_destructor_y_por_eso_no_se_destruye_dos_veces`).
- **HIR → WIR:** el target web **no** ejecuta punteros, `free`, `move` ni
  hooks de memoria: los rechaza con `WEB0xx` (política declarada en
  [`web/src/target/policy.ts`](../web/src/target/policy.ts)).

## Pendiente

- [ ] Documentar regla por regla la bajada AST → HIR (hoy la referencia es el
      propio emisor, que tiene un método por clase de nodo).
- [ ] El JIT (MIR → código de máquina).
