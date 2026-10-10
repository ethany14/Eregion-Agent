"""Resolve current materials without hiding sibling documents in another pack."""


def latest_materials(workspace, packs, workflow, application_id):
    app = workspace.get_application(application_id)
    selected = {}
    for candidate in packs.list_for_application(application_id):
        pack = workflow.refresh_staleness(candidate.pack_id)
        if pack.snapshot_id != app.current_snapshot_id or pack.status.value == 'stale':
            continue
        for item in packs.items(pack.pack_id):
            key = (item.artifact_type, item.source_question)
            previous = selected.get(key)
            if previous is None or item.updated_at > previous[1].updated_at:
                selected[key] = (pack, item)
    return list(selected.values())


def current_materials(workspace, packs, workflow, application_id):
    selected = latest_materials(workspace, packs, workflow, application_id)
    app = workspace.get_application(application_id)
    visible = {item.pack_item_id: (pack, item) for pack, item in selected}
    successful = {}
    for candidate in packs.list_for_application(application_id):
        pack = workflow.refresh_staleness(candidate.pack_id)
        if pack.snapshot_id != app.current_snapshot_id or pack.status.value == 'stale':
            continue
        for item in packs.items(pack.pack_id):
            if not item.artifact_id or item.status.value not in {'approved', 'awaiting_review'}:
                continue
            if item.status.value == 'approved':
                # A newer approval elsewhere cannot remove this conversation's
                # intended reviewed file from the choices available for re-review.
                visible[item.pack_item_id] = (pack, item)
                continue
            key = (item.artifact_type, item.source_question, item.status.value)
            if key not in successful or item.updated_at > successful[key][1].updated_at:
                successful[key] = (pack, item)
    for pack, item in successful.values():
        visible[item.pack_item_id] = (pack, item)
    return list(visible.values())


def reviewed_selections(latest, visible, selections):
    """Resolve explicit per-document choices; stale/mismatched choices never fall back."""
    result = []
    available_types = {item.artifact_type for _, item in latest}
    if any(choice and kind not in available_types for kind, choice in selections.items()):
        raise ValueError('The explicitly selected document is no longer current for this job. Review/select the current materials again before upload.')
    for newest_pack, newest in latest:
        choice = selections.get(newest.artifact_type, {})
        selected = next(((pack, item) for pack, item in visible
            if item.artifact_type == newest.artifact_type
            and item.source_question == newest.source_question
            and item.status.value == 'approved' and item.artifact_id
            and choice == {'pack_id': pack.pack_id, 'item_id': item.pack_item_id,
                'version': item.version, 'superseding_item_id': newest.pack_item_id,
                'superseding_version': newest.version}), None)
        if choice and selected is None:
            raise ValueError('The explicitly selected document or the newer material attempt changed. Review/select the intended version again before upload; no replacement was selected.')
        result.append(selected or (newest_pack, newest))
    return result
