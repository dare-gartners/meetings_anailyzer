// ── Tag colour palette (deterministic by name) ──────────────────────────────
const TAG_COLORS = [
  { bg: '#bfdbfe', text: '#1e40af' },
  { bg: '#bbf7d0', text: '#15803d' },
  { bg: '#e9d5ff', text: '#7e22ce' },
  { bg: '#fed7aa', text: '#c2410c' },
  { bg: '#fbcfe8', text: '#be185d' },
  { bg: '#fef08a', text: '#a16207' },
  { bg: '#c7d2fe', text: '#4338ca' },
  { bg: '#fecaca', text: '#b91c1c' },
  { bg: '#99f6e4', text: '#0f766e' },
  { bg: '#a5f3fc', text: '#0e7490' },
];
function tagPalette(name) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h += name.charCodeAt(i) * (i + 1);
  const c = TAG_COLORS[h % TAG_COLORS.length];
  return { bg: c.bg, color: c.text };
}

// ── State ────────────────────────────────────────────────────────────────────
let currentMeetingId = null;
let activeTagFilter = null;
let beforeSearchRestore = null;

// ── DOM refs ─────────────────────────────────────────────────────────────────
const viewAnalyze = document.getElementById('view-analyze');
const viewDetail  = document.getElementById('view-detail');
const sidebarList = document.getElementById('sidebar-list');
const form        = document.getElementById('form');
const submitBtn   = document.getElementById('submit-btn');
const errorBanner = document.getElementById('error');
const tagInput    = document.getElementById('tag-input');
const tagError    = document.getElementById('tag-error');

