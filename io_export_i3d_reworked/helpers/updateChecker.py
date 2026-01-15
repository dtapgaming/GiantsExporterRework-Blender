# --------------------------------------------------------------
# Update Checker (Legacy Add-on)
# - Respects Blender "Allow Online Access" (bpy.app.online_access)
# - Opt-in via Add-on Preferences
# - Non-blocking (threaded fetch + main-thread popup)
# --------------------------------------------------------------

import bpy
import json
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
import importlib
import os
import tempfile




def _log(msg: str):
    try:
        print(msg)
    except Exception:
        pass

# Session-only state
_I3D_UPDATE_CHECKED_THIS_SESSION = False
_I3D_UPDATE_THREAD = None
_I3D_UPDATE_RESULT = None
_I3D_UPDATE_OFFER = None
_I3D_UPDATE_ERROR = None
# Manual-check flag (used to show "No updates" or error dialogs when the user clicks "Check Now")
_I3D_LAST_CHECK_WAS_MANUAL = False




# Persistent "Checking for updates..." status text (session-only state)
_I3D_UPDATE_STATUS_ACTIVE = False
_I3D_UPDATE_STATUS_START_TIME = 0.0
_I3D_UPDATE_STATUS_TIMEOUT_SECONDS = 30.0
_I3D_UPDATE_STATUS_TIMER_RUNNING = False
_I3D_UPDATE_STATUS_WAS_MANUAL = False
_I3D_UPDATE_STATUS_MESSAGE = "Checking for updates..."

# Each update check gets a monotonically increasing ID so we can ignore late/stale thread results
# (e.g. after a 30s UI timeout, since Python threads can't be force-killed safely).
_I3D_UPDATE_NEXT_CHECK_ID = 0
_I3D_UPDATE_ACTIVE_CHECK_ID = 0
_I3D_UPDATE_ERROR_CHECK_ID = 0




# --------------------------------------------------------------
# ALPHA <-> BETA Channel Switch (forced install prompt)
# --------------------------------------------------------------
# This flow is separate from normal update checks because ALPHA and BETA may share the same
# semantic version while still being different builds. When the user switches between ALPHA and BETA,
# we fetch the selected channel's manifest entry and force an explicit install decision.

_I3D_CHANNEL_SWITCH_INTERNAL_SET = False

# When True, the Add-on Preferences Update Checker UI should be temporarily
# disabled (greyed out) while we gather build information ...
_I3D_CHANNEL_SWITCH_IN_PROGRESS = False
_I3D_CHANNEL_SWITCH_START_TIME = 0.0
_I3D_CHANNEL_SWITCH_TIMEOUT_SECONDS = 30.0


def is_channel_switch_in_progress():
    """Return True while we are gathering manifest info for an ALPHA<->BETA switch."""
    return bool(_I3D_CHANNEL_SWITCH_IN_PROGRESS)


def _channel_switch_promote_result_if_ready():
    """If the channel-switch worker thread has finished, promote its result/error into the offer dict.

    This makes the Preferences UI resilient even if Blender timers fail to run in some contexts.
    """
    global _I3D_CHANNEL_SWITCH_THREAD, _I3D_CHANNEL_SWITCH_RESULT, _I3D_CHANNEL_SWITCH_OFFER, _I3D_CHANNEL_SWITCH_ERROR
    global _I3D_UPDATE_STATUS_ACTIVE
    try:
        if not bool(_I3D_CHANNEL_SWITCH_IN_PROGRESS):
            return
        t = _I3D_CHANNEL_SWITCH_THREAD
        if t is None:
            return
        # Only promote once the worker is done.
        # NOTE: In some Blender contexts, timers may not run reliably. This function
        # provides a fallback path so the Preferences UI can still progress.
        try:
            if t.is_alive():
                # Fallback timeout guard: if the thread takes too long, unstick the UI
                # by surfacing an error that allows the user to revert.
                try:
                    elapsed = time.time() - float(_I3D_CHANNEL_SWITCH_START_TIME or 0.0)
                except Exception:
                    elapsed = 0.0

                if elapsed >= float(_I3D_CHANNEL_SWITCH_TIMEOUT_SECONDS or 30.0):
                    try:
                        _I3D_UPDATE_STATUS_ACTIVE = False
                        _clear_update_status_text()
                    except Exception:
                        pass

                    try:
                        offer = dict(_I3D_CHANNEL_SWITCH_OFFER or {})
                    except Exception:
                        offer = {}

                    msg = "Timed out while gathering build information (30s)."
                    offer["error"] = msg
                    _I3D_CHANNEL_SWITCH_OFFER = offer
                    _I3D_CHANNEL_SWITCH_ERROR = msg

                    # Detach the thread reference so we don't stay stuck in the wait UI.
                    _I3D_CHANNEL_SWITCH_THREAD = None

                    try:
                        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
                    except Exception:
                        pass
                return
        except Exception:
            return

        # Stop any persistent "please wait" banner once we have a final outcome.
        try:
            _I3D_UPDATE_STATUS_ACTIVE = False
            _clear_update_status_text()
        except Exception:
            pass

        # Success: stash the full result for the UI to render.
        if _I3D_CHANNEL_SWITCH_RESULT:
            try:
                _I3D_CHANNEL_SWITCH_OFFER = dict(_I3D_CHANNEL_SWITCH_RESULT)
            except Exception:
                _I3D_CHANNEL_SWITCH_OFFER = _I3D_CHANNEL_SWITCH_RESULT
            _I3D_CHANNEL_SWITCH_RESULT = None
            _I3D_CHANNEL_SWITCH_ERROR = None
            _I3D_CHANNEL_SWITCH_THREAD = None

            # Force a redraw so the Preferences UI can show the Commit/Cancel section
            # without requiring mouse movement.
            try:
                bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
            except Exception:
                pass
            return

        # Error: attach error text to offer so the UI can render a revert button.
        if _I3D_CHANNEL_SWITCH_ERROR:
            try:
                offer = dict(_I3D_CHANNEL_SWITCH_OFFER or {})
            except Exception:
                offer = {}
            offer["error"] = str(_I3D_CHANNEL_SWITCH_ERROR)
            _I3D_CHANNEL_SWITCH_OFFER = offer
            _I3D_CHANNEL_SWITCH_THREAD = None

            try:
                bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
            except Exception:
                pass
            return
    except Exception:
        return

def get_channel_switch_offer():
    """Return the current ALPHA<->BETA channel-switch offer dict (runtime only)."""
    _channel_switch_promote_result_if_ready()
    _ensure_channel_switch_poll_timer()
    try:
        return dict(_I3D_CHANNEL_SWITCH_OFFER or {})
    except Exception:
        return {}

def get_channel_switch_error():
    """Return a channel-switch error string, if any (runtime only)."""
    _channel_switch_promote_result_if_ready()
    _ensure_channel_switch_poll_timer()
    try:
        if _I3D_CHANNEL_SWITCH_ERROR:
            return str(_I3D_CHANNEL_SWITCH_ERROR)
        offer = _I3D_CHANNEL_SWITCH_OFFER or {}
        if isinstance(offer, dict) and offer.get("error"):
            return str(offer.get("error"))
        return ""
    except Exception:
        return ""

def is_channel_switch_ready():
    """Return True when manifest info has been gathered and commit/cancel can be shown."""
    try:
        _channel_switch_promote_result_if_ready()
        _ensure_channel_switch_poll_timer()
        if not bool(_I3D_CHANNEL_SWITCH_IN_PROGRESS):
            return False
        if _I3D_CHANNEL_SWITCH_THREAD is not None and _I3D_CHANNEL_SWITCH_THREAD.is_alive():
            return False
        offer = _I3D_CHANNEL_SWITCH_OFFER or {}
        # Consider it "ready" once we have any meaningful manifest payload (or an error).
        if isinstance(offer, dict):
            if offer.get("remote_version") is not None:
                return True
            if offer.get("download_primary") or offer.get("download_secondary"):
                return True
            if offer.get("notes") or offer.get("notes_url"):
                return True
            if offer.get("error"):
                return True
        return False
    except Exception:
        return False


_I3D_CHANNEL_SWITCH_THREAD = None
_I3D_CHANNEL_SWITCH_RESULT = None
_I3D_CHANNEL_SWITCH_OFFER = None
_I3D_CHANNEL_SWITCH_ERROR = None
_I3D_CHANNEL_SWITCH_OVERRIDE = None  # context override captured from the dropdown change

# Channel-switch dialog invoke retry (main-thread timer)
_I3D_CHANNEL_SWITCH_DIALOG_PENDING = False
_I3D_CHANNEL_SWITCH_DIALOG_START_TIME = 0.0
_I3D_CHANNEL_SWITCH_DIALOG_TIMEOUT_SECONDS = 8.0  # how long to keep retrying UI invoke after fetch completes


_I3D_CHANNEL_SWITCH_NEXT_CHECK_ID = 0
_I3D_CHANNEL_SWITCH_ACTIVE_CHECK_ID = 0
_I3D_CHANNEL_SWITCH_ERROR_CHECK_ID = 0




# Channel-switch poll timer guard: ensures we always have a running main-thread timer
# to promote worker results into the Preferences UI (Commit/Cancel section).
_I3D_CHANNEL_SWITCH_POLL_TIMER_RUNNING = False

def _ensure_channel_switch_poll_timer():
    """Ensure the channel-switch polling timer is running while a switch is in progress.

    Some Blender contexts (notably enum update callbacks) can fail to register timers.
    This helper is safe to call from the Preferences UI draw path; it is idempotent.
    """
    global _I3D_CHANNEL_SWITCH_POLL_TIMER_RUNNING
    try:
        if _I3D_CHANNEL_SWITCH_POLL_TIMER_RUNNING:
            return
        if not bool(_I3D_CHANNEL_SWITCH_IN_PROGRESS):
            return
        t = _I3D_CHANNEL_SWITCH_THREAD
        if t is None:
            return
    except Exception:
        return

    _I3D_CHANNEL_SWITCH_POLL_TIMER_RUNNING = True
    try:
        bpy.app.timers.register(_poll_channel_switch_result_timer, first_interval=0.25)
    except Exception:
        _I3D_CHANNEL_SWITCH_POLL_TIMER_RUNNING = False

def _set_update_channel_internal(prefs_obj, channel_value):
    """Set prefs.update_channel without triggering the ALPHA<->BETA prompt."""
    global _I3D_CHANNEL_SWITCH_INTERNAL_SET
    _I3D_CHANNEL_SWITCH_INTERNAL_SET = True
    try:
        prefs_obj.update_channel = str(channel_value or "STABLE").upper()
    finally:
        _I3D_CHANNEL_SWITCH_INTERNAL_SET = False

def _set_workspace_status_text(text):
    try:
        ws = bpy.context.workspace
        ws.status_text_set(text)
        return True
    except Exception:
        return False


def _clear_update_status_text():
    global _I3D_UPDATE_STATUS_ACTIVE, _I3D_UPDATE_STATUS_TIMER_RUNNING, _I3D_UPDATE_STATUS_WAS_MANUAL

    _I3D_UPDATE_STATUS_ACTIVE = False
    _I3D_UPDATE_STATUS_WAS_MANUAL = False

    try:
        ws = bpy.context.workspace
        ws.status_text_set(None)
    except Exception:
        pass


