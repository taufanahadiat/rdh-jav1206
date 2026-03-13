<?php

if (!function_exists('db_config')) {
  function db_config(): array
  {
    static $config = null;

    if ($config !== null) {
      return $config;
    }

    $dbHost = getenv('PGHOST');
    if ($dbHost === false || $dbHost === '') {
      $dbHost = '127.0.0.1';
    }

    $config = [
      'host' => $dbHost,
      'port' => getenv('PGPORT') ?: '5432',
      'name' => getenv('PGDATABASE') ?: 'jav1206',
      'user' => getenv('PGUSER') ?: 'jav1206',
      'pass' => getenv('PGPASSWORD') ?: 'akpidev3',
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
