// SwarmGuard-AI in-iframe interaction wiring.
// Injected into every /screens/*.html so the static designs behave like a real app.
(function () {
  var NAV_MAP = {
    'dashboard': 'dashboard_with_logout_modal_overlay',
    'command center': 'dashboard_with_logout_modal_overlay',
    'overview': 'dashboard_with_logout_modal_overlay',
    'live telemetry': 'live_telemetry_monitoring',
    'telemetry': 'live_telemetry_monitoring',
    'drone monitoring': 'drone_fleet_monitoring',
    'drone fleet': 'drone_fleet_monitoring',
    'fleet': 'drone_fleet_monitoring',
    'threat intelligence': 'threat_intelligence_hub',
    'threats': 'threat_intelligence_hub',
    'incidents': 'active_incidents_list',
    'active incidents': 'active_incidents_list',
    'incident deep analysis': 'incident_deep_analysis_unified_actions_with_access_tags',
    'deep analysis': 'incident_deep_analysis_unified_actions_with_access_tags',
    'drone management': 'drone_management_admin_terminal',
    'drone admin': 'drone_management_admin_terminal',
    'admin terminal': 'drone_management_admin_terminal',
    'settings': 'system_settings_account_security_terminal',
    'system settings': 'system_settings_account_security_terminal',
    'account': 'system_settings_account_security_terminal',
    'profile': 'user_profile',
    'user profile': 'user_profile',
    'logout': 'secure_login',
    'log out': 'secure_login',
    'sign out': 'secure_login',
    'sign in': 'dashboard_with_logout_modal_overlay',
    'log in': 'dashboard_with_logout_modal_overlay',
    'login': 'dashboard_with_logout_modal_overlay',
    'recovery': 'secure_login',
    'view all incidents': 'active_incidents_list',
    'view details': 'incident_deep_analysis_unified_actions_with_access_tags',
    'investigate': 'incident_deep_analysis_unified_actions_with_access_tags',
    'analyze': 'incident_deep_analysis_unified_actions_with_access_tags',
    'back to dashboard': 'dashboard_with_logout_modal_overlay',
    'return to dashboard': 'dashboard_with_logout_modal_overlay',
    'go home': 'dashboard_with_logout_modal_overlay',
    'home': 'dashboard_with_logout_modal_overlay',
    'notifications': 'active_incidents_list',
    'contact technical operations': 'user_profile',
  };

  function navigateTo(slug) {
    var url = '/screens/' + slug;
    try {
      if (window.parent && window.parent !== window) {
        window.parent.postMessage({ type: 'swarmguard:navigate', slug: slug }, '*');
        return;
      }
    } catch (e) {}
    window.location.href = url;
  }

  function normalizeText(el) {
    if (!el) return '';
    return (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
  }

  function slugForElement(el) {
    var direct = el.getAttribute && el.getAttribute('data-nav');
    if (direct) return direct;
    var label = normalizeText(el);
    if (NAV_MAP[label]) return NAV_MAP[label];
    // Try known keys as substring
    var keys = Object.keys(NAV_MAP);
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      if (label === k) return NAV_MAP[k];
    }
    for (var j = 0; j < keys.length; j++) {
      var k2 = keys[j];
      if (label.indexOf(k2) !== -1) return NAV_MAP[k2];
    }
    return null;
  }

  function isInteractive(el) {
    if (!el) return false;
    var tag = el.tagName;
    if (tag === 'A' || tag === 'BUTTON') return true;
    var role = el.getAttribute && el.getAttribute('role');
    return role === 'button' || role === 'link';
  }

  function findInteractiveAncestor(el) {
    var cur = el;
    while (cur && cur !== document.body) {
      if (isInteractive(cur)) return cur;
      cur = cur.parentElement;
    }
    return null;
  }

  // Auth Guard
  if (window.location.pathname.indexOf('secure_login') === -1) {
    if (!localStorage.getItem('swarmguard_token')) {
      if (window.parent && window.parent !== window) {
        window.parent.postMessage({ type: 'swarmguard:navigate', slug: 'secure_login' }, '*');
      } else {
        window.location.href = '/screens/secure_login';
      }
    }
  }

  // Global Auth Headers Helper
  window.getAuthHeaders = function() {
    return { 'Authorization': 'Bearer ' + localStorage.getItem('swarmguard_token') };
  };

  document.addEventListener(
    'click',
    function (ev) {
      var target = findInteractiveAncestor(ev.target);
      if (!target) return;

      // Login form submit button on secure_login
      if (target.tagName === 'BUTTON' && target.type === 'submit') {
        // Let the secure_login.html handle its own submit logic
        return;
      }

      var slug = slugForElement(target);
      if (slug) {
        ev.preventDefault();
        navigateTo(slug);
      } else if (target.tagName === 'A') {
        var href = target.getAttribute('href') || '';
        if (href === '#' || href === '') {
          ev.preventDefault();
        }
      }
    },
    true,
  );
})();
