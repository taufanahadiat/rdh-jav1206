<?php
session_start();

if (!isset($_SESSION['username'])) {
  header('Location: ../index.php');
  exit();
}

$displayName = trim((string) ($_SESSION['name'] ?? ''));
if ($displayName === '') {
  $displayName = (string) $_SESSION['username'];
}
$userRole = strtolower(trim((string) ($_SESSION['role'] ?? '')));

$id = isset($_GET['id']) ? trim((string) $_GET['id']) : 'dashboard';
if ($id === '' || $id === 'dashbboard') {
  $id = 'dashboard';
}

$activeMenu = $id;
$pageTitle = 'Dashboard Inbox | LINE-5';
$assetBase = '../';
$routeBase = 'index.php';
$logoutUrl = '../index.php?logout=1';
$inboxEndpoint = '../include/dashboard/dash_act.php';
$includeDataTables = $id === 'database' && $userRole === 'admin';
?>
<?php include('../_partials/head.php'); ?>
<body class="hold-transition sidebar-mini layout-fixed theme-dark">
<div class="wrapper">
  <?php include('../_partials/navbar.php'); ?>
  <?php include('../_partials/sidebar.php'); ?>

  <div class="content-wrapper">
    <?php
    if ($id === 'dashboard') {
      include_once(__DIR__ . '/../include/dashboard/dashboard.php');
    } elseif ($id === 'database' && $userRole === 'admin') {
      include_once(__DIR__ . '/../include/admin/database.php');
    } else {
      include_once(__DIR__ . '/../include/dashboard/dashboard.php');
    }
    ?>
  </div>

  <?php include('../_partials/footer.php'); ?>
</div>
<?php include('../_partials/js.php'); ?>
</body>
</html>
