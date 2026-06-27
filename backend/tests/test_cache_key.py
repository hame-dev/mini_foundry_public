from app.cache.sql_cache import cache_key_for_sql


def test_same_inputs_same_key():
    a = cache_key_for_sql("u1", "SELECT 1", 5)
    b = cache_key_for_sql("u1", "SELECT 1", 5)
    assert a == b


def test_different_users_different_key():
    assert cache_key_for_sql("u1", "SELECT 1", 5) != cache_key_for_sql("u2", "SELECT 1", 5)


def test_bumping_permission_version_changes_key():
    assert cache_key_for_sql("u1", "SELECT 1", 5) != cache_key_for_sql("u1", "SELECT 1", 6)


def test_different_sql_different_key():
    assert cache_key_for_sql("u1", "SELECT 1", 5) != cache_key_for_sql("u1", "SELECT 2", 5)