// ── Sidebar ──────────────────────────────────────────────────────────────────
async function loadSidebar() {
  const url = activeTagFilter ? `/meetings?tag=${encodeURIComponent(activeTagFilter)}` : '/meetings';
  const res = await fetch(url);
  if (!res.ok) return;
  const meetings = await res.json();
  sidebarList.innerHTML = '';
  if (meetings.length === 0) {
    sidebarList.innerHTML = '<div class="sidebar-empty">No meetings yet.</div>';
    return;
  }
  meetings.forEach(m => {
    const item = document.createElement('div');
    item.className = 'sidebar-item' + (m.id === currentMeetingId ? ' active' : '');
    item.dataset.id = m.id;
    const date = new Date(m.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    item.innerHTML = `<div class="sidebar-item-title">${esc(m.title)}</div><div class="sidebar-item-date">${date}</div>`;
    item.addEventListener('click', () => openMeeting(m.id));
    sidebarList.appendChild(item);
  });
}

function setSidebarActive(id) {
  document.querySelectorAll('.sidebar-item').forEach(el => {
    el.classList.toggle('active', parseInt(el.dataset.id) === id);
  });
}

// ── Views ────────────────────────────────────────────────────────────────────
function showHomeView() {
  currentMeetingId = null;
  beforeSearchRestore = null;
  viewAnalyze.style.display = 'none';
  viewDetail.style.display  = 'none';
  document.getElementById('view-tags').style.display   = 'none';
  document.getElementById('view-search').style.display = 'none';
  document.getElementById('view-home').style.display   = '';
  document.getElementById('search-container').style.display = 'none';
  document.getElementById('search-input').value = '';
  document.getElementById('home-search-input').value = '';
  document.getElementById('tags-nav-btn').classList.remove('active');
  setSidebarActive(null);
  document.getElementById('home-search-input').focus();
}

function showAnalyzeView() {
  currentMeetingId = null;
  beforeSearchRestore = null;
  document.getElementById('title').value = '';
  document.getElementById('notes').value = '';
  document.getElementById('date').value = '';
  document.getElementById('recording-url').value = '';
  errorBanner.classList.remove('visible');
  viewAnalyze.style.display = '';
  viewDetail.style.display  = 'none';
  document.getElementById('view-tags').style.display = 'none';
  document.getElementById('view-search').style.display = 'none';
  document.getElementById('search-container').style.display = 'none';
  document.getElementById('search-input').value = '';
  document.getElementById('tags-nav-btn').classList.remove('active');
  setSidebarActive(null);
}

async function showTagsView() {
  beforeSearchRestore = null;
  document.getElementById('search-input').value = '';
  document.getElementById('view-search').style.display = 'none';
  document.getElementById('view-home').style.display = 'none';
  document.getElementById('search-container').style.display = '';
  viewAnalyze.style.display = 'none';
  viewDetail.style.display  = 'none';
  document.getElementById('view-tags').style.display = '';
  document.getElementById('tags-nav-btn').classList.add('active');
  setSidebarActive(null);
  const res = await fetch('/tags/trending');
  if (!res.ok) return;
  const tags = await res.json();
  renderTagsAnalytics(tags);
}

function renderTagsAnalytics(tags) {
  const container = document.getElementById('tags-analytics');
  container.innerHTML = '';
  if (!tags.length) {
    container.textContent = 'No tags yet.';
    return;
  }
  tags.forEach(t => {
    const p = tagPalette(t.name);
    const span = document.createElement('span');
    span.className = 'tag tag-stat' + (activeTagFilter === t.name ? ' tag-active' : '');
    span.style.background = p.bg;
    span.style.color = p.color;
    span.innerHTML = `${esc(t.name)} <span class="tag-stat-count">${t.count}</span>`;
    span.addEventListener('click', () => {
      activeTagFilter = activeTagFilter === t.name ? null : t.name;
      loadSidebar();
      renderTagsAnalytics(tags);
    });
    container.appendChild(span);
  });
}

async function openMeeting(id, successMessage = null) {
  const res = await fetch(`/meetings/${id}`);
  if (!res.ok) return;
  const m = await res.json();
  currentMeetingId = id;
  beforeSearchRestore = null;
  document.getElementById('search-input').value = '';
  renderDetail(m);
  viewAnalyze.style.display = 'none';
  viewDetail.style.display  = '';
  document.getElementById('view-tags').style.display = 'none';
  document.getElementById('view-search').style.display = 'none';
  document.getElementById('view-home').style.display = 'none';
  document.getElementById('search-container').style.display = '';
  setSidebarActive(id);
  if (successMessage) {
    const banner = document.getElementById('success-banner');
    banner.textContent = successMessage;
    banner.style.display = '';
    setTimeout(() => { banner.style.display = 'none'; }, 5000);
  }
}

function renderDetail(m) {
  currentMeetingId = m.id;
  document.getElementById('detail-title').textContent = m.title;
  document.getElementById('detail-summary').textContent = m.summary || '—';
  document.getElementById('detail-notes-raw').textContent = m.notes_raw || '';

  // Meta row: recording (left), meeting date (right)
  const meta = document.getElementById('detail-meta');
  meta.innerHTML = '';
  if (m.recording_url) meta.innerHTML += `<a class="recording-link" href="${esc(m.recording_url)}" target="_blank" rel="noopener">🎥 Recording</a>`;
  if (m.date) meta.innerHTML += `<span class="detail-meta-created">📅 ${esc(m.date)}</span>`;

  renderDetailTags(m.tags || [], m.id);

  const atLimit = (m.tags || []).length >= 10;
  document.getElementById('tag-add-form').style.display = atLimit ? 'none' : 'flex';
  document.getElementById('tag-count').textContent = `${(m.tags || []).length}/10`;
  tagError.textContent = atLimit ? 'Tag limit reached' : '';
  tagInput.value = '';

  const sr = document.getElementById('similar-results');
  sr.style.display = 'none';
  sr.innerHTML = '';
}

function renderDetailTags(tags, meetingId) {
  const container = document.getElementById('detail-tags');
  container.innerHTML = '';
  tags.forEach(name => {
    const p = tagPalette(name);
    const span = document.createElement('span');
    span.className = 'tag';
    span.style.background = p.bg;
    span.style.color = p.color;
    span.innerHTML = `${esc(name)}<button class="tag-remove" title="Remove tag" data-tag="${esc(name)}">&times;</button>`;
    span.querySelector('.tag-remove').addEventListener('click', () => removeTag(meetingId, name));
    container.appendChild(span);
  });
}

// ── Analyze form ─────────────────────────────────────────────────────────────
document.getElementById('new-btn').addEventListener('click', showAnalyzeView);
document.getElementById('back-btn').addEventListener('click', showAnalyzeView);
document.getElementById('tags-nav-btn').addEventListener('click', showTagsView);

document.getElementById('cancel-btn').addEventListener('click', () => {
  document.getElementById('title').value = '';
  document.getElementById('notes').value = '';
  document.getElementById('date').value = '';
  document.getElementById('recording-url').value = '';
  errorBanner.classList.remove('visible');
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const title = document.getElementById('title').value.trim();
  const notes = document.getElementById('notes').value.trim();
  if (!title || !notes) {
    errorBanner.textContent = !title && !notes
      ? 'Please fill in the meeting title and notes.'
      : !title ? 'Please fill in the meeting title.'
      : 'Please fill in the meeting notes.';
    errorBanner.classList.add('visible');
    return;
  }
  const date         = document.getElementById('date').value || null;
  const recordingUrl = document.getElementById('recording-url').value.trim() || null;

  submitBtn.disabled = true;
  submitBtn.textContent = 'Saving…';
  errorBanner.classList.remove('visible');

  try {
    const res = await fetch('/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, notes, date, recording_url: recordingUrl }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Server error: ${res.status}`);
    }
    const data = await res.json();
    await loadSidebar();
    if (data.id) {
      await openMeeting(data.id, 'Meeting saved successfully.');
    }
  } catch (err) {
    errorBanner.textContent = err.message || 'Something went wrong. Please try again.';
    errorBanner.classList.add('visible');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Save';
  }
});

// ── Tag add/remove ───────────────────────────────────────────────────────────
const TAG_RE = /^[a-z0-9][a-z0-9-]*$/;

document.getElementById('tag-add-btn').addEventListener('click', async () => {
  const name = tagInput.value.trim().toLowerCase();
  tagError.textContent = '';
  if (!name) return;
  if (!TAG_RE.test(name)) {
    tagError.textContent = 'Lowercase letters, digits, hyphens only. Must start with a letter or digit.';
    return;
  }
  const res = await fetch(`/meetings/${currentMeetingId}/tags`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  const data = await res.json();
  if (!res.ok) { tagError.textContent = data.detail || 'Could not add tag.'; return; }
  renderDetail(data);
});

tagInput.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); document.getElementById('tag-add-btn').click(); } });

