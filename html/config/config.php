<?php

if (!function_exists('load_shared_env_config')) {
  function load_shared_env_config(): void
  {
    static $loaded = false;

    if ($loaded) {
      return;
    }

    $loaded = true;
    $envPath = __DIR__ . '/.env';
    if (!is_file($envPath) || !is_readable($envPath)) {
      return;
    }

    $lines = file($envPath, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    if ($lines === false) {
      return;
    }

    foreach ($lines as $rawLine) {
      $line = trim($rawLine);
      if ($line === '' || str_starts_with($line, '#')) {
        continue;
      }

      if (str_starts_with($line, 'export ')) {
        $line = trim(substr($line, 7));
      }

      $pos = strpos($line, '=');
      if ($pos === false) {
        continue;
      }

      $key = trim(substr($line, 0, $pos));
      if ($key === '' || getenv($key) !== false) {
        continue;
      }

      $value = trim(substr($line, $pos + 1));
      $len = strlen($value);
      if ($len >= 2) {
        $first = $value[0];
        $last = $value[$len - 1];
        if (($first === '"' && $last === '"') || ($first === "'" && $last === "'")) {
          $value = substr($value, 1, -1);
        }
      }

      putenv($key . '=' . $value);
      $_ENV[$key] = $value;
      $_SERVER[$key] = $value;
    }
  }
}

if (!function_exists('config_env')) {
  function config_env(array $keys, ?string $default = null): ?string
  {
    load_shared_env_config();

    foreach ($keys as $key) {
      $value = getenv($key);
      if ($value !== false && $value !== '') {
        return $value;
      }
    }

    return $default;
  }
}

if (!function_exists('config_env_bool')) {
  function config_env_bool(array $keys, bool $default = false): bool
  {
    $value = config_env($keys);
    if ($value === null) {
      return $default;
    }

    return in_array(strtolower(trim($value)), ['1', 'true', 'yes', 'on'], true);
  }
}

if (!function_exists('config_env_int')) {
  function config_env_int(array $keys, int $default = 0): int
  {
    $value = config_env($keys);
    if ($value === null || !is_numeric($value)) {
      return $default;
    }

    return (int) $value;
  }
}

if (!function_exists('app_config')) {
  function app_config(): array
  {
    static $config = null;

    if ($config !== null) {
      return $config;
    }

    $config = [
      'name' => config_env(['APP_NAME'], 'PLC Historian'),
      'env' => strtolower((string) config_env(['APP_ENV'], 'production')),
      'debug' => config_env_bool(['APP_DEBUG'], false),
      'timezone' => config_env(['APP_TIMEZONE'], 'UTC'),
    ];

    return $config;
  }
}

if (!function_exists('app_name')) {
  function app_name(): string
  {
    return (string) app_config()['name'];
  }
}

if (!function_exists('app_env')) {
  function app_env(): string
  {
    return (string) app_config()['env'];
  }
}

if (!function_exists('app_debug')) {
  function app_debug(): bool
  {
    return (bool) app_config()['debug'];
  }
}

if (!function_exists('plc_api_base_url')) {
  function plc_api_base_url(): string
  {
    return rtrim((string) config_env(['API_BASE_URL', 'PLC_API_URL'], 'http://127.0.0.1:8000'), '/');
  }
}

if (!function_exists('plc_api_timeout_seconds')) {
  function plc_api_timeout_seconds(): int
  {
    return max(1, config_env_int(['API_TIMEOUT_SECONDS', 'PLC_API_TIMEOUT_SECONDS'], 5));
  }
}

if (!function_exists('plc_api_snapshot_path')) {
  function plc_api_snapshot_path(): string
  {
    return '/' . ltrim((string) config_env(['API_SNAPSHOT_PATH'], '/plc/dashboard-snapshot'), '/');
  }
}

if (!function_exists('plc_api_snapshot_url')) {
  function plc_api_snapshot_url(): string
  {
    return plc_api_base_url() . plc_api_snapshot_path();
  }
}

if (!function_exists('web_dashboard_snapshot_endpoint')) {
  function web_dashboard_snapshot_endpoint(): string
  {
    return (string) config_env(['WEB_DASHBOARD_SNAPSHOT_ENDPOINT', 'DASHBOARD_SNAPSHOT_ENDPOINT'], '/plc/dashboard-snapshot/');
  }
}

if (!function_exists('web_app_title')) {
  function web_app_title(): string
  {
    return (string) config_env(['WEB_APP_TITLE'], 'Dashboard Inbox');
  }
}

if (!function_exists('web_line_name')) {
  function web_line_name(): string
  {
    return (string) config_env(['WEB_LINE_NAME'], 'LINE-5');
  }
}

if (!function_exists('web_brand_label')) {
  function web_brand_label(): string
  {
    return (string) config_env(['WEB_BRAND_LABEL'], 'JAV1206');
  }
}

if (!function_exists('web_login_heading')) {
  function web_login_heading(): string
  {
    return web_app_title();
  }
}

if (!function_exists('web_login_subtitle')) {
  function web_login_subtitle(): string
  {
    return web_line_name() . ' [' . web_brand_label() . ']';
  }
}

if (!function_exists('web_page_title')) {
  function web_page_title(?string $section = null): string
  {
    $base = web_line_name();
    $prefix = trim((string) ($section ?? ''));
    if ($prefix === '') {
      return $base;
    }

    return $prefix . ' | ' . $base;
  }
}

if (!function_exists('web_sidebar_title')) {
  function web_sidebar_title(): string
  {
    return web_app_title() . ' | ' . web_line_name();
  }
}

if (!function_exists('web_dashboard_request_timeout_ms')) {
  function web_dashboard_request_timeout_ms(): int
  {
    return max(1000, config_env_int(['WEB_DASHBOARD_REQUEST_TIMEOUT_MS'], 6000));
  }
}

if (!function_exists('web_dashboard_poll_interval_ms')) {
  function web_dashboard_poll_interval_ms(): int
  {
    return max(250, config_env_int(['WEB_DASHBOARD_POLL_INTERVAL_MS'], 1000));
  }
}

if (!function_exists('web_dashboard_hidden_poll_interval_ms')) {
  function web_dashboard_hidden_poll_interval_ms(): int
  {
    return max(250, config_env_int(['WEB_DASHBOARD_HIDDEN_POLL_INTERVAL_MS'], 3000));
  }
}

if (!function_exists('web_history_refresh_ms')) {
  function web_history_refresh_ms(): int
  {
    return max(1000, config_env_int(['WEB_HISTORY_REFRESH_MS'], 30000));
  }
}

if (!function_exists('web_history_request_timeout_ms')) {
  function web_history_request_timeout_ms(): int
  {
    return max(1000, config_env_int(['WEB_HISTORY_REQUEST_TIMEOUT_MS'], 8000));
  }
}

if (!function_exists('web_config')) {
  function web_config(): array
  {
    static $config = null;

    if ($config !== null) {
      return $config;
    }

    $config = [
      'dashboard_snapshot_endpoint' => web_dashboard_snapshot_endpoint(),
      'app_env' => app_env(),
      'app_debug' => app_debug(),
      'app_name' => app_name(),
      'app_title' => web_app_title(),
      'line_name' => web_line_name(),
      'brand_label' => web_brand_label(),
      'login_heading' => web_login_heading(),
      'login_subtitle' => web_login_subtitle(),
      'sidebar_title' => web_sidebar_title(),
      'dashboard_request_timeout_ms' => web_dashboard_request_timeout_ms(),
      'dashboard_poll_interval_ms' => web_dashboard_poll_interval_ms(),
      'dashboard_hidden_poll_interval_ms' => web_dashboard_hidden_poll_interval_ms(),
      'history_refresh_ms' => web_history_refresh_ms(),
      'history_request_timeout_ms' => web_history_request_timeout_ms(),
    ];

    return $config;
  }
}

if (!function_exists('db_config')) {
  function db_config(): array
  {
    static $config = null;

    if ($config !== null) {
      return $config;
    }

    $config = [
      'host' => config_env(['DB_HOST', 'POSTGRES_HOST', 'PGHOST']),
      'port' => config_env(['DB_PORT', 'POSTGRES_PORT', 'PGPORT']),
      'name' => config_env(['DB_NAME', 'POSTGRES_DBNAME', 'PGDATABASE']),
      'user' => config_env(['DB_USER', 'POSTGRES_USER', 'PGUSER']),
      'pass' => config_env(['DB_PASSWORD', 'POSTGRES_PASSWORD', 'PGPASSWORD']),
    ];

    return $config;
  }
}

if (!function_exists('db_connect')) {
  function db_connect(): PDO
  {
    $config = db_config();
    $dsn =
      'pgsql:host=' .
      $config['host'] .
      ';port=' .
      $config['port'] .
      ';dbname=' .
      $config['name'] .
      ";options='--client_encoding=UTF8'";

    return new PDO($dsn, $config['user'], $config['pass'], [
      PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
      PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
  }
}
