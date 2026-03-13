<?php
if (session_status() !== PHP_SESSION_ACTIVE) {
  session_start();
}

header('Content-Type: application/json');

if (!isset($_SESSION['username'])) {
  http_response_code(401);
  echo json_encode(['ok' => false, 'message' => 'Unauthorized']);
  exit();
}

$userRole = strtolower(trim((string) ($_SESSION['role'] ?? '')));
if ($userRole !== 'admin') {
  http_response_code(403);
  echo json_encode(['ok' => false, 'message' => 'Access denied.']);
  exit();
}

require_once dirname(__DIR__, 2) . '/config/config.php';

const DB_AWL_IMPORT_SCRIPT = '/var/www/html/py/import_awl_to_dblist.py';
const DB_DBLIST_TABLE = 'public.dblist';
const DB_PREVIEW_SAMPLE_LIMIT = 8;
const DB_TABLE_ALIASES = [
  'public.dblist' => 'public.dbmaster',
];
const DB_DEFAULT_LIMITED_TABLES = [
  'public.rolldata',
  'public.rtag5sec',
  'public.rtagroll',
];
const DB_ALLOWED_LIMITS = [500, 1000, 5000, 10000];

function db_act_respond(array $payload, int $statusCode = 200): void
{
  http_response_code($statusCode);
  echo json_encode($payload);
  exit();
}

function db_act_quote_identifier(string $name): string
{
  return '"' . str_replace('"', '""', $name) . '"';
}

function db_act_run_command(array $command): array
{
  $escaped = array_map('escapeshellarg', $command);
  $cmd = implode(' ', $escaped) . ' 2>&1';
  $output = [];
  $exitCode = 0;
  exec($cmd, $output, $exitCode);

  return [
    'exit_code' => $exitCode,
    'output' => trim(implode("\n", $output)),
  ];
}

function db_act_dbmaster_map(PDO $pdo): array
{
  $stmt = $pdo->query('SELECT id, dbsym, dbname FROM public.dbmaster ORDER BY dbsym');
  $map = [];
  foreach ($stmt->fetchAll() as $row) {
    $map[(int) $row['dbsym']] = [
      'id' => (int) $row['id'],
      'dbsym' => (int) $row['dbsym'],
      'dbname' => (string) $row['dbname'],
    ];
  }

  return $map;
}

function db_act_table_options(PDO $pdo): array
{
  $stmt = $pdo->query(
    "SELECT table_schema, table_name
     FROM information_schema.tables
     WHERE table_type = 'BASE TABLE'
       AND table_schema NOT IN ('pg_catalog', 'information_schema')
     ORDER BY table_schema, table_name",
  );

  $tables = [];
  foreach ($stmt->fetchAll() as $row) {
    $schemaName = (string) $row['table_schema'];
    $tableName = (string) $row['table_name'];
    $tables[] = [
      'schema' => $schemaName,
      'table' => $tableName,
      'value' => $schemaName . '.' . $tableName,
      'label' => $schemaName . '.' . $tableName,
    ];
  }

  return $tables;
}

function db_act_resolve_table(array $tableOptions, string $selectedValue): ?array
{
  foreach ($tableOptions as $table) {
    if ($table['value'] === $selectedValue) {
      return $table;
    }
  }

  return null;
}

function db_act_normalize_requested_table(array $tableOptions, string $requestedTable): string
{
  if (db_act_resolve_table($tableOptions, $requestedTable) !== null) {
    return $requestedTable;
  }

  return DB_TABLE_ALIASES[$requestedTable] ?? $requestedTable;
}

function db_act_table_columns(PDO $pdo, string $schemaName, string $tableName): array
{
  $stmt = $pdo->prepare(
    "SELECT column_name
     FROM information_schema.columns
     WHERE table_schema = :schema
       AND table_name = :table
     ORDER BY ordinal_position",
  );
  $stmt->execute([
    ':schema' => $schemaName,
    ':table' => $tableName,
  ]);

  return array_map(static function ($row) {
    return (string) $row['column_name'];
  }, $stmt->fetchAll());
}

function db_act_normalize_value($value)
{
  if ($value === null) {
    return null;
  }

  if (is_bool($value)) {
    return $value ? 'true' : 'false';
  }

  if (is_scalar($value)) {
    return $value;
  }

  $encoded = json_encode($value);
  return $encoded === false ? (string) $value : $encoded;
}

