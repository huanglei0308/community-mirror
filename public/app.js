/**
 * Community Mirror Hub — Dashboard Logic
 *
 * Fetches community registry (config/orgs.json) and then parallel-fetches
 * each community's results.json from their gh-pages.  Renders the dashboard
 * entirely in the browser — zero server-side secrets or tokens needed.
 */

const CONFIG_URL = 'https://raw.githubusercontent.com/huanglei0308/community-mirror/main/config/orgs.json';
const STALE_HOURS = 36; // warn if data is older than this

// ── Helpers ────────────────────────────────────────────

function fmtTime(iso) {
  try {
    const d = new Date(iso.replace('Z', '+00:00'));
    return d.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  } catch (_) { return iso || 'N/A'; }
}

function hoursAgo(iso) {
  try {
    return (Date.now() - new Date(iso.replace('Z', '+00:00')).getTime()) / 3600000;
  } catch (_) { return Infinity; }
}

function repoTag(name, cls) {
  return `<span class="repo-tag ${cls}">${escapeHtml(name)}</span>`;
}

function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Fetch all data ─────────────────────────────────────

async function fetchAll() {
  // 1. Load community registry
  let config;
  try {
    const resp = await fetch(CONFIG_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    config = await resp.json();
  } catch (e) {
    document.getElementById('community-list').innerHTML =
      `<div class="error">Failed to load community registry: ${escapeHtml(e.message)}</div>`;
    return;
  }

  document.title = config.title || 'Community Mirror Hub';

  // 2. Parallel fetch all results.json
  const results = await Promise.all(
    config.repos.map(async (repo) => {
      try {
        const resp = await fetch(repo.results_url, { cache: 'no-cache' });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        return { ...repo, data, ok: true };
      } catch (e) {
        return { ...repo, data: null, ok: false, error: e.message };
      }
    })
  );

  render(config, results);
}

// ── Render ─────────────────────────────────────────────

let currentResults = [];

function render(config, results) {
  currentResults = results;

  // --- Aggregates ---
  let totalOrgs = results.length;
  let totalRepos = 0, totalSuccess = 0, totalFailed = 0, totalSkipped = 0;
  let latest = '';

  results.forEach((r) => {
    const d = r.data;
    if (!d) return;
    totalRepos   += d.total   || 0;
    totalSuccess += d.success || 0;
    totalFailed  += d.failed  || 0;
    totalSkipped += d.skipped || 0;
    if (d.timestamp && d.timestamp > latest) latest = d.timestamp;
  });

  document.getElementById('total-orgs').textContent = totalOrgs;
  document.getElementById('total-repos').textContent = totalRepos;
  document.getElementById('total-success').textContent = totalSuccess;
  document.getElementById('total-failed').textContent = totalFailed;
  document.getElementById('total-skipped').textContent = totalSkipped;
  document.getElementById('last-refresh').textContent =
    latest ? `Latest data: ${fmtTime(latest)}` : '';

  // --- Stale warning ---
  const staleWarn = document.getElementById('stale-warning');
  if (staleWarn) {
    const hasStale = results.some(r => r.data && hoursAgo(r.data.timestamp) > STALE_HOURS);
    staleWarn.style.display = hasStale ? 'block' : 'none';
  }

  // --- Community list ---
  renderList(results);
}

function renderList(results) {
  const el = document.getElementById('community-list');

  if (!results.length) {
    el.innerHTML = '<div class="empty">No communities registered yet.</div>';
    return;
  }

  el.innerHTML = results.map((r) => {
    const d = r.data;

    // Error / no data state
    if (!d) {
      return `
        <div class="org-card stale">
          <div class="org-header">
            <span class="org-name">
              ${escapeHtml(r.org)}
              <span class="org-badge stale">NO DATA</span>
            </span>
            <div class="org-meta">
              ${r.contact ? `Contact: ${escapeHtml(r.contact)}` : ''}
            </div>
          </div>
          <div class="org-body">
            <p class="org-flow" style="color:var(--danger)">
              Failed to load: ${escapeHtml(r.error || 'Unknown error')}
            </p>
            <p class="org-flow">
              <a href="${escapeHtml(r.results_url)}" target="_blank">results.json</a>
            </p>
          </div>
        </div>`;
    }

    // Normal state
    const failed    = d.failed || 0;
    const skipped   = d.skipped || 0;
    const success   = d.success || 0;
    const total     = d.total || 0;
    const failedList  = d.failed_list  || [];
    const skippedList = d.skipped_list || [];
    const successList = d.success_list || [];
    const stale    = hoursAgo(d.timestamp) > STALE_HOURS;
    const cardCls  = (!r.ok) ? 'stale' : (failed > 0 ? 'failed' : 'ok');
    const badgeCls = (!r.ok) ? 'stale' : (failed > 0 ? 'err' : 'ok');
    const badgeText= (!r.ok) ? 'ERROR'  : (failed > 0 ? 'HAS FAILURES' : 'ALL GOOD');

    // Failed section
    let failedHtml = '';
    if (failedList.length) {
      failedHtml = `
        <p style="font-size:13px;font-weight:600;color:var(--danger);margin-top:10px;">
          &#x26A0; Failed repos (${failedList.length})</p>
        <div class="repo-tags">${failedList.map(n => repoTag(n, 'failed')).join('')}</div>`;
    }

    // Skipped section
    let skippedHtml = '';
    if (skippedList.length) {
      skippedHtml = `
        <details>
          <summary style="color:var(--warn);">Skipped repos (${skippedList.length})</summary>
          <div class="repo-tags">${skippedList.map(n => repoTag(n, 'skipped')).join('')}</div>
        </details>`;
    }

    // Success section
    let successHtml = '';
    if (successList.length) {
      successHtml = `
        <details>
          <summary style="color:var(--success);">&#x2705; Synced repos (${successList.length})</summary>
          <div class="repo-tags">${successList.map(n => repoTag(n, 'success')).join('')}</div>
        </details>`;
    }

    const srcShort = (d.src || '').split('/').pop() || d.src || '';
    const dstShort = (d.dst || '').split('/').pop() || d.dst || '';

    return `
      <div class="org-card ${cardCls}" data-status="${cardCls}">
        <div class="org-header">
          <span class="org-name">
            ${escapeHtml(r.org)}
            <span class="org-badge ${badgeCls}">${badgeText}</span>
            ${stale ? '<span class="org-badge stale">STALE</span>' : ''}
          </span>
          <div class="org-meta">
            ${r.contact ? `Contact: ${escapeHtml(r.contact)}<br>` : ''}
            ${fmtTime(d.timestamp)}
          </div>
        </div>
        <div class="org-body">
          <div class="status-row">
            <span><span class="dot g"></span> ${success} synced</span>
            <span><span class="dot r"></span> ${failed} failed</span>
            <span><span class="dot y"></span> ${skipped} skipped</span>
            <span style="font-size:12px;color:var(--muted);">${total} total</span>
          </div>
          <p class="org-flow">
            ${escapeHtml(d.src)} &#8594; ${escapeHtml(d.dst)}
            &nbsp;&middot;&nbsp;
            <a href="https://github.com/${escapeHtml(r.owner)}" target="_blank">GitHub</a>
            &nbsp;&middot;&nbsp;
            <a href="community.html?org=${encodeURIComponent(r.org)}">查看详情 →</a>
          </p>
          ${failedHtml}
          ${skippedHtml}
          ${successHtml}
        </div>
      </div>`;
  }).join('');

  // Re-apply filter
  applyFilter(document.querySelector('.filter-btn.active')?.dataset?.filter || 'all');
}

// ── Filter ─────────────────────────────────────────────

function applyFilter(filter) {
  document.querySelectorAll('.org-card').forEach(card => {
    if (filter === 'all') {
      card.style.display = '';
    } else {
      card.style.display = card.dataset.status === filter ? '' : 'none';
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  // Filter buttons
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      applyFilter(btn.dataset.filter);
    });
  });

  // Kick off
  fetchAll();
});
