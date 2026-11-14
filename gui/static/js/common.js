(function() {
  var saved = null;
  try { saved = localStorage.getItem('deckgen-theme'); } catch (e) {}
  var dark = saved ? saved === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
})();
(function() {
  var saved = null;
  try { saved = localStorage.getItem('deckgen-panel-collapsed'); } catch (e) {}
  var collapsed = saved === null ? window.matchMedia('(max-width: 900px)').matches : saved === '1';
  if (collapsed) document.documentElement.setAttribute('data-panel-collapsed', '');
})();

const themeToggle = document.getElementById('theme-toggle');
const panelToggle = document.getElementById('panel-toggle');
const panelRailToggle = document.getElementById('panel-rail-toggle');

function applyTheme(theme) {
  const dark = theme === 'dark';
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  if (themeToggle) {
    themeToggle.textContent = dark ? '☀' : '🌙';
    const label = dark ? 'Switch to light theme' : 'Switch to dark theme';
    themeToggle.title = label;
    themeToggle.setAttribute('aria-label', label);
    themeToggle.setAttribute('aria-pressed', dark ? 'true' : 'false');
  }
}

function currentTheme() {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
}

function applyPanelCollapsed(collapsed) {
  document.documentElement.toggleAttribute('data-panel-collapsed', collapsed);
  [panelToggle, panelRailToggle].forEach(function(btn) {
    if (!btn) return;
    btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  });
  if (panelToggle) {
    const label = collapsed ? 'Show' : 'Hide';
    panelToggle.title = label + ' options panel';
    panelToggle.setAttribute('aria-label', label + ' options panel');
    panelToggle.textContent = collapsed ? '»' : '«';
  }
  if (panelRailToggle) {
    panelRailToggle.title = 'Show options panel';
    panelRailToggle.setAttribute('aria-label', 'Show options panel');
  }
}

function isPanelCollapsed() {
  return document.documentElement.hasAttribute('data-panel-collapsed');
}

applyTheme(currentTheme());
applyPanelCollapsed(isPanelCollapsed());

if (themeToggle) {
  themeToggle.addEventListener('click', function() {
    const next = currentTheme() === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    try { localStorage.setItem('deckgen-theme', next); } catch (e) {}
  });
}

function setPanelCollapsed(collapsed, moveFocus) {
  applyPanelCollapsed(collapsed);
  try { localStorage.setItem('deckgen-panel-collapsed', collapsed ? '1' : '0'); } catch (e) {}
  if (moveFocus) {
    const target = collapsed ? panelRailToggle : panelToggle;
    if (target) target.focus();
  }
}

if (panelToggle) {
  panelToggle.addEventListener('click', function() { setPanelCollapsed(true, true); });
}
if (panelRailToggle) {
  panelRailToggle.addEventListener('click', function() { setPanelCollapsed(false, true); });
}
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape' && isPanelCollapsed() && panelRailToggle) {
    panelRailToggle.focus();
  }
});

// --- Project Save / Load (state_<date>.json) ---
(function() {
  const saveProjectBtn = document.getElementById('nav-save-project-btn');
  const loadProjectBtn = document.getElementById('nav-load-project-btn');
  const cleanAllBtn = document.getElementById('nav-clean-all-btn');
  const loadProjectInput = document.getElementById('nav-load-project-input');

  function readStorageJson(key) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function formatStateDate(d) {
    const pad = function(n) { return String(n).padStart(2, '0'); };
    return (
      d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
      '_' + pad(d.getHours()) + '-' + pad(d.getMinutes()) + '-' + pad(d.getSeconds())
    );
  }

  if (saveProjectBtn) {
    saveProjectBtn.addEventListener('click', function() {
      const dgState = typeof window.__deckgenGetDeckGeneratorState === 'function'
        ? window.__deckgenGetDeckGeneratorState()
        : readStorageJson('deckgen-dg-state');
      const cbState = typeof window.__deckgenGetCardBuilderState === 'function'
        ? window.__deckgenGetCardBuilderState()
        : readStorageJson('deckgen-cb-state');

      const payload = {
        version: 1,
        saved_at: new Date().toISOString(),
        deck_generator: dgState,
        card_builder: cbState,
      };

      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'state_' + formatStateDate(new Date()) + '.json';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
    });
  }

  if (loadProjectBtn && loadProjectInput) {
    loadProjectBtn.addEventListener('click', function() {
      loadProjectInput.value = '';
      loadProjectInput.click();
    });

    loadProjectInput.addEventListener('change', async function() {
      const file = this.files && this.files[0];
      if (!file) return;
      try {
        const text = await file.text();
        const data = JSON.parse(text);
        if (!data || typeof data !== 'object' || (!('deck_generator' in data) && !('card_builder' in data))) {
          alert('Invalid project state file.');
          return;
        }
        if (data.deck_generator) {
          try { localStorage.setItem('deckgen-dg-state', JSON.stringify(data.deck_generator)); } catch (e) {}
          if (typeof window.__deckgenApplyDeckGeneratorState === 'function') {
            window.__deckgenApplyDeckGeneratorState(data.deck_generator);
          }
        }
        if (data.card_builder) {
          try { localStorage.setItem('deckgen-cb-state', JSON.stringify(data.card_builder)); } catch (e) {}
          if (typeof window.__deckgenApplyCardBuilderState === 'function') {
            window.__deckgenApplyCardBuilderState(data.card_builder);
          }
        }
        if (typeof window.__deckgenApplyDeckGeneratorState !== 'function' &&
            typeof window.__deckgenApplyCardBuilderState !== 'function') {
          alert('Project loaded! Open Card Builder or Deck Generator to continue.');
        }
      } catch (err) {
        alert('Error loading project file: ' + err.message);
      }
    });
  }

  if (cleanAllBtn) {
    cleanAllBtn.addEventListener('click', async function() {
      window.__deckgenSkipSaveOnUnload = true;
      try {
        localStorage.removeItem('deckgen-dg-state');
        localStorage.removeItem('deckgen-cb-state');
      } catch (e) {}
      try {
        await fetch('/clear-cache', { method: 'POST' });
      } catch (e) {}
      window.location.href = window.location.pathname;
    });
  }
})();
