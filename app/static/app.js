/* Slipcast dashboard — vanilla JS client.
 * No eval / no Function() so the strict CSP (script-src 'self') stays intact.
 * All data comes from /api/state; all mutations go through the JSON API. */

'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/* ---- tiny DOM builder ---- */
function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k === 'dataset') Object.assign(node.dataset, v);
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
    else if (v === true) node.setAttribute(k, '');
    else if (v !== false && v != null) node.setAttribute(k, v);
  }
  (Array.isArray(children) ? children : [children]).forEach((c) => {
    if (c == null || c === false) return;
    node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  });
  return node;
}

/* ---- client state ---- */
const state = {
  data: null,
  selected: new Set(),     // selected subscribed-channel urls
  search: '',
  sort: 'added',
  seenJobs: new Set(),     // job ids already toasted
  primed: false,           // suppress toasts for jobs that existed at first load
};

/* ---- toasts ---- */
function toast(message, kind = 'info') {
  const icon = kind === 'ok' ? '✓' : kind === 'err' ? '!' : 'ℹ';
  const t = el('div', { class: `toast ${kind}`, role: 'status' }, [
    el('span', { class: 't-icon', text: icon }),
    el('span', { text: message }),
  ]);
  $('#toaster').appendChild(t);
  setTimeout(() => {
    t.classList.add('out');
    t.addEventListener('animationend', () => t.remove(), { once: true });
  }, kind === 'err' ? 6000 : 3800);
}

/* ---- API helpers ---- */
async function readError(res) {
  try { const j = await res.json(); return j.detail || j.message || res.statusText; }
  catch { return res.statusText || 'Request failed'; }
}

async function postForm(url, formData) {
  const res = await fetch(url, { method: 'POST', body: formData });
  if (!res.ok) throw new Error(await readError(res));
  return res.json().catch(() => ({}));
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json().catch(() => ({}));
}

function fd(obj) {
  const f = new FormData();
  for (const [k, v] of Object.entries(obj)) f.append(k, v);
  return f;
}

/* ---- state loading + polling ---- */
let pollTimer = null;

async function loadState() {
  try {
    const res = await fetch('/api/state');
    if (!res.ok) return;
    state.data = await res.json();
    handleJobs(state.data.jobs || []);
    render();
  } catch { /* transient — next tick retries */ }
  schedulePoll();
}

function schedulePoll() {
  clearTimeout(pollTimer);
  const active = (state.data?.jobs || []).some((j) => j.status === 'running');
  pollTimer = setTimeout(loadState, active ? 2000 : 9000);
}

function handleJobs(jobs) {
  for (const j of jobs) {
    if (j.status === 'running' || state.seenJobs.has(j.id)) continue;
    state.seenJobs.add(j.id);
    if (state.primed) toast(j.message || j.target, j.status === 'success' ? 'ok' : 'err');
  }
  state.primed = true;
}

/* ---- rendering ---- */
function avatar(name, thumb) {
  if (thumb) return el('span', { class: 'ch-avatar' }, [el('img', { src: thumb, alt: '', loading: 'lazy', onerror: (e) => { e.target.remove(); } })]);
  const letter = (name || '?').trim().charAt(0).toUpperCase();
  return el('span', { class: 'ch-avatar', 'aria-hidden': 'true', text: letter });
}

function epBadge(n) {
  return el('span', { class: `ep-badge${n === 0 ? ' zero' : ''}`, text: n === 0 ? 'no episodes yet' : `${n} episode${n === 1 ? '' : 's'}` });
}

function subscribedCard(ch) {
  const selected = state.selected.has(ch.url);
  const card = el('div', { class: `card ch-card${selected ? ' selected' : ''}` });

  const checkbox = el('input', {
    type: 'checkbox', 'aria-label': `Select ${ch.name}`,
    onchange: (e) => { e.target.checked ? state.selected.add(ch.url) : state.selected.delete(ch.url); render(); },
  });
  checkbox.checked = selected;
  card.appendChild(el('span', { class: 'ch-select' }, [checkbox]));

  card.appendChild(el('div', { class: 'ch-top' }, [
    avatar(ch.name, ch.thumbnail),
    el('div', { class: 'ch-meta' }, [
      el('div', { class: 'ch-name', title: ch.name, text: ch.name }),
      el('div', { class: 'ch-sub' }, [epBadge(ch.episodes)]),
    ]),
  ]));

  const share = el('button', { class: 'btn btn-ghost btn-sm', type: 'button', text: 'Share', onclick: () => openShare(ch) });
  if (!ch.feed_url) { share.disabled = true; share.title = 'Feed appears after the first successful poll'; }

  card.appendChild(el('div', { class: 'ch-actions' }, [
    share,
    el('button', { class: 'btn btn-ghost btn-sm', type: 'button', text: 'Poll', onclick: () => act(() => postForm('/channels/poll', fd({ url: ch.url }))) }),
    el('button', {
      class: 'btn btn-danger-ghost btn-sm', type: 'button', text: 'Remove',
      onclick: () => { if (confirm(`Remove ${ch.name}? Downloaded audio will be deleted.`)) act(() => postForm('/channels/remove', fd({ url: ch.url }))); },
    }),
  ]));
  return card;
}

