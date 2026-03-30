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

require_once dirname(__DIR__, 2) . '/config/config.php';

const ROLL_HISTORY_LIMIT = 48;
const ROLL_HISTORY_RANGE_LIMIT = 500;

function roll_history_respond(array $payload, int $statusCode = 200): void
{
  http_response_code($statusCode);
  echo json_encode($payload);
  exit();
}

function roll_history_format_datetime($value): ?string
{
  if ($value === null || $value === '') {
    return null;
  }

  if ($value instanceof DateTimeInterface) {
    return $value->format('Y-m-d H:i:s');
  }

  try {
    $datetime = new DateTimeImmutable((string) $value);
    return $datetime->format('Y-m-d H:i:s');
  } catch (Throwable $e) {
    return null;
  }
}

function roll_history_duration_label(?int $seconds): string
{
  if ($seconds === null || $seconds <= 0) {
    return '-';
  }

  $hours = intdiv($seconds, 3600);
  $minutes = intdiv($seconds % 3600, 60);
  $parts = [];
  if ($hours > 0) {
    $parts[] = $hours . 'h';
  }
  if ($minutes > 0 || empty($parts)) {
    $parts[] = $minutes . 'm';
  }

  return implode(' ', $parts);
}

function roll_history_duration_seconds($starttime, $endtime): ?int
{
  if ($starttime === null || $starttime === '' || $endtime === null || $endtime === '') {
    return null;
  }

  try {
    $start =
      $starttime instanceof DateTimeInterface
        ? DateTimeImmutable::createFromInterface($starttime)
        : new DateTimeImmutable((string) $starttime);
    $end =
      $endtime instanceof DateTimeInterface
        ? DateTimeImmutable::createFromInterface($endtime)
        : new DateTimeImmutable((string) $endtime);
    return max(0, $end->getTimestamp() - $start->getTimestamp());
  } catch (Throwable $e) {
    return null;
  }
}

function roll_history_parse_datetime_param($value): ?DateTimeImmutable
{
  if ($value === null || trim((string) $value) === '') {
    return null;
  }

  try {
    return new DateTimeImmutable((string) $value);
  } catch (Throwable $e) {
    return null;
  }
}

function roll_history_fetch_rolls(
  PDO $pdo,
  ?DateTimeImmutable $rangeStart = null,
  ?DateTimeImmutable $rangeEnd = null,
): array {
  $sql = 'SELECT
       id,
       rollname,
       product,
       recipe,
       campaign,
       status,
       starttime,
       endtime,
       CASE
         WHEN starttime IS NOT NULL AND endtime IS NOT NULL THEN GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (endtime - starttime)))::int)
         ELSE NULL
       END AS duration_seconds
     FROM public.rolldata';
  $conditions = [];
  if ($rangeStart !== null) {
    $conditions[] = 'COALESCE(endtime, NOW()) >= :range_start';
  }
  if ($rangeEnd !== null) {
    $conditions[] = 'starttime <= :range_end';
  }
  if (!empty($conditions)) {
    $sql .= ' WHERE ' . implode(' AND ', $conditions);
  }
  $sql .= ' ORDER BY starttime DESC NULLS LAST, id DESC LIMIT :limit';

  $stmt = $pdo->prepare($sql);
  if ($rangeStart !== null) {
    $stmt->bindValue(':range_start', $rangeStart->format('Y-m-d H:i:s'));
  }
  if ($rangeEnd !== null) {
    $stmt->bindValue(':range_end', $rangeEnd->format('Y-m-d H:i:s'));
  }
  $stmt->bindValue(
    ':limit',
    $rangeStart !== null || $rangeEnd !== null ? ROLL_HISTORY_RANGE_LIMIT : ROLL_HISTORY_LIMIT,
    PDO::PARAM_INT,
  );
  $stmt->execute();

  $rolls = [];
  foreach ($stmt->fetchAll() as $row) {
    $durationSeconds = isset($row['duration_seconds']) ? (int) $row['duration_seconds'] : null;
    $rolls[] = [
      'id' => (int) $row['id'],
      'rollname' => (string) ($row['rollname'] ?? ''),
      'product' => (string) ($row['product'] ?? ''),
      'recipe' => (string) ($row['recipe'] ?? ''),
      'campaign' => (string) ($row['campaign'] ?? ''),
      'status' => isset($row['status']) ? (int) $row['status'] : null,
      'starttime' => roll_history_format_datetime($row['starttime'] ?? null),
      'endtime' => roll_history_format_datetime($row['endtime'] ?? null),
      'duration_seconds' => $durationSeconds,
      'duration_label' => roll_history_duration_label($durationSeconds),
    ];
  }

  return $rolls;
}

