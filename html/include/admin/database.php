<?php
$selectedValue = isset($_GET['table']) ? trim((string) $_GET['table']) : '';
$ajaxEndpoint = '../include/admin/db_act.php';
?>

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
            <button type="button" id="import-dblist" class="btn btn-success" disabled>Re-import AWL to dblist</button>
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

<script>
  document.addEventListener('DOMContentLoaded', function () {
    (function ($) {
      if (!$ || !$.fn || !$.fn.DataTable) {
        return;
      }

      var endpoint = <?php echo json_encode($ajaxEndpoint); ?>;
      var dblistTable = 'public.dblist';
      var initialTable = <?php echo json_encode($selectedValue); ?>;
      var initialUrl = new URL(window.location.href);
      var initialLimit = (initialUrl.searchParams.get('limit') || '').trim().toLowerCase();
      var initialOrderBy = (initialUrl.searchParams.get('order_by') || '').trim();
      var initialOrderDir = (initialUrl.searchParams.get('order_dir') || 'asc').trim().toLowerCase() === 'desc' ? 'desc' : 'asc';
      if (['500', '1000', '5000', '10000', 'all'].indexOf(initialLimit) === -1) {
        initialLimit = '';
      }
      var $tableSelect = $('#table');
      var $rowLimitSelect = $('#row-limit');
      var $reloadButton = $('#reload-table');
      var $importButton = $('#import-dblist');
      var $summary = $('#database-summary');
      var $dbName = $('#database-name');
      var $tableWrapper = $('#database-table-wrapper');
      var $table = $('#database-table');
      var dataTableInstance = null;
      var currentTable = initialTable || '';
      var selectedLimit = initialLimit;
      var currentSortColumn = initialOrderBy;
      var currentSortDirection = initialOrderDir;
      var pendingAlertMessage = '';
      var pendingAlertType = 'success';

      function notify(message, type, options) {
        if (!message || !window.AppNotify || !window.AppNotify.backend) {
          return;
        }

        return window.AppNotify.backend.show(type || 'info', message, assignOptionDefaults(options || {}));
      }

      function assignOptionDefaults(options) {
        var config = $.extend(true, {}, options || {});
        if (!config.options) {
          config.options = {};
        }
        if (typeof config.options.toast !== 'boolean') {
          config.options.toast = true;
        }
        if (!config.options.position) {
          config.options.position = 'top-end';
        }
        return config;
      }

      function syncImportButton(isLoading, selectedTable) {
        var hasDblist = $tableSelect.find('option[value="' + dblistTable + '"]').length > 0;
        var canImport = !isLoading && hasDblist && (selectedTable || currentTable) === dblistTable;
        $importButton.prop('disabled', !canImport);
      }

      function setLoadingState(isLoading) {
        $tableSelect.prop('disabled', isLoading);
        $rowLimitSelect.prop('disabled', isLoading);
        $reloadButton.prop('disabled', isLoading);
        syncImportButton(isLoading, $tableSelect.val());
        if (isLoading) {
          $summary.text('Loading data...');
        }
      }

      function updateLimitSelection(limitValue) {
        var normalized = limitValue || 'all';
        if ($rowLimitSelect.find('option[value="' + normalized + '"]').length === 0) {
          normalized = 'all';
        }
        $rowLimitSelect.val(normalized);
      }

      function fillTableOptions(tables, selectedTable) {
        var hasTables = Array.isArray(tables) && tables.length > 0;
        $tableSelect.empty();

        if (!hasTables) {
          $tableSelect
            .append($('<option>', { value: '', text: 'No tables available' }))
            .prop('disabled', true);
          return;
        }

        $.each(tables, function (_, item) {
          $tableSelect.append(
            $('<option>', {
              value: item.value,
              text: item.label,
              selected: item.value === selectedTable
            })
          );
        });

        $tableSelect.prop('disabled', false);
        syncImportButton(false, selectedTable);
      }

      function renderGrid(columns, rows, sortColumn, sortDirection) {
        var tableColumns = [];
        var headerRow = $('<tr></tr>');
        var normalizedRows = Array.isArray(rows) ? rows : [];
        var $thead;
        var $tbody;

        if (dataTableInstance) {
          dataTableInstance.destroy(true);
          dataTableInstance = null;
        }

        $tableWrapper.empty();
        $table = $(
          '<table id="database-table" class="table table-bordered table-striped table-sm w-100">' +
            '<thead></thead>' +
            '<tbody></tbody>' +
          '</table>'
        );
        $tableWrapper.append($table);
        $thead = $table.find('thead');
        $tbody = $table.find('tbody');

        if (!Array.isArray(columns) || columns.length === 0) {
          $thead.append('<tr><th>Data</th></tr>');
          $tbody.append('<tr><td class="text-center">No columns were found.</td></tr>');
          return;
        }

        $.each(columns, function (_, columnName) {
          var label = columnName;
          if (sortColumn && sortColumn === columnName) {
            label += sortDirection === 'desc' ? ' ▼' : ' ▲';
          }

          headerRow.append(
            $('<th></th>')
              .attr('data-column', columnName)
              .attr('title', 'Sort from database')
              .css('cursor', 'pointer')
              .text(label)
          );
          tableColumns.push({
            data: columnName,
            title: columnName,
            defaultContent: ''
          });
        });
        $thead.append(headerRow);

        dataTableInstance = $table.DataTable({
          data: normalizedRows,
          columns: tableColumns,
          responsive: false,
          autoWidth: false,
          deferRender: true,
          scrollX: true,
          ordering: false,
          pageLength: 25,
          lengthMenu: [[10, 25, 50, 100, -1], [10, 25, 50, 100, 'All']],
          language: {
            search: 'Search:',
            lengthMenu: 'Show _MENU_ rows',
            info: 'Showing _START_ to _END_ of _TOTAL_ rows',
            infoEmpty: 'No data available',
            zeroRecords: 'No matching records found',
            emptyTable: 'No data available',
            paginate: {
              first: 'First',
              last: 'Last',
              next: 'Next',
              previous: 'Previous'
            }
          }
        });

        $table.find('thead').off('click', 'th').on('click', 'th', function () {
          var nextColumn = $(this).attr('data-column') || '';
          if (!nextColumn) {
            return;
          }

          if (currentSortColumn === nextColumn) {
            currentSortDirection = currentSortDirection === 'asc' ? 'desc' : 'asc';
          } else {
            currentSortColumn = nextColumn;
            currentSortDirection = 'asc';
          }

          loadTable(currentTable || $tableSelect.val() || initialTable);
        });
      }

      function updateSummary(payload) {
        if (!payload || !payload.selected_table) {
          $summary.text('No tables are available.');
          return;
        }

        var effectiveLimit = payload.row_limit_value === 'all' ? 'All' : (payload.row_limit_value || 'All');
        $summary.empty()
          .append(document.createTextNode('Total tables: '))
          .append($('<strong></strong>').text(payload.tables ? payload.tables.length : 0))
          .append(document.createTextNode(' | Showing: '))
          .append($('<strong></strong>').text(payload.selected_table))
          .append(document.createTextNode(' | Total rows: '))
          .append($('<strong></strong>').text(payload.row_count || 0))
          .append(document.createTextNode(' | Loaded: '))
          .append($('<strong></strong>').text(payload.returned_row_count || 0))
          .append(document.createTextNode(' (max ' + effectiveLimit + ')'));
      }

      function syncUrl(selectedTable) {
        if (!window.history || !window.history.replaceState) {
          return;
        }

        var url = new URL(window.location.href);
        url.searchParams.set('id', 'database');

        if (selectedTable) {
          url.searchParams.set('table', selectedTable);
        } else {
          url.searchParams.delete('table');
        }

        if (selectedLimit) {
          url.searchParams.set('limit', selectedLimit);
        } else {
          url.searchParams.delete('limit');
        }

        if (currentSortColumn) {
          url.searchParams.set('order_by', currentSortColumn);
          url.searchParams.set('order_dir', currentSortDirection);
        } else {
          url.searchParams.delete('order_by');
          url.searchParams.delete('order_dir');
        }

        window.history.replaceState({}, '', url.toString());
      }

      function loadTable(tableName) {
        setLoadingState(true);
        $.ajax({
          url: endpoint,
          method: 'GET',
          dataType: 'json',
          data: (function () {
            var requestData = {};
            if (tableName) {
              requestData.table = tableName;
            }
            if (selectedLimit) {
              requestData.limit = selectedLimit;
            }
            if (currentSortColumn) {
              requestData.order_by = currentSortColumn;
              requestData.order_dir = currentSortDirection;
            }
            return requestData;
          })()
        })
          .done(function (response) {
            if (!response || !response.ok) {
              notify(response && response.message ? response.message : 'Failed to load table data.', 'error');
              return;
            }

            $dbName.text('PostgreSQL: ' + (response.db_name || ''));
            fillTableOptions(response.tables || [], response.selected_table || '');
            currentSortColumn = response.order_by || '';
            currentSortDirection = response.order_dir || 'asc';
            updateLimitSelection(response.row_limit_value || 'all');
            renderGrid(response.columns || [], response.rows || [], currentSortColumn, currentSortDirection);
            updateSummary(response);
            currentTable = response.selected_table || '';
            syncUrl(response.selected_table || '');
            if (pendingAlertMessage) {
              notify(pendingAlertMessage, pendingAlertType);
              pendingAlertMessage = '';
              pendingAlertType = 'success';
            }
          })
          .fail(function (xhr) {
            var message = 'Failed to load table data.';
            if (xhr && xhr.responseJSON && xhr.responseJSON.message) {
              message = xhr.responseJSON.message;
            }

            fillTableOptions([], '');
            renderGrid([], [], '', 'asc');
            $summary.text('Failed to load data.');
            notify(message, 'error');
          })
          .always(function () {
            setLoadingState(false);
          });
      }

      function renderPreviewText(preview) {
        var summary = preview && preview.summary ? preview.summary : {};
        var examples = preview && preview.examples ? preview.examples : {};
        var parts = [
          'Changes were detected between the new AWL file and the current dblist.',
          '',
          'Address conflicts: ' + (summary.address_conflicts || 0),
          'Name conflicts: ' + (summary.name_conflicts || 0),
          'New rows: ' + (summary.new_rows || 0),
          'Removed source rows: ' + (summary.removed_rows || 0)
        ];

        if (examples.address_conflicts && examples.address_conflicts.length) {
          parts.push('', 'Address conflict examples:');
          $.each(examples.address_conflicts, function (_, item) {
            parts.push(
              '- ' + item.address + ' | Old: DB' + item.old_dbsym + ' / ' + item.old_name + ' / ' + item.old_type +
              ' | New: DB' + item.new_dbsym + ' / ' + item.new_name + ' / ' + item.new_type
            );
          });
        }

        if (examples.name_conflicts && examples.name_conflicts.length) {
          parts.push('', 'Name conflict examples:');
          $.each(examples.name_conflicts, function (_, item) {
            parts.push(
              '- DB' + item.dbsym + ' / ' + item.name +
              ' | Old: ' + item.old_address + ' / ' + item.old_type +
              ' | New: ' + item.new_address + ' / ' + item.new_type
            );
          });
        }

        parts.push('', 'Continue with the re-import?');
        return parts.join('\n');
      }

      function runImport() {
        setLoadingState(true);
        notify('Re-importing dblist from the AWL file...', 'info');

        $.ajax({
          url: endpoint,
          method: 'POST',
          dataType: 'json',
          data: { action: 'reimport_dblist' }
        })
          .done(function (response) {
            if (!response || !response.ok) {
              notify(response && response.message ? response.message : 'Failed to re-import dblist.', 'error');
              return;
            }

            currentTable = response.selected_table || dblistTable;
            pendingAlertMessage = response.message || 'The dblist import has finished.';
            pendingAlertType = 'success';
            loadTable(currentTable);
          })
          .fail(function (xhr) {
            var message = 'Failed to re-import dblist.';
            if (xhr && xhr.responseJSON && xhr.responseJSON.message) {
              message = xhr.responseJSON.message;
            }
            notify(message, 'error');
            setLoadingState(false);
          });
      }

      $tableSelect.on('change', function () {
        currentSortColumn = '';
        currentSortDirection = 'asc';
        loadTable($(this).val());
      });

      $rowLimitSelect.on('change', function () {
        selectedLimit = $(this).val() || 'all';
        loadTable($tableSelect.val() || currentTable || initialTable);
      });

      $reloadButton.on('click', function () {
        loadTable($tableSelect.val() || initialTable);
      });

      $importButton.on('click', function () {
        if (($tableSelect.val() || currentTable) !== dblistTable) {
          return;
        }

        setLoadingState(true);
        notify('Checking AWL changes against dblist...', 'info');

        $.ajax({
          url: endpoint,
          method: 'POST',
          dataType: 'json',
          data: { action: 'preview_reimport_dblist' }
        })
          .done(function (response) {
            if (!response || !response.ok) {
              notify(response && response.message ? response.message : 'Failed to preview the dblist import.', 'error');
              setLoadingState(false);
              return;
            }

            if (!response.preview || !response.preview.has_shift) {
              notify(response.message || 'No changes were detected. Starting the import...', 'success');
              runImport();
              return;
            }

            setLoadingState(false);
            notify(response.message || 'Changes were detected before import.', 'warning');
            if (!window.AppNotify || !window.AppNotify.backend) {
              if (window.confirm(renderPreviewText(response.preview))) {
                runImport();
              }
              return;
            }

            window.AppNotify.backend.question(renderPreviewText(response.preview), {
              title: 'Changes detected',
              autohide: false,
              options: {
                toast: false,
                width: 760,
                showCancelButton: true,
                confirmButtonText: 'Continue re-import',
                cancelButtonText: 'Cancel'
              }
            }).then(function (result) {
              if (result && result.isConfirmed) {
                runImport();
              }
            });
          })
          .fail(function (xhr) {
            var message = 'Failed to preview the dblist import.';
            if (xhr && xhr.responseJSON && xhr.responseJSON.message) {
              message = xhr.responseJSON.message;
            }
            notify(message, 'error');
            setLoadingState(false);
          });
      });

      loadTable(initialTable);
    })(window.jQuery);
  });
</script>
