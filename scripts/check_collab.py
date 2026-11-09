"""Verify decode and incremental structural mutations on disposable database snapshots."""

import json
from importlib.metadata import version
from pathlib import Path

from pycrdt import Doc, Map


def verify(path: Path) -> dict:
    before = path.read_bytes()
    doc = Doc()
    doc.apply_update(before)
    database = doc.get("data", type=Map)["database"]
    field_id = next(iter(database["fields"].keys()))
    state = doc.get_state()
    with doc.transaction():
        database["fields"][field_id]["name"] = "Compatibility rename"
        for view_id in list(database["views"].keys()):
            view = database["views"][view_id]
            if "row_orders" in view and len(view["row_orders"]):
                del view["row_orders"][0]
    replica = Doc()
    replica.apply_update(before)
    replica.apply_update(doc.get_update(state))
    assert (
        replica.get("data", type=Map)["database"]["fields"][field_id]["name"]
        == "Compatibility rename"
    )
    assert replica.get("data", type=Map).to_py() == doc.get("data", type=Map).to_py()
    return {
        "fixture": path.name,
        "bytes": len(before),
        "decode": True,
        "structural_diff_roundtrip": True,
    }


def main():
    fixtures = sorted(
        (Path(__file__).resolve().parent.parent / "tests/fixtures").glob(
            "database-*.bin"
        )
    )
    if not fixtures:
        raise SystemExit("No disposable database fixtures found")
    results = []
    for path in fixtures:
        try:
            results.append(verify(path))
        except (ValueError, RuntimeError, AssertionError, KeyError, TypeError) as exc:
            results.append(
                {
                    "fixture": path.name,
                    "decode": False,
                    "error_type": type(exc).__name__,
                }
            )
    print(json.dumps({"pycrdt": version("pycrdt"), "results": results}, indent=2))
    raise SystemExit(0 if all(item["decode"] for item in results) else 1)


if __name__ == "__main__":
    main()
