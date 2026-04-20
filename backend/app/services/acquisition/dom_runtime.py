from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SHADOW_DOM_FLATTENER_SCRIPT = """
() => {
  let flattenedRoots = 0;
  for (const el of document.querySelectorAll('*')) {
    if (!(el instanceof Element) || !el.shadowRoot) {
      continue;
    }
    try {
      const clone = document.createElement('template');
      clone.innerHTML = el.shadowRoot.innerHTML;
      el.appendChild(clone.content.cloneNode(true));
      flattenedRoots += 1;
    } catch (error) {
      continue;
    }
  }
  return flattenedRoots;
}
"""

_MUTATION_SETTLE_SCRIPT = """
({ quietWindowMs, timeoutMs }) => new Promise((resolve) => {
  const root = document.body || document.documentElement;
  if (!root) {
    resolve({ observed: false });
    return;
  }
  let settled = false;
  let quietTimer = null;
  let timeoutTimer = null;
  const finish = (observed) => {
    if (settled) {
      return;
    }
    settled = true;
    if (quietTimer !== null) {
      clearTimeout(quietTimer);
    }
    if (timeoutTimer !== null) {
      clearTimeout(timeoutTimer);
    }
    observer.disconnect();
    resolve({ observed });
  };
  const observer = new MutationObserver(() => {
    if (quietTimer !== null) {
      clearTimeout(quietTimer);
    }
    quietTimer = setTimeout(() => finish(true), quietWindowMs);
  });
  observer.observe(root, {
    attributes: true,
    characterData: true,
    childList: true,
    subtree: true,
  });
  quietTimer = setTimeout(() => finish(false), quietWindowMs);
  timeoutTimer = setTimeout(() => finish(false), timeoutMs);
});
"""


async def get_page_html(page) -> str:
    await flatten_shadow_dom(page)
    return await page.content()


async def flatten_shadow_dom(page) -> None:
    try:
        await page.evaluate(_SHADOW_DOM_FLATTENER_SCRIPT)
    except Exception:
        logger.debug("Shadow DOM flattening failed", exc_info=True)


async def wait_for_dom_mutation_settle(
    page,
    *,
    quiet_window_ms: int,
    timeout_ms: int,
) -> None:
    if quiet_window_ms <= 0 or timeout_ms <= 0:
        return
    try:
        await page.evaluate(
            _MUTATION_SETTLE_SCRIPT,
            {
                "quietWindowMs": int(quiet_window_ms),
                "timeoutMs": int(timeout_ms),
            },
        )
    except Exception:
        logger.debug("DOM mutation settle failed", exc_info=True)
