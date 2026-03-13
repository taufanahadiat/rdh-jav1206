(function (window, $) {
  var storageKey = 'dashboardThemeMode';
  var initialized = false;

  function normalizeMode(mode) {
    return mode === 'light' ? 'light' : 'dark';
  }

  function getThemeSelect() {
    return $('#themeMode');
  }

  function readStoredMode() {
    try {
      return normalizeMode(localStorage.getItem(storageKey));
    } catch (err) {
      return 'dark';
    }
  }

  function writeStoredMode(mode) {
    try {
      localStorage.setItem(storageKey, mode);
    } catch (err) {}
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
    var selectedMode = normalizeMode(mode);

    $('body')
      .removeClass('theme-dark theme-light')
      .addClass('theme-' + selectedMode);
    syncThemeSelect(selectedMode);
    writeStoredMode(selectedMode);

    return selectedMode;
  }

  function initThemeSelect() {
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

  function init() {
    if (initialized) {
      syncThemeSelect(readStoredMode());
      return;
    }

    initialized = true;
    initThemeSelect();
    applyTheme(readStoredMode());
  }

  window.AppTheme = {
    apply: applyTheme,
    init: init,
    storageKey: storageKey
  };

  $(init);
})(window, window.jQuery);