function oneoffCard(ch) {
  return el('div', { class: 'card ch-card' }, [
    el('div', { class: 'ch-top' }, [
      avatar(ch.name, ch.thumbnail),
      el('div', { class: 'ch-meta' }, [
        el('div', { class: 'ch-name', title: ch.name, text: ch.name }),
        el('div', { class: 'ch-sub' }, [epBadge(ch.episodes)]),
      ]),
    ]),
    el('div', { class: 'ch-actions' }, [
      el('button', { class: 'btn btn-ghost btn-sm', type: 'button', text: 'Share', onclick: () => openShare(ch) }),
      el('button', { class: 'btn btn-primary btn-sm', type: 'button', text: 'Subscribe', onclick: () => act(() => postForm('/channels/subscribe', fd({ channel_id: ch.channel_id, channel_name: ch.name }))) }),
    ]),
  ]);
}

function emptyCard(emoji, title, hint) {
  return el('div', { class: 'empty' }, [
    el('span', { class: 'empty-emoji', 'aria-hidden': 'true', text: emoji }),
    el('strong', { text: title }),
    el('span', { text: hint }),
  ]);
}

function filteredSubscribed() {
  let list = (state.data?.channels || []).slice();
  const q = state.search.trim().toLowerCase();
  if (q) list = list.filter((c) => c.name.toLowerCase().includes(q));
  if (state.sort === 'name') list.sort((a, b) => a.name.localeCompare(b.name));
  else if (state.sort === 'episodes') list.sort((a, b) => b.episodes - a.episodes);
  else list.sort((a, b) => (a.added_at || '').localeCompare(b.added_at || ''));
  return list;
}

function render() {
  if (!state.data) return;
  const d = state.data;

  // counts + next poll
  $('#subs-count').textContent = d.channels.length;
  $('#oneoff-count').textContent = d.unsubscribed.length;
  $('#next-poll').textContent = d.next_poll || '';
  $('#version').textContent = d.version ? `v${d.version}` : '';

  // activity indicator
  const running = (d.jobs || []).filter((j) => j.status === 'running');
  const activity = $('#activity');
  if (running.length) {
    activity.hidden = false;
    $('#activity-text').textContent = running.length === 1 ? (running[0].target || 'Working…') : `${running.length} jobs running`;
  } else { activity.hidden = true; }

  // cookie banner + status card
  renderCookies(d.cookies, d.email);

  // toolbar visibility
  $('#subs-toolbar').hidden = d.channels.length === 0;

  // subscribed grid
  const grid = $('#subs-grid');
  grid.replaceChildren();
  if (d.channels.length === 0) {
    grid.appendChild(emptyCard('📡', 'No channels yet', 'Paste a YouTube channel URL above to start building a podcast feed.'));
  } else {
    const list = filteredSubscribed();
    if (list.length === 0) grid.appendChild(emptyCard('🔍', 'No matches', 'No channels match your search.'));
    else list.forEach((ch) => grid.appendChild(subscribedCard(ch)));
  }

  // bulk bar
  state.selected.forEach((u) => { if (!d.channels.some((c) => c.url === u)) state.selected.delete(u); });
  const bulk = $('#bulk-bar');
  if (state.selected.size > 0) {
    bulk.hidden = false;
    $('#bulk-count').textContent = `${state.selected.size} selected`;
  } else { bulk.hidden = true; }

  // one-off grid
  const og = $('#oneoff-grid');
  og.replaceChildren();
  if (d.unsubscribed.length === 0) og.appendChild(emptyCard('🎯', 'Nothing here', 'One-off video downloads will appear here. Subscribe to keep getting new episodes.'));
  else d.unsubscribed.forEach((ch) => og.appendChild(oneoffCard(ch)));
}