async function removeTag(meetingId, name) {
  const res = await fetch(`/meetings/${meetingId}/tags/${encodeURIComponent(name)}`, { method: 'DELETE' });
  if (!res.ok) return;
  const data = await res.json();
  renderDetail(data);
}

// ── Delete meeting ───────────────────────────────────────────────────────────
document.getElementById('delete-btn').addEventListener('click', async () => {
  if (!currentMeetingId) return;
  if (!confirm('Delete this meeting? This cannot be undone.')) return;
  const res = await fetch(`/meetings/${currentMeetingId}`, { method: 'DELETE' });
  if (!res.ok) return;
  await loadSidebar();
  showAnalyzeView();
});

// ── Similar meetings ─────────────────────────────────────────────────────────
document.getElementById('similar-btn').addEventListener('click', async () => {
  const btn = document.getElementById('similar-btn');
  const container = document.getElementById('similar-results');
  btn.disabled = true;
  btn.textContent = 'Searching…';
  container.style.display = 'none';
  container.innerHTML = '';

  try {
    const res = await fetch(`/meetings/${currentMeetingId}/similar`, { method: 'POST' });
    if (!res.ok) throw new Error('Request failed');
    const results = await res.json();
    container.style.display = 'flex';

    if (results.length === 0) {
      container.innerHTML = '<div class="similar-empty">No similar meetings found.</div>';
    } else {
      results.forEach(m => buildSimCard(m, container));
    }
  } catch {
    container.style.display = 'flex';
    container.innerHTML = '<div class="similar-empty">Could not load similar meetings.</div>';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Show related meetings';
  }
});

function firstLine(text) {
  return (text || '').split('\n')[0].trim();
}