function db_act_table_rows(
  PDO $pdo,
  string $schemaName,
  string $tableName,
  array $columns,
  ?int $limit = null,
  ?string $orderBy = null,
  string $orderDir = 'asc'
): array {
  if (empty($columns)) {
    return [];
  }

  $safeSchema = db_act_quote_identifier($schemaName);
  $safeTable = db_act_quote_identifier($tableName);
  $orderSql = '';
  if ($orderBy !== null && in_array($orderBy, $columns, true)) {
    $safeOrderColumn = db_act_quote_identifier($orderBy);
    $safeOrderDir = strtolower($orderDir) === 'desc' ? 'DESC' : 'ASC';
    $orderSql = " ORDER BY {$safeOrderColumn} {$safeOrderDir}";
  } elseif (in_array('id', $columns, true)) {
    $orderSql = ' ORDER BY "id"';
  }

  $limitSql = $limit !== null ? ' LIMIT ' . (int) $limit : '';
  $stmt = $pdo->query("SELECT * FROM {$safeSchema}.{$safeTable}{$orderSql}{$limitSql}");

  $rows = [];
  foreach ($stmt->fetchAll() as $row) {
    $item = [];
    foreach ($columns as $column) {
      $item[$column] = db_act_normalize_value($row[$column] ?? null);
    }
    $rows[] = $item;
  }

  return $rows;
}

function db_act_table_total_rows(PDO $pdo, string $schemaName, string $tableName): int
{
  $safeSchema = db_act_quote_identifier($schemaName);
  $safeTable = db_act_quote_identifier($tableName);
  $stmt = $pdo->query("SELECT COUNT(*) FROM {$safeSchema}.{$safeTable}");
  return (int) $stmt->fetchColumn();
}

function db_act_effective_row_limit(string $schemaName, string $tableName, string $requestedLimit): ?int
{
  if ($requestedLimit === 'all') {
    return null;
  }

  if ($requestedLimit !== '') {
    $parsedLimit = (int) $requestedLimit;
    if (in_array($parsedLimit, DB_ALLOWED_LIMITS, true)) {
      return $parsedLimit;
    }
  }

  $tableValue = $schemaName . '.' . $tableName;
  if (in_array($tableValue, DB_DEFAULT_LIMITED_TABLES, true)) {
    return 500;
  }

  return null;
}

function db_act_limit_value(?int $limit): string
{
  return $limit === null ? 'all' : (string) $limit;
}

function db_act_order_column(array $columns, string $requestedColumn): ?string
{
  if ($requestedColumn === '') {
    return null;
  }

  return in_array($requestedColumn, $columns, true) ? $requestedColumn : null;
}

function db_act_order_direction(string $requestedDirection): string
{
  return strtolower($requestedDirection) === 'desc' ? 'desc' : 'asc';
}

function db_act_import_dblist(PDO $pdo): array
{
  if (!is_file(DB_AWL_IMPORT_SCRIPT)) {
    throw new RuntimeException('The AWL import script was not found.');
  }

  $result = db_act_run_command(['python3', DB_AWL_IMPORT_SCRIPT, '--write-db']);
  if ($result['exit_code'] !== 0) {
    $message = $result['output'] !== '' ? $result['output'] : 'The AWL import command failed to run.';
    throw new RuntimeException($message);
  }

  $rowCountStmt = $pdo->query('SELECT COUNT(*) FROM public.dblist');
  $rowCount = (int) $rowCountStmt->fetchColumn();
  $dbCountStmt = $pdo->query('SELECT COUNT(DISTINCT dbmasterid) FROM public.dblist');
  $dbCount = (int) $dbCountStmt->fetchColumn();

  return [
    'command_output' => $result['output'],
    'row_count' => $rowCount,
    'db_count' => $dbCount,
  ];
}

