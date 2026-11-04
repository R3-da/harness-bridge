import pytest

from hbridge import HBridgeError
from hbridge.catalog import Catalog, deep_merge


def test_deep_merge_overrides_leaves_only():
    merged = deep_merge({"a": {"b": 1, "c": 2}, "d": [1]}, {"a": {"b": 9}, "d": [2]})
    assert merged == {"a": {"b": 9, "c": 2}, "d": [2]}


def test_user_catalog_merges_on_defaults(home):
    (home / "catalog.toml").write_text('[tools.codex.providers.go]\nmodel = "glm-5.3"\n')
    catalog = Catalog.load()
    go = catalog.tool_providers("codex")["go"]
    assert go["model"] == "glm-5.3"
    assert go["model_provider"] == "opencode_go"  # untouched default
    assert len(catalog.sources) == 2


def test_aliases_and_subscription(catalog):
    assert catalog.resolve_provider("claude", "sub") == "anthropic"
    assert catalog.resolve_provider("codex", "subscription") == "openai"
    assert catalog.resolve_provider("kilo", "or") == "openrouter"
    assert catalog.resolve_provider("pi", "opencode-go") == "go"
    with pytest.raises(HBridgeError, match="unknown provider"):
        catalog.resolve_provider("codex", "anthropic")


def test_invalid_user_catalog(home):
    (home / "catalog.toml").write_text("not = [valid")
    with pytest.raises(HBridgeError, match="invalid TOML"):
        Catalog.load()


def test_includes_merge_before_own_keys(home):
    (home / "models.toml").write_text(
        '[tools.codex.providers.go]\nmodel = "from-include"\n'
        '[tools.kilo.providers.go]\nmodel = "opencode-go/from-include"\n'
    )
    (home / "catalog.toml").write_text(
        'include = ["models.toml", "~/absent.toml"]\n'
        '[tools.kilo.providers.go]\nmodel = "opencode-go/own"\n'
    )
    catalog = Catalog.load()
    assert catalog.tool_providers("codex")["go"]["model"] == "from-include"
    assert catalog.tool_providers("kilo")["go"]["model"] == "opencode-go/own"
    assert catalog.missing == [str(home / "absent.toml")]
    assert catalog.sources[1:] == [str(home / "models.toml"), str(home / "catalog.toml")]


def test_include_cycle(home):
    (home / "catalog.toml").write_text('include = ["catalog.toml"]\n')
    with pytest.raises(HBridgeError, match="cycle"):
        Catalog.load()