function buildSimCard(m, container) {
  const matches = m.all_matches.slice(0, 3);
  const date = new Date(m.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  const pct = Math.round(m.score * 100);

  const card = document.createElement('div');
  card.className = 'sim-card';

  // Header
  const header = document.createElement('div');
  header.className = 'sim-card-header';
  header.innerHTML = `
    <div class="sim-card-header-left">
      <div class="sim-card-header-title">${esc(m.title)}</div>
      <div class="sim-card-header-date">${date}</div>
    </div>
    <div class="sim-card-header-right">
      <span class="sim-badge">${pct}% similar</span>
      <button class="sim-expand-btn" type="button" title="Expand">+</button>
    </div>`;
  header.querySelector('.sim-card-header-title').style.cursor = 'pointer';
  header.querySelector('.sim-card-header-title').addEventListener('click', (e) => { e.stopPropagation(); openMeeting(m.id); });

  // Table
  const tableWrap = document.createElement('div');
  tableWrap.className = 'sim-table-wrap';
  tableWrap.innerHTML = buildSimTable(m);

  // Wire Why? buttons
  tableWrap.querySelectorAll('.why-btn').forEach((whyBtn, idx) => {
    whyBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const match = matches[idx];
      const existingRow = tableWrap.querySelector(`[data-explain-row="${idx}"]`);
      if (existingRow) { existingRow.remove(); whyBtn.textContent = 'Why?'; return; }
      whyBtn.disabled = true;
      whyBtn.textContent = '…';
      try {
        const res = await fetch('/matches/explain', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            source_chunk: match.source_description || match.source_chunk,
            matched_chunk: match.matched_description || match.matched_chunk,
          }),
        });
        const data = await res.json();
        const tr = tableWrap.querySelector(`[data-row="${idx}"]`);
        const explainTr = document.createElement('tr');
        explainTr.className = 'explain-row';
        explainTr.dataset.explainRow = idx;
        const text = data.explanation || data.detail || 'Could not generate explanation.';
        explainTr.innerHTML = `<td colspan="4">${esc(text)}</td>`;
        tr.insertAdjacentElement('afterend', explainTr);
        whyBtn.textContent = 'Hide';
      } catch (err) {
        whyBtn.textContent = 'Error';
        setTimeout(() => { whyBtn.textContent = 'Why?'; }, 2000);
      } finally {
        whyBtn.disabled = false;
      }
    });
  });

  // Toggle: show/hide extra rows and the "more" footer row
  let expanded = false;
  const expandBtn = header.querySelector('.sim-expand-btn');
  function toggleExpand(e) {
    if (e) e.stopPropagation();
    expanded = !expanded;
    tableWrap.querySelectorAll('tr[data-row]').forEach((tr, i) => {
      if (i > 0) tr.style.display = expanded ? '' : 'none';
    });
    const moreRow = tableWrap.querySelector('.more-row');
    if (moreRow) moreRow.style.display = expanded ? 'none' : '';
    expandBtn.textContent = expanded ? '−' : '+';
  }
  expandBtn.addEventListener('click', toggleExpand);
  tableWrap.querySelector('.sim-more-link')?.addEventListener('click', (e) => { e.stopPropagation(); toggleExpand(null); });

  card.appendChild(header);
  card.appendChild(tableWrap);
  container.appendChild(card);
}

function buildSimTable(m) {
  const allMatches = m.all_matches.slice(0, 3);
  const extra = allMatches.length - 1;
  const rows = allMatches.map((match, idx) => {
    const pct = Math.round(match.score * 100);
    const srcLabel = match.source_description || firstLine(match.source_chunk);
    const matchLabel = match.matched_description || firstLine(match.matched_chunk);
    const hidden = idx > 0 ? ' style="display:none"' : '';
    return `<tr class="${match.is_best ? 'best-row' : ''}" data-row="${idx}"${hidden}>
      <td class="col-your">${esc(srcLabel)}</td>
      <td class="col-match">${esc(matchLabel)}</td>
      <td class="col-score">${pct}%</td>
      <td class="col-why"><button class="why-btn" type="button">Why?</button></td>
    </tr>`;
  }).join('');
  const moreRow = extra > 0
    ? `<tr class="more-row"><td colspan="4"><span class="sim-more-link">+ ${extra} more matching topic${extra > 1 ? 's' : ''}</span></td></tr>`
    : '';
  return `<table class="sim-table">
    <colgroup>
      <col>
      <col>
      <col style="width:52px">
      <col style="width:72px">
    </colgroup>
    <thead><tr>
      <th>This meeting</th>
      <th>${esc(m.title)} <button class="sim-open-btn" onclick="openMeeting(${m.id})" type="button" title="Open meeting">↗</button></th>
      <th>Match</th>
      <th></th>
    </tr></thead>
    <tbody>${rows}${moreRow}</tbody>
  </table>`;
}

