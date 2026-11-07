import hashlib
import io
import json
import logging
import os
import re
import shutil
import string
import subprocess
import tempfile
import threading
import webbrowser
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageOps
import tornado.escape
import tornado.httpserver
import tornado.httputil
import tornado.ioloop
import tornado.web


PORT = 8766
DPI = 300
PREVIEW_DPI = 100
CARD_W_MM = 63.5
CARD_H_MM = 88.9
MM_TO_INCH = 25.4
PAPER_SIZES = {
    "a3": (297.0, 420.0),
    "a4": (210.0, 297.0),
    "a4-3": (297.0, 420.0),
}
PREVIEW_CACHE_DIR = "/tmp/opencode"
STANDARD_CARD_W_PX = 750
STANDARD_CARD_H_PX = 1050

progress_state = {"percent": 0, "status": "idle", "done": True}
_progress_lock = threading.Lock()


def _set_progress(percent, status, done):
    with _progress_lock:
        progress_state["percent"] = percent
        progress_state["status"] = status
        progress_state["done"] = done


def _progress_callback(current, total):
    percent = int(current * 100 / total) if total else 0
    _set_progress(percent, f"rendered {current} of {total}", False)


FORM_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>DeckGen Sheet Generator</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #ffffff;
      --fg: #1e293b;
      --panel-bg: #ffffff;
      --preview-bg: #f5f5f5;
      --border: #cccccc;
      --muted: #64748b;
      --input-bg: #ffffff;
      --input-fg: #1e293b;
      --hover-bg: #f0f0f0;
      --accent: #2563eb;
      --accent-hover: #1d4ed8;
      --accent-fg: #ffffff;
      --info: #0284c7;
      --ok: #15803d;
      --ok-bg: #dcfce7;
      --warn: #b45309;
      --danger: #c00;
      --danger-bg: #fff0f0;
      --danger-hover: #fdd;
      --danger-border: #fcc;
      --shadow: rgba(0, 0, 0, 0.1);
      --scrim: rgba(0, 0, 0, 0.65);
      --overlay-bg: rgba(255, 255, 255, 0.8);
      --modal-bg: #ffffff;
      --modal-header-bg: #1e1e1e;
      --modal-header-fg: #ffffff;
      --modal-footer-bg: #f8fafc;
      --table-head-bg: #f1f5f9;
      --table-head-fg: #334155;
      --table-border: #e2e8f0;
      --table-row-hover: #f8fafc;
      --stat-bg: #f8f9fa;
      --stat-border: #e2e8f0;
      --progress-bg: #dddddd;
      --progress-fill: #333333;
      --progress-fg: #333333;
    }
    [data-theme="dark"] {
      color-scheme: dark;
      --bg: #0f172a;
      --fg: #e2e8f0;
      --panel-bg: #111c2e;
      --preview-bg: #0b1220;
      --border: #334155;
      --muted: #94a3b8;
      --input-bg: #1e293b;
      --input-fg: #e2e8f0;
      --hover-bg: #1e293b;
      --accent: #3b82f6;
      --accent-hover: #60a5fa;
      --accent-fg: #ffffff;
      --info: #38bdf8;
      --ok: #4ade80;
      --ok-bg: #14532d;
      --warn: #fbbf24;
      --danger: #f87171;
      --danger-bg: #3b1219;
      --danger-hover: #4a1a22;
      --danger-border: #7f1d1d;
      --shadow: rgba(0, 0, 0, 0.5);
      --scrim: rgba(0, 0, 0, 0.75);
      --overlay-bg: rgba(15, 23, 42, 0.85);
      --modal-bg: #1e293b;
      --modal-header-bg: #0b1220;
      --modal-header-fg: #e2e8f0;
      --modal-footer-bg: #16233a;
      --table-head-bg: #16233a;
      --table-head-fg: #cbd5e1;
      --table-border: #334155;
      --table-row-hover: #1e293b;
      --stat-bg: #16233a;
      --stat-border: #334155;
      --progress-bg: #334155;
      --progress-fill: #60a5fa;
      --progress-fg: #e2e8f0;
    }
    html, body {
      height: 100%;
      margin: 0;
      font-family: sans-serif;
      background: var(--bg);
      color: var(--fg);
    }
    a { color: var(--accent); }
    .app {
      display: flex;
      height: 100vh;
      background: var(--bg);
      color: var(--fg);
    }
    .panel {
      width: 20rem;
      flex: 0 0 20rem;
      padding: 1em;
      overflow-y: auto;
      background: var(--panel-bg);
      color: var(--fg);
      border-right: 1px solid var(--border);
      box-sizing: border-box;
      transition: flex-basis 0.2s ease, width 0.2s ease, padding 0.2s ease;
    }
    .panel.collapsed,
    html[data-panel-collapsed] .panel {
      flex: 0 0 0;
      width: 0;
      padding: 0;
      border-right: 0;
      overflow: hidden;
    }
    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5em;
      margin-bottom: 0.6em;
    }
    .panel h1 { font-size: 1.2em; margin: 0; color: var(--fg); }
    .panel-head .head-actions { display: flex; gap: 0.3em; flex-shrink: 0; }
    .icon-btn {
      margin: 0;
      padding: 0.3em 0.5em;
      background: var(--hover-bg);
      color: var(--fg);
      border: 1px solid var(--border);
      border-radius: 4px;
      font-size: 0.95em;
      line-height: 1;
      cursor: pointer;
    }
    .icon-btn:hover { background: var(--border); }
    .icon-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
    .panel-rail {
      display: none;
      flex: 0 0 28px;
      width: 28px;
      align-items: flex-start;
      justify-content: center;
      padding-top: 0.8em;
      box-sizing: border-box;
      background: var(--panel-bg);
      border-right: 1px solid var(--border);
    }
    .panel.collapsed + .panel-rail,
    html[data-panel-collapsed] .panel-rail { display: flex; }
    .panel-rail .icon-btn { padding: 0.45em 0.3em; }
    label { display: block; margin-top: 1em; color: var(--fg); }
    input, select {
      width: 100%;
      padding: 0.4em;
      box-sizing: border-box;
      background: var(--input-bg);
      color: var(--input-fg);
      border: 1px solid var(--border);
      border-radius: 4px;
    }
    button {
      margin-top: 1.5em;
      padding: 0.6em 1.2em;
      background: var(--input-bg);
      color: var(--fg);
      border: 1px solid var(--border);
      border-radius: 4px;
      font: inherit;
      cursor: pointer;
    }
    button:hover { background: var(--hover-bg); }
    .preview {
      flex: 1 1 auto;
      min-width: 0;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      background: var(--preview-bg);
      overflow: auto;
      position: relative;
    }
    .preview img {
      display: none;
      max-width: 95%;
      max-height: 95%;
      border: 1px solid var(--border);
      box-shadow: 0 2px 6px var(--shadow);
    }
    .error { color: var(--danger); margin-top: 1em; }
    #save-result { margin-top: 1em; word-break: break-all; }
    #save-result a { display: block; margin-top: 0.5em; }
    .overlay {
      position: fixed;
      inset: 0;
      background: var(--overlay-bg);
      display: none;
      justify-content: center;
      align-items: center;
      z-index: 100;
    }
    .overlay.active { display: flex; }
    .progress-box { text-align: center; }
    .progress-bar-bg {
      width: 300px;
      height: 20px;
      background: var(--progress-bg);
      border-radius: 4px;
      overflow: hidden;
      margin: 0 auto 1em;
    }
    .progress-bar-fill {
      height: 100%;
      width: 0%;
      background: var(--progress-fill);
      transition: width 0.2s;
    }
    #progress-status { color: var(--progress-fg); }
    .input-with-buttons {
      display: flex;
      gap: 0.3em;
      align-items: center;
      margin-top: 0.3em;
    }
    .input-with-buttons button {
      margin-top: 0;
      padding: 0.4em 0.8em;
      font-weight: bold;
      font-size: 1.1em;
      cursor: pointer;
      width: auto;
    }
    .input-with-buttons input {
      text-align: center;
    }
    .field-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 1em;
    }
    .field-header label {
      margin-top: 0;
      font-weight: bold;
    }
    .btn-clear-field {
      background: none;
      border: none;
      color: var(--muted);
      cursor: pointer;
      font-size: 0.8em;
      padding: 0.2em 0.4em;
      margin: 0;
      border-radius: 3px;
    }
    .btn-clear-field:hover {
      color: var(--danger);
      background: var(--danger-bg);
    }
    .btn-group {
      display: flex;
      gap: 0.5em;
      margin-top: 0.8em;
    }
    .btn-group button {
      margin-top: 0;
      flex: 1;
    }
    .btn-secondary {
      background: var(--hover-bg);
      color: var(--fg);
      border: 1px solid var(--border);
      cursor: pointer;
    }
    .btn-secondary:hover {
      background: var(--border);
    }
    .btn-danger {
      background: var(--danger-bg);
      color: var(--danger);
      border: 1px solid var(--danger-border);
      cursor: pointer;
    }
    .btn-danger:hover {
      background: var(--danger-hover);
    }
    .modal-overlay {
      position: fixed;
      inset: 0;
      background: var(--scrim);
      display: none;
      justify-content: center;
      align-items: center;
      z-index: 200;
      backdrop-filter: blur(2px);
    }
    .modal-overlay.active { display: flex; }
    .modal-content {
      background: var(--modal-bg);
      color: var(--fg);
      width: 92%;
      max-width: 1050px;
      max-height: 88vh;
      border-radius: 8px;
      box-shadow: 0 10px 40px var(--shadow);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.8em 1.2em;
      background: var(--modal-header-bg);
      color: var(--modal-header-fg);
    }
    .modal-header h2 {
      margin: 0;
      font-size: 1.15em;
      display: flex;
      align-items: center;
      gap: 0.5em;
    }
    .modal-close {
      background: none;
      border: none;
      color: var(--muted);
      font-size: 1.6em;
      cursor: pointer;
      line-height: 1;
      padding: 0 0.2em;
    }
    .modal-close:hover { color: var(--modal-header-fg); }
    .modal-body {
      padding: 1.2em;
      overflow-y: auto;
      flex: 1;
      background: var(--modal-bg);
      color: var(--fg);
    }
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 0.8em;
      margin-bottom: 1em;
    }
    .stat-card {
      background: var(--stat-bg);
      border: 1px solid var(--stat-border);
      border-radius: 6px;
      padding: 0.6em 0.8em;
      text-align: center;
    }
    .stat-card .val { font-size: 1.4em; font-weight: bold; color: var(--fg); }
    .stat-card .lbl {
      font-size: 0.75em;
      color: var(--muted);
      text-transform: uppercase;
      font-weight: 600;
      margin-top: 0.2em;
    }
    .modal-tabs {
      display: flex;
      gap: 0.4em;
      border-bottom: 2px solid var(--table-border);
      margin-bottom: 0.8em;
    }
    .tab-btn {
      background: none;
      border: none;
      padding: 0.6em 1em;
      font-size: 0.85em;
      font-weight: 600;
      cursor: pointer;
      color: var(--muted);
      border-bottom: 2px solid transparent;
      margin-bottom: -2px;
    }
    .tab-btn.active {
      color: var(--accent);
      border-bottom-color: var(--accent);
    }
    .modal-table-container {
      max-height: 380px;
      overflow-y: auto;
      border: 1px solid var(--table-border);
      border-radius: 6px;
    }
    .deck-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85em;
    }
    .deck-table th {
      background: var(--table-head-bg);
      position: sticky;
      top: 0;
      z-index: 2;
      padding: 0.6em 0.8em;
      text-align: left;
      border-bottom: 2px solid var(--border);
      font-weight: 600;
      color: var(--table-head-fg);
    }
    .deck-table td {
      padding: 0.5em 0.8em;
      border-bottom: 1px solid var(--table-border);
      vertical-align: middle;
    }
    .deck-table tr:hover { background: var(--table-row-hover); }
    .badge {
      display: inline-block;
      padding: 0.2em 0.6em;
      border-radius: 12px;
      font-size: 0.78em;
      font-weight: 600;
    }
    .badge-ok { background: #dcfce7; color: #15803d; }
    .badge-warn { background: #fef3c7; color: #b45309; }
    .badge-missing { background: #fee2e2; color: #b91c1c; }
    .badge-extra { background: #e0e7ff; color: #4338ca; }
    .badge-custom { background: #dbeafe; color: #1e40af; border: 1px solid #93c5fd; }
    .badge-generic { background: #f1f5f9; color: #64748b; }
    [data-theme="dark"] .badge-ok { background: #14532d; color: #bbf7d0; }
    [data-theme="dark"] .badge-warn { background: #451a03; color: #fcd34d; }
    [data-theme="dark"] .badge-missing { background: #450a0a; color: #fca5a5; }
    [data-theme="dark"] .badge-extra { background: #1e1b4b; color: #c7d2fe; }
    [data-theme="dark"] .badge-custom { background: #1e3a8a; color: #dbeafe; border-color: #3b82f6; }
    [data-theme="dark"] .badge-generic { background: #1e293b; color: #cbd5e1; }
    .btn-action-small {
      background: var(--accent);
      color: var(--accent-fg);
      border: none;
      border-radius: 4px;
      padding: 0.35em 0.7em;
      font-size: 0.8em;
      cursor: pointer;
      margin: 0;
      font-weight: 600;
    }
    .btn-action-small:hover { background: var(--accent-hover); }
    .btn-action-small:disabled {
      background: var(--border);
      cursor: not-allowed;
    }
    @media (max-width: 900px) {
      .panel { width: 16rem; flex-basis: 16rem; }
    }
  </style>
  <script>
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
  </script>
</head>
<body>
  <div id="loading-overlay" class="overlay">
    <div class="progress-box">
      <div class="progress-bar-bg"><div id="progress-bar" class="progress-bar-fill"></div></div>
      <div id="progress-status">Processing...</div>
    </div>
  </div>
  <div class="app">
    <div class="panel" id="options-panel">
      <div class="panel-head">
        <h1>DeckGen Sheet Generator</h1>
        <div class="head-actions">
          <button type="button" id="theme-toggle" class="icon-btn" title="Cambiar a tema oscuro" aria-label="Cambiar a tema oscuro">🌙</button>
          <button type="button" id="panel-toggle" class="icon-btn" title="Ocultar panel de opciones" aria-label="Ocultar panel de opciones" aria-expanded="true" aria-controls="options-panel">«</button>
        </div>
      </div>
      <form id="deckform" method="post" action="/generate" enctype="multipart/form-data">
        <div class="field-header">
          <label for="source-files">PDF cards source</label>
          <button type="button" class="btn-clear-field" data-target="source-files" title="Limpiar selección de carpeta">✕ Limpiar</button>
        </div>
        <input type="file" id="source-files" webkitdirectory directory multiple name="source_files">

        <div class="field-header">
          <label for="back-file">Card back (PDF / imagen)</label>
          <button type="button" class="btn-clear-field" data-target="back-file" title="Limpiar reverso seleccionado">✕ Limpiar</button>
        </div>
        <input type="file" name="back_file" id="back-file" accept=".pdf,.png,.jpg,.jpeg">
        <button type="button" id="open-custom-backs-btn" class="btn-secondary" style="margin-top: 0.4em; margin-bottom: 0.6em; width: 100%; font-weight: 600; padding: 0.5em 0.8em; display: flex; align-items: center; justify-content: center; gap: 0.5em; background: var(--hover-bg); border: 1px solid var(--border); border-radius: 4px; cursor: pointer;">
          <span>🔄</span> Reversos custom / MDFC (PDF)
          <span id="custom-backs-badge" style="display: none; background: var(--accent); color: #fff; border-radius: 10px; padding: 1px 7px; font-size: 0.78em; font-weight: bold;">0 MDFC</span>
        </button>

        <div class="field-header">
          <label for="export-dir">Export directory (destino)</label>
          <button type="button" class="btn-clear-field" data-target="export-dir" title="Limpiar directorio">✕ Limpiar</button>
        </div>
        <input type="text" name="export_dir" id="export-dir" value="$export_dir" placeholder="/home/choroy/don-corleone">
        <button type="button" id="check-deck-btn" class="btn-secondary" style="margin-top: 0.4em; width: 100%; font-weight: bold; padding: 0.5em 0.8em; display: flex; align-items: center; justify-content: center; gap: 0.5em;">
          <span>📋</span> Verificar mazo (XML / MTGO .txt)
        </button>

        <label>Face
          <select name="face" id="face-select">
            <option value="fronts" $face_fronts_selected>fronts</option>
            <option value="backs" $face_backs_selected>backs</option>
          </select>
        </label>
        <label id="duplex-flip-label" style="display: flex; align-items: center; gap: 0.5em; font-size: 0.88em; margin-top: 0.2em; margin-bottom: 0.6em; cursor: pointer;">
          <input type="checkbox" name="duplex_flip" id="duplex-flip" value="true" $duplex_flip_checked>
          <span>Espejar reversos (dúplex)</span>
        </label>
        <div class="field-header">
          <label for="card-spacing">Card spacing (mm)</label>
          <button type="button" class="btn-clear-field" id="spacing-reset" title="Resetear espaciado a 0">✕ Reset (0)</button>
        </div>
        <div class="input-with-buttons">
          <button type="button" id="spacing-minus">-</button>
          <input type="number" name="card_spacing" id="card-spacing" value="$card_spacing" step="0.5" min="0">
          <button type="button" id="spacing-plus">+</button>
        </div>
        <label>Paper
          <select name="paper">
            <option value="a3" $paper_a3_selected>a3</option>
            <option value="a4" $paper_a4_selected>a4</option>
            <option value="a4-3" $paper_a4_3_selected>a4-3</option>
          </select>
        </label>
        <label>Landscape
          <input type="checkbox" name="landscape" value="true" $landscape_checked>
        </label>
        <label>Cut lines
          <select name="cut">
            <option value="none" $cut_none_selected>none</option>
            <option value="full" $cut_full_selected>full</option>
            <option value="corners" $cut_corners_selected>corners</option>
          </select>
        </label>
        <label>Cut color (hex)
          <input type="text" name="color" id="color-text" value="$color" required>
          <input type="color" id="color-picker" value="$color">
        </label>
        <label>Cut thickness (pt)
          <input type="number" name="thickness" value="$thickness" step="0.1" min="0.1" required>
        </label>
        <label>Mark length (mm)
          <input type="number" name="mark_len" value="$mark_len" step="0.1" min="1" required>
        </label>
        <div class="btn-group">
          <button type="submit">Generate PDF</button>
          <button type="button" id="preview-btn">Previsualizar</button>
        </div>
        <div class="btn-group">
          <button type="button" id="clear-cache-btn" class="btn-secondary" title="Eliminar previsualizaciones cacheadas">Limpiar caché</button>
          <button type="button" id="reset-all-btn" class="btn-danger" title="Restablecer todos los campos y caché">Reset general</button>
        </div>
      </form>
      <div class="field-header" style="margin-top: 1.5em;">
        <label for="image-input">Images to convert (PNG/JPG)</label>
        <button type="button" class="btn-clear-field" data-target="image-input" title="Limpiar imágenes seleccionadas">✕ Limpiar</button>
      </div>
      <input type="file" id="image-input" accept=".png,.jpg,.jpeg,image/png,image/jpeg" multiple>
      <button type="button" id="convert-btn">Convertir imágenes a PDF estándar</button>
      <div id="convert-result"></div>
      <div id="error-message" class="error">$error</div>
      <div id="save-result"></div>
    </div>
    <div class="panel-rail">
      <button type="button" id="panel-rail-toggle" class="icon-btn" title="Mostrar panel de opciones" aria-label="Mostrar panel de opciones" aria-expanded="false" aria-controls="options-panel">»</button>
    </div>
    <div class="preview">
      <img id="preview" alt="Preview">
    </div>
  </div>

  <div id="deck-modal" class="modal-overlay">
    <div class="modal-content">
      <div class="modal-header">
        <h2><span>📋</span> Verificación e Inspección del Mazo (XML / MTGO .txt)</h2>
        <button type="button" class="modal-close" id="modal-close-btn">&times;</button>
      </div>
      <div class="modal-body">
        <div style="display: flex; gap: 0.8em; align-items: center; margin-bottom: 1em; flex-wrap: wrap;">
          <label style="font-weight: 600; font-size: 0.9em; margin: 0;">Lista de mazo (.txt / .xml):</label>
          <select id="xml-select" style="flex: 1; min-width: 200px; padding: 0.4em; border-radius: 4px; border: 1px solid var(--border);"></select>
          <label class="btn-secondary" style="margin: 0; padding: 0.4em 0.8em; cursor: pointer; border-radius: 4px; font-size: 0.85em; display: inline-flex; align-items: center; gap: 0.3em;">
            <span>📁</span> Subir TXT / XML
            <input type="file" id="xml-file-input" accept=".xml,.txt,text/plain" style="display: none;">
          </label>
          <button type="button" id="xml-refresh-btn" class="btn-secondary" style="margin: 0; padding: 0.4em 0.8em; font-size: 0.85em;">↻ Recargar</button>
        </div>

        <div id="deck-stats" class="stats-grid">
          <div class="stat-card"><div class="val" id="stat-target">100</div><div class="lbl">Objetivo</div></div>
          <div class="stat-card"><div class="val" id="stat-disk" style="color: var(--info);">-</div><div class="lbl">En disco</div></div>
          <div class="stat-card"><div class="val" id="stat-xml" style="color: var(--muted);">-</div><div class="lbl">Cartas en lista</div></div>
          <div class="stat-card"><div class="val" id="stat-needs" style="color: var(--warn);">-</div><div class="lbl">Por duplicar</div></div>
          <div class="stat-card"><div class="val" id="stat-missing" style="color: var(--danger);">-</div><div class="lbl">Faltantes</div></div>
        </div>

        <div id="deck-feedback" style="display: none; padding: 0.6em 0.8em; border-radius: 4px; margin-bottom: 0.8em; font-size: 0.85em;"></div>

        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.8em; gap: 1em; flex-wrap: wrap;">
          <button type="button" id="auto-duplicate-btn" style="margin: 0; background: var(--ok); color: #fff; font-weight: bold; padding: 0.5em 1em; border: none; border-radius: 4px; cursor: pointer; display: flex; align-items: center; gap: 0.4em;">
            <span>⚡</span> Duplicar cartas repetidas según lista
          </button>
          <input type="text" id="deck-search-input" placeholder="Filtrar por nombre..." style="width: 220px; padding: 0.4em 0.6em; border-radius: 4px; border: 1px solid var(--border); margin: 0; font-size: 0.85em;">
        </div>

        <div class="modal-tabs">
          <button type="button" class="tab-btn active" data-tab="all">Todas (<span id="count-all">0</span>)</button>
          <button type="button" class="tab-btn" data-tab="needs_copies" style="color: var(--warn);">⚠️ Por duplicar (<span id="count-needs">0</span>)</button>
          <button type="button" class="tab-btn" data-tab="missing" style="color: var(--danger);">❌ Faltantes (<span id="count-missing">0</span>)</button>
          <button type="button" class="tab-btn" data-tab="ok" style="color: var(--ok);">✅ Completas (<span id="count-ok">0</span>)</button>
          <button type="button" class="tab-btn" data-tab="extra">Tokens / Extras (<span id="count-extra">0</span>)</button>
        </div>

        <div class="modal-table-container">
          <table class="deck-table" id="deck-table">
            <thead>
              <tr>
                <th style="width: 14%;">Slots</th>
                <th style="width: 36%;">Carta / Query</th>
                <th style="width: 8%;">Req.</th>
                <th style="width: 8%;">Disco</th>
                <th style="width: 14%;">Estado</th>
                <th style="width: 20%;">Acción</th>
              </tr>
            </thead>
            <tbody id="deck-table-body">
              <tr><td colspan="6" style="text-align: center; color: var(--muted); padding: 2em;">Cargando datos del mazo...</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      <div style="display: flex; justify-content: flex-end; padding: 0.8em 1.2em; border-top: 1px solid var(--table-border); background: var(--modal-footer-bg);">
        <button type="button" class="btn-secondary" id="modal-close-footer-btn" style="margin: 0; padding: 0.4em 1em;">Cerrar</button>
      </div>
    </div>
  </div>

  <!-- Modal Custom Card Backs (MDFC) -->
  <div id="custom-backs-modal" class="modal-overlay">
    <div class="modal-content">
      <div class="modal-header">
        <h2><span>🔄</span> Reversos Personalizados / Cartas Doble Cara (MDFC)</h2>
        <button type="button" class="modal-close" id="cb-modal-close-btn">&times;</button>
      </div>
      <div class="modal-body">
        <p style="margin-top: 0; color: var(--muted); font-size: 0.88em;">
          Asigna un archivo PDF de reverso individual a cartas que se dan vuelta (MDFC / Transform). Las cartas sin reverso personalizado usarán el reverso genérico.
        </p>

        <div id="cb-stats" class="stats-grid">
          <div class="stat-card">
            <div class="val" id="cb-stat-total">0</div>
            <div class="lbl">Total Cartas</div>
          </div>
          <div class="stat-card">
            <div class="val" id="cb-stat-generic" style="color: var(--muted);">0</div>
            <div class="lbl">Reverso Genérico</div>
          </div>
          <div class="stat-card">
            <div class="val" id="cb-stat-custom" style="color: var(--accent);">0</div>
            <div class="lbl">Reverso Custom (PDF)</div>
          </div>
          <div class="stat-card">
            <div class="val" id="cb-stat-available" style="color: var(--ok);">0</div>
            <div class="lbl">PDFs en backs/</div>
          </div>
        </div>

        <div id="cb-feedback" style="display: none; padding: 0.6em 0.8em; border-radius: 4px; margin-bottom: 0.8em; font-size: 0.85em;"></div>

        <div style="display: flex; gap: 0.6em; align-items: center; margin-bottom: 0.8em; flex-wrap: wrap;">
          <input type="text" id="cb-search-input" placeholder="Buscar carta por nombre o archivo..." style="flex: 1; min-width: 180px; padding: 0.45em 0.8em; font-size: 0.85em; border: 1px solid var(--border); border-radius: 4px;">
          <select id="cb-filter-select" style="padding: 0.45em 0.8em; font-size: 0.85em; border: 1px solid var(--border); border-radius: 4px;">
            <option value="all">Todas las cartas</option>
            <option value="custom">Solo con reverso custom</option>
            <option value="generic">Solo reverso genérico</option>
          </select>
          <button type="button" id="cb-autodetect-btn" style="background: var(--info); color: #fff; padding: 0.45em 0.8em; font-size: 0.85em; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; display: flex; align-items: center; gap: 0.3em;">
            <span>⚡</span> Auto-detectar
          </button>
          <button type="button" id="cb-bulk-assign-btn" style="background: var(--accent); color: #fff; padding: 0.45em 0.8em; font-size: 0.85em; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; display: flex; align-items: center; gap: 0.3em;">
            <span>📤</span> Asignar PDF a seleccionadas (<span id="cb-selected-count">0</span>)
          </button>
          <button type="button" id="cb-bulk-remove-btn" style="background: var(--danger); color: #fff; padding: 0.45em 0.8em; font-size: 0.85em; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; display: flex; align-items: center; gap: 0.3em;">
            <span>✕</span> Quitar custom
          </button>
        </div>

        <input type="file" id="cb-single-upload" accept=".pdf" style="display: none;">
        <input type="file" id="cb-bulk-upload" accept=".pdf" style="display: none;">

        <div class="modal-table-container">
          <table class="deck-table" id="cb-table">
            <thead>
              <tr>
                <th style="width: 34px; text-align: center;"><input type="checkbox" id="cb-select-all"></th>
                <th style="width: 38px;">#</th>
                <th>Carta Frontal</th>
                <th>Archivo Front</th>
                <th>Reverso Asignado</th>
                <th style="width: 240px; text-align: right;">Acciones</th>
              </tr>
            </thead>
            <tbody id="cb-table-body">
              <tr><td colspan="6" style="text-align: center; color: var(--muted); padding: 2em;">Cargando cartas...</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.8em 1.2em; border-top: 1px solid var(--table-border); background: var(--modal-footer-bg);">
        <div style="font-size: 0.82em; color: var(--muted);">
          Directorio: <strong id="cb-footer-dir" style="color: var(--fg);">-</strong>
        </div>
        <button type="button" id="cb-modal-footer-close-btn" class="btn-secondary" style="margin: 0; padding: 0.45em 1.2em; font-weight: 600; cursor: pointer;">Cerrar</button>
      </div>
    </div>
  </div>
  <script>
    const form = document.getElementById('deckform');
    const previewBtn = document.getElementById('preview-btn');
    const previewImg = document.getElementById('preview');
    const overlay = document.getElementById('loading-overlay');
    const errorMessage = document.getElementById('error-message');
    const saveResult = document.getElementById('save-result');
    const colorText = document.getElementById('color-text');
    const colorPicker = document.getElementById('color-picker');
    const progressBar = document.getElementById('progress-bar');
    const progressStatus = document.getElementById('progress-status');
    const convertBtn = document.getElementById('convert-btn');
    const imageInput = document.getElementById('image-input');
    const convertResult = document.getElementById('convert-result');
    const spacingInput = document.getElementById('card-spacing');
    const spacingMinus = document.getElementById('spacing-minus');
    const spacingPlus = document.getElementById('spacing-plus');
    const spacingReset = document.getElementById('spacing-reset');
    const clearCacheBtn = document.getElementById('clear-cache-btn');
    const resetAllBtn = document.getElementById('reset-all-btn');

    const themeToggle = document.getElementById('theme-toggle');
    const panelToggle = document.getElementById('panel-toggle');
    const panelRailToggle = document.getElementById('panel-rail-toggle');
    const optionsPanel = document.getElementById('options-panel');

    function applyTheme(theme) {
      const dark = theme === 'dark';
      document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
      if (themeToggle) {
        themeToggle.textContent = dark ? '☀' : '🌙';
        const label = dark ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro';
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
        const label = collapsed ? 'Mostrar' : 'Ocultar';
        panelToggle.title = label + ' panel de opciones';
        panelToggle.setAttribute('aria-label', label + ' panel de opciones');
        panelToggle.textContent = collapsed ? '»' : '«';
      }
      if (panelRailToggle) {
        panelRailToggle.title = 'Mostrar panel de opciones';
        panelRailToggle.setAttribute('aria-label', 'Mostrar panel de opciones');
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
    // fin bloque tema/panel

    // Reset por campo
    document.querySelectorAll('.btn-clear-field').forEach(btn => {
      btn.addEventListener('click', function() {
        const targetId = this.getAttribute('data-target');
        if (!targetId) return;
        const targetInput = document.getElementById(targetId);
        if (targetInput) {
          targetInput.value = '';
          targetInput.dispatchEvent(new Event('change'));
        }
      });
    });

    if (spacingReset) {
      spacingReset.addEventListener('click', function() {
        spacingInput.value = '0';
      });
    }

    if (clearCacheBtn) {
      clearCacheBtn.addEventListener('click', async function() {
        setLoading(true);
        setError('');
        try {
          const res = await fetch('/clear-cache', { method: 'POST' });
          const data = await res.json();
          saveResult.innerHTML = '<p style="color: var(--ok);">Caché limpiado con éxito (' + data.cleared + ' archivos eliminados).</p>';
        } catch (err) {
          setError('Error al limpiar caché: ' + err.message);
        } finally {
          setLoading(false);
        }
      });
    }

    if (resetAllBtn) {
      resetAllBtn.addEventListener('click', async function() {
        setLoading(true);
        setError('');
        form.reset();
        document.getElementById('source-files').value = '';
        document.getElementById('back-file').value = '';
        document.getElementById('export-dir').value = '';
        spacingInput.value = '0';
        imageInput.value = '';

        previewImg.src = '';
        previewImg.style.display = 'none';
        errorMessage.textContent = '';
        saveResult.innerHTML = '';
        convertResult.textContent = '';

        try {
          const res = await fetch('/clear-cache', { method: 'POST' });
          const data = await res.json();
          saveResult.innerHTML = '<p style="color: var(--ok);">Reset general completado (' + data.cleared + ' archivos de caché eliminados).</p>';
        } catch (err) {
          saveResult.innerHTML = '<p style="color: var(--ok);">Formulario restablecido.</p>';
        } finally {
          setLoading(false);
        }
      });
    }

    spacingMinus.addEventListener('click', function() {
      let val = parseFloat(spacingInput.value) || 0;
      val = Math.max(0, parseFloat((val - 0.5).toFixed(1)));
      spacingInput.value = val;
    });

    spacingPlus.addEventListener('click', function() {
      let val = parseFloat(spacingInput.value) || 0;
      val = parseFloat((val + 0.5).toFixed(1));
      spacingInput.value = val;
    });

    colorPicker.addEventListener('input', function() {
      colorText.value = colorPicker.value;
    });

    colorText.addEventListener('input', function() {
      if (/^#[0-9A-Fa-f]{6}$$/.test(colorText.value)) {
        colorPicker.value = colorText.value;
      }
    });

    function setLoading(show) {
      overlay.classList.toggle('active', show);
    }

    function setError(message) {
      errorMessage.textContent = message;
    }

    window.addEventListener('load', function() { setLoading(false); });
    window.addEventListener('error', function() { setLoading(false); });
    window.addEventListener('unhandledrejection', function() { setLoading(false); });

    previewBtn.addEventListener('click', async function() {
      setLoading(true);
      setError('');
      try {
        const response = await fetch('/preview', { method: 'POST', body: new FormData(form) });
        if (!response.ok) {
          setError('Preview failed: ' + await response.text());
          previewImg.style.display = 'none';
          return;
        }
        previewImg.src = URL.createObjectURL(await response.blob());
        previewImg.style.display = 'block';
      } catch (err) {
        setError('Preview failed: ' + err.message);
      } finally {
        setLoading(false);
      }
    });

    convertBtn.addEventListener('click', async function() {
      if (!imageInput.files.length) {
        setError('Select at least one image to convert.');
        return;
      }
      const exportDir = form.querySelector('input[name="export_dir"]').value.trim();
      if (!exportDir) {
        setError('Type the local path of the export directory.');
        return;
      }
      setLoading(true);
      setError('');
      convertResult.textContent = '';
      const body = new FormData();
      body.append('export_dir', exportDir);
      for (const file of imageInput.files) {
        body.append('images', file);
      }
      try {
        const response = await fetch('/convert', { method: 'POST', body: body });
        if (!response.ok) {
          setError('Convert failed: ' + await response.text());
          return;
        }
        const data = await response.json();
        convertResult.textContent = 'Converted ' + data.count + ' PDFs to: ' + data.path;
      } catch (err) {
        setError('Convert failed: ' + err.message);
      } finally {
        setLoading(false);
      }
    });

    form.addEventListener('submit', async function(event) {
      event.preventDefault();
      setLoading(true);
      setError('');
      progressBar.style.width = '0%';
      progressStatus.textContent = 'Starting...';
      const intervalId = setInterval(async function() {
        try {
          const response = await fetch('/progress');
          const data = await response.json();
          progressBar.style.width = data.percent + '%';
          progressStatus.textContent = data.status;
          if (data.done) {
            clearInterval(intervalId);
          }
        } catch (err) {
          clearInterval(intervalId);
        }
      }, 500);
      try {
        const response = await fetch('/generate', { method: 'POST', body: new FormData(form) });
        clearInterval(intervalId);
        if (!response.ok) {
          let msg = await response.text();
          try {
            const errData = JSON.parse(msg);
            if (errData.error) msg = errData.error;
          } catch (parseErr) {}
          setError('Generate failed: ' + msg);
          saveResult.innerHTML = '';
          return;
        }
        const data = await response.json();
        setError('');
        saveResult.innerHTML = '';
        const pathP = document.createElement('p');
        pathP.textContent = 'Saved to: ' + data.path;
        saveResult.appendChild(pathP);
        if (data.download_url) {
          const link = document.createElement('a');
          link.href = data.download_url;
          link.textContent = 'Download PDF';
          link.target = '_blank';
          saveResult.appendChild(link);
        }
      } catch (err) {
        clearInterval(intervalId);
        setError('Generate failed: ' + err.message);
      } finally {
        setLoading(false);
      }
    });

    // Modal Deck Inspector
    const checkDeckBtn = document.getElementById('check-deck-btn');
    const deckModal = document.getElementById('deck-modal');
    const modalCloseBtn = document.getElementById('modal-close-btn');
    const modalCloseFooterBtn = document.getElementById('modal-close-footer-btn');
    const xmlSelect = document.getElementById('xml-select');
    const xmlFileInput = document.getElementById('xml-file-input');
    const xmlRefreshBtn = document.getElementById('xml-refresh-btn');
    const autoDuplicateBtn = document.getElementById('auto-duplicate-btn');
    const deckSearchInput = document.getElementById('deck-search-input');
    const deckFeedback = document.getElementById('deck-feedback');
    const deckTableBody = document.getElementById('deck-table-body');
    const tabBtns = document.querySelectorAll('.tab-btn');

    let currentDeckData = null;
    let currentTab = 'all';

    function showDeckFeedback(msg, isError) {
      deckFeedback.style.display = 'block';
      deckFeedback.style.background = isError ? 'var(--danger-bg)' : 'var(--ok-bg)';
      deckFeedback.style.color = isError ? 'var(--danger)' : 'var(--ok)';
      deckFeedback.textContent = msg;
    }

    function hideDeckFeedback() {
      deckFeedback.style.display = 'none';
    }

    async function loadDeckData(xmlPath, xmlFile) {
      const exportDir = document.getElementById('export-dir').value.trim();
      if (!exportDir && !xmlFile) {
        showDeckFeedback('Por favor introduce la ruta del directorio del mazo en "Export directory".', true);
        deckTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--danger); padding: 2em;">Falta especificar "Export directory".</td></tr>';
        return;
      }
      hideDeckFeedback();
      deckTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--muted); padding: 2em;">Inspeccionando cartas y comparando con lista de mazo (.txt / .xml)...</td></tr>';
      
      const formData = new FormData();
      formData.append('export_dir', exportDir);
      if (xmlPath) {
        formData.append('deck_path', xmlPath);
        formData.append('xml_path', xmlPath);
      }
      if (xmlFile) {
        formData.append('deck_file', xmlFile);
        formData.append('xml_file', xmlFile);
      }

      try {
        const res = await fetch('/deck/check', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.error) {
          showDeckFeedback(data.error, true);
          deckTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--danger); padding: 2em;">' + data.error + '</td></tr>';
          return;
        }
        currentDeckData = data;
        updateModalHeaderAndStats(data);
        renderDeckTable();
      } catch (err) {
        showDeckFeedback('Error de conexión: ' + err.message, true);
      }
    }

    function updateModalHeaderAndStats(data) {
      document.getElementById('stat-target').textContent = data.quantity || 100;
      document.getElementById('stat-disk').textContent = data.total_files_disk;
      const countCards = data.total_cards || data.total_cards_xml || 0;
      document.getElementById('stat-xml').textContent = countCards + ' (' + data.total_slots + ' slots)';
      
      let needsCount = 0;
      let missingCount = 0;
      let okCount = 0;
      data.cards.forEach(function(c) {
        if (c.status === 'needs_copies') needsCount++;
        else if (c.status === 'missing') missingCount++;
        else if (c.status === 'ok') okCount++;
      });
      document.getElementById('stat-needs').textContent = needsCount;
      document.getElementById('stat-missing').textContent = missingCount;

      document.getElementById('count-all').textContent = data.cards.length;
      document.getElementById('count-needs').textContent = needsCount;
      document.getElementById('count-missing').textContent = missingCount;
      document.getElementById('count-ok').textContent = okCount;
      document.getElementById('count-extra').textContent = data.extra_files ? data.extra_files.length : 0;

      xmlSelect.innerHTML = '';
      const fileList = data.available_files || data.available_xmls || [];
      const currentSelected = data.deck_file_path || data.xml_path;
      if (fileList && fileList.length > 0) {
        fileList.forEach(function(xp) {
          const opt = document.createElement('option');
          opt.value = xp;
          opt.textContent = xp;
          if (xp === currentSelected) opt.selected = true;
          xmlSelect.appendChild(opt);
        });
      } else if (currentSelected) {
        const opt = document.createElement('option');
        opt.value = currentSelected;
        opt.textContent = currentSelected;
        opt.selected = true;
        xmlSelect.appendChild(opt);
      }
    }

    function renderDeckTable() {
      if (!currentDeckData) return;
      const q = deckSearchInput.value.toLowerCase().trim();
      deckTableBody.innerHTML = '';

      if (currentTab === 'extra') {
        const extras = currentDeckData.extra_files || [];
        const filteredExtras = extras.filter(function(f) {
          return !q || f.toLowerCase().indexOf(q) !== -1;
        });
        if (filteredExtras.length === 0) {
          deckTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--muted); padding: 2em;">No hay archivos extras/tokens.</td></tr>';
          return;
        }
        filteredExtras.forEach(function(f) {
          const tr = document.createElement('tr');
          tr.innerHTML = '<td>-</td>' +
            '<td><strong>' + f + '</strong></td>' +
            '<td>-</td>' +
            '<td>1</td>' +
            '<td><span class="badge badge-extra">Token / Extra</span></td>' +
            '<td><button type="button" class="btn-action-small btn-dup" data-file="' + encodeURIComponent(f) + '" data-count="1">+1 Duplicar</button></td>';
          deckTableBody.appendChild(tr);
        });
        return;
      }

      const filteredCards = currentDeckData.cards.filter(function(c) {
        if (currentTab === 'needs_copies' && c.status !== 'needs_copies') return false;
        if (currentTab === 'missing' && c.status !== 'missing') return false;
        if (currentTab === 'ok' && c.status !== 'ok') return false;
        if (q) {
          const matchName = c.name && c.name.toLowerCase().indexOf(q) !== -1;
          const matchQuery = c.query && c.query.toLowerCase().indexOf(q) !== -1;
          const matchFile = c.matched_file && c.matched_file.toLowerCase().indexOf(q) !== -1;
          if (!matchName && !matchQuery && !matchFile) return false;
        }
        return true;
      });

      if (filteredCards.length === 0) {
        deckTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--muted); padding: 2em;">No se encontraron cartas en este filtro.</td></tr>';
        return;
      }

      filteredCards.forEach(function(c) {
        const tr = document.createElement('tr');
        let statusBadge = '';
        let actionBtn = '';

        if (c.status === 'ok') {
          statusBadge = '<span class="badge badge-ok">✅ Completa</span>';
          if (c.matched_file) {
            actionBtn = '<button type="button" class="btn-action-small btn-dup" data-file="' + encodeURIComponent(c.matched_file) + '" data-count="1">+1 Duplicar</button>';
          }
        } else if (c.status === 'needs_copies') {
          const diff = c.required_count - c.existing_copies;
          statusBadge = '<span class="badge badge-warn">⚠️ Faltan ' + diff + '</span>';
          if (c.matched_file) {
            actionBtn = '<button type="button" class="btn-action-small btn-dup" style="background: #d97706;" data-file="' + encodeURIComponent(c.matched_file) + '" data-count="' + diff + '">⚡ Duplicar ' + diff + '</button>';
          }
        } else {
          statusBadge = '<span class="badge badge-missing">❌ No en disco</span>';
          actionBtn = '<span style="color: var(--muted); font-size: 0.85em;">(Falta archivo)</span>';
        }

        const slotsDisplay = c.slots.join(', ');
        const matchedDisplay = c.matched_file ? '<div style="color: var(--ok); font-size: 0.85em;">📄 ' + c.matched_file + '</div>' : '';

        tr.innerHTML = '<td><code style="font-size: 0.82em; background: var(--table-head-bg); padding: 2px 4px; color: var(--fg); border-radius: 3px;">' + slotsDisplay + '</code></td>' +
          '<td><strong>' + c.name + '</strong>' +
          (c.query && c.query !== c.name ? '<div style="color: #64748b; font-size: 0.85em;">Query: ' + c.query + '</div>' : '') +
          matchedDisplay + '</td>' +
          '<td><strong>' + c.required_count + '</strong></td>' +
          '<td>' + c.existing_copies + '</td>' +
          '<td>' + statusBadge + '</td>' +
          '<td>' + actionBtn + '</td>';
        deckTableBody.appendChild(tr);
      });
    }

    deckTableBody.addEventListener('click', function(e) {
      const btn = e.target.closest('.btn-dup');
      if (btn) {
        const file = btn.getAttribute('data-file');
        const count = parseInt(btn.getAttribute('data-count'), 10) || 1;
        duplicateCard(file, count);
      }
    });

    window.duplicateCard = async function(encodedFile, count) {
      const fileName = decodeURIComponent(encodedFile);
      const exportDir = document.getElementById('export-dir').value.trim();
      const body = new FormData();
      body.append('export_dir', exportDir);
      body.append('target_file', fileName);
      body.append('copies_to_add', count);
      try {
        const res = await fetch('/deck/duplicate', { method: 'POST', body: body });
        const data = await res.json();
        if (data.error) {
          showDeckFeedback('Error al duplicar: ' + data.error, true);
        } else {
          showDeckFeedback(data.message || ('Se crearon ' + count + ' copia(s).'), false);
          loadDeckData(xmlSelect.value);
        }
      } catch (err) {
        showDeckFeedback('Error: ' + err.message, true);
      }
    };

    autoDuplicateBtn.addEventListener('click', async function() {
      const exportDir = document.getElementById('export-dir').value.trim();
      if (!exportDir) {
        showDeckFeedback('Especifica "Export directory".', true);
        return;
      }
      autoDuplicateBtn.disabled = true;
      autoDuplicateBtn.textContent = 'Duplicando...';
      const body = new FormData();
      body.append('export_dir', exportDir);
      body.append('auto_deck', 'true');
      body.append('auto_xml', 'true');
      if (xmlSelect.value) {
        body.append('deck_path', xmlSelect.value);
        body.append('xml_path', xmlSelect.value);
      }
      try {
        const res = await fetch('/deck/duplicate', { method: 'POST', body: body });
        const data = await res.json();
        if (data.error) {
          showDeckFeedback('Error: ' + data.error, true);
        } else {
          showDeckFeedback(data.message || ('Duplicación completada: ' + data.count + ' archivos creados.'), false);
          loadDeckData(xmlSelect.value);
        }
      } catch (err) {
        showDeckFeedback('Error de duplicación: ' + err.message, true);
      } finally {
        autoDuplicateBtn.disabled = false;
        autoDuplicateBtn.innerHTML = '<span>⚡</span> Duplicar cartas repetidas según lista';
      }
    });

    checkDeckBtn.addEventListener('click', function() {
      deckModal.classList.add('active');
      loadDeckData();
    });

    modalCloseBtn.addEventListener('click', function() {
      deckModal.classList.remove('active');
    });

    modalCloseFooterBtn.addEventListener('click', function() {
      deckModal.classList.remove('active');
    });

    xmlSelect.addEventListener('change', function() {
      loadDeckData(this.value);
    });

    xmlFileInput.addEventListener('change', function() {
      if (this.files.length) {
        loadDeckData(null, this.files[0]);
      }
    });

    xmlRefreshBtn.addEventListener('click', function() {
      loadDeckData(xmlSelect.value);
    });

    deckSearchInput.addEventListener('input', renderDeckTable);

    tabBtns.forEach(function(btn) {
      btn.addEventListener('click', function() {
        tabBtns.forEach(function(b) { b.classList.remove('active'); });
        this.classList.add('active');
        currentTab = this.getAttribute('data-tab');
        renderDeckTable();
      });
    });

    // Custom Card Backs (MDFC) Modal
    const openCustomBacksBtn = document.getElementById('open-custom-backs-btn');
    const customBacksBadge = document.getElementById('custom-backs-badge');
    const customBacksModal = document.getElementById('custom-backs-modal');
    const cbModalCloseBtn = document.getElementById('cb-modal-close-btn');
    const cbModalFooterCloseBtn = document.getElementById('cb-modal-footer-close-btn');
    const cbFeedback = document.getElementById('cb-feedback');
    const cbTableBody = document.getElementById('cb-table-body');
    const cbSearchInput = document.getElementById('cb-search-input');
    const cbFilterSelect = document.getElementById('cb-filter-select');
    const cbAutodetectBtn = document.getElementById('cb-autodetect-btn');
    const cbBulkAssignBtn = document.getElementById('cb-bulk-assign-btn');
    const cbBulkRemoveBtn = document.getElementById('cb-bulk-remove-btn');
    const cbSelectAll = document.getElementById('cb-select-all');
    const cbSingleUpload = document.getElementById('cb-single-upload');
    const cbBulkUpload = document.getElementById('cb-bulk-upload');
    const cbSelectedCount = document.getElementById('cb-selected-count');

    let currentCbData = null;
    let pendingUploadCardFiles = [];

    function showCbFeedback(msg, isError) {
      cbFeedback.style.display = 'block';
      cbFeedback.style.background = isError ? 'var(--danger-bg)' : 'var(--ok-bg)';
      cbFeedback.style.color = isError ? 'var(--danger)' : 'var(--ok)';
      cbFeedback.textContent = msg;
    }

    function hideCbFeedback() {
      cbFeedback.style.display = 'none';
    }

    function updateMainBadge(count) {
      if (count > 0) {
        customBacksBadge.style.display = 'inline-block';
        customBacksBadge.textContent = count + ' MDFC';
      } else {
        customBacksBadge.style.display = 'none';
      }
    }

    async function checkCustomBacksCount() {
      const exportDir = document.getElementById('export-dir').value.trim();
      if (!exportDir) {
        updateMainBadge(0);
        return;
      }
      try {
        const res = await fetch('/deck/custom_backs?export_dir=' + encodeURIComponent(exportDir));
        const data = await res.json();
        if (data.status === 'ok') {
          updateMainBadge(data.custom_count || 0);
        }
      } catch (e) {}
    }

    async function loadCustomBacksData() {
      const exportDir = document.getElementById('export-dir').value.trim();
      if (!exportDir) {
        showCbFeedback('Por favor introduce la ruta del directorio del mazo en "Export directory".', true);
        cbTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--danger); padding: 2em;">Falta la ruta en Export Directory.</td></tr>';
        return;
      }
      hideCbFeedback();
      cbTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--muted); padding: 2em;">Cargando cartas del mazo...</td></tr>';
      document.getElementById('cb-footer-dir').textContent = exportDir;

      try {
        const formData = new FormData();
        formData.append('action', 'inspect');
        formData.append('export_dir', exportDir);
        const res = await fetch('/deck/custom_backs', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.error) {
          showCbFeedback(data.error, true);
          cbTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--danger); padding: 2em;">' + data.error + '</td></tr>';
          return;
        }
        currentCbData = data;
        document.getElementById('cb-stat-total').textContent = data.total_cards || 0;
        document.getElementById('cb-stat-generic').textContent = data.generic_count || 0;
        document.getElementById('cb-stat-custom').textContent = data.custom_count || 0;
        document.getElementById('cb-stat-available').textContent = (data.available_backs || []).length;
        updateMainBadge(data.custom_count || 0);
        renderCustomBacksTable();
      } catch (err) {
        showCbFeedback('Error de conexión: ' + err.message, true);
        cbTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--danger); padding: 2em;">Error al conectar con el servidor.</td></tr>';
      }
    }

    function renderCustomBacksTable() {
      if (!currentCbData || !currentCbData.cards) return;
      const q = cbSearchInput.value.toLowerCase().trim();
      const filter = cbFilterSelect.value;
      const available = currentCbData.available_backs || [];

      cbTableBody.innerHTML = '';
      cbSelectAll.checked = false;
      updateSelectedCount();

      const filtered = currentCbData.cards.filter(function(c) {
        if (filter === 'custom' && !c.is_custom) return false;
        if (filter === 'generic' && c.is_custom) return false;
        if (q) {
          const matchName = (c.name || '').toLowerCase().includes(q);
          const matchFile = (c.filename || '').toLowerCase().includes(q);
          const matchBack = (c.custom_back_filename || '').toLowerCase().includes(q);
          if (!matchName && !matchFile && !matchBack) return false;
        }
        return true;
      });

      if (filtered.length === 0) {
        cbTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--muted); padding: 2em;">No hay cartas que coincidan con los filtros.</td></tr>';
        return;
      }

      filtered.forEach(function(c) {
        const tr = document.createElement('tr');
        const encodedFile = encodeURIComponent(c.filename);

        let backBadgeHtml = '';
        if (c.is_custom) {
          backBadgeHtml = '<span class="badge badge-custom" title="Ruta: ' + (c.custom_back || '') + '">📄 ' + (c.custom_back_filename || 'Custom PDF') + '</span>';
        } else {
          backBadgeHtml = '<span class="badge badge-generic">Genérico</span>';
          if (c.xml_paired_back) {
            backBadgeHtml += ' <span style="font-size: 0.75em; color: var(--info);" title="Detectado en XML: ' + c.xml_paired_back + '">💡 Sugerido: ' + c.xml_paired_back + '</span>';
          }
        }

        let selectHtml = '';
        if (available.length > 0) {
          selectHtml = '<select class="cb-select-back" data-file="' + encodedFile + '" style="max-width: 130px; font-size: 0.8em; padding: 2px 4px; border: 1px solid var(--border); border-radius: 3px; margin-left: 4px;">';
          selectHtml += '<option value="">-- de backs/ --</option>';
          available.forEach(function(b) {
            const bBase = b.replace(/^backs\\//, '');
            const isSel = (c.custom_back === b || c.custom_back === bBase) ? ' selected' : '';
            selectHtml += '<option value="' + encodeURIComponent(b) + '"' + isSel + '>' + bBase + '</option>';
          });
          selectHtml += '</select>';
        }

        let removeBtnHtml = '';
        if (c.is_custom) {
          removeBtnHtml = '<button type="button" class="btn-action-small cb-btn-remove" data-file="' + encodedFile + '" style="background: var(--danger); margin-left: 4px;" title="Restaurar al reverso genérico">✕</button>';
        }

        tr.innerHTML = '<td style="text-align: center;"><input type="checkbox" class="cb-card-check" data-file="' + encodedFile + '"></td>' +
          '<td style="color: #64748b; font-size: 0.85em;">' + c.index + '</td>' +
          '<td style="font-weight: 600; color: var(--fg);">' + c.name + '</td>' +
          '<td><code style="font-size: 0.8em; background: var(--table-head-bg); padding: 2px 4px; color: var(--fg); border-radius: 3px;">' + c.filename + '</code></td>' +
          '<td>' + backBadgeHtml + '</td>' +
          '<td style="text-align: right; white-space: nowrap;">' +
            '<button type="button" class="btn-action-small cb-btn-upload" data-file="' + encodedFile + '" style="background: var(--accent);">📎 Subir PDF</button>' +
            selectHtml +
            removeBtnHtml +
          '</td>';

        cbTableBody.appendChild(tr);
      });
    }

    function getSelectedCardFiles() {
      const checks = cbTableBody.querySelectorAll('.cb-card-check:checked');
      const files = [];
      checks.forEach(function(chk) {
        files.push(decodeURIComponent(chk.dataset.file));
      });
      return files;
    }

    function updateSelectedCount() {
      const sel = getSelectedCardFiles();
      cbSelectedCount.textContent = sel.length;
    }

    cbTableBody.addEventListener('change', function(e) {
      if (e.target.classList.contains('cb-card-check')) {
        updateSelectedCount();
      } else if (e.target.classList.contains('cb-select-back')) {
        const file = decodeURIComponent(e.target.dataset.file);
        const backVal = decodeURIComponent(e.target.value);
        if (backVal) {
          assignExistingCustomBack([file], backVal);
        }
      }
    });

    cbTableBody.addEventListener('click', function(e) {
      const btnUpload = e.target.closest('.cb-btn-upload');
      if (btnUpload) {
        const file = decodeURIComponent(btnUpload.dataset.file);
        pendingUploadCardFiles = [file];
        cbSingleUpload.value = '';
        cbSingleUpload.click();
        return;
      }
      const btnRemove = e.target.closest('.cb-btn-remove');
      if (btnRemove) {
        const file = decodeURIComponent(btnRemove.dataset.file);
        removeCustomBack([file]);
        return;
      }
    });

    cbSelectAll.addEventListener('change', function() {
      const checks = cbTableBody.querySelectorAll('.cb-card-check');
      const checked = this.checked;
      checks.forEach(function(c) { c.checked = checked; });
      updateSelectedCount();
    });

    cbBulkAssignBtn.addEventListener('click', function() {
      const selected = getSelectedCardFiles();
      if (selected.length === 0) {
        showCbFeedback('Por favor marca las casillas de las cartas a las que deseas asignar el reverso.', true);
        return;
      }
      pendingUploadCardFiles = selected;
      cbBulkUpload.value = '';
      cbBulkUpload.click();
    });

    cbBulkRemoveBtn.addEventListener('click', function() {
      const selected = getSelectedCardFiles();
      if (selected.length === 0) {
        showCbFeedback('Por favor selecciona al menos una carta para quitar su reverso custom.', true);
        return;
      }
      removeCustomBack(selected);
    });

    cbSingleUpload.addEventListener('change', function() {
      if (this.files && this.files[0] && pendingUploadCardFiles.length > 0) {
        uploadAndAssignCustomBack(pendingUploadCardFiles, this.files[0]);
      }
    });

    cbBulkUpload.addEventListener('change', function() {
      if (this.files && this.files[0] && pendingUploadCardFiles.length > 0) {
        uploadAndAssignCustomBack(pendingUploadCardFiles, this.files[0]);
      }
    });

    async function uploadAndAssignCustomBack(files, pdfFile) {
      const exportDir = document.getElementById('export-dir').value.trim();
      const formData = new FormData();
      formData.append('action', 'assign');
      formData.append('export_dir', exportDir);
      formData.append('card_filenames', JSON.stringify(files));
      formData.append('back_pdf', pdfFile);
      showCbFeedback('Subiendo y asignando PDF de reverso...', false);
      try {
        const res = await fetch('/deck/custom_backs', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.error) {
          showCbFeedback('Error: ' + data.error, true);
        } else {
          showCbFeedback(data.message || 'Reverso asignado exitosamente.', false);
          loadCustomBacksData();
        }
      } catch (err) {
        showCbFeedback('Error de conexión: ' + err.message, true);
      }
    }

    async function assignExistingCustomBack(files, backFilename) {
      const exportDir = document.getElementById('export-dir').value.trim();
      const formData = new FormData();
      formData.append('action', 'assign');
      formData.append('export_dir', exportDir);
      formData.append('card_filenames', JSON.stringify(files));
      formData.append('back_filename', backFilename);
      try {
        const res = await fetch('/deck/custom_backs', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.error) {
          showCbFeedback('Error: ' + data.error, true);
        } else {
          showCbFeedback(data.message || 'Reverso asignado exitosamente.', false);
          loadCustomBacksData();
        }
      } catch (err) {
        showCbFeedback('Error de conexión: ' + err.message, true);
      }
    }

    async function removeCustomBack(files) {
      const exportDir = document.getElementById('export-dir').value.trim();
      const formData = new FormData();
      formData.append('action', 'remove');
      formData.append('export_dir', exportDir);
      formData.append('card_filenames', JSON.stringify(files));
      try {
        const res = await fetch('/deck/custom_backs', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.error) {
          showCbFeedback('Error: ' + data.error, true);
        } else {
          showCbFeedback(data.message || 'Reverso restaurado a genérico.', false);
          loadCustomBacksData();
        }
      } catch (err) {
        showCbFeedback('Error de conexión: ' + err.message, true);
      }
    }

    cbAutodetectBtn.addEventListener('click', function() {
      const exportDir = document.getElementById('export-dir').value.trim();
      if (!exportDir) {
        showCbFeedback('Especifica "Export directory".', true);
        return;
      }
      const formData = new FormData();
      formData.append('action', 'auto_detect');
      formData.append('export_dir', exportDir);
      showCbFeedback('Buscando reversos en XML y carpeta backs/...', false);
      fetch('/deck/custom_backs', { method: 'POST', body: formData })
        .then(function(r) { return r.json(); })
        .then(function(data) {
          if (data.error) {
            showCbFeedback('Error: ' + data.error, true);
          } else {
            showCbFeedback(data.message || ('Auto-detección completada: ' + data.detected_count + ' reversos detectados.'), false);
            loadCustomBacksData();
          }
        })
        .catch(function(err) {
          showCbFeedback('Error de auto-detección: ' + err.message, true);
        });
    });

    openCustomBacksBtn.addEventListener('click', function() {
      customBacksModal.classList.add('active');
      loadCustomBacksData();
    });

    cbModalCloseBtn.addEventListener('click', function() {
      customBacksModal.classList.remove('active');
    });

    cbModalFooterCloseBtn.addEventListener('click', function() {
      customBacksModal.classList.remove('active');
    });

    customBacksModal.addEventListener('click', function(e) {
      if (e.target === customBacksModal) {
        customBacksModal.classList.remove('active');
      }
    });

    cbSearchInput.addEventListener('input', renderCustomBacksTable);
    cbFilterSelect.addEventListener('change', renderCustomBacksTable);

    // Initial check of custom backs badge
    checkCustomBacksCount();
    document.getElementById('export-dir').addEventListener('change', checkCustomBacksCount);
  </script>
</body>
</html>
"""
FORM_TEMPLATE = string.Template(FORM_HTML)


def mm_to_px(mm, dpi):
    return int(round(mm / MM_TO_INCH * dpi))


def parse_bool(value):
    return value in ("true", "True", "1", "on")


def parse_hex(color):
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("color must be #RRGGBB")
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)
    return (r, g, b)


def pt_to_px(pt, dpi):
    return max(1, int(round(pt / 72.0 * dpi)))


def collect_front_pdfs(export_dir):
    for source_dir in (
        os.path.join(export_dir, "fronts"),
        os.path.join(export_dir, "pdfs"),
        export_dir,
    ):
        if not os.path.isdir(source_dir):
            continue
        pdfs = sorted(
            os.path.join(source_dir, f)
            for f in os.listdir(source_dir)
            if f.lower().endswith(".pdf") and "back" not in f.lower()
        )
        if pdfs:
            return pdfs
    if os.path.isdir(export_dir):
        pdfs = sorted(
            os.path.join(export_dir, f)
            for f in os.listdir(export_dir)
            if f.lower().endswith(".pdf")
        )
        if pdfs:
            return pdfs
    raise ValueError(f"no front PDFs found in {export_dir}")


def collect_back_pdfs(export_dir):
    backs_dir = os.path.join(export_dir, "backs")
    if os.path.isdir(backs_dir):
        pdfs = sorted(
            os.path.join(backs_dir, f)
            for f in os.listdir(backs_dir)
            if f.lower().endswith(".pdf")
        )
        if pdfs:
            return pdfs

    for root, _, files in os.walk(export_dir):
        backs = sorted(
            os.path.join(root, f)
            for f in files
            if f.lower().endswith(".pdf") and "back" in f.lower()
        )
        if backs:
            return backs

    return []


def collect_pdfs(export_dir, face):
    if face == "backs":
        backs = collect_back_pdfs(export_dir)
        if backs:
            return backs
        raise ValueError(f"no back PDFs found in {export_dir}")
    return collect_front_pdfs(export_dir)


def load_custom_backs(export_dir):
    if not export_dir or not os.path.isdir(export_dir):
        return {}
    cb_path = os.path.join(export_dir, "custom_backs.json")
    if os.path.isfile(cb_path):
        try:
            with open(cb_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def save_custom_backs(export_dir, mapping):
    if not export_dir or not os.path.isdir(export_dir):
        return False
    cb_path = os.path.join(export_dir, "custom_backs.json")
    try:
        with open(cb_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def find_generic_back_pdf(export_dir):
    if not export_dir or not os.path.isdir(export_dir):
        return None
    backs_dir = os.path.join(export_dir, "backs")
    search_dirs = [backs_dir, export_dir] if os.path.isdir(backs_dir) else [export_dir]
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for cand in ["card_back.pdf", "back.pdf", "cardback.pdf", "generic_back.pdf", "reverso.pdf"]:
            p = os.path.join(d, cand)
            if os.path.isfile(p):
                return p
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".pdf") and "back" in f.lower() and not f.lower().startswith(("sheet", "deckgen_")):
                return os.path.join(d, f)
    if os.path.isdir(backs_dir):
        pdfs = sorted([
            os.path.join(backs_dir, f)
            for f in os.listdir(backs_dir)
            if f.lower().endswith(".pdf") and not f.lower().startswith(("sheet", "deckgen_"))
        ])
        if pdfs:
            return pdfs[0]
    return None


def render_pdf_to_png(pdf_path, dpi, tmp_dir):
    target_w = mm_to_px(CARD_W_MM, dpi)
    target_h = mm_to_px(CARD_H_MM, dpi)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    safe_base = re.sub(r"[^a-zA-Z0-9_\-]", "_", base)
    out_prefix = os.path.join(tmp_dir, f"{safe_base}_{dpi}")
    cmd = [
        "pdftoppm",
        "-png",
        "-scale-to-x",
        str(target_w),
        "-scale-to-y",
        str(target_h),
        "-singlefile",
        pdf_path,
        out_prefix,
    ]
    subprocess.run(cmd, check=True)
    out_path = out_prefix + ".png"
    if not os.path.exists(out_path):
        raise RuntimeError(f"pdftoppm did not produce {out_path}")
    img = Image.open(out_path).convert("RGB")
    if img.size != (target_w, target_h):
        img = img.resize((target_w, target_h), Image.LANCZOS)
    return img


def compute_grid(paper_w_mm, paper_h_mm, card_spacing=0.0):
    cols = int((paper_w_mm + card_spacing) // (CARD_W_MM + card_spacing))
    rows = int((paper_h_mm + card_spacing) // (CARD_H_MM + card_spacing))
    if cols < 1 or rows < 1:
        raise ValueError("paper size too small for one card")
    return cols, rows


def _sheet_geometry(paper, landscape, dpi, card_spacing=0.0):
    paper_w_mm, paper_h_mm = PAPER_SIZES[paper]
    if landscape:
        paper_w_mm, paper_h_mm = paper_h_mm, paper_w_mm
    cols, rows = compute_grid(paper_w_mm, paper_h_mm, card_spacing)
    paper_px = (mm_to_px(paper_w_mm, dpi), mm_to_px(paper_h_mm, dpi))
    card_px = (mm_to_px(CARD_W_MM, dpi), mm_to_px(CARD_H_MM, dpi))
    gap_px = mm_to_px(card_spacing, dpi)
    grid_w = cols * card_px[0] + (cols - 1) * gap_px
    grid_h = rows * card_px[1] + (rows - 1) * gap_px
    margin_x = max(0, (paper_px[0] - grid_w) // 2)
    margin_y = max(0, (paper_px[1] - grid_h) // 2)
    return cols, rows, paper_px, card_px, margin_x, margin_y, gap_px


def generate_base_sheets(images, paper, landscape, dpi, card_spacing=0.0, is_back=False, duplex_flip=True):
    cols, rows, paper_px, card_px, margin_x, margin_y, gap_px = _sheet_geometry(
        paper, landscape, dpi, card_spacing
    )
    pitch_x = card_px[0] + gap_px
    pitch_y = card_px[1] + gap_px
    cards_per_sheet = cols * rows
    sheets = []
    for sheet_idx in range(0, len(images), cards_per_sheet):
        canvas = Image.new("RGB", paper_px, (255, 255, 255))
        for idx, image in enumerate(images[sheet_idx : sheet_idx + cards_per_sheet]):
            row = idx // cols
            col = (cols - 1 - (idx % cols)) if (is_back and duplex_flip) else (idx % cols)
            x = margin_x + col * pitch_x
            y = margin_y + row * pitch_y
            img_to_paste = (
                image.resize(card_px, Image.LANCZOS)
                if image.size != card_px
                else image
            )
            canvas.paste(img_to_paste, (x, y))
        sheets.append(canvas)
    return sheets


def _draw_cut_lines_on_canvas(
    canvas, paper, landscape, dpi, cut, color, thickness, mark_len, card_spacing=0.0
):
    cols, rows, paper_px, card_px, margin_x, margin_y, gap_px = _sheet_geometry(
        paper, landscape, dpi, card_spacing
    )
    if cut == "none":
        return canvas
    draw = ImageDraw.Draw(canvas)
    mark_px = mm_to_px(mark_len, dpi)
    line_width = pt_to_px(thickness, dpi)
    line_color = parse_hex(color)
    draw_cut_lines(
        draw,
        margin_x,
        margin_y,
        cols,
        rows,
        card_px,
        gap_px,
        paper_px,
        mark_px,
        line_width,
        line_color,
        cut == "corners",
    )
    return canvas


def generate_sheets(
    images, paper, landscape, dpi, cut, color, thickness, mark_len, card_spacing=0.0, is_back=False, duplex_flip=True
):
    sheets = generate_base_sheets(images, paper, landscape, dpi, card_spacing, is_back=is_back, duplex_flip=duplex_flip)
    for canvas in sheets:
        _draw_cut_lines_on_canvas(
            canvas, paper, landscape, dpi, cut, color, thickness, mark_len, card_spacing
        )
    return sheets


def draw_cut_lines(
    draw,
    margin_x,
    margin_y,
    cols,
    rows,
    card_px,
    gap_px,
    paper_px,
    mark_px,
    line_width,
    color,
    corners_only,
):
    pitch_x = card_px[0] + gap_px
    pitch_y = card_px[1] + gap_px
    grid_w = cols * card_px[0] + (cols - 1) * gap_px
    grid_h = rows * card_px[1] + (rows - 1) * gap_px
    right = margin_x + grid_w
    bottom = margin_y + grid_h

    def draw_segment(x1, y1, x2, y2):
        draw.line([(x1, y1), (x2, y2)], fill=color, width=line_width)

    xs = set()
    for c in range(cols):
        xs.add(margin_x + c * pitch_x)
        xs.add(margin_x + c * pitch_x + card_px[0])
    xs = sorted(xs)

    ys = set()
    for r in range(rows):
        ys.add(margin_y + r * pitch_y)
        ys.add(margin_y + r * pitch_y + card_px[1])
    ys = sorted(ys)

    if corners_only:
        for x in xs:
            for y in ys:
                if y == margin_y:
                    draw_segment(x, y, x, min(y + mark_px, bottom))
                elif y == bottom:
                    draw_segment(x, max(y - mark_px, margin_y), x, y)
                else:
                    draw_segment(
                        x,
                        max(y - mark_px // 2, margin_y),
                        x,
                        min(y + mark_px // 2, bottom),
                    )

                if x == margin_x:
                    draw_segment(x, y, min(x + mark_px, right), y)
                elif x == right:
                    draw_segment(max(x - mark_px, margin_x), y, x, y)
                else:
                    draw_segment(
                        max(x - mark_px // 2, margin_x),
                        y,
                        min(x + mark_px // 2, right),
                        y,
                    )
    else:
        for x in xs:
            draw_segment(x, margin_y, x, bottom)
        for y in ys:
            draw_segment(margin_x, y, right, y)


def _uploaded_dir_name(files):
    for file_info in files:
        rel_path = file_info["filename"].replace("\\", "/")
        rel_path = os.path.normpath(rel_path).lstrip("/")
        if os.sep in rel_path:
            return rel_path.split(os.sep)[0]
    return "export"


def _first_sheet_hash(pdfs):
    hasher = hashlib.sha256()
    for pdf in pdfs:
        hasher.update(os.path.basename(pdf).encode())
        with open(pdf, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
    return hasher.hexdigest()


def _preview_cache_key(source_name, face, paper, landscape, card_spacing, pdfs, duplex_flip=True):
    content_hash = _first_sheet_hash(pdfs)
    raw = (
        f"{CARD_W_MM}\x00{CARD_H_MM}\x00{source_name}\x00{face}\x00{paper}\x00{landscape}\x00"
        f"{card_spacing}\x00{duplex_flip}\x00{content_hash}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _preview_cache_path(cache_key):
    return os.path.join(PREVIEW_CACHE_DIR, f"deckgen_preview_{cache_key}.png")


def build_pdf(sheets, tmp_dir):
    out_path = os.path.join(tmp_dir, "sheets.pdf")
    first = sheets[0]
    rest = sheets[1:]
    first.save(out_path, format="PDF", save_all=True, append_images=rest, resolution=float(DPI))
    return out_path


def image_to_standard_pdf(image_bytes, dest_path):
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    card = ImageOps.fit(
        image, (STANDARD_CARD_W_PX, STANDARD_CARD_H_PX), method=Image.LANCZOS
    )
    card.save(dest_path, format="PDF", resolution=DPI)


def _build_pdf_bytes(sheets):
    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = build_pdf(sheets, tmp_dir)
        with open(pdf_path, "rb") as f:
            return f.read()


def save_uploaded_export(files, export_dir):
    saved = 0
    for file_info in files:
        rel_path = file_info["filename"].replace("\\", "/")
        rel_path = os.path.normpath(rel_path).lstrip("/")
        if not rel_path or rel_path.startswith(".."):
            continue
        dest_path = os.path.join(export_dir, rel_path)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(file_info["body"])
        saved += 1
    return saved


def resolve_export_dir(root):
    faces = ("fronts", "backs", "pdfs")

    def has_direct_pdfs(path):
        return any(f.lower().endswith(".pdf") for f in os.listdir(path))

    def is_valid_export(path):
        if not os.path.isdir(path):
            return False
        if any(os.path.isdir(os.path.join(path, face)) for face in faces):
            return True
        return has_direct_pdfs(path)

    candidates = []
    if is_valid_export(root):
        candidates.append((root, 0, has_direct_pdfs(root)))
    for entry in os.listdir(root):
        entry_path = os.path.join(root, entry)
        if is_valid_export(entry_path):
            depth = len(os.path.relpath(entry_path, root).split(os.sep))
            candidates.append((entry_path, depth, has_direct_pdfs(entry_path)))

    if not candidates:
        raise ValueError("no PDFs found in uploaded directory")

    if len(candidates) == 1:
        return candidates[0][0]

    max_depth = max(c[1] for c in candidates)
    deepest = [c for c in candidates if c[1] == max_depth]
    pdf_deepest = [c for c in deepest if c[2]]
    if pdf_deepest:
        return pdf_deepest[0][0]
    return deepest[0][0]


def parse_and_build_sheets(handler, preview=False, progress_callback=None, source_files=None):
    try:
        face = handler.get_body_argument("face")
        paper = handler.get_body_argument("paper")
        landscape = parse_bool(handler.get_body_argument("landscape", "false"))
        cut = handler.get_body_argument("cut")
        color = handler.get_body_argument("color")
        thickness = float(handler.get_body_argument("thickness"))
        mark_len = float(handler.get_body_argument("mark_len"))
        card_spacing = float(handler.get_body_argument("card_spacing", "0"))
    except (ValueError, tornado.web.MissingArgumentError) as exc:
        return None, f"invalid form input: {exc}"

    if source_files is None:
        files = handler.request.files.get("files", [])
        source_files = handler.request.files.get("source_files", [])
        if not source_files:
            source_files = files

    back_files = handler.request.files.get("back_file", [])
    export_dir_param = handler.get_body_argument("export_dir", "").strip()

    if not source_files and not (export_dir_param and os.path.isdir(export_dir_param)) and not (face == "backs" and back_files):
        return None, "no source directory uploaded or valid export directory specified"

    if face not in ("fronts", "backs"):
        return None, "invalid face"

    if paper not in PAPER_SIZES:
        return None, "invalid paper"

    if cut not in ("none", "full", "corners"):
        return None, "invalid cut mode"

    dpi = PREVIEW_DPI if preview else DPI

    source_uploads = source_files
    source_name = _uploaded_dir_name(source_uploads) if source_uploads else (os.path.basename(export_dir_param) if export_dir_param else "back_only")

    with tempfile.TemporaryDirectory() as source_dir:
        real_source_dir = None
        if source_uploads:
            saved = save_uploaded_export(source_uploads, source_dir)
            if saved > 0:
                try:
                    real_source_dir = resolve_export_dir(source_dir)
                except ValueError:
                    real_source_dir = source_dir
        elif export_dir_param and os.path.isdir(export_dir_param):
            real_source_dir = export_dir_param

        # Conteo de cartas fronts para saber cuántos backs se requieren en generación completa
        front_count = None
        if real_source_dir:
            try:
                front_count = len(collect_front_pdfs(real_source_dir))
            except ValueError:
                pass

        paper_w_mm, paper_h_mm = PAPER_SIZES[paper]
        if landscape:
            paper_w_mm, paper_h_mm = paper_h_mm, paper_w_mm
        cols, rows = compute_grid(paper_w_mm, paper_h_mm, card_spacing)
        sheet_capacity = cols * rows

        duplex_flip = handler.get_body_argument("duplex_flip", "true").lower() in ("true", "1", "on", "yes")

        front_pdfs = []
        if real_source_dir:
            try:
                front_pdfs = collect_front_pdfs(real_source_dir)
            except ValueError:
                pass
        if not front_pdfs and export_dir_param and os.path.isdir(export_dir_param):
            try:
                front_pdfs = collect_front_pdfs(export_dir_param)
            except ValueError:
                pass

        if face == "fronts":
            if not front_pdfs:
                return None, "no source files uploaded for fronts"
            pdfs = front_pdfs
        else:
            # face == "backs"
            back_pdf_path = None
            if back_files:
                bf = back_files[0]
                fname = bf.get("filename", "").lower()
                body = bf.get("body", b"")
                if fname.endswith((".png", ".jpg", ".jpeg")):
                    back_pdf_path = os.path.join(source_dir, "uploaded_back.pdf")
                    image_to_standard_pdf(body, back_pdf_path)
                else:
                    back_pdf_path = os.path.join(source_dir, "uploaded_back.pdf")
                    with open(back_pdf_path, "wb") as f:
                        f.write(body)

            if not back_pdf_path and real_source_dir:
                back_pdf_path = find_generic_back_pdf(real_source_dir)

            if not back_pdf_path and export_dir_param and os.path.isdir(export_dir_param):
                back_pdf_path = find_generic_back_pdf(export_dir_param)

            effective_dir = export_dir_param if (export_dir_param and os.path.isdir(export_dir_param)) else real_source_dir
            custom_map = load_custom_backs(effective_dir)

            if front_pdfs:
                pdfs = []
                for f in front_pdfs:
                    f_base = os.path.basename(f)
                    cback = custom_map.get(f_base)
                    if not cback:
                        clean_stem = os.path.splitext(f_base)[0]
                        cback = custom_map.get(clean_stem)

                    assigned_path = None
                    if cback:
                        if os.path.isabs(cback) and os.path.isfile(cback):
                            assigned_path = cback
                        elif effective_dir:
                            cand = os.path.join(effective_dir, cback)
                            if os.path.isfile(cand):
                                assigned_path = cand
                            else:
                                cand2 = os.path.join(effective_dir, "backs", cback)
                                if os.path.isfile(cand2):
                                    assigned_path = cand2

                    if assigned_path:
                        pdfs.append(assigned_path)
                    elif back_pdf_path:
                        pdfs.append(back_pdf_path)
                    else:
                        pdfs.append(None)

                if any(p is None for p in pdfs):
                    if not back_pdf_path:
                        return (
                            None,
                            "No se encontró el back genérico de las cartas ni reverso para algunas cartas. Por favor selecciona el archivo en el campo 'Card back'.",
                        )
            elif back_pdf_path:
                needed = sheet_capacity
                pdfs = [back_pdf_path] * needed
            else:
                return (
                    None,
                    "No se encontró el back de las cartas. Por favor selecciona el archivo en el campo 'Card back'.",
                )

        if preview:
            pdfs = pdfs[:sheet_capacity]
            cache_key = _preview_cache_key(
                source_name, face, paper, landscape, card_spacing, pdfs, duplex_flip=duplex_flip
            )
            cache_path = _preview_cache_path(cache_key)
            if os.path.exists(cache_path):
                base = Image.open(cache_path).convert("RGB")
                canvas = base.copy()
                _draw_cut_lines_on_canvas(
                    canvas, paper, landscape, dpi, cut, color, thickness, mark_len, card_spacing
                )
                return [canvas], None

        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                images = []
                rendered_cache = {}
                for idx, pdf in enumerate(pdfs):
                    if pdf not in rendered_cache:
                        rendered_cache[pdf] = render_pdf_to_png(pdf, dpi, tmp_dir)
                    images.append(rendered_cache[pdf])
                    if progress_callback:
                        progress_callback(idx + 1, len(pdfs))
                if preview:
                    base_sheets = generate_base_sheets(
                        images, paper, landscape, dpi, card_spacing, is_back=(face == "backs"), duplex_flip=duplex_flip
                    )
                    base = base_sheets[0]
                    os.makedirs(PREVIEW_CACHE_DIR, exist_ok=True)
                    base.save(cache_path, format="PNG")
                    canvas = base.copy()
                    _draw_cut_lines_on_canvas(
                        canvas, paper, landscape, dpi, cut, color, thickness, mark_len, card_spacing
                    )
                    return [canvas], None
                sheets = generate_sheets(
                    images, paper, landscape, dpi, cut, color, thickness, mark_len, card_spacing, is_back=(face == "backs"), duplex_flip=duplex_flip
                )
            except (subprocess.CalledProcessError, ValueError, RuntimeError, OSError) as exc:
                return None, str(exc)

    return sheets, None


class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        defaults = {
            "export_dir": self.get_argument("export_dir", ""),
            "face": self.get_argument("face", "fronts"),
            "paper": self.get_argument("paper", "a3"),
            "landscape": self.get_argument("landscape", "false"),
            "card_spacing": self.get_argument("card_spacing", "0"),
            "cut": self.get_argument("cut", "none"),
            "color": self.get_argument("color", "#000000"),
            "thickness": self.get_argument("thickness", "0.5"),
            "mark_len": self.get_argument("mark_len", "5"),
            "duplex_flip": self.get_argument("duplex_flip", "true"),
            "error": "",
        }
        error = self.get_argument("error", "")
        if error:
            defaults["error"] = f'<p class="error">{tornado.escape.xhtml_escape(error)}</p>'
        defaults["face_fronts_selected"] = "selected" if defaults["face"] == "fronts" else ""
        defaults["face_backs_selected"] = "selected" if defaults["face"] == "backs" else ""
        defaults["paper_a3_selected"] = "selected" if defaults["paper"] == "a3" else ""
        defaults["paper_a4_selected"] = "selected" if defaults["paper"] == "a4" else ""
        defaults["paper_a4_3_selected"] = "selected" if defaults["paper"] == "a4-3" else ""
        defaults["landscape_checked"] = "checked" if parse_bool(defaults["landscape"]) else ""
        defaults["duplex_flip_checked"] = "checked" if parse_bool(defaults["duplex_flip"]) else ""
        defaults["cut_none_selected"] = "selected" if defaults["cut"] == "none" else ""
        defaults["cut_full_selected"] = "selected" if defaults["cut"] == "full" else ""
        defaults["cut_corners_selected"] = "selected" if defaults["cut"] == "corners" else ""
        self.write(FORM_TEMPLATE.safe_substitute(defaults))


class GenerateHandler(tornado.web.RequestHandler):
    async def post(self):
        _set_progress(0, "starting", False)
        try:
            face = self.get_body_argument("face")
            paper = self.get_body_argument("paper")
            source_files = self.request.files.get("source_files", [])
            export_dir = self.get_body_argument("export_dir", "").strip()
            if not os.path.isdir(export_dir):
                _set_progress(0, "error: missing export directory", True)
                self.set_status(400)
                self.set_header("Content-Type", "application/json")
                self.write(json.dumps({"error": f"export directory not found: {export_dir}"}))
                return

            loop = tornado.ioloop.IOLoop.current()
            sheets, error = await loop.run_in_executor(
                None, parse_and_build_sheets, self, False, _progress_callback, source_files or None
            )
            if error:
                _set_progress(0, f"error: {error}", True)
                self.set_status(400)
                self.set_header("Content-Type", "application/json")
                self.write(json.dumps({"error": error}))
                return

            _set_progress(95, "saving PDF", False)
            dest_dir = export_dir

            def save_pdf():
                built_path = build_pdf(sheets, dest_dir)
                pdf_name = f"deckgen_{face}_{paper}.pdf"
                final_path = os.path.join(dest_dir, pdf_name)
                os.rename(built_path, final_path)
                return final_path

            pdf_path = await loop.run_in_executor(None, save_pdf)
            _set_progress(100, "done", True)
            download_url = f"/download?path={tornado.escape.url_escape(pdf_path)}"
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"path": pdf_path, "download_url": download_url}))
        except Exception as exc:
            _set_progress(0, f"error: {exc}", True)
            raise


class DownloadHandler(tornado.web.RequestHandler):
    def get(self):
        path = self.get_argument("path", "")
        if not path or not os.path.isfile(path):
            self.set_status(404)
            self.set_header("Content-Type", "text/plain; charset=utf-8")
            self.write("file not found")
            return
        self.set_header("Content-Type", "application/pdf")
        self.set_header(
            "Content-Disposition",
            f'attachment; filename="{os.path.basename(path)}"',
        )
        with open(path, "rb") as f:
            self.write(f.read())


class ProgressHandler(tornado.web.RequestHandler):
    def get(self):
        with _progress_lock:
            self.write(progress_state)


class PreviewHandler(tornado.web.RequestHandler):
    def post(self):
        sheets, error = parse_and_build_sheets(self, preview=True)
        if error:
            logging.error("preview error: %s", error)
            self.set_status(400)
            self.set_header("Content-Type", "text/plain; charset=utf-8")
            self.write(error)
            return

        buf = io.BytesIO()
        sheets[0].save(buf, format="PNG")
        buf.seek(0)
        self.set_header("Content-Type", "image/png")
        self.write(buf.read())


class ConvertImagesHandler(tornado.web.RequestHandler):
    def post(self):
        images = self.request.files.get("images", [])
        export_dir = self.get_body_argument("export_dir", "").strip()
        if not os.path.isdir(export_dir):
            self.set_status(400)
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"error": f"export directory not found: {export_dir}"}))
            return
        pdfs_dir = os.path.join(export_dir, "pdfs")
        os.makedirs(pdfs_dir, exist_ok=True)
        for idx, file_info in enumerate(images):
            stem = os.path.splitext(os.path.basename(file_info["filename"]))[0]
            name = stem or f"image_{idx:03d}"
            image_to_standard_pdf(file_info["body"], os.path.join(pdfs_dir, f"{name}.pdf"))
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"path": pdfs_dir, "count": len(images)}))


class ClearCacheHandler(tornado.web.RequestHandler):
    def post(self):
        cleared_count = 0
        if os.path.exists(PREVIEW_CACHE_DIR):
            for f in os.listdir(PREVIEW_CACHE_DIR):
                if f.startswith("deckgen_preview_"):
                    try:
                        os.remove(os.path.join(PREVIEW_CACHE_DIR, f))
                        cleared_count += 1
                    except OSError:
                        pass
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"status": "ok", "cleared": cleared_count}))


def normalize_card_text(text):
    if not text:
        return ""
    t = os.path.splitext(text)[0].lower()
    t = re.sub(r"\(copia \d+\)", "", t)
    t = re.sub(r"\([a-zA-Z0-9_\-]{20,}\)", "", t)
    t = re.sub(r"\[.*?\]|\{.*?\}", "", t)
    return re.sub(r"[^a-z0-9]", "", t)


def find_deck_files(export_dir):
    deck_files = []
    if export_dir and os.path.isdir(export_dir):
        for root, _, files in os.walk(export_dir):
            for f in files:
                f_lower = f.lower()
                if f_lower.endswith(".xml") or (f_lower.endswith(".txt") and "requirements" not in f_lower):
                    deck_files.append(os.path.join(root, f))
    def sort_key(p):
        rel = os.path.relpath(p, export_dir)
        depth = len(rel.split(os.sep))
        base = os.path.basename(p).lower()
        is_txt = base.endswith(".txt")
        is_cards = "cards.xml" in base
        score = 0 if (depth == 1 and (is_txt or is_cards)) else (1 if is_txt else 2)
        return (depth, score, rel)
    return sorted(deck_files, key=sort_key)


def find_deck_xmls(export_dir):
    return find_deck_files(export_dir)


def parse_mtgo_txt(content):
    cards = []
    lines = content.splitlines() if isinstance(content, str) else content.decode("utf-8", errors="replace").splitlines()
    slot_idx = 0
    in_sideboard = False
    sideboard_cards = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        lower_line = line.lower()
        if lower_line.startswith(("sideboard", "// sideboard", "# sideboard")):
            in_sideboard = True
            continue
        if lower_line.startswith(("//", "#")):
            continue
        m = re.match(r"^(\d+)\s*[xX]?\s+(.+)$", line)
        if not m:
            continue
        qty = int(m.group(1))
        raw = m.group(2).strip()
        name = re.sub(r"\s*\*F\*\s*$", "", raw, flags=re.IGNORECASE)
        name = re.sub(r"\s*\{[A-Za-z0-9_]+\}\s*$", "", name)
        name = re.sub(r"\s*\([A-Za-z0-9_]{3,5}\)\s*[A-Za-z0-9_{}-]*$", "", name)
        name = re.sub(r"\s*\[[A-Za-z0-9_]{3,5}\]\s*[A-Za-z0-9_{}-]*$", "", name)
        name = name.strip()
        slots = list(range(slot_idx, slot_idx + qty))
        slot_idx += qty
        entry = {
            "id": "",
            "name": name,
            "query": name.lower(),
            "slots": slots,
            "required_count": qty,
        }
        if in_sideboard:
            sideboard_cards.append(entry)
        else:
            cards.append(entry)

    total_quantity = sum(c["required_count"] for c in cards)
    return total_quantity, cards, sideboard_cards


def inspect_deck_file(export_dir, deck_path=None, file_content=None):
    if not export_dir or not os.path.isdir(export_dir):
        return {"error": f"El directorio '{export_dir}' no existe o no es válido."}

    available_files = find_deck_files(export_dir)
    chosen_file = deck_path if (deck_path and os.path.isfile(deck_path)) else (available_files[0] if available_files else None)

    is_txt = False
    raw_text = None
    if file_content:
        raw_text = file_content if isinstance(file_content, str) else file_content.decode("utf-8", errors="replace")
        if not raw_text.strip().startswith("<"):
            is_txt = True
    elif chosen_file:
        if chosen_file.lower().endswith(".txt"):
            is_txt = True
            with open(chosen_file, "r", encoding="utf-8", errors="replace") as f:
                raw_text = f.read()

    cards_data = []
    if is_txt:
        quantity, all_cards, _ = parse_mtgo_txt(raw_text)
        display_path = chosen_file or "TXT subido"
    elif file_content or chosen_file:
        try:
            if file_content:
                root = ET.fromstring(file_content)
                display_path = "XML subido"
            else:
                tree = ET.parse(chosen_file)
                root = tree.getroot()
                display_path = chosen_file
            try:
                quantity = int(root.findtext("details/quantity", "100"))
            except ValueError:
                quantity = 100
            all_cards = []
            for c in root.findall("fronts/card"):
                cid = c.findtext("id", "").strip()
                cname = c.findtext("name", "").strip()
                cquery = c.findtext("query", "").strip()
                slots_str = c.findtext("slots", "").strip()
                slots = [int(s) for s in slots_str.split(",") if s.strip()]
                all_cards.append({
                    "id": cid,
                    "name": cname,
                    "query": cquery,
                    "slots": slots,
                    "required_count": len(slots),
                })
        except Exception as e:
            return {"error": f"Error al leer archivo de mazo: {e}"}
    else:
        return {"error": "No se encontró ningún archivo de mazo (.xml o .txt) en el directorio.", "available_files": [], "available_xmls": []}

    pdf_dir = os.path.join(export_dir, "pdfs")
    target_dir = pdf_dir if os.path.isdir(pdf_dir) else export_dir
    files_on_disk = [
        f for f in sorted(os.listdir(target_dir))
        if f.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")) and not f.lower().startswith("sheet") and "back" not in f.lower()
    ]

    matched_files = set()
    all_slots = set()

    for c in all_cards:
        cid = c.get("id", "")
        cname = c.get("name", "")
        cquery = c.get("query", "")
        slots = c.get("slots", [])
        all_slots.update(slots)

        matches = []
        for f in files_on_disk:
            f_norm = normalize_card_text(f)
            if cid and cid in f:
                matches.append(f)
                continue
            m = re.match(r"^\(([^)]+)\)\s*\(([^)]+)\)", f)
            if m:
                orig = normalize_card_text(m.group(1))
                if orig and (orig == normalize_card_text(cquery) or orig == normalize_card_text(cname)):
                    matches.append(f)
                    continue
            q_norm = normalize_card_text(cquery)
            n_norm = normalize_card_text(cname)
            if q_norm and (q_norm == f_norm or q_norm in f_norm or f_norm in q_norm):
                matches.append(f)
                continue
            if n_norm and (n_norm == f_norm or n_norm in f_norm or f_norm in n_norm):
                matches.append(f)
                continue
            words = [w for w in re.findall(r"[a-z0-9]+", (cquery or cname).lower()) if len(w) > 3]
            if words and all(w in f.lower() for w in words):
                matches.append(f)
                continue

        unique_matches = []
        for m in matches:
            if m not in unique_matches:
                unique_matches.append(m)

        for m in unique_matches:
            matched_files.add(m)

        required = c["required_count"]
        found_count = len(unique_matches)
        if found_count == 0:
            status = "missing"
        elif found_count < required:
            status = "needs_copies"
        else:
            status = "ok"

        cards_data.append({
            "id": cid,
            "name": cname,
            "query": cquery,
            "slots": slots,
            "required_count": required,
            "existing_copies": found_count,
            "status": status,
            "matched_file": unique_matches[0] if unique_matches else None,
            "all_matched_files": unique_matches,
        })

    extra_files = [f for f in sorted(files_on_disk) if f not in matched_files]
    missing_slots = sorted(set(range(quantity)) - all_slots) if quantity else []

    return {
        "deck_file_path": display_path,
        "xml_path": display_path,
        "format": "txt" if is_txt else "xml",
        "available_files": available_files,
        "available_xmls": available_files,
        "target_dir": target_dir,
        "quantity": quantity,
        "total_slots": len(all_slots),
        "total_cards": len(cards_data),
        "total_cards_xml": len(cards_data),
        "total_files_disk": len(files_on_disk),
        "missing_slots": missing_slots,
        "cards": cards_data,
        "extra_files": extra_files,
    }


def inspect_deck_xml(export_dir, xml_path=None, xml_content=None):
    return inspect_deck_file(export_dir, xml_path, xml_content)


def duplicate_deck_cards(export_dir, target_file=None, count=1, auto_deck=False, deck_path=None, file_content=None, auto_xml=False, xml_path=None, xml_content=None):
    if not export_dir or not os.path.isdir(export_dir):
        return {"error": f"Directorio no encontrado: {export_dir}", "created": []}

    pdf_dir = os.path.join(export_dir, "pdfs")
    target_dir = pdf_dir if os.path.isdir(pdf_dir) else export_dir
    images_dir = os.path.join(export_dir, "images")
    has_images = os.path.isdir(images_dir)

    effective_auto = auto_deck or auto_xml
    effective_path = deck_path or xml_path
    effective_content = file_content or xml_content

    created = []

    def copy_file_variant(src_path, num_copies):
        new_files = []
        d = os.path.dirname(src_path)
        base = os.path.basename(src_path)
        stem, ext = os.path.splitext(base)
        clean_stem = re.sub(r"\s*\(copia \d+\)$", "", stem)
        n = 2
        for _ in range(num_copies):
            while True:
                cand = os.path.join(d, f"{clean_stem} (copia {n}){ext}")
                if not os.path.exists(cand):
                    break
                n += 1
            shutil.copy2(src_path, cand)
            new_files.append(cand)
            n += 1
        return new_files

    if effective_auto:
        inspection = inspect_deck_file(export_dir, effective_path, effective_content)
        if "error" in inspection:
            return {"error": inspection["error"], "created": []}
        for card in inspection["cards"]:
            if card["status"] == "needs_copies" and card["matched_file"]:
                src_path = os.path.join(target_dir, card["matched_file"])
                if os.path.exists(src_path):
                    missing = card["required_count"] - card["existing_copies"]
                    if missing > 0:
                        new_files = copy_file_variant(src_path, missing)
                        created.extend(new_files)
                        if has_images:
                            stem = os.path.splitext(card["matched_file"])[0]
                            clean_stem = re.sub(r"\s*\(copia \d+\)$", "", stem)
                            for img_ext in (".png", ".jpg", ".jpeg"):
                                img_src = os.path.join(images_dir, clean_stem + img_ext)
                                if os.path.exists(img_src):
                                    copy_file_variant(img_src, missing)
                                    break
    elif target_file:
        src_path = os.path.join(target_dir, target_file)
        if not os.path.exists(src_path):
            return {"error": f"Archivo '{target_file}' no encontrado en {target_dir}", "created": []}
        new_files = copy_file_variant(src_path, count)
        created.extend(new_files)
        if has_images:
            stem = os.path.splitext(target_file)[0]
            clean_stem = re.sub(r"\s*\(copia \d+\)$", "", stem)
            for img_ext in (".png", ".jpg", ".jpeg"):
                img_src = os.path.join(images_dir, clean_stem + img_ext)
                if os.path.exists(img_src):
                    copy_file_variant(img_src, count)
                    break
    else:
        return {"error": "No se especificó ninguna acción de duplicación.", "created": []}

    # Invalidate preview cache
    if os.path.exists(PREVIEW_CACHE_DIR):
        for f in os.listdir(PREVIEW_CACHE_DIR):
            if f.startswith("deckgen_preview_"):
                try:
                    os.remove(os.path.join(PREVIEW_CACHE_DIR, f))
                except OSError:
                    pass

    return {
        "status": "ok",
        "created": [os.path.basename(f) for f in created],
        "count": len(created),
        "message": f"Se crearon exitosamente {len(created)} copia(s) de carta(s)."
    }


class DeckCheckHandler(tornado.web.RequestHandler):
    def post(self):
        export_dir = self.get_body_argument("export_dir", "").strip()
        deck_path = self.get_body_argument("deck_path", self.get_body_argument("xml_path", "")).strip()
        file_content = None
        if "deck_file" in self.request.files:
            file_content = self.request.files["deck_file"][0]["body"]
        elif "xml_file" in self.request.files:
            file_content = self.request.files["xml_file"][0]["body"]
        res = inspect_deck_file(export_dir, deck_path or None, file_content)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(res))


class DeckDuplicateHandler(tornado.web.RequestHandler):
    def post(self):
        export_dir = self.get_body_argument("export_dir", "").strip()
        target_file = self.get_body_argument("target_file", "").strip()
        copies_to_add = int(self.get_body_argument("copies_to_add", "1"))
        auto_deck = parse_bool(self.get_body_argument("auto_deck", self.get_body_argument("auto_xml", "false")))
        deck_path = self.get_body_argument("deck_path", self.get_body_argument("xml_path", "")).strip()
        file_content = None
        if "deck_file" in self.request.files:
            file_content = self.request.files["deck_file"][0]["body"]
        elif "xml_file" in self.request.files:
            file_content = self.request.files["xml_file"][0]["body"]
        res = duplicate_deck_cards(
            export_dir=export_dir,
            target_file=target_file or None,
            count=copies_to_add,
            auto_deck=auto_deck,
            deck_path=deck_path or None,
            file_content=file_content,
        )
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(res))


def inspect_custom_backs(export_dir):
    if not export_dir or not os.path.isdir(export_dir):
        return {"error": f"Directorio no encontrado: '{export_dir}'"}

    try:
        front_pdfs = collect_front_pdfs(export_dir)
    except Exception as e:
        return {"error": f"No se encontraron cartas frontales: {e}"}

    backs_dir = os.path.join(export_dir, "backs")
    available_backs = []
    if os.path.isdir(backs_dir):
        for f in sorted(os.listdir(backs_dir)):
            if f.lower().endswith(".pdf") and not f.lower().startswith(("sheet", "deckgen_")):
                available_backs.append(os.path.join("backs", f))
    for f in sorted(os.listdir(export_dir)):
        if f.lower().endswith(".pdf") and "back" in f.lower() and not f.lower().startswith(("sheet", "deckgen_")):
            if f not in available_backs:
                available_backs.append(f)

    custom_map = load_custom_backs(export_dir)

    # Check cards.xml for back slot pairing
    xml_pairs = {}
    for xml_cand in [os.path.join(export_dir, "cards.xml"), os.path.join(export_dir, "images", "cards.xml")]:
        if os.path.isfile(xml_cand):
            try:
                tree = ET.parse(xml_cand)
                root = tree.getroot()
                f_by_slot = {}
                for c in root.findall("fronts/card"):
                    cname = c.findtext("name", "").strip()
                    cid = c.findtext("id", "").strip()
                    cquery = c.findtext("query", "").strip()
                    for s in [x.strip() for x in c.findtext("slots", "").split(",") if x.strip()]:
                        f_by_slot[s] = {"name": cname, "id": cid, "query": cquery}
                for b in root.findall("backs/card"):
                    bname = b.findtext("name", "").strip()
                    bid = b.findtext("id", "").strip()
                    bquery = b.findtext("query", "").strip()
                    for s in [x.strip() for x in b.findtext("slots", "").split(",") if x.strip()]:
                        if s in f_by_slot:
                            f_info = f_by_slot[s]
                            xml_pairs[normalize_card_text(f_info["name"])] = bname
                            xml_pairs[normalize_card_text(f_info["query"])] = bname
            except Exception:
                pass
            break

    cards_data = []
    custom_count = 0
    for idx, fpath in enumerate(front_pdfs):
        fname = os.path.basename(fpath)
        stem = os.path.splitext(fname)[0]
        m = re.match(r"^\(([^)]+)\)\s*\(([^)]+)\)", fname)
        if m:
            clean_name = f"{m.group(2)} ({m.group(1)})"
        else:
            clean_name = re.sub(r"\s*\(copia \d+\)", "", stem)
            clean_name = re.sub(r"\s*\([a-zA-Z0-9_\-]{20,}\)", "", clean_name)
            clean_name = re.sub(r"\s*\[.*?\]|\{.*?\}", "", clean_name).strip()

        assigned_back = custom_map.get(fname) or custom_map.get(stem)
        is_custom = bool(assigned_back)
        if is_custom:
            custom_count += 1

        norm = normalize_card_text(fname)
        paired_xml = xml_pairs.get(norm)

        cards_data.append({
            "index": idx + 1,
            "filename": fname,
            "name": clean_name,
            "custom_back": assigned_back,
            "custom_back_filename": os.path.basename(assigned_back) if assigned_back else None,
            "is_custom": is_custom,
            "xml_paired_back": paired_xml,
        })

    generic_back = find_generic_back_pdf(export_dir)

    return {
        "status": "ok",
        "export_dir": export_dir,
        "total_cards": len(cards_data),
        "custom_count": custom_count,
        "generic_count": len(cards_data) - custom_count,
        "available_backs": available_backs,
        "generic_back": os.path.basename(generic_back) if generic_back else None,
        "cards": cards_data,
    }


def assign_custom_backs(export_dir, card_filenames, back_file_body=None, back_filename=None, original_filename=None):
    if not export_dir or not os.path.isdir(export_dir):
        return {"error": f"Directorio no encontrado: '{export_dir}'"}
    if not card_filenames:
        return {"error": "No se seleccionaron cartas para asignar reverso."}

    backs_dir = os.path.join(export_dir, "backs")
    os.makedirs(backs_dir, exist_ok=True)

    assigned_rel_path = None
    if back_file_body:
        fname = original_filename or "custom_back.pdf"
        base, ext = os.path.splitext(fname)
        if ext.lower() not in (".pdf", ".png", ".jpg", ".jpeg"):
            ext = ".pdf"
        safe_fname = re.sub(r"[^\w\s\-\.\(\)]", "_", base).strip() + ext
        dest_path = os.path.join(backs_dir, safe_fname)
        if ext.lower() in (".png", ".jpg", ".jpeg"):
            pdf_dest = os.path.join(backs_dir, base + ".pdf")
            image_to_standard_pdf(back_file_body, pdf_dest)
            assigned_rel_path = os.path.join("backs", os.path.basename(pdf_dest))
        else:
            with open(dest_path, "wb") as f:
                f.write(back_file_body)
            assigned_rel_path = os.path.join("backs", safe_fname)
    elif back_filename:
        cand = os.path.join(export_dir, back_filename)
        cand_backs = os.path.join(backs_dir, back_filename)
        if os.path.isfile(cand):
            assigned_rel_path = back_filename
        elif os.path.isfile(cand_backs):
            assigned_rel_path = os.path.join("backs", back_filename)
        else:
            return {"error": f"Archivo de reverso no encontrado: '{back_filename}'"}
    else:
        return {"error": "No se proporcionó archivo ni nombre de reverso."}

    mapping = load_custom_backs(export_dir)
    for cf in card_filenames:
        mapping[cf] = assigned_rel_path

    save_custom_backs(export_dir, mapping)

    # Invalidate preview cache
    if os.path.exists(PREVIEW_CACHE_DIR):
        for f in os.listdir(PREVIEW_CACHE_DIR):
            if f.startswith("deckgen_preview_"):
                try:
                    os.remove(os.path.join(PREVIEW_CACHE_DIR, f))
                except OSError:
                    pass

    return {
        "status": "ok",
        "assigned_back": assigned_rel_path,
        "updated_count": len(card_filenames),
        "message": f"Se asignó '{os.path.basename(assigned_rel_path)}' a {len(card_filenames)} carta(s)."
    }


def remove_custom_backs(export_dir, card_filenames):
    if not export_dir or not os.path.isdir(export_dir):
        return {"error": f"Directorio no encontrado: '{export_dir}'"}
    if not card_filenames:
        return {"error": "No se seleccionaron cartas."}

    mapping = load_custom_backs(export_dir)
    removed = 0
    for cf in card_filenames:
        if cf in mapping:
            del mapping[cf]
            removed += 1
        stem = os.path.splitext(cf)[0]
        if stem in mapping:
            del mapping[stem]
            removed += 1

    save_custom_backs(export_dir, mapping)

    # Invalidate preview cache
    if os.path.exists(PREVIEW_CACHE_DIR):
        for f in os.listdir(PREVIEW_CACHE_DIR):
            if f.startswith("deckgen_preview_"):
                try:
                    os.remove(os.path.join(PREVIEW_CACHE_DIR, f))
                except OSError:
                    pass

    return {
        "status": "ok",
        "removed_count": removed,
        "message": f"Se restauraron {len(card_filenames)} carta(s) al reverso genérico."
    }


def auto_detect_custom_backs(export_dir):
    if not export_dir or not os.path.isdir(export_dir):
        return {"error": f"Directorio no encontrado: '{export_dir}'"}

    try:
        front_pdfs = collect_front_pdfs(export_dir)
    except Exception as e:
        return {"error": f"No se pudieron leer las cartas frontales: {e}"}

    backs_dir = os.path.join(export_dir, "backs")
    back_files = []
    if os.path.isdir(backs_dir):
        back_files = [f for f in os.listdir(backs_dir) if f.lower().endswith(".pdf")]

    mapping = load_custom_backs(export_dir)
    new_detected = 0

    # 1. XML detection
    for xml_cand in [os.path.join(export_dir, "cards.xml"), os.path.join(export_dir, "images", "cards.xml")]:
        if os.path.isfile(xml_cand):
            try:
                tree = ET.parse(xml_cand)
                root = tree.getroot()
                f_by_slot = {}
                for c in root.findall("fronts/card"):
                    cname = c.findtext("name", "").strip()
                    cid = c.findtext("id", "").strip()
                    cquery = c.findtext("query", "").strip()
                    for s in [x.strip() for x in c.findtext("slots", "").split(",") if x.strip()]:
                        f_by_slot[s] = {"name": cname, "id": cid, "query": cquery}

                for b in root.findall("backs/card"):
                    bname = b.findtext("name", "").strip()
                    bid = b.findtext("id", "").strip()
                    bquery = b.findtext("query", "").strip()
                    for s in [x.strip() for x in b.findtext("slots", "").split(",") if x.strip()]:
                        if s in f_by_slot:
                            f_info = f_by_slot[s]
                            f_match = None
                            for f in front_pdfs:
                                f_base = os.path.basename(f)
                                if (f_info["id"] and f_info["id"] in f_base) or \
                                   (normalize_card_text(f_info["name"]) and normalize_card_text(f_info["name"]) in normalize_card_text(f_base)) or \
                                   (normalize_card_text(f_info["query"]) and normalize_card_text(f_info["query"]) in normalize_card_text(f_base)):
                                    f_match = f_base
                                    break
                            b_match = None
                            for bf in back_files:
                                if (bid and bid in bf) or \
                                   (normalize_card_text(bname) and normalize_card_text(bname) in normalize_card_text(bf)) or \
                                   (normalize_card_text(bquery) and normalize_card_text(bquery) in normalize_card_text(bf)):
                                    b_match = os.path.join("backs", bf)
                                    break
                            if f_match and b_match:
                                mapping[f_match] = b_match
                                new_detected += 1
            except Exception:
                pass
            break

    # 2. Disk name matching in backs/
    if back_files:
        for f in front_pdfs:
            f_base = os.path.basename(f)
            if f_base in mapping:
                continue
            f_norm = normalize_card_text(f_base)
            for bf in back_files:
                if bf.lower().startswith(("sheet", "deckgen_", "card_back", "back.pdf", "cardback")):
                    continue
                bf_norm = normalize_card_text(bf)
                if bf_norm and (bf_norm == f_norm or bf_norm in f_norm or f_norm in bf_norm):
                    mapping[f_base] = os.path.join("backs", bf)
                    new_detected += 1
                    break

    save_custom_backs(export_dir, mapping)

    # Invalidate preview cache
    if os.path.exists(PREVIEW_CACHE_DIR):
        for f in os.listdir(PREVIEW_CACHE_DIR):
            if f.startswith("deckgen_preview_"):
                try:
                    os.remove(os.path.join(PREVIEW_CACHE_DIR, f))
                except OSError:
                    pass

    return {
        "status": "ok",
        "detected_count": new_detected,
        "total_custom": len(mapping),
        "message": f"Se auto-detectaron {new_detected} reverso(s) personalizados."
    }


class CustomBacksHandler(tornado.web.RequestHandler):
    def get(self):
        export_dir = self.get_argument("export_dir", "").strip()
        res = inspect_custom_backs(export_dir)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(res))

    def post(self):
        action = self.get_body_argument("action", "inspect").strip()
        export_dir = self.get_body_argument("export_dir", "").strip()

        if action == "inspect":
            res = inspect_custom_backs(export_dir)
        elif action == "assign":
            card_files_raw = self.get_body_argument("card_filenames", "[]")
            try:
                card_files = json.loads(card_files_raw)
            except Exception:
                card_files = [card_files_raw] if card_files_raw else []

            back_file_body = None
            original_filename = None
            if "back_pdf" in self.request.files:
                finfo = self.request.files["back_pdf"][0]
                back_file_body = finfo["body"]
                original_filename = finfo["filename"]

            back_filename = self.get_body_argument("back_filename", "").strip()

            res = assign_custom_backs(
                export_dir=export_dir,
                card_filenames=card_files,
                back_file_body=back_file_body,
                back_filename=back_filename or None,
                original_filename=original_filename,
            )
        elif action == "remove":
            card_files_raw = self.get_body_argument("card_filenames", "[]")
            try:
                card_files = json.loads(card_files_raw)
            except Exception:
                card_files = [card_files_raw] if card_files_raw else []
            res = remove_custom_backs(export_dir, card_files)
        elif action == "auto_detect":
            res = auto_detect_custom_backs(export_dir)
        else:
            res = {"error": f"Acción desconocida: '{action}'"}

        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(res))


def make_app():
    return tornado.web.Application(
        [
            (r"/", IndexHandler),
            (r"/generate", GenerateHandler),
            (r"/download", DownloadHandler),
            (r"/progress", ProgressHandler),
            (r"/preview", PreviewHandler),
            (r"/convert", ConvertImagesHandler),
            (r"/clear-cache", ClearCacheHandler),
            (r"/deck/check", DeckCheckHandler),
            (r"/deck/duplicate", DeckDuplicateHandler),
            (r"/deck/custom_backs", CustomBacksHandler),
        ]
    )


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = make_app()
    tornado.httputil.set_parse_body_config(
        tornado.httputil.ParseBodyConfig(
            multipart=tornado.httputil.ParseMultipartConfig(max_parts=100000)
        )
    )
    server = tornado.httpserver.HTTPServer(
        app,
        max_body_size=2 * 1024 ** 3,
        max_buffer_size=2 * 1024 ** 3,
    )
    port = PORT
    for offset in range(10):
        try:
            server.listen(port)
            break
        except OSError as e:
            if e.errno == 98 and offset < 9:
                port += 1
                continue
            raise
    url = f"http://127.0.0.1:{port}/"
    print(f"Listening on {url}")
    webbrowser.open(url)
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
