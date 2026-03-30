<?php
require_once __DIR__ . '/../config/config.php';
$activeMenu = $activeMenu ?? 'dashboard';
$routeBase = $routeBase ?? 'index.php';
$userRole = strtolower(trim((string) ($userRole ?? '')));
$isAdmin = $userRole === 'admin';
$isAdminMenuOpen = $activeMenu === 'database';
$sidebarTitle = web_sidebar_title();
?>
<aside class="main-sidebar sidebar-dark-primary elevation-4">
  <a href="<?php echo htmlspecialchars($routeBase); ?>?id=dashboard" class="brand-link">
    <span class="brand-text font-weight-light"><?php echo htmlspecialchars($sidebarTitle); ?></span>
  </a>
  <div class="sidebar">
    <div class="user-panel mt-3 pb-3 mb-3 d-flex">
      <div class="image">
        <i class="fas fa-user-circle fa-2x text-white"></i>
      </div>
      <div class="info">
        <span class="d-block text-white"><?php echo htmlspecialchars($displayName); ?></span>
      </div>
    </div>
    <nav class="mt-2">
      <ul class="nav nav-pills nav-sidebar flex-column" data-widget="treeview" role="menu" data-accordion="false">
        <li class="nav-item">
          <a href="<?php echo htmlspecialchars($routeBase); ?>?id=dashboard" class="nav-link <?php echo $activeMenu === 'dashboard' ? 'active' : ''; ?>">
            <i class="nav-icon fas fa-tachometer-alt"></i>
            <p>Dashboard</p>
          </a>
        </li>
        <?php if ($isAdmin): ?>
          <li class="nav-item has-treeview <?php echo $isAdminMenuOpen ? 'menu-open' : ''; ?>">
            <a href="#" class="nav-link <?php echo $isAdminMenuOpen ? 'active' : ''; ?>">
              <i class="nav-icon fas fa-user-shield"></i>
              <p>
                Admin
                <i class="right fas fa-angle-left"></i>
              </p>
            </a>
            <ul class="nav nav-treeview">
              <li class="nav-item">
                <a href="<?php echo htmlspecialchars($routeBase); ?>?id=database" class="nav-link <?php echo $activeMenu === 'database' ? 'active' : ''; ?>">
                  <i class="far fa-circle nav-icon"></i>
                  <p>Database</p>
                </a>
              </li>
            </ul>
          </li>
        <?php endif; ?>
      </ul>
    </nav>
  </div>
</aside>
