from src.processor import file_path_is_config, file_path_is_test


def test_file_path_is_test_rules() -> None:
    assert file_path_is_test("tests/test_orders.yaml")
    assert file_path_is_test("tests/helpers.yaml")
    assert file_path_is_test("test_orders.yaml")
    assert file_path_is_test("pkg/orders_test.yml")
    assert not file_path_is_test("models/orders.sql")
    assert not file_path_is_test("sqlmesh/core/test/definition.py")
    assert not file_path_is_test("config.yaml")


def test_file_path_is_config_rules() -> None:
    assert file_path_is_config("config.yaml")
    assert file_path_is_config("config.yml")
    assert file_path_is_config("config.py")
    assert file_path_is_config("nested/config.yaml")
    assert not file_path_is_config("external_models.yaml")
    assert not file_path_is_config("models/orders.sql")
    assert not file_path_is_config("Config.yaml")
