(function() {
  const convertBtn = document.getElementById('convert-btn');
  const imageInput = document.getElementById('image-input');
  const exportDirInput = document.getElementById('export-dir');
  const convertResult = document.getElementById('convert-result');
  const errorMessage = document.getElementById('error-message');
  const overlay = document.getElementById('loading-overlay');

  function setLoading(show) {
    overlay.classList.toggle('active', show);
  }

  function setError(message) {
    errorMessage.textContent = message;
  }

  document.querySelectorAll('.btn-clear-field').forEach(function(btn) {
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

  window.addEventListener('load', function() { setLoading(false); });
  window.addEventListener('error', function() { setLoading(false); });
  window.addEventListener('unhandledrejection', function() { setLoading(false); });

  convertBtn.addEventListener('click', async function() {
    if (!imageInput.files.length) {
      setError('Select at least one image to convert.');
      return;
    }
    const exportDir = exportDirInput.value.trim();
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
})();
