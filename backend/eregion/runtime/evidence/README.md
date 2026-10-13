# Career evidence

Career evidence records candidate facts with their provenance. It is separate
from preferences and memory, procedural skills, employer requirements, and
generated application materials. A job description or generated sentence cannot
establish a candidate's experience.

## Lifecycle and ownership

Each evidence item has a stable ID and an optimistic state version. Content
versions are immutable and have their own IDs and hashes. Revisions, confirmation,
rejection, supersession, and archiving preserve an event history.

Manual statements enter as candidates and require confirmation. Server-side resume
imports validate quotes against the held source, retain source identity, and
deduplicate replay. Confirmation records the accepted source or the user's
attestation; it is not independent fact checking.

Keep employer/project ownership, dates, units, qualifiers, and limitations with
the claim. A confirmed fact does not support stronger leadership, impact, scale,
degree-completion, or proficiency claims than the source supplies.

Application links cite particular confirmed versions. Removing an application
does not remove reusable evidence; archiving hides it from new retrieval while
preserving historical references.

## Runtime consumers

Session retrieval selects relevant confirmed evidence within a separate context
budget. Context snapshots record the evidence IDs, version IDs, and hashes used
for a model request.

Application packs also consume evidence. Their selection policy freezes an
application-scoped snapshot for generation and verification. Source or preference
changes can invalidate a pack, so an older confirmation is not a blanket approval
to reuse outdated material.

See [the architecture guide](../../../../docs/agent-loop.md) for source completion,
material version selection, and browser upload boundaries.

## API and implementation

The local API exposes candidate creation, confirmation, revisions, version/event
inspection, and application linking. Consult the running `/docs` page and
[`api/evidence_routes.py`](../../api/evidence_routes.py) for current endpoints.
Clients cannot claim resume provenance by posting an unchecked quote; imports
must go through the server's source-validation path.

| File | Purpose |
| --- | --- |
| `types.py`, `models.py` | Public contracts and persisted records |
| `repository.py` | Versioned mutations, source imports, links, and events |
| `retrieval.py` | Scoped confirmed-evidence selection for context |
| `extraction.py` | Evidence extraction integration |

Evidence lives in the local database and can contain personal information.
Protect local data and evaluation exports accordingly. See
[configuration and data handling](../../../../docs/configuration.md#data-and-credentials).
