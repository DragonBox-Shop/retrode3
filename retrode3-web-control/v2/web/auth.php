<?php
/* Never put a password or credential file inside the served document root. */
function retrode_auth() {
    $file = '/etc/retrode3-web-control.auth';
    if (!is_readable($file)) {
        http_response_code(503);
        header('Content-Type: text/plain; charset=utf-8');
        exit("Retrode3 web authentication is not configured.\nSee v2/README.md.\n");
    }
    $hash = trim(file_get_contents($file));
    $user = isset($_SERVER['PHP_AUTH_USER']) ? $_SERVER['PHP_AUTH_USER'] : '';
    $password = isset($_SERVER['PHP_AUTH_PW']) ? $_SERVER['PHP_AUTH_PW'] : '';
    if ($user !== 'admin' || !password_verify($password, $hash)) {
        header('WWW-Authenticate: Basic realm="Retrode3 Administration"');
        http_response_code(401);
        exit('Authentication required');
    }
}
function retrode_session() {
    ini_set('session.cookie_httponly', '1');
    ini_set('session.cookie_samesite', 'Strict');
    session_start();
    if (empty($_SESSION['csrf'])) {
        if (function_exists('random_bytes')) {
            $bytes = random_bytes(24);
        } elseif (function_exists('openssl_random_pseudo_bytes')) {
            $strong = false;
            $bytes = openssl_random_pseudo_bytes(24, $strong);
            if (!$strong) {
                http_response_code(503);
                exit('Secure session randomness unavailable');
            }
        } else {
            http_response_code(503);
            exit('Secure session randomness unavailable');
        }
        $_SESSION['csrf'] = bin2hex($bytes);
    }
    return $_SESSION['csrf'];
}
function retrode_csrf() {
    $token = isset($_SERVER['HTTP_X_CSRF_TOKEN']) ? $_SERVER['HTTP_X_CSRF_TOKEN'] : '';
    if (!$token || !hash_equals($_SESSION['csrf'], $token)) {
        http_response_code(403);
        header('Content-Type: application/json; charset=utf-8');
        exit('{"error":"csrf_invalid"}');
    }
    /* Reject requests coming from a different origin, including a form post. */
    $host = isset($_SERVER['HTTP_HOST']) ? $_SERVER['HTTP_HOST'] : '';
    $origin = isset($_SERVER['HTTP_ORIGIN']) ? $_SERVER['HTTP_ORIGIN'] : '';
    if ($origin) {
        $target = parse_url($origin, PHP_URL_HOST);
        $authority = parse_url('http://' . $host, PHP_URL_HOST);
        if (!$target || strcasecmp($target, $authority) !== 0) {
            http_response_code(403);
            exit('{"error":"origin_invalid"}');
        }
    }
}
