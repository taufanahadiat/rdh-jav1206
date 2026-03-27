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
$dashboardRollHistoryEndpoint =
  $dashboardRollHistoryEndpoint ?? $assetBase . 'include/dashboard/roll_history_act.php';
$dashboardJsVersion = @filemtime(__DIR__ . '/dashboard.js') ?: time();
?>
<script>
  window.DASHBOARD_SNAPSHOT_ENDPOINT = <?php echo json_encode($dashboardSnapshotEndpoint); ?>;
  window.DASHBOARD_ROLL_HISTORY_ENDPOINT = <?php echo json_encode(
    $dashboardRollHistoryEndpoint,
  ); ?>;
</script>
<script src="<?php echo htmlspecialchars(
  $assetBase,
); ?>include/dashboard/dashboard.js?v=<?php echo urlencode(
  (string) $dashboardJsVersion,
); ?>" defer></script>

<section class="content">
  <div class="container-fluid">
    <div class="row">
      <div class="col-lg-3 col-6">
        <div class="small-box bg-industrial box-tone-1">
          <div class="inner">
            <h3 id="productName" class="live-data" data-db="DB2.DBB0[50]" data-format="string">PCL-25</h3>
            <p>Product</p>
          </div>
          <div class="icon"><i class="far fa-life-ring fa-spin"></i></div>
        </div>
      </div>

      <div class="col-lg-3 col-6">
        <div class="small-box bg-industrial box-tone-2">
          <div class="inner">
            <h3 class="live-data" data-db="DB325.DBD1498" data-format="float" data-decimal="0">00</h3>
            <p>Line Speed (m/min)</p>
          </div>
          <div class="icon"><i class="fas fa-tachometer-alt"></i></div>
        </div>
      </div>

      <div class="col-lg-3 col-6">
        <div class="small-box bg-industrial box-tone-3">
          <div class="inner">
            <h3 id="outputWinder">0</h3>
            <p>Output On Winder (kg/h)</p>
          </div>
          <div class="icon"><i class="fas fa-weight-hanging"></i></div>
        </div>
      </div>

      <div class="col-lg-3 col-6">
        <div class="small-box bg-industrial box-tone-4">
          <div class="inner">
            <h3 class="live-data" data-db="DB330.DBD3010" data-format="float" data-decimal="0">00</h3>
            <p>Meter Counter (m)</p>
          </div>
          <div class="icon"><i class="fab fa-monero"></i></div>
        </div>
      </div>
    </div>

    <div class="row">
      <div class="col-12">
        <div class="card card-light card-outline roll-history-card">
          <div class="card-header">Roll History</div>
          <div class="card-body">
            <div id="rollHistoryEmpty" class="roll-history-empty d-none">Belum ada data roll history.</div>
            <div id="rollHistoryTimelineWrap" class="roll-history-timeline-wrap d-none">
              <div id="rollHistoryTimeline" class="roll-history-timeline" aria-label="Roll history timeline"></div>
              <div id="rollHistoryTimeAxis" class="roll-history-axis roll-history-axis-bottom"></div>
            </div>
            <div id="rollHistoryRangeControls" class="roll-history-range-controls d-none">
              <label class="roll-history-range-field">
                <span class="roll-history-range-icon"><i class="far fa-calendar-alt"></i></span>
                <input id="rollHistoryRangeStart" class="roll-history-range-input" type="datetime-local" step="300" aria-label="Roll history start date">
              </label>
              <label class="roll-history-range-field">
                <span class="roll-history-range-icon"><i class="far fa-calendar-alt"></i></span>
                <input id="rollHistoryRangeEnd" class="roll-history-range-input" type="datetime-local" step="300" aria-label="Roll history end date">
              </label>
            </div>
            <div id="rollHistoryLoading" class="roll-history-loading">Memuat roll history...</div>
          </div>
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

    <div class="row">
      <div class="col-12">
        <div class="card card-light card-outline roll-detail-card">
          <div class="card-header d-flex flex-wrap justify-content-between align-items-center">
            <span>Roll Detail</span>
            <span id="rollDetailMeta" class="roll-detail-meta">Pilih roll pada timeline.</span>
          </div>
          <div class="card-body">
            <div id="rollDetailSummary" class="roll-detail-summary d-none"></div>
            <div id="rollDetailLoading" class="roll-detail-loading d-none">Memuat detail roll...</div>
            <div id="rollDetailEmpty" class="roll-detail-empty">Klik salah satu roll untuk melihat data `rtagroll`.</div>
            <div id="rollDetailTableWrap" class="table-responsive d-none">
              <table class="table table-bordered table-striped table-sm roll-detail-table mb-0">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>DB ID</th>
                    <th>Address</th>
                    <th>Name</th>
                    <th>Value</th>
                    <th>Timestamp</th>
                  </tr>
                </thead>
                <tbody id="rollDetailTableBody"></tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>
