"""Пути БД каталога: AppData + seed (план §2.3)."""

from core.catalog.db import (
    get_bundled_db_path,
    get_user_db_path,
    get_default_db_path,
    get_app_root,
)


def test_default_is_user_not_install_dir():
    user = get_user_db_path()
    bundled = get_bundled_db_path()
    assert get_default_db_path() == user
    assert user != bundled
    assert "catalog" in str(user)
    assert get_app_root() in bundled.parents or bundled.parent.parent == get_app_root()


def test_user_path_under_home_or_appdata():
    p = str(get_user_db_path())
    assert "NestCraft" in p
