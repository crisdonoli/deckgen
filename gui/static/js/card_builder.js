(function () {
  const canvas = document.getElementById("card-canvas");
  const ctx = canvas.getContext("2d");
  const overlay = document.getElementById("loading-overlay");
  const progressStatus = document.getElementById("progress-status");
  const statusMsg = document.getElementById("cb-status-msg");

  const targetDirInput = document.getElementById("cb-target-dir");
  const scryfallInput = document.getElementById("cb-scryfall-input");
  const searchBtn = document.getElementById("cb-search-btn");
  const txtInput = document.getElementById("cb-txt-input");
  const uploadTxtBtn = document.getElementById("cb-upload-txt-btn");
  const cardListEl = document.getElementById("cb-card-list");
  const cardsCountEl = document.getElementById("cb-cards-count");
  const filterCardsInput = document.getElementById("cb-filter-cards");
  const removeCardBtn = document.getElementById("cb-remove-card-btn");

  const interactiveCheck = document.getElementById("cb-interactive-mode");
  const undoBtn = document.getElementById("cb-undo-btn");
  const redoBtn = document.getElementById("cb-redo-btn");
  const resetLayoutBtn = document.getElementById("cb-reset-layout-btn");

  const styleSelect = document.getElementById("cb-style-select");
  const autoLayerBtn = document.getElementById("cb-autolayer-btn");
  const layerPickersContainer = document.getElementById("cb-layer-pickers-container");

  const hoverPreviewBox = document.getElementById("cb-layer-hover-preview");
  const hoverPreviewImg = document.getElementById("cb-layer-hover-img");
  const hoverPreviewCaption = document.getElementById("cb-layer-hover-caption");

  const colorHeaderInput = document.getElementById("cb-color-header");
  const colorOracleInput = document.getElementById("cb-color-oracle");
  const autoContrastBtn = document.getElementById("cb-auto-contrast-btn");

  const artUrlInput = document.getElementById("cb-art-url");
  const artFileInput = document.getElementById("cb-art-file");
  const artScaleInput = document.getElementById("cb-art-scale");
  const artOxInput = document.getElementById("cb-art-ox");
  const artOyInput = document.getElementById("cb-art-oy");

  const fieldName = document.getElementById("cb-field-name");
  const fieldOfficialName = document.getElementById("cb-field-official-name");
  const frameOpacityInput = document.getElementById("cb-frame-opacity");
  const fieldMana = document.getElementById("cb-field-mana");
  const fieldType = document.getElementById("cb-field-type");
  const fieldSet = document.getElementById("cb-field-set");
  const fieldRarity = document.getElementById("cb-field-rarity");
  const fieldOracle = document.getElementById("cb-field-oracle");
  const fieldFlavor = document.getElementById("cb-field-flavor");
  const fieldPower = document.getElementById("cb-field-power");
  const fieldToughness = document.getElementById("cb-field-toughness");
  const fieldArtist = document.getElementById("cb-field-artist");

  const posInputs = {
    artX: document.getElementById("pos-art-x"),
    artY: document.getElementById("pos-art-y"),
    artW: document.getElementById("pos-art-w"),
    artH: document.getElementById("pos-art-h"),
    titleX: document.getElementById("pos-title-x"),
    titleY: document.getElementById("pos-title-y"),
    titleSize: document.getElementById("pos-title-size"),
    manaX: document.getElementById("pos-mana-x"),
    manaY: document.getElementById("pos-mana-y"),
    manaSize: document.getElementById("pos-mana-size"),
    typeX: document.getElementById("pos-type-x"),
    typeY: document.getElementById("pos-type-y"),
    typeSize: document.getElementById("pos-type-size"),
    oracleX: document.getElementById("pos-oracle-x"),
    oracleY: document.getElementById("pos-oracle-y"),
    oracleW: document.getElementById("pos-oracle-w"),
    oracleH: document.getElementById("pos-oracle-h"),
    oracleSize: document.getElementById("pos-oracle-size"),
    ptX: document.getElementById("pos-pt-x"),
    ptY: document.getElementById("pos-pt-y"),
    ptSize: document.getElementById("pos-pt-size"),
  };

  // Calibrated coordinates matching the inner frame margins (with bleed) of Automated Templates
  const DEFAULT_LAYOUT = {
    canvas: { w: 750, h: 1050 },
    art: { x: 64, y: 136, w: 622, h: 446, scale: 1.0, offset_x: 0, offset_y: 0 },
    title: { x: 84, y: 116, max_w: 450, font_size: 28, color: "#111111" },
    mana_cost: { x: 664, y: 116, size: 25, align: "right" },
    type_line: { x: 84, y: 622, max_w: 500, font_size: 23, color: "#111111" },
    set_symbol: { x: 664, y: 614, size: 32, align: "right" },
    oracle_box: { x: 88, y: 658, w: 574, h: 272, font_size: 21, color: "#111111" },
    pt_box: { x: 562, y: 908, w: 123, h: 66 },
    pt_text: { x: 624, y: 941, font_size: 29, color: "#111111" },
    artist: { x: 76, y: 990, font_size: 14, color: "#ffffff" },
  };
  const STATIC_FRAME_GEOMETRY = {
    titleBar: { x: 64, y: 78, w: 622, h: 58, r: 14 },
    artFrame: { x: 64, y: 136, w: 622, h: 446 },
    typeBar: { x: 64, y: 586, w: 622, h: 56, r: 14 },
    oracleFrame: { x: 64, y: 642, w: 622, h: 303 },
    ptFrame: { x: 562, y: 908, w: 123, h: 66, r: 12 },
  };

  const LAYER_DEFINITIONS = [
    { key: "background", label: "Background" },
    { key: "pinlines", label: "Pinlines & Textbox" },
    { key: "name_box", label: "Name & Title Box" },
    { key: "crown", label: "Legendary Crown" },
    { key: "border", label: "Border" },
    { key: "pt_box", label: "PT Box" },
  ];
  const DEFAULT_LAYER_ORDER = LAYER_DEFINITIONS.map((d) => d.key);

  function getCardLayerOrder(card) {
    const raw = Array.isArray(card?.layer_order) ? card.layer_order : [];
    const seen = new Set();
    const out = [];
    raw.forEach((k) => {
      if (DEFAULT_LAYER_ORDER.includes(k) && !seen.has(k)) {
        seen.add(k);
        out.push(k);
      }
    });
    DEFAULT_LAYER_ORDER.forEach((k) => {
      if (!seen.has(k)) out.push(k);
    });
    return out;
  }

  function syncLayerOrderDOM(card) {
    if (!layerPickersContainer) return;
    const order = getCardLayerOrder(card);
    order.forEach((key) => {
      const el = layerPickersContainer.querySelector(`.cb-visual-picker[data-layer-key="${key}"]`);
      if (el) layerPickersContainer.appendChild(el);
    });
  }

  let cards = [];
  let activeIndex = -1;
  let templateCatalog = {};
  const customPickerInstances = {};

  const MAX_CACHE_ENTRIES = 40;
  const imageCache = new Map();
  const transparentLayerCache = new Map();
  const manaGlyphCache = new Map();
  const keyruneGlyphCache = new Map();

  const historyStacks = new Map();
  const MAX_HISTORY = 50;

  let selectedElementKey = "oracle_box";
  let hoveredElementKey = null;
  let dragState = null;
  const HANDLE_SIZE = 10;

  function setCacheBounded(map, key, val) {
    if (map.has(key)) map.delete(key);
    map.set(key, val);
    if (map.size > MAX_CACHE_ENTRIES) {
      const oldestKey = map.keys().next().value;
      map.delete(oldestKey);
    }
  }

  function setLoading(show, text) {
    if (text) progressStatus.textContent = text;
    overlay.classList.toggle("active", show);
  }

  function showStatus(msg, isError) {
    statusMsg.textContent = msg;
    statusMsg.style.color = isError ? "var(--danger)" : "var(--ok)";
  }

  // --- Floating JPG Hover Preview ---
  function showLayerHoverPreview(item, anchorRect) {
    if (!item || !item.url) {
      hideLayerHoverPreview();
      return;
    }
    hoverPreviewImg.src = item.url;
    hoverPreviewCaption.textContent = item.label;
    hoverPreviewBox.hidden = false;

    const previewW = 150;
    const previewH = 228;
    const left = Math.max(10, anchorRect.left - previewW - 12);
    const top = Math.min(window.innerHeight - previewH - 12, Math.max(52, anchorRect.top - 30));
    hoverPreviewBox.style.left = `${left}px`;
    hoverPreviewBox.style.top = `${top}px`;
  }

  function hideLayerHoverPreview() {
    hoverPreviewBox.hidden = true;
  }

  function initLayerPickers() {
    layerPickersContainer.innerHTML = "";
    LAYER_DEFINITIONS.forEach((def) => {
      const wrapper = document.createElement("div");
      wrapper.className = "cb-visual-picker";
      wrapper.dataset.layerKey = def.key;
      wrapper.innerHTML = `
        <div class="cb-visual-picker-row">
          <span class="cb-visual-picker-label">${def.label}</span>
          <button type="button" class="cb-visual-picker-trigger" data-layer="${def.key}">
            <span class="cb-vp-text">None</span>
            <span class="cb-vp-caret">▾</span>
          </button>
          <div style="display: flex; gap: 2px; flex-shrink: 0;">
            <button type="button" class="ps-mini-btn cb-layer-move" data-dir="-1" title="Move back (draw earlier)">↑</button>
            <button type="button" class="ps-mini-btn cb-layer-move" data-dir="1" title="Move forward (draw later)">↓</button>
          </div>
        </div>
        <div class="ps-slider-row cb-layer-opacity-row" style="margin-top: 3px; margin-bottom: 4px;">
          <span style="font-size: 10px; opacity: 0.8;">Opacity</span>
          <input type="range" class="cb-layer-opacity" data-layer="${def.key}" min="0" max="1" step="0.05" value="1">
          <span class="ps-val cb-layer-opacity-val" style="min-width: 34px;">100%</span>
        </div>
        <div class="cb-visual-picker-menu" hidden>
          <input type="text" class="ps-input cb-vp-search" placeholder="Filter layer...">
          <ul class="cb-vp-list"></ul>
        </div>
      `;
      layerPickersContainer.appendChild(wrapper);

      const trigger = wrapper.querySelector(".cb-visual-picker-trigger");
      const textSpan = wrapper.querySelector(".cb-vp-text");
      const menu = wrapper.querySelector(".cb-visual-picker-menu");
      const searchInput = wrapper.querySelector(".cb-vp-search");
      const listEl = wrapper.querySelector(".cb-vp-list");
      const opacitySlider = wrapper.querySelector(".cb-layer-opacity");
      const opacityVal = wrapper.querySelector(".cb-layer-opacity-val");
      const moveBtns = wrapper.querySelectorAll(".cb-layer-move");

      moveBtns.forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          if (activeIndex < 0 || !cards[activeIndex]) return;
          const card = cards[activeIndex];
          const dir = parseInt(btn.dataset.dir, 10);
          const order = getCardLayerOrder(card);
          const idx = order.indexOf(def.key);
          const swapIdx = idx + dir;
          if (idx < 0 || swapIdx < 0 || swapIdx >= order.length) return;
          pushUndoState();
          const tmp = order[idx];
          order[idx] = order[swapIdx];
          order[swapIdx] = tmp;
          card.layer_order = order;
          syncLayerOrderDOM(card);
          renderCardCanvas();
        });
      });

      if (opacitySlider) {
        opacitySlider.addEventListener("focus", () => pushUndoState());
        opacitySlider.addEventListener("input", () => {
          if (activeIndex < 0 || !cards[activeIndex]) return;
          const card = cards[activeIndex];
          if (!card.layer_opacities) card.layer_opacities = {};
          const v = Math.max(0, Math.min(1, parseFloat(opacitySlider.value)));
          card.layer_opacities[def.key] = Number.isFinite(v) ? v : 1.0;
          if (opacityVal) opacityVal.textContent = Math.round(card.layer_opacities[def.key] * 100) + "%";
          renderCardCanvas();
        });
      }

      let currentItems = [];
      let currentValue = "";

      function renderMenuItems(filter = "") {
        const q = filter.toLowerCase().trim();
        listEl.innerHTML = "";

        const noneLi = document.createElement("li");
        noneLi.className = "cb-vp-option" + (currentValue === "" ? " selected" : "");
        noneLi.textContent = "None";
        noneLi.addEventListener("mouseenter", hideLayerHoverPreview);
        noneLi.addEventListener("click", () => {
          setValue("");
          menu.hidden = true;
          onLayerChanged(def.key, "");
        });
        listEl.appendChild(noneLi);

        currentItems.forEach((item) => {
          const fullTitle = item.folder && item.folder !== "." ? `${item.label} (${item.folder})` : item.label;
          if (q && !fullTitle.toLowerCase().includes(q)) return;
          const li = document.createElement("li");
          li.className = "cb-vp-option" + (currentValue === item.rel_path ? " selected" : "");
          li.textContent = fullTitle;

          li.addEventListener("mouseenter", () => {
            showLayerHoverPreview(item, li.getBoundingClientRect());
          });
          li.addEventListener("mouseleave", hideLayerHoverPreview);
          li.addEventListener("click", () => {
            hideLayerHoverPreview();
            setValue(item.rel_path);
            menu.hidden = true;
            onLayerChanged(def.key, item.rel_path);
          });
          listEl.appendChild(li);
        });
      }

      function setValue(relPath) {
        currentValue = relPath || "";
        const found = currentItems.find((i) => i.rel_path === currentValue);
        textSpan.textContent = found ? found.label : "None";
        trigger.title = found ? found.rel_path : "None";
      }

      trigger.addEventListener("click", (e) => {
        e.stopPropagation();
        const wasHidden = menu.hidden;
        document.querySelectorAll(".cb-visual-picker-menu").forEach((m) => (m.hidden = true));
        hideLayerHoverPreview();
        if (wasHidden) {
          menu.hidden = false;
          searchInput.value = "";
          renderMenuItems("");
          searchInput.focus();
        }
      });

      trigger.addEventListener("mouseenter", () => {
        const found = currentItems.find((i) => i.rel_path === currentValue);
        if (found) showLayerHoverPreview(found, trigger.getBoundingClientRect());
      });
      trigger.addEventListener("mouseleave", hideLayerHoverPreview);

      searchInput.addEventListener("input", () => renderMenuItems(searchInput.value));
      searchInput.addEventListener("click", (e) => e.stopPropagation());

      customPickerInstances[def.key] = {
        setItems(items, selectedVal) {
          currentItems = items || [];
          setValue(selectedVal);
        },
        setValue,
      };
    });

    document.addEventListener("click", () => {
      document.querySelectorAll(".cb-visual-picker-menu").forEach((m) => (m.hidden = true));
      hideLayerHoverPreview();
    });
  }

  function onLayerChanged(layerKey, relPath) {
    if (activeIndex < 0) return;
    pushUndoState();
    if (!cards[activeIndex].frame_components) {
      cards[activeIndex].frame_components = { style: styleSelect.value };
    }
    cards[activeIndex].frame_components[layerKey] = relPath;
    renderCardCanvas();
  }

  // --- Undo / Redo History ---
  function getCardHistory(idx) {
    if (!historyStacks.has(idx)) {
      historyStacks.set(idx, { undo: [], redo: [] });
    }
    return historyStacks.get(idx);
  }

  function cloneCardState(card) {
    return JSON.parse(
      JSON.stringify({
        name: card.name,
        mana_cost: card.mana_cost,
        type_line: card.type_line,
        set: card.set,
        rarity: card.rarity,
        oracle_text: card.oracle_text,
        flavor_text: card.flavor_text,
        power: card.power,
        toughness: card.toughness,
        artist: card.artist,
        art_crop_url: card.art_crop_url,
        frame_components: card.frame_components,
        layout: card.layout,
        custom_layout: Boolean(card.custom_layout),
      })
    );
  }

  function applyCardSnapshot(card, snap) {
    Object.assign(card, JSON.parse(JSON.stringify(snap)));
  }

  function pushUndoState(customSnapshot = null) {
    if (activeIndex < 0 || !cards[activeIndex]) return;
    const hist = getCardHistory(activeIndex);
    const snap = customSnapshot || cloneCardState(cards[activeIndex]);
    if (hist.undo.length > 0) {
      const last = hist.undo[hist.undo.length - 1];
      if (JSON.stringify(last) === JSON.stringify(snap)) return;
    }
    hist.undo.push(snap);
    if (hist.undo.length > MAX_HISTORY) hist.undo.shift();
    hist.redo = [];
    updateUndoRedoButtons();
  }

  function updateUndoRedoButtons() {
    if (activeIndex < 0) {
      if (undoBtn) undoBtn.disabled = true;
      if (redoBtn) redoBtn.disabled = true;
      return;
    }
    const hist = getCardHistory(activeIndex);
    if (undoBtn) undoBtn.disabled = hist.undo.length === 0;
    if (redoBtn) redoBtn.disabled = hist.redo.length === 0;
  }

  function performUndo() {
    if (activeIndex < 0 || !cards[activeIndex]) return;
    const hist = getCardHistory(activeIndex);
    if (hist.undo.length === 0) return;
    hist.redo.push(cloneCardState(cards[activeIndex]));
    applyCardSnapshot(cards[activeIndex], hist.undo.pop());
    refreshInputsFromActiveCard();
    updateUndoRedoButtons();
    renderCardList();
    renderCardCanvas();
  }

  function performRedo() {
    if (activeIndex < 0 || !cards[activeIndex]) return;
    const hist = getCardHistory(activeIndex);
    if (hist.redo.length === 0) return;
    hist.undo.push(cloneCardState(cards[activeIndex]));
    applyCardSnapshot(cards[activeIndex], hist.redo.pop());
    refreshInputsFromActiveCard();
    updateUndoRedoButtons();
    renderCardList();
    renderCardCanvas();
  }

  if (undoBtn) undoBtn.addEventListener("click", performUndo);
  if (redoBtn) redoBtn.addEventListener("click", performRedo);

  window.addEventListener("keydown", (evt) => {
    const tag = document.activeElement ? document.activeElement.tagName.toLowerCase() : "";
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    if ((evt.ctrlKey || evt.metaKey) && evt.key.toLowerCase() === "z") {
      evt.preventDefault();
      if (evt.shiftKey) performRedo();
      else performUndo();
    } else if ((evt.ctrlKey || evt.metaKey) && evt.key.toLowerCase() === "y") {
      evt.preventDefault();
      performRedo();
    }
  });

  // Inspector Tabs
  document.querySelectorAll(".cb-editor-panel .ps-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tab;
      document.querySelectorAll(".cb-editor-panel .ps-tab").forEach((t) => {
        t.classList.toggle("active", t === tab);
      });
      document.querySelectorAll(".cb-editor-panel .ps-tab-panel").forEach((p) => {
        p.classList.toggle("active", p.dataset.panel === target);
      });
    });
  });

  function getIconGlyph(className, cache) {
    if (cache.has(className)) {
      const cached = cache.get(className);
      if (cached && cached.char) return cached;
    }
    const span = document.createElement("i");
    span.className = className;
    span.style.position = "fixed";
    span.style.left = "-9999px";
    span.style.top = "-9999px";
    document.body.appendChild(span);

    const beforeStyle = window.getComputedStyle(span, "::before");
    const baseStyle = window.getComputedStyle(span);
    const content = beforeStyle.content;
    const fontFamily = beforeStyle.fontFamily && beforeStyle.fontFamily !== "none"
      ? beforeStyle.fontFamily
      : baseStyle.fontFamily;

    document.body.removeChild(span);

    let char = "";
    if (content && content !== "none" && content !== "normal") {
      char = content.replace(/^["']|["']$/g, "");
      if (char.startsWith("\\")) {
        const code = parseInt(char.slice(1), 16);
        if (!Number.isNaN(code)) char = String.fromCodePoint(code);
      }
    }
    const result = { char, fontFamily };
    if (char) cache.set(className, result);
    return result;
  }

  function symbolToManaClass(sym) {
    const clean = sym.replace(/[{}]/g, "").toLowerCase().replace("/", "");
    if (clean === "t") return "ms ms-tap";
    if (clean === "q") return "ms ms-untap";
    return `ms ms-${clean}`;
  }

  function getManaCircleColor(sym) {
    const s = sym.replace(/[{}]/g, "").toUpperCase();
    if (s.includes("W")) return "#f8f6d8";
    if (s.includes("U")) return "#c1d7e9";
    if (s.includes("B")) return "#bab1ab";
    if (s.includes("R")) return "#e49977";
    if (s.includes("G")) return "#a3c095";
    return "#cbc2bf";
  }

  function isLightColor(hex) {
    if (!hex) return false;
    const clean = hex.replace("#", "");
    if (clean.length < 6) return false;
    const r = parseInt(clean.slice(0, 2), 16);
    const g = parseInt(clean.slice(2, 4), 16);
    const b = parseInt(clean.slice(4, 6), 16);
    return (r * 299 + g * 587 + b * 114) / 1000 > 145;
  }

  function relPathToAssetUrl(relPath) {
    if (!relPath) return "";
    if (relPath.startsWith("data:") || relPath.startsWith("http") || relPath.startsWith("/assets/")) {
      return relPath;
    }
    return "/assets/" + relPath.split("/").map(encodeURIComponent).join("/");
  }

  function loadImage(src) {
    if (!src) return Promise.resolve(null);
    if (imageCache.has(src)) return Promise.resolve(imageCache.get(src));
    return new Promise((resolve) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        setCacheBounded(imageCache, src, img);
        resolve(img);
      };
      img.onerror = () => resolve(null);
      img.src = src;
    });
  }

  async function loadTransparentLayerJpg(relPath) {
    if (!relPath) return null;
    if (transparentLayerCache.has(relPath)) {
      return transparentLayerCache.get(relPath);
    }
    const url = relPathToAssetUrl(relPath);
    const img = await loadImage(url);
    if (!img) return null;

    const off = document.createElement("canvas");
    off.width = 750;
    off.height = 1050;
    const octx = off.getContext("2d");
    octx.drawImage(img, 0, 0, 750, 1050);

    try {
      const imgData = octx.getImageData(0, 0, 750, 1050);
      const d = imgData.data;
      const cIndices = [0, (750 - 1) * 4, (1050 - 1) * 750 * 4, (1050 * 750 - 1) * 4];
      let rSum = 0, gSum = 0, bSum = 0;
      cIndices.forEach((idx) => {
        rSum += d[idx];
        gSum += d[idx + 1];
        bSum += d[idx + 2];
      });
      const br = rSum / 4, bg = gSum / 4, bb = bSum / 4;
      const isWhiteBg = br > 235 && bg > 235 && bb > 235;
      const isBlackBg = br < 20 && bg < 20 && bb < 20;

      if (isWhiteBg || isBlackBg) {
        const tol = 28;
        for (let i = 0; i < d.length; i += 4) {
          const diff = Math.max(Math.abs(d[i] - br), Math.abs(d[i + 1] - bg), Math.abs(d[i + 2] - bb));
          if (diff < tol) {
            d[i + 3] = 0;
          } else if (diff < tol + 24) {
            d[i + 3] = Math.min(d[i + 3], Math.round(((diff - tol) / 24) * 255));
          }
        }
        octx.putImageData(imgData, 0, 0);
      }
    } catch (e) {
      console.warn("Chroma-key skipped:", e);
    }

    setCacheBounded(transparentLayerCache, relPath, off);
    return off;
  }

  async function fetchTemplateCatalog() {
    try {
      const res = await fetch("/api/card-builder/templates");
      const data = await res.json();
      templateCatalog = data.catalog || {};
      styleSelect.innerHTML = '<option value="">-- Procedural Frame (No JPG) --</option>';
      Object.keys(templateCatalog).forEach((styleKey) => {
        const opt = document.createElement("option");
        opt.value = styleKey;
        opt.textContent = styleKey.replace("Automated Templates/", "Auto / ").replace("Manual Templates/", "Manual / ");
        styleSelect.appendChild(opt);
      });
    } catch (e) {
      console.error("Error loading template catalog:", e);
    }
  }

  function populateComponentDropdowns(styleKey, selectedComponents = {}) {
    const cats = templateCatalog[styleKey] || {};
    LAYER_DEFINITIONS.forEach((def) => {
      const picker = customPickerInstances[def.key];
      if (!picker) return;
      picker.setItems(cats[def.key] || [], selectedComponents[def.key] || "");
    });
  }

  function autoPickClientLayers(card, styleKey) {
    const cats = templateCatalog[styleKey];
    if (!cats) return;
    const tl = (card.type_line || "").toLowerCase();
    const isLand = tl.includes("land");
    const isLeg = tl.includes("legendary");
    const hasPt = card.power !== null && card.power !== undefined && String(card.power).trim() !== "";
    const colors = card.colors && card.colors.length ? card.colors : card.color_identity || [];

    let colorToken = "Colourless";
    let broadToken = "Colourless";
    if (colors.length === 1) {
      colorToken = colors[0];
      broadToken = colors[0];
    } else if (colors.length === 2) {
      const guilds = ["WU", "UB", "BR", "RG", "GW", "WB", "BG", "GU", "UR", "RW"];
      const foundG = guilds.find((g) => g.includes(colors[0]) && g.includes(colors[1]));
      colorToken = foundG || "Gold";
      broadToken = "Gold";
    } else if (colors.length > 2) {
      colorToken = "Gold";
      broadToken = "Gold";
    } else if (tl.includes("artifact")) {
      colorToken = "Artifact";
      broadToken = "Artifact";
    } else if (isLand) {
      colorToken = "Land";
      broadToken = "Land";
    }

    const pick = (list, tokens, folderSub = null) => {
      if (!list || !list.length) return "";
      let pool = list;
      if (folderSub) {
        const sub = list.filter((i) => i.folder.toLowerCase().includes(folderSub.toLowerCase()));
        if (sub.length) pool = sub;
      }
      for (const tk of tokens) {
        const exact = pool.find((i) => new RegExp(`^\\d+_${tk}(_\\[oculta\\])?$`, "i").test(i.label));
        if (exact) return exact.rel_path;
        const part = pool.find((i) => i.label.toLowerCase().includes(tk.toLowerCase()));
        if (part) return part.rel_path;
      }
      return pool[0].rel_path;
    };

    const searchTokens = styleKey.toLowerCase().includes("basic")
      ? [card.name, colorToken, broadToken, "Gold"]
      : [colorToken, broadToken, "Gold", "Artifact", "Land"];

    card.frame_components = {
      style: styleKey,
      background: pick(cats.background, isLand ? ["Land", ...searchTokens] : searchTokens, "Background"),
      pinlines: pick(cats.pinlines, searchTokens, isLand ? "Land Pinlines" : "Pinlines & Textbox"),
      name_box: pick(cats.name_box, isLand ? ["Land", broadToken, colorToken] : [broadToken, colorToken, "Gold"]),
      crown: isLeg ? pick(cats.crown, [colorToken, broadToken, "Gold"]) : "",
      border: pick(cats.border, isLeg ? ["Legendary Border"] : ["Normal Border"]),
      pt_box: hasPt ? pick(cats.pt_box, [broadToken, colorToken, "Gold", "Artifact"]) : "",
    };
    populateComponentDropdowns(styleKey, card.frame_components);
  }

  function renderCardList() {
    const q = filterCardsInput.value.toLowerCase().trim();
    cardListEl.innerHTML = "";
    cardsCountEl.textContent = cards.length;

    if (cards.length === 0) {
      cardListEl.innerHTML = '<li class="cb-empty-item">No cards loaded.</li>';
      return;
    }

    cards.forEach((card, idx) => {
      if (q && !card.name.toLowerCase().includes(q) && !(card.type_line || "").toLowerCase().includes(q)) {
        return;
      }
      const li = document.createElement("li");
      li.className = "cb-card-item" + (idx === activeIndex ? " active" : "");
      const manaIconsHtml = (card.mana_cost || "").replace(/\{([^}]+)\}/g, (_, s) => {
        const cls = symbolToManaClass(s);
        return `<i class="${cls} ms-cost ms-shadow"></i>`;
      });
      li.innerHTML = `
        <div class="cb-card-item-main">
          <span class="cb-card-qty">${card.count || 1}x</span>
          <span class="cb-card-name">${card.name}</span>
        </div>
        <div class="cb-card-item-meta">
          <span class="cb-card-mana">${manaIconsHtml}</span>
          <i class="ss ss-${(card.set || "mtg").toLowerCase()} ss-${card.rarity || "common"}"></i>
        </div>
      `;
      li.addEventListener("click", () => selectCard(idx));
      cardListEl.appendChild(li);
    });
  }

  function populatePositionInputsFromLayout(L) {
    artScaleInput.value = L.art.scale ?? 1.0;
    artOxInput.value = Math.round(L.art.offset_x ?? 0);
    artOyInput.value = Math.round(L.art.offset_y ?? 0);
    document.getElementById("val-art-scale").textContent = Number(artScaleInput.value).toFixed(2) + "x";
    document.getElementById("val-art-ox").textContent = artOxInput.value + "px";
    document.getElementById("val-art-oy").textContent = artOyInput.value + "px";

    posInputs.artX.value = Math.round(L.art.x);
    posInputs.artY.value = Math.round(L.art.y);
    posInputs.artW.value = Math.round(L.art.w);
    posInputs.artH.value = Math.round(L.art.h);
    posInputs.titleX.value = Math.round(L.title.x);
    posInputs.titleY.value = Math.round(L.title.y);
    posInputs.titleSize.value = Math.round(L.title.font_size);
    posInputs.manaX.value = Math.round(L.mana_cost.x);
    posInputs.manaY.value = Math.round(L.mana_cost.y);
    posInputs.manaSize.value = Math.round(L.mana_cost.size);
    posInputs.typeX.value = Math.round(L.type_line.x);
    posInputs.typeY.value = Math.round(L.type_line.y);
    posInputs.typeSize.value = Math.round(L.type_line.font_size);
    posInputs.oracleX.value = Math.round(L.oracle_box.x);
    posInputs.oracleY.value = Math.round(L.oracle_box.y);
    posInputs.oracleW.value = Math.round(L.oracle_box.w);
    posInputs.oracleH.value = Math.round(L.oracle_box.h);
    posInputs.oracleSize.value = Math.round(L.oracle_box.font_size);
    posInputs.ptX.value = Math.round(L.pt_text.x);
    posInputs.ptY.value = Math.round(L.pt_text.y);
    posInputs.ptSize.value = Math.round(L.pt_text.font_size);

    if (colorHeaderInput) colorHeaderInput.value = L.title.color || "#111111";
    if (colorOracleInput) colorOracleInput.value = L.oracle_box.color || "#111111";
  }

  function getLayerOpacity(card, key) {
    if (card?.layer_opacities && card.layer_opacities[key] !== undefined) {
      const v = Number(card.layer_opacities[key]);
      return Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 1.0;
    }
    const fb = card?.frame_opacity !== undefined ? Number(card.frame_opacity) : 1.0;
    return Number.isFinite(fb) ? Math.max(0, Math.min(1, fb)) : 1.0;
  }

  function syncLayerOpacitySliders(card) {
    LAYER_DEFINITIONS.forEach((def) => {
      const slider = layerPickersContainer.querySelector(`.cb-layer-opacity[data-layer="${def.key}"]`);
      if (!slider) return;
      const op = getLayerOpacity(card, def.key);
      slider.value = op;
      const valEl = slider.parentElement?.querySelector(".cb-layer-opacity-val");
      if (valEl) valEl.textContent = Math.round(op * 100) + "%";
    });
  }

  function refreshInputsFromActiveCard() {
    if (activeIndex < 0 || !cards[activeIndex]) return;
    const card = cards[activeIndex];
    document.getElementById("cb-editor-title").textContent = card.name;
    fieldName.value = card.name || "";
    if (fieldOfficialName) fieldOfficialName.value = card.official_name || "";
    const fOp = card.frame_opacity !== undefined ? Number(card.frame_opacity) : 1.0;
    if (frameOpacityInput) {
      frameOpacityInput.value = Number.isFinite(fOp) ? fOp : 1.0;
      const valEl = document.getElementById("val-frame-opacity");
      if (valEl) valEl.textContent = Math.round((Number.isFinite(fOp) ? fOp : 1.0) * 100) + "%";
    }
    syncLayerOpacitySliders(card);
    syncLayerOrderDOM(card);
    fieldMana.value = card.mana_cost || "";
    fieldType.value = card.type_line || "";
    fieldSet.value = card.set || "";
    fieldRarity.value = card.rarity || "common";
    fieldOracle.value = card.oracle_text || "";
    fieldFlavor.value = card.flavor_text || "";
    fieldPower.value = card.power ?? "";
    fieldToughness.value = card.toughness ?? "";
    fieldArtist.value = card.artist || "";
    artUrlInput.value = card.art_crop_url || "";
    populatePositionInputsFromLayout(card.layout);

    if (!card.frame_components) {
      autoPickClientLayers(card, "Automated Templates/normal");
    } else {
      const st = card.frame_components.style || "Automated Templates/normal";
      styleSelect.value = templateCatalog[st] ? st : "";
      populateComponentDropdowns(st, card.frame_components);
    }
  }

  function normalizeCardLayout(card, forceReset = false) {
    const base = JSON.parse(JSON.stringify(DEFAULT_LAYOUT));
    if (!card.layout || forceReset || !card.custom_layout) {
      const prevHeaderColor = card.layout?.title?.color || base.title.color;
      const prevOracleColor = card.layout?.oracle_box?.color || base.oracle_box.color;
      card.layout = base;
      card.layout.title.color = prevHeaderColor;
      card.layout.type_line.color = prevHeaderColor;
      card.layout.pt_text.color = prevHeaderColor;
      card.layout.oracle_box.color = prevOracleColor;
    } else {
      for (const section of Object.keys(base)) {
        if (!card.layout[section] || typeof card.layout[section] !== "object") {
          card.layout[section] = base[section];
        } else {
          card.layout[section] = { ...base[section], ...card.layout[section] };
        }
      }
    }

    // Dynamically fit title width so it never collides with mana symbols
    const manaTokens = (card.mana_cost || "").match(/\{[^}]+\}/g) || [];
    const manaTotalWidth = manaTokens.length * (card.layout.mana_cost.size + 5);
    const availableTitleW = card.layout.mana_cost.x - manaTotalWidth - card.layout.title.x - 12;
    if (availableTitleW > 120) {
      card.layout.title.max_w = availableTitleW;
    }

    // Dynamically fit type line width so it never collides with the expansion symbol
    const availableTypeW = card.layout.set_symbol.x - (card.layout.set_symbol.size || 30) - card.layout.type_line.x - 12;
    if (availableTypeW > 120) {
      card.layout.type_line.max_w = availableTypeW;
    }
  }

  function selectCard(index) {
    if (index < 0 || index >= cards.length) return;
    activeIndex = index;
    const card = cards[activeIndex];
    normalizeCardLayout(card);
    renderCardList();
    refreshInputsFromActiveCard();
    updateUndoRedoButtons();
    renderCardCanvas();
    if (typeof saveCardBuilderState === "function") saveCardBuilderState();
  }

  if (removeCardBtn) {
    removeCardBtn.addEventListener("click", () => {
      if (activeIndex < 0 || !cards[activeIndex]) return;
      cards.splice(activeIndex, 1);
      historyStacks.clear();
      if (cards.length === 0) {
        activeIndex = -1;
        renderCardList();
        updateUndoRedoButtons();
        renderCardCanvas();
        return;
      }
      selectCard(Math.min(activeIndex, cards.length - 1));
    });
  }

  // --- Font Color & Auto-Contrast ---
  function applyFontColor(group, hexColor) {
    if (activeIndex < 0 || !cards[activeIndex]) return;
    pushUndoState();
    const L = cards[activeIndex].layout;
    if (group === "header") {
      L.title.color = hexColor;
      L.type_line.color = hexColor;
      L.pt_text.color = hexColor;
      if (colorHeaderInput) colorHeaderInput.value = hexColor;
    } else if (group === "oracle") {
      L.oracle_box.color = hexColor;
      if (colorOracleInput) colorOracleInput.value = hexColor;
    }
    renderCardCanvas();
  }

  if (colorHeaderInput) {
    colorHeaderInput.addEventListener("focus", () => pushUndoState());
    colorHeaderInput.addEventListener("input", () => applyFontColor("header", colorHeaderInput.value));
  }
  if (colorOracleInput) {
    colorOracleInput.addEventListener("focus", () => pushUndoState());
    colorOracleInput.addEventListener("input", () => applyFontColor("oracle", colorOracleInput.value));
  }

  document.querySelectorAll(".cb-preset-color").forEach((btn) => {
    btn.addEventListener("click", () => {
      applyFontColor(btn.dataset.target, btn.dataset.color);
    });
  });

  if (autoContrastBtn) {
    autoContrastBtn.addEventListener("click", async () => {
      if (activeIndex < 0 || !cards[activeIndex]) return;
      await renderCardCanvas(true);
      const L = cards[activeIndex].layout;

      function sampleRegionBrightness(x, y, w, h) {
        const sx = Math.max(0, Math.min(740, Math.round(x)));
        const sy = Math.max(0, Math.min(1040, Math.round(y)));
        const sw = Math.max(4, Math.min(750 - sx, Math.round(w)));
        const sh = Math.max(4, Math.min(1050 - sy, Math.round(h)));
        const data = ctx.getImageData(sx, sy, sw, sh).data;
        let lumSum = 0;
        const step = 16;
        let count = 0;
        for (let i = 0; i < data.length; i += 4 * step) {
          lumSum += (data[i] * 299 + data[i + 1] * 587 + data[i + 2] * 114) / 1000;
          count++;
        }
        return count ? lumSum / count : 128;
      }

      const headerLum = sampleRegionBrightness(L.title.x, L.title.y - 24, 320, 32);
      const oracleLum = sampleRegionBrightness(L.oracle_box.x, L.oracle_box.y, L.oracle_box.w, L.oracle_box.h);

      pushUndoState();
      const headerColor = headerLum < 120 ? "#ffffff" : "#111111";
      const oracleColor = oracleLum < 120 ? "#ffffff" : "#111111";
      L.title.color = headerColor;
      L.type_line.color = headerColor;
      L.pt_text.color = headerColor;
      L.oracle_box.color = oracleColor;

      if (colorHeaderInput) colorHeaderInput.value = headerColor;
      if (colorOracleInput) colorOracleInput.value = oracleColor;
      renderCardCanvas(false);
    });
  }

  function getInteractiveRegions(card) {
    const L = card.layout;
    const regions = [];

    const manaTokens = (card.mana_cost || "").match(/\{[^}]+\}/g) || [];
    const manaCount = Math.max(1, manaTokens.length);
    const manaStep = L.mana_cost.size + 5;
    const manaW = manaCount * manaStep;
    const manaH = L.mana_cost.size * 1.15;
    regions.push({
      key: "mana_cost",
      label: "Mana Cost",
      x: L.mana_cost.x - manaW,
      y: L.mana_cost.y - L.mana_cost.size * 0.88,
      w: manaW,
      h: manaH,
      resizable: true,
    });

    regions.push({
      key: "title",
      label: "Card Title",
      x: L.title.x,
      y: L.title.y - L.title.font_size * 0.9,
      w: L.title.max_w || 470,
      h: L.title.font_size * 1.15,
      resizable: true,
    });

    const setSize = L.set_symbol.size || 30;
    const setY = L.set_symbol.y ?? L.type_line.y;
    regions.push({
      key: "set_symbol",
      label: "Set Symbol",
      x: L.set_symbol.x - setSize * 1.15,
      y: setY - setSize * 0.75,
      w: setSize * 1.2,
      h: setSize * 1.15,
      resizable: true,
    });

    regions.push({
      key: "type_line",
      label: "Type Line",
      x: L.type_line.x,
      y: L.type_line.y - L.type_line.font_size * 0.9,
      w: L.type_line.max_w || 520,
      h: L.type_line.font_size * 1.15,
      resizable: true,
    });

    if (card.power !== null && card.power !== undefined && String(card.power).trim() !== "") {
      const ptFontSize = L.pt_text.font_size || 31;
      const ptTextW = 90;
      const ptTextH = ptFontSize * 1.2;
      regions.push({
        key: "pt_text",
        label: "Power / Toughness",
        x: L.pt_text.x - ptTextW / 2,
        y: L.pt_text.y - ptTextH / 2,
        w: ptTextW,
        h: ptTextH,
        resizable: true,
      });
    }

    regions.push({
      key: "oracle_box",
      label: "Oracle Text",
      x: L.oracle_box.x,
      y: L.oracle_box.y,
      w: L.oracle_box.w,
      h: L.oracle_box.h,
      resizable: true,
    });

    regions.push({
      key: "artist",
      label: "Artist",
      x: L.artist.x,
      y: L.artist.y - L.artist.font_size * 0.9,
      w: 260,
      h: L.artist.font_size * 1.25,
      resizable: true,
    });

    regions.push({
      key: "art",
      label: "Artwork (Shift+Drag to Pan)",
      x: L.art.x,
      y: L.art.y,
      w: L.art.w,
      h: L.art.h,
      resizable: true,
    });

    return regions;
  }

  function getHandlesForRegion(r) {
    if (!r || !r.resizable) return [];
    const cx = r.x + r.w / 2;
    const cy = r.y + r.h / 2;
    return [
      { id: "nw", x: r.x, y: r.y, cursor: "nwse-resize" },
      { id: "n", x: cx, y: r.y, cursor: "ns-resize" },
      { id: "ne", x: r.x + r.w, y: r.y, cursor: "nesw-resize" },
      { id: "e", x: r.x + r.w, y: cy, cursor: "ew-resize" },
      { id: "se", x: r.x + r.w, y: r.y + r.h, cursor: "nwse-resize" },
      { id: "s", x: cx, y: r.y + r.h, cursor: "ns-resize" },
      { id: "sw", x: r.x, y: r.y + r.h, cursor: "nesw-resize" },
      { id: "w", x: r.x, y: cy, cursor: "ew-resize" },
    ];
  }

  function drawInteractiveOverlays(card) {
    if (!interactiveCheck || !interactiveCheck.checked) return;
    const regions = getInteractiveRegions(card);

    regions.forEach((r) => {
      const isSelected = r.key === selectedElementKey;
      const isHovered = r.key === hoveredElementKey;
      if (!isSelected && !isHovered) return;

      ctx.save();
      ctx.strokeStyle = isSelected ? "#3b82f6" : "rgba(59, 130, 246, 0.65)";
      ctx.lineWidth = isSelected ? 2.5 : 1.5;
      ctx.setLineDash(isSelected ? [] : [6, 4]);
      ctx.strokeRect(r.x, r.y, r.w, r.h);

      ctx.setLineDash([]);
      ctx.font = "bold 12px sans-serif";
      const tagText = r.label;
      const textW = ctx.measureText(tagText).width + 10;
      const tagY = Math.max(4, r.y - 20);
      ctx.fillStyle = isSelected ? "#2563eb" : "rgba(37, 99, 235, 0.8)";
      ctx.beginPath();
      ctx.roundRect(r.x, tagY, textW, 18, 3);
      ctx.fill();
      ctx.fillStyle = "#ffffff";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(tagText, r.x + 5, tagY + 9);

      if (isSelected) {
        const handles = getHandlesForRegion(r);
        handles.forEach((h) => {
          ctx.fillStyle = "#ffffff";
          ctx.strokeStyle = "#1d4ed8";
          ctx.lineWidth = 2;
          ctx.fillRect(h.x - HANDLE_SIZE / 2, h.y - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
          ctx.strokeRect(h.x - HANDLE_SIZE / 2, h.y - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
        });
      }
      ctx.restore();
    });
  }

  function drawProceduralFrame(card) {
    const colors = card.colors || [];
    let primaryHex = "#c8c4be";
    let accentHex = "#8c877e";
    const map = {
      W: ["#f4f1e1", "#d8d1b4"],
      U: ["#1c6ea4", "#89b9d9"],
      B: ["#3b363a", "#756d73"],
      R: ["#b83728", "#df8779"],
      G: ["#26663b", "#82b08d"],
    };
    if (colors.length > 1) {
      primaryHex = "#c7a951";
      accentHex = "#e5cf87";
    } else if (colors.length === 1 && map[colors[0]]) {
      [primaryHex, accentHex] = map[colors[0]];
    }

    ctx.save();
    ctx.fillStyle = "#111111";
    ctx.fillRect(0, 0, 750, 1050);

    ctx.fillStyle = primaryHex;
    ctx.beginPath();
    ctx.roundRect(38, 38, 674, 950, 24);
    ctx.fill();

    ctx.fillStyle = "#f3f1ea";
    ctx.strokeStyle = accentHex;
    ctx.lineWidth = 4;

    const tb = STATIC_FRAME_GEOMETRY.titleBar;
    ctx.beginPath();
    ctx.roundRect(tb.x, tb.y, tb.w, tb.h, tb.r);
    ctx.fill();
    ctx.stroke();

    const af = STATIC_FRAME_GEOMETRY.artFrame;
    ctx.strokeRect(af.x, af.y, af.w, af.h);

    const tyb = STATIC_FRAME_GEOMETRY.typeBar;
    ctx.beginPath();
    ctx.roundRect(tyb.x, tyb.y, tyb.w, tyb.h, tyb.r);
    ctx.fill();
    ctx.stroke();

    const ofr = STATIC_FRAME_GEOMETRY.oracleFrame;
    ctx.fillStyle = "#f7f5f0";
    ctx.fillRect(ofr.x, ofr.y, ofr.w, ofr.h);
    ctx.strokeRect(ofr.x, ofr.y, ofr.w, ofr.h);
    ctx.restore();
  }

  function applyTextShadowIfLight(targetCtx, hexColor) {
    if (isLightColor(hexColor)) {
      targetCtx.shadowColor = "rgba(0, 0, 0, 0.85)";
      targetCtx.shadowBlur = 3;
      targetCtx.shadowOffsetX = 1;
      targetCtx.shadowOffsetY = 1;
    } else {
      targetCtx.shadowColor = "transparent";
      targetCtx.shadowBlur = 0;
      targetCtx.shadowOffsetX = 0;
      targetCtx.shadowOffsetY = 0;
    }
  }

  function drawManaCost(targetCtx, manaStr, rightX, baselineY, size) {
    if (!manaStr) return;
    const tokens = manaStr.match(/\{[^}]+\}/g) || [];
    const step = size + 5;
    let curX = rightX - size / 2;

    for (let i = tokens.length - 1; i >= 0; i--) {
      const sym = tokens[i];
      targetCtx.save();
      targetCtx.beginPath();
      targetCtx.arc(curX, baselineY - size * 0.32, size * 0.54, 0, Math.PI * 2);
      targetCtx.fillStyle = getManaCircleColor(sym);
      targetCtx.shadowColor = "rgba(0,0,0,0.5)";
      targetCtx.shadowBlur = 3;
      targetCtx.shadowOffsetX = -1;
      targetCtx.shadowOffsetY = 2;
      targetCtx.fill();
      targetCtx.restore();

      const cls = symbolToManaClass(sym);
      const glyph = getIconGlyph(cls, manaGlyphCache);
      targetCtx.save();
      targetCtx.fillStyle = "#111111";
      targetCtx.textAlign = "center";
      targetCtx.textBaseline = "middle";
      if (glyph.char) {
        targetCtx.font = `${Math.round(size * 0.76)}px ${glyph.fontFamily || "Mana"}`;
        targetCtx.fillText(glyph.char, curX, baselineY - size * 0.3);
      } else {
        targetCtx.font = `bold ${Math.round(size * 0.65)}px sans-serif`;
        targetCtx.fillText(sym.replace(/[{}]/g, ""), curX, baselineY - size * 0.3);
      }
      targetCtx.restore();
      curX -= step;
    }
  }

  function drawSetSymbol(targetCtx, setCode, rarity, rightX, centerY, size) {
    const cls = `ss ss-${(setCode || "mtg").toLowerCase()}`;
    const glyph = getIconGlyph(cls, keyruneGlyphCache);
    const rarityColors = {
      common: "#111111",
      uncommon: "#8da2b0",
      rare: "#d4af37",
      mythic: "#e05a26",
    };
    const r = (rarity || "common").toLowerCase();
    targetCtx.save();
    targetCtx.fillStyle = rarityColors[r] || "#111111";
    targetCtx.strokeStyle = r === "common" ? "#ffffff" : "#111111";
    targetCtx.lineWidth = r === "common" ? 2.5 : 3.5;
    targetCtx.lineJoin = "round";
    targetCtx.textAlign = "right";
    targetCtx.textBaseline = "middle";
    if (glyph.char) {
      targetCtx.font = `${size}px ${glyph.fontFamily || "Keyrune"}`;
      targetCtx.strokeText(glyph.char, rightX, centerY);
      targetCtx.fillText(glyph.char, rightX, centerY);
    } else {
      targetCtx.font = `bold ${Math.round(size * 0.6)}px "BelerenLocal", serif`;
      targetCtx.fillText((setCode || "MTG").toUpperCase(), rightX, centerY);
    }
    targetCtx.restore();
  }

  function measureOracleBlockHeight(targetCtx, oracleText, flavorText, boxW, fontSize) {
    const lineHeight = Math.round(fontSize * 1.24);
    let totalH = 0;
    targetCtx.font = `${fontSize}px "MPlantinLocal", Georgia, serif`;
    const spaceW = targetCtx.measureText(" ").width;

    const paragraphs = (oracleText || "").split("\n").filter((p) => p.trim().length > 0);
    paragraphs.forEach((para) => {
      const words = para.trim().split(/\s+/);
      let lineW = 0;
      let lines = 1;
      words.forEach((word) => {
        const parts = word.split(/(\{[^}]+\})/g).filter(Boolean);
        let wordW = 0;
        parts.forEach((part) => {
          if (part.startsWith("{") && part.endsWith("}")) {
            wordW += fontSize * 0.9;
          } else {
            wordW += targetCtx.measureText(part).width;
          }
        });
        if (lineW + wordW > boxW && lineW > 0) {
          lines++;
          lineW = wordW + spaceW;
        } else {
          lineW += wordW + spaceW;
        }
      });
      totalH += lines * lineHeight + Math.round(lineHeight * 0.22);
    });

    if (flavorText && flavorText.trim()) {
      totalH += 14;
      targetCtx.font = `italic ${Math.round(fontSize * 0.92)}px "MPlantinLocal", Georgia, serif`;
      const fWords = flavorText.trim().split(/\s+/);
      let fLine = "";
      let fLines = 1;
      fWords.forEach((w) => {
        const test = fLine ? `${fLine} ${w}` : w;
        if (targetCtx.measureText(test).width > boxW) {
          fLines++;
          fLine = w;
        } else {
          fLine = test;
        }
      });
      totalH += fLines * Math.round(lineHeight * 0.92);
    }
    return totalH;
  }

  function drawRichOracleText(targetCtx, oracleText, flavorText, box) {
    let fontSize = box.font_size || 24;
    const textColor = box.color || "#111111";
    const maxW = box.w;
    const maxH = box.h;

    while (fontSize > 14 && measureOracleBlockHeight(targetCtx, oracleText, flavorText, maxW, fontSize) > maxH - 6) {
      fontSize -= 1;
    }

    const lineHeight = Math.round(fontSize * 1.24);
    const contentHeight = measureOracleBlockHeight(targetCtx, oracleText, flavorText, maxW, fontSize);
    const verticalOffset = Math.max(0, Math.floor((maxH - contentHeight) / 2));
    let curY = box.y + fontSize + verticalOffset;

    targetCtx.save();
    targetCtx.beginPath();
    targetCtx.rect(box.x - 2, box.y - 2, box.w + 4, box.h + 4);
    targetCtx.clip();

    targetCtx.textAlign = "left";
    targetCtx.textBaseline = "alphabetic";

    const paragraphs = (oracleText || "").split("\n").filter((p) => p.trim().length > 0);
    paragraphs.forEach((para) => {
      const words = para.trim().split(/\s+/);
      let lineTokens = [];
      let lineWidth = 0;

      function flushLine(tokens, y) {
        let x = box.x;
        tokens.forEach((tk) => {
          if (tk.type === "mana") {
            const r = fontSize * 0.42;
            const cx = x + r;
            const cy = y - fontSize * 0.32;
            targetCtx.save();
            targetCtx.beginPath();
            targetCtx.arc(cx, cy, r, 0, Math.PI * 2);
            targetCtx.fillStyle = getManaCircleColor(tk.raw);
            targetCtx.fill();
            const g = getIconGlyph(symbolToManaClass(tk.raw), manaGlyphCache);
            targetCtx.fillStyle = "#111111";
            targetCtx.textAlign = "center";
            targetCtx.textBaseline = "middle";
            targetCtx.font = `${Math.round(fontSize * 0.64)}px ${g.fontFamily || "Mana"}`;
            targetCtx.fillText(g.char || tk.raw.replace(/[{}]/g, ""), cx, cy);
            targetCtx.restore();
            x += tk.width;
          } else {
            targetCtx.save();
            targetCtx.font = `${fontSize}px "MPlantinLocal", Georgia, serif`;
            targetCtx.fillStyle = textColor;
            applyTextShadowIfLight(targetCtx, textColor);
            targetCtx.textAlign = "left";
            targetCtx.textBaseline = "alphabetic";
            targetCtx.fillText(tk.text, x, y);
            targetCtx.restore();
            x += tk.width;
          }
        });
      }

      targetCtx.font = `${fontSize}px "MPlantinLocal", Georgia, serif`;
      const spaceW = targetCtx.measureText(" ").width;

      words.forEach((word) => {
        const parts = word.split(/(\{[^}]+\})/g).filter(Boolean);
        let wordTokens = [];
        let wordW = 0;
        parts.forEach((part) => {
          if (part.startsWith("{") && part.endsWith("}")) {
            const w = fontSize * 0.9;
            wordTokens.push({ type: "mana", raw: part, width: w });
            wordW += w;
          } else {
            targetCtx.font = `${fontSize}px "MPlantinLocal", Georgia, serif`;
            const w = targetCtx.measureText(part).width;
            wordTokens.push({ type: "text", text: part, width: w });
            wordW += w;
          }
        });

        if (lineWidth + wordW > maxW && lineTokens.length > 0) {
          flushLine(lineTokens, curY);
          curY += lineHeight;
          lineTokens = [...wordTokens, { type: "text", text: " ", width: spaceW }];
          lineWidth = wordW + spaceW;
        } else {
          lineTokens.push(...wordTokens, { type: "text", text: " ", width: spaceW });
          lineWidth += wordW + spaceW;
        }
      });

      if (lineTokens.length > 0) {
        flushLine(lineTokens, curY);
        curY += Math.round(lineHeight * 1.22);
      }
    });

    if (flavorText && flavorText.trim()) {
      curY += 4;
      targetCtx.strokeStyle = isLightColor(textColor) ? "rgba(255,255,255,0.28)" : "rgba(0,0,0,0.22)";
      targetCtx.lineWidth = 1;
      targetCtx.beginPath();
      targetCtx.moveTo(box.x + 30, curY - fontSize * 0.68);
      targetCtx.lineTo(box.x + maxW - 30, curY - fontSize * 0.68);
      targetCtx.stroke();
      curY += 10;

      targetCtx.font = `italic ${Math.round(fontSize * 0.92)}px "MPlantinLocal", Georgia, serif`;
      targetCtx.fillStyle = textColor;
      applyTextShadowIfLight(targetCtx, textColor);
      targetCtx.textAlign = "left";
      targetCtx.textBaseline = "alphabetic";
      const fWords = flavorText.trim().split(/\s+/);
      let fLine = "";
      fWords.forEach((w) => {
        const test = fLine ? `${fLine} ${w}` : w;
        if (targetCtx.measureText(test).width > maxW) {
          targetCtx.fillText(fLine, box.x, curY);
          curY += Math.round(lineHeight * 0.92);
          fLine = w;
        } else {
          fLine = test;
        }
      });
      if (fLine) targetCtx.fillText(fLine, box.x, curY);
    }
    targetCtx.restore();
  }

  function drawAllTextsAndIcons(targetCtx, card) {
    const L = card.layout;
    const titleColor = L.title.color || "#111111";
    const typeColor = L.type_line.color || titleColor;
    const ptColor = L.pt_text.color || titleColor;

    targetCtx.save();
    targetCtx.fillStyle = titleColor;
    applyTextShadowIfLight(targetCtx, titleColor);
    targetCtx.font = `bold ${L.title.font_size}px "BelerenLocal", Georgia, serif`;
    targetCtx.textAlign = "left";
    targetCtx.textBaseline = "alphabetic";
    targetCtx.fillText(card.name || "", L.title.x, L.title.y, L.title.max_w || 470);
    const officialTitle = (card.official_name || "").trim();
    if (officialTitle) {
      const subSize = Math.max(12, Math.round(L.title.font_size * 0.56));
      targetCtx.font = `italic ${subSize}px "BelerenLocal", "MPlantinLocal", Georgia, serif`;
      targetCtx.fillText(`(${officialTitle})`, L.title.x, L.title.y + Math.round(L.title.font_size * 0.78), L.title.max_w || 470);
    }
    targetCtx.restore();

    drawManaCost(targetCtx, card.mana_cost || "", L.mana_cost.x, L.mana_cost.y, L.mana_cost.size);

    targetCtx.save();
    targetCtx.fillStyle = typeColor;
    applyTextShadowIfLight(targetCtx, typeColor);
    targetCtx.font = `bold ${L.type_line.font_size}px "BelerenLocal", Georgia, serif`;
    targetCtx.textAlign = "left";
    targetCtx.textBaseline = "alphabetic";
    targetCtx.fillText(card.type_line || "", L.type_line.x, L.type_line.y, L.type_line.max_w || 520);
    targetCtx.restore();

    const setY = L.set_symbol.y ?? L.type_line.y - 8;
    drawSetSymbol(targetCtx, card.set, card.rarity, L.set_symbol.x, setY, L.set_symbol.size);

    drawRichOracleText(targetCtx, card.oracle_text, card.flavor_text, L.oracle_box);

    if (card.power !== null && card.power !== undefined && String(card.power).trim() !== "") {
      targetCtx.save();
      targetCtx.fillStyle = ptColor;
      applyTextShadowIfLight(targetCtx, ptColor);
      targetCtx.font = `bold ${L.pt_text.font_size}px "BelerenLocal", serif`;
      targetCtx.textAlign = "center";
      targetCtx.textBaseline = "middle";
      targetCtx.fillText(`${card.power}/${card.toughness}`, L.pt_text.x, L.pt_text.y);
      targetCtx.restore();
    }

    targetCtx.save();
    targetCtx.fillStyle = L.artist.color || "#ffffff";
    targetCtx.font = `600 ${L.artist.font_size}px sans-serif`;
    targetCtx.textAlign = "left";
    targetCtx.textBaseline = "alphabetic";
    targetCtx.fillText(`🖌 ${card.artist || "Unknown Artist"}`, L.artist.x, L.artist.y);
    targetCtx.restore();
  }

  function renderTextOnlyDataUrl(card) {
    const off = document.createElement("canvas");
    off.width = 750;
    off.height = 1050;
    const octx = off.getContext("2d");
    drawAllTextsAndIcons(octx, card);
    return off.toDataURL("image/png");
  }

  async function renderArtOnlyDataUrl(card) {
    const L = card.layout;
    const artSrc = card.custom_art_data || card.art_crop_url;
    const artImg = await loadImage(artSrc);
    if (!artImg) return "";

    const off = document.createElement("canvas");
    off.width = 750;
    off.height = 1050;
    const octx = off.getContext("2d");

    octx.save();
    octx.beginPath();
    octx.rect(L.art.x, L.art.y, L.art.w, L.art.h);
    octx.clip();
    const scale = L.art.scale || 1.0;
    const baseScale = Math.max(L.art.w / artImg.width, L.art.h / artImg.height) * scale;
    const drawW = artImg.width * baseScale;
    const drawH = artImg.height * baseScale;
    const dx = L.art.x + (L.art.w - drawW) / 2 + (L.art.offset_x || 0);
    const dy = L.art.y + (L.art.h - drawH) / 2 + (L.art.offset_y || 0);
    octx.drawImage(artImg, dx, dy, drawW, drawH);
    octx.restore();

    return off.toDataURL("image/png");
  }

  async function renderCardCanvas(skipOverlays = false) {
    if (activeIndex < 0 || !cards[activeIndex]) {
      ctx.save();
      ctx.fillStyle = "#1e293b";
      ctx.fillRect(0, 0, 750, 1050);
      ctx.fillStyle = "#94a3b8";
      ctx.font = "22px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Select or search a card to start editing", 375, 525);
      ctx.restore();
      return;
    }

    const card = cards[activeIndex];
    const L = card.layout;
    const fc = card.frame_components || {};
    ctx.clearRect(0, 0, 750, 1050);

    const artSrc = card.custom_art_data || card.art_crop_url;
    const artImg = await loadImage(artSrc);

    const drawArtLayer = () => {
      if (!artImg) return;
      ctx.save();
      ctx.beginPath();
      ctx.rect(L.art.x, L.art.y, L.art.w, L.art.h);
      ctx.clip();
      const scale = L.art.scale || 1.0;
      const baseScale = Math.max(L.art.w / artImg.width, L.art.h / artImg.height) * scale;
      const drawW = artImg.width * baseScale;
      const drawH = artImg.height * baseScale;
      const dx = L.art.x + (L.art.w - drawW) / 2 + (L.art.offset_x || 0);
      const dy = L.art.y + (L.art.h - drawH) / 2 + (L.art.offset_y || 0);
      ctx.drawImage(artImg, dx, dy, drawW, drawH);
      ctx.restore();
    };

    const hasAnyJpgComponent = Boolean(
      fc.background || fc.pinlines || fc.name_box || fc.crown || fc.border || fc.pt_box
    );

    const frameOpacity = card.frame_opacity !== undefined ? Math.max(0.05, Math.min(1.0, Number(card.frame_opacity))) : 1.0;

    if (hasAnyJpgComponent) {
      ctx.fillStyle = "#111111";
      ctx.fillRect(0, 0, 750, 1050);

      const bgOp = getLayerOpacity(card, "background");
      const order = getCardLayerOrder(card);
      let artDrawn = false;

      const drawBg = async () => {
        if (fc.background && bgOp > 0.001) {
          const bgImg = await loadImage(relPathToAssetUrl(fc.background));
          if (bgImg) {
            ctx.save();
            ctx.globalAlpha = bgOp;
            ctx.drawImage(bgImg, 0, 0, 750, 1050);
            ctx.restore();
          }
        }
      };

      for (const compKey of order) {
        if (compKey === "background") {
          if (bgOp < 0.999) {
            if (!artDrawn) {
              drawArtLayer();
              artDrawn = true;
            }
            await drawBg();
          } else {
            await drawBg();
            if (!artDrawn) {
              drawArtLayer();
              artDrawn = true;
            }
          }
          continue;
        }
        const compOp = getLayerOpacity(card, compKey);
        if (fc[compKey] && compOp > 0.001) {
          const layerCanvas = await loadTransparentLayerJpg(fc[compKey]);
          if (layerCanvas) {
            ctx.save();
            ctx.globalAlpha = compOp;
            ctx.drawImage(layerCanvas, 0, 0, 750, 1050);
            ctx.restore();
          }
        }
      }
      if (!artDrawn) drawArtLayer();
    } else {
      if (frameOpacity < 1.0) {
        drawArtLayer();
        ctx.save();
        ctx.globalAlpha = frameOpacity;
        drawProceduralFrame(card);
        ctx.restore();
      } else {
        drawProceduralFrame(card);
        drawArtLayer();
      }
      if (card.power !== null && card.power !== undefined && String(card.power).trim() !== "") {
        const ptf = L.pt_box || STATIC_FRAME_GEOMETRY.ptFrame;
        ctx.save();
        ctx.fillStyle = "#f3f1ea";
        ctx.strokeStyle = "#444444";
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.roundRect(ptf.x, ptf.y, ptf.w, ptf.h, 12);
        ctx.fill();
        ctx.stroke();
        ctx.restore();
      }
    }

    drawAllTextsAndIcons(ctx, card);

    if (!skipOverlays) {
      drawInteractiveOverlays(card);
    }
  }

  styleSelect.addEventListener("change", () => {
    if (activeIndex < 0) return;
    pushUndoState();
    const card = cards[activeIndex];
    const st = styleSelect.value;
    if (!st) {
      card.frame_components = {};
      populateComponentDropdowns("", {});
    } else {
      autoPickClientLayers(card, st);
    }
    renderCardCanvas();
  });

  if (autoLayerBtn) {
    autoLayerBtn.addEventListener("click", () => {
      if (activeIndex < 0) return;
      pushUndoState();
      const st = styleSelect.value || "Automated Templates/normal";
      styleSelect.value = st;
      autoPickClientLayers(cards[activeIndex], st);
      renderCardCanvas();
    });
  }

  // --- Mouse Drag & Reshape ---
  function getCanvasMouseCoords(evt) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: (evt.clientX - rect.left) * scaleX,
      y: (evt.clientY - rect.top) * scaleY,
    };
  }

  function findHitTarget(mx, my, card) {
    const regions = getInteractiveRegions(card);
    const selRegion = regions.find((r) => r.key === selectedElementKey);
    if (selRegion) {
      const handles = getHandlesForRegion(selRegion);
      for (const h of handles) {
        if (Math.abs(mx - h.x) <= HANDLE_SIZE && Math.abs(my - h.y) <= HANDLE_SIZE) {
          return { type: "handle", key: selRegion.key, handle: h.id, cursor: h.cursor, region: selRegion };
        }
      }
    }
    for (const r of regions) {
      if (mx >= r.x && mx <= r.x + r.w && my >= r.y && my <= r.y + r.h) {
        return { type: "region", key: r.key, cursor: "move", region: r };
      }
    }
    return null;
  }

  canvas.addEventListener("mousedown", (evt) => {
    if (!interactiveCheck || !interactiveCheck.checked || activeIndex < 0) return;
    const card = cards[activeIndex];
    const { x: mx, y: my } = getCanvasMouseCoords(evt);
    const hit = findHitTarget(mx, my, card);

    if (!hit) {
      selectedElementKey = null;
      renderCardCanvas();
      return;
    }

    selectedElementKey = hit.key;
    const preDragSnapshot = cloneCardState(card);
    const clonedLayout = JSON.parse(JSON.stringify(card.layout));

    if (hit.type === "handle") {
      dragState = {
        mode: "resize",
        key: hit.key,
        handle: hit.handle,
        startX: mx,
        startY: my,
        initialLayout: clonedLayout,
        preDragSnapshot,
        changed: false,
      };
    } else if (hit.key === "art" && evt.shiftKey) {
      dragState = {
        mode: "pan-art",
        key: "art",
        startX: mx,
        startY: my,
        initialLayout: clonedLayout,
        preDragSnapshot,
        changed: false,
      };
    } else {
      dragState = {
        mode: "move",
        key: hit.key,
        startX: mx,
        startY: my,
        initialLayout: clonedLayout,
        preDragSnapshot,
        changed: false,
      };
    }
    renderCardCanvas();
  });

  window.addEventListener("mousemove", (evt) => {
    if (activeIndex < 0 || !cards[activeIndex]) return;
    const card = cards[activeIndex];
    const { x: mx, y: my } = getCanvasMouseCoords(evt);

    if (!dragState) {
      if (!interactiveCheck || !interactiveCheck.checked) {
        canvas.style.cursor = "default";
        return;
      }
      const hit = findHitTarget(mx, my, card);
      const prevHover = hoveredElementKey;
      hoveredElementKey = hit ? hit.key : null;
      canvas.style.cursor = hit ? hit.cursor : "default";
      if (prevHover !== hoveredElementKey) renderCardCanvas();
      return;
    }

    const dx = mx - dragState.startX;
    const dy = my - dragState.startY;
    if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
      dragState.changed = true;
      card.custom_layout = true;
    }

    const init = dragState.initialLayout;
    const L = card.layout;
    const k = dragState.key;

    if (dragState.mode === "pan-art") {
      L.art.offset_x = (init.art.offset_x || 0) + dx;
      L.art.offset_y = (init.art.offset_y || 0) + dy;
    } else if (dragState.mode === "move") {
      if (k === "art") {
        L.art.x = init.art.x + dx;
        L.art.y = init.art.y + dy;
      } else if (k === "title") {
        L.title.x = init.title.x + dx;
        L.title.y = init.title.y + dy;
      } else if (k === "mana_cost") {
        L.mana_cost.x = init.mana_cost.x + dx;
        L.mana_cost.y = init.mana_cost.y + dy;
      } else if (k === "type_line") {
        L.type_line.x = init.type_line.x + dx;
        L.type_line.y = init.type_line.y + dy;
      } else if (k === "set_symbol") {
        L.set_symbol.x = init.set_symbol.x + dx;
        L.set_symbol.y = (init.set_symbol.y ?? init.type_line.y - 8) + dy;
      } else if (k === "oracle_box") {
        L.oracle_box.x = init.oracle_box.x + dx;
        L.oracle_box.y = init.oracle_box.y + dy;
      } else if (k === "pt_text") {
        L.pt_text.x = init.pt_text.x + dx;
        L.pt_text.y = init.pt_text.y + dy;
      } else if (k === "artist") {
        L.artist.x = init.artist.x + dx;
        L.artist.y = init.artist.y + dy;
      }
    } else if (dragState.mode === "resize") {
      const h = dragState.handle;
      if (k === "art" || k === "oracle_box") {
        const targetInit = init[k];
        const targetCur = L[k];
        let nx = targetInit.x;
        let ny = targetInit.y;
        let nw = targetInit.w;
        let nh = targetInit.h;

        if (h.includes("e")) nw = Math.max(60, targetInit.w + dx);
        if (h.includes("s")) nh = Math.max(40, targetInit.h + dy);
        if (h.includes("w")) {
          const possibleW = targetInit.w - dx;
          if (possibleW >= 60) {
            nw = possibleW;
            nx = targetInit.x + dx;
          }
        }
        if (h.includes("n")) {
          const possibleH = targetInit.h - dy;
          if (possibleH >= 40) {
            nh = possibleH;
            ny = targetInit.y + dy;
          }
        }
        targetCur.x = nx;
        targetCur.y = ny;
        targetCur.w = nw;
        targetCur.h = nh;
      } else if (k === "title" || k === "type_line") {
        const tInit = init[k];
        const tCur = L[k];
        if (h.includes("e")) tCur.max_w = Math.max(100, (tInit.max_w || 470) + dx);
        if (h.includes("w")) {
          tCur.x = tInit.x + dx;
          tCur.max_w = Math.max(100, (tInit.max_w || 470) - dx);
        }
        if (h.includes("s") || h.includes("n")) {
          const deltaFont = h.includes("s") ? dy : -dy;
          tCur.font_size = Math.max(12, Math.min(72, tInit.font_size + deltaFont * 0.5));
        }
      } else if (k === "mana_cost") {
        const delta = h.includes("s") || h.includes("e") ? dy + dx * 0.3 : -(dy + dx * 0.3);
        L.mana_cost.size = Math.max(14, Math.min(64, init.mana_cost.size + delta * 0.4));
      } else if (k === "set_symbol") {
        const delta = h.includes("s") || h.includes("e") ? dy : -dy;
        L.set_symbol.size = Math.max(16, Math.min(72, (init.set_symbol.size || 30) + delta * 0.5));
      } else if (k === "pt_text") {
        const dir = h.includes("s") || h.includes("e") ? 1 : -1;
        L.pt_text.font_size = Math.max(16, Math.min(64, init.pt_text.font_size + (dy + dx * 0.5) * dir * 0.4));
      } else if (k === "artist") {
        const delta = h.includes("s") ? dy : -dy;
        L.artist.font_size = Math.max(10, Math.min(36, init.artist.font_size + delta * 0.4));
      }
    }

    populatePositionInputsFromLayout(L);
    renderCardCanvas();
  });

  window.addEventListener("mouseup", () => {
    if (dragState) {
      if (dragState.changed) {
        pushUndoState(dragState.preDragSnapshot);
      }
      dragState = null;
      renderCardCanvas();
    }
  });

  canvas.addEventListener(
    "wheel",
    (evt) => {
      if (!interactiveCheck || !interactiveCheck.checked || activeIndex < 0) return;
      const card = cards[activeIndex];
      const { x: mx, y: my } = getCanvasMouseCoords(evt);
      const hit = findHitTarget(mx, my, card);
      if (!hit) return;

      evt.preventDefault();
      pushUndoState();
      selectedElementKey = hit.key;
      card.custom_layout = true;
      const L = card.layout;
      const dir = evt.deltaY < 0 ? 1 : -1;

      if (hit.key === "art") {
        L.art.scale = Math.max(0.2, Math.min(4.0, (L.art.scale || 1.0) + dir * 0.04));
      } else if (hit.key === "oracle_box") {
        L.oracle_box.font_size = Math.max(12, Math.min(48, L.oracle_box.font_size + dir));
      } else if (hit.key === "title") {
        L.title.font_size = Math.max(14, Math.min(72, L.title.font_size + dir));
      } else if (hit.key === "type_line") {
        L.type_line.font_size = Math.max(12, Math.min(54, L.type_line.font_size + dir));
      } else if (hit.key === "mana_cost") {
        L.mana_cost.size = Math.max(14, Math.min(64, L.mana_cost.size + dir));
      } else if (hit.key === "set_symbol") {
        L.set_symbol.size = Math.max(14, Math.min(68, (L.set_symbol.size || 30) + dir));
      } else if (hit.key === "pt_text") {
        L.pt_text.font_size = Math.max(14, Math.min(64, L.pt_text.font_size + dir));
      }

      populatePositionInputsFromLayout(L);
      renderCardCanvas();
    },
    { passive: false }
  );

  if (interactiveCheck) {
    interactiveCheck.addEventListener("change", () => renderCardCanvas());
  }

  if (resetLayoutBtn) {
    resetLayoutBtn.addEventListener("click", () => {
      if (activeIndex < 0) return;
      pushUndoState();
      cards[activeIndex].custom_layout = false;
      normalizeCardLayout(cards[activeIndex], true);
      populatePositionInputsFromLayout(cards[activeIndex].layout);
      renderCardCanvas();
    });
  }

  function syncEditorToCard() {
    if (activeIndex < 0 || !cards[activeIndex]) return;
    const card = cards[activeIndex];
    card.name = fieldName.value;
    if (fieldOfficialName) card.official_name = fieldOfficialName.value;
    if (frameOpacityInput) {
      const fOp = parseFloat(frameOpacityInput.value);
      const nextOp = Number.isFinite(fOp) ? fOp : 1.0;
      if (card.frame_opacity !== nextOp) {
        card.frame_opacity = nextOp;
        if (!card.layer_opacities) card.layer_opacities = {};
        LAYER_DEFINITIONS.forEach((def) => {
          card.layer_opacities[def.key] = nextOp;
        });
        syncLayerOpacitySliders(card);
    syncLayerOrderDOM(card);
      }
      const valEl = document.getElementById("val-frame-opacity");
      if (valEl) valEl.textContent = Math.round(nextOp * 100) + "%";
    }
    card.mana_cost = fieldMana.value;
    card.type_line = fieldType.value;
    card.set = fieldSet.value.trim().toLowerCase();
    card.rarity = fieldRarity.value;
    card.oracle_text = fieldOracle.value;
    card.flavor_text = fieldFlavor.value;
    card.power = fieldPower.value;
    card.toughness = fieldToughness.value;
    card.artist = fieldArtist.value;
    card.art_crop_url = artUrlInput.value.trim();

    card.custom_layout = true;
    const L = card.layout;
    L.art.scale = parseFloat(artScaleInput.value) || 1.0;
    L.art.offset_x = parseInt(artOxInput.value, 10) || 0;
    L.art.offset_y = parseInt(artOyInput.value, 10) || 0;
    document.getElementById("val-art-scale").textContent = L.art.scale.toFixed(2) + "x";
    document.getElementById("val-art-ox").textContent = L.art.offset_x + "px";
    document.getElementById("val-art-oy").textContent = L.art.offset_y + "px";

    L.art.x = parseInt(posInputs.artX.value, 10) || DEFAULT_LAYOUT.art.x;
    L.art.y = parseInt(posInputs.artY.value, 10) || DEFAULT_LAYOUT.art.y;
    L.art.w = parseInt(posInputs.artW.value, 10) || DEFAULT_LAYOUT.art.w;
    L.art.h = parseInt(posInputs.artH.value, 10) || DEFAULT_LAYOUT.art.h;
    L.title.x = parseInt(posInputs.titleX.value, 10) || DEFAULT_LAYOUT.title.x;
    L.title.y = parseInt(posInputs.titleY.value, 10) || DEFAULT_LAYOUT.title.y;
    L.title.font_size = parseInt(posInputs.titleSize.value, 10) || DEFAULT_LAYOUT.title.font_size;
    L.mana_cost.x = parseInt(posInputs.manaX.value, 10) || DEFAULT_LAYOUT.mana_cost.x;
    L.mana_cost.y = parseInt(posInputs.manaY.value, 10) || DEFAULT_LAYOUT.mana_cost.y;
    L.mana_cost.size = parseInt(posInputs.manaSize.value, 10) || DEFAULT_LAYOUT.mana_cost.size;
    L.type_line.x = parseInt(posInputs.typeX.value, 10) || DEFAULT_LAYOUT.type_line.x;
    L.type_line.y = parseInt(posInputs.typeY.value, 10) || DEFAULT_LAYOUT.type_line.y;
    L.type_line.font_size = parseInt(posInputs.typeSize.value, 10) || DEFAULT_LAYOUT.type_line.font_size;
    L.oracle_box.x = parseInt(posInputs.oracleX.value, 10) || DEFAULT_LAYOUT.oracle_box.x;
    L.oracle_box.y = parseInt(posInputs.oracleY.value, 10) || DEFAULT_LAYOUT.oracle_box.y;
    L.oracle_box.w = parseInt(posInputs.oracleW.value, 10) || DEFAULT_LAYOUT.oracle_box.w;
    L.oracle_box.h = parseInt(posInputs.oracleH.value, 10) || DEFAULT_LAYOUT.oracle_box.h;
    L.oracle_box.font_size = parseInt(posInputs.oracleSize.value, 10) || DEFAULT_LAYOUT.oracle_box.font_size;
    L.pt_text.x = parseInt(posInputs.ptX.value, 10) || DEFAULT_LAYOUT.pt_text.x;
    L.pt_text.y = parseInt(posInputs.ptY.value, 10) || DEFAULT_LAYOUT.pt_text.y;
    L.pt_text.font_size = parseInt(posInputs.ptSize.value, 10) || DEFAULT_LAYOUT.pt_text.font_size;

    renderCardList();
    renderCardCanvas();
  }

  [
    fieldName, fieldOfficialName, frameOpacityInput, fieldMana, fieldType, fieldSet, fieldRarity,
    fieldOracle, fieldFlavor, fieldPower, fieldToughness, fieldArtist,
    artUrlInput, artScaleInput, artOxInput, artOyInput,
    ...Object.values(posInputs),
  ].forEach((el) => {
    if (!el) return;
    el.addEventListener("focus", () => pushUndoState());
    el.addEventListener("input", syncEditorToCard);
  });

  artFileInput.addEventListener("change", function () {
    if (!this.files || !this.files[0] || activeIndex < 0) return;
    pushUndoState();
    const reader = new FileReader();
    reader.onload = (e) => {
      cards[activeIndex].custom_art_data = e.target.result;
      renderCardCanvas();
    };
    reader.readAsDataURL(this.files[0]);
  });

  searchBtn.addEventListener("click", async () => {
    const query = scryfallInput.value.trim();
    if (!query) return;
    setLoading(true, `Searching "${query}" on Scryfall...`);
    const body = new FormData();
    body.append("query", query);
    body.append("target_dir", targetDirInput.value.trim());

    try {
      const res = await fetch("/api/card-builder/search", { method: "POST", body });
      const data = await res.json();
      if (!res.ok || data.error) {
        showStatus(data.error || "Card search failed.", true);
        return;
      }
      const existingIdx = cards.findIndex((c) => c.name.toLowerCase() === data.card.name.toLowerCase());
      if (existingIdx >= 0) {
        cards[existingIdx] = data.card;
        selectCard(existingIdx);
      } else {
        cards.unshift(data.card);
        selectCard(0);
      }
      showStatus(
        data.saved_path ? `JSON saved: ${data.saved_path}` : `Loaded "${data.card.name}".`,
        false
      );
    } catch (err) {
      showStatus("Connection error: " + err.message, true);
    } finally {
      setLoading(false);
    }
  });

  scryfallInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      searchBtn.click();
    }
  });

  const cancelLoadingBtn = document.getElementById("cb-cancel-loading-btn");

  uploadTxtBtn.addEventListener("click", async () => {
    const targetDir = targetDirInput.value.trim();
    if (!txtInput.files.length && !targetDir) {
      showStatus("Select an MTGO .txt file or enter a folder path.", true);
      return;
    }
    const controller = new AbortController();
    if (cancelLoadingBtn) {
      cancelLoadingBtn.style.display = "inline-block";
      cancelLoadingBtn.onclick = () => controller.abort();
    }
    setLoading(true, "Fetching Scryfall metadata and saving per-card JSONs... Calmao, This might take a bit");
    const body = new FormData();
    body.append("target_dir", targetDir);
    if (txtInput.files.length) {
      body.append("txt_file", txtInput.files[0]);
    }

    try {
      const res = await fetch("/api/card-builder/upload-txt", {
        method: "POST",
        body,
        signal: controller.signal,
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        showStatus(data.error || "Error processing .txt file.", true);
        return;
      }
      if (data.target_dir) targetDirInput.value = data.target_dir;
      cards = data.cards || [];
      historyStacks.clear();
      if (cards.length > 0) selectCard(0);
      else renderCardList();
      saveCardBuilderState();

      const errNote = data.errors && data.errors.length ? ` (${data.errors.length} not found)` : "";
      showStatus(`Saved ${cards.length} JSON files to ${data.target_dir}/json${errNote}`, false);
    } catch (err) {
      if (err && err.name === "AbortError") {
        showStatus("Parse & Save cancelled.", false);
      } else {
        showStatus("List error: " + err.message, true);
      }
    } finally {
      if (cancelLoadingBtn) {
        cancelLoadingBtn.style.display = "none";
        cancelLoadingBtn.onclick = null;
      }
      setLoading(false);
    }
  });

  filterCardsInput.addEventListener("input", renderCardList);

  document.getElementById("cb-save-json-btn").addEventListener("click", async () => {
    if (activeIndex < 0) return;
    try {
      const res = await fetch("/api/card-builder/save-card", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          card: cards[activeIndex],
          target_dir: targetDirInput.value.trim(),
        }),
      });
      const data = await res.json();
      if (data.error) showStatus(data.error, true);
      else showStatus(`JSON updated: ${data.saved_path}`, false);
    } catch (err) {
      showStatus("Save error: " + err.message, true);
    }
  });

  document.getElementById("cb-download-png-btn").addEventListener("click", async () => {
    if (activeIndex < 0) return;
    await renderCardCanvas(true);
    const link = document.createElement("a");
    link.download = `${cards[activeIndex].name.replace(/[^a-z0-9]/gi, "_").toLowerCase()}.png`;
    link.href = canvas.toDataURL("image/png");
    link.click();
    renderCardCanvas(false);
  });

  document.getElementById("cb-export-pdf-btn").addEventListener("click", async () => {
    if (activeIndex < 0) return;
    const card = cards[activeIndex];
    setLoading(true, "Compositing high-res PDF from .pdf layer assets...");
    await renderCardCanvas(true);
    const fullDataUrl = canvas.toDataURL("image/png");
    const artOverlayDataUrl = await renderArtOnlyDataUrl(card);
    const textOverlayDataUrl = renderTextOnlyDataUrl(card);
    renderCardCanvas(false);

    try {
      const res = await fetch("/api/card-builder/export-pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          card,
          card_name: card.name,
          target_dir: targetDirInput.value.trim(),
          art_overlay_data_url: artOverlayDataUrl,
          text_overlay_data_url: textOverlayDataUrl,
          image_data_url: fullDataUrl,
        }),
      });
      const data = await res.json();
      if (data.error) {
        showStatus(data.error, true);
      } else {
        const countPdf = (data.pdf_components_used || []).length;
        showStatus(`Exported PDF: ${data.pdf_path} (${countPdf} .pdf layers)`, false);
      }
    } catch (err) {
      showStatus("PDF export error: " + err.message, true);
    } finally {
      setLoading(false);
    }
  });

  // --- Interactive Art Crop Modal ---
  const cropArtBtn = document.getElementById("cb-crop-art-btn");
  const cropModal = document.getElementById("cb-crop-modal");
  const cropCanvas = document.getElementById("cb-crop-canvas");
  const cropCtx = cropCanvas ? cropCanvas.getContext("2d") : null;
  const cropLockRatio = document.getElementById("cb-crop-lock-ratio");
  const cropInfo = document.getElementById("cb-crop-info");
  const cropResetBtn = document.getElementById("cb-crop-reset-btn");
  const cropApplyBtn = document.getElementById("cb-crop-apply-btn");
  const cropCloseBtn = document.getElementById("cb-crop-close-btn");
  const cropCancelBtn = document.getElementById("cb-crop-cancel-btn");

  let cropImg = null;
  let cropScale = 1;
  let cropRect = { x: 0, y: 0, w: 100, h: 100 };
  let cropTargetRatio = 622 / 446;
  let cropDrag = null;

  function getActiveArtBoxRatio() {
    const card = cards[activeIndex];
    const art = card?.layout?.art || DEFAULT_LAYOUT.art;
    return art.w > 0 && art.h > 0 ? art.w / art.h : 622 / 446;
  }

  function initDefaultCropRect() {
    if (!cropImg) return;
    const iw = cropImg.naturalWidth;
    const ih = cropImg.naturalHeight;
    if (!cropLockRatio || !cropLockRatio.checked) {
      cropRect = { x: 0, y: 0, w: iw, h: ih };
      return;
    }
    const r = cropTargetRatio;
    let w = iw;
    let h = w / r;
    if (h > ih) {
      h = ih;
      w = h * r;
    }
    cropRect = {
      x: (iw - w) / 2,
      y: (ih - h) / 2,
      w,
      h,
    };
  }

  function drawCropCanvas() {
    if (!cropCanvas || !cropCtx || !cropImg) return;
    const cw = cropCanvas.width;
    const ch = cropCanvas.height;
    cropCtx.clearRect(0, 0, cw, ch);
    cropCtx.drawImage(cropImg, 0, 0, cw, ch);

    const sx = cropRect.x * cropScale;
    const sy = cropRect.y * cropScale;
    const sw = cropRect.w * cropScale;
    const sh = cropRect.h * cropScale;

    // Dim exterior
    cropCtx.fillStyle = "rgba(0, 0, 0, 0.62)";
    cropCtx.beginPath();
    cropCtx.rect(0, 0, cw, ch);
    cropCtx.rect(sx, sy, sw, sh);
    cropCtx.fill("evenodd");

    // Rule-of-thirds grid
    cropCtx.strokeStyle = "rgba(255, 255, 255, 0.25)";
    cropCtx.lineWidth = 1;
    cropCtx.beginPath();
    for (let i = 1; i <= 2; i++) {
      cropCtx.moveTo(sx + (sw * i) / 3, sy);
      cropCtx.lineTo(sx + (sw * i) / 3, sy + sh);
      cropCtx.moveTo(sx, sy + (sh * i) / 3);
      cropCtx.lineTo(sx + sw, sy + (sh * i) / 3);
    }
    cropCtx.stroke();

    // Crop border
    cropCtx.strokeStyle = "#38bdf8";
    cropCtx.lineWidth = 2;
    cropCtx.strokeRect(sx, sy, sw, sh);

    // Corner & edge handles
    const hs = 10;
    cropCtx.fillStyle = "#38bdf8";
    const handles = [
      [sx, sy],
      [sx + sw, sy],
      [sx, sy + sh],
      [sx + sw, sy + sh],
      [sx + sw / 2, sy],
      [sx + sw / 2, sy + sh],
      [sx, sy + sh / 2],
      [sx + sw, sy + sh / 2],
    ];
    for (const [cx, cy] of handles) {
      cropCtx.fillRect(cx - hs / 2, cy - hs / 2, hs, hs);
    }

    if (cropInfo) {
      cropInfo.textContent = `${Math.round(cropRect.w)} × ${Math.round(cropRect.h)} px`;
    }
  }

  function closeCropModal() {
    if (cropModal) cropModal.classList.remove("active");
    cropDrag = null;
  }

  async function openCropModal() {
    const card = cards[activeIndex];
    if (!card) return;
    const artSrc = card.custom_art_data || card.art_crop_url;
    if (!artSrc) {
      showStatus("No artwork loaded for this card.", true);
      return;
    }
    const img = await loadImage(artSrc);
    if (!img || !img.naturalWidth) {
      showStatus("Could not load artwork image for cropping.", true);
      return;
    }
    cropImg = img;
    cropTargetRatio = getActiveArtBoxRatio();

    const maxW = 700;
    const maxH = 460;
    cropScale = Math.min(maxW / img.naturalWidth, maxH / img.naturalHeight, 1);
    cropCanvas.width = Math.max(1, Math.round(img.naturalWidth * cropScale));
    cropCanvas.height = Math.max(1, Math.round(img.naturalHeight * cropScale));

    initDefaultCropRect();
    drawCropCanvas();
    if (cropModal) cropModal.classList.add("active");
  }

  function getCropPointerPos(e) {
    const rect = cropCanvas.getBoundingClientRect();
    return {
      x: ((e.clientX - rect.left) / rect.width) * cropImg.naturalWidth,
      y: ((e.clientY - rect.top) / rect.height) * cropImg.naturalHeight,
    };
  }

  function hitTestCropHandle(px, py) {
    const tol = 14 / cropScale;
    const { x, y, w, h } = cropRect;
    const points = [
      ["nw", x, y],
      ["ne", x + w, y],
      ["sw", x, y + h],
      ["se", x + w, y + h],
      ["n", x + w / 2, y],
      ["s", x + w / 2, y + h],
      ["w", x, y + h / 2],
      ["e", x + w, y + h / 2],
    ];
    for (const [mode, cx, cy] of points) {
      if (Math.abs(px - cx) <= tol && Math.abs(py - cy) <= tol) return mode;
    }
    if (px >= x && px <= x + w && py >= y && py <= y + h) return "move";
    return null;
  }

  if (cropArtBtn) cropArtBtn.addEventListener("click", openCropModal);
  if (cropCloseBtn) cropCloseBtn.addEventListener("click", closeCropModal);
  if (cropCancelBtn) cropCancelBtn.addEventListener("click", closeCropModal);
  if (cropModal) {
    cropModal.addEventListener("click", (e) => {
      if (e.target === cropModal) closeCropModal();
    });
  }
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && cropModal && cropModal.classList.contains("active")) {
      closeCropModal();
    }
  });

  if (cropLockRatio) {
    cropLockRatio.addEventListener("change", () => {
      if (!cropImg) return;
      if (cropLockRatio.checked) {
        const iw = cropImg.naturalWidth;
        const ih = cropImg.naturalHeight;
        const cx = cropRect.x + cropRect.w / 2;
        const cy = cropRect.y + cropRect.h / 2;
        let w = cropRect.w;
        let h = w / cropTargetRatio;
        if (h > ih) {
          h = ih;
          w = h * cropTargetRatio;
        }
        if (w > iw) {
          w = iw;
          h = w / cropTargetRatio;
        }
        cropRect = {
          x: Math.max(0, Math.min(iw - w, cx - w / 2)),
          y: Math.max(0, Math.min(ih - h, cy - h / 2)),
          w,
          h,
        };
      }
      drawCropCanvas();
    });
  }

  if (cropResetBtn) {
    cropResetBtn.addEventListener("click", () => {
      initDefaultCropRect();
      drawCropCanvas();
    });
  }

  if (cropCanvas) {
    cropCanvas.addEventListener("pointerdown", (e) => {
      if (!cropImg) return;
      const pos = getCropPointerPos(e);
      const mode = hitTestCropHandle(pos.x, pos.y);
      if (!mode) return;
      cropCanvas.setPointerCapture(e.pointerId);
      cropDrag = {
        mode,
        startX: pos.x,
        startY: pos.y,
        orig: { ...cropRect },
      };
    });

    cropCanvas.addEventListener("pointermove", (e) => {
      if (!cropImg) return;
      const pos = getCropPointerPos(e);
      if (!cropDrag) {
        const hover = hitTestCropHandle(pos.x, pos.y);
        cropCanvas.style.cursor =
          hover === "move"
            ? "grab"
            : hover === "nw" || hover === "se"
              ? "nwse-resize"
              : hover === "ne" || hover === "sw"
                ? "nesw-resize"
                : hover === "n" || hover === "s"
                  ? "ns-resize"
                  : hover === "w" || hover === "e"
                    ? "ew-resize"
                    : "default";
        return;
      }

      const iw = cropImg.naturalWidth;
      const ih = cropImg.naturalHeight;
      const o = cropDrag.orig;
      const dx = pos.x - cropDrag.startX;
      const dy = pos.y - cropDrag.startY;
      const minSize = 24;
      const mode = cropDrag.mode;

      if (mode === "move") {
        cropRect.x = Math.max(0, Math.min(iw - o.w, o.x + dx));
        cropRect.y = Math.max(0, Math.min(ih - o.h, o.y + dy));
        drawCropCanvas();
        return;
      }

      const lock = cropLockRatio && cropLockRatio.checked;
      const r = cropTargetRatio;
      const hasW = mode.includes("w");
      const hasE = mode.includes("e");
      const hasN = mode.includes("n");
      const hasS = mode.includes("s");

      if (!lock) {
        let newX = o.x;
        let newY = o.y;
        let newW = o.w;
        let newH = o.h;

        if (hasW) {
          const maxLeft = o.x + o.w - minSize;
          newX = Math.max(0, Math.min(maxLeft, o.x + dx));
          newW = o.x + o.w - newX;
        } else if (hasE) {
          newW = Math.max(minSize, Math.min(iw - o.x, o.w + dx));
        }

        if (hasN) {
          const maxTop = o.y + o.h - minSize;
          newY = Math.max(0, Math.min(maxTop, o.y + dy));
          newH = o.y + o.h - newY;
        } else if (hasS) {
          newH = Math.max(minSize, Math.min(ih - o.y, o.h + dy));
        }

        cropRect = { x: newX, y: newY, w: newW, h: newH };
        drawCropCanvas();
        return;
      }

      const anchorX = hasW ? o.x + o.w : o.x;
      const anchorY = hasN ? o.y + o.h : o.y;
      const dirX = hasW ? -1 : 1;
      const dirY = hasN ? -1 : 1;
      const maxW = dirX === 1 ? iw - anchorX : anchorX;
      const maxH = dirY === 1 ? ih - anchorY : anchorY;

      let newW = o.w;
      if (hasW) newW = o.w - dx;
      else if (hasE) newW = o.w + dx;
      else if (hasN) newW = (o.h - dy) * r;
      else if (hasS) newW = (o.h + dy) * r;

      newW = Math.max(minSize, Math.min(maxW, newW));
      let newH = newW / r;
      if (newH > maxH) {
        newH = maxH;
        newW = newH * r;
      }
      if (newH < minSize) {
        newH = minSize;
        newW = newH * r;
      }

      cropRect = {
        x: dirX === 1 ? anchorX : anchorX - newW,
        y: dirY === 1 ? anchorY : anchorY - newH,
        w: newW,
        h: newH,
      };
      drawCropCanvas();
    });

    cropCanvas.addEventListener("pointerup", () => {
      cropDrag = null;
    });
    cropCanvas.addEventListener("pointercancel", () => {
      cropDrag = null;
    });
  }

  if (cropApplyBtn) {
    cropApplyBtn.addEventListener("click", () => {
      const card = cards[activeIndex];
      if (!card || !cropImg) return;
      const outW = Math.max(1, Math.round(cropRect.w));
      const outH = Math.max(1, Math.round(cropRect.h));
      const off = document.createElement("canvas");
      off.width = outW;
      off.height = outH;
      const octx = off.getContext("2d");
      octx.drawImage(
        cropImg,
        cropRect.x,
        cropRect.y,
        cropRect.w,
        cropRect.h,
        0,
        0,
        outW,
        outH
      );
      try {
        const dataUrl = off.toDataURL("image/png");
        pushUndoState();
        card.custom_art_data = dataUrl;
        if (!card.layout) card.layout = deepClone(DEFAULT_LAYOUT);
        if (!card.layout.art) card.layout.art = deepClone(DEFAULT_LAYOUT.art);
        card.layout.art.scale = 1.0;
        card.layout.art.offset_x = 0;
        card.layout.art.offset_y = 0;
        refreshInputsFromActiveCard();
        renderCardCanvas();
        closeCropModal();
        showStatus("Artwork cropped to Art Box.");
      } catch (err) {
        showStatus("Could not export cropped image (CORS restriction).", true);
      }
    });
  }

  // --- Deck Folder Browser Modal ---
  const targetDirBrowseBtn = document.getElementById("cb-target-dir-browse-btn");
  const cbDirModal = document.getElementById("cb-dir-browser-modal");
  const cbDirCloseBtn = document.getElementById("cb-dir-browser-close-btn");
  const cbDirCancelBtn = document.getElementById("cb-dir-browser-cancel-btn");
  const cbDirUpBtn = document.getElementById("cb-dir-browser-up-btn");
  const cbDirCurrent = document.getElementById("cb-dir-browser-current");
  const cbDirList = document.getElementById("cb-dir-browser-list");
  const cbDirNewName = document.getElementById("cb-dir-browser-new-name");
  const cbDirMkdirBtn = document.getElementById("cb-dir-browser-mkdir-btn");
  const cbDirSelectBtn = document.getElementById("cb-dir-browser-select-btn");
  const cbDirError = document.getElementById("cb-dir-browser-error");
  let cbDirParent = null;

  function showCbDirError(msg) {
    if (!cbDirError) return;
    cbDirError.textContent = msg || "";
    cbDirError.style.display = msg ? "block" : "none";
  }

  async function loadCbDirBrowser(path) {
    showCbDirError("");
    try {
      const url = "/browse-dirs" + (path ? "?path=" + encodeURIComponent(path) : "");
      const res = await fetch(url);
      const data = await res.json();
      if (!res.ok || data.error) {
        showCbDirError(data.error || "Could not open folder.");
        return;
      }
      if (cbDirCurrent) cbDirCurrent.value = data.current;
      cbDirParent = data.parent || null;
      if (cbDirUpBtn) cbDirUpBtn.disabled = !cbDirParent;
      if (cbDirList) {
        cbDirList.innerHTML = "";
        if (!data.dirs || data.dirs.length === 0) {
          const empty = document.createElement("div");
          empty.style.padding = "12px";
          empty.style.color = "var(--muted)";
          empty.style.fontSize = "12px";
          empty.textContent = "(No subfolders)";
          cbDirList.appendChild(empty);
        } else {
          data.dirs.forEach((name) => {
            const item = document.createElement("button");
            item.type = "button";
            item.style.display = "flex";
            item.style.alignItems = "center";
            item.style.gap = "8px";
            item.style.width = "100%";
            item.style.textAlign = "left";
            item.style.padding = "8px 12px";
            item.style.border = "0";
            item.style.borderBottom = "1px solid var(--table-border)";
            item.style.background = "transparent";
            item.style.color = "var(--fg)";
            item.style.cursor = "pointer";
            item.style.fontSize = "13px";
            item.textContent = "📁 " + name;
            item.addEventListener("click", () => {
              const sep = data.current.endsWith("/") ? "" : "/";
              loadCbDirBrowser(data.current + sep + name);
            });
            cbDirList.appendChild(item);
          });
        }
      }
    } catch (err) {
      showCbDirError("Error loading folders: " + err.message);
    }
  }

  function closeCbDirModal() {
    if (cbDirModal) cbDirModal.classList.remove("active");
  }

  if (targetDirBrowseBtn) {
    targetDirBrowseBtn.addEventListener("click", () => {
      if (cbDirModal) cbDirModal.classList.add("active");
      loadCbDirBrowser(targetDirInput ? targetDirInput.value.trim() : "");
    });
  }
  if (cbDirCloseBtn) cbDirCloseBtn.addEventListener("click", closeCbDirModal);
  if (cbDirCancelBtn) cbDirCancelBtn.addEventListener("click", closeCbDirModal);
  if (cbDirModal) {
    cbDirModal.addEventListener("click", (e) => {
      if (e.target === cbDirModal) closeCbDirModal();
    });
  }
  if (cbDirUpBtn) {
    cbDirUpBtn.addEventListener("click", () => {
      if (cbDirParent) loadCbDirBrowser(cbDirParent);
    });
  }
  if (cbDirMkdirBtn) {
    cbDirMkdirBtn.addEventListener("click", async () => {
      const current = cbDirCurrent ? cbDirCurrent.value.trim() : "";
      const name = cbDirNewName ? cbDirNewName.value.trim() : "";
      if (!name) {
        showCbDirError("Enter a folder name.");
        return;
      }
      showCbDirError("");
      const body = new FormData();
      body.append("current", current);
      body.append("folder_name", name);
      try {
        const res = await fetch("/browse-dirs", { method: "POST", body });
        const data = await res.json();
        if (!res.ok || data.error) {
          showCbDirError(data.error || "Could not create folder.");
          return;
        }
        if (cbDirNewName) cbDirNewName.value = "";
        loadCbDirBrowser(data.created || current);
      } catch (err) {
        showCbDirError("Error creating folder: " + err.message);
      }
    });
  }
  if (cbDirSelectBtn) {
    cbDirSelectBtn.addEventListener("click", () => {
      if (targetDirInput && cbDirCurrent) {
        targetDirInput.value = cbDirCurrent.value;
      }
      closeCbDirModal();
    });
  }

  const CB_STATE_KEY = "deckgen-cb-state";

  function getCardBuilderStateObject() {
    return {
      target_dir: targetDirInput ? targetDirInput.value.trim() : "",
      active_index: activeIndex,
      cards: Array.isArray(cards) ? cards : [],
    };
  }

  function saveCardBuilderState() {
    const state = getCardBuilderStateObject();
    try {
      localStorage.setItem(CB_STATE_KEY, JSON.stringify(state));
    } catch (e) {
      // Fallback: strip heavy base64 custom_art_data if localStorage quota is exceeded
      try {
        const lightCards = (state.cards || []).map((c, idx) => {
          if (idx === state.active_index || !c || !c.custom_art_data) return c;
          const copy = { ...c };
          delete copy.custom_art_data;
          return copy;
        });
        localStorage.setItem(CB_STATE_KEY, JSON.stringify({ ...state, cards: lightCards }));
      } catch (e2) {
        try {
          const minimalCards = (state.cards || []).map((c) => {
            if (!c || !c.custom_art_data) return c;
            const copy = { ...c };
            delete copy.custom_art_data;
            return copy;
          });
          localStorage.setItem(CB_STATE_KEY, JSON.stringify({ ...state, cards: minimalCards }));
        } catch (e3) {}
      }
    }
  }

  function applyCardBuilderStateObject(state) {
    if (!state || typeof state !== "object") return;
    if (targetDirInput && typeof state.target_dir === "string") {
      targetDirInput.value = state.target_dir;
    }
    if (Array.isArray(state.cards) && state.cards.length > 0) {
      cards = state.cards;
      const idx = typeof state.active_index === "number" ? state.active_index : 0;
      activeIndex = Math.max(0, Math.min(cards.length - 1, idx));
      renderCardList();
      refreshInputsFromActiveCard();
      renderCardCanvas();
    } else if (typeof renderCardList === "function") {
      renderCardList();
      renderCardCanvas();
    }
  }

  window.__deckgenGetCardBuilderState = getCardBuilderStateObject;
  window.__deckgenApplyCardBuilderState = function (state) {
    applyCardBuilderStateObject(state);
    saveCardBuilderState();
    showStatus("Project state loaded.");
  };

  if (targetDirInput) {
    targetDirInput.addEventListener("change", saveCardBuilderState);
  }
  if (cbDirSelectBtn) {
    cbDirSelectBtn.addEventListener("click", () => {
      setTimeout(saveCardBuilderState, 0);
    });
  }
  window.addEventListener("beforeunload", () => {
    if (!window.__deckgenSkipSaveOnUnload) saveCardBuilderState();
  });

  async function initCardBuilder() {
    initLayerPickers();
    await fetchTemplateCatalog();
    try {
      const raw = localStorage.getItem(CB_STATE_KEY);
      if (raw) applyCardBuilderStateObject(JSON.parse(raw));
    } catch (e) {}
    if (document.fonts) {
      try {
        await Promise.all([
          document.fonts.load('16px "Mana"'),
          document.fonts.load('16px "Keyrune"'),
          document.fonts.load('bold 16px "BelerenLocal"'),
          document.fonts.load('16px "MPlantinLocal"'),
        ]);
        await document.fonts.ready;
      } catch (e) {
        console.warn("Font preload notice:", e);
      }
    }
    manaGlyphCache.clear();
    keyruneGlyphCache.clear();
    renderCardCanvas();
  }

  initCardBuilder();
})();
