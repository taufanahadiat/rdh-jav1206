<?php
session_start();
require_once __DIR__ . '/../config/config.php';

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
$pageTitle = web_page_title(web_app_title());
$assetBase = '../';
$routeBase = 'index.php';
$logoutUrl = '../index.php?logout=1';
$inboxEndpoint = '../include/dashboard/dash_act.php';
$includeDataTables = $id === 'database' && $userRole === 'admin';
$sidebarStorageKey = 'dashboardSidebarState:' . (string) ($_SESSION['username'] ?? 'guest');
$layoutJsVersion = @filemtime(__DIR__ . '/../assets/js/layout.js') ?: time();
?>
<?php include('../_partials/head.php'); ?>
<body class="hold-transition sidebar-collapse layout-fixed theme-dark" data-sidebar-storage-key="<?php echo htmlspecialchars($sidebarStorageKey); ?>">
<script src="<?php echo htmlspecialchars($assetBase); ?>assets/js/layout.js?v=<?php echo urlencode((string) $layoutJsVersion); ?>"></script>
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
