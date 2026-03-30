(function (window, document) {
  var themeStorageKey = 'dashboardThemeMode';
  var defaultSidebarState = 'collapsed';
  var sidebarBreakpoint = 992;
  var jqueryWaitAttempts = 200;
  var initialized = false;

  function getJQuery() {
    return window.jQuery || null;
  }

  function getBody() {
    return document.body;
  }

  function normalizeMode(mode) {
    return mode === 'light' ? 'light' : 'dark';
  }

  function normalizeSidebarState(state) {
    return state === 'expanded' ? 'expanded' : defaultSidebarState;
  }

  function getSidebarStorageKey() {
    var body = getBody();

    if (!body) {
      return '';
    }

    return body.getAttribute('data-sidebar-storage-key') || '';
  }

  function isDesktopSidebarViewport() {
    return window.innerWidth > sidebarBreakpoint;
  }

  function readStoredMode() {
    try {
      return normalizeMode(localStorage.getItem(themeStorageKey));
    } catch (err) {
      return 'dark';
    }
  }

  function readStoredSidebarState() {
    var sidebarStorageKey = getSidebarStorageKey();

    if (!sidebarStorageKey) {
      return defaultSidebarState;
    }

    try {
      return normalizeSidebarState(localStorage.getItem(sidebarStorageKey));
    } catch (err) {
      return defaultSidebarState;
    }
  }

  function writeStoredMode(mode) {
    try {
      localStorage.setItem(themeStorageKey, normalizeMode(mode));
    } catch (err) {}
  }

  function writeStoredSidebarState(state) {
    var sidebarStorageKey = getSidebarStorageKey();

    if (!sidebarStorageKey) {
      return;
    }

    try {
      localStorage.setItem(sidebarStorageKey, normalizeSidebarState(state));
    } catch (err) {}
  }

  function applyInitialSidebarState() {
    var body = getBody();
    var storageKey = getSidebarStorageKey();
    var state;

    if (!body || !storageKey) {
      return;
    }

    try {
      state = localStorage.getItem(storageKey);
    } catch (err) {
      state = null;
    }

    body.classList.remove('sidebar-open');
    body.classList.remove('sidebar-closed');

    if (state === 'expanded' && isDesktopSidebarViewport()) {
      body.classList.remove('sidebar-collapse');
      return;
    }

    body.classList.add('sidebar-collapse');
  }

  function getThemeSelect() {
    return getJQuery()('#themeMode');
  }

  function getPushMenuButton() {
    return getJQuery()('[data-widget="pushmenu"]').first();
  }

  function isSidebarExpanded() {
    return isDesktopSidebarViewport() && !getJQuery()('body').hasClass('sidebar-collapse');
  }

  function syncThemeSelect(mode) {
    var $themeSelect = getThemeSelect();

    if (!$themeSelect.length) {
      return;
    }

    $themeSelect.val(mode);
    if ($themeSelect.hasClass('select2-hidden-accessible')) {
      $themeSelect.trigger('change.select2');
    }
  }

  function applyTheme(mode) {
    var $ = getJQuery();
    var selectedMode = normalizeMode(mode);

    $('body')
      .removeClass('theme-dark theme-light')
      .addClass('theme-' + selectedMode);
    syncThemeSelect(selectedMode);
    writeStoredMode(selectedMode);

    return selectedMode;
  }

  function applySidebarState(state) {
    var $ = getJQuery();
    var selectedState = normalizeSidebarState(state);
    var $body = $('body');

    if (!$body.length) {
      return selectedState;
    }

    $body.removeClass('sidebar-open');

    if (selectedState === 'expanded' && isDesktopSidebarViewport()) {
      $body.removeClass('sidebar-collapse sidebar-closed');
      return selectedState;
    }

    $body.addClass('sidebar-collapse').removeClass('sidebar-closed');
    return defaultSidebarState;
  }

  function collapseSidebar() {
    var $ = getJQuery();
    var $toggleButton = getPushMenuButton();

    if ($toggleButton.length && $.fn.PushMenu) {
      $toggleButton.PushMenu('collapse');
      return;
    }

    $('body')
      .addClass('sidebar-collapse')
      .removeClass('sidebar-open sidebar-closed');
  }

  function bindSidebarRemember() {
    var $ = getJQuery();
    var $body = $('body');

    if (!$body.length || $body.attr('data-sidebar-bound') === '1') {
      return;
    }

    $body.attr('data-sidebar-bound', '1');

    $(document).on('collapsed.lte.pushmenu.appSidebar', '[data-widget="pushmenu"]', function () {
      if (isDesktopSidebarViewport()) {
        writeStoredSidebarState('collapsed');
      }
    });

    $(document).on('shown.lte.pushmenu.appSidebar', '[data-widget="pushmenu"]', function () {
      if (isDesktopSidebarViewport()) {
        writeStoredSidebarState('expanded');
      }
    });
  }

  function bindSidebarAutoCollapse() {
    var $ = getJQuery();
    var $body = $('body');
    var openedAt = 0;

    if (!$body.length || $body.attr('data-sidebar-autocollapse-bound') === '1') {
      return;
    }

    $body.attr('data-sidebar-autocollapse-bound', '1');

    $(document).on('shown.lte.pushmenu.appSidebarAuto', '[data-widget="pushmenu"]', function () {
      if (isDesktopSidebarViewport()) {
        openedAt = Date.now();
      }
    });

    $(document).on('collapsed.lte.pushmenu.appSidebarAuto', '[data-widget="pushmenu"]', function () {
      openedAt = 0;
    });

    $(document).on('mousemove.appSidebarAuto', function (event) {
      var $target = $(event.target);

      if (!isSidebarExpanded()) {
        return;
      }

      if (!openedAt) {
        openedAt = Date.now();
      }

      if (Date.now() - openedAt < 180) {
        return;
      }

      if ($target.closest('.main-sidebar').length || $target.closest('[data-widget="pushmenu"]').length) {
        return;
      }

      collapseSidebar();
    });
  }

  function initThemeSelect() {
    var $ = getJQuery();
    var $themeSelect = getThemeSelect();

    if (!$themeSelect.length) {
      return;
    }

    if ($.fn.select2 && !$themeSelect.hasClass('select2-hidden-accessible')) {
      $themeSelect.select2({
        theme: 'bootstrap4',
        minimumResultsForSearch: Infinity,
        width: 'style'
      });
    }

    if ($themeSelect.attr('data-theme-bound') === '1') {
      return;
    }

    $themeSelect.attr('data-theme-bound', '1');
    $themeSelect.on('change select2:select', function () {
      applyTheme($themeSelect.val());
    });
  }

  function exposeApi() {
    window.AppLayout = {
      applyTheme: applyTheme,
      applySidebarState: applySidebarState,
      collapseSidebar: collapseSidebar,
      init: init,
      readStoredSidebarState: readStoredSidebarState,
      themeStorageKey: themeStorageKey
    };

    window.AppTheme = {
      apply: applyTheme,
      init: init,
      storageKey: themeStorageKey,
      applySidebarState: applySidebarState,
      readStoredSidebarState: readStoredSidebarState
    };
  }

  function init() {
    if (!getJQuery()) {
      return false;
    }

    if (initialized) {
      syncThemeSelect(readStoredMode());
      applySidebarState(readStoredSidebarState());
      return true;
    }

    initialized = true;
    initThemeSelect();
    applyTheme(readStoredMode());
    applySidebarState(readStoredSidebarState());
    bindSidebarRemember();
    bindSidebarAutoCollapse();
    exposeApi();
    return true;
  }

  function waitForJQueryAndInit(attemptsLeft) {
    if (init()) {
      return;
    }

    if (attemptsLeft <= 0) {
      return;
    }

    window.setTimeout(function () {
      waitForJQueryAndInit(attemptsLeft - 1);
    }, 25);
  }

  applyInitialSidebarState();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      waitForJQueryAndInit(jqueryWaitAttempts);
    });
  } else {
    waitForJQueryAndInit(jqueryWaitAttempts);
  }
})(window, document);
