import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--db-url",
        action="store",
        help="PostgreSQL server URL without a database name",
    )


@pytest.fixture(scope="session")
def server_db_url(pytestconfig: pytest.Config) -> str:
    value = pytestconfig.getoption("db_url")
    if not isinstance(value, str) or value == "":
        raise pytest.UsageError("--db-url is required")
    return value
