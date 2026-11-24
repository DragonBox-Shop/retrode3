<?php
/* Write Cartridge ROM upload: local computer -> Retrode3 ROM library.
 * Same session, CSRF and file ownership as the existing Web file manager.
 * No command shell or root privileges. Compatible with PHP 5.6+.
 */
require __DIR__ . '/auth.php';
retrode_auth();
retrode_session();
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');

function rom_upload_error($status, $code, $message) {
    http_response_code($status);
    echo json_encode(array('error' => $code, 'message' => $message));
    exit;
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    header('Allow: POST');
    rom_upload_error(405, 'method', 'POST required');
}
retrode_csrf();

$maximum = 4194304;
if (isset($_SERVER['CONTENT_LENGTH']) &&
    (float) $_SERVER['CONTENT_LENGTH'] > $maximum + 65536) {
    rom_upload_error(413, 'too_large', 'Maximum ROM size is 4 MiB');
}
$folder = isset($_POST['folder']) ? $_POST['folder'] : null;
if (!is_string($folder) || !preg_match('/^[A-Z0-9_-]{1,48}$/D', $folder)) {
    rom_upload_error(400, 'folder', 'Invalid ROM destination folder');
}
if (!isset($_FILES['rom']) || !is_array($_FILES['rom'])) {
    rom_upload_error(400, 'file', 'Choose a ROM file to upload');
}
$file = $_FILES['rom'];
if (isset($file['error']) && $file['error'] === UPLOAD_ERR_INI_SIZE ||
    isset($file['error']) && $file['error'] === UPLOAD_ERR_FORM_SIZE) {
    rom_upload_error(413, 'php_limit', 'PHP upload limit is too small for this ROM');
}
if (!isset($file['error']) || $file['error'] !== UPLOAD_ERR_OK ||
    !isset($file['tmp_name']) || !is_uploaded_file($file['tmp_name'])) {
    rom_upload_error(400, 'upload', 'ROM upload failed');
}
$size = isset($file['size']) ? (int) $file['size'] : -1;
if ($size < 512 || $size > $maximum || ($size % 2) !== 0) {
    rom_upload_error(400, 'size', 'ROM must be an even-sized file of at most 4 MiB');
}
$name = isset($file['name']) ? $file['name'] : '';
if (!is_string($name) || strlen($name) < 1 || strlen($name) > 128 ||
    $name[0] === '.' || strpos($name, '/') !== false ||
    strpos($name, '\\') !== false || preg_match('/[\x00-\x1f\x7f]/', $name)) {
    rom_upload_error(400, 'filename', 'Invalid ROM filename');
}
if (!preg_match('/^[A-Za-z0-9_. -]+$/D', $name)) {
    rom_upload_error(400, 'filename', 'Please use a simple ROM filename');
}
$root = '/usr/local/games/ROMs';
if (!is_dir($root) || is_link($root)) {
    rom_upload_error(503, 'storage', 'ROM library is unavailable');
}
$directory = $root . '/' . $folder;
if (!is_dir($directory) && !mkdir($directory, 0755)) {
    rom_upload_error(503, 'storage', 'Cannot create the ROM system folder');
}
if (is_link($directory) || !is_dir($directory)) {
    rom_upload_error(400, 'storage', 'Invalid destination directory');
}
$stem = pathinfo($name, PATHINFO_FILENAME);
$ext = pathinfo($name, PATHINFO_EXTENSION);
if ($stem === '' || strlen($stem) > 120) {
    rom_upload_error(400, 'filename', 'Invalid ROM filename');
}
$suffix = $ext !== '' ? '.' . $ext : '';
$chosen = '';
for ($i = 0; $i < 1000; $i++) {
    $candidate = $stem . ($i ? '-' . $i : '') . $suffix;
    if (!file_exists($directory . '/' . $candidate) &&
        !is_link($directory . '/' . $candidate)) {
        $chosen = $candidate;
        break;
    }
}
if ($chosen === '') {
    rom_upload_error(409, 'exists', 'Too many files with this name');
}
if (!move_uploaded_file($file['tmp_name'], $directory . '/' . $chosen)) {
    rom_upload_error(500, 'storage', 'Unable to save uploaded ROM');
}
@chmod($directory . '/' . $chosen, 0644);
echo json_encode(array('ok' => true,
                       'path' => $folder . '/' . $chosen,
                       'size' => $size));
