"""Bounded, typed inputs for the compact AppFlowy tool profile."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]
Markdown = Annotated[str, Field(max_length=100_000)]


def _only_fields(model: BaseModel, operation: str, allowed: str) -> None:
    """Reject meaningful inputs an operation would ignore, keeping compact schemas.

    Clients may materialize optional defaults, so explicitly supplied defaults are
    harmless. A non-default value must be consumed by the selected operation.
    """
    fields = type(model).model_fields
    ignored = sorted(
        name
        for name in model.model_fields_set - set(allowed.split())
        if getattr(model, name) != fields[name].get_default(call_default_factory=True)
    )
    if ignored:
        raise ValueError(f"{operation} does not accept: {', '.join(ignored)}")


def _command_fields(model: BaseModel, commands: dict[str, str]) -> None:
    _only_fields(
        model, model.command, "workspace_id command " + commands[model.command]
    )


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
    offset: int = Field(default=0, ge=0)
    id: str = "self"
    kind: Literal[
        "auto",
        "self",
        "workspaces",
        "workspace_folder",
        "database_fields",
        "page",
        "comments",
    ] = "auto"
    database_id: str = ""
    depth: int = Field(default=1, ge=0, le=5)
    target_type: Literal["document", "published", "row"] = "document"

    @model_validator(mode="after")
    def applicable_fields(self):
        kind = self.kind
        if kind == "auto":
            kind = (
                "self"
                if self.id == "self"
                else "database_fields"
                if self.database_id
                else "page"
            )
        _only_fields(
            self,
            kind,
            "kind "
            + {
                "comments": "workspace_id id target_type limit offset response_format",
                "self": "limit offset",
                "workspaces": "limit offset",
                "workspace_folder": "workspace_id id depth",
                "database_fields": "workspace_id id database_id limit offset",
                "page": "workspace_id id response_format"
                + (" offset" if self.response_format == "markdown" else ""),
            }[kind],
        )
        if kind == "comments" and self.id == "self":
            raise ValueError("id must identify a document, published page or row")
        if (
            kind == "database_fields"
            and self.database_id
            and self.id not in {"self", self.database_id}
        ):
            raise ValueError(
                "id and database_id identify different databases; provide one ID"
            )
        return self


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

    @model_validator(mode="after")
    def applicable_fields(self):
        _only_fields(
            self,
            self.kind,
            "kind name "
            + {
                "document": "parent_view_id markdown",
                "space": "permission",
                "database": "parent_view_id layout",
                "database_view": "parent_view_id layout",
            }[self.kind],
        )
        return self


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
        "append_comment",
    ]
    id: Identifier
    name: str = Field(default="", max_length=200)
    parent_view_id: str = ""
    markdown: Markdown = ""
    permission: SpacePermission | None = None
    expected_markdown: Markdown | None = None

    target_type: Literal["document", "published", "row"] = "document"
    content: Markdown = ""
    reply_comment_id: str = Field(
        default="", max_length=128, pattern=r"^[A-Za-z0-9_-]*$"
    )
    block_id: str = Field(default="", max_length=128, pattern=r"^[A-Za-z0-9_-]*$")
    database_view_id: str = Field(
        default="", max_length=128, pattern=r"^[A-Za-z0-9_-]*$"
    )

    @model_validator(mode="after")
    def applicable_fields(self):
        _command_fields(
            self,
            {
                "append_comment": "id target_type content reply_comment_id block_id database_view_id",
                "rename": "id name",
                "move": "id parent_view_id",
                "duplicate": "id name",
                "trash": "id",
                "restore": "id",
                "append": "id markdown",
                "prepend": "id markdown expected_markdown",
                "replace": "id markdown expected_markdown",
                "space_permissions": "id permission",
            },
        )
        return self


class DeleteInput(Input):
    kind: Literal["page", "row", "block", "field"]
    id: Identifier
    database_id: str = ""
    page_id: str = ""

    @model_validator(mode="after")
    def applicable_fields(self):
        _only_fields(
            self,
            self.kind,
            "workspace_id kind id "
            + {
                "page": "",
                "row": "database_id",
                "field": "database_id",
                "block": "page_id",
            }[self.kind],
        )
        return self


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

    @model_validator(mode="after")
    def applicable_fields(self):
        _command_fields(
            self,
            {
                "list": "limit offset response_format",
                "fields": "database_id limit offset response_format",
                "add_field": "database_id name field_type settings",
                "update_field": "database_id field_id name settings",
                "delete_field": "database_id field_id",
                "add_option": "database_id field_id name",
                "delete_option": "database_id field_id option_id",
                "group_by": "database_id field_id view_id",
                "formula": "database_id field_id expression",
                "timeline": "database_id view_id settings",
                "view_settings": "database_id view_id",
                "space_permissions": "view_id",
            },
        )
        return self


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

    @model_validator(mode="after")
    def applicable_fields(self):
        _row_fields(self)
        for row in self.rows:
            _only_fields(
                row,
                self.command,
                {
                    "create": "cells document",
                    "upsert": "cells document pre_hash",
                    "update_cells": "row_id cells",
                }.get(self.command, ""),
            )
        return self


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

    @model_validator(mode="after")
    def applicable_fields(self):
        _command_fields(
            self,
            {
                "add": "page_id parent_id "
                + ("block_type text data" if self.block_type else "markdown"),
                "edit": "page_id block_id text",
                "delete": "page_id block_id",
                "replace_text": "page_id find replace replace_all",
            },
        )
        return self


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
    offset: int = Field(default=0, ge=0, le=1_000_000)


class AIInput(ReadInput):
    command: Literal["create_chat", "ask", "messages", "delete_chat", "set_context"]
    chat_id: str = ""
    parent_view_id: str = ""
    name: str = Field(default="AI chat", max_length=200)
    question: str = Field(default="", max_length=20_000)
    page_ids: list[Identifier] = Field(default_factory=list, max_length=50)
    full_workspace: bool = False

    @model_validator(mode="after")
    def applicable_fields(self):
        _command_fields(
            self,
            {
                "create_chat": "parent_view_id name",
                "ask": "chat_id question page_ids full_workspace",
                "messages": "chat_id limit offset",
                "delete_chat": "chat_id",
                "set_context": "chat_id page_ids full_workspace",
            },
        )
        return self


class APIInput(Input):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    path: str = Field(min_length=1, max_length=500)
    params: dict[str, Any] = Field(default_factory=dict, max_length=20)
    body: dict[str, Any] | None = None


class ReadDatabaseInput(ReadInput):
    command: Literal["list", "fields", "view_settings", "space_permissions"]
    database_id: str = ""
    view_id: str = ""

    @model_validator(mode="after")
    def applicable_fields(self):
        _command_fields(
            self,
            {
                "list": "limit offset response_format",
                "fields": "database_id limit offset response_format",
                "view_settings": "database_id view_id",
                "space_permissions": "view_id",
            },
        )
        return self


class ReadRowsInput(ReadInput):
    command: Literal["list", "get", "changed_since"]
    database_id: Identifier
    row_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    with_doc: bool = False
    after: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def applicable_fields(self):
        _row_fields(self)
        return self


def _row_fields(model: BaseModel) -> None:
    _command_fields(
        model,
        {
            "list": "database_id limit offset response_format with_doc",
            "get": "database_id row_ids limit offset response_format with_doc",
            "changed_since": "database_id after limit offset response_format",
            "create": "database_id rows",
            "upsert": "database_id rows",
            "update_cells": "database_id rows",
            "delete": "database_id row_ids",
        },
    )


ImportInput.model_rebuild()
