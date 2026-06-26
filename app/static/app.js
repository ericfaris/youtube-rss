// Copy-to-clipboard for feed URLs and confirm prompts for destructive forms.
// Loaded as an external script so the page CSP can forbid inline scripts.

document.addEventListener('click', function (e) {
  const btn = e.target.closest('.btn-copy');
  if (!btn) return;
  const url = btn.dataset.url;
  function onSuccess() {
    btn.textContent = '✓';
    setTimeout(() => { btn.innerHTML = '&#128203;'; }, 1500);
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url).then(onSuccess).catch(() => fallback(url, onSuccess));
  } else {
    fallback(url, onSuccess);
  }
});

function fallback(text, onSuccess) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  try { document.execCommand('copy'); onSuccess(); } catch (e) { prompt('Copy this URL:', text); }
  document.body.removeChild(ta);
}

// Forms with a data-confirm attribute ask before submitting (replaces inline onsubmit).
document.addEventListener('submit', function (e) {
  const msg = e.target.getAttribute && e.target.getAttribute('data-confirm');
  if (msg && !window.confirm(msg)) {
    e.preventDefault();
  }
});