def _begin_update_status_text(is_manual, message=None):
    global _I3D_UPDATE_STATUS_ACTIVE, _I3D_UPDATE_STATUS_START_TIME, _I3D_UPDATE_STATUS_WAS_MANUAL
    global _I3D_UPDATE_STATUS_MESSAGE

    _I3D_UPDATE_STATUS_ACTIVE = True
    _I3D_UPDATE_STATUS_START_TIME = time.time()
    _I3D_UPDATE_STATUS_WAS_MANUAL = bool(is_manual)

    if message is None:
        message = "Checking for updates..."
    _I3D_UPDATE_STATUS_MESSAGE = str(message)

    _set_workspace_status_text(_I3D_UPDATE_STATUS_MESSAGE)
    _ensure_update_status_timer()


def _ensure_update_status_timer():
    global _I3D_UPDATE_STATUS_TIMER_RUNNING

    if _I3D_UPDATE_STATUS_TIMER_RUNNING:
        return

    _I3D_UPDATE_STATUS_TIMER_RUNNING = True
    try:
        bpy.app.timers.register(_update_status_text_timer, first_interval=0.25)
    except Exception:
        _I3D_UPDATE_STATUS_TIMER_RUNNING = False


def _update_status_text_timer():
    global _I3D_UPDATE_STATUS_TIMER_RUNNING, _I3D_UPDATE_ACTIVE_CHECK_ID, _I3D_LAST_CHECK_WAS_MANUAL

    if not _I3D_UPDATE_STATUS_ACTIVE:
        _I3D_UPDATE_STATUS_TIMER_RUNNING = False
        return None

    # If the update check finished, stop and clear (the poll timer will handle dialogs).
    if _I3D_UPDATE_THREAD is None or (_I3D_UPDATE_THREAD is not None and not _I3D_UPDATE_THREAD.is_alive()):
        _clear_update_status_text()
        _I3D_UPDATE_STATUS_TIMER_RUNNING = False
        return None

    elapsed = time.time() - float(_I3D_UPDATE_STATUS_START_TIME or 0.0)
    if elapsed >= float(_I3D_UPDATE_STATUS_TIMEOUT_SECONDS):
        # UI timeout: stop the banner so Blender doesn't feel "stuck" forever.
        _clear_update_status_text()
        _I3D_UPDATE_STATUS_TIMER_RUNNING = False

        # For MANUAL checks only: show a visible result so it never feels like "nothing happened".
        if _I3D_LAST_CHECK_WAS_MANUAL or _I3D_UPDATE_STATUS_WAS_MANUAL:
            title = "Update Check"
            msg = "Update check timed out (30s). Please try again."
            _invoke_op('i3d.update_check_info_dialog', title=title, message=msg)
            _I3D_LAST_CHECK_WAS_MANUAL = False

        # Ignore late results from this check (we can't kill Python threads safely).
        _I3D_UPDATE_ACTIVE_CHECK_ID = -1
        return None

    # Keep the status text alive.
    _set_workspace_status_text("Checking for updates...")
    return 1.0


# Update dialog flashing (session-only state)
_I3D_UPDATE_DIALOG_ACTIVE = False
_I3D_UPDATE_DIALOG_CLOSE_REQUEST = False
_I3D_UPDATE_DIALOG_FLASH_STATE = False
_I3D_UPDATE_DIALOG_FLASH_INTERVAL = 0.20
_I3D_UPDATE_DIALOG_TIMER_RUNNING = False


def _update_dialog_flash_timer():
    """Timer callback used to drive flashing UI elements in the Update dialog.

    Using a timer avoids the flash changing only when Blender happens to redraw
    (e.g. when the mouse moves over the dialog).
    """
    global _I3D_UPDATE_DIALOG_ACTIVE, _I3D_UPDATE_DIALOG_FLASH_STATE, _I3D_UPDATE_DIALOG_TIMER_RUNNING

    if not _I3D_UPDATE_DIALOG_ACTIVE:
        _I3D_UPDATE_DIALOG_TIMER_RUNNING = False
        return None

    _I3D_UPDATE_DIALOG_FLASH_STATE = not bool(_I3D_UPDATE_DIALOG_FLASH_STATE)

    # Force a redraw so the dialog updates even if the mouse is still.
    try:
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    except Exception:
        pass

    return float(_I3D_UPDATE_DIALOG_FLASH_INTERVAL)


def _ensure_update_dialog_flash_timer():
    """Start the flashing timer once (per dialog lifetime)."""
    global _I3D_UPDATE_DIALOG_TIMER_RUNNING

    if _I3D_UPDATE_DIALOG_TIMER_RUNNING:
        return

    _I3D_UPDATE_DIALOG_TIMER_RUNNING = True
    try:
        bpy.app.timers.register(_update_dialog_flash_timer, first_interval=float(_I3D_UPDATE_DIALOG_FLASH_INTERVAL))
    except Exception:
        _I3D_UPDATE_DIALOG_TIMER_RUNNING = False


def _stop_all_update_timers_best_effort():
    """Unregister timers started by updateChecker.

    This prevents stale callbacks from firing while the add-on is being reinstalled in-place.
    """
    for _fn in (
        _update_dialog_flash_timer,
        _poll_update_result_timer,
        _poll_channel_switch_result_timer,
        _update_status_text_timer,
        _startup_timer,
    ):
        try:
            if hasattr(bpy.app.timers, 'is_registered') and bpy.app.timers.is_registered(_fn):
                bpy.app.timers.unregister(_fn)
        except Exception:
            pass





def _sanitize_url(url: str) -> str:
    """Best-effort cleanup for hosting/redirect quirks.

    IONOS "Instant Domain" forwarding has been observed to append "/defaultsite"
    to the destination URL, sometimes even inside query parameter values.
    This helper removes common variants so the add-on can still open/download.
    """
    if not url or not isinstance(url, str):
        return url

    u = url.strip()

    # Fast path: strip a literal trailing suffix.
    if u.endswith('/defaultsite'):
        u = u[:-len('/defaultsite')]

    # Also strip URL-encoded variant at the end.
    if u.endswith('%2Fdefaultsite') or u.endswith('%2fdefaultsite'):
        u = u[:-len('%2Fdefaultsite')]

    # Parse and clean query parameter values (e.g. id=<fileid>/defaultsite)
    try:
        parts = urllib.parse.urlsplit(u)

        # Clean path too, in case it was appended there.
        path = parts.path or ''
        if path.endswith('/defaultsite'):
            path = path[:-len('/defaultsite')]

        q = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        cleaned = []
        for k, v in q:
            if isinstance(v, str):
                if v.endswith('/defaultsite'):
                    v = v[:-len('/defaultsite')]
                if v.endswith('%2Fdefaultsite') or v.endswith('%2fdefaultsite'):
                    v = v[:-len('%2Fdefaultsite')]
            cleaned.append((k, v))
        query = urllib.parse.urlencode(cleaned, doseq=True)

        u = urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))
    except Exception:
        # If parsing fails, fall back to simple replacements.
        u = u.replace('/defaultsite', '')
        u = u.replace('%2Fdefaultsite', '').replace('%2fdefaultsite', '')

    return u


def _with_cache_buster(url: str) -> str:
    """Append a cache-busting query param to avoid stale CDN/proxy responses.

    This is critical for build-only bumps (e.g. 10.0.17.3 -> 10.0.17.4) where
    aggressive HTTP caching can otherwise cause the add-on to keep seeing the old
    manifest and incorrectly assume the user is still on the skipped build.
    """
    if not url or not isinstance(url, str):
        return url
    try:
        parts = urllib.parse.urlsplit(url)
        q = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        # Remove any previous cache-busters so the URL doesn't grow forever.
        q = [(k, v) for (k, v) in q if str(k).lower() not in ('nocache', 'cachebust', '_', 't', 'ts')]
        q.append(('nocache', str(int(time.time() * 1000))))
        query = urllib.parse.urlencode(q, doseq=True)
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    except Exception:
        sep = '&' if '?' in url else '?'
        return f"{url}{sep}nocache={int(time.time() * 1000)}"



def _get_addon_module():
    try:
        return importlib.import_module("io_export_i3d_reworked")
    except Exception:
        return None


def _get_local_version_tuple():
    mod = _get_addon_module()
    if mod and hasattr(mod, "bl_info"):
        v = mod.bl_info.get("version", (0, 0, 0))
        if isinstance(v, (list, tuple)) and len(v) >= 3:
            return (int(v[0]), int(v[1]), int(v[2]))
    return (0, 0, 0)


def _get_local_build_int():
    mod = _get_addon_module()
    try:
        b = getattr(mod, "I3D_REWORKED_BUILD", 0) if mod else 0
        return int(b)
    except Exception:
        return 0


def _parse_build_int(v):
    try:
        if v is None:
            return 0
        return int(v)
    except Exception:
        return 0


def _version_build_key(v_tuple, build_int):
    try:
        if v_tuple is None:
            v_tuple = (0, 0, 0)
        return (int(v_tuple[0]), int(v_tuple[1]), int(v_tuple[2]), int(build_int or 0))
    except Exception:
        try:
            return (0, 0, 0, int(build_int or 0))
        except Exception:
            return (0, 0, 0, 0)



def _get_addon_display_name():
    # Best-effort: read bl_info['name'] from the add-on module.
    try:
        import importlib
        mod = importlib.import_module("io_export_i3d_reworked")
        bl = getattr(mod, "bl_info", None)
        if isinstance(bl, dict):
            return bl.get("name") or "io_export_i3d_reworked"
    except Exception:
        pass
    return "io_export_i3d_reworked"

def _get_addon_prefs():
    addon = bpy.context.preferences.addons.get("io_export_i3d_reworked")
    if addon is None:
        return None
    return getattr(addon, "preferences", None)


def _set_last_update_action(prefs, message: str):
    """Store a short, user-facing summary of the last update action (persistent)."""
    try:
        if prefs is None:
            return
        prefs.update_last_action = str(message or "")
        try:
            prefs.update_last_action_ts = int(time.time())
        except Exception:
            prefs.update_last_action_ts = 0
    except Exception:
        pass


def set_last_update_action(message: str):
    """Public helper to store last update action summary into add-on preferences."""
    try:
        prefs = _get_addon_prefs()
        _set_last_update_action(prefs, message)
        return True
    except Exception:
        return False


def _online_access_allowed():
    # Blender 4.2+ provides bpy.app.online_access (read-only).
    # If missing, assume allowed (older builds).
    try:
        return bool(getattr(bpy.app, "online_access", True))
    except Exception:
        return True


def _parse_version_tuple(v):
    # Accept [x,y,z] or "x.y.z"
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        return (int(v[0]), int(v[1]), int(v[2]))
    if isinstance(v, str):
        parts = [p.strip() for p in v.split(".") if p.strip() != ""]
        if len(parts) >= 3:
            return (int(parts[0]), int(parts[1]), int(parts[2]))
    return None


def _channel_key_from_pref(channel_pref):
    # stored as enum identifiers
    if channel_pref == "ALPHA":
        return "alpha"
    if channel_pref == "BETA":
        return "beta"
    return "stable"