function roll_history_fetch_current_helper(
  PDO $pdo,
  ?DateTimeImmutable $rangeStart = null,
  ?DateTimeImmutable $rangeEnd = null,
): ?array {
  $sql = 'SELECT
      rollname,
      product,
      recipe,
      campaign,
      status,
      starttime,
      LOCALTIMESTAMP AS endtime,
      CASE
        WHEN starttime IS NOT NULL THEN GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (LOCALTIMESTAMP - starttime)))::int)
        ELSE NULL
      END AS duration_seconds
    FROM public.helper';
  $conditions = [];
  if ($rangeStart !== null) {
    $conditions[] = 'LOCALTIMESTAMP >= :range_start';
  }
  if ($rangeEnd !== null) {
    $conditions[] = 'starttime <= :range_end';
  }
  if (!empty($conditions)) {
    $sql .= ' WHERE ' . implode(' AND ', $conditions);
  }
  $sql .= ' ORDER BY starttime DESC NULLS LAST LIMIT 1';

  $stmt = $pdo->prepare($sql);
  if ($rangeStart !== null) {
    $stmt->bindValue(':range_start', $rangeStart->format('Y-m-d H:i:s'));
  }
  if ($rangeEnd !== null) {
    $stmt->bindValue(':range_end', $rangeEnd->format('Y-m-d H:i:s'));
  }
  $stmt->execute();

  $row = $stmt->fetch();
  if (!$row) {
    return null;
  }

  $starttime = roll_history_format_datetime($row['starttime'] ?? null);
  $endtime = roll_history_format_datetime($row['endtime'] ?? null);
  if ($starttime === null) {
    return null;
  }
  if ($endtime === null) {
    $endtime = $starttime;
  }

  $durationSeconds = isset($row['duration_seconds']) ? (int) $row['duration_seconds'] : null;

  return [
    'id' => 'helper-current',
    'rollname' => (string) ($row['rollname'] ?? ''),
    'product' => (string) ($row['product'] ?? ''),
    'recipe' => (string) ($row['recipe'] ?? ''),
    'campaign' => (string) ($row['campaign'] ?? ''),
    'status' => isset($row['status']) ? (int) $row['status'] : null,
    'starttime' => $starttime,
    'endtime' => $endtime,
    'duration_seconds' => $durationSeconds,
    'duration_label' => roll_history_duration_label($durationSeconds),
    'is_live' => true,
  ];
}

