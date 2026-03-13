(function (window) {
  var toastDefaults = {
    closeButton: true,
    progressBar: true,
    newestOnTop: true,
    positionClass: 'toast-top-right',
    preventDuplicates: false,
    timeOut: 4000,
    extendedTimeOut: 1000
  };
  var lastShown = {};

  function normalizeType(type) {
    switch (String(type || '').toLowerCase()) {
      case 'success':
      case 'warning':
      case 'info':
      case 'error':
        return String(type).toLowerCase();
      default:
        return 'info';
    }
  }

  function shouldSkip(message, options) {
    var key = options && options.key ? String(options.key) : '';
    var cooldown = options && Number.isFinite(options.cooldown) ? Number(options.cooldown) : 0;
    var now = Date.now();
    var entry;

    if (!key || cooldown <= 0) {
      return false;
    }

    entry = lastShown[key];
    if (entry && entry.message === message && now - entry.at < cooldown) {
      return true;
    }

    lastShown[key] = {
      at: now,
      message: message
    };
    return false;
  }

  function assign(target) {
    var i;
    var source;
    var key;

    for (i = 1; i < arguments.length; i += 1) {
      source = arguments[i] || {};
      for (key in source) {
        if (Object.prototype.hasOwnProperty.call(source, key)) {
          target[key] = source[key];
        }
      }
    }

    return target;
  }

  function show(message, type, options) {
    var normalizedType = normalizeType(type);
    var text = message == null ? '' : String(message);
    var toastrOptions;
    var typeDefaults = {};

    if (!text) {
      return;
    }

    if (shouldSkip(text, options || {})) {
      return;
    }

    if (!window.toastr || typeof window.toastr[normalizedType] !== 'function') {
      if (window.console && typeof window.console.warn === 'function') {
        window.console.warn('Toast fallback:', normalizedType, text);
      }
      return;
    }

    if (normalizedType === 'error') {
      typeDefaults = {
        timeOut: 0,
        extendedTimeOut: 0,
        tapToDismiss: false
      };
    }

    toastrOptions = assign({}, toastDefaults, typeDefaults, (options && options.toastrOptions) || {});
    window.toastr.options = toastrOptions;
    window.toastr[normalizedType](text);
  }

  window.AppToast = {
    show: show,
    success: function (message, options) {
      show(message, 'success', options);
    },
    info: function (message, options) {
      show(message, 'info', options);
    },
    warning: function (message, options) {
      show(message, 'warning', options);
    },
    error: function (message, options) {
      show(message, 'error', options);
    },
    clear: function () {
      if (window.toastr && typeof window.toastr.clear === 'function') {
        window.toastr.clear();
      }
    }
  };
})(window);
