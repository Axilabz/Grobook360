// Renders the per-role interactive step-by-step flow. Expects a global
// `ROLE` ('OWNER' | 'MANAGER' | 'SALESPERSON') to be set by the page
// before this script runs, and MODULES / hasAnyPermission / hasPermission
// from modules-data.js to already be loaded.

(function () {
  const KIND_LABEL = {
    view: 'View', create: 'Create', edit: 'Edit', approve: 'Approve/Post',
    export: 'Export', delete: 'Cancel/Reverse', special: 'Action',
  };

  const ROLE_LABEL = ROLE.charAt(0) + ROLE.slice(1).toLowerCase();

  function visibleModules() {
    return MODULES
      .map((m) => {
        const steps = m.steps.filter((s) => hasAnyPermission(ROLE, s.permission));
        return { ...m, steps };
      })
      .filter((m) => m.steps.length > 0);
  }

  function accessLevel(mod) {
    const total = mod.steps.length;
    // Recompute against the UNFILTERED original module to know the full step count.
    const original = MODULES.find((m) => m.id === mod.id);
    const allCount = original.steps.length;
    if (mod.steps.length === 0) return { label: 'No Access', cls: 'access-none' };
    if (mod.steps.length === allCount) return { label: 'Full Access', cls: 'access-full' };
    const onlyView = mod.steps.every((s) => s.kind === 'view');
    if (onlyView) return { label: 'View Only', cls: 'access-view' };
    return { label: 'Partial Access', cls: 'access-partial' };
  }

  function groupModules(mods) {
    const groups = {};
    mods.forEach((m) => {
      groups[m.group] = groups[m.group] || [];
      groups[m.group].push(m);
    });
    return groups;
  }

  function storageKey(suffix) {
    return `userflow:${ROLE}:${suffix}`;
  }

  function init() {
    const mods = visibleModules();
    if (mods.length === 0) return;

    const sidebar = document.getElementById('sidebar');
    const main = document.getElementById('main-panel');

    const groups = groupModules(mods);
    const groupOrder = [];
    mods.forEach((m) => { if (!groupOrder.includes(m.group)) groupOrder.push(m.group); });

    let state = {
      moduleId: localStorage.getItem(storageKey('module')) || mods[0].id,
      stepIndex: 0,
    };
    if (!mods.find((m) => m.id === state.moduleId)) state.moduleId = mods[0].id;

    function renderSidebar() {
      sidebar.innerHTML = '';
      groupOrder.forEach((g) => {
        const h = document.createElement('h2');
        h.textContent = g;
        sidebar.appendChild(h);
        groups[g].forEach((m) => {
          const el = document.createElement('div');
          el.className = 'module-link' + (m.id === state.moduleId ? ' active' : '');
          el.innerHTML = `<span class="icon">${m.icon}</span><span>${m.name}</span><span class="count">${m.steps.length}</span>`;
          el.addEventListener('click', () => {
            state.moduleId = m.id;
            state.stepIndex = 0;
            localStorage.setItem(storageKey('module'), m.id);
            renderAll();
          });
          sidebar.appendChild(el);
        });
      });
    }

    function currentModule() {
      return mods.find((m) => m.id === state.moduleId);
    }

    function renderMain() {
      const mod = currentModule();
      const step = mod.steps[state.stepIndex];
      const access = accessLevel(mod);

      main.innerHTML = `
        <div class="module-header">
          <div>
            <div class="group">${mod.group}</div>
            <h2>${mod.icon} ${mod.name}</h2>
          </div>
          <span class="access-pill ${access.cls}">${access.label} for ${ROLE_LABEL}</span>
        </div>
        <div class="progress-track"><div class="progress-fill" style="width:${((state.stepIndex + 1) / mod.steps.length) * 100}%"></div></div>
        <div class="step-dots" id="step-dots"></div>
        <div class="step-card">
          <div class="step-eyebrow">Step ${state.stepIndex + 1} of ${mod.steps.length}</div>
          <h3>${step.title}<span class="kind-badge kind-${step.kind}">${KIND_LABEL[step.kind] || step.kind}</span></h3>
          <div class="screen-path">📍 ${step.screen}</div>
          <div class="step-detail">${step.detail || ''}</div>
          ${step.permission ? `<div class="step-detail" style="margin-top:10px;color:#9ca3af;font-size:12.5px;">Requires permission: <code>${Array.isArray(step.permission) ? step.permission.join(' or ') : step.permission}</code></div>` : ''}
        </div>
        <div class="nav-row">
          <button class="nav-btn" id="prev-btn" ${state.stepIndex === 0 ? 'disabled' : ''}>← Back</button>
          <button class="nav-btn primary" id="next-btn" ${state.stepIndex === mod.steps.length - 1 ? 'disabled' : ''}>Next →</button>
        </div>
      `;

      const dots = document.getElementById('step-dots');
      mod.steps.forEach((s, i) => {
        const d = document.createElement('div');
        d.className = 'step-dot' + (i === state.stepIndex ? ' current' : i < state.stepIndex ? ' done' : '');
        d.textContent = i + 1;
        d.title = s.title;
        d.addEventListener('click', () => { state.stepIndex = i; renderMain(); });
        dots.appendChild(d);
      });

      document.getElementById('prev-btn').addEventListener('click', () => {
        if (state.stepIndex > 0) { state.stepIndex -= 1; renderMain(); }
      });
      document.getElementById('next-btn').addEventListener('click', () => {
        if (state.stepIndex < mod.steps.length - 1) { state.stepIndex += 1; renderMain(); }
      });
    }

    function renderAll() {
      renderSidebar();
      renderMain();
    }

    renderAll();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