function renderCookies(c, email) {
  const banner = $('#cookie-banner');
  if (!c.present) {
    banner.hidden = false; banner.className = 'banner is-error';
    banner.innerHTML = '<strong>No YouTube cookies.</strong> Downloads will be blocked until you upload <code>cookies.txt</code> below.';
  } else if (c.stale) {
    banner.hidden = false; banner.className = 'banner is-warn';
    banner.innerHTML = `<strong>Cookies are ${c.age_days} days old.</strong> YouTube cookies usually expire after a few weeks — re-upload soon to avoid failed polls.`;
  } else { banner.hidden = true; }

  const dot = !c.present ? 'bad' : c.stale ? 'warn' : 'ok';
  const label = !c.present ? 'No cookies' : c.stale ? 'Cookies aging' : 'Cookies active';
  const sub = c.present ? `updated ${c.updated}` : 'YouTube may block downloads';
  $('#cookies-status').replaceChildren(
    el('span', { class: `dot ${dot}` }),
    el('span', { text: label }),
    el('span', { class: 'sub', text: sub }),
  );

  const wrap = $('#cookies-email');
  wrap.replaceChildren();
  if (email.configured) {
    wrap.appendChild(el('span', { text: `✉ Expiry alerts on — ${email.address}` }));
    wrap.appendChild(el('button', { class: 'btn btn-ghost btn-sm', type: 'button', text: 'Send test email', onclick: () => act(() => postForm('/auth/test-email', new FormData())) }));
  } else {
    wrap.appendChild(el('span', { text: '✉ Email alerts not configured (set SMTP_* in .env)' }));
  }
}

/* ---- actions ---- */
async function act(fn) {
  try {
    const r = await fn();
    if (r && r.message) toast(r.message, 'ok');
    state.selected.clear();
    await loadState();
  } catch (e) {
    toast(e.message || 'Something went wrong', 'err');
  }
}

/* ---- share modal ---- */
function openShare(ch) {
  const url = ch.feed_url;
  if (!url) return;
  $('#share-name').textContent = ch.name;
  $('#share-url-input').value = url;

  const qrBox = $('#share-qr');
  qrBox.replaceChildren();
  try {
    const qr = qrcode(0, 'M');
    qr.addData(url);
    qr.make();
    qrBox.innerHTML = qr.createSvgTag({ cellSize: 4, margin: 2, scalable: true });
  } catch { qrBox.textContent = ''; }

  const noScheme = url.replace(/^https?:\/\//, '');
  $('#share-apple').href = 'podcast://' + noScheme;
  $('#share-pocketcasts').href = 'pktc://subscribe/' + noScheme;

  const modal = $('#share-modal');
  modal.hidden = false;
  $('#share-copy').focus();
}

function closeShare() { $('#share-modal').hidden = true; }

/* ---- copy ---- */
async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = el('textarea', {}, []); ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } catch { /* ignore */ }
    ta.remove();
  }
  if (btn) { const old = btn.textContent; btn.textContent = 'Copied!'; setTimeout(() => { btn.textContent = old; }, 1500); }
}

/* ---- wiring ---- */
function init() {
  $('#add-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const input = $('#add-url');
    act(() => postForm('/channels/add', fd({ url: input.value.trim() }))).then(() => { input.value = ''; });
  });

  $('#dl-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const input = $('#dl-url');
    const sub = $('#dl-subscribe').checked;
    act(() => postForm('/episodes/download', fd({ url: input.value.trim(), subscribe: sub }))).then(() => { input.value = ''; $('#dl-subscribe').checked = false; });
  });

  $('#cookies-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const file = $('#cookies-file').files[0];
    if (!file) return;
    act(() => postForm('/auth/cookies', fd({ file }))).then(() => { $('#cookies-form').reset(); });
  });

  $('#poll-all').addEventListener('click', () => act(() => postForm('/channels/poll-all', new FormData())));

  $('#subs-search').addEventListener('input', (e) => { state.search = e.target.value; render(); });
  $('#subs-sort').addEventListener('change', (e) => { state.sort = e.target.value; render(); });

  $('#bulk-poll').addEventListener('click', () => act(() => postJSON('/channels/poll-bulk', { urls: [...state.selected] })));
  $('#bulk-remove').addEventListener('click', () => {
    if (confirm(`Remove ${state.selected.size} channel(s)? Downloaded audio will be deleted.`)) act(() => postJSON('/channels/remove-bulk', { urls: [...state.selected] }));
  });
  $('#bulk-clear').addEventListener('click', () => { state.selected.clear(); render(); });

  // share modal
  $('#share-copy').addEventListener('click', (e) => copyText($('#share-url-input').value, e.target));
  $$('#share-modal [data-close]').forEach((n) => n.addEventListener('click', closeShare));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeShare(); });

  loadState();
}

document.addEventListener('DOMContentLoaded', init);
