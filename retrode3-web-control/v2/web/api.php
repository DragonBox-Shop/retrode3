<?php
/* Authenticated same-origin gateway to the loopback Python backend. */
require __DIR__ . '/auth.php';
retrode_auth();
retrode_session();
$method = $_SERVER['REQUEST_METHOD'];
if ($method !== 'GET' && $method !== 'POST') {
    header('Allow: GET, POST');
    http_response_code(405);
    exit;
}
if ($method === 'POST') retrode_csrf();
$route = isset($_GET['route']) ? $_GET['route'] : '';
if (!is_string($route) || !preg_match('~^/(?:api/[A-Za-z0-9/_-]+)$~', $route)) {
    http_response_code(400);
    exit('{"error":"invalid_route"}');
}
$query = '';
if (isset($_GET['path'])) {
    if (!is_string($_GET['path'])) {
        http_response_code(400);
        exit('{"error":"invalid_path"}');
    }
    $query = '?path=' . rawurlencode($_GET['path']);
}
$body = '';
if ($method === 'POST') {
    $body = file_get_contents('php://input', false, null, 0, 16385);
    if (strlen($body) > 16384) {
        http_response_code(413);
        exit('{"error":"body_too_large"}');
    }
}
$socket = @stream_socket_client('tcp://127.0.0.1:8765', $errno, $errstr, 3);
if (!$socket) {
    header('Content-Type: application/json; charset=utf-8');
    http_response_code(503);
    exit('{"error":"backend_unavailable"}');
}
stream_set_timeout($socket, 20);
$request = $method . ' ' . $route . $query . " HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n";
if ($method === 'POST') {
    $request .= "Content-Type: application/json\r\nContent-Length: " . strlen($body) . "\r\n";
}
$request .= "\r\n" . $body;
fwrite($socket, $request);
$statusLine = fgets($socket, 4096);
if (!preg_match('~^HTTP/\d\.\d\s+(\d{3})~', $statusLine, $match)) {
    fclose($socket);
    http_response_code(502);
    exit('{"error":"backend_response_invalid"}');
}
$status = intval($match[1]);
$headers = array();
while (($line = fgets($socket, 8192)) !== false) {
    if (trim($line) === '') break;
    $parts = explode(':', $line, 2);
    if (count($parts) === 2) {
        $headers[strtolower(trim($parts[0]))] = trim($parts[1]);
    }
}
http_response_code($status);
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
header('Content-Type: ' . (isset($headers['content-type']) && $route === '/api/files/download'
    ? 'application/octet-stream' : 'application/json; charset=utf-8'));
if ($route === '/api/files/download') {
    if (isset($headers['content-disposition'])) {
        header('Content-Disposition: ' . $headers['content-disposition']);
    }
    if (isset($headers['content-length'])) {
        header('Content-Length: ' . $headers['content-length']);
    }
}
while (!feof($socket)) {
    $block = fread($socket, 65536);
    if ($block === false || $block === '') break;
    echo $block;
}
fclose($socket);
