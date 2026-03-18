(function ($, window, document) {
  if (!$ || !$.fn || !$.fn.DataTable) {
    return;
  }

  const config = window.DATABASE_PAGE_CONFIG || {};
  const endpoint = config.endpoint || '../include/admin/db_act.php';
  const dblistTable = config.dblistTable || 'public.dblist';
  const initialTable = config.initialTable || '';
  const initialUrl = new URL(window.location.href);
  const initialBindRelated = ['1', 'true', 'yes', 'on', 'related'].indexOf((initialUrl.searchParams.get('bind') || '').trim().toLowerCase()) !== -1;

  let initialLimit = (initialUrl.searchParams.get('limit') || '').trim().toLowerCase();
  const initialOrderBy = (initialUrl.searchParams.get('order_by') || '').trim();
  const initialOrderDir = (initialUrl.searchParams.get('order_dir') || 'asc').trim().toLowerCase() === 'desc' ? 'desc' : 'asc';

  if (['500', '1000', '5000', '10000', 'all'].indexOf(initialLimit) === -1) {
    initialLimit = '';
  }

  const $tableSelect = $('#table');
  const $rowLimitSelect = $('#row-limit');
  const $reloadButton = $('#reload-table');
  const $bindButton = $('#toggle-bind-related');
  const $importButton = $('#import-dblist');
  const $summary = $('#database-summary');
  const $dbName = $('#database-name');
  const $tableWrapper = $('#database-table-wrapper');
  let $table = $('#database-table');
  let dataTableInstance = null;
  let currentTable = initialTable;
  let selectedLimit = initialLimit;
  let currentSortColumn = initialOrderBy;
  let currentSortDirection = initialOrderDir;
  let pendingAlertMessage = '';
  let pendingAlertType = 'success';
  let bindRelated = initialBindRelated;
  let bindAvailable = false;

  function assignOptionDefaults(options) {
    const mergedOptions = $.extend(true, {}, options || {});
    if (!mergedOptions.options) {
      mergedOptions.options = {};
    }
    if (typeof mergedOptions.options.toast !== 'boolean') {
      mergedOptions.options.toast = true;
    }
    if (!mergedOptions.options.position) {
      mergedOptions.options.position = 'top-end';
    }
    return mergedOptions;
  }

  function notify(message, type, options) {
    if (!message || !window.AppNotify || !window.AppNotify.backend) {
      return;
    }

    return window.AppNotify.backend.show(type || 'info', message, assignOptionDefaults(options || {}));
  }

  function syncImportButton(isLoading, selectedTable) {
    const hasDblist = $tableSelect.find('option[value="' + dblistTable + '"]').length > 0;
    const canImport = !isLoading && hasDblist && (selectedTable || currentTable) === dblistTable;
    $importButton.prop('disabled', !canImport);
  }

  function syncBindButton(isLoading) {
    const canBind = !isLoading && bindAvailable;
    $bindButton
      .prop('disabled', !canBind)
      .toggleClass('btn-info', !bindRelated || !bindAvailable)
      .toggleClass('btn-warning', bindRelated && bindAvailable)
      .text(bindRelated && bindAvailable ? 'Unbind DB' : 'Bind DB');
  }

  function setLoadingState(isLoading) {
    $tableSelect.prop('disabled', isLoading);
    $rowLimitSelect.prop('disabled', isLoading);
    $reloadButton.prop('disabled', isLoading);
    syncImportButton(isLoading, $tableSelect.val());
    syncBindButton(isLoading);
    if (isLoading) {
      $summary.text('Loading data...');
    }
  }

  function updateLimitSelection(limitValue) {
    let normalized = limitValue || 'all';
    if ($rowLimitSelect.find('option[value="' + normalized + '"]').length === 0) {
      normalized = 'all';
    }
    $rowLimitSelect.val(normalized);
  }

  function fillTableOptions(tables, selectedTable) {
    const hasTables = Array.isArray(tables) && tables.length > 0;
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
    const tableColumns = [];
    const headerRow = $('<tr></tr>');
    const normalizedRows = Array.isArray(rows) ? rows : [];
    let initialOrder = [];
    let $thead;
    let $tbody;

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
      headerRow.append(
        $('<th></th>')
          .attr('data-column', columnName)
          .attr('title', 'Sort by column')
          .text(columnName)
      );
      tableColumns.push({
        data: columnName,
        name: columnName,
        title: columnName,
        defaultContent: ''
      });
    });
    $thead.append(headerRow);

    if (sortColumn) {
      $.each(tableColumns, function (index, columnConfig) {
        if (columnConfig.data === sortColumn) {
          initialOrder = [[index, sortDirection === 'desc' ? 'desc' : 'asc']];
          return false;
        }
      });
    }

    dataTableInstance = $table.DataTable({
      data: normalizedRows,
      columns: tableColumns,
      responsive: false,
      autoWidth: false,
      deferRender: true,
      scrollX: true,
      ordering: true,
      orderMulti: false,
      order: initialOrder,
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

    dataTableInstance.on('order.dt', function () {
      const orderedColumns = dataTableInstance.order();
      if (!Array.isArray(orderedColumns) || !orderedColumns.length) {
        return;
      }

      const orderedColumn = orderedColumns[0];
      const columnIndex = Array.isArray(orderedColumn) ? orderedColumn[0] : -1;
      const nextDirection = Array.isArray(orderedColumn) && orderedColumn[1] === 'desc' ? 'desc' : 'asc';
      const nextColumn = tableColumns[columnIndex] ? tableColumns[columnIndex].data : '';

      if (!nextColumn || (currentSortColumn === nextColumn && currentSortDirection === nextDirection)) {
        return;
      }

      currentSortColumn = nextColumn;
      currentSortDirection = nextDirection;
      loadTable(currentTable || $tableSelect.val() || initialTable);
    });
  }

  function updateSummary(payload) {
    if (!payload || !payload.selected_table) {
      $summary.text('No tables are available.');
      return;
    }

    const effectiveLimit = payload.row_limit_value === 'all' ? 'All' : (payload.row_limit_value || 'All');
    const bindModeText = payload.bind_enabled ? 'Bound' : 'Raw';
    $summary.empty()
      .append(document.createTextNode('Total tables: '))
      .append($('<strong></strong>').text(payload.tables ? payload.tables.length : 0))
      .append(document.createTextNode(' | Showing: '))
      .append($('<strong></strong>').text(payload.selected_table))
      .append(document.createTextNode(' | View: '))
      .append($('<strong></strong>').text(bindModeText))
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

    const url = new URL(window.location.href);
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

    if (bindRelated) {
      url.searchParams.set('bind', 'related');
    } else {
      url.searchParams.delete('bind');
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
        const requestData = {};
        if (tableName) {
          requestData.table = tableName;
        }
        if (selectedLimit) {
          requestData.limit = selectedLimit;
        }
        if (bindRelated) {
          requestData.bind = 'related';
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
        bindAvailable = !!response.bind_available;
        bindRelated = !!response.bind_enabled;
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
        let message = 'Failed to load table data.';
        if (xhr && xhr.responseJSON && xhr.responseJSON.message) {
          message = xhr.responseJSON.message;
        }

        fillTableOptions([], '');
        renderGrid([], [], '', 'asc');
        $summary.text('Failed to load data.');
        bindAvailable = false;
        bindRelated = false;
        notify(message, 'error');
      })
      .always(function () {
        setLoadingState(false);
      });
  }

  function renderPreviewText(preview) {
    const summary = preview && preview.summary ? preview.summary : {};
    const examples = preview && preview.examples ? preview.examples : {};
    const parts = [
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
        let message = 'Failed to re-import dblist.';
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

  $bindButton.on('click', function () {
    if (!bindAvailable || $bindButton.prop('disabled')) {
      return;
    }

    bindRelated = !bindRelated;
    currentSortColumn = '';
    currentSortDirection = 'asc';
    loadTable($tableSelect.val() || currentTable || initialTable);
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
        let message = 'Failed to preview the dblist import.';
        if (xhr && xhr.responseJSON && xhr.responseJSON.message) {
          message = xhr.responseJSON.message;
        }
        notify(message, 'error');
        setLoadingState(false);
      });
  });

  loadTable(initialTable);
})(window.jQuery, window, document);
