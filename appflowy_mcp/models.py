"""Bounded, typed inputs for the compact AppFlowy tool profile."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]
Markdown = Annotated[str, Field(max_length=100_000)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str = ""


class ReadInput(Input):
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)
    response_format: Literal["json", "markdown"] = "json"


class SearchInput(ReadInput):
    query: str = Field(min_length=1, max_length=500)


class FetchInput(ReadInput):
    id: str = "self"
    kind: Literal[
        "auto", "self", "workspaces", "workspace_folder", "database_fields", "page"
    ] = "auto"
    database_id: str = ""
    depth: int = Field(default=1, ge=0, le=5)


class SpaceSecurity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disable_guests: bool = False
    disable_public_links: bool = False
    disable_export: bool = False


class SpacePermission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visibility: Literal["public", "private", "custom"]
    owner_access_level: Literal[50] = 50
    member_default_access_level: Literal[10, 20, 30, 50] | None = 30
    everyone_else_access_level: Literal[10, 20, 30, 50] | None = None
    invite_policy: Literal["owners_only", "members_and_owners"] = "owners_only"
    sidebar_edit_policy: Literal["owners_only", "members_and_owners"] = "owners_only"
    invite_link_enabled: bool = False
    security: SpaceSecurity = Field(default_factory=SpaceSecurity)

    @model_validator(mode="after")
    def check_visibility(self):
        if self.visibility != "custom" and (
            self.member_default_access_level is None
            or self.everyone_else_access_level is not None
        ):
            raise ValueError(
                "Only custom spaces support no member access or everyone-else access"
            )
        return self


class PageSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_view_id: str = ""
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["document", "space", "database", "database_view"] = "document"
    layout: Literal[
        "grid",
        "board",
        "calendar",
        "list",
        "gallery",
        "chart",
        "feed",
        "form",
        "timeline",
    ] = "grid"
    markdown: Markdown = ""
    permission: SpacePermission | None = None


class CreateInput(Input):
    pages: list[PageSpec] = Field(min_length=1, max_length=20)


class UpdateInput(Input):
    command: Literal[
        "rename",
        "move",
        "duplicate",
        "trash",
        "restore",
        "append",
        "prepend",
        "replace",
        "space_permissions",
    ]
    id: Identifier
    name: str = Field(default="", max_length=200)
    parent_view_id: str = ""
    markdown: Markdown = ""
    permission: SpacePermission | None = None
    expected_markdown: Markdown | None = None


class DeleteInput(Input):
    kind: Literal["page", "row", "block", "field"]
    id: Identifier
    database_id: str = ""
    page_id: str = ""


class DatabaseInput(ReadInput):
    command: Literal[
        "list",
        "fields",
        "add_field",
        "update_field",
        "delete_field",
        "add_option",
        "delete_option",
        "group_by",
        "formula",
        "timeline",
        "view_settings",
        "space_permissions",
    ]
    database_id: str = ""
    field_id: str = ""
    view_id: str = ""
    name: str = Field(default="", max_length=200)
    field_type: int = Field(default=0, ge=0, le=19)
    option_id: str = ""
    expression: str = Field(default="", max_length=10_000)
    settings: dict[str, Any] = Field(default_factory=dict, max_length=20)


class RowSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_id: str = ""
    pre_hash: str = Field(default="", max_length=500)
    cells: dict[str, Any] = Field(default_factory=dict, max_length=100)
    document: Markdown = ""


class RowsInput(ReadInput):
    command: Literal[
        "list", "get", "create", "upsert", "update_cells", "delete", "changed_since"
    ]
    database_id: Identifier
    row_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    rows: list[RowSpec] = Field(default_factory=list, max_length=20)
    with_doc: bool = False
    after: str = Field(default="", max_length=200)


class BlocksInput(Input):
    command: Literal["add", "edit", "delete", "replace_text"]
    page_id: Identifier
    block_id: str = ""
    parent_id: str = ""
    markdown: Markdown = ""
    text: Markdown = ""
    find: str = Field(default="", max_length=10_000)
    replace: Markdown = ""
    replace_all: bool = False
    block_type: str = Field(default="", max_length=80, pattern=r"^[A-Za-z0-9_]*$")
    data: dict[str, Any] = Field(default_factory=dict, max_length=20)


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=500)
    markdown: Markdown = ""


class ImportInput(Input):
    parent_view_id: Identifier
    entries: list[Entry] = Field(default_factory=list, max_length=50)
    files: list["FileEntry"] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def has_payload(self):
        if not self.entries and not self.files:
            raise ValueError("Provide entries and/or files")
        return self


class FileEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(min_length=1, max_length=1_400_000)
    content_type: str = Field(
        default="application/octet-stream", pattern=r"^[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+$"
    )


class ExportInput(Input):
    view_id: Identifier
    depth: int = Field(default=0, ge=0, le=5)
    limit: int = Field(default=50, ge=1, le=100)


class AIInput(ReadInput):
    command: Literal["create_chat", "ask", "messages", "delete_chat", "set_context"]
    chat_id: str = ""
    parent_view_id: str = ""
    name: str = Field(default="AI chat", max_length=200)
    question: str = Field(default="", max_length=20_000)
    page_ids: list[Identifier] = Field(default_factory=list, max_length=50)
    full_workspace: bool = False


class APIInput(Input):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    path: str = Field(min_length=1, max_length=500)
    params: dict[str, Any] = Field(default_factory=dict, max_length=20)
    body: dict[str, Any] | None = None


class ReadDatabaseInput(ReadInput):
    command: Literal["list", "fields", "view_settings", "space_permissions"]
    database_id: str = ""
    view_id: str = ""


class ReadRowsInput(ReadInput):
    command: Literal["list", "get", "changed_since"]
    database_id: Identifier
    row_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    with_doc: bool = False
    after: str = Field(default="", max_length=200)


ImportInput.model_rebuild()
