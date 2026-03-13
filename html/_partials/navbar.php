<?php
$routeBase = $routeBase ?? 'index.php';
$logoutUrl = $logoutUrl ?? 'index.php?logout=1';
?>
<nav class="main-header navbar navbar-expand navbar-white navbar-light">
  <ul class="navbar-nav">
    <li class="nav-item">
      <a class="nav-link" data-widget="pushmenu" href="#" role="button"><i class="fas fa-bars"></i></a>
    </li>
    <li class="nav-item d-none d-sm-inline-block">
      <a href="<?php echo htmlspecialchars($routeBase); ?>?id=dashboard" class="nav-link">Dashboard</a>
    </li>
  </ul>
  <ul class="navbar-nav ml-auto">
    <li class="nav-item mr-2 d-flex align-items-center">
      <label for="themeMode" class="mb-0 mr-2 text-sm">Mode</label>
      <select id="themeMode" class="custom-select custom-select-sm theme-switch-select" aria-label="Theme mode">
        <option value="dark" selected>Dark</option>
        <option value="light">Light</option>
      </select>
    </li>
    <li class="nav-item">
      <a class="nav-link" href="<?php echo htmlspecialchars($logoutUrl); ?>"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </li>
  </ul>
</nav>
