# R7 · LinkedIn MCP T1 live read-only validation

**Status: NOT RUN (deferred).**

T1 needs a LinkedIn account chosen explicitly by the user and a login through the pinned upstream server ([contract](linkedin-mcp-contract.md)). The current instruction does not authorize logins. No account was used, no browser login was imported, and no MCP call was made.

**Prepared limits for when T1 is authorized:**
- 3 searches + 15 details + 6 apply URLs + 2 company lookups = **26 business calls**, zero model;
- at most 2 pages per group;
- 120 s per call and 30 min per batch;
- retries count against the same budget;
- stop on login challenge, rate limit, wrong account or a call that cannot be cancelled.

The adapter enforces the call budget, page cap, deadline and stop conditions (T0).