function db_act_awl_rows(PDO $pdo): array
{
  if (!is_file(DB_AWL_IMPORT_SCRIPT)) {
    throw new RuntimeException('The AWL import script was not found.');
  }

  $result = db_act_run_command(['python3', DB_AWL_IMPORT_SCRIPT]);
  if ($result['exit_code'] !== 0) {
    $message = $result['output'] !== '' ? $result['output'] : 'The AWL preview command failed to run.';
    throw new RuntimeException($message);
  }

  $dbmasterMap = db_act_dbmaster_map($pdo);
  $handle = fopen('php://temp', 'r+');
  fwrite($handle, $result['output']);
  rewind($handle);

  $header = fgetcsv($handle);
  if (!is_array($header)) {
    fclose($handle);
    throw new RuntimeException('The AWL preview output is empty.');
  }

  $rows = [];
  while (($line = fgetcsv($handle)) !== false) {
    if (count($line) < 6) {
      continue;
    }

    $dbsym = (int) $line[0];
    if (!isset($dbmasterMap[$dbsym])) {
      continue;
    }

    $rows[] = [
      'dbmasterid' => $dbmasterMap[$dbsym]['id'],
      'dbsym' => $dbsym,
      'dbname' => $dbmasterMap[$dbsym]['dbname'],
      'address' => (string) $line[1],
      'name' => (string) $line[2],
      'type' => (string) $line[3],
      'initvalue' => (string) $line[4],
      'comment' => (string) $line[5],
    ];
  }

  fclose($handle);
  return $rows;
}

function db_act_preview_limit_examples(array &$items): array
{
  return array_slice($items, 0, DB_PREVIEW_SAMPLE_LIMIT);
}

function db_act_preview_reimport_dblist(PDO $pdo): array
{
  $incomingRows = db_act_awl_rows($pdo);
  $existingStmt = $pdo->query(
    "SELECT l.id, l.dbmasterid, m.dbsym, m.dbname, l.address, l.name, l.type, l.initvalue, l.comment
     FROM public.dblist l
     JOIN public.dbmaster m ON m.id = l.dbmasterid
     ORDER BY l.id"
  );
  $existingRows = $existingStmt->fetchAll();

  $incomingByAddress = [];
  $incomingByName = [];
  foreach ($incomingRows as $row) {
    $incomingByAddress[$row['address']] = $row;
    $incomingByName[$row['dbmasterid'] . '|' . $row['name']] = $row;
  }

  $existingByAddress = [];
  $existingByName = [];
  foreach ($existingRows as $row) {
    $existingByAddress[(string) $row['address']] = $row;
    $existingByName[(string) $row['dbmasterid'] . '|' . (string) $row['name']] = $row;
  }

  $addressConflicts = [];
  foreach ($incomingByAddress as $address => $incoming) {
    if (!isset($existingByAddress[$address])) {
      continue;
    }

    $existing = $existingByAddress[$address];
    $hasNameShift = (string) $existing['name'] !== (string) $incoming['name'];
    $hasTypeShift = (string) $existing['type'] !== (string) $incoming['type'];
    $hasDbShift = (int) $existing['dbmasterid'] !== (int) $incoming['dbmasterid'];
    if (!$hasNameShift && !$hasTypeShift && !$hasDbShift) {
      continue;
    }

    $addressConflicts[] = [
      'address' => $address,
      'old_dbsym' => (int) $existing['dbsym'],
      'new_dbsym' => (int) $incoming['dbsym'],
      'old_name' => (string) $existing['name'],
      'new_name' => (string) $incoming['name'],
      'old_type' => (string) $existing['type'],
      'new_type' => (string) $incoming['type'],
    ];
  }

  $nameConflicts = [];
  foreach ($incomingByName as $nameKey => $incoming) {
    if (!isset($existingByName[$nameKey])) {
      continue;
    }

    $existing = $existingByName[$nameKey];
    $hasAddressShift = (string) $existing['address'] !== (string) $incoming['address'];
    $hasTypeShift = (string) $existing['type'] !== (string) $incoming['type'];
    if (!$hasAddressShift && !$hasTypeShift) {
      continue;
    }

    $nameConflicts[] = [
      'dbsym' => (int) $incoming['dbsym'],
      'name' => (string) $incoming['name'],
      'old_address' => (string) $existing['address'],
      'new_address' => (string) $incoming['address'],
      'old_type' => (string) $existing['type'],
      'new_type' => (string) $incoming['type'],
    ];
  }

  $newRows = 0;
  foreach ($incomingByAddress as $address => $incoming) {
    if (!isset($existingByAddress[$address])) {
      $newRows++;
    }
  }

  $removedRows = 0;
  foreach ($existingByAddress as $address => $existing) {
    if (!isset($incomingByAddress[$address])) {
      $removedRows++;
    }
  }

  return [
    'has_shift' => !empty($addressConflicts) || !empty($nameConflicts),
    'summary' => [
      'incoming_rows' => count($incomingRows),
      'existing_rows' => count($existingRows),
      'address_conflicts' => count($addressConflicts),
      'name_conflicts' => count($nameConflicts),
      'new_rows' => $newRows,
      'removed_rows' => $removedRows,
    ],
    'examples' => [
      'address_conflicts' => db_act_preview_limit_examples($addressConflicts),
      'name_conflicts' => db_act_preview_limit_examples($nameConflicts),
    ],
  ];
}

