(function ($, window, document) {
  const webConfig = window.WEB_CONFIG || {};
  const rollHistoryEndpoint =
    window.DASHBOARD_ROLL_HISTORY_ENDPOINT || '/include/history/prod_his_act.php';
  const ROLL_HISTORY_REFRESH_MS = Number(webConfig.history_refresh_ms) || 30000;
  const HISTORY_REQUEST_TIMEOUT_MS = Number(webConfig.history_request_timeout_ms) || 8000;
  const TIMELINE_TICK_MINUTES = 5;
  const TIMELINE_LABEL_INTERVAL_MINUTES = 60;
  const TIMELINE_INLINE_TEXT_MIN_WIDTH = 110;
  const DEFAULT_TIMELINE_RANGE_HOURS = 12;

  let rollHistoryTimer = null;
  let isFetchingRollHistory = false;
  let currentRollHistoryRequest = null;
  let currentRollDetailRequest = null;
  let selectedRollId = null;
  let rollItems = [];
  let lastRenderedRollHistorySignature = '';
  let lastRenderedRollDetailSignature = '';
  let $rollHistoryHoverTooltip = null;
  let rollHistoryRangeStartMs = Number.NaN;
  let rollHistoryRangeEndMs = Number.NaN;

  const $rollHistoryTimeline = $('#rollHistoryTimeline');
  const $rollHistoryTimeAxis = $('#rollHistoryTimeAxis');
  const $rollHistoryTimelineWrap = $('#rollHistoryTimelineWrap');
  const $rollHistoryRangeControls = $('#rollHistoryRangeControls');
  const $rollHistoryRangeStart = $('#rollHistoryRangeStart');
  const $rollHistoryRangeEnd = $('#rollHistoryRangeEnd');
  const $rollHistoryLoading = $('#rollHistoryLoading');
  const $rollHistoryEmpty = $('#rollHistoryEmpty');
  const $rollDetailMeta = $('#rollDetailMeta');
  const $rollDetailSummary = $('#rollDetailSummary');
  const $rollDetailLoading = $('#rollDetailLoading');
  const $rollDetailEmpty = $('#rollDetailEmpty');
  const $rollDetailTableWrap = $('#rollDetailTableWrap');
  const $rollDetailTableBody = $('#rollDetailTableBody');

  if (
    !$rollHistoryTimeline.length &&
    !$rollHistoryTimeAxis.length &&
    !$rollDetailTableBody.length
  ) {
    return;
  }

  function hasSelectedRoll(rollId) {
    return Number.isInteger(Number.parseInt(String(rollId || ''), 10)) && Number(rollId) > 0;
  }

  function toNum(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (char) {
      return {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      }[char];
    });
  }

  function parseTimestamp(value) {
    if (!value) return Number.NaN;
    const parsed = Date.parse(String(value).replace(' ', 'T'));
    return Number.isFinite(parsed) ? parsed : Number.NaN;
  }

  function timeLabel(value) {
    if (!value || value.length < 16) return '-';
    return value.slice(11, 16);
  }

  function dateKey(value) {
    if (!value || value.length < 10) return '';
    return value.slice(0, 10);
  }

  function dateTimeLabel(value) {
    if (!value || value.length < 16) return '-';
    return value.slice(8, 10) + '/' + value.slice(5, 7) + ' ' + value.slice(11, 16);
  }

  function timeWithSecondsLabel(value) {
    if (!value || value.length < 19) {
      return timeLabel(value);
    }
    return value.slice(11, 19);
  }

  function todayDateKey() {
    const today = new Date();
    return (
      String(today.getFullYear()) +
      '-' +
      String(today.getMonth() + 1).padStart(2, '0') +
      '-' +
      String(today.getDate()).padStart(2, '0')
    );
  }

  function dottedDateLabel(value) {
    if (!value || value.length < 10) return '';
    return value.slice(8, 10) + '.' + value.slice(5, 7) + '.' + value.slice(0, 4);
  }

  function formatDateTimeLocalValue(date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) return '';
    return (
      String(date.getFullYear()) +
      '-' +
      String(date.getMonth() + 1).padStart(2, '0') +
      '-' +
      String(date.getDate()).padStart(2, '0') +
      'T' +
      String(date.getHours()).padStart(2, '0') +
      ':' +
      String(date.getMinutes()).padStart(2, '0')
    );
  }

  function formatServerDateTimeValue(ms) {
    const date = new Date(ms);
    if (Number.isNaN(date.getTime())) return '';
    return (
      String(date.getFullYear()) +
      '-' +
      String(date.getMonth() + 1).padStart(2, '0') +
      '-' +
      String(date.getDate()).padStart(2, '0') +
      ' ' +
      String(date.getHours()).padStart(2, '0') +
      ':' +
      String(date.getMinutes()).padStart(2, '0') +
      ':00'
    );
  }

  function parseDateTimeLocalValue(value) {
    if (!value) return Number.NaN;
    const parsed = Date.parse(String(value));
    return Number.isFinite(parsed) ? parsed : Number.NaN;
  }

  function roundDateToNearestMinutes(date, stepMinutes) {
    const stepMs = Math.max(1, stepMinutes) * 60 * 1000;
    return new Date(Math.round(date.getTime() / stepMs) * stepMs);
  }

  function axisClockLabel(date) {
    return (
      String(date.getHours()).padStart(2, '0') + ':' + String(date.getMinutes()).padStart(2, '0')
    );
  }

  function hasValidRollHistoryRange() {
    return (
      Number.isFinite(rollHistoryRangeStartMs) &&
      Number.isFinite(rollHistoryRangeEndMs) &&
      rollHistoryRangeEndMs > rollHistoryRangeStartMs
    );
  }

  function syncRollHistoryRangeInputs() {
    if (
      !$rollHistoryRangeStart.length ||
      !$rollHistoryRangeEnd.length ||
      !hasValidRollHistoryRange()
    ) {
      return;
    }

    $rollHistoryRangeStart.val(formatDateTimeLocalValue(new Date(rollHistoryRangeStartMs)));
    $rollHistoryRangeEnd.val(formatDateTimeLocalValue(new Date(rollHistoryRangeEndMs)));
  }

  function setRollHistoryRange(startMs, endMs, syncInputs) {
    rollHistoryRangeStartMs = startMs;
    rollHistoryRangeEndMs = endMs;
    if (syncInputs !== false) {
      syncRollHistoryRangeInputs();
    }
  }

  function ensureDefaultRollHistoryRange() {
    if (hasValidRollHistoryRange()) return;

    const endDate = roundDateToNearestMinutes(new Date(), TIMELINE_TICK_MINUTES);
    const startDate = new Date(endDate.getTime() - DEFAULT_TIMELINE_RANGE_HOURS * 60 * 60 * 1000);
    setRollHistoryRange(startDate.getTime(), endDate.getTime());
  }

  function tooltipDateTimeParts(value, includeDate) {
    if (!value) {
      return {
        date: '',
        time: '-',
      };
    }

    return {
      date: includeDate ? dottedDateLabel(value) : '',
      time: timeWithSecondsLabel(value),
    };
  }

  function tooltipDurationLabel(seconds) {
    const totalSeconds = Math.max(0, Math.round(toNum(seconds)));
    if (totalSeconds <= 0) return '-';

    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);

    if (hours > 0) {
      return String(hours).padStart(2, '0') + ' h ' + String(minutes).padStart(2, '0') + ' min';
    }

    if (minutes > 0) {
      return String(minutes).padStart(2, '0') + ' min';
    }

    return String(totalSeconds).padStart(2, '0') + ' sec';
  }

  function measureRollHistoryViewportWidth() {
    const wrapWidth = $rollHistoryTimelineWrap.length ? $rollHistoryTimelineWrap.innerWidth() : 0;
    const parentWidth = $rollHistoryTimelineWrap.parent().innerWidth() || 0;
    return Math.max(320, Math.round(wrapWidth || parentWidth || 320));
  }

  function renderRealtimeTimeAxis(timelineWidth, rangeStartMs, rangeEndMs) {
    if (!$rollHistoryTimeAxis.length) return;

    $rollHistoryTimeAxis.empty();

    const safeTimelineWidth = Math.max(1, timelineWidth);
    const safeRangeStartMs = Number.isFinite(rangeStartMs) ? rangeStartMs : Date.now();
    const safeRangeEndMs = Number.isFinite(rangeEndMs)
      ? Math.max(rangeEndMs, safeRangeStartMs + TIMELINE_TICK_MINUTES * 60 * 1000)
      : safeRangeStartMs + TIMELINE_TICK_MINUTES * 60 * 1000;
    const totalDurationMs = Math.max(
      TIMELINE_TICK_MINUTES * 60 * 1000,
      safeRangeEndMs - safeRangeStartMs
    );
    const tickStepMs = TIMELINE_TICK_MINUTES * 60 * 1000;
    const firstTickTimeMs = Math.ceil(safeRangeStartMs / tickStepMs) * tickStepMs;
    let majorTickCount = 0;

    for (let tickTimeMs = firstTickTimeMs; tickTimeMs <= safeRangeEndMs; tickTimeMs += tickStepMs) {
      const ratio = (tickTimeMs - safeRangeStartMs) / totalDurationMs;
      const left = Math.max(0, Math.min(safeTimelineWidth, Math.round(ratio * safeTimelineWidth)));
      const tickDate = new Date(tickTimeMs);
      const isMajor = tickDate.getMinutes() % TIMELINE_LABEL_INTERVAL_MINUTES === 0;
      let edgeClass = '';

      if (isMajor) {
        majorTickCount += 1;
      }

      if (left <= 24) {
        edgeClass = ' is-edge-start';
      } else if (left >= safeTimelineWidth - 24) {
        edgeClass = ' is-edge-end';
      }

      $rollHistoryTimeAxis.append(
        '<div class="roll-history-time-tick' +
          (isMajor ? ' is-major' : '') +
          edgeClass +
          '" style="left:' +
          left +
          'px">' +
          (isMajor
            ? '<span class="roll-history-time-label">' +
              escapeHtml(axisClockLabel(tickDate)) +
              '</span>'
            : '') +
          '</div>'
      );
    }

    if (majorTickCount === 0) {
      const endDate = new Date(safeRangeEndMs);
      $rollHistoryTimeAxis.append(
        '<div class="roll-history-time-tick is-major is-edge-end" style="left:' +
          safeTimelineWidth +
          'px">' +
          '<span class="roll-history-time-label">' +
          escapeHtml(axisClockLabel(endDate)) +
          '</span>' +
          '</div>'
      );
    }
  }

  function buildRollHistorySignature(rolls, rangeStartMs, rangeEndMs) {
    return JSON.stringify({
      range_start: rangeStartMs,
      range_end: rangeEndMs,
      rolls: (Array.isArray(rolls) ? rolls : []).map(function (roll) {
        return {
          id: roll && roll.id,
          rollname: roll && roll.rollname,
          product: roll && roll.product,
          status: roll && roll.status,
          starttime: roll && roll.starttime,
          endtime: roll && roll.endtime,
          duration_seconds: roll && roll.duration_seconds,
          duration_label: roll && roll.duration_label,
          is_live: roll && roll.is_live,
        };
      }),
    });
  }

  function buildRollDetailSignature(roll, rows) {
    return JSON.stringify({
      roll: roll
        ? {
            id: roll.id,
            rollname: roll.rollname,
            product: roll.product,
            recipe: roll.recipe,
            campaign: roll.campaign,
            starttime: roll.starttime,
            endtime: roll.endtime,
            duration_label: roll.duration_label,
          }
        : null,
      rows: (Array.isArray(rows) ? rows : []).map(function (row) {
        return {
          id: row && row.id,
          dbid: row && row.dbid,
          address: row && row.address,
          name: row && row.name,
          value_text: row && row.value_text,
          timestamp: row && row.timestamp,
        };
      }),
    });
  }

  function setRollHistoryLoading(isLoading, text) {
    if (!$rollHistoryLoading.length) return;
    $rollHistoryLoading.text(text || 'Memuat production history...');
    $rollHistoryLoading.toggleClass('d-none', !isLoading);
  }

  function setRollDetailLoading(isLoading, text) {
    if (!$rollDetailLoading.length) return;
    $rollDetailLoading.text(text || 'Memuat detail roll...');
    $rollDetailLoading.toggleClass('d-none', !isLoading);
  }

  function showRollHistoryError(msg) {
    const message = msg || 'Gagal memuat production history.';
    if (window.AppNotify && window.AppNotify.backend) {
      window.AppNotify.backend.error(message, {
        key: 'roll-history-error',
        cooldown: 5000,
        options: {
          toast: true,
          position: 'top-end',
        },
      });
    }
  }

  function ensureRollHistoryTooltip() {
    if ($rollHistoryHoverTooltip && $rollHistoryHoverTooltip.length) {
      return $rollHistoryHoverTooltip;
    }

    $rollHistoryHoverTooltip = $(
      '<div id="rollHistoryHoverTooltip" class="roll-history-hover-tooltip" aria-hidden="true"></div>'
    ).appendTo(document.body);

    return $rollHistoryHoverTooltip;
  }

  function hideRollHistoryTooltip() {
    const $tooltip = ensureRollHistoryTooltip();
    $tooltip.removeClass('is-visible').attr('aria-hidden', 'true').empty();
  }

  function positionRollHistoryTooltip($item) {
    const $tooltip = ensureRollHistoryTooltip();
    if (!$item || !$item.length || !$tooltip.length) return;

    const itemRect = $item[0].getBoundingClientRect();
    const tooltipRect = $tooltip[0].getBoundingClientRect();
    const viewportPadding = 8;
    let left = itemRect.left + itemRect.width / 2 - tooltipRect.width / 2;
    left = Math.max(
      viewportPadding,
      Math.min(left, window.innerWidth - tooltipRect.width - viewportPadding)
    );

    let top = itemRect.top - tooltipRect.height - 10;
    if (top < viewportPadding) {
      top = itemRect.bottom + 10;
    }

    $tooltip.css({
      left: left + 'px',
      top: top + 'px',
    });
  }

  function showRollHistoryTooltip($item) {
    if (!$item || !$item.length) return;

    const $tooltip = ensureRollHistoryTooltip();
    const rollName = $item.attr('data-roll-name') || '-';
    const startDate = $item.attr('data-roll-start-date') || '';
    const startTime = $item.attr('data-roll-start-time') || '-';
    const endDate = $item.attr('data-roll-end-date') || '';
    const endTime = $item.attr('data-roll-end-time') || '-';
    const duration = $item.attr('data-roll-duration') || '-';

    $tooltip
      .html(
        '<div class="roll-history-hover-tooltip-title">' +
          escapeHtml(rollName) +
          '</div>' +
          '<div class="roll-history-hover-tooltip-row">' +
          '<span class="roll-history-hover-tooltip-datetime">' +
          (startDate
            ? '<span class="roll-history-hover-tooltip-date">' + escapeHtml(startDate) + '</span>'
            : '') +
          '<span class="roll-history-hover-tooltip-time">' +
          escapeHtml(startTime) +
          '</span>' +
          '</span>' +
          '<span class="roll-history-hover-tooltip-duration">' +
          escapeHtml(duration) +
          '</span>' +
          '</div>' +
          '<div class="roll-history-hover-tooltip-row">' +
          '<span class="roll-history-hover-tooltip-datetime">' +
          (endDate
            ? '<span class="roll-history-hover-tooltip-date">' + escapeHtml(endDate) + '</span>'
            : '') +
          '<span class="roll-history-hover-tooltip-time roll-history-hover-tooltip-time-end">' +
          escapeHtml(endTime) +
          '</span>' +
          '</span>' +
          '</div>'
      )
      .addClass('is-visible')
      .attr('aria-hidden', 'false');

    positionRollHistoryTooltip($item);
  }

  function scheduleRollHistoryRefresh(ms) {
    clearTimeout(rollHistoryTimer);
    rollHistoryTimer = setTimeout(function () {
      fetchRollHistory(selectedRollId);
    }, ms);
  }

  function renderRollTimeline(rolls, rangeStartMs, rangeEndMs) {
    if (!$rollHistoryTimeline.length || !$rollHistoryTimeAxis.length) {
      return;
    }

    $rollHistoryTimeline.empty();
    $rollHistoryTimeAxis.empty();
    $rollHistoryTimeline.removeClass('has-active-selection');

    if (!rolls.length) {
      $rollHistoryTimelineWrap.addClass('d-none');
      $rollHistoryEmpty.removeClass('d-none');
      return;
    }

    const orderedRolls = rolls.slice().sort(function (a, b) {
      const timeA = parseTimestamp(a.starttime || a.endtime);
      const timeB = parseTimestamp(b.starttime || b.endtime);
      if (Number.isFinite(timeA) && Number.isFinite(timeB) && timeA !== timeB) {
        return timeA - timeB;
      }
      return toNum(a.id) - toNum(b.id);
    });

    const currentDateKey = todayDateKey();
    const safeRangeStartMs = Number.isFinite(rangeStartMs) ? rangeStartMs : Date.now();
    const safeRangeEndMs = Number.isFinite(rangeEndMs)
      ? Math.max(rangeEndMs, safeRangeStartMs + TIMELINE_TICK_MINUTES * 60 * 1000)
      : safeRangeStartMs + TIMELINE_TICK_MINUTES * 60 * 1000;
    const timelineWidth = measureRollHistoryViewportWidth();
    const totalRangeMs = Math.max(1, safeRangeEndMs - safeRangeStartMs);
    const hasActiveSelection = hasSelectedRoll(selectedRollId);

    orderedRolls.forEach(function (roll) {
      const startTimestampMs = parseTimestamp(roll.starttime || roll.endtime);
      const endTimestampMs = parseTimestamp(roll.endtime || roll.starttime);
      if (!Number.isFinite(startTimestampMs) || !Number.isFinite(endTimestampMs)) {
        return;
      }

      const isLiveRoll = roll && roll.is_live === true;
      const clampedStartMs = Math.max(safeRangeStartMs, startTimestampMs);
      const clampedEndMs = isLiveRoll
        ? safeRangeEndMs
        : Math.max(clampedStartMs, Math.min(safeRangeEndMs, endTimestampMs));
      const left = Math.max(
        0,
        Math.min(
          timelineWidth,
          Math.floor(((clampedStartMs - safeRangeStartMs) / totalRangeMs) * timelineWidth)
        )
      );
      const right = Math.max(
        left + 1,
        Math.min(
          timelineWidth,
          Math.ceil(((clampedEndMs - safeRangeStartMs) / totalRangeMs) * timelineWidth)
        )
      );
      const width = Math.max(1, right - left);
      const startTimestamp = roll.starttime || '';
      const endTimestamp = roll.endtime || roll.starttime || '';
      const shouldShowTooltipDate =
        dateKey(startTimestamp) !== currentDateKey || dateKey(endTimestamp) !== currentDateKey;
      const startParts = tooltipDateTimeParts(startTimestamp, shouldShowTooltipDate);
      const endParts = isLiveRoll
        ? {
            date: '',
            time: '....',
          }
        : tooltipDateTimeParts(endTimestamp, shouldShowTooltipDate);

      const isShutdown = Number(roll.status) === 0;
      const isActive = String(roll.id) === String(selectedRollId);
      const activeClass = isActive ? ' is-active' : '';
      const inactiveClass = hasActiveSelection && !isActive ? ' is-inactive' : '';
      const statusClass = isShutdown ? ' is-status-shutdown' : '';
      const compactClass = width < TIMELINE_INLINE_TEXT_MIN_WIDTH ? ' is-compact' : '';
      const productText = roll.product ? escapeHtml(roll.product) : '-';
      const durationText = roll.duration_label ? escapeHtml(roll.duration_label) : '-';

      $rollHistoryTimeline.append(
        '<button type="button" class="roll-history-item' +
          statusClass +
          compactClass +
          inactiveClass +
          activeClass +
          '" data-roll-id="' +
          escapeHtml(roll.id) +
          '" data-roll-name="' +
          escapeHtml(roll.rollname || 'Roll ' + roll.id) +
          '" data-roll-start-date="' +
          escapeHtml(startParts.date) +
          '" data-roll-start-time="' +
          escapeHtml(startParts.time) +
          '" data-roll-end-date="' +
          escapeHtml(endParts.date) +
          '" data-roll-end-time="' +
          escapeHtml(endParts.time) +
          '" data-roll-live="' +
          (isLiveRoll ? '1' : '0') +
          '" data-roll-duration="' +
          escapeHtml(tooltipDurationLabel(roll.duration_seconds)) +
          '" style="left:' +
          left +
          'px;width:' +
          width +
          'px" aria-label="' +
          escapeHtml(roll.rollname || 'Roll ' + roll.id) +
          '">' +
          '<span class="roll-history-text">' +
          '<span class="roll-history-name">' +
          escapeHtml(roll.rollname || 'Roll ' + roll.id) +
          '</span>' +
          '<span class="roll-history-sub">' +
          productText +
          ' • ' +
          durationText +
          '</span>' +
          '</span>' +
          '</button>'
      );
    });

    $rollHistoryTimeline.toggleClass('has-active-selection', hasActiveSelection);
    $rollHistoryTimeline.css('width', timelineWidth + 'px');
    $rollHistoryTimeAxis.css('width', timelineWidth + 'px');
    renderRealtimeTimeAxis(timelineWidth, safeRangeStartMs, safeRangeEndMs);
    $rollHistoryTimelineWrap.removeClass('d-none');
    $rollHistoryEmpty.addClass('d-none');
    $rollHistoryRangeControls.removeClass('d-none');
    updateRollHistoryLabelVisibility();
  }

  function updateRollHistoryLabelVisibility() {
    if (!$rollHistoryTimeline.length) {
      return;
    }

    $rollHistoryTimeline.find('.roll-history-item').each(function () {
      const item = this;
      const $item = $(item);
      const text = item.querySelector('.roll-history-text');
      const name = item.querySelector('.roll-history-name');
      const sub = item.querySelector('.roll-history-sub');

      if (!text || !name || !sub) {
        return;
      }

      $item.removeClass('is-label-hidden');

      const isOverflowing =
        name.scrollWidth > name.clientWidth + 1 ||
        sub.scrollWidth > sub.clientWidth + 1 ||
        text.scrollHeight > text.clientHeight + 1;

      $item.toggleClass('is-label-hidden', isOverflowing);
    });
  }

  function renderRollDetail(roll, rows) {
    const detailRows = Array.isArray(rows) ? rows : [];
    const hasRoll = roll && typeof roll === 'object';

    $rollDetailTableBody.empty();

    if (!hasRoll) {
      $rollDetailMeta.text('Pilih roll pada timeline.');
      $rollDetailSummary.addClass('d-none').empty();
      $rollDetailTableWrap.addClass('d-none');
      $rollDetailEmpty
        .removeClass('d-none')
        .text('Klik salah satu roll untuk melihat data `rtagroll`.');
      return;
    }

    $rollDetailMeta.text(
      (roll.rollname || 'Roll ' + roll.id) + ' • ' + detailRows.length + ' rows'
    );
    $rollDetailSummary
      .removeClass('d-none')
      .html(
        '<div class="roll-detail-pill"><span>Roll</span><strong>' +
          escapeHtml(roll.rollname || '-') +
          '</strong></div>' +
          '<div class="roll-detail-pill"><span>Product</span><strong>' +
          escapeHtml(roll.product || '-') +
          '</strong></div>' +
          '<div class="roll-detail-pill"><span>Recipe</span><strong>' +
          escapeHtml(roll.recipe || '-') +
          '</strong></div>' +
          '<div class="roll-detail-pill"><span>Campaign</span><strong>' +
          escapeHtml(roll.campaign || '-') +
          '</strong></div>' +
          '<div class="roll-detail-pill"><span>Range</span><strong>' +
          escapeHtml(dateTimeLabel(roll.starttime)) +
          ' - ' +
          escapeHtml(timeLabel(roll.endtime)) +
          '</strong></div>' +
          '<div class="roll-detail-pill"><span>Duration</span><strong>' +
          escapeHtml(roll.duration_label || '-') +
          '</strong></div>'
      );

    if (!detailRows.length) {
      $rollDetailTableWrap.addClass('d-none');
      $rollDetailEmpty.removeClass('d-none').text('Tidak ada data `rtagroll` untuk roll ini.');
      return;
    }

    detailRows.forEach(function (row) {
      $rollDetailTableBody.append(
        '<tr>' +
          '<td>' +
          escapeHtml(row.id) +
          '</td>' +
          '<td>' +
          escapeHtml(row.dbid) +
          '</td>' +
          '<td>' +
          escapeHtml(row.address || '-') +
          '</td>' +
          '<td>' +
          escapeHtml(row.name || '-') +
          '</td>' +
          '<td class="text-right">' +
          escapeHtml(row.value_text || '-') +
          '</td>' +
          '<td>' +
          escapeHtml(row.timestamp || '-') +
          '</td>' +
          '</tr>'
      );
    });

    $rollDetailTableWrap.removeClass('d-none');
    $rollDetailEmpty.addClass('d-none');
  }

  function setSelectedRoll(rollId) {
    selectedRollId = rollId;
    const hasActiveSelection = hasSelectedRoll(rollId);
    $rollHistoryTimeline.toggleClass('has-active-selection', hasActiveSelection);
    $rollHistoryTimeline.find('.roll-history-item').each(function () {
      const $item = $(this);
      const isActive = hasActiveSelection && String($item.attr('data-roll-id')) === String(rollId);
      $item.toggleClass('is-active', isActive);
      $item.toggleClass('is-inactive', hasActiveSelection && !isActive);
    });
  }

  function fetchRollDetail(rollId) {
    if (!rollId || !$rollDetailTableBody.length) return;

    if (currentRollDetailRequest) {
      currentRollDetailRequest.abort();
    }

    setSelectedRoll(rollId);
    setRollDetailLoading(true, 'Memuat detail roll...');
    $rollDetailEmpty.addClass('d-none');

    currentRollDetailRequest = $.ajax({
      url: rollHistoryEndpoint,
      method: 'GET',
      dataType: 'json',
      timeout: HISTORY_REQUEST_TIMEOUT_MS,
      cache: false,
      data: {
        action: 'detail',
        roll_id: rollId,
      },
    });

    currentRollDetailRequest.done(function (res) {
      if (!res || !res.ok) {
        showRollHistoryError(
          res && res.message ? res.message : 'Response detail roll tidak valid.'
        );
        return;
      }

      renderRollDetail(res.roll, res.tag_rows);
      lastRenderedRollDetailSignature = buildRollDetailSignature(res.roll, res.tag_rows);
    });

    currentRollDetailRequest.fail(function (xhr, status) {
      if (status === 'abort') return;
      const msg =
        xhr && xhr.responseJSON && (xhr.responseJSON.message || xhr.responseJSON.detail)
          ? xhr.responseJSON.message || xhr.responseJSON.detail
          : 'Gagal mengambil detail roll.';
      showRollHistoryError(msg);
      $rollDetailEmpty.removeClass('d-none').text(msg);
      $rollDetailTableWrap.addClass('d-none');
    });

    currentRollDetailRequest.always(function () {
      setRollDetailLoading(false);
      currentRollDetailRequest = null;
    });
  }

  function fetchRollHistory(preferredRollId) {
    if (!$rollHistoryTimeline.length || isFetchingRollHistory) {
      return;
    }

    ensureDefaultRollHistoryRange();

    if (currentRollHistoryRequest) {
      currentRollHistoryRequest.abort();
    }

    isFetchingRollHistory = true;
    if (!lastRenderedRollHistorySignature) {
      setRollHistoryLoading(true, 'Memuat production history...');
    }

    currentRollHistoryRequest = $.ajax({
      url: rollHistoryEndpoint,
      method: 'GET',
      dataType: 'json',
      timeout: HISTORY_REQUEST_TIMEOUT_MS,
      cache: false,
      data: preferredRollId
        ? {
            action: 'history',
            roll_id: preferredRollId,
            range_start: formatServerDateTimeValue(rollHistoryRangeStartMs),
            range_end: formatServerDateTimeValue(rollHistoryRangeEndMs),
          }
        : {
            action: 'history',
            range_start: formatServerDateTimeValue(rollHistoryRangeStartMs),
            range_end: formatServerDateTimeValue(rollHistoryRangeEndMs),
          },
    });

    currentRollHistoryRequest.done(function (res) {
      if (!res || !res.ok) {
        showRollHistoryError(
          res && res.message ? res.message : 'Response production history tidak valid.'
        );
        return;
      }

      rollItems = Array.isArray(res.rolls) ? res.rolls : [];
      const responseRangeStartMs = parseTimestamp(res.range_start);
      const responseRangeEndMs = parseTimestamp(res.range_end);
      if (Number.isFinite(responseRangeStartMs) && Number.isFinite(responseRangeEndMs)) {
        setRollHistoryRange(responseRangeStartMs, responseRangeEndMs);
      } else {
        syncRollHistoryRangeInputs();
      }

      const nextSelectedRollId = res.selected_roll_id || (res.roll && res.roll.id) || null;
      const nextRollHistorySignature = buildRollHistorySignature(
        rollItems,
        rollHistoryRangeStartMs,
        rollHistoryRangeEndMs
      );
      const nextRollDetailSignature = buildRollDetailSignature(res.roll, res.tag_rows);
      const shouldRenderTimeline = nextRollHistorySignature !== lastRenderedRollHistorySignature;
      const shouldRenderDetail = nextRollDetailSignature !== lastRenderedRollDetailSignature;
      const selectionChanged = String(nextSelectedRollId) !== String(selectedRollId);

      selectedRollId = nextSelectedRollId;
      $rollHistoryRangeControls.removeClass('d-none');

      if (shouldRenderTimeline) {
        renderRollTimeline(rollItems, rollHistoryRangeStartMs, rollHistoryRangeEndMs);
        lastRenderedRollHistorySignature = nextRollHistorySignature;
      } else if (selectionChanged) {
        setSelectedRoll(selectedRollId);
      }

      if (shouldRenderDetail) {
        renderRollDetail(res.roll, res.tag_rows);
        lastRenderedRollDetailSignature = nextRollDetailSignature;
      }
    });

    currentRollHistoryRequest.fail(function (xhr, status) {
      if (status === 'abort') return;
      const msg =
        xhr && xhr.responseJSON && (xhr.responseJSON.message || xhr.responseJSON.detail)
          ? xhr.responseJSON.message || xhr.responseJSON.detail
          : 'Gagal mengambil production history.';
      showRollHistoryError(msg);
      $rollHistoryTimelineWrap.addClass('d-none');
      $rollHistoryRangeControls.removeClass('d-none');
      $rollHistoryEmpty.removeClass('d-none').text(msg);
    });

    currentRollHistoryRequest.always(function () {
      isFetchingRollHistory = false;
      currentRollHistoryRequest = null;
      setRollHistoryLoading(false);
      scheduleRollHistoryRefresh(ROLL_HISTORY_REFRESH_MS);
    });
  }

  function applyRollHistoryRangeFromInputs() {
    const nextStartMs = parseDateTimeLocalValue($rollHistoryRangeStart.val());
    const nextEndMs = parseDateTimeLocalValue($rollHistoryRangeEnd.val());

    if (!Number.isFinite(nextStartMs) || !Number.isFinite(nextEndMs) || nextEndMs <= nextStartMs) {
      syncRollHistoryRangeInputs();
      showRollHistoryError('Range waktu production history tidak valid.');
      return;
    }

    setRollHistoryRange(nextStartMs, nextEndMs, true);
    lastRenderedRollHistorySignature = '';
    fetchRollHistory(selectedRollId);
  }

  $(document).on('visibilitychange', function () {
    if (document.hidden) {
      hideRollHistoryTooltip();
      if (currentRollHistoryRequest) {
        currentRollHistoryRequest.abort();
      }
      if (currentRollDetailRequest) {
        currentRollDetailRequest.abort();
      }
      clearTimeout(rollHistoryTimer);
    } else {
      fetchRollHistory(selectedRollId);
    }
  });

  $rollHistoryRangeStart.on('change', applyRollHistoryRangeFromInputs);
  $rollHistoryRangeEnd.on('change', applyRollHistoryRangeFromInputs);

  $rollHistoryTimeline.on('click', '.roll-history-item', function () {
    const rollId = Number.parseInt($(this).attr('data-roll-id') || '0', 10);
    if (!Number.isInteger(rollId) || rollId <= 0) {
      return;
    }

    fetchRollDetail(rollId);
  });

  $rollHistoryTimeline.on('mouseenter focusin', '.roll-history-item', function () {
    showRollHistoryTooltip($(this));
  });

  $rollHistoryTimeline.on('mouseleave focusout', '.roll-history-item', function () {
    hideRollHistoryTooltip();
  });

  $rollHistoryTimelineWrap.on('scroll', function () {
    hideRollHistoryTooltip();
  });

  $(window).on('scroll resize', function () {
    hideRollHistoryTooltip();
    if (rollItems.length && hasValidRollHistoryRange()) {
      renderRollTimeline(rollItems, rollHistoryRangeStartMs, rollHistoryRangeEndMs);
    }
  });

  ensureDefaultRollHistoryRange();
  syncRollHistoryRangeInputs();
  fetchRollHistory();
})(window.jQuery, window, document);
