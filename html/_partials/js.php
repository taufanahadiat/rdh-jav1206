<?php
$assetBase = $assetBase ?? '';
?>
<script src="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/plugins/jquery/jquery.min.js"></script>
<script src="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/plugins/bootstrap/js/bootstrap.bundle.min.js"></script>
<script src="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/plugins/select2/js/select2.full.min.js"></script>
<script src="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/plugins/toastr/toastr.min.js"></script>
<?php if (!empty($includeDataTables)): ?>
<script src="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/plugins/datatables/jquery.dataTables.min.js"></script>
<script src="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/plugins/datatables-bs4/js/dataTables.bootstrap4.min.js"></script>
<script src="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/plugins/datatables-responsive/js/dataTables.responsive.min.js"></script>
<script src="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/plugins/datatables-responsive/js/responsive.bootstrap4.min.js"></script>
<?php endif; ?>
<script src="<?php echo htmlspecialchars($assetBase); ?>plugins/AdminLTE-3.2.0/dist/js/adminlte.min.js"></script>
<script src="<?php echo htmlspecialchars($assetBase); ?>app-notify.js"></script>
<script src="<?php echo htmlspecialchars($assetBase); ?>theme.js"></script>
