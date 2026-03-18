<?php
session_start();

if (!isset($_SESSION['username'])) {
  http_response_code(401);
  header('Content-Type: application/json');
  echo json_encode(['ok' => false, 'message' => 'Unauthorized']);
  exit();
}

$upstreamBaseUrl = rtrim((string) (getenv('PLC_API_URL') ?: 'http://127.0.0.1:8000'), '/');
$upstreamUrl = $upstreamBaseUrl . '/plc/dashboard-snapshot';
$queryString = (string) ($_SERVER['QUERY_STRING'] ?? '');
if ($queryString !== '') {
  $upstreamUrl .= '?' . $queryString;
}

$method = strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET'));
$rawBody = file_get_contents('php://input');
$headers = [
  'Accept: application/json',
];

$contentType = (string) ($_SERVER['CONTENT_TYPE'] ?? '');
if ($contentType !== '') {
  $headers[] = 'Content-Type: ' . $contentType;
}

$context = stream_context_create([
  'http' => [
    'method' => $method,
    'timeout' => 10,
    'ignore_errors' => true,
    'header' => implode("\r\n", $headers),
    'content' => in_array($method, ['POST', 'PUT', 'PATCH'], true) ? $rawBody : '',
  ],
]);

$responseBody = @file_get_contents($upstreamUrl, false, $context);
if ($responseBody === false) {
  http_response_code(502);
  header('Content-Type: application/json');
  echo json_encode([
    'ok' => false,
    'message' => 'Failed to reach PLC API upstream.',
    'upstream' => $upstreamUrl,
  ]);
  exit();
}

$statusCode = 200;
foreach (($http_response_header ?? []) as $headerLine) {
  if (preg_match('#^HTTP/\S+\s+(\d{3})#', $headerLine, $m)) {
    $statusCode = (int) $m[1];
    continue;
  }

  if (stripos($headerLine, 'Content-Type:') === 0) {
    header($headerLine);
  }
}

http_response_code($statusCode);
if (!headers_sent()) {
  header('Content-Type: application/json');
}
echo $responseBody;
