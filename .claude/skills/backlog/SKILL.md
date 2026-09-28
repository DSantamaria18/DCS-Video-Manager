---
name: backlog
description: Anotar entradas en BACKLOG.md o trabajar una entrada (BUG-NN, FEA-NN, TEC-NN, SEC-NN, INF-NN, DOC-NN) de principio a fin siguiendo CLAUDE.md. Usar cuando David reporta un bug o una idea, o pide arreglar/implementar una entrada concreta.
argument-hint: "add <descripción> | <ID>"
---

# Flujo de backlog

`BACKLOG.md` agrupa entradas por sección con columnas `# | Título | Prioridad | Dif. | Descripción y justificación`. Prioridad P0-P3, dificultad S/M/L. Los IDs llevan prefijo por tipo (`BUG`, `FEA`, `TEC`, `SEC`, `INF`, `DOC`) y no se reutilizan: busca el número más alto de ese prefijo en `BACKLOG.md`, `CHANGELOG.md` y `git log` y continúa.

## `add <descripción>`

1. Elige sección, prefijo, prioridad y dificultad. Cita la evidencia (fichero y función) en la descripción, igual que las entradas existentes.
2. Añade la fila. Es documentación puramente descriptiva: puede ir en commit directo a `main` si David lo pide.

## `<ID>`: trabajar una entrada

1. Revisa `DECISIONS.md` (lecciones y, si toca el fichero, su rationale técnico).
2. Feature nueva o cambio de arquitectura: `SPEC.md` y plan aprobados por David antes de escribir código. Bug o ajuste puntual: directo.
3. Rama propia desde `main` (`fix/...`, `feat/...`, `chore/...`).
4. TDD: test que reproduce el bug o fija el contrato, luego el código. `python -m pytest tests/ -q` y `python -m ruff check .` en verde.
5. Si se ve en la UI, compruébalo con la skill `run-app`.
6. En la misma PR: mueve la entrada de `BACKLOG.md` a `CHANGELOG.md` (`[No publicado]`) y actualiza `README.md`, `ARCHITECTURE.md` y `DECISIONS.md` si cambian.
7. PR a `main` y `gh pr checks` para el CI real. Merge solo con aprobación de David.