try {
  $pdo = db_connect();
  $dbConfig = db_config();
  $tableOptions = db_act_table_options($pdo);

  if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $action = trim((string) ($_POST['action'] ?? ''));
    if ($action === 'preview_reimport_dblist') {
      $previewResult = db_act_preview_reimport_dblist($pdo);
      db_act_respond([
        'ok' => true,
        'action' => $action,
        'selected_table' => DB_DBLIST_TABLE,
        'message' => $previewResult['has_shift']
          ? 'Address, name, or type changes were detected before import.'
          : 'No address, name, or type changes were detected.',
        'preview' => $previewResult,
      ]);
    }

    if ($action === 'reimport_dblist') {
      $importResult = db_act_import_dblist($pdo);
      db_act_respond([
        'ok' => true,
        'action' => $action,
        'selected_table' => DB_DBLIST_TABLE,
        'row_count' => $importResult['row_count'],
        'db_count' => $importResult['db_count'],
        'message' => 'AWL import to dblist completed. Total rows: ' . $importResult['row_count'] . ' across ' . $importResult['db_count'] . ' DBs.',
        'detail' => $importResult['command_output'],
      ]);
    }

    db_act_respond([
      'ok' => false,
      'message' => 'Invalid action.',
    ], 400);
  }

  if (empty($tableOptions)) {
    db_act_respond([
      'ok' => true,
      'db_name' => $dbConfig['name'],
      'tables' => [],
      'selected_table' => '',
      'columns' => [],
      'rows' => [],
      'row_count' => 0,
      'returned_row_count' => 0,
      'row_limit' => null,
      'row_limit_value' => 'all',
      'order_by' => null,
      'order_dir' => 'asc',
      'message' => 'No tables are available.',
    ]);
  }

  $requestedTable = trim((string) ($_GET['table'] ?? ''));
  if ($requestedTable === '') {
    $requestedTable = $tableOptions[0]['value'];
  }
  $requestedTable = db_act_normalize_requested_table($tableOptions, $requestedTable);

  $selectedTable = db_act_resolve_table($tableOptions, $requestedTable);
  if ($selectedTable === null) {
    db_act_respond([
      'ok' => false,
      'message' => 'Invalid table selection.',
    ], 400);
  }

  $schemaName = $selectedTable['schema'];
  $tableName = $selectedTable['table'];
  $requestedLimit = trim((string) ($_GET['limit'] ?? ''));
  $columns = db_act_table_columns($pdo, $schemaName, $tableName);
  $orderBy = db_act_order_column($columns, trim((string) ($_GET['order_by'] ?? '')));
  $orderDir = db_act_order_direction(trim((string) ($_GET['order_dir'] ?? 'asc')));
  $rowLimit = db_act_effective_row_limit($schemaName, $tableName, $requestedLimit);
  $rows = db_act_table_rows($pdo, $schemaName, $tableName, $columns, $rowLimit, $orderBy, $orderDir);
  $totalRows = db_act_table_total_rows($pdo, $schemaName, $tableName);

  db_act_respond([
    'ok' => true,
    'db_name' => $dbConfig['name'],
    'tables' => $tableOptions,
    'selected_table' => $selectedTable['value'],
    'columns' => $columns,
    'rows' => $rows,
    'row_count' => $totalRows,
    'returned_row_count' => count($rows),
    'row_limit' => $rowLimit,
    'row_limit_value' => db_act_limit_value($rowLimit),
    'order_by' => $orderBy,
    'order_dir' => $orderDir,
    'message' => '',
  ]);
} catch (Throwable $e) {
  db_act_respond([
    'ok' => false,
    'message' => 'Failed to connect to the database or read the table: ' . $e->getMessage(),
  ], 500);
}
