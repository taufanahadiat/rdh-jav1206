<section class="content-header">
  <div class="container-fluid">
    <div class="row mb-2">
      <div class="col-sm-6">
      </div>
    </div>
  </div>
</section>
<?php
$assetBase = $assetBase ?? '';
$dashboardSnapshotEndpoint = $dashboardSnapshotEndpoint ?? '/plc/dashboard-snapshot/';
$dashboardJsVersion = @filemtime(__DIR__ . '/dashboard.js') ?: time();
?>
<script>
  window.DASHBOARD_SNAPSHOT_ENDPOINT = <?php echo json_encode($dashboardSnapshotEndpoint); ?>;
</script>
<script src="<?php echo htmlspecialchars(
  $assetBase,
); ?>include/dashboard/dashboard.js?v=<?php echo urlencode((string) $dashboardJsVersion); ?>" defer></script>

<section class="content">
  <div class="container-fluid">
    <div class="row">
      <div class="col-lg-3 col-6">
        <div class="small-box bg-industrial">
          <div class="inner">
            <h3 id="productName" class="live-data" data-db="DB2.DBB0[50]" data-format="string">PCL-25</h3>
            <p>Product</p>
          </div>
          <div class="icon"><i class="far fa-life-ring fa-spin"></i></div>
        </div>
      </div>

      <div class="col-lg-3 col-6">
        <div class="small-box bg-industrial">
          <div class="inner">
            <h3 class="live-data" data-db="DB325.DBD1498" data-format="float" data-decimal="0">00</h3>
            <p>Line Speed (m/min)</p>
          </div>
          <div class="icon"><i class="fas fa-tachometer-alt"></i></div>
        </div>
      </div>

      <div class="col-lg-3 col-6">
        <div class="small-box bg-industrial">
          <div class="inner">
            <h3 id="outputWinder">0</h3>
            <p>Output On Winder (kg/h)</p>
          </div>
          <div class="icon"><i class="fas fa-weight-hanging"></i></div>
        </div>
      </div>

      <div class="col-lg-3 col-6">
        <div class="small-box bg-industrial">
          <div class="inner">
            <h3 class="live-data" data-db="DB330.DBD3010" data-format="float" data-decimal="0">00</h3>
            <p>Meter Counter (m)</p>
          </div>
          <div class="icon"><i class="fab fa-monero"></i></div>
        </div>
      </div>
    </div>

    <div class="row">
      <div class="col-lg-6">
        <div class="card card-light card-outline product-detail-card">
          <div class="card-header text-uppercase">Product</div>
          <div class="card-body">
            <div class="product-code"><i class="fas fa-tag mr-2"></i><span id="productCode" class="live-data" data-db="DB2.DBB0[50]" data-format="string">PCL-25</span></div>
            <p class="detail-label mb-3">Product</p>
            <div class="row">
              <div class="col-sm-6">
                <div class="detail-item">
                  <div class="detail-value">+ <span class="live-data" data-db="DB326.DBD2716" data-format="float" data-decimal="2">0.00</span> &mu;m</div>
                  <p class="detail-label">Thickness</p>
                </div>
                <div class="detail-item">
                  <div class="detail-value-sm"><i class="fas fa-sun mr-1"></i><span class="live-data" data-db="DB326.DBX3666.2" data-format="bool" data-true="Corona" data-false="None">None</span></div>
                  <p class="detail-label">Treatment inside</p>
                </div>
                <div class="detail-item mb-0">
                  <div class="detail-value-sm"><i class="fas fa-sun mr-1"></i><span class="live-data" data-db="DB326.DBX3822.2" data-format="bool" data-true="Corona" data-false="None">None</span></div>
                  <p class="detail-label">Treatment outside</p>
                </div>
              </div>
              <div class="col-sm-6">
                <div class="detail-item">
                  <div class="detail-value-sm">0.91 g/cm&sup3;</div>
                  <p class="detail-label">Density</p>
                </div>
                <div class="detail-item">
                  <div class="detail-value-sm"><i class="far fa-file-alt mr-1"></i><span id="recipeValue" class="live-data" data-db="DB2.DBB52[50]" data-format="string">PCL-25-25-50 TEST</span></div>
                  <p class="detail-label">Recipe</p>
                </div>
                <div class="detail-item mb-0">
                  <div class="detail-value-sm"><i class="fas fa-flag mr-1 text-success"></i><span id="campaignValue" class="live-data" data-db="DB2.DBB104[50]" data-format="string">PCL25_7107_10620900</span></div>
                  <p class="detail-label">Campaign</p>
                </div>
              </div>
            </div>
            <span class="live-data d-none" data-db="DB326.DBD2720" data-format="float" data-decimal="2">0.00</span>
          </div>
        </div>
      </div>

      <div class="col-lg-6">
        <div class="card card-light card-outline output-card">
          <div class="card-header">Output</div>
          <div class="card-body">
            <div class="row align-items-start">
              <div class="col-sm-5">
                <div class="output-roll">
                  <i class="fas fa-battery-full"></i>
                  <span>Roll</span>
                </div>
              </div>
              <div class="col-sm-7">
                <div class="output-minutes"><span class="live-data" data-db="DB330.DBD3018" data-format="int">0</span><small> min</small></div>
                <div class="output-remaining">
                  <div class="output-remaining-value"><span id="outputRemainingM">0</span><small> m</small></div>
                  <div class="output-remaining-label">Remaining</div>
                </div>
              </div>
            </div>
            <div class="progress output-progress">
              <div id="outputProgressBar" class="progress-bar" role="progressbar" style="width: 0%"></div>
            </div>
            <div class="output-progress-text">
              <span class="live-data" data-db="DB330.DBD3010" data-format="int">0</span> / <span class="live-data" data-db="DB330.DBD3006" data-format="int">0</span> m
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>