function roll_history_fetch_detail(PDO $pdo, int $rollId): array
{
  $rollStmt = $pdo->prepare(
    'SELECT
       id,
       rollname,
       product,
       recipe,
       campaign,
       status,
       starttime,
       endtime,
       CASE
         WHEN starttime IS NOT NULL AND endtime IS NOT NULL THEN GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (endtime - starttime)))::int)
         ELSE NULL
       END AS duration_seconds
     FROM public.rolldata
     WHERE id = :roll_id
     LIMIT 1',
  );
  $rollStmt->execute([':roll_id' => $rollId]);
  $rollRow = $rollStmt->fetch();
  if (!$rollRow) {
    roll_history_respond(['ok' => false, 'message' => 'Roll tidak ditemukan.'], 404);
  }

  $durationSeconds = isset($rollRow['duration_seconds'])
    ? (int) $rollRow['duration_seconds']
    : null;
  $roll = [
    'id' => (int) $rollRow['id'],
    'rollname' => (string) ($rollRow['rollname'] ?? ''),
    'product' => (string) ($rollRow['product'] ?? ''),
    'recipe' => (string) ($rollRow['recipe'] ?? ''),
    'campaign' => (string) ($rollRow['campaign'] ?? ''),
    'status' => isset($rollRow['status']) ? (int) $rollRow['status'] : null,
    'starttime' => roll_history_format_datetime($rollRow['starttime'] ?? null),
    'endtime' => roll_history_format_datetime($rollRow['endtime'] ?? null),
    'duration_seconds' => $durationSeconds,
    'duration_label' => roll_history_duration_label($durationSeconds),
  ];

  $detailStmt = $pdo->prepare(
    'SELECT
       r.id,
       r.rollid,
       r.dbid,
       d.address,
       d.name,
       r.value,
       r.timestamp
     FROM public.rtagroll r
     LEFT JOIN public.dblist d ON d.id = r.dbid
     WHERE r.rollid = :roll_id
     ORDER BY r.timestamp DESC NULLS LAST, r.id DESC',
  );
  $detailStmt->execute([':roll_id' => $rollId]);

  $rows = [];
  foreach ($detailStmt->fetchAll() as $row) {
    $value = $row['value'];
    $rows[] = [
      'id' => (int) $row['id'],
      'rollid' => (int) $row['rollid'],
      'dbid' => (int) $row['dbid'],
      'address' => (string) ($row['address'] ?? ''),
      'name' => (string) ($row['name'] ?? ''),
      'value' => $value !== null ? (float) $value : null,
      'value_text' => $value !== null ? (string) $value : '',
      'timestamp' => roll_history_format_datetime($row['timestamp'] ?? null),
    ];
  }

  return [
    'roll' => $roll,
    'tag_rows' => $rows,
    'tag_row_count' => count($rows),
  ];
}

try {
  $pdo = db_connect();
  $action = strtolower(trim((string) ($_GET['action'] ?? 'history')));
  $rangeStart = roll_history_parse_datetime_param($_GET['range_start'] ?? null);
  $rangeEnd = roll_history_parse_datetime_param($_GET['range_end'] ?? null);
  if ($rangeStart !== null && $rangeEnd !== null && $rangeStart > $rangeEnd) {
    [$rangeStart, $rangeEnd] = [$rangeEnd, $rangeStart];
  }

  if ($action === 'detail') {
    $rollId = (int) ($_GET['roll_id'] ?? 0);
    if ($rollId <= 0) {
      roll_history_respond(['ok' => false, 'message' => 'roll_id tidak valid.'], 422);
    }

    $detail = roll_history_fetch_detail($pdo, $rollId);
    roll_history_respond([
      'ok' => true,
      'roll' => $detail['roll'],
      'tag_rows' => $detail['tag_rows'],
      'tag_row_count' => $detail['tag_row_count'],
    ]);
  }

  $rolls = roll_history_fetch_rolls($pdo, $rangeStart, $rangeEnd);
  $currentHelperRoll = roll_history_fetch_current_helper($pdo, $rangeStart, $rangeEnd);
  if ($currentHelperRoll !== null) {
    $rolls[] = $currentHelperRoll;
  }
  $selectedRollId = (int) ($_GET['roll_id'] ?? 0);
  $selectedRollExistsInRange = false;
  foreach ($rolls as $rollItem) {
    if ((int) ($rollItem['id'] ?? 0) === $selectedRollId && $selectedRollId > 0) {
      $selectedRollExistsInRange = true;
      break;
    }
  }

  if ($selectedRollId <= 0 || !$selectedRollExistsInRange) {
    $selectedRollId = 0;
  }

  $detail = $selectedRollId > 0 ? roll_history_fetch_detail($pdo, $selectedRollId) : null;

  roll_history_respond([
    'ok' => true,
    'rolls' => $rolls,
    'range_start' => $rangeStart !== null ? $rangeStart->format('Y-m-d H:i:s') : null,
    'range_end' => $rangeEnd !== null ? $rangeEnd->format('Y-m-d H:i:s') : null,
    'selected_roll_id' => $selectedRollId > 0 ? $selectedRollId : null,
    'roll' => $detail['roll'] ?? null,
    'tag_rows' => $detail['tag_rows'] ?? [],
    'tag_row_count' => $detail['tag_row_count'] ?? 0,
  ]);
} catch (Throwable $e) {
  roll_history_respond(
    [
      'ok' => false,
      'message' => 'Gagal memuat roll history.',
      'detail' => $e->getMessage(),
    ],
    500,
  );
}
