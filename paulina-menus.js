/**
 * paulina-menus.js — Visor de menús + generador de lista multi-semana
 * Se carga después del script principal de index.html.
 *
 * Dos funcionalidades:
 *   📚  Visor de menús anteriores  → botón FAB inferior
 *   🛒  Generador multi-semana     → botón FAB inferior
 */

const PaulinaMenus = (() => {
  // ── Estado ────────────────────────────────────────────────────────────────
  let _db       = null;
  let _loaded   = false;
  let _selMenu  = null;          // para el viewer
  let _selIds   = new Set();     // para el builder

  const DATA_URL = './data/menus_database.json';

  const CAT_ICONS = {
    'Supermercado': '🏪', 'Carnes': '🥩', 'Dietética': '🥗',
    'Verdulería': '🥬', 'Para la yapa': '⭐',
    'Para el comodín - Opcional': '👑',
    'Seguro ya tengas en casa (a chequear!)': '🏠',
  };
  const CAT_ORDER = [
    'Supermercado','Carnes','Dietética','Verdulería',
    'Para la yapa','Para el comodín - Opcional',
    'Seguro ya tengas en casa (a chequear!)',
  ];

  // ── Carga ─────────────────────────────────────────────────────────────────
  async function load() {
    if (_loaded) return _db;
    try {
      const res = await fetch(DATA_URL + '?v=' + Date.now());
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      _db = await res.json();
      _loaded = true;
      console.log(`[PaulinaMenus] ${_db.total_semanas} menús cargados`);
    } catch (e) {
      console.error('[PaulinaMenus] No se pudo cargar JSON:', e);
    }
    return _db;
  }

  function allMenus() {
    return _db ? [..._db.menus].sort((a,b) => b.semana - a.semana) : [];
  }
  function getMenu(semana) {
    return _db ? _db.menus.find(m => m.semana === semana) : null;
  }

  // ── Lista de compras combinada ─────────────────────────────────────────────
  function buildCombined(semanas, type = 'general') {
    const combined = {};
    const key = type === 'veggie' ? 'veggie' : 'general';
    for (const s of semanas) {
      const menu = getMenu(s);
      if (!menu) continue;
      for (const [cat, items] of Object.entries(menu[key] || {})) {
        if (!combined[cat]) combined[cat] = new Set();
        items.forEach(i => combined[cat].add(i));
      }
    }
    const result = {};
    for (const cat of CAT_ORDER) {
      if (combined[cat]?.size) result[cat] = [...combined[cat]];
    }
    for (const [cat, s] of Object.entries(combined)) {
      if (!result[cat] && s.size) result[cat] = [...s];
    }
    return result;
  }

  // ── Integración con la app existente ──────────────────────────────────────
  /**
   * Convierte la lista combinada al formato interno de la app
   * y crea una nueva semana usando createWeekFromImport() del main script.
   */
  function importToApp(combinedList, semanas, type) {
    // Construir el objeto data que espera createWeekFromImport
    const semanasSorted = [...semanas].sort((a,b) => a-b);
    const fechasList = semanasSorted.map(s => getMenu(s)?.fechas || '').filter(Boolean).join(' + ');
    const tituloStr  = `S${semanasSorted.join('+')}`;

    // Normalizar claves al formato del scraper (con emojis) para que mapCategoryName funcione
    const generalNorm = {};
    for (const [cat, items] of Object.entries(combinedList)) {
      generalNorm[cat] = items;
    }

    // data object compatible con executeImport / createWeekFromImport
    const fakeData = {
      titulo: tituloStr,
      semana: semanasSorted[0] || 0,
      fechas: fechasList,
      general: type === 'general' ? generalNorm : {},
      veggie:  type === 'veggie'  ? generalNorm : {},
    };

    // Inyectar en pendingPaulinaData (global de index.html) y llamar directamente
    if (typeof pendingPaulinaData !== 'undefined' &&
        typeof createWeekFromImport === 'function') {
      // Construir importWrapper directamente (salteamos el modal de días)
      const importWrapper = {};
      if (type === 'general' && Object.keys(generalNorm).length > 0) {
        importWrapper.general = generalNorm;
      } else if (type === 'veggie' && Object.keys(generalNorm).length > 0) {
        importWrapper.veggie = generalNorm;
      }
      // selectedImportMode es global en index.html
      if (typeof selectedImportMode !== 'undefined') {
        window.selectedImportMode = type === 'veggie' ? 'veggie' : 'general';
      }
      createWeekFromImport(fakeData, importWrapper).then(() => {
        _showToast(`✅ Lista ${tituloStr} importada`);
      });
    } else {
      // Fallback: evento custom
      document.dispatchEvent(new CustomEvent('paulina:import', {
        detail: { name: tituloStr, items: combinedList, fechas: fechasList }
      }));
      _showToast(`✅ Lista ${tituloStr} enviada`);
    }
    closeBuilder();
  }

  // ── Toast ─────────────────────────────────────────────────────────────────
  function _showToast(msg) {
    if (typeof showToast === 'function') { showToast(msg, 'success'); return; }
    const t = document.getElementById('toast');
    if (t) { t.textContent = msg; t.classList.add('show');
             setTimeout(() => t.classList.remove('show'), 3000); }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // VISOR DE MENÚS
  // ═══════════════════════════════════════════════════════════════════════════

  function openViewer() {
    _ensureViewer();
    document.getElementById('pm-viewer').style.display = 'flex';
    _renderSidebar();
  }
  function closeViewer() {
    const el = document.getElementById('pm-viewer');
    if (el) el.style.display = 'none';
  }

  function _renderSidebar() {
    const list = document.getElementById('pm-sidebar');
    list.innerHTML = allMenus().map(m => {
      const n = Object.values(m.dias).reduce((a,d) => a+d.length, 0);
      const label = m.semana === 0 ? `⭐ ${m.titulo}` : `Semana ${m.semana}`;
      return `<div class="pm-scard" onclick="PaulinaMenus._pickMenu(${m.semana})" data-s="${m.semana}">
        <b>${label}</b>
        <span>${m.fechas}</span>
        <small>🍽 ${n} recetas</small>
      </div>`;
    }).join('');
  }

  function _pickMenu(semana) {
    _selMenu = getMenu(semana);
    document.querySelectorAll('.pm-scard').forEach(c =>
      c.classList.toggle('pm-active', c.dataset.s == semana));
    _renderDetail();
  }

  function _renderDetail() {
    const el = document.getElementById('pm-detail');
    if (!_selMenu) { el.innerHTML = '<p class="pm-ph">👈 Seleccioná una semana</p>'; return; }
    const m = _selMenu;
    let h = `<div class="pm-dh"><h3>${m.semana > 0 ? `Semana ${m.semana}` : m.titulo}</h3>
             <p>${m.fechas}</p></div>`;
    for (const [dia, recetas] of Object.entries(m.dias)) {
      h += `<div class="pm-dia"><div class="pm-dia-t">${dia}</div>`;
      for (const r of recetas) {
        const tags = [
          r.es_vegetariano ? '<span class="pm-t pm-tv">🌿 Veggie</span>' : '',
          r.es_guarnicion  ? '<span class="pm-t pm-tg">🥗 Guarnición</span>' : '',
          r.preparacion_tiempo ? `<span class="pm-t pm-tt">⏱ ${r.preparacion_tiempo}</span>` : '',
          r.porciones ? `<span class="pm-t pm-tp">👤 ${r.porciones} porciones</span>` : '',
        ].join('');
        const ings = r.ingredientes
          .filter(i => i && !i.endsWith(':') && i.length > 2)
          .map(i => `<li>${i}</li>`).join('');
        const instrs = r.instrucciones
          ? r.instrucciones.split('\n').filter(l=>l.trim()).map(l=>`<p>${l}</p>`).join('')
          : '';
        h += `<div class="pm-rec">
          <div class="pm-rn">${r.nombre}</div>
          <div class="pm-tags">${tags}</div>
          ${ings ? `<details class="pm-acc"><summary>🧂 Ingredientes</summary><ul class="pm-ul">${ings}</ul></details>` : ''}
          ${instrs ? `<details class="pm-acc"><summary>👩‍🍳 Instrucciones</summary><div class="pm-ins">${instrs}</div></details>` : ''}
        </div>`;
      }
      h += '</div>';
    }
    el.innerHTML = h;
    el.scrollTop = 0;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // GENERADOR DE LISTA MULTI-SEMANA
  // ═══════════════════════════════════════════════════════════════════════════

  function openBuilder() {
    _ensureBuilder();
    _selIds.clear();
    document.getElementById('pm-builder').style.display = 'flex';
    _renderBuilderList();
    _renderPreview();
  }
  function closeBuilder() {
    const el = document.getElementById('pm-builder');
    if (el) el.style.display = 'none';
    _selIds.clear();
  }

  function _renderBuilderList() {
    const c = document.getElementById('pm-blist');
    c.innerHTML = allMenus().filter(m => m.semana > 0).map(m => {
      const n = Object.values(m.general || {}).reduce((a,v) => a+v.length, 0);
      return `<label class="pm-bitem" id="pm-bi-${m.semana}"
        onclick="PaulinaMenus._toggleSemana(${m.semana},this)" data-s="${m.semana}">
        <div class="pm-bchk" id="pm-bchk-${m.semana}">☐</div>
        <div class="pm-binfo">
          <b>Semana ${m.semana}</b>
          <span>${m.fechas}</span>
        </div>
        <span class="pm-bcnt">${n} items</span>
      </label>`;
    }).join('');
  }

  function _toggleSemana(s, el) {
    if (_selIds.has(s)) {
      _selIds.delete(s);
      el.classList.remove('pm-bsel');
      document.getElementById(`pm-bchk-${s}`).textContent = '☐';
    } else {
      _selIds.add(s);
      el.classList.add('pm-bsel');
      document.getElementById(`pm-bchk-${s}`).textContent = '☑';
    }
    _renderPreview();
  }

  function _renderPreview() {
    const countEl = document.getElementById('pm-bcount');
    const preview = document.getElementById('pm-prev');
    countEl.textContent = _selIds.size === 0
      ? 'Seleccioná semanas'
      : `${_selIds.size} semana${_selIds.size>1?'s':''} seleccionada${_selIds.size>1?'s':''}`;
    if (_selIds.size === 0) {
      preview.innerHTML = '<p class="pm-ph">La lista combinada aparecerá acá ↑</p>';
      return;
    }
    const type = document.getElementById('pm-btype')?.value || 'general';
    const comb = buildCombined([..._selIds], type);
    let h = '';
    for (const [cat, items] of Object.entries(comb)) {
      const icon = CAT_ICONS[cat] || '📦';
      h += `<div class="pm-pcat">
        <b>${icon} ${cat} <span class="pm-pcnt">(${items.length})</span></b>
        <ul class="pm-ul">${items.map(i=>`<li>${i}</li>`).join('')}</ul>
      </div>`;
    }
    preview.innerHTML = h || '<p class="pm-ph">Sin items para este tipo de lista.</p>';
  }

  function confirmImport() {
    if (!_selIds.size) { _showToast('Seleccioná al menos una semana'); return; }
    const type = document.getElementById('pm-btype')?.value || 'general';
    const comb = buildCombined([..._selIds], type);
    importToApp(comb, _selIds, type);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // DOM: inyectar modales y estilos
  // ═══════════════════════════════════════════════════════════════════════════

  function _ensureViewer() {
    if (document.getElementById('pm-viewer')) return;
    document.body.insertAdjacentHTML('beforeend', `
      <div id="pm-viewer" class="pm-overlay" style="display:none"
           onclick="if(event.target===this)PaulinaMenus.closeViewer()">
        <div class="pm-modal pm-modal-wide">
          <div class="pm-mhdr">
            <span>📚 Menús anteriores</span>
            <button class="pm-x" onclick="PaulinaMenus.closeViewer()">✕</button>
          </div>
          <div class="pm-body pm-viewer-body">
            <div class="pm-sidebar" id="pm-sidebar"></div>
            <div class="pm-detail" id="pm-detail">
              <p class="pm-ph">👈 Seleccioná una semana para ver el menú completo</p>
            </div>
          </div>
        </div>
      </div>`);
  }

  function _ensureBuilder() {
    if (document.getElementById('pm-builder')) return;
    document.body.insertAdjacentHTML('beforeend', `
      <div id="pm-builder" class="pm-overlay" style="display:none"
           onclick="if(event.target===this)PaulinaMenus.closeBuilder()">
        <div class="pm-modal pm-modal-wide">
          <div class="pm-mhdr">
            <span>🛒 Armar lista de compras</span>
            <button class="pm-x" onclick="PaulinaMenus.closeBuilder()">✕</button>
          </div>
          <div class="pm-body pm-builder-body">
            <div class="pm-bleft">
              <p style="font-size:13px;color:#666;margin:0 0 10px">Elegí las semanas a combinar:</p>
              <div id="pm-blist"></div>
            </div>
            <div class="pm-bright">
              <div class="pm-bctrl">
                <span id="pm-bcount" class="pm-bcount-lbl">Seleccioná semanas</span>
                <select id="pm-btype" class="pm-btype-sel" onchange="PaulinaMenus._renderPreview()">
                  <option value="general">🍖 Lista general</option>
                  <option value="veggie">🥬 Lista vegetariana</option>
                </select>
              </div>
              <div class="pm-preview" id="pm-prev">
                <p class="pm-ph">La lista combinada aparecerá acá ↑</p>
              </div>
              <button class="pm-confirm" onclick="PaulinaMenus.confirmImport()">
                ✅ Agregar a mis compras
              </button>
            </div>
          </div>
        </div>
      </div>`);
  }

  function _injectStyles() {
    if (document.getElementById('pm-css')) return;
    const s = document.createElement('style');
    s.id = 'pm-css';
    s.textContent = `
      .pm-overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;
        align-items:center;justify-content:center;z-index:9999;padding:12px;box-sizing:border-box}
      .pm-modal{background:#fff;border-radius:16px;width:100%;max-height:92vh;
        display:flex;flex-direction:column;overflow:hidden;
        box-shadow:0 20px 60px rgba(0,0,0,.3)}
      .pm-modal-wide{max-width:880px}
      .pm-mhdr{display:flex;align-items:center;justify-content:space-between;
        padding:14px 18px;border-bottom:1px solid #eee;font-weight:700;font-size:16px;
        background:#fafafa;flex-shrink:0}
      .pm-x{background:none;border:none;font-size:20px;cursor:pointer;
        color:#888;padding:2px 8px;border-radius:8px}
      .pm-x:hover{background:#eee}
      .pm-body{display:flex;flex:1;overflow:hidden;min-height:0}

      /* Viewer */
      .pm-viewer-body{}
      .pm-sidebar{width:220px;min-width:220px;overflow-y:auto;
        border-right:1px solid #eee;padding:10px 8px;background:#f8f9fa;flex-shrink:0}
      .pm-scard{background:#fff;border-radius:10px;padding:9px 11px;margin-bottom:7px;
        cursor:pointer;border:2px solid transparent;
        box-shadow:0 1px 3px rgba(0,0,0,.08);transition:.15s;display:flex;flex-direction:column;gap:2px}
      .pm-scard b{font-size:13px;color:#222}
      .pm-scard span{font-size:11px;color:#888}
      .pm-scard small{font-size:11px;color:#aaa}
      .pm-scard:hover{border-color:#CF1015;background:#fff5f5}
      .pm-scard.pm-active{border-color:#CF1015;background:#fff0f0}
      .pm-detail{flex:1;overflow-y:auto;padding:14px 18px}
      .pm-ph{color:#bbb;text-align:center;margin-top:40px;font-size:14px}
      .pm-dh h3{margin:0 0 4px;font-size:20px}
      .pm-dh p{color:#888;font-size:13px;margin:0 0 16px}
      .pm-dia{margin-bottom:18px}
      .pm-dia-t{font-weight:800;font-size:12px;text-transform:uppercase;
        color:#CF1015;letter-spacing:.5px;padding-bottom:4px;
        border-bottom:2px solid #fce4e4;margin-bottom:8px}
      .pm-rec{background:#f9f9f9;border-radius:10px;padding:10px 13px;
        margin-bottom:7px;border:1px solid #eee}
      .pm-rn{font-weight:700;font-size:14px;margin-bottom:5px}
      .pm-tags{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:5px}
      .pm-t{font-size:11px;padding:2px 7px;border-radius:20px;font-weight:600}
      .pm-tv{background:#e8f5e9;color:#2e7d32}
      .pm-tg{background:#e3f2fd;color:#1565c0}
      .pm-tt{background:#fff3e0;color:#e65100}
      .pm-tp{background:#f3e5f5;color:#6a1b9a}
      .pm-acc{border:1px solid #e0e0e0;border-radius:8px;margin-top:5px;overflow:hidden;font-size:13px}
      .pm-acc summary{padding:5px 10px;cursor:pointer;font-weight:600;
        background:#f5f5f5;user-select:none}
      .pm-acc summary:hover{background:#eee}
      .pm-ul{margin:0;padding:7px 10px 7px 22px;list-style:disc;line-height:1.7;background:#fff}
      .pm-ins{padding:7px 12px;line-height:1.6;background:#fff}
      .pm-ins p{margin:0 0 5px}

      /* Builder */
      .pm-builder-body{}
      .pm-bleft{width:250px;min-width:250px;border-right:1px solid #eee;
        overflow-y:auto;padding:10px;flex-shrink:0}
      .pm-bitem{display:flex;align-items:center;gap:9px;padding:9px 11px;
        border-radius:10px;cursor:pointer;border:2px solid transparent;
        background:#f8f9fa;margin-bottom:5px;transition:.15s;user-select:none}
      .pm-bitem:hover{background:#fff5f5;border-color:#f8bbd0}
      .pm-bsel{background:#fce4e4!important;border-color:#CF1015!important}
      .pm-bchk{font-size:18px;color:#CF1015;width:20px;text-align:center}
      .pm-binfo{flex:1;display:flex;flex-direction:column;gap:1px}
      .pm-binfo b{font-size:13px}
      .pm-binfo span{font-size:11px;color:#888}
      .pm-bcnt{font-size:11px;color:#bbb;white-space:nowrap}
      .pm-bright{flex:1;display:flex;flex-direction:column;padding:10px 14px;min-width:0}
      .pm-bctrl{display:flex;justify-content:space-between;align-items:center;
        margin-bottom:8px;flex-wrap:wrap;gap:6px}
      .pm-bcount-lbl{font-size:13px;font-weight:600;color:#555}
      .pm-btype-sel{padding:5px 9px;border-radius:8px;border:1px solid #ddd;
        font-size:13px;background:#fff;cursor:pointer}
      .pm-preview{flex:1;overflow-y:auto;border:1px solid #eee;border-radius:10px;
        padding:9px;background:#fafafa;min-height:150px;margin-bottom:10px;font-size:13px}
      .pm-pcat{margin-bottom:10px}
      .pm-pcat b{display:block;margin-bottom:3px;font-size:12px;color:#333}
      .pm-pcnt{font-weight:400;color:#aaa}
      .pm-confirm{background:#CF1015;color:#fff;border:none;padding:11px;
        border-radius:12px;font-size:15px;font-weight:700;cursor:pointer;width:100%}
      .pm-confirm:hover{background:#a00d11}

      /* FABs */
      .pm-fabs{position:fixed;bottom:80px;right:14px;display:flex;
        flex-direction:column;gap:7px;z-index:100}
      .pm-fab{background:#CF1015;color:#fff;border:none;border-radius:24px;
        padding:9px 16px;font-size:13px;font-weight:700;cursor:pointer;
        box-shadow:0 3px 12px rgba(207,16,21,.35);transition:.15s;
        white-space:nowrap;display:flex;align-items:center;gap:5px}
      .pm-fab:hover{background:#a00d11;transform:translateY(-1px)}
      .pm-fab:active{transform:scale(.97)}

      @media(max-width:600px){
        .pm-viewer-body,.pm-builder-body{flex-direction:column}
        .pm-sidebar{width:100%;min-width:unset;max-height:150px;
          border-right:none;border-bottom:1px solid #eee}
        .pm-bleft{width:100%;min-width:unset;border-right:none;
          border-bottom:1px solid #eee;max-height:190px;overflow-y:auto}
      }
    `;
    document.head.appendChild(s);
  }

  function _injectFABs() {
    if (document.getElementById('pm-fabs')) return;
    document.body.insertAdjacentHTML('beforeend', `
      <div id="pm-fabs" class="pm-fabs">
        <button class="pm-fab" onclick="PaulinaMenus.openViewer()">📚 Menús</button>
        <button class="pm-fab" onclick="PaulinaMenus.openBuilder()">🛒 Armar lista</button>
      </div>`);
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  async function init() {
    _injectStyles();
    await load();
    _injectFABs();
  }

  // Esperar a que el DOM esté listo
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // ── API pública ───────────────────────────────────────────────────────────
  return {
    init, load, openViewer, closeViewer, openBuilder, closeBuilder,
    confirmImport, buildCombined,
    // Internos usados por handlers HTML
    _pickMenu, _toggleSemana, _renderPreview,
  };
})();
