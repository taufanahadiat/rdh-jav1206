import os
from pathlib import Path
from typing import Any, Optional


CONFIG_DIR = Path(__file__).resolve().parent
HTML_DIR = CONFIG_DIR.parent
PROJECT_ROOT = HTML_DIR.parent
MISSING = object()


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _resolve_dotenv_path() -> Optional[Path]:
    override = os.getenv("APP_ENV_FILE", "").strip() or os.getenv("PYTHON_CONFIG_DOTENV", "").strip()
    if override:
        return Path(override).expanduser()

    candidates = [
        CONFIG_DIR / ".env",
        HTML_DIR / ".env",
        PROJECT_ROOT / ".env",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _load_dotenv() -> Optional[Path]:
    dotenv_path = _resolve_dotenv_path()
    if dotenv_path is None or not dotenv_path.is_file():
        return None

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue

        os.environ.setdefault(key, _strip_quotes(value.strip()))

    return dotenv_path


def _coerce_env_value(raw_value: str, cast: Any, names: tuple[str, ...]) -> Any:
    try:
        if cast is bool:
            return raw_value.strip().lower() in {"1", "true", "yes", "on"}
        if cast is int:
            return int(raw_value.strip())
        if cast is float:
            return float(raw_value.strip())
        if cast is Path:
            return Path(raw_value.strip()).expanduser()
        if cast == "csv":
            return [item.strip() for item in raw_value.split(",") if item.strip()]
        return str(raw_value)
    except ValueError as exc:
        joined_names = ", ".join(names)
        cast_name = getattr(cast, "__name__", str(cast))
        raise RuntimeError(f"Invalid {cast_name} config value for: {joined_names}") from exc


def _get_env(*names: str, cast: Any = str, default: Any = MISSING) -> Any:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return _coerce_env_value(value, cast, names)

    if default is not MISSING:
        if cast == "csv" and isinstance(default, list):
            return default
        if cast is Path and isinstance(default, Path):
            return default.expanduser()
        if cast is bool and isinstance(default, bool):
            return default
        if cast in {int, float} and isinstance(default, cast):
            return default
        return _coerce_env_value(str(default), cast, names)

    joined_names = ", ".join(names)
    raise RuntimeError(f"Missing required config value. Set one of: {joined_names}")


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


DOTENV_PATH = _load_dotenv()


# APP
APP_NAME = _get_env("APP_NAME", default="PLC Historian")
APP_ENV = _get_env("APP_ENV", default="production").lower()
APP_DEBUG = _get_env("APP_DEBUG", cast=bool, default=False)
APP_TIMEZONE = _get_env("APP_TIMEZONE", default="UTC")
APP_DIR = HTML_DIR
PYTHON_DIR = HTML_DIR / "python"


# PLC
PLC_IP = _get_env("PLC_IP")
PLC_RACK = _get_env("PLC_RACK", cast=int)
PLC_SLOT = _get_env("PLC_SLOT", cast=int)
PLC_POLL_INTERVAL_MS = _get_env("PLC_POLL_INTERVAL_MS", cast=int)
PLC_CONNECT_TIMEOUT_MS = _get_env("PLC_CONNECT_TIMEOUT_MS", cast=int)
PLC_READ_TIMEOUT_MS = _get_env("PLC_READ_TIMEOUT_MS", cast=int)
PLC_RETRY_COUNT = _get_env("PLC_RETRY_COUNT", cast=int)
PLC_RETRY_DELAY_MS = _get_env("PLC_RETRY_DELAY_MS", cast=int)
PLC_AWL_DIR = _get_env("PLC_AWL_DIR", cast=Path)
PLC_DB_SCRIPT_DIR = _get_env("PLC_DB_SCRIPT_DIR", cast=Path)
PLC_FLUCT_CATALOG_PATH = _get_env(
    "PLC_FLUCT_CATALOG_PATH",
    cast=Path,
    default=PLC_AWL_DIR / "config" / "hisotrian_tag.json",
)


# DB
DB_HOST = _get_env("DB_HOST", "POSTGRES_HOST", "PGHOST")
DB_PORT = _get_env("DB_PORT", "POSTGRES_PORT", "PGPORT", cast=int)
DB_NAME = _get_env("DB_NAME", "POSTGRES_DBNAME", "PGDATABASE")
DB_USER = _get_env("DB_USER", "POSTGRES_USER", "PGUSER")
DB_PASSWORD = _get_env("DB_PASSWORD", "POSTGRES_PASSWORD", "PGPASSWORD")
DB_CONNECT_TIMEOUT = _get_env("DB_CONNECT_TIMEOUT", "POSTGRES_CONNECT_TIMEOUT", "PGCONNECT_TIMEOUT", cast=int)
DB_SSLMODE = _get_env("DB_SSLMODE", "PGSSLMODE", default="")
DB_SCHEMA = _get_env("DB_SCHEMA")
DB_APP_NAME = _get_env("DB_APP_NAME", "PGAPPNAME")

POSTGRES_HOST = DB_HOST
POSTGRES_PORT = DB_PORT
POSTGRES_DBNAME = DB_NAME
POSTGRES_USER = DB_USER
POSTGRES_PASSWORD = DB_PASSWORD


# API
API_BASE_URL = _get_env("API_BASE_URL", "PLC_API_URL")
API_ALLOW_ORIGINS = _get_env("API_ALLOW_ORIGINS", "PLC_API_ALLOW_ORIGINS")
API_TIMEOUT_SECONDS = _get_env("API_TIMEOUT_SECONDS", "PLC_API_TIMEOUT_SECONDS", cast=float)
API_SNAPSHOT_PATH = _get_env("API_SNAPSHOT_PATH")
API_SNAPSHOT_URL = _get_env(
    "API_SNAPSHOT_URL",
    "PLC_API_SNAPSHOT_URL",
    default=_join_url(API_BASE_URL, API_SNAPSHOT_PATH),
)

PLC_API_ALLOW_ORIGINS = API_ALLOW_ORIGINS
PLC_API_TIMEOUT_SECONDS = API_TIMEOUT_SECONDS
PLC_API_SNAPSHOT_URL = API_SNAPSHOT_URL


# HISTORIAN
HISTORIAN_INTERVAL_MS = _get_env("HISTORIAN_INTERVAL_MS", cast=int)
HISTORIAN_EVENT_HOLDOFF_MS = _get_env("HISTORIAN_EVENT_HOLDOFF_MS", cast=int)
HISTORIAN_DOWNTIME_ROLLNAME = _get_env("HISTORIAN_DOWNTIME_ROLLNAME")
HISTORIAN_DB_WINDER_NUM = _get_env("HISTORIAN_DB_WINDER_NUM", cast=int)
HISTORIAN_DB_WINDER_STATUS_BYTE = _get_env("HISTORIAN_DB_WINDER_STATUS_BYTE", cast=int)
HISTORIAN_DB_WINDER_START_BIT = _get_env("HISTORIAN_DB_WINDER_START_BIT", cast=int)
HISTORIAN_DB_WINDER_AUX_BIT = _get_env("HISTORIAN_DB_WINDER_AUX_BIT", cast=int)
HISTORIAN_MARKER_STATUS_BYTE = _get_env("HISTORIAN_MARKER_STATUS_BYTE", cast=int)
HISTORIAN_MARKER_FIRST_CYCLE_BIT = _get_env("HISTORIAN_MARKER_FIRST_CYCLE_BIT", cast=int)
HISTORIAN_DB330_NUM = HISTORIAN_DB_WINDER_NUM
HISTORIAN_DB330_STATUS_BYTE = HISTORIAN_DB_WINDER_STATUS_BYTE
HISTORIAN_DB330_START_BIT = HISTORIAN_DB_WINDER_START_BIT
HISTORIAN_DB330_AUX_BIT = HISTORIAN_DB_WINDER_AUX_BIT


# LOGGING
LOG_LEVEL = _get_env("LOG_LEVEL", default="INFO").upper()
LOG_JSON = _get_env("LOG_JSON", cast=bool, default=True)
LOG_FILE_PATH_RAW = _get_env("LOG_FILE_PATH", default="")
LOG_FILE_PATH = Path(LOG_FILE_PATH_RAW).expanduser() if LOG_FILE_PATH_RAW else None
LOG_ROTATE_DAYS = _get_env("LOG_ROTATE_DAYS", cast=int, default=7)
SYSTEMLOG_ENABLED = _get_env("SYSTEMLOG_ENABLED", cast=bool, default=True)
SYSTEMLOG_DB_NAME = _get_env("SYSTEMLOG_DB_NAME", default=DB_NAME)
SYSTEMLOG_TABLE = _get_env("SYSTEMLOG_TABLE", default="systemlog")


def get_postgres_config() -> dict[str, Any]:
    config: dict[str, Any] = {
        "host": DB_HOST,
        "port": DB_PORT,
        "dbname": DB_NAME,
        "user": DB_USER,
        "password": DB_PASSWORD,
    }
    if DB_CONNECT_TIMEOUT > 0:
        config["connect_timeout"] = DB_CONNECT_TIMEOUT
    if DB_SSLMODE:
        config["sslmode"] = DB_SSLMODE
    if DB_APP_NAME:
        config["application_name"] = DB_APP_NAME
    if DB_SCHEMA:
        config["options"] = f"-c search_path={DB_SCHEMA}"
    return config