// ── Search ────────────────────────────────────────────────────────────────────
const searchInput = document.getElementById('search-input');
const searchSubmitBtn = document.getElementById('search-submit-btn');

function _captureRestore() {
  if (beforeSearchRestore) return;
  const wasDetail = viewDetail.style.display !== 'none';
  const wasTags   = document.getElementById('view-tags').style.display !== 'none';
  const wasHome   = document.getElementById('view-home').style.display !== 'none';
  const savedId   = currentMeetingId;
  beforeSearchRestore = () => {
    document.getElementById('view-search').style.display = 'none';
    if (wasDetail) {
      viewDetail.style.display = '';
      setSidebarActive(savedId);
    } else if (wasTags) {
      document.getElementById('view-tags').style.display = '';
      document.getElementById('tags-nav-btn').classList.add('active');
    } else if (wasHome) {
      document.getElementById('view-home').style.display = '';
    }
  };
}

async function runSearch(query) {
  _captureRestore();
  viewAnalyze.style.display = 'none';
  viewDetail.style.display  = 'none';
  document.getElementById('view-tags').style.display = 'none';
  document.getElementById('view-home').style.display = 'none';
  setSidebarActive(null);
  document.getElementById('tags-nav-btn').classList.remove('active');
  document.getElementById('search-container').style.display = '';
  searchInput.value = query;
  const searchView = document.getElementById('view-search');
  searchView.style.display = '';
  const resultsContainer = document.getElementById('search-results');
  resultsContainer.innerHTML = '<div class="search-empty">Searching…</div>';
  searchSubmitBtn.disabled = true;

  try {
    const res = await fetch('/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });
    if (!res.ok) throw new Error('Search failed');
    const results = await res.json();
    resultsContainer.innerHTML = '';
    if (!results.length) {
      resultsContainer.innerHTML = '<div class="search-empty">No meetings found for this query.</div>';
    } else {
      results.forEach(r => buildSearchCard(r, resultsContainer));
    }
  } catch {
    resultsContainer.innerHTML = '<div class="search-empty">Search failed. Please try again.</div>';
  } finally {
    searchSubmitBtn.disabled = false;
  }
}

function buildSearchCard(r, container) {
  const date = new Date(r.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  const label = r.matched_description || firstLine(r.matched_chunk);

  const card = document.createElement('div');
  card.className = 'sim-card';
  card.style.cursor = 'pointer';
  card.innerHTML = `
    <div class="sim-card-header">
      <div class="sim-card-header-left">
        <div class="sim-card-header-title">${esc(r.title)}</div>
        <div class="sim-card-header-date">${date}</div>
      </div>
      <div class="sim-card-header-right">
      </div>
    </div>
    <div class="sim-card-body">
      <div class="sim-chunk">${esc(label)}</div>
    </div>`;
  card.addEventListener('click', () => openMeeting(r.id));
  container.appendChild(card);
}

document.getElementById('app-title').addEventListener('click', showHomeView);

const homeSearchInput = document.getElementById('home-search-input');
document.getElementById('home-search-btn').addEventListener('click', () => {
  const q = homeSearchInput.value.trim();
  if (q) runSearch(q);
});
homeSearchInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    const q = homeSearchInput.value.trim();
    if (q) runSearch(q);
  }
});

searchSubmitBtn.addEventListener('click', () => {
  const q = searchInput.value.trim();
  if (q) runSearch(q);
});

searchInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    const q = searchInput.value.trim();
    if (q) runSearch(q);
  }
});

searchInput.addEventListener('input', () => {
  if (!searchInput.value.trim() && beforeSearchRestore) {
    beforeSearchRestore();
    beforeSearchRestore = null;
  }
});

// ── Helpers ──────────────────────────────────────────────────────────────────
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Init ─────────────────────────────────────────────────────────────────────
loadSidebar();
