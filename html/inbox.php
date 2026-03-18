<?php
session_start();

if (!isset($_SESSION['username'])) {
  http_response_code(401);
  header('Content-Type: application/json');
  echo json_encode(['ok' => false, 'message' => 'Unauthorized']);
  exit();
}

header('Content-Type: application/json');

$normalizeTag = function ($rawTag) {
  $rawTag = strtoupper(preg_replace('/\s+/', '', (string) $rawTag));
  if (preg_match('/^DB(\d+)\.DBB(\d+)\[(\d+)\]$/', $rawTag, $m)) {
    $dbNum = (int) $m[1];
    $byte = (int) $m[2];
    $len = (int) $m[3];

    if ($len < 1 || $len > 254) {
      return null;
    }

    return [sprintf('DB%d.DBB%d[%d]', $dbNum, $byte, $len), $dbNum];
  }

  if (!preg_match('/^DB(\d+)\.(DBX|DBB|DBW|DBD|DBS)(\d+)(?:\.(\d+))?$/', $rawTag, $m)) {
    return null;
  }

  $dbNum = (int) $m[1];
  $area = $m[2];
  $byte = (int) $m[3];
  $bit = isset($m[4]) ? (int) $m[4] : null;

  if ($area === 'DBX') {
    if ($bit === null || $bit < 0 || $bit > 7) {
      return null;
    }
    return [sprintf('DB%d.DBX%d.%d', $dbNum, $byte, $bit), $dbNum];
  }

  if ($area === 'DBS') {
    $len = $bit === null ? 50 : $bit;
    if ($len < 1 || $len > 254) {
      return null;
    }
    return [sprintf('DB%d.DBB%d[%d]', $dbNum, $byte, $len), $dbNum];
  }

  if ($bit !== null) {
    return null;
  }

  return [sprintf('DB%d.%s%d', $dbNum, $area, $byte), $dbNum];
};

$rawTags = [];
$rawBody = file_get_contents('php://input');
if (is_string($rawBody) && trim($rawBody) !== '') {
  $jsonBody = json_decode($rawBody, true);
  if (is_array($jsonBody)) {
    if (isset($jsonBody['tags']) && is_array($jsonBody['tags'])) {
      $rawTags = $jsonBody['tags'];
    } elseif (isset($jsonBody['tags']) && is_string($jsonBody['tags'])) {
      $rawTags = explode(',', $jsonBody['tags']);
    }
  }
}

if (empty($rawTags) && isset($_POST['tags'])) {
  if (is_array($_POST['tags'])) {
    $rawTags = $_POST['tags'];
  } else {
    $rawTags = explode(',', (string) $_POST['tags']);
  }
}

if (empty($rawTags) && isset($_GET['tags'])) {
  $rawTags = explode(',', (string) $_GET['tags']);
}

if (empty($rawTags) && isset($_GET['tag'])) {
  if (is_array($_GET['tag'])) {
    $rawTags = $_GET['tag'];
  } else {
    $rawTags = [$_GET['tag']];
  }
}

if (empty($rawTags) && isset($_GET['db'])) {
  if (is_array($_GET['db'])) {
    $rawTags = $_GET['db'];
  } else {
    $rawTags = [$_GET['db']];
  }
}

$rawTags = array_values(
  array_filter(array_map('trim', $rawTags), function ($v) {
    return $v !== '';
  }),
);

if (empty($rawTags)) {
  echo json_encode(['ok' => false, 'message' => 'No PLC tags were requested.']);
  exit();
}

$tagsByDb = [];
$normalizedTags = [];
foreach ($rawTags as $rawTag) {
  $parsed = $normalizeTag($rawTag);
  if ($parsed === null) {
    echo json_encode(['ok' => false, 'message' => 'Invalid PLC tag format: ' . $rawTag]);
    exit();
  }

  [$tag, $dbNum] = $parsed;
  if (!isset($normalizedTags[$tag])) {
    $normalizedTags[$tag] = true;
    if (!isset($tagsByDb[$dbNum])) {
      $tagsByDb[$dbNum] = [];
    }
    $tagsByDb[$dbNum][] = $tag;
  }
}

if (empty($tagsByDb)) {
  echo json_encode(['ok' => false, 'message' => 'No PLC tags were requested.']);
  exit();
}

$tagValues = [];
foreach ($tagsByDb as $dbNum => $tags) {
  $scripts = glob(__DIR__ . '/py/DB' . (int) $dbNum . '_*.py');
  if (!$scripts) {
    echo json_encode([
      'ok' => false,
      'message' => 'Reader script for DB' . $dbNum . ' was not found.',
    ]);
    exit();
  }

  sort($scripts, SORT_NATURAL | SORT_FLAG_CASE);
  $scriptPath = $scripts[0];

  $cmdParts = ['python3', escapeshellarg($scriptPath), '--json'];
  foreach ($tags as $tag) {
    $cmdParts[] = '--tag';
    $cmdParts[] = escapeshellarg($tag);
  }
  $cmd = implode(' ', $cmdParts) . ' 2>&1';

  $output = shell_exec($cmd);
  if ($output === null || trim($output) === '') {
    echo json_encode(['ok' => false, 'message' => 'Failed to read DB' . $dbNum . ' from the PLC.']);
    exit();
  }

  $cleanOutput = trim($output);
  $readerData = json_decode($cleanOutput, true);
  if (!is_array($readerData) && preg_match('/\{(?:[^{}]|(?R))*\}\s*$/s', $cleanOutput, $m)) {
    $readerData = json_decode($m[0], true);
  }

  if (!is_array($readerData)) {
    echo json_encode([
      'ok' => false,
      'message' => 'The DB' . $dbNum . ' reader output is not valid JSON.',
      'raw' => $cleanOutput,
    ]);
    exit();
  }

  if (isset($readerData['error']) && $readerData['error'] !== '') {
    echo json_encode([
      'ok' => false,
      'message' => 'DB' . $dbNum . ' reader error: ' . $readerData['error'],
    ]);
    exit();
  }

  if (!isset($readerData['tags']) || !is_array($readerData['tags'])) {
    echo json_encode([
      'ok' => false,
      'message' => 'DB' . $dbNum . ' reader did not return a tags field.',
      'raw' => $readerData,
    ]);
    exit();
  }

  foreach ($readerData['tags'] as $tag => $value) {
    $tagValues[strtoupper((string) $tag)] = $value;
  }
}

if (count($normalizedTags) === 1) {
  $singleTag = '';
  foreach ($normalizedTags as $tag => $_) {
    $singleTag = $tag;
    break;
  }

  echo json_encode([
    'ok' => true,
    'timestamp' => date('Y-m-d H:i:s'),
    'data' => [
      'mode' => 'single_tag',
      'product' => $singleTag,
      'tag' => $singleTag,
      'value' => array_key_exists($singleTag, $tagValues) ? $tagValues[$singleTag] : null,
    ],
    'tag_values' => $tagValues,
  ]);
  exit();
}

echo json_encode([
  'ok' => true,
  'timestamp' => date('Y-m-d H:i:s'),
  'data' => [],
  'tag_values' => $tagValues,
]);
exit();
