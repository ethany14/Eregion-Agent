# Documentation index

## Start here

- [User guide](usage.md) and [configuration](configuration.md)
- [Single AgentLoop architecture](agent-loop.md)
- [Runtime directory map and import migration](../backend/eregion/runtime/README.md)
- [Development and repository map](development.md)
- [Backend namespace and startup](../backend/README.md)
- [Namespace cleanup and validation](diagnostics/eregion-namespace-cleanup-20261012.md)

## Current implementation and acceptance

- [LinkedIn MCP + public boards default route](diagnostics/mcp-default-route-20261012.md)
- [API/MCP source comparison](diagnostics/filter-api-mcp-comparison-20261012.md)
- [Source retrieval and repeated-read repairs](diagnostics/codex-source-repair-20261012.md)
- [Unified-loop migration evidence](diagnostics/unified-loop-final.md)
- [Workspace reorganization](diagnostics/workspace-layout-20261012.md)

Source-level comparisons and offline passing tests do not establish integrated
10–15-qualified-job acceptance. Consult each report's remaining acceptance section.

## Document roles

| Directory | Contents |
| --- | --- |
| `specs/` | Implementation plans, requirements and gate amendments |
| `diagnostics/` | Findings, implementation status, limitations and evidence references |
| `benchmarks/` | Recorded test logs, metrics and reproducible compact evidence |
| `examples/` | User-facing integration configuration examples |

The [unified execution plan](specs/claude-unified-execution-plan-20261012.md) and
[API-first gate amendment](specs/r1-r2-api-first-gate-amendment-20261012.md) describe
the migration sequence. Older optimization and Treg plans remain historical inputs;
the later default-route report records the approved MCP/public-board source policy.
Do not treat every older plan as an additional active architecture.

Root-level dated E2E reports remain at their existing paths because audit scripts
and recorded evidence reference them. New reports belong in `diagnostics/` and
measurements in `benchmarks/`. Local raw captures, sessions and databases are not
documentation and must not be published.
