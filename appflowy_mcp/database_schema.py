"""Read-only dependency checks before an incremental database schema mutation."""

import json
import re

# Mirrors AppFlowy-Web's formula/prop-calls.ts: strings/comments hide calls,
# references are quoted literals, and current.prop() targets a related row.
_FORMULA_TOKEN = re.compile(
    r"(?P<comment>/\*.*?(?:\*/|\Z))"
    r"""|(?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')"""
    r"""|(?P<unfinished>["'].*)"""
    r"|(?P<ident>[A-Za-z_][A-Za-z_0-9]*)|(?P<punct>[^\s])",
    re.DOTALL,
)


def formula_references(expression: str) -> set[str]:
    tokens = []
    escapes = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "'": "'"}
    for match in _FORMULA_TOKEN.finditer(expression):
        kind, value = match.lastgroup, match.group()
        if kind == "unfinished" or (kind == "comment" and not value.endswith("*/")):
            break
        if kind == "comment":
            continue
        if kind == "string":
            value = re.sub(
                r"\\(.)",
                lambda m: escapes.get(m[1], m[0]),
                value[1:-1],
                flags=re.DOTALL,
            )
        tokens.append((kind, value))
    return {
        tokens[index + 2][1]
        for index in range(len(tokens) - 3)
        if tokens[index] == ("ident", "prop")
        and tokens[index + 1] == ("punct", "(")
        and tokens[index + 2][0] == "string"
        and tokens[index + 3] == ("punct", ")")
        and (index == 0 or tokens[index - 1] != ("punct", "."))
    }


def _reference_paths(value, field_id: str, path: str):
    if isinstance(value, str):
        # Some type options/layout settings are persisted as JSON strings.
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return
    if isinstance(value, dict):
        for key, child in value.items():
            location = f"{path}.{key}"
            normalized = key.replace("_", "").lower()
            if (normalized.endswith("fieldid") and child == field_id) or (
                normalized.endswith("fieldids")
                and isinstance(child, list)
                and field_id in child
            ):
                yield location
            yield from _reference_paths(child, field_id, location)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _reference_paths(child, field_id, f"{path}[{index}]")


def field_dependencies(database: dict, field_id: str) -> list[str]:
    """Find local schema/view references without mutating filters or formulas.

    Field order and direct per-field settings are removed by the caller. This
    checks the fetched database, not reverse references in other databases.
    """
    dependencies = []
    fields = database["fields"]
    name = fields[field_id].get("name", "")
    for other_id, field in fields.items():
        if other_id == field_id:
            continue
        options = field.get("type_option", {})
        dependencies.extend(
            _reference_paths(options, field_id, f"field:{other_id}.type_option")
        )
        if int(field.get("ty", 0)) == 19:
            expression = options.get("19", {}).get("expression", "")
            if isinstance(expression, str):
                refs = formula_references(expression)
                if field_id in refs or (name in refs and name not in fields):
                    dependencies.append(f"field:{other_id}.formula")
    for view_id, view in database.get("views", {}).items():
        settings = {
            key: value
            for key, value in view.items()
            if key
            not in {
                "field_orders",
                "field_settings",
                "form_field_settings",
                "row_orders",
            }
        }
        dependencies.extend(_reference_paths(settings, field_id, f"view:{view_id}"))
    return sorted(set(dependencies))
