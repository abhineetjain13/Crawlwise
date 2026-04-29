from __future__ import annotations

import asyncio
import logging

from app.services.config.runtime_settings import crawler_runtime_settings

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


async def get_page_html(page, *, flatten_shadow: bool = True) -> str:
    if flatten_shadow:
        await flatten_shadow_dom(page)
    retry_budget = max(0, int(crawler_runtime_settings.browser_error_retry_attempts or 0))
    delay_ms = max(0, int(crawler_runtime_settings.browser_error_retry_delay_ms or 0))
    last_exc: Exception | None = None
    for attempt in range(retry_budget + 1):
        try:
            return await page.content()
        except Exception as exc:
            last_exc = exc
            if not _is_retryable_page_content_error(exc):
                raise
            if attempt >= retry_budget:
                fallback_html = await _outer_html_fallback(page)
                if fallback_html.strip():
                    logger.warning(
                        "Recovered page HTML via DOM outerHTML fallback after Page.content failed: %s",
                        exc,
                    )
                    return fallback_html
                raise
            logger.warning(
                "Retrying Page.content after transient browser serialization failure (%s/%s): %s",
                attempt + 1,
                retry_budget + 1,
                exc,
            )
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)
    # Defensive: retry loop above always returns recovered HTML or raises last_exc.
    if last_exc is not None:
        raise last_exc
    return ""


async def flatten_shadow_dom(page) -> None:
    try:
        await page.evaluate(_SHADOW_DOM_FLATTENER_SCRIPT)
    except Exception:
        logger.debug("Shadow DOM flattening failed", exc_info=True)


async def _outer_html_fallback(page) -> str:
    try:
        return str(
            await page.evaluate(
                """() => {
                  const root = document.documentElement;
                  const doctype = document.doctype
                    ? '<!DOCTYPE ' + document.doctype.name + '>'
                    : '';
                  if (root && root.outerHTML) {
                    return doctype + root.outerHTML;
                  }
                  const body = document.body;
                  if (!body || !body.outerHTML) {
                    return "";
                  }
                  return doctype + '<html><head></head>' + body.outerHTML + '</html>';
                }"""
            )
            or ""
        )
    except Exception:
        logger.debug("Page outerHTML fallback failed", exc_info=True)
        return ""


def _is_retryable_page_content_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    class_name = type(exc).__name__.lower()
    return any(
        marker in message
        for marker in (
            "connection closed while reading from the driver",
            "target closed",
            "page closed",
            "browser has been closed",
        )
    ) or "targetclosed" in class_name


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
