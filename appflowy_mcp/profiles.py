"""Shared tool annotations and explicit registration of the legacy profile."""

# Tool behavior hints for MCP clients (advisory — they help an agent choose safe
# operations; they are NOT a security boundary). readOnly = performs no writes;
# destructive = makes an irreversible change; idempotent = repeating with the same
# args reaches the same state; openWorld = calls the external AppFlowy service (always
# true here). Both profiles reuse these conservative presets.
READ = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
CREATE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}
WRITE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
DESTRUCTIVE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": True,
}


_LEGACY_TOOLS = (
    ("get_workspaces", READ),
    ("get_workspace_folder", READ),
    ("get_database_fields", READ),
    ("get_database_row_ids", READ),
    ("get_database_row_details", READ),
    ("create_database_row", CREATE),
    ("upsert_database_row", WRITE),
    ("list_updated_rows", READ),
    ("list_databases", READ),
    ("create_page", CREATE),
    ("create_database", CREATE),
    ("create_database_view", CREATE),
    ("add_database_field", CREATE),
    ("update_database_field", WRITE),
    ("delete_database_field", DESTRUCTIVE),
    ("add_select_option", WRITE),
    ("delete_select_option", DESTRUCTIVE),
    ("set_group_by", WRITE),
    ("append_blocks", CREATE),
    ("create_space", CREATE),
    ("move_page", WRITE),
    ("duplicate_page", CREATE),
    ("trash_page", WRITE),
    ("rename_page", WRITE),
    ("restore_page", WRITE),
    ("get_page", READ),
    ("get_page_markdown", READ),
    ("update_row_cells", WRITE),
    ("delete_row", DESTRUCTIVE),
    ("add_block", CREATE),
    ("add_blocks", WRITE),
    ("edit_block_text", WRITE),
    ("replace_text", WRITE),
    ("delete_block", DESTRUCTIVE),
)


def register_legacy(server, namespace, *, read_only: bool):
    """Register existing async handlers without wrapping or duplicating logic."""
    for name, annotations in _LEGACY_TOOLS:
        if not read_only or annotations["readOnlyHint"]:
            server.tool(annotations=annotations)(namespace[name])
