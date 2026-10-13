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
