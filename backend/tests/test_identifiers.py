import pytest
from app.util.identifiers import UnsafeIdentifier, assert_safe_ident, is_safe_ident, quote_ident


@pytest.mark.parametrize("name", ["a", "_a", "ABC", "abc_123", "_x_"])
def test_safe_identifiers(name):
    assert is_safe_ident(name)
    quote_ident(name)


@pytest.mark.parametrize(
    "name",
    ["", "1abc", "a-b", "a b", "a;b", 'a"b', "a.b", None, 42],
)
def test_unsafe_identifiers(name):
    assert not is_safe_ident(name)
    with pytest.raises(UnsafeIdentifier):
        assert_safe_ident(name)


def test_quote_wraps_in_double_quotes():
    assert quote_ident("orders") == '"orders"'
