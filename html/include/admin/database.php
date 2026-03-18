<?php
$assetBase = $assetBase ?? '';
$selectedValue = isset($_GET['table']) ? trim((string) $_GET['table']) : '';
$ajaxEndpoint = $ajaxEndpoint ?? ($assetBase . 'include/admin/db_act.php');
?>

<script>
  window.DATABASE_PAGE_CONFIG = {
    endpoint: <?php echo json_encode($ajaxEndpoint); ?>,
    initialTable: <?php echo json_encode($selectedValue); ?>,
    dblistTable: 'public.dblist'
  };
</script>
<script src="<?php echo htmlspecialchars($assetBase); ?>include/admin/database.js" defer></script>

<section class="content-header">
  <div class="container-fluid">
    <div class="row mb-2">
      <div class="col-sm-6">
        <h1>Database</h1>
      </div>
    </div>
  </div>
</section>

<section class="content">
  <div class="container-fluid">
    <div class="card">
      <div class="card-header">
        <strong id="database-name">PostgreSQL</strong>
      </div>
      <div class="card-body">
        <div class="form-row align-items-end mb-3">
          <div class="col-md-5">
            <label for="table">Table</label>
            <select id="table" class="form-control" disabled>
              <option value="">Loading table list...</option>
            </select>
          </div>
          <div class="col-md-2">
            <label for="row-limit">Max Rows</label>
            <select id="row-limit" class="form-control">
              <option value="500">500</option>
              <option value="1000">1000</option>
              <option value="5000">5000</option>
              <option value="10000">10000</option>
              <option value="all">All</option>
            </select>
          </div>
          <div class="col-md-auto mt-3 mt-md-0">
            <button type="button" id="reload-table" class="btn btn-primary">Reload</button>
          </div>
          <div class="col-md-auto mt-3 mt-md-0">
            <button type="button" id="toggle-bind-related" class="btn btn-info" disabled>Bind DB</button>
          </div>
          <div class="col-md-auto mt-3 mt-md-0">
            <button type="button" id="import-dblist" class="btn btn-success" disabled>Re-import dblist</button>
          </div>
        </div>

        <p class="mb-2" id="database-summary">
          Loading data...
        </p>

        <div class="table-responsive" id="database-table-wrapper">
          <table id="database-table" class="table table-bordered table-striped table-sm w-100">
            <thead></thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</section>
