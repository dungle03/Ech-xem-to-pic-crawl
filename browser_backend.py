"""Selectable browser launchers for the crawler evaluation branch."""

import os
import platform
from urllib.parse import unquote, urlsplit

from camoufox.addons import DefaultAddons
from camoufox.sync_api import Camoufox
from cloakbrowser import launch as cloak_launch


class BrowserHandle:
    """Present one closeable Browser interface for both launcher styles."""

    def __init__(self, browser, manager=None):
        self._browser = browser
        self._manager = manager

    def new_context(self, **kwargs):
        return self._browser.new_context(**kwargs)

    def close(self):
        if self._manager is not None:
            self._manager.__exit__(None, None, None)
            self._manager = None
        else:
            self._browser.close()


def playwright_proxy(proxy_url):
    """Convert an authenticated proxy URL to Playwright's mapping."""
    if not proxy_url:
        return None
    parsed = urlsplit(proxy_url)
    if not parsed.scheme or not parsed.hostname or not parsed.port:
        raise ValueError("Proxy must use scheme://[user:pass@]host:port")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    server = f"{parsed.scheme}://{host}:{parsed.port}"
    result = {"server": server}
    if parsed.username is not None:
        result["username"] = unquote(parsed.username)
    if parsed.password is not None:
        result["password"] = unquote(parsed.password)
    return result


def _camoufox_os():
    """Map the host OS to Camoufox's identity labels."""
    return {"Darwin": "macos", "Windows": "windows"}.get(platform.system(), "linux")


def launch_browser(backend, *, headless=False, proxy=None, fingerprint_seed=None):
    """Launch the requested Playwright-compatible browser backend."""
    if backend == "camoufox":
        options = {
            "headless": headless,
            "humanize": True,
            "os": _camoufox_os(),
            # The crawler loads final pages over HTTP; omit default extension
            # downloads to avoid a separate cold-start network dependency.
            "exclude_addons": [DefaultAddons.UBO],
        }
        executable_path = os.environ.get("CAMOUFOX_EXECUTABLE_PATH", "").strip()
        if executable_path:
            options["executable_path"] = executable_path
        proxy_config = playwright_proxy(proxy)
        if proxy_config:
            options["proxy"] = proxy_config
            if os.environ.get("CAMOUFOX_GEOIP", "").strip().lower() in {"1", "true", "yes", "on"}:
                options["geoip"] = True
        elif os.environ.get("CAMOUFOX_GEOIP", "").strip().lower() in {"1", "true", "yes", "on"}:
            options["geoip"] = True
        manager = Camoufox(**options)
        browser = manager.__enter__()
        return BrowserHandle(browser, manager=manager)

    if backend == "cloakbrowser":
        browser = cloak_launch(
            headless=headless,
            humanize=True,
            stealth_args=False,
            proxy=proxy,
            args=[
                "--no-sandbox",
                f"--fingerprint={fingerprint_seed}",
                "--fingerprint-platform=macos",
                "--disable-dev-shm-usage",
            ],
        )
        return BrowserHandle(browser)

    raise ValueError(f"Unsupported browser backend: {backend}")
