<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title><?php echo htmlspecialchars($pageTitle ?? 'Dashboard Inbox | LINE-5'); ?></title>

  <?php $assetBase = $assetBase ?? ''; ?>
  <link rel="icon" type="image/svg+xml" href="<?php echo htmlspecialchars($assetBase); ?>favicon.svg">
  <link rel="icon" type="image/x-icon" href="<?php echo htmlspecialchars($assetBase); ?>favicon.ico">
  <link rel="shortcut icon" href="<?php echo htmlspecialchars($assetBase); ?>favicon.ico">
  <link rel="stylesheet" href="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/plugins/fontawesome-free/css/all.min.css">
  <link rel="stylesheet" href="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/dist/css/adminlte.min.css">
  <link rel="stylesheet" href="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/plugins/select2/css/select2.min.css">
  <link rel="stylesheet" href="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/plugins/select2-bootstrap4-theme/select2-bootstrap4.min.css">
  <link rel="stylesheet" href="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/plugins/sweetalert2-theme-bootstrap-4/bootstrap-4.min.css">
  <link rel="stylesheet" href="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/plugins/sweetalert2/sweetalert2.min.css">
  <link rel="stylesheet" href="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/plugins/toastr/toastr.min.css">
  <?php if (!empty($includeDataTables)): ?>
  <link rel="stylesheet" href="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/plugins/datatables-bs4/css/dataTables.bootstrap4.min.css">
  <link rel="stylesheet" href="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/plugins/datatables-responsive/css/responsive.bootstrap4.min.css">
  <?php endif; ?>
  <link rel="stylesheet" href="<?php echo htmlspecialchars($assetBase); ?>include/dashboard/dashboard.css">
  <link rel="stylesheet" href="<?php echo htmlspecialchars($assetBase); ?>theme.css">
</head>
