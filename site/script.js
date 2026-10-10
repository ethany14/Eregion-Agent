// Day/Night toggle, operating-system detection for the install steps, and copy buttons.
(() => {
  const root = document.documentElement;
  const prefersLight = matchMedia('(prefers-color-scheme: light)');
  const current = () => root.dataset.theme || (prefersLight.matches ? 'light' : 'dark');

  function syncToggle() {
    const light = current() === 'light';
    document.querySelector('.theme-toggle .night')?.setAttribute('aria-pressed', String(!light));
    document.querySelector('.theme-toggle .day')?.setAttribute('aria-pressed', String(light));
  }
  document.querySelector('.theme-toggle')?.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    const theme = button.classList.contains('day') ? 'light' : 'dark';
    root.dataset.theme = theme;
    try { localStorage.setItem('eregion.site-theme', theme); } catch { /* The choice still applies to this page. */ }
    syncToggle();
  });
  prefersLight.addEventListener?.('change', syncToggle);
  syncToggle();

  // Show the commands for the visitor's system first.
  const platform = (navigator.userAgentData?.platform || navigator.platform || navigator.userAgent).toLowerCase();
  const detected = platform.includes('win') ? 'win' : platform.includes('mac') ? 'mac' : platform.includes('linux') ? 'linux' : null;
  const names = { win: 'Windows', mac: 'macOS', linux: 'Linux' };
  const install = document.getElementById('cmd-install');

  function selectOs(os) {
    for (const tab of document.querySelectorAll('.os-tabs [role="tab"]')) {
      tab.setAttribute('aria-selected', String(tab.dataset.os === os));
      tab.tabIndex = tab.dataset.os === os ? 0 : -1;
    }
    if (install) install.textContent = os === 'win' ? install.dataset.win : install.dataset.unix;
  }
  const tabs = document.querySelector('.os-tabs');
  tabs?.addEventListener('click', event => {
    const tab = event.target.closest('[role="tab"]');
    if (tab) selectOs(tab.dataset.os);
  });
  tabs?.addEventListener('keydown', event => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    const list = [...tabs.querySelectorAll('[role="tab"]')];
    const at = list.findIndex(tab => tab.getAttribute('aria-selected') === 'true');
    const next = list[(at + (event.key === 'ArrowRight' ? 1 : list.length - 1)) % list.length];
    selectOs(next.dataset.os);
    next.focus();
  });
  if (detected) {
    selectOs(detected);
    const osName = document.getElementById('os-name');
    if (osName) osName.textContent = names[detected];
    const heroDownload = document.querySelector('#hero-download span');
    if (heroDownload) heroDownload.textContent = `Download for ${names[detected]}`;
  }

  // Site menu: a slide-out side panel with every page and topic.
  const drawer = document.getElementById('drawer');
  const drawerScrim = document.querySelector('.drawer-scrim');
  const openers = [...document.querySelectorAll('.menu-btn, .side-toggle')];
  const setMenu = open => {
    if (!drawer) return;
    drawer.classList.toggle('open', open);
    drawerScrim.hidden = !open;
    document.body.classList.toggle('menu-open', open);
    for (const button of openers) button.setAttribute('aria-expanded', String(open));
    if (open) drawer.querySelector('.drawer-close')?.focus();
  };
  for (const button of openers) button.addEventListener('click', () => setMenu(!drawer.classList.contains('open')));
  drawerScrim?.addEventListener('click', () => setMenu(false));
  drawer?.querySelector('.drawer-close')?.addEventListener('click', () => setMenu(false));
  drawer?.addEventListener('click', event => { if (event.target.closest('a')) setMenu(false); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') setMenu(false); });

  // Guide and docs: show one topic at a time, chosen from the side panel.
  const article = document.querySelector('.pager');
  const sideLinks = [...document.querySelectorAll('.side a')];
  if (article && sideLinks.length) {
    const page = article.dataset.page;
    const sections = [...article.querySelectorAll(':scope > section')];
    const current = document.querySelector('.side-current');
    const baseTitle = document.title;
    const drawerLinks = [...document.querySelectorAll('.drawer a[data-id]')];

    // Previous / next follow the side panel's order, across both pages.
    sections.forEach(section => {
      const index = sideLinks.findIndex(link => link.dataset.page === page && link.dataset.id === section.id);
      const nav = document.createElement('nav');
      nav.className = 'pager-nav';
      nav.setAttribute('aria-label', 'Previous and next topic');
      for (const [offset, cls, label] of [[-1, 'prev', 'Previous'], [1, 'next', 'Next']]) {
        const target = sideLinks[index + offset];
        if (!target) { nav.append(document.createElement('span')); continue; }
        const a = document.createElement('a');
        a.className = cls;
        a.href = target.dataset.page === page ? `#${target.dataset.id}` : target.getAttribute('href');
        a.innerHTML = `<small>${label}</small><b></b>`;
        a.querySelector('b').textContent = target.textContent;
        nav.append(a);
      }
      section.append(nav);
    });

    function show(id, scroll) {
      const section = sections.find(s => s.id === id) || sections[0];
      for (const s of sections) s.hidden = s !== section;
      for (const link of [...sideLinks, ...drawerLinks]) {
        const on = link.dataset.page === page && link.dataset.id === section.id;
        link.classList.toggle('on', on);
        if (on) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
      }
      const label = sideLinks.find(link => link.classList.contains('on'))?.textContent || '';
      if (current) current.textContent = label;
      document.title = label ? `${label} · ${baseTitle}` : baseTitle;
      setMenu(false);
      if (scroll) window.scrollTo({ top: 0 });
    }
    window.addEventListener('hashchange', () => show(location.hash.slice(1), true));
    article.classList.add('paged');
    show(location.hash.slice(1), false);
    // The browser jumps to the hash target on load; start each topic at the top instead.
    if (location.hash) {
      const top = () => window.scrollTo({ top: 0 });
      requestAnimationFrame(top);
      window.addEventListener('load', () => setTimeout(top, 0), { once: true });
    }
  }

  // Copy buttons fall back to selecting the text when the clipboard is unavailable.
  document.addEventListener('click', async event => {
    const button = event.target.closest('.copy');
    if (!button) return;
    const code = document.getElementById(button.dataset.copy);
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code.textContent);
      button.classList.add('done');
      button.setAttribute('aria-label', 'Copied');
      setTimeout(() => button.classList.remove('done'), 1600);
    } catch {
      const range = document.createRange();
      range.selectNodeContents(code);
      const selection = getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    }
  });
})();
