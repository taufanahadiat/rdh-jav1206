(function ($, window, document) {
  const webConfig = window.WEB_CONFIG || {};
  const DENSITY_G_CM3 = 0.91;
  const $liveNodes = $('.live-data[data-db]');
  const nodesByTag = {};
  const tags = [];
  const tagValues = {};
  const snapshotEndpoint =
    window.DASHBOARD_SNAPSHOT_ENDPOINT ||
    webConfig.dashboard_snapshot_endpoint ||
    '/include/dashboard/plc/dashboard-snapshot/';
  const REQUEST_TIMEOUT_MS = Number(webConfig.dashboard_request_timeout_ms) || 6000;
  const POLL_INTERVAL_MS = Number(webConfig.dashboard_poll_interval_ms) || 1000;
  const HIDDEN_POLL_INTERVAL_MS = Number(webConfig.dashboard_hidden_poll_interval_ms) || 3000;

  let isFetching = false;
  let pollTimer = null;
  let currentRequest = null;
  let lastErrorMessage = '';

  function normalizeTag(tag) {
    return String(tag || '')
      .replace(/\s+/g, '')
      .toUpperCase();
  }

  function toNum(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }

  function isTruthy(v) {
    if (v === true) return true;
    if (typeof v === 'number') return v === 1;
    if (typeof v === 'string') {
      const s = v.trim().toLowerCase();
      return s === '1' || s === 'true' || s === 'on' || s === 'yes';
    }
    return false;
  }

  function fmtInt(v) {
    return Math.round(toNum(v)).toLocaleString('en-US');
  }

  function formatValueForNode(rawValue, $node) {
    const format = String($node.attr('data-format') || 'auto').toLowerCase();
    const decimal = Number.parseInt($node.attr('data-decimal') || '2', 10);

    if (format === 'bool') {
      const onText = $node.attr('data-true') || 'ON';
      const offText = $node.attr('data-false') || 'OFF';
      return isTruthy(rawValue) ? onText : offText;
    }

    if (format === 'int') {
      return fmtInt(rawValue);
    }

    if (format === 'float') {
      const digits = Number.isInteger(decimal) && decimal >= 0 ? decimal : 2;
      return toNum(rawValue).toFixed(digits);
    }

    if (format === 'string') {
      if (rawValue === null || rawValue === undefined) return '-';
      return String(rawValue);
    }

    if (rawValue === null || rawValue === undefined) {
      return '-';
    }

    return String(rawValue);
  }

  function updateLiveNodes(values) {
    Object.keys(nodesByTag).forEach(function (tag) {
      const rawValue = Object.prototype.hasOwnProperty.call(values, tag) ? values[tag] : null;
      nodesByTag[tag].forEach(function ($node) {
        $node.text(formatValueForNode(rawValue, $node));
      });
    });
  }

  function updateDerivedValues(values) {
    const lineSpeed = toNum(values['DB325.DBD1498']);
    const thicknessUm = toNum(values['DB326.DBD2716']);
    const webWidthMm = toNum(values['DB326.DBD2720']);
    const meterSet = toNum(values['DB330.DBD3006']);
    const meterCounter = toNum(values['DB330.DBD3010']);

    const meterRemaining = Math.max(0, meterSet - meterCounter);
    const progressPct =
      meterSet > 0 ? Math.min(100, Math.max(0, (meterCounter / meterSet) * 100)) : 0;
    const densityKgM3 = DENSITY_G_CM3 * 1000;
    const massKg = thicknessUm * 1e-6 * (webWidthMm * 1e-3) * meterCounter * densityKgM3;
    const lineSpeedMh = lineSpeed * 60;
    const estimatedHours = lineSpeedMh > 0 && meterCounter > 0 ? meterCounter / lineSpeedMh : 0;
    const outputWinder = estimatedHours > 0 ? massKg / estimatedHours : 0;

    $('#outputRemainingM').text(fmtInt(meterRemaining));
    $('#outputProgressBar').css('width', progressPct.toFixed(1) + '%');
    $('#outputProgressBar').attr('aria-valuenow', progressPct.toFixed(1));
    $('#outputWinder').text(outputWinder.toFixed(0));
  }

  function showBackendError(msg) {
    const message = msg || 'An error occurred while reading live data.';
    if (message === lastErrorMessage) {
      return;
    }

    lastErrorMessage = message;
    if (window.AppNotify && window.AppNotify.backend) {
      window.AppNotify.backend.error(message, {
        key: 'dashboard-live-error',
        cooldown: 5000,
        options: {
          toast: true,
          position: 'top-end',
        },
      });
    }
  }

  function showFrontendError(msg) {
    const message = msg || 'A frontend error occurred.';
    if (window.AppNotify && window.AppNotify.frontend) {
      window.AppNotify.frontend.error(message, {
        key: 'dashboard-frontend-error',
        cooldown: 5000,
      });
    }
  }

  function clearError() {
    lastErrorMessage = '';
  }

  function scheduleNext(ms) {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(fetchInbox, ms);
  }

  function fetchInbox() {
    if (!tags.length) {
      showFrontendError('No `.live-data` elements with a `data-db` attribute were found.');
      return;
    }

    if (document.hidden) {
      scheduleNext(HIDDEN_POLL_INTERVAL_MS);
      return;
    }

    if (isFetching) {
      scheduleNext(POLL_INTERVAL_MS);
      return;
    }

    isFetching = true;

    const requestUrl = new URL(snapshotEndpoint, window.location.href);
    tags.forEach(function (tag) {
      requestUrl.searchParams.append('tag', tag);
    });
    requestUrl.searchParams.set('direct_read_missing', '1');

    currentRequest = $.ajax({
      url: requestUrl.toString(),
      method: 'GET',
      dataType: 'json',
      timeout: REQUEST_TIMEOUT_MS,
      cache: false,
    });

    currentRequest.done(function (res) {
      if (!res || !res.ok) {
        showBackendError(res && res.message ? res.message : 'The server response is invalid.');
        return;
      }

      const values =
        res && res.tag_values && typeof res.tag_values === 'object' ? res.tag_values : {};
      if (Object.keys(values).length === 0) {
        showBackendError('Tidak ada data yang diterima. Periksa koneksi PLC dan konfigurasi tag.');
      }

      Object.keys(values).forEach(function (tag) {
        tagValues[normalizeTag(tag)] = values[tag];
      });

      updateLiveNodes(tagValues);
      updateDerivedValues(tagValues);
      clearError();
    });

    currentRequest.fail(function (xhr, status) {
      if (status === 'abort') return;

      const msg =
        xhr && xhr.responseJSON && (xhr.responseJSON.message || xhr.responseJSON.detail)
          ? xhr.responseJSON.message || xhr.responseJSON.detail
          : 'Failed to connect to the live inbox endpoint.';
      showBackendError(msg);
    });

    currentRequest.always(function () {
      isFetching = false;
      currentRequest = null;
      scheduleNext(POLL_INTERVAL_MS);
    });
  }

  $liveNodes.each(function () {
    const $node = $(this);
    const tag = normalizeTag($node.attr('data-db'));
    if (!tag) return;

    if (!nodesByTag[tag]) {
      nodesByTag[tag] = [];
      tags.push(tag);
    }

    nodesByTag[tag].push($node);
  });

  $(document).on('visibilitychange', function () {
    if (document.hidden) {
      if (currentRequest) {
        currentRequest.abort();
      }
      clearTimeout(pollTimer);
    } else {
      fetchInbox();
    }
  });

  fetchInbox();
})(window.jQuery, window, document);
