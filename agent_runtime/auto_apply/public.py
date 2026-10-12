"""The client-visible view of an application run, shared by the API and career tasks."""


def public(state):
    from agent_runtime.auto_apply.drafting import visible_drafts
    result = {key: value for key, value in state.items()
        if key not in {"profile", "answers", "review_digest", "resume_context"}}
    if isinstance(result.get('loop_runtime'), dict):
        result['loop_runtime'] = {k: v for k, v in result['loop_runtime'].items() if k != 'context_archive'}
    if "fields" in state:
        from agent_runtime.auto_apply.contracts import can_reopen
        result["answer_drafts"] = visible_drafts(state, state["fields"])
        result["can_reopen"] = can_reopen(state)
    return result
