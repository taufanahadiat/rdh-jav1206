<?php
$isHttps =
  (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ||
  ($_SERVER['SERVER_PORT'] ?? '') === '443';

if (PHP_VERSION_ID >= 70300) {
  session_set_cookie_params([
    'lifetime' => 0,
    'path' => '/',
    'domain' => '',
    'secure' => $isHttps,
    'httponly' => true,
    'samesite' => 'Lax',
  ]);
} else {
  session_set_cookie_params(0, '/; samesite=Lax', '', $isHttps, true);
}

ini_set('session.use_strict_mode', '1');
ini_set('session.use_only_cookies', '1');
session_start();
require_once __DIR__ . '/config/config.php';

$dbConfig = db_config();

$error = '';
$debugMsg = '';

if (isset($_GET['logout'])) {
  session_destroy();
  header('Location: index.php');
  exit();
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  $username = trim($_POST['username'] ?? '');
  $password = (string) ($_POST['password'] ?? '');
  $isAjax =
    (isset($_SERVER['HTTP_X_REQUESTED_WITH']) &&
      strtolower($_SERVER['HTTP_X_REQUESTED_WITH']) === 'xmlhttprequest') ||
    (isset($_POST['ajax']) && $_POST['ajax'] === '1');

  if ($username === '') {
    $error = 'Username is required.';
    if ($isAjax) {
      header('Content-Type: application/json');
      echo json_encode(['ok' => false, 'message' => $error]);
      exit();
    }
  } else {
    try {
      $pdo = db_connect();
      $stmt = $pdo->prepare(
        'SELECT u.username, u.pass, COALESCE(u.name, \'\') AS name, COALESCE(r.rolename, \'\') AS rolename
         FROM public."user" u
         LEFT JOIN public.role r ON r.id = u.roleid
         WHERE u.username = :username
         LIMIT 1',
      );
      $stmt->execute([':username' => $username]);
      $row = $stmt->fetch();

      if ($row && password_verify($password, (string) $row['pass'])) {
        session_regenerate_id(true);
        $_SESSION['username'] = $username;
        $_SESSION['name'] = $row['name'] !== '' ? $row['name'] : $username;
        $_SESSION['role'] = $row['rolename'];

        $updateLogin = $pdo->prepare(
          'UPDATE public."user" SET lastlogin = CURRENT_TIMESTAMP WHERE username = :username',
        );
        $updateLogin->execute([':username' => $username]);

        if ($isAjax) {
          header('Content-Type: application/json');
          echo json_encode(['ok' => true, 'redirect' => 'main/index.php']);
          exit();
        } else {
          header('Location: main/index.php');
          exit();
        }
      } else {
        $error = 'Invalid username or password.';
        if ($isAjax) {
          header('Content-Type: application/json');
          echo json_encode(['ok' => false, 'message' => $error]);
          exit();
        }
      }
    } catch (Exception $e) {
      $safeHost = $dbConfig['host'];
      $safePort = $dbConfig['port'];
      $safeDb = $dbConfig['name'];
      $safeUser = $dbConfig['user'];
      $debugMsg =
        'DB ERROR: ' .
        $e->getMessage() .
        ' | host=' .
        $safeHost .
        ' port=' .
        $safePort .
        ' db=' .
        $safeDb .
        ' user=' .
        $safeUser;
      error_log($debugMsg);
      $error = 'Database connection failed. Please check the configuration.';
      if ($isAjax) {
        header('Content-Type: application/json');
        echo json_encode(['ok' => false, 'message' => $error, 'debug' => $debugMsg]);
        exit();
      }
    }
  }
}

$loggedIn = isset($_SESSION['username']);
if ($loggedIn) {
  header('Location: main/index.php');
  exit();
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Login | LINE-5</title>

  <!-- Font Awesome (local) -->
  <link rel="stylesheet" href="plugins/AdminLTE-3.2.0/plugins/fontawesome-free/css/all.min.css">
  <!-- AdminLTE 3 (local) -->
  <link rel="stylesheet" href="plugins/AdminLTE-3.2.0/dist/css/adminlte.min.css">
  <link rel="stylesheet" href="plugins/AdminLTE-3.2.0/plugins/sweetalert2-theme-bootstrap-4/bootstrap-4.min.css">
  <link rel="stylesheet" href="plugins/AdminLTE-3.2.0/plugins/sweetalert2/sweetalert2.min.css">
  <link rel="stylesheet" href="plugins/AdminLTE-3.2.0/plugins/toastr/toastr.min.css">
</head>
<body class="hold-transition login-page">

  <div class="login-box">
    <div class="card card-outline card-primary">
      <div class="card-header text-center">
        <span class="h1"><b>Roll Data</b> History</span>
      </div>
      <div class="card-body">
        <p class="login-box-msg">LINE-5 [JAV1206]</p>

        <form id="login-form" action="index.php" method="post" autocomplete="off">
          <div class="input-group mb-3">
            <input type="text" name="username" class="form-control" placeholder="Username" required>
            <div class="input-group-append">
              <div class="input-group-text">
                <span class="fas fa-user"></span>
              </div>
            </div>
          </div>
          <div class="input-group mb-3">
            <input type="password" name="password" class="form-control" placeholder="Password">
            <div class="input-group-append">
              <div class="input-group-text">
                <span class="fas fa-lock"></span>
              </div>
            </div>
          </div>
          <div class="row">
            <div class="col-12">
              <button type="submit" class="btn btn-primary btn-block">Login</button>
            </div>
          </div>
        </form>
      </div>
    </div>
  </div>

<!-- jQuery (local) -->
<script src="plugins/AdminLTE-3.2.0/plugins/jquery/jquery.min.js"></script>
<!-- Bootstrap 4 (local) -->
<script src="plugins/AdminLTE-3.2.0/plugins/bootstrap/js/bootstrap.bundle.min.js"></script>
<script src="plugins/AdminLTE-3.2.0/plugins/sweetalert2/sweetalert2.all.min.js"></script>
<script src="plugins/AdminLTE-3.2.0/plugins/toastr/toastr.min.js"></script>
<!-- AdminLTE 3 (local) -->
<script src="plugins/AdminLTE-3.2.0/dist/js/adminlte.min.js"></script>
<script src="app-notify.js"></script>
<script>
  (function ($) {
    var $form = $('#login-form');
    if (!$form.length) return;

    <?php if ($error): ?>
    if (window.AppNotify) {
      window.AppNotify.backend.error(<?php echo json_encode($error); ?>);
    }
    <?php endif; ?>

    $form.on('submit', function (e) {
      var formData = new FormData($form[0]);

      e.preventDefault();
      formData.append('ajax', '1');

      $.ajax({
        url: 'index.php',
        method: 'POST',
        dataType: 'json',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        data: formData,
        processData: false,
        contentType: false
      })
        .done(function (data) {
          if (data.ok) {
            window.location.href = data.redirect || 'main/index.php';
            return;
          }
          if (data.debug) {
            console.error(data.debug);
          }
          if (window.AppNotify) {
            window.AppNotify.backend.error(data.message || 'Login failed.');
          }
        })
        .fail(function (xhr, status, err) {
          var message = 'Login failed.';
          console.error('AJAX error:', err);
          if (xhr && xhr.responseJSON && xhr.responseJSON.message) {
            message = xhr.responseJSON.message;
          } else if (status) {
            message = 'Request failed: ' + status;
            console.error(message);
          }

          if (window.AppNotify) {
            window.AppNotify.backend.error(message);
          }
        });
    });
  })(window.jQuery);
</script>
</body>
</html>
