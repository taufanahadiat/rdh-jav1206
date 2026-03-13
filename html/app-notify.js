(function (window) {
  var lastShown = {};
  var notificationTypes = ['success', 'info', 'warning', 'error', 'question'];
  var toastDefaults = {
    closeButton: true,
    progressBar: true,
    newestOnTop: true,
    positionClass: 'toast-top-right',
    preventDuplicates: false,
    timeOut: 4000,
    extendedTimeOut: 1000
  };
  var swalDefaults = {
    toast: true,
    position: 'top-end',
    showConfirmButton: false,
    showCloseButton: false,
    timerProgressBar: true,
    customClass: {
      popup: 'app-swal-toast'
    }
  };

  function assign(target) {
    var i;
    var source;
    var key;

    for (i = 1; i < arguments.length; i += 1) {
      source = arguments[i] || {};
      for (key in source) {
        if (Object.prototype.hasOwnProperty.call(source, key)) {
          if (
            target[key] &&
            typeof target[key] === 'object' &&
            !Array.isArray(target[key]) &&
            typeof source[key] === 'object' &&
            source[key] !== null &&
            !Array.isArray(source[key])
          ) {
            assign(target[key], source[key]);
          } else {
            target[key] = source[key];
          }
        }
      }
    }

    return target;
  }

  function normalizeType(type) {
    var normalized = String(type || '').toLowerCase();
    return notificationTypes.indexOf(normalized) >= 0 ? normalized : 'info';
  }

  function titleCase(value) {
    var text = String(value || '');
    if (!text) {
      return '';
    }
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function shouldSkip(message, config) {
    var key = config && config.key ? String(config.key) : '';
    var cooldown = config && Number.isFinite(config.cooldown) ? Number(config.cooldown) : 0;
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

  function resolveAutoHide(type, config) {
    if (typeof config.autohide === 'boolean') {
      return config.autohide;
    }

    return type !== 'question';
  }

  function resolveTimeout(config) {
    if (Number.isFinite(config.timeout) && Number(config.timeout) >= 0) {
      return Number(config.timeout);
    }

    return 4000;
  }

  function resolveConfig(message, config) {
    var resolved = assign({}, config || {});
    resolved.message = message == null ? '' : String(message);
    resolved.type = normalizeType(resolved.type);
    resolved.autohide = resolveAutoHide(resolved.type, resolved);
    resolved.timeout = resolveTimeout(resolved);
    resolved.options = assign({}, resolved.options || {});
    return resolved;
  }

  function buildSwalOptions(type, config) {
    var options = assign({}, swalDefaults, config.options || {});
    var toastMode = typeof options.toast === 'boolean' ? options.toast : true;
    var title = config.title ? String(config.title) : (toastMode ? config.message : titleCase(type));

    options.icon = type;
    options.toast = toastMode;
    options.title = title;

    if (config.title) {
      options.text = config.message;
    } else if (!toastMode && !options.html) {
      options.text = config.message;
    } else if (!options.html) {
      delete options.text;
    }

    if (config.autohide) {
      options.timer = config.timeout;
      options.timerProgressBar = true;
      options.showCloseButton = false;
      if (typeof options.showConfirmButton !== 'boolean') {
        options.showConfirmButton = false;
      }
    } else {
      delete options.timer;
      options.timerProgressBar = false;
      options.showCloseButton = true;
      if (type === 'question') {
        options.showConfirmButton = true;
        options.showCancelButton = typeof options.showCancelButton === 'boolean' ? options.showCancelButton : true;
        options.confirmButtonText = options.confirmButtonText || 'OK';
        options.cancelButtonText = options.cancelButtonText || 'Cancel';
        options.toast = false;
      } else if (typeof options.showConfirmButton !== 'boolean') {
        options.showConfirmButton = false;
      }
    }

    return options;
  }

  function showSwal(type, message, config) {
    var resolved = resolveConfig(message, assign({}, config || {}, { type: type }));
    var options;

    if (!resolved.message) {
      return Promise.resolve(null);
    }

    if (shouldSkip(resolved.message, resolved)) {
      return Promise.resolve({ skipped: true, isDismissed: true });
    }

    if (!window.Swal || typeof window.Swal.fire !== 'function') {
      if (resolved.type === 'question') {
        return Promise.resolve({ isConfirmed: window.confirm(resolved.message) });
      }

      window.alert(resolved.message);
      return Promise.resolve({ fallback: true });
    }

    options = buildSwalOptions(resolved.type, resolved);
    return window.Swal.fire(options);
  }

  function buildToastrOptions(type, config) {
    var typeDefaults = {};

    if (!config.autohide) {
      typeDefaults = {
        timeOut: 0,
        extendedTimeOut: 0,
        tapToDismiss: false
      };
    } else {
      typeDefaults = {
        timeOut: config.timeout,
        extendedTimeOut: Math.max(1000, Math.round(config.timeout / 2))
      };
    }

    return assign({}, toastDefaults, typeDefaults, config.options || {});
  }

  function showToast(type, message, config) {
    var resolved = resolveConfig(message, assign({}, config || {}, { type: type }));
    var options;

    if (!resolved.message) {
      return;
    }

    if (shouldSkip(resolved.message, resolved)) {
      return;
    }

    if (!window.toastr || typeof window.toastr[resolved.type === 'question' ? 'info' : resolved.type] !== 'function') {
      if (window.console && typeof window.console.warn === 'function') {
        window.console.warn('Toast fallback:', resolved.type, resolved.message);
      }
      return;
    }

    options = buildToastrOptions(resolved.type, resolved);
    window.toastr.options = options;
    window.toastr[resolved.type === 'question' ? 'info' : resolved.type](
      resolved.message,
      resolved.title ? String(resolved.title) : ''
    );
  }

  function createChannel(showHandler) {
    var channel = {
      show: function (type, message, config) {
        return showHandler(type, message, config || {});
      }
    };

    notificationTypes.forEach(function (type) {
      channel[type] = function (message, config) {
        return showHandler(type, message, config || {});
      };
    });

    return channel;
  }

  var AppNotify = {
    swal: createChannel(showSwal),
    toast: createChannel(showToast),
    backend: createChannel(showSwal),
    frontend: createChannel(showToast),
    clear: function () {
      if (window.toastr && typeof window.toastr.clear === 'function') {
        window.toastr.clear();
      }
      if (window.Swal && typeof window.Swal.close === 'function') {
        window.Swal.close();
      }
    }
  };

  window.AppNotify = AppNotify;
  window.AppToast = AppNotify.toast;
})(window);
