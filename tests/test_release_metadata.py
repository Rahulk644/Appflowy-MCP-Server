"""Release validation must reject mismatched tags and generated image metadata."""

from copy import deepcopy
from pathlib import Path

import pytest

from appflowy_mcp import __version__
from scripts.release_metadata import IMAGE, check_registry, package_version


@pytest.mark.parametrize(
    "change,tag",
    [
        ({"version": "0.0.0"}, None),
        ({"packages": [{"registryType": "oci", "identifier": IMAGE + ":0.0.0"}]}, None),
        (
            {
                "packages": [
                    {
                        "registryType": "oci",
                        "identifier": "ghcr.io/other/repo:" + __version__,
                    }
                ]
            },
            None,
        ),
        ({}, "v0.0.0"),
    ],
)
def test_release_metadata_rejects_mismatch(change, tag):
    registry = {
        "version": __version__,
        "packages": [{"registryType": "oci", "identifier": IMAGE + ":" + __version__}],
    }
    registry.update(deepcopy(change))
    with pytest.raises(ValueError):
        check_registry(registry, __version__, tag)


def test_source_version_and_prerelease_tag(tmp_path):
    assert package_version(Path(__file__).resolve().parent.parent) == __version__
    package = tmp_path / "appflowy_mcp"
    package.mkdir()
    (package / "__init__.py").write_text('__version__ = "2.1.0rc1"\n')
    value = package_version(tmp_path)
    check_registry(
        {
            "version": value,
            "packages": [{"registryType": "oci", "identifier": IMAGE + ":" + value}],
        },
        value,
        "v" + value,
    )
