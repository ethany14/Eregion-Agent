// Day / Night theme. An explicit choice is remembered on this device; until then
// the page follows the system setting. The <head> script applies a saved choice
// before first paint, so this module only keeps toggles and storage in sync.
const KEY='eregion.theme';
const prefersLight=matchMedia('(prefers-color-scheme: light)');

export function currentTheme(){
  const chosen=document.documentElement.dataset.theme;
  return chosen==='light'||chosen==='night'?chosen:prefersLight.matches?'light':'night';
}

export function syncThemeToggles(root=document){
  const light=currentTheme()==='light';
  for(const toggle of root.querySelectorAll('.theme-toggle')){
    toggle.dataset.state=light?'light':'night';
    toggle.querySelector('.night')?.setAttribute('aria-pressed',String(!light));
    toggle.querySelector('.day')?.setAttribute('aria-pressed',String(light));
  }
}

export function setTheme(theme){
  document.documentElement.dataset.theme=theme;
  try{localStorage.setItem(KEY,theme);}catch{/* The choice still applies to this page. */}
  syncThemeToggles();
}

export function initTheme(){
  document.addEventListener('click',event=>{
    const button=event.target.closest('.theme-toggle button');
    if(button)setTheme(button.classList.contains('day')?'light':'night');
  });
  prefersLight.addEventListener('change',()=>syncThemeToggles());
  syncThemeToggles();
}
