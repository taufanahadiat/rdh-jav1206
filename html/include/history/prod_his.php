<?php
$assetBase = $assetBase ?? '';
$dashboardRollHistoryEndpoint =
  $dashboardRollHistoryEndpoint ?? $assetBase . 'include/history/prod_his_act.php';
$prodHisJsVersion = @filemtime(__DIR__ . '/prod_his.js') ?: time();
$prodHisSection = isset($prodHisSection) ? (string) $prodHisSection : 'history';

if (!defined('PROD_HIS_ASSETS_INCLUDED')) {
  define('PROD_HIS_ASSETS_INCLUDED', true); ?>
<script>
  window.DASHBOARD_ROLL_HISTORY_ENDPOINT = <?php echo json_encode(
    $dashboardRollHistoryEndpoint,
  ); ?>;
</script>
<script src="<?php echo htmlspecialchars(
  $assetBase,
); ?>include/history/prod_his.js?v=<?php echo urlencode(
  (string) $prodHisJsVersion,
); ?>" defer></script>
<?php
}
?>

<?php if ($prodHisSection === 'history'): ?>
    <div class="row">
      <div class="col-12">
        <div class="card card-light card-outline roll-history-card">
          <div class="card-header">Production History</div>
          <div class="card-body">
            <div id="rollHistoryEmpty" class="roll-history-empty d-none">Belum ada data production history.</div>
            <div id="rollHistoryTimelineWrap" class="roll-history-timeline-wrap d-none">
              <div id="rollHistoryTimeline" class="roll-history-timeline" aria-label="Production history timeline"></div>
              <div id="rollHistoryTimeAxis" class="roll-history-axis roll-history-axis-bottom"></div>
            </div>
            <div id="rollHistoryRangeControls" class="roll-history-range-controls d-none">
              <label class="roll-history-range-field">
                <span class="roll-history-range-icon"><i class="far fa-calendar-alt"></i></span>
                <input id="rollHistoryRangeStart" class="roll-history-range-input" type="datetime-local" step="300" aria-label="Production history start date">
              </label>
              <label class="roll-history-range-field">
                <span class="roll-history-range-icon"><i class="far fa-calendar-alt"></i></span>
                <input id="rollHistoryRangeEnd" class="roll-history-range-input" type="datetime-local" step="300" aria-label="Production history end date">
              </label>
            </div>
            <div id="rollHistoryLoading" class="roll-history-loading">Memuat production history...</div>
          </div>
        </div>
      </div>
    </div>
<?php elseif ($prodHisSection === 'detail'): ?>
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
<?php endif; ?>