def _fetch_manifest_json(url, timeout_seconds=3.0):
    # Try the URL exactly as configured first to avoid breaking strict hosts.
    # Then try a sanitized variant (IONOS /defaultsite quirk), and finally (best-effort)
    # try a cache-busted URL *only if* the host accepts query params. Any cache-bust
    # failure is swallowed when we already have a valid response.
    base_url = (url or "").strip()

    def _do_fetch(u: str):
        req = urllib.request.Request(
            u,
            headers={
                "User-Agent": f"DTAP-I3D-Exporter/{_get_local_version_tuple()[0]}.{_get_local_version_tuple()[1]}.{_get_local_version_tuple()[2]}",
                "Accept": "application/json",
                "Cache-Control": "no-cache, no-store, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            }
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read()
        return json.loads(raw.decode("utf-8"))

    last_err = None

    # 1) Original URL
    if base_url:
        try:
            data = _do_fetch(base_url)
        except Exception as e:
            last_err = e
            data = None
    else:
        data = None

    # 2) Sanitized URL (only if different)
    if data is None:
        try:
            s_url = _sanitize_url(base_url)
            if s_url and s_url != base_url:
                data = _do_fetch(s_url)
            elif base_url:
                # If sanitize didn't change anything, rethrow the original error.
                raise last_err if last_err is not None else RuntimeError("Empty manifest URL")
        except Exception as e:
            last_err = e
            data = None

    if data is None:
        # Nothing worked.
        if last_err is not None:
            raise last_err
        raise RuntimeError("Update manifest fetch failed")

    # 3) Best-effort cache-bust re-fetch (swallow failures)
    try:
        s_url = _sanitize_url(base_url)
        bust_url = _with_cache_buster(s_url if s_url else base_url)
        if bust_url and bust_url != (s_url if s_url else base_url):
            data2 = _do_fetch(bust_url)
            # Prefer newer/different data if the host returned it.
            if isinstance(data2, dict) and data2 != data:
                return data2
    except Exception:
        pass

    return data


def _fetch_manifest_json_with_fallback(url_primary, url_fallback, timeout_seconds=3.0):
    # Try primary URL first, then fallback URL (if provided).
    last_err = None

    if url_primary:
        try:
            return _fetch_manifest_json(url_primary, timeout_seconds=timeout_seconds)
        except Exception as e:
            last_err = e

    if url_fallback:
        try:
            return _fetch_manifest_json(url_fallback, timeout_seconds=timeout_seconds)
        except Exception as e:
            last_err = e

    if last_err is not None:
        raise last_err
    raise RuntimeError("No manifest URL configured")



def _update_thread_main(manifest_url_primary, channel_key, check_id):
    global _I3D_UPDATE_RESULT, _I3D_UPDATE_ERROR

    try:
        data = _fetch_manifest_json(manifest_url_primary, timeout_seconds=3.0)

        channels = data.get("channels", {})
        ch = channels.get(channel_key)
        if ch is None:
            raise ValueError(f"Manifest missing channel '{channel_key}'")

        remote_v = _parse_version_tuple(ch.get("version"))
        if remote_v is None:
            raise ValueError("Manifest channel has invalid 'version'")

        local_v = _get_local_version_tuple()

        remote_build = _parse_build_int(ch.get("build"))
        local_build = _get_local_build_int()

        # optional: blender minimum
        blender_min = _parse_version_tuple(ch.get("min_blender")) if ch.get("min_blender") is not None else None

        download_primary = None
        download_secondary = None
        dl = ch.get("download", {})
        if isinstance(dl, dict):
            download_primary = dl.get("primary")
            download_secondary = dl.get("secondary")
        else:
            download_primary = ch.get("download_url")  # legacy/simple manifest support

        notes_url = ch.get("notes_url")
        message = ch.get("message")
        notes = ch.get("notes")
        if notes is None:
            notes = ch.get("notes_text")

        _I3D_UPDATE_RESULT = {
            "_check_id": int(check_id),
            "channel": channel_key,
            "local_version": local_v,
            "local_build": local_build,
            "remote_version": remote_v,
            "remote_build": remote_build,
            "min_blender": blender_min,
            "download_primary": download_primary,
            "download_secondary": download_secondary,
            "notes_url": notes_url,
            "notes": notes,
            "message": message,
        }
        _I3D_UPDATE_ERROR = None

    except Exception as e:
        _I3D_UPDATE_RESULT = None
        _I3D_UPDATE_ERROR = str(e)
        global _I3D_UPDATE_ERROR_CHECK_ID
        _I3D_UPDATE_ERROR_CHECK_ID = int(check_id)
        try:
            mod = importlib.import_module("io_export_i3d_reworked")
            name = getattr(mod, "bl_info", {}).get("name", "io_export_i3d_reworked")
        except Exception:
            name = "io_export_i3d_reworked"
        print(f"{name} Failed to check for updates")

def _format_version(v):
    try:
        return f"{int(v[0])}.{int(v[1])}.{int(v[2])}"
    except Exception:
        return "0.0.0"

def _format_version_build(v, b):
    try:
        return f"{int(v[0])}.{int(v[1])}.{int(v[2])}.{int(b or 0)}"
    except Exception:
        try:
            return f"{_format_version(v)}.{int(b or 0)}"
        except Exception:
            return "0.0.0.0"




class I3D_OT_UpdateCheckInfoDialog(bpy.types.Operator):
    bl_idname = "i3d.update_check_info_dialog"
    bl_label = "Update Check"
    bl_description = "Update Check."
    bl_options = {'INTERNAL'}

    title: bpy.props.StringProperty(default="Update Check")
    message: bpy.props.StringProperty(default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text=self.title, icon='INFO')
        if self.message:
            for line in self.message.split("\n"):
                box.label(text=line)

    def execute(self, context):
        return {'FINISHED'}

class I3D_OT_OpenURL(bpy.types.Operator):
    bl_idname = "i3d.open_url"
    bl_label = "Open URL"
    bl_description = "Open URL: opens the related window or resource."
    bl_options = {'INTERNAL'}

    url: bpy.props.StringProperty(default="")

    def execute(self, context):
        if self.url:
            try:
                bpy.ops.wm.url_open(url=_sanitize_url(self.url))
            except Exception as e:
                print(f"Unable to open URL: {e}")
        return {'FINISHED'}


class I3D_OT_CheckForUpdates(bpy.types.Operator):
    bl_idname = "i3d.check_for_updates"
    bl_label = "Check for Updates"
    bl_description = "Check for Updates."
    bl_options = {'INTERNAL'}

    def execute(self, context):
        global _I3D_LAST_CHECK_WAS_MANUAL
        _I3D_LAST_CHECK_WAS_MANUAL = True
        _begin_update_status_text(is_manual=True, message="Checking for updates...")
        # Keep the info banner alive while the network fetch runs.
        _invoke_op('i3d.update_check_progress')
        self.report({'INFO'}, str(_I3D_UPDATE_STATUS_MESSAGE))
        start_update_check(force=True)
        return {'FINISHED'}



class I3D_OT_UpdateCheckProgress(bpy.types.Operator):
    bl_idname = "i3d.update_check_progress"
    bl_label = "Update Check Progress"
    bl_description = "Update Check Progress."
    bl_options = {'INTERNAL'}

    _timer = None

    def invoke(self, context, event):
        wm = context.window_manager
        try:
            self._timer = wm.event_timer_add(1.0, window=context.window)
        except Exception:
            self._timer = None
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        # Keep re-reporting so the banner doesn't disappear while the network fetch is still running.
        if event.type == 'TIMER':
            # Channel switch polling: promote worker result and force a redraw so the
            # Preferences panel can show Commit/Cancel without requiring mouse movement.
            if bool(_I3D_CHANNEL_SWITCH_IN_PROGRESS):
                try:
                    _channel_switch_promote_result_if_ready()
                except Exception:
                    pass
                try:
                    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
                except Exception:
                    pass
            if not _I3D_UPDATE_STATUS_ACTIVE:
                self.cancel(context)
                return {'FINISHED'}
            self.report({'INFO'}, str(_I3D_UPDATE_STATUS_MESSAGE))

        if not _I3D_UPDATE_STATUS_ACTIVE:
            self.cancel(context)
            return {'FINISHED'}
        return {'PASS_THROUGH'}

    def cancel(self, context):
        wm = context.window_manager
        if self._timer is not None:
            try:
                wm.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None

class I3D_OT_UpdateAvailableDialog(bpy.types.Operator):
    bl_idname = "i3d.update_available_dialog"
    bl_label = "Update Available"
    bl_description = "Update Available."
    bl_options = {'INTERNAL'}

    _timer = None

    def _remove_timer(self, context):
        try:
            wm = context.window_manager
            if getattr(self, '_timer', None) is not None:
                wm.event_timer_remove(self._timer)
        except Exception:
            pass
        self._timer = None

    def invoke(self, context, event):
        # Snapshot offer so redraws don't lose the content.
        try:
            global _I3D_UPDATE_OFFER
            self._offer = dict(_I3D_UPDATE_OFFER or {})
        except Exception:
            self._offer = {}

        # NOTE: Flashing UI in Blender popup dialogs is redraw-limited (often only updates on mouse move).
        # Keep the rollback target styling solid instead of flashing.
        global _I3D_UPDATE_DIALOG_ACTIVE, _I3D_UPDATE_DIALOG_CLOSE_REQUEST
        _I3D_UPDATE_DIALOG_ACTIVE = True
        _I3D_UPDATE_DIALOG_CLOSE_REQUEST = False


        # Timer ensures modal runs so we can close this popup without requiring mouse movement.
        try:
            wm = context.window_manager
            self._timer = wm.event_timer_add(0.1, window=context.window)
        except Exception:
            self._timer = None

        return context.window_manager.invoke_popup(self, width=560)
    def modal(self, context, event):
        global _I3D_UPDATE_DIALOG_ACTIVE, _I3D_UPDATE_DIALOG_CLOSE_REQUEST

        if _I3D_UPDATE_DIALOG_CLOSE_REQUEST:
            _I3D_UPDATE_DIALOG_ACTIVE = False
            _I3D_UPDATE_DIALOG_CLOSE_REQUEST = False
            self._remove_timer(context)
            return {'FINISHED'}

        if event.type in {'ESC'}:
            return self.cancel(context)

        return {'RUNNING_MODAL'}


    def draw(self, context):
        layout = self.layout
        prefs = _get_addon_prefs()

        r = getattr(self, '_offer', None) or {}
        local_v = r.get("local_version", (0, 0, 0))
        local_b = int(r.get("local_build") or 0)
        remote_v = r.get("remote_version", (0, 0, 0))
        remote_b = int(r.get("remote_build") or 0)
        channel = str(getattr(prefs, "update_channel", "STABLE")).upper() if prefs else "STABLE"

        is_update = _version_build_key(remote_v, remote_b) > _version_build_key(local_v, local_b)
        is_rollback = _version_build_key(remote_v, remote_b) < _version_build_key(local_v, local_b)

        installed_channel = str(getattr(prefs, 'update_installed_channel', 'STABLE')).upper() if prefs else 'STABLE'
        selected_channel = channel
        force_reinstall = (
            (not is_update) and (not is_rollback)
            and tuple(remote_v) == tuple(local_v)
            and selected_channel in ('ALPHA', 'BETA')
            and installed_channel in ('ALPHA', 'BETA')
            and selected_channel != installed_channel
        )

        # Header
        header = layout.box()
        header.alert = True
        action_word = "Update" if is_update else ("Rollback" if is_rollback else ("Reinstall" if force_reinstall else "Install"))
        header.label(
            text=f"{_get_addon_display_name()}: {channel.upper()} {action_word} available!",
            icon='IMPORT'
        )

        # Channel switch (ALPHA <-> BETA) reinstall prompt
        if force_reinstall:
            sw = layout.box()
            sw.alert = True
            sw.label(text=f"You are switching from {installed_channel.title()} to {selected_channel.title()}.", icon='INFO')
            sw.label(text="Would you like to reinstall this add-on in case there are changes?", icon='QUESTION')

        # Version display (extra emphasis for rollbacks)
        if is_rollback:
            vbox = layout.box()
            vbox.label(text="🟨 You are going BACK to an older version.", icon='ERROR')

            current_row = vbox.row()
            current_row.label(text=f"🟩 Current (installed): {_format_version_build(local_v, local_b)}", icon='CHECKMARK')

            # Rollback target: solid red (no flashing; popup redraws are often mouse-move driven)
            rb = vbox.box()
            rb.alert = True
            rb_row = rb.row()
            rb_row.alert = True
            rb_row.label(text=f"Rollback target: {_format_version_build(remote_v, remote_b)}", icon='ERROR')
        else:
            layout.label(text=f"Installed: {_format_version_build(local_v, local_b)}")
            layout.label(text=f"Latest:    {_format_version_build(remote_v, remote_b)}")

        # Message from manifest
        if r.get("message"):
            msg = layout.box()
            msg.label(text=str(r.get("message")), icon='INFO')

        # Inline notes (from manifest)
        notes_lines = []
        notes_val = r.get("notes")
        if isinstance(notes_val, list):
            notes_lines = [str(x) for x in notes_val if str(x).strip()]
        elif isinstance(notes_val, str):
            notes_lines = [ln.strip() for ln in notes_val.splitlines() if ln.strip()]

        if notes_lines:
            nb = layout.box()
            nb.label(text="Patch Notes:", icon='TEXT')
            for ln in notes_lines[:12]:
                nb.label(text=ln[:140])
            if len(notes_lines) > 12:
                nb.label(text="(More in Release Notes)", icon='DOT')

        layout.separator()

        # Primary actions
        row = layout.row(align=True)
        row.scale_y = 1.2

        if is_rollback:
            left = row.row(align=True)
            left.alert = True
            left.operator("i3d.perform_update", text="Rollback", icon='RECOVER_LAST')
        elif is_update:
            row.operator("i3d.perform_update", text="Update", icon='FILE_REFRESH')
        else:
            if force_reinstall:
                row.operator("i3d.perform_update", text="Reinstall", icon='FILE_REFRESH')
            else:
                row.operator("i3d.perform_update", text="Install", icon='IMPORT')

        op = row.operator("i3d.skip_update_version", text="Skip", icon='CANCEL')
        op.version_str = _format_version(remote_v)
        op.build_int = int(remote_b or 0)

        if r.get("notes_url"):
            row = layout.row()
            op = row.operator("i3d.open_url", text="Release Notes", icon='HELP')
            op.url = r.get("notes_url")
        # Warning about OK/Cancel
        warn = layout.box()
        warn.alert = True
        warn.label(text="After clicking Update, move your mouse above and below this text", icon='ERROR')
        warn.label(text="to get this screen to disappear after the update is complete.")
        warn.label(text="If you choose any other option, just click out of this screen to close it.")

        layout.separator()

        # preference actions
        if prefs is not None:
            row = layout.row()
            row.operator("i3d.disable_update_checks", text="Disable Update Checks", icon='CHECKBOX_HLT')

    
    def execute(self, context):
        # OK/Cancel just closes this dialog
        global _I3D_UPDATE_DIALOG_ACTIVE, _I3D_UPDATE_DIALOG_CLOSE_REQUEST
        _I3D_UPDATE_DIALOG_ACTIVE = False
        self._remove_timer(context)
        return {'FINISHED'}

    def cancel(self, context):
        global _I3D_UPDATE_DIALOG_ACTIVE, _I3D_UPDATE_DIALOG_CLOSE_REQUEST
        _I3D_UPDATE_DIALOG_ACTIVE = False

        self._remove_timer(context)


class I3D_OT_SkipUpdateVersion(bpy.types.Operator):
    bl_idname = "i3d.skip_update_version"
    bl_label = "Skip Update Version"
    bl_description = "Skip Update Version."
    bl_options = {'INTERNAL'}

    version_str: bpy.props.StringProperty(default="")
    build_int: bpy.props.IntProperty(default=0)

    def execute(self, context):
        prefs = _get_addon_prefs()
        channel_pref = "STABLE"
        if prefs is not None:
            # Store skip per selected channel
            channel_pref = getattr(prefs, "update_channel", "STABLE")
            if channel_pref == "ALPHA":
                prefs.update_skip_version_alpha = self.version_str
                prefs.update_skip_build_alpha = int(self.build_int or 0)
            elif channel_pref == "BETA":
                prefs.update_skip_version_beta = self.version_str
                prefs.update_skip_build_beta = int(self.build_int or 0)
            else:
                prefs.update_skip_version_stable = self.version_str
                prefs.update_skip_build_stable = int(self.build_int or 0)
            try:
                bpy.ops.wm.save_userpref()
            except Exception:
                pass

        # Provide visible feedback in Blender's status bar.
        try:
            try:
                _set_last_update_action(prefs, f"User skipped update {self.version_str}.{int(self.build_int or 0)}")
            except Exception:
                pass

            self.report({'INFO'}, f"Skipped version {self.version_str} build {int(self.build_int or 0)} for {channel_pref} channel.")
        except Exception:
            pass

        # Clear the stored offer so follow-up redraws in this session don't keep advertising it.
        try:
            global _I3D_UPDATE_OFFER
            _I3D_UPDATE_OFFER = None
        except Exception:
            pass

        return {'FINISHED'}


class I3D_OT_DisableUpdateChecks(bpy.types.Operator):
    bl_idname = "i3d.disable_update_checks"
    bl_label = "Disable Update Checks"
    bl_description = "Disable Update Checks."
    bl_options = {'INTERNAL'}

    def execute(self, context):
        prefs = _get_addon_prefs()
        if prefs is not None:
            prefs.enable_update_checks = False
            try:
                bpy.ops.wm.save_userpref()
            except Exception:
                pass
        return {'FINISHED'}


def _should_offer_update(result_dict, prefs):
    if result_dict is None or prefs is None:
        return False

    remote_v = result_dict.get("remote_version")
    remote_b = int(result_dict.get("remote_build") or 0)
    local_v = result_dict.get("local_version")
    local_b = int(result_dict.get("local_build") or 0)

    if remote_v is None or local_v is None:
        return False

    # Respect "skip version" (per-channel)
    channel_pref = getattr(prefs, "update_channel", "STABLE")
    if channel_pref == "ALPHA":
        skip = getattr(prefs, "update_skip_version_alpha", "")
        skip_b = int(getattr(prefs, "update_skip_build_alpha", 0) or 0)
    elif channel_pref == "BETA":
        skip = getattr(prefs, "update_skip_version_beta", "")
        skip_b = int(getattr(prefs, "update_skip_build_beta", 0) or 0)
    else:
        skip = getattr(prefs, "update_skip_version_stable", "")
        skip_b = int(getattr(prefs, "update_skip_build_stable", 0) or 0)

    if skip:
        try:
            if skip.strip() == _format_version(remote_v) and int(skip_b or 0) == int(remote_b or 0):
                return False
        except Exception:
            pass


    # Force a reinstall prompt when switching between ALPHA <-> BETA even if the version matches.
    try:
        selected_channel = str(getattr(prefs, 'update_channel', '')).upper()
        installed_channel = str(getattr(prefs, 'update_installed_channel', 'STABLE')).upper()
        if selected_channel in ('ALPHA', 'BETA') and installed_channel in ('ALPHA', 'BETA') and selected_channel != installed_channel:
            if tuple(remote_v) == tuple(local_v):
                return True
    except Exception:
        pass

    return _version_build_key(remote_v, remote_b) != _version_build_key(local_v, local_b)



def _capture_override_from_context(context):
    """Capture a usable override dict from the current UI context (best-effort).

    Update callbacks (like EnumProperty.update) can run with a limited context
    where area/region are None. When that happens, we try to derive a sensible
    area/region from the active Preferences window so dialogs can be invoked.
    """
    try:
        if context is None:
            return None

        ov = {}

        win = getattr(context, "window", None)
        if win is not None:
            ov["window"] = win
            try:
                ov["screen"] = win.screen
            except Exception:
                pass

        scr = getattr(context, "screen", None)
        if scr is not None:
            ov["screen"] = scr

        area = getattr(context, "area", None)
        region = getattr(context, "region", None)

        # If area/region are missing, attempt to find a Preferences area in the window screen.
        if (area is None or region is None):
            try:
                s = None
                if win is not None:
                    s = getattr(win, "screen", None)
                if s is None:
                    s = ov.get("screen")
                if s is not None and getattr(s, "areas", None):
                    if area is None:
                        for a in s.areas:
                            if a.type == "PREFERENCES":
                                area = a
                                break
                        if area is None:
                            area = s.areas[0]
                    if region is None and area is not None and getattr(area, "regions", None):
                        for r in area.regions:
                            if r.type == "WINDOW":
                                region = r
                                break
            except Exception:
                pass

        if area is not None:
            ov["area"] = area
        if region is not None:
            ov["region"] = region

        return ov or None
    except Exception:
        return None



def _find_invoke_override():
    """Return a best-effort override context for invoking dialogs from timers."""
    try:
        # If we captured a context override from the channel dropdown change, prefer it.
        global _I3D_CHANNEL_SWITCH_OVERRIDE
        if _I3D_CHANNEL_SWITCH_OVERRIDE:
            try:
                ov = dict(_I3D_CHANNEL_SWITCH_OVERRIDE)
                # Validate that the window still exists.
                wm = bpy.context.window_manager
                if wm and getattr(wm, "windows", None) and ov.get("window") in wm.windows:
                    return ov
            except Exception:
                pass

        wm = bpy.context.window_manager
        if not wm or not getattr(wm, "windows", None):
            return None
        win = wm.windows[0]
        screen = win.screen
        if not screen:
            return {"window": win}

        # Prefer Preferences area when available.
        area = None
        for a in screen.areas:
            if a.type == 'PREFERENCES':
                area = a
                break
        if area is None and screen.areas:
            area = screen.areas[0]

        region = None
        if area is not None:
            for r in area.regions:
                if r.type == 'WINDOW':
                    region = r
                    break

        override = {"window": win, "screen": screen}
        if area is not None:
            override["area"] = area
        if region is not None:
            override["region"] = region
        return override
    except Exception:
        return None


def _build_fallback_invoke_override():
    """Build a best-effort override for invoking dialog operators.

    We prefer a Preferences area (if available), otherwise fall back to any WINDOW region
    in the first available window/screen. This makes dialog invocations far more reliable
    when called from property-update callbacks or timers where bpy.context.* may be None.
    """
    try:
        wm = bpy.context.window_manager
        if not wm or not getattr(wm, "windows", None):
            return None

        # Prefer a Preferences area if one exists
        for win in wm.windows:
            scr = win.screen
            if not scr:
                continue
            for area in scr.areas:
                if area.type == 'PREFERENCES':
                    region = None
                    for r in area.regions:
                        if r.type == 'WINDOW':
                            region = r
                            break
                    if region:
                        return {"window": win, "screen": scr, "area": area, "region": region}

        # Fallback: any area with a WINDOW region
        for win in wm.windows:
            scr = win.screen
            if not scr:
                continue
            for area in scr.areas:
                region = None
                for r in area.regions:
                    if r.type == 'WINDOW':
                        region = r
                        break
                if region:
                    return {"window": win, "screen": scr, "area": area, "region": region}
    except Exception:
        pass
    return None


def _try_invoke_channel_switch_dialog_timer():
    """Retry invoking the channel-switch commit dialog on the main thread.

    Property update callbacks often do not have a stable UI context for popups.
    This timer keeps trying for a short window after the manifest fetch completes.
    """
    global _I3D_CHANNEL_SWITCH_DIALOG_PENDING, _I3D_CHANNEL_SWITCH_DIALOG_START_TIME
    global _I3D_CHANNEL_SWITCH_IN_PROGRESS, _I3D_CHANNEL_SWITCH_OVERRIDE

    if not _I3D_CHANNEL_SWITCH_DIALOG_PENDING:
        return None

    try:
        elapsed = time.time() - float(_I3D_CHANNEL_SWITCH_DIALOG_START_TIME or 0.0)
    except Exception:
        elapsed = 0.0

    if elapsed >= float(_I3D_CHANNEL_SWITCH_DIALOG_TIMEOUT_SECONDS):
        # Give up: revert and show a visible error.
        _I3D_CHANNEL_SWITCH_DIALOG_PENDING = False
        _I3D_CHANNEL_SWITCH_IN_PROGRESS = False
        _clear_update_status_text()
        try:
            prefs = _get_addon_prefs()
            offer = _I3D_CHANNEL_SWITCH_OFFER or {}
            old_ch = str(offer.get('old_channel', getattr(prefs, 'update_channel_prev', 'STABLE')) or 'STABLE').upper() if prefs else 'STABLE'
            if prefs:
                _set_update_channel_internal(prefs, old_ch)
                prefs.update_channel_prev = old_ch
                bpy.ops.wm.save_userpref()
        except Exception:
            pass
        _invoke_op('i3d.update_check_info_dialog', title='Update Channel', message='Unable to open the channel switch prompt (UI context not available).')
        _I3D_CHANNEL_SWITCH_OVERRIDE = None
        return None

    # Attempt to invoke in a robust context:
    # 1) captured override (from dropdown)
    ok = False
    try:
        if _I3D_CHANNEL_SWITCH_OVERRIDE:
            try:
                with bpy.context.temp_override(**_I3D_CHANNEL_SWITCH_OVERRIDE):
                    ok = _invoke_op('i3d.channel_switch_dialog')
            except Exception:
                ok = False
    except Exception:
        ok = False

    # 2) fallback override
    if not ok:
        ov = _build_fallback_invoke_override()
        if ov:
            try:
                with bpy.context.temp_override(**ov):
                    ok = _invoke_op('i3d.channel_switch_dialog')
            except Exception:
                ok = False
        else:
            ok = _invoke_op('i3d.channel_switch_dialog')

    if ok:
        # Stop the "please wait" status and stop retrying.
        _I3D_CHANNEL_SWITCH_DIALOG_PENDING = False
        _clear_update_status_text()
        _I3D_CHANNEL_SWITCH_OVERRIDE = None
        return None

    return 0.25

def _invoke_op(op_idname, invoke_type='INVOKE_DEFAULT', **kwargs):
    """Invoke an operator in the best available UI context.

    Blender can be picky about context for dialogs. This helper attempts to
    invoke with a best-effort temp_override, and treats a CANCELLED return
    value as a failure (so callers can fallback/revert).
    """
    try:
        cat, op = op_idname.split('.', 1)
        fn = getattr(getattr(bpy.ops, cat), op)

        override = _find_invoke_override()
        result = None

        if override:
            try:
                with bpy.context.temp_override(**override):
                    result = fn(invoke_type, **kwargs)
            except TypeError:
                # Fallback for older builds that don't support temp_override in this way.
                result = fn(invoke_type, **kwargs)
        else:
            result = fn(invoke_type, **kwargs)

        # Some ops return {'CANCELLED'} instead of raising when context is invalid.
        try:
            if isinstance(result, (set, frozenset)) and ('CANCELLED' in result):
                return False
        except Exception:
            pass

        return True
    except Exception as e:
        print(f"Unable to invoke operator '{op_idname}': {e}")
        return False


def _poll_update_result_timer():
    global _I3D_UPDATE_THREAD, _I3D_UPDATE_RESULT, _I3D_UPDATE_ERROR, _I3D_LAST_CHECK_WAS_MANUAL

    # Wait for thread completion (or results)
    if _I3D_UPDATE_THREAD is not None and _I3D_UPDATE_THREAD.is_alive():
        return 0.25

    prefs = _get_addon_prefs()

    # Thread finished: clear the persistent status text now.
    _clear_update_status_text()

    if prefs is None:
        return None

    # Ignore stale/late results (e.g. after a 30s UI timeout).
    if _I3D_UPDATE_RESULT is not None:
        try:
            if int(_I3D_UPDATE_RESULT.get('_check_id', 0)) != int(_I3D_UPDATE_ACTIVE_CHECK_ID):
                _I3D_UPDATE_RESULT = None
        except Exception:
            _I3D_UPDATE_RESULT = None

    if _I3D_UPDATE_ERROR is not None:
        try:
            if int(_I3D_UPDATE_ERROR_CHECK_ID or 0) != int(_I3D_UPDATE_ACTIVE_CHECK_ID):
                _I3D_UPDATE_ERROR = None
        except Exception:
            _I3D_UPDATE_ERROR = None


    # If we got a result and an install should be offered (upgrade OR rollback), show the update dialog.
    if _I3D_UPDATE_RESULT and _should_offer_update(_I3D_UPDATE_RESULT, prefs):
        # Snapshot the offer so the dialog can redraw safely even if globals are cleared.
        global _I3D_UPDATE_OFFER
        _I3D_UPDATE_OFFER = dict(_I3D_UPDATE_RESULT)
        try:
            rv = _I3D_UPDATE_OFFER.get('remote_version')
            if isinstance(rv, str):
                rv = _parse_version_tuple(rv)
            rb = int(_I3D_UPDATE_OFFER.get('remote_build', 0) or 0)
            _set_last_update_action(prefs, f"Update available: {_format_version_build(rv, rb)}")
        except Exception:
            pass
        _invoke_op('i3d.update_available_dialog')
        _I3D_LAST_CHECK_WAS_MANUAL = False

        # Clear thread/result for next manual check (keep _I3D_UPDATE_OFFER until user acts)
        _I3D_UPDATE_THREAD = None
        _I3D_UPDATE_RESULT = None
        _I3D_UPDATE_ERROR = None
        return None

    # For manual checks, show a visible result even when there is no update (or an error).
    if _I3D_LAST_CHECK_WAS_MANUAL:
        title = "Update Check"
        msg = "No updates found."
        if _I3D_UPDATE_ERROR:
            msg = f"Failed to check for updates.\n\n{_I3D_UPDATE_ERROR}"

        try:
            if _I3D_UPDATE_ERROR:
                _set_last_update_action(prefs, "Update check failed")
            else:
                _set_last_update_action(prefs, "No updates were found")
        except Exception:
            pass

        if not _invoke_op('i3d.update_check_info_dialog', title=title, message=msg):
            print("Unable to show update result dialog")

        _I3D_LAST_CHECK_WAS_MANUAL = False

    # (Optional) print error to console for debugging, but don't spam users.
    if _I3D_UPDATE_ERROR:
        print(f"Update check error: {_I3D_UPDATE_ERROR}")

    # Clear thread/result for next manual check
    _I3D_UPDATE_THREAD = None
    _I3D_UPDATE_RESULT = None
    _I3D_UPDATE_ERROR = None

    return None

def start_update_check(force=False):
    """Kick off an update check in the background.

    force=True ignores "checked this session" and runs again.
    """
    global _I3D_UPDATE_CHECKED_THIS_SESSION, _I3D_UPDATE_THREAD

    prefs = _get_addon_prefs()
    if prefs is None:
        return

    if not getattr(prefs, "enable_update_checks", False):
        return

    if not _online_access_allowed():
        return

    if (not force) and _I3D_UPDATE_CHECKED_THIS_SESSION:
        return

    manifest_url_primary = getattr(prefs, "update_manifest_url", "").strip()
    if not manifest_url_primary:
        return

    channel_key = _channel_key_from_pref(getattr(prefs, "update_channel", "STABLE"))

    # Avoid parallel checks
    if _I3D_UPDATE_THREAD is not None and _I3D_UPDATE_THREAD.is_alive():
        return


    # Begin persistent status text so users can see we're still working (even if the network is slow).
    _begin_update_status_text(is_manual=_I3D_LAST_CHECK_WAS_MANUAL)

    global _I3D_UPDATE_NEXT_CHECK_ID, _I3D_UPDATE_ACTIVE_CHECK_ID
    _I3D_UPDATE_NEXT_CHECK_ID += 1
    check_id = int(_I3D_UPDATE_NEXT_CHECK_ID)
    _I3D_UPDATE_ACTIVE_CHECK_ID = check_id

    _I3D_UPDATE_CHECKED_THIS_SESSION = True

    _I3D_UPDATE_THREAD = threading.Thread(
        target=_update_thread_main,
        args=(manifest_url_primary, channel_key, check_id),
        daemon=True,
    )
    _I3D_UPDATE_THREAD.start()

    # Poll on main thread (needed to invoke operators)
    try:
        bpy.app.timers.register(_poll_update_result_timer, first_interval=0.25)
    except Exception:
        pass

def _startup_timer():
    start_update_check(force=False)
    return None



def _channel_switch_thread_main(manifest_url_primary, old_channel, new_channel, check_id):
    global _I3D_CHANNEL_SWITCH_RESULT, _I3D_CHANNEL_SWITCH_ERROR, _I3D_CHANNEL_SWITCH_ERROR_CHECK_ID
    global _I3D_CHANNEL_SWITCH_OFFER, _I3D_CHANNEL_SWITCH_ACTIVE_CHECK_ID
    try:
        print(f"[I3D Update] Channel switch fetch begin ({old_channel} -> {new_channel}) url={manifest_url_primary}")
    except Exception:
        pass


    try:
        data = _fetch_manifest_json(manifest_url_primary, timeout_seconds=3.0)

        channels = data.get("channels", {})
        # Manifest channel keys are case-sensitive and are expected to be lowercase
        # (e.g. "alpha" / "beta" / "stable"). Accept any caller casing here.
        key = str(new_channel or "").strip()
        ch = channels.get(key)
        if ch is None:
            ch = channels.get(key.lower())
        if ch is None:
            ch = channels.get(key.upper())
        if ch is None:
            raise ValueError(f"Manifest missing channel '{new_channel}'")

        remote_v = _parse_version_tuple(ch.get("version"))
        if remote_v is None:
            raise ValueError("Manifest channel has invalid 'version'")

        local_v = _get_local_version_tuple()

        remote_build = _parse_build_int(ch.get("build"))
        local_build = _get_local_build_int()

        blender_min = _parse_version_tuple(ch.get("min_blender")) if ch.get("min_blender") is not None else None

        download_primary = None
        download_secondary = None
        dl = ch.get("download", {})
        if isinstance(dl, dict):
            download_primary = dl.get("primary")
            download_secondary = dl.get("secondary")
        else:
            download_primary = ch.get("download_url")  # legacy/simple manifest support

        notes_url = ch.get("notes_url")
        message = ch.get("message")
        notes = ch.get("notes")
        if notes is None:
            notes = ch.get("notes_text")

        result_payload = {
            "_check_id": int(check_id),
            "old_channel": str(old_channel or "STABLE").upper(),
            "new_channel": str(new_channel or "STABLE").upper(),
            "local_version": local_v,
            "local_build": local_build,
            "remote_version": remote_v,
            "remote_build": remote_build,
            "min_blender": blender_min,
            "download_primary": download_primary,
            "download_secondary": download_secondary,
            "notes_url": notes_url,
            "notes": notes,
            "message": message,
        }

        # IMPORTANT: Make the Preferences UI "ready" immediately after the network fetch
        # completes by writing the full offer payload here.
        #
        # Rationale: Blender can silently cancel timers/operators started from an EnumProperty
        # update callback in the Preferences window, which can prevent the main-thread poll
        # timer from promoting _I3D_CHANNEL_SWITCH_RESULT into _I3D_CHANNEL_SWITCH_OFFER.
        #
        # We still keep _I3D_CHANNEL_SWITCH_IN_PROGRESS True so the prefs panel stays locked
        # until the user commits or cancels.
        try:
            if int(check_id) == int(_I3D_CHANNEL_SWITCH_ACTIVE_CHECK_ID):
                _I3D_CHANNEL_SWITCH_OFFER = dict(result_payload)
        except Exception:
            pass

        _I3D_CHANNEL_SWITCH_RESULT = dict(result_payload)
        _I3D_CHANNEL_SWITCH_ERROR = None
        try:
            dl = download_primary or download_secondary
            print(f"[I3D Update] Channel switch fetch ok: {old_channel} -> {new_channel} remote={_format_version(remote_v)} download={dl}")
        except Exception:
            pass


    except Exception as e:
        _I3D_CHANNEL_SWITCH_RESULT = None
        _I3D_CHANNEL_SWITCH_ERROR = str(e)
        _I3D_CHANNEL_SWITCH_ERROR_CHECK_ID = int(check_id)
        # Surface the error directly to the prefs UI (same reasoning as success path above).
        try:
            if int(check_id) == int(_I3D_CHANNEL_SWITCH_ACTIVE_CHECK_ID):
                offer = dict(_I3D_CHANNEL_SWITCH_OFFER or {})
                offer["error"] = str(e)
                _I3D_CHANNEL_SWITCH_OFFER = offer
        except Exception:
            pass
        try:
            print(f"[I3D Update] Channel switch fetch failed: {str(e)}")
        except Exception:
            pass



def _poll_channel_switch_result_timer():
    global _I3D_CHANNEL_SWITCH_THREAD, _I3D_CHANNEL_SWITCH_RESULT, _I3D_CHANNEL_SWITCH_ERROR
    global _I3D_CHANNEL_SWITCH_OFFER
    global _I3D_UPDATE_STATUS_ACTIVE
    global _I3D_CHANNEL_SWITCH_IN_PROGRESS
    global _I3D_CHANNEL_SWITCH_OVERRIDE
    global _I3D_CHANNEL_SWITCH_DIALOG_PENDING
    global _I3D_CHANNEL_SWITCH_POLL_TIMER_RUNNING
    # Wait for thread completion (with a UI timeout so Blender doesn't feel stuck)
    if _I3D_CHANNEL_SWITCH_THREAD is not None and _I3D_CHANNEL_SWITCH_THREAD.is_alive():
        try:
            elapsed = time.time() - float(_I3D_CHANNEL_SWITCH_START_TIME or 0.0)
        except Exception:
            elapsed = 0.0

        if elapsed >= float(_I3D_CHANNEL_SWITCH_TIMEOUT_SECONDS):
            # Timeout: revert the dropdown back to the previous selection, unlock UI, and show a visible message.
            _I3D_CHANNEL_SWITCH_IN_PROGRESS = False
            _I3D_CHANNEL_SWITCH_OVERRIDE = None

            _I3D_UPDATE_STATUS_ACTIVE = False
            _clear_update_status_text()

            prefs = _get_addon_prefs()
            if prefs is not None:
                offer = _I3D_CHANNEL_SWITCH_OFFER or {}
                old_channel = str(offer.get("old_channel", getattr(prefs, "update_channel_prev", "STABLE"))).upper()
                try:
                    _set_update_channel_internal(prefs, old_channel)
                    prefs.update_channel_prev = old_channel
                    bpy.ops.wm.save_userpref()
                except Exception:
                    pass

            title = "Update Channel"
            msg = "Timed out while gathering build information (30s).\n\nPlease try again."
            _invoke_op('i3d.update_check_info_dialog', title=title, message=msg)

            # Ignore any late/stale thread result.
            _I3D_CHANNEL_SWITCH_ACTIVE_CHECK_ID = -1
            _I3D_CHANNEL_SWITCH_THREAD = None
            _I3D_CHANNEL_SWITCH_RESULT = None
            _I3D_CHANNEL_SWITCH_ERROR = None
            _I3D_CHANNEL_SWITCH_OFFER = None
            _I3D_CHANNEL_SWITCH_POLL_TIMER_RUNNING = False
            return None

        return 0.25

    # Stop the persistent "checking" banner.
    _I3D_UPDATE_STATUS_ACTIVE = False
    _clear_update_status_text()

    prefs = _get_addon_prefs()
    if prefs is None:
        _I3D_CHANNEL_SWITCH_POLL_TIMER_RUNNING = False
        return None

    # Ignore stale results
    if _I3D_CHANNEL_SWITCH_RESULT is not None:
        try:
            if int(_I3D_CHANNEL_SWITCH_RESULT.get('_check_id', 0)) != int(_I3D_CHANNEL_SWITCH_ACTIVE_CHECK_ID):
                _I3D_CHANNEL_SWITCH_RESULT = None
        except Exception:
            _I3D_CHANNEL_SWITCH_RESULT = None

    if _I3D_CHANNEL_SWITCH_ERROR is not None:
        try:
            if int(_I3D_CHANNEL_SWITCH_ERROR_CHECK_ID or 0) != int(_I3D_CHANNEL_SWITCH_ACTIVE_CHECK_ID):
                _I3D_CHANNEL_SWITCH_ERROR = None
        except Exception:
            _I3D_CHANNEL_SWITCH_ERROR = None
    # Success: build info gathered. We do NOT open a popup for channel switching.
    # Instead, keep the Update Checker UI locked and let the Preferences panel
    # show a Commit/Cancel section driven by _I3D_CHANNEL_SWITCH_OFFER.
    if _I3D_CHANNEL_SWITCH_RESULT:
        _I3D_CHANNEL_SWITCH_OFFER = dict(_I3D_CHANNEL_SWITCH_RESULT)

        # Mark dialog pending as false (we are not using popups for channel switching).
        _I3D_CHANNEL_SWITCH_DIALOG_PENDING = False

        # Clear the captured override (no popup to invoke).
        _I3D_CHANNEL_SWITCH_OVERRIDE = None

        # Consume the thread/result; keep _I3D_CHANNEL_SWITCH_IN_PROGRESS True until
        # the user commits or cancels.
        _I3D_CHANNEL_SWITCH_THREAD = None
        _I3D_CHANNEL_SWITCH_RESULT = None
        _I3D_CHANNEL_SWITCH_ERROR = None

        # Force a redraw so the Preferences UI can immediately show the Commit/Cancel section
        # (otherwise users may only see the change after moving the mouse).
        try:
            bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
        except Exception:
            pass
        _I3D_CHANNEL_SWITCH_POLL_TIMER_RUNNING = False
        return None

    # Error: keep the UI locked but surface an error and allow revert.
    if _I3D_CHANNEL_SWITCH_ERROR:
        try:
            offer = dict(_I3D_CHANNEL_SWITCH_OFFER or {})
        except Exception:
            offer = {}
        offer["error"] = str(_I3D_CHANNEL_SWITCH_ERROR)
        _I3D_CHANNEL_SWITCH_OFFER = offer

        # Detach the thread reference to prevent the wait UI from persisting.
        _I3D_CHANNEL_SWITCH_THREAD = None

        try:
            bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
        except Exception:
            pass
        _I3D_CHANNEL_SWITCH_POLL_TIMER_RUNNING = False
        return None
    _I3D_CHANNEL_SWITCH_POLL_TIMER_RUNNING = False
    return None

def request_alpha_beta_switch(old_channel, new_channel, context=None):
    """Triggered by the Update Channel dropdown when switching ALPHA <-> BETA.

    This fetches the selected channel's manifest entry and forces a prompt to install now or revert.
    """
    prefs = _get_addon_prefs()
    if prefs is None:
        return

    # Only ALPHA <-> BETA
    old_channel = str(old_channel or "STABLE").upper()
    new_channel = str(new_channel or "STABLE").upper()
    if not (old_channel in ("ALPHA", "BETA") and new_channel in ("ALPHA", "BETA") and old_channel != new_channel):
        return

    try:
        print(f"[I3D Update] Channel switch requested: {old_channel} -> {new_channel}")
    except Exception:
        pass

    manifest_url_primary = getattr(prefs, "update_manifest_url", "").strip()
    if not manifest_url_primary:
        # If manifest URL is missing, revert immediately.
        _set_update_channel_internal(prefs, old_channel)
        prefs.update_channel_prev = old_channel
        try:
            bpy.ops.wm.save_userpref()
        except Exception:
            pass
        return

    # Avoid double-queries: if a channel switch fetch is already running, ignore new requests.
    global _I3D_CHANNEL_SWITCH_THREAD
    if _I3D_CHANNEL_SWITCH_THREAD is not None and _I3D_CHANNEL_SWITCH_THREAD.is_alive():
        return

    # Lock the Update Checker UI while we gather build info.
    global _I3D_CHANNEL_SWITCH_IN_PROGRESS, _I3D_CHANNEL_SWITCH_START_TIME
    _I3D_CHANNEL_SWITCH_IN_PROGRESS = True
    _I3D_CHANNEL_SWITCH_START_TIME = time.time()

    # Capture the current UI context so the follow-up dialog appears in the same window/area.
    global _I3D_CHANNEL_SWITCH_OVERRIDE
    ov = _capture_override_from_context(context)
    if ov:
        _I3D_CHANNEL_SWITCH_OVERRIDE = ov

    # Start persistent banner + keep it alive using the existing progress operator.
    global _I3D_UPDATE_STATUS_ACTIVE, _I3D_UPDATE_STATUS_START_TIME, _I3D_UPDATE_STATUS_WAS_MANUAL, _I3D_UPDATE_STATUS_MESSAGE
    _I3D_UPDATE_STATUS_ACTIVE = True
    _I3D_UPDATE_STATUS_START_TIME = time.time()
    _I3D_UPDATE_STATUS_WAS_MANUAL = True
    _I3D_UPDATE_STATUS_MESSAGE = f"Please wait while we gather {str(new_channel).title()} build information..."
    _set_workspace_status_text(_I3D_UPDATE_STATUS_MESSAGE)
    _ensure_update_status_timer()
    _invoke_op('i3d.update_check_progress')

    # Allocate a unique check id
    global _I3D_CHANNEL_SWITCH_NEXT_CHECK_ID, _I3D_CHANNEL_SWITCH_ACTIVE_CHECK_ID
    _I3D_CHANNEL_SWITCH_NEXT_CHECK_ID += 1
    check_id = int(_I3D_CHANNEL_SWITCH_NEXT_CHECK_ID)
    _I3D_CHANNEL_SWITCH_ACTIVE_CHECK_ID = check_id

    global _I3D_CHANNEL_SWITCH_RESULT, _I3D_CHANNEL_SWITCH_ERROR, _I3D_CHANNEL_SWITCH_OFFER
    _I3D_CHANNEL_SWITCH_RESULT = None
    _I3D_CHANNEL_SWITCH_ERROR = None
    _I3D_CHANNEL_SWITCH_OFFER = {"old_channel": old_channel, "new_channel": new_channel}

    _I3D_CHANNEL_SWITCH_THREAD = threading.Thread(
        target=_channel_switch_thread_main,
        args=(manifest_url_primary, old_channel, new_channel, check_id),
        daemon=True,
    )
    _I3D_CHANNEL_SWITCH_THREAD.start()

    try:
        bpy.app.timers.register(_poll_channel_switch_result_timer, first_interval=0.25)
    except Exception:
        pass


class I3D_OT_ChannelSwitchDialog(bpy.types.Operator):
    bl_idname = "i3d.channel_switch_dialog"
    bl_label = "Update Channel Switch"
    bl_description = "Update Channel Switch."
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        # Snapshot offer for stable redraw
        self._offer = dict(_I3D_CHANNEL_SWITCH_OFFER or {})
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        layout = self.layout
        prefs = _get_addon_prefs()

        r = getattr(self, '_offer', None) or {}
        old_channel = str(r.get("old_channel", "BETA")).upper()
        new_channel = str(r.get("new_channel", "ALPHA")).upper()

        header = layout.box()
        header.alert = True
        header.label(text=f"Switching {old_channel.title()} → {new_channel.title()}", icon='INFO')

        box = layout.box()
        box.label(text=f"You are switching to the {new_channel.title()} build.", icon='ERROR')
        box.label(text="To apply this change, you must install now and then quit Blender.", icon='ERROR')

        # Patch notes
        notes_val = r.get("notes")
        notes_lines = []
        if isinstance(notes_val, list):
            notes_lines = [str(x) for x in notes_val if str(x).strip()]
        elif isinstance(notes_val, str):
            notes_lines = [ln.strip() for ln in notes_val.splitlines() if ln.strip()]

        if notes_lines:
            nb = layout.box()
            nb.label(text="Patch Notes:", icon='TEXT')
            for ln in notes_lines[:12]:
                nb.label(text=ln[:140])
            if len(notes_lines) > 12:
                nb.label(text="(More in Release Notes)", icon='DOT')

        if r.get("notes_url"):
            row = layout.row()
            op = row.operator("i3d.open_url", text="Release Notes", icon='HELP')
            op.url = r.get("notes_url")

        layout.separator()

        row = layout.row(align=True)
        row.scale_y = 1.2

        yes = row.operator("i3d.channel_switch_commit", text="Yes", icon='CHECKMARK')
        yes.old_channel = old_channel
        yes.new_channel = new_channel

        no = row.operator("i3d.channel_switch_cancel", text="No", icon='CANCEL')
        no.old_channel = old_channel

    def execute(self, context):
        # Treat the default OK button as "No" (revert the dropdown) so the user
        # must explicitly choose Yes to commit.
        self.cancel(context)
        return {'FINISHED'}

    def cancel(self, context):
        # Revert dropdown back to previous selection and unlock the Update Checker UI.
        global _I3D_CHANNEL_SWITCH_IN_PROGRESS
        _I3D_CHANNEL_SWITCH_IN_PROGRESS = False

        prefs = _get_addon_prefs()
        if prefs is None:
            return

        offer = getattr(self, '_offer', None) or dict(_I3D_CHANNEL_SWITCH_OFFER or {})
        old_ch = str(offer.get("old_channel", getattr(prefs, "update_channel_prev", "STABLE")) or "STABLE").upper()
        try:
            _set_update_channel_internal(prefs, old_ch)
            prefs.update_channel_prev = old_ch
            bpy.ops.wm.save_userpref()
        except Exception:
            pass


class I3D_OT_ChannelSwitchCommit(bpy.types.Operator):
    bl_idname = "i3d.channel_switch_commit"
    bl_label = "Commit Channel Switch"
    bl_description = "Commit Channel Switch."
    bl_options = {'INTERNAL'}

    old_channel: bpy.props.StringProperty(default="BETA")
    new_channel: bpy.props.StringProperty(default="ALPHA")

    def execute(self, context):
        global _I3D_CHANNEL_SWITCH_OFFER, _I3D_CHANNEL_SWITCH_ERROR, _I3D_CHANNEL_SWITCH_RESULT, _I3D_CHANNEL_SWITCH_OVERRIDE
        global _I3D_CHANNEL_SWITCH_IN_PROGRESS
        global _I3D_UPDATE_OFFER
        global _I3D_UPDATE_STATUS_ACTIVE

        prefs = _get_addon_prefs()
        if prefs is None:
            return {'CANCELLED'}

        # Snapshot the offer BEFORE clearing channel-switch state.
        r = dict(_I3D_CHANNEL_SWITCH_OFFER or {})
        # Make this offer the active update offer so the existing installer logic can run.
        _I3D_UPDATE_OFFER = dict(r)

        # User committed the switch; unlock the Update Checker UI.
        _I3D_CHANNEL_SWITCH_IN_PROGRESS = False
        # Clear pending channel-switch state (runtime only).
        _I3D_CHANNEL_SWITCH_OFFER = None
        _I3D_CHANNEL_SWITCH_ERROR = None
        _I3D_CHANNEL_SWITCH_RESULT = None
        _I3D_CHANNEL_SWITCH_OVERRIDE = None

        # Stop any persistent status banner.
        _I3D_UPDATE_STATUS_ACTIVE = False
        _clear_update_status_text()

        # Commit the "previous" marker to the new channel.
        try:
            prefs.update_channel_prev = str(self.new_channel or "STABLE").upper()
            try:
                from .. import i3d_globals as _i3d_globals
                _i3d_globals._I3D_LAST_UPDATE_CHANNEL_VALUE = str(self.new_channel or "STABLE").upper()
            except Exception:
                pass
            bpy.ops.wm.save_userpref()
        except Exception:
            pass

        # Start install
        try:
            bpy.ops.i3d.perform_update()
        except Exception:
            pass

        # Reminder: quit Blender after install.
        title = "Update Channel"
        msg = "Install started.\n\nWhen it finishes, quit and reopen Blender for changes to take effect."
        _invoke_op('i3d.update_check_info_dialog', title=title, message=msg)

        return {'FINISHED'}


class I3D_OT_ChannelSwitchCancel(bpy.types.Operator):
    bl_idname = "i3d.channel_switch_cancel"
    bl_label = "Cancel Channel Switch"
    bl_description = "Cancel Channel Switch."
    bl_options = {'INTERNAL'}

    old_channel: bpy.props.StringProperty(default="BETA")

    def execute(self, context):
        # User canceled the switch; unlock the Update Checker UI.
        global _I3D_CHANNEL_SWITCH_IN_PROGRESS
        _I3D_CHANNEL_SWITCH_IN_PROGRESS = False
        # Clear pending channel-switch state (runtime only).
        global _I3D_CHANNEL_SWITCH_OFFER, _I3D_CHANNEL_SWITCH_ERROR, _I3D_CHANNEL_SWITCH_RESULT, _I3D_CHANNEL_SWITCH_OVERRIDE
        _I3D_CHANNEL_SWITCH_OFFER = None
        _I3D_CHANNEL_SWITCH_ERROR = None
        _I3D_CHANNEL_SWITCH_RESULT = None
        _I3D_CHANNEL_SWITCH_OVERRIDE = None

        # Stop any persistent status banner.
        global _I3D_UPDATE_STATUS_ACTIVE
        _I3D_UPDATE_STATUS_ACTIVE = False
        _clear_update_status_text()

        prefs = _get_addon_prefs()
        if prefs is None:
            return {'CANCELLED'}

        old_ch = str(self.old_channel or "STABLE").upper()

        # Revert dropdown back to previous selection.
        try:
            _set_update_channel_internal(prefs, old_ch)
            prefs.update_channel_prev = old_ch
            bpy.ops.wm.save_userpref()
        except Exception:
            pass

        return {'FINISHED'}


# --------------------------------------------------------------
# Auto Update (download + install)
# --------------------------------------------------------------

_I3D_UPDATE_INSTALL_ERROR = None

def _download_bytes(url, timeout_seconds=6.0):
    url = _sanitize_url(url)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"DTAP-I3D-Exporter/{_get_local_version_tuple()[0]}.{_get_local_version_tuple()[1]}.{_get_local_version_tuple()[2]}",
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        }
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        return resp.read()

def _download_zip_with_fallback(url_primary, url_secondary):
    last_err = None

    if url_primary:
        try:
            return _download_bytes(url_primary, timeout_seconds=12.0), url_primary
        except Exception as e:
            last_err = e

    if url_secondary:
        try:
            return _download_bytes(url_secondary, timeout_seconds=12.0), url_secondary
        except Exception as e:
            last_err = e

    if last_err is not None:
        raise last_err
    raise RuntimeError("No download URL configured")


# --------------------------------------------------------------
# Full UI Redraw Helper (post-update)
# --------------------------------------------------------------
# After in-place updates (disable -> overwrite -> enable), Blender may keep some UI areas
# visually "stale" until the user interacts or restarts. Tagging every area/region for redraw
# (and nudging a window swap) refreshes the UI so newly-registered panels/buttons appear.

def _force_full_ui_redraw_all_windows():
    try:
        wm = bpy.context.window_manager
    except Exception:
        wm = None

    if not wm:
        return

    try:
        windows = list(getattr(wm, "windows", []) or [])
    except Exception:
        windows = []

    for win in windows:
        scr = getattr(win, "screen", None)
        if not scr:
            continue

        for area in getattr(scr, "areas", []) or []:
            try:
                area.tag_redraw()
            except Exception:
                pass

            for region in getattr(area, "regions", []) or []:
                try:
                    region.tag_redraw()
                except Exception:
                    pass

    # Extra nudge (safe best-effort): forces a window swap draw pass.
    try:
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    except Exception:
        pass


def _schedule_full_ui_redraw_all_windows(iterations=5, first_interval=0.2, step_interval=0.15):
    try:
        remaining = int(iterations)
    except Exception:
        remaining = 3

    state = {"remaining": max(1, remaining)}

    def _timer():
        try:
            _force_full_ui_redraw_all_windows()
        except Exception:
            pass

        state["remaining"] -= 1
        if state["remaining"] <= 0:
            return None
        try:
            return float(step_interval)
        except Exception:
            return 0.15

    try:
        bpy.app.timers.register(_timer, first_interval=float(first_interval))
    except Exception:
        # Fallback: at least do a single redraw attempt.
        try:
            _force_full_ui_redraw_all_windows()
        except Exception:
            pass



class I3D_OT_PerformUpdate(bpy.types.Operator):
    bl_idname = "i3d.perform_update"
    bl_label = "Update Add-on"
    bl_description = "Update Add-on."
    bl_options = {'INTERNAL'}

    def execute(self, context):
        global _I3D_UPDATE_INSTALL_ERROR
        global _I3D_UPDATE_DIALOG_CLOSE_REQUEST, _I3D_UPDATE_DIALOG_ACTIVE

        prefs = _get_addon_prefs()
        if prefs is None:
            return {'CANCELLED'}

        r = _I3D_UPDATE_OFFER or {}

        url_primary = r.get("download_primary")
        url_secondary = r.get("download_secondary")

        # Request the update popup to close FIRST (do not start download/install synchronously here).
        _I3D_UPDATE_DIALOG_CLOSE_REQUEST = True
        _I3D_UPDATE_DIALOG_ACTIVE = False

        state = {"phase": "wait", "t0": time.time(), "temp_zip": None}

        def _timer():
            global _I3D_UPDATE_INSTALL_ERROR
            global _I3D_UPDATE_DIALOG_CLOSE_REQUEST, _I3D_UPDATE_DIALOG_ACTIVE

            # Phase 1: wait for the dialog modal to process the close request.
            if state["phase"] == "wait":
                if _I3D_UPDATE_DIALOG_ACTIVE:
                    return 0.1

                # If the close flag is still set, give the dialog a moment to consume it.
                if _I3D_UPDATE_DIALOG_CLOSE_REQUEST:
                    if (time.time() - state["t0"]) < 2.0:
                        return 0.1
                    _I3D_UPDATE_DIALOG_CLOSE_REQUEST = False

                state["phase"] = "download"
                return 0.1

            # Phase 2: download + write temp zip.
            if state["phase"] == "download":
                try:
                    data, used_url = _download_zip_with_fallback(url_primary, url_secondary)
                except Exception as e:
                    _I3D_UPDATE_INSTALL_ERROR = f"Download failed: {e}"
                    try:
                        bpy.ops.i3d.update_failed_dialog('INVOKE_DEFAULT')
                    except Exception:
                        pass
                    return None

                try:
                    temp_dir = getattr(bpy.app, "tempdir", None) or tempfile.gettempdir()
                    temp_zip = os.path.join(temp_dir, "io_export_i3d_reworked_update.zip")
                    with open(temp_zip, "wb") as f:
                        f.write(data)
                    state["temp_zip"] = temp_zip
                except Exception as e:
                    _I3D_UPDATE_INSTALL_ERROR = f"Unable to write update zip: {e}"
                    try:
                        bpy.ops.i3d.update_failed_dialog('INVOKE_DEFAULT')
                    except Exception:
                        pass
                    return None

                state["phase"] = "install"
                return 0.1

            # Phase 3: disable + overwrite + purge sys.modules + enable.
            if state["phase"] == "install":
                temp_zip = state.get("temp_zip")
                if not temp_zip:
                    _I3D_UPDATE_INSTALL_ERROR = "Install failed: missing temp zip"
                    try:
                        bpy.ops.i3d.update_failed_dialog('INVOKE_DEFAULT')
                    except Exception:
                        pass
                    return None

                try:
                    _stop_all_update_timers_best_effort()
                except Exception:
                    pass

                try:
                    import sys as _sys
                    import importlib as _importlib
                    import zipfile as _zipfile
                    import shutil as _shutil
                    import addon_utils as _addon_utils

                    # Disable before overwriting.
                    try:
                        _addon_utils.disable("io_export_i3d_reworked", default_set=True)
                    except Exception:
                        pass

                    try:
                        _addon_utils.modules_refresh()
                    except Exception:
                        pass

                    # Resolve user add-ons path.
                    addons_path = None
                    try:
                        addons_path = bpy.utils.user_resource('SCRIPTS', path="addons")
                    except TypeError:
                        try:
                            addons_path = bpy.utils.user_resource('SCRIPTS', "addons")
                        except Exception:
                            addons_path = None
                    except Exception:
                        addons_path = None

                    if not addons_path:
                        # Fallback: first addon search path.
                        try:
                            paths = list(_addon_utils.paths())
                            if paths:
                                addons_path = paths[0]
                        except Exception:
                            addons_path = None

                    if not addons_path:
                        raise RuntimeError("Unable to resolve add-on install path")

                    try:
                        os.makedirs(addons_path, exist_ok=True)
                    except Exception:
                        pass

                    target_dir = os.path.join(addons_path, "io_export_i3d_reworked")
                    if os.path.isdir(target_dir):
                        try:
                            _shutil.rmtree(target_dir)
                        except Exception:
                            pass

                    # Extract zip into the add-ons folder.
                    with _zipfile.ZipFile(temp_zip, "r") as zf:
                        zf.extractall(addons_path)

                    # Sanity check: the expected folder must exist after extraction.
                    if not os.path.isdir(target_dir):
                        raise RuntimeError("Update zip did not contain io_export_i3d_reworked folder")

                    # Purge sys.modules entries for io_export_i3d_reworked so the next enable imports fresh code from disk.
                    _purged = []
                    for _k in list(_sys.modules.keys()):
                        if _k == 'io_export_i3d_reworked' or _k.startswith('io_export_i3d_reworked.'):
                            _purged.append(_k)
                            del _sys.modules[_k]
                        elif _k.endswith('.io_export_i3d_reworked') or '.io_export_i3d_reworked.' in _k:
                            _purged.append(_k)
                            del _sys.modules[_k]

                    try:
                        _importlib.invalidate_caches()
                    except Exception:
                        pass

                    if _purged:
                        _log(f"[I3D Update] Purged sys.modules entries: {len(_purged)}")

                    # Refresh + enable.
                    try:
                        _addon_utils.modules_refresh()
                    except Exception:
                        pass

                    try:
                        _addon_utils.enable("io_export_i3d_reworked", default_set=True)
                    except Exception:
                        pass

                    # Force a full UI redraw so newly-added panels/tools appear without requiring a Blender restart.
                    try:
                        _schedule_full_ui_redraw_all_windows(iterations=6, first_interval=0.25, step_interval=0.15)
                    except Exception:
                        pass

                    # Record which update channel the current add-on build came from.
                    try:
                        prefs2 = _get_addon_prefs()
                        if prefs2 is not None:
                            prefs2.update_installed_channel = str(getattr(prefs2, 'update_channel', 'STABLE')).upper()
                            prefs2.update_installed_by_updater = True
                    except Exception:
                        pass

                    try:
                        bpy.ops.wm.save_userpref()
                    except Exception:
                        pass

                    try:
                        _set_last_update_action(prefs2 if prefs2 is not None else prefs, "Update successfully installed")
                    except Exception:
                        pass

                    _I3D_UPDATE_INSTALL_ERROR = None
                    return None

                except Exception as e:
                    _I3D_UPDATE_INSTALL_ERROR = f"Install failed: {e}"
                    try:
                        _set_last_update_action(prefs, "Update install failed")
                    except Exception:
                        pass
                    try:
                        bpy.ops.i3d.update_failed_dialog('INVOKE_DEFAULT')
                    except Exception:
                        pass
                    return None

            return None

        try:
            bpy.app.timers.register(_timer, first_interval=0.1)
        except Exception as e:
            _I3D_UPDATE_INSTALL_ERROR = f"Unable to schedule install: {e}"
            try:
                bpy.ops.i3d.update_failed_dialog('INVOKE_DEFAULT')
            except Exception:
                pass

        return {'FINISHED'}

class I3D_OT_UpdateFailedDialog(bpy.types.Operator):
    bl_idname = "i3d.update_failed_dialog"
    bl_label = "Update Failed"
    bl_description = "Update Failed."
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        layout = self.layout

        header = layout.box()
        header.alert = True
        header.label(text="Auto update failed.", icon='ERROR')

        if _I3D_UPDATE_INSTALL_ERROR:
            layout.label(text=str(_I3D_UPDATE_INSTALL_ERROR))

        r = _I3D_UPDATE_OFFER or {}

        row = layout.row()
        if r.get("download_primary"):
            op = row.operator("i3d.open_url", text="Manual Download (Primary)", icon='URL')
            op.url = r.get("download_primary")

        if r.get("download_secondary"):
            op = row.operator("i3d.open_url", text="Manual Download (Secondary)", icon='URL')
            op.url = r.get("download_secondary")

        if r.get("notes_url"):
            op = layout.operator("i3d.open_url", text="Release Notes", icon='HELP')
            op.url = r.get("notes_url")

        warn = layout.box()
        warn.alert = True
        warn.label(text="After installing manually, no quit needed.", icon='INFO')

    def execute(self, context):
        return {'FINISHED'}


def register():
    bpy.utils.register_class(I3D_OT_UpdateCheckInfoDialog)
    bpy.utils.register_class(I3D_OT_OpenURL)
    bpy.utils.register_class(I3D_OT_CheckForUpdates)
    bpy.utils.register_class(I3D_OT_UpdateCheckProgress)
    bpy.utils.register_class(I3D_OT_ChannelSwitchDialog)
    bpy.utils.register_class(I3D_OT_ChannelSwitchCommit)
    bpy.utils.register_class(I3D_OT_ChannelSwitchCancel)
    bpy.utils.register_class(I3D_OT_UpdateAvailableDialog)
    bpy.utils.register_class(I3D_OT_SkipUpdateVersion)
    bpy.utils.register_class(I3D_OT_DisableUpdateChecks)
    bpy.utils.register_class(I3D_OT_PerformUpdate)
    bpy.utils.register_class(I3D_OT_UpdateFailedDialog)

    # Run shortly after startup so we don't block registration.
    try:
        bpy.app.timers.register(_startup_timer, first_interval=2.0)
    except Exception:
        pass


def unregister():
    bpy.utils.unregister_class(I3D_OT_UpdateCheckInfoDialog)
    try:
        bpy.utils.unregister_class(I3D_OT_ChannelSwitchCancel)
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(I3D_OT_ChannelSwitchCommit)
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(I3D_OT_ChannelSwitchDialog)
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(I3D_OT_UpdateFailedDialog)
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(I3D_OT_PerformUpdate)
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(I3D_OT_DisableUpdateChecks)
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(I3D_OT_SkipUpdateVersion)
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(I3D_OT_UpdateAvailableDialog)
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(I3D_OT_UpdateCheckProgress)
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(I3D_OT_CheckForUpdates)
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(I3D_OT_OpenURL)
    except Exception:
        pass
