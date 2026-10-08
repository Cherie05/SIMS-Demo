import { useEffect } from 'react';

const STORAGE_KEY = 'sims.shortcuts';

/** Single-key shortcuts can be switched off (WCAG 2.1.4), remembered per browser. */
export function readShortcutsEnabled(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== 'off';
  } catch {
    return true;
  }
}

export function writeShortcutsEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, enabled ? 'on' : 'off');
  } catch {
    // Storage unavailable (private mode): the choice lasts for this page view only.
  }
}

/** Global single-key shortcuts, ignored while typing or while a dialog/menu is open. */
export function useGlobalShortcuts(actions: Record<string, () => void>, enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.repeat || event.ctrlKey || event.metaKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return;
      if (document.querySelector('[role="dialog"], [role="menu"], [role="listbox"]')) return;
      const action = actions[event.key.toLowerCase()] ?? actions[event.key];
      if (action) {
        event.preventDefault();
        action();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [actions, enabled]);
}
