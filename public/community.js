/**
 * Community Mirror Status — Single Community Detail Page
 *
 * URL: community.html?org=<community-name>
 * Fetches orgs.json to find the community, then fetches its results.json.
 */

const CONFIG_URL = 'https://raw.githubusercontent.com/huanglei0308/community-mirror/main/config/orgs.json';
const STALE_HOURS = 36;

// ── Helpers ────────────────────────────────────────────

function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

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

function platformUrl(platformSlug) {
  // "github/openeuler-mirror" → "https://github.com/openeuler-mirror"
  const parts = platformSlug.split('/');
  if (parts.length < 2) return null;
  const type = parts[0], account = parts.slice(1).join('/');
  const bases = {
    github:  'https://github.com/' + account,
    gitee:   'https://gitee.com/' + account,
    gitcode: 'https://gitcode.com/' + account,
    gitlab:  'https://gitlab.com/' + account,
  };
  return bases[type] || null;
}

const REDUCED_MOTION = typeof window !== 'undefined' &&
  window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function animateNumber(el, target) {
  if (REDUCED_MOTION || !target) { el.textContent = target; return; }
  const duration = 650;
  const start = performance.now();
  function tick(now) {
    const p = Math.min((now - start) / duration, 1);
    el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3)));
    if (p < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

// ── Render ─────────────────────────────────────────────

function render(community, data) {
  if (!data) {
    document.getElementById('org-title').textContent = community.org;
    document.getElementById('org-flow').textContent = '数据加载失败';
    document.getElementById('summary').innerHTML =
      '<div class="error">无法获取同步数据，请确认 results_url 可访问</div>';
    return;
  }

  const failed    = data.failed || 0;
  const skipped   = data.skipped || 0;
  const success   = data.success || 0;
  const total     = data.total || 0;
  const failedList  = data.failed_list  || [];
  const successList = data.success_list || [];
  const errors      = data.errors || {};
  const diagnoses   = data.diagnoses || {};
  const stale     = hoursAgo(data.timestamp) > STALE_HOURS;

  // Title & flow
  document.title = community.org + ' — Mirror Status';
  document.getElementById('org-title').textContent = community.org;
  document.getElementById('org-flow').textContent =
    (data.src || community.source || '') + ' → ' + (data.dst || community.destination || '');

  // Stale warning
  document.getElementById('stale-warning').style.display = stale ? 'block' : 'none';

  // Summary cards
  const cards = [
    { cls: 'info',    num: total,   label: '总仓库数' },
    { cls: 'success', num: success, label: '已同步' },
    { cls: 'danger',  num: failed,  label: '同步失败' },
    { cls: 'warn',    num: skipped, label: '已跳过' },
  ];
  const summaryEl = document.getElementById('summary');
  summaryEl.innerHTML = cards.map(c =>
    `<div class="card ${c.cls}"><div class="number" data-target="${c.num}">0</div><div class="label">${c.label}</div></div>`
  ).join('');
  summaryEl.querySelectorAll('[data-target]').forEach(el => animateNumber(el, Number(el.dataset.target)));

  // Progress bar
  if (total > 0) {
    const pSuccess = (success / total * 100).toFixed(1);
    const pFailed  = (failed  / total * 100).toFixed(1);
    const pSkipped = (skipped / total * 100).toFixed(1);
    document.getElementById('progress-bar').innerHTML =
      `<div class="bar-success" style="width:${pSuccess}%"></div>
       <div class="bar-failed"  style="width:${pFailed}%"></div>
       <div class="bar-skipped" style="width:${pSkipped}%"></div>`;
  }

  // Meta links: source, destination, sync-config
  const links = [];
  const srcUrl = platformUrl(community.source);
  const dstUrl = platformUrl(community.destination);
  const syncUrl = 'https://github.com/' + community.owner + '/sync-config';

  if (srcUrl) links.push({ label: '源：' + community.source, url: srcUrl });
  if (dstUrl) links.push({ label: '目的：' + community.destination, url: dstUrl });
  links.push({ label: '同步配置仓', url: syncUrl });

  document.getElementById('meta-links').innerHTML = links.map(l =>
    `<a href="${escapeHtml(l.url)}" target="_blank" rel="noopener">${escapeHtml(l.label)} ↗</a>`
  ).join('');

  // Failed repos table with reasons
  const failedSection = document.getElementById('failed-section');
  if (failedList.length > 0) {
    const rows = failedList.map(repo => {
      const rawErr = errors[repo] || '';
      // errors may be a string or {category, message} object
      const errMsg = typeof rawErr === 'object' && rawErr.message
        ? rawErr.message : String(rawErr);
      const diag = (diagnoses[repo] || []).join('；');
      return `<tr>
        <td class="repo-name">${escapeHtml(repo)}</td>
        <td class="err-msg">${escapeHtml(errMsg)}</td>
        <td class="diag-msg">${escapeHtml(diag)}</td>
      </tr>`;
    }).join('');
    failedSection.innerHTML = `
      <div class="section-title">⚠️ 同步失败仓库（${failedList.length}）</div>
      <div class="table-wrap">
        <table class="fail-table">
          <thead><tr><th>仓库</th><th>错误信息</th><th>诊断结果</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  } else {
    failedSection.innerHTML = '';
  }

  // Synced repos (collapsible)
  const successSection = document.getElementById('success-section');
  if (successList.length > 0) {
    successSection.innerHTML = `
      <details>
        <summary class="section-title" style="cursor:pointer;display:inline-block;">
          ✅ 已同步仓库（${successList.length}）
        </summary>
        <div class="repo-tags">${successList.map(n =>
          `<span class="repo-tag success">${escapeHtml(n)}</span>`
        ).join('')}</div>
      </details>`;
  } else {
    successSection.innerHTML = '';
  }

  // Footer
  const contact = community.contact || 'N/A';
  document.getElementById('footer-info').innerHTML =
    `最后更新：${fmtTime(data.timestamp)}　|　负责人：${escapeHtml(contact)}`;
}

// ── Main ───────────────────────────────────────────────

async function main() {
  const params = new URLSearchParams(window.location.search);
  const orgName = params.get('org');
  if (!orgName) {
    document.getElementById('org-title').textContent = '缺少参数';
    document.getElementById('summary').innerHTML =
      '<div class="error">请通过 ?org=社区名 指定社区，如 <code>?org=openEuler</code></div>';
    return;
  }

  // Fetch orgs.json
  let config;
  try {
    const resp = await fetch(CONFIG_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    config = await resp.json();
  } catch (e) {
    document.getElementById('org-title').textContent = orgName;
    document.getElementById('summary').innerHTML =
      `<div class="error">无法加载社区注册表：${escapeHtml(e.message)}</div>`;
    return;
  }

  const community = (config.repos || []).find(r => r.org === orgName);
  if (!community) {
    document.getElementById('org-title').textContent = orgName;
    document.getElementById('summary').innerHTML =
      '<div class="error">未找到该社区，请检查社区名是否正确</div>';
    return;
  }

  // Fetch results.json
  let data = null;
  try {
    const resp = await fetch(community.results_url, { cache: 'no-cache' });
    if (resp.ok) data = await resp.json();
  } catch (_) { /* render below handles null */ }

  render(community, data);
}

document.addEventListener('DOMContentLoaded', main);
