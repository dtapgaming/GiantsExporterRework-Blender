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

# Each update check gets a monotonically increasing ID so we can ignore late/stale thread results
# (e.g. after a 30s UI timeout, since Python threads can't be force-killed safely).
_I3D_UPDATE_NEXT_CHECK_ID = 0
_I3D_UPDATE_ACTIVE_CHECK_ID = 0
_I3D_UPDATE_ERROR_CHECK_ID = 0


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


def _begin_update_status_text(is_manual):
    global _I3D_UPDATE_STATUS_ACTIVE, _I3D_UPDATE_STATUS_START_TIME, _I3D_UPDATE_STATUS_WAS_MANUAL

    _I3D_UPDATE_STATUS_ACTIVE = True
    _I3D_UPDATE_STATUS_START_TIME = time.time()
    _I3D_UPDATE_STATUS_WAS_MANUAL = bool(is_manual)

    _set_workspace_status_text("Checking for updates...")
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
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"DTAP-I3D-Exporter/{_get_local_version_tuple()[0]}.{_get_local_version_tuple()[1]}.{_get_local_version_tuple()[2]}",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        }
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))

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
            "remote_version": remote_v,
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



class I3D_OT_UpdateCheckInfoDialog(bpy.types.Operator):
    bl_idname = "i3d.update_check_info_dialog"
    bl_label = "Update Check"
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
    bl_options = {'INTERNAL'}

    def execute(self, context):
        global _I3D_LAST_CHECK_WAS_MANUAL
        _I3D_LAST_CHECK_WAS_MANUAL = True
        _begin_update_status_text(is_manual=True)
        # Keep the info banner alive while the network fetch runs.
        _invoke_op('i3d.update_check_progress')
        self.report({'INFO'}, 'Checking for updates...')
        start_update_check(force=True)
        return {'FINISHED'}



class I3D_OT_UpdateCheckProgress(bpy.types.Operator):
    bl_idname = "i3d.update_check_progress"
    bl_label = "Update Check Progress"
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
            if not _I3D_UPDATE_STATUS_ACTIVE:
                self.cancel(context)
                return {'FINISHED'}
            self.report({'INFO'}, 'Checking for updates...')

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
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        # Snapshot offer so redraws don't lose the content.
        try:
            global _I3D_UPDATE_OFFER
            self._offer = dict(_I3D_UPDATE_OFFER or {})
        except Exception:
            self._offer = {}

        # NOTE: Flashing UI in Blender popup dialogs is redraw-limited (often only updates on mouse move).
        # Keep the rollback target styling solid instead of flashing.
        global _I3D_UPDATE_DIALOG_ACTIVE
        _I3D_UPDATE_DIALOG_ACTIVE = True

        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        layout = self.layout
        prefs = _get_addon_prefs()

        r = getattr(self, '_offer', None) or {}
        local_v = r.get("local_version", (0, 0, 0))
        remote_v = r.get("remote_version", (0, 0, 0))
        channel = str(getattr(prefs, "update_channel", "STABLE")).upper() if prefs else "STABLE"

        is_update = tuple(remote_v) > tuple(local_v)
        is_rollback = tuple(remote_v) < tuple(local_v)

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
            current_row.label(text=f"🟩 Current (installed): {_format_version(local_v)}", icon='CHECKMARK')

            # Rollback target: solid red (no flashing; popup redraws are often mouse-move driven)
            rb = vbox.box()
            rb.alert = True
            rb_row = rb.row()
            rb_row.alert = True
            rb_row.label(text=f"Rollback target: {_format_version(remote_v)}", icon='ERROR')
        else:
            layout.label(text=f"Installed: {_format_version(local_v)}")
            layout.label(text=f"Latest:    {_format_version(remote_v)}")

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

        if r.get("notes_url"):
            row = layout.row()
            op = row.operator("i3d.open_url", text="Release Notes", icon='HELP')
            op.url = r.get("notes_url")

        # Warning about OK/Cancel
        warn = layout.box()
        warn.alert = True
        warn.label(text="Use the buttons above. OK/Cancel only closes this dialog.", icon='ERROR')

        layout.separator()

        # preference actions
        if prefs is not None:
            row = layout.row()
            row.operator("i3d.disable_update_checks", text="Disable Update Checks", icon='CHECKBOX_HLT')

    
    def execute(self, context):
        # OK/Cancel just closes this dialog
        global _I3D_UPDATE_DIALOG_ACTIVE
        _I3D_UPDATE_DIALOG_ACTIVE = False
        return {'FINISHED'}

    def cancel(self, context):
        global _I3D_UPDATE_DIALOG_ACTIVE
        _I3D_UPDATE_DIALOG_ACTIVE = False


class I3D_OT_SkipUpdateVersion(bpy.types.Operator):
    bl_idname = "i3d.skip_update_version"
    bl_label = "Skip Update Version"
    bl_options = {'INTERNAL'}

    version_str: bpy.props.StringProperty(default="")

    def execute(self, context):
        prefs = _get_addon_prefs()
        channel_pref = "STABLE"
        if prefs is not None:
            # Store skip per selected channel
            channel_pref = getattr(prefs, "update_channel", "STABLE")
            if channel_pref == "ALPHA":
                prefs.update_skip_version_alpha = self.version_str
            elif channel_pref == "BETA":
                prefs.update_skip_version_beta = self.version_str
            else:
                prefs.update_skip_version_stable = self.version_str
            try:
                bpy.ops.wm.save_userpref()
            except Exception:
                pass

        # Provide visible feedback in Blender's status bar.
        try:
            self.report({'INFO'}, f"Skipped version {self.version_str} for {channel_pref} channel.")
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
    local_v = result_dict.get("local_version")

    if remote_v is None or local_v is None:
        return False

    # Respect "skip version" (per-channel)
    channel_pref = getattr(prefs, "update_channel", "STABLE")
    if channel_pref == "ALPHA":
        skip = getattr(prefs, "update_skip_version_alpha", "")
    elif channel_pref == "BETA":
        skip = getattr(prefs, "update_skip_version_beta", "")
    else:
        skip = getattr(prefs, "update_skip_version_stable", "")

    if skip:
        try:
            if skip.strip() == _format_version(remote_v):
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

    return tuple(remote_v) != tuple(local_v)



def _find_invoke_override():
    """Return a best-effort override context for invoking dialogs from timers."""
    try:
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


def _invoke_op(op_idname, invoke_type='INVOKE_DEFAULT', **kwargs):
    """Invoke an operator in the best available UI context.

    Blender 4.5+ can be picky about passing context overrides as positional args.
    Using bpy.context.temp_override is more stable than calling ops with an
    override dict positional parameter.
    """
    try:
        cat, op = op_idname.split('.', 1)
        fn = getattr(getattr(bpy.ops, cat), op)

        override = _find_invoke_override()
        if override:
            try:
                with bpy.context.temp_override(**override):
                    fn(invoke_type, **kwargs)
            except TypeError:
                # Fallback for older builds that don't support temp_override in this way.
                fn(invoke_type, **kwargs)
        else:
            fn(invoke_type, **kwargs)
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


class I3D_OT_PerformUpdate(bpy.types.Operator):
    bl_idname = "i3d.perform_update"
    bl_label = "Update Add-on"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        global _I3D_UPDATE_INSTALL_ERROR

        prefs = _get_addon_prefs()
        if prefs is None:
            return {'CANCELLED'}

        r = _I3D_UPDATE_OFFER or {}
        url_primary = r.get("download_primary")
        url_secondary = r.get("download_secondary")

        # Download ZIP (primary -> secondary)
        try:
            data, used_url = _download_zip_with_fallback(url_primary, url_secondary)
        except Exception as e:
            _I3D_UPDATE_INSTALL_ERROR = f"Download failed: {e}"
            try:
                bpy.ops.i3d.update_failed_dialog('INVOKE_DEFAULT')
            except Exception:
                pass
            return {'FINISHED'}

        # Write to temp zip
        try:
            temp_dir = getattr(bpy.app, "tempdir", None) or tempfile.gettempdir()
            temp_zip = os.path.join(temp_dir, "io_export_i3d_reworked_update.zip")
            with open(temp_zip, "wb") as f:
                f.write(data)
        except Exception as e:
            _I3D_UPDATE_INSTALL_ERROR = f"Unable to write update zip: {e}"
            try:
                bpy.ops.i3d.update_failed_dialog('INVOKE_DEFAULT')
            except Exception:
                pass
            return {'FINISHED'}

        # Install (overwrite) and re-enable
        def _install_timer():
            global _I3D_UPDATE_INSTALL_ERROR
            try:
                # Disable before overwriting
                try:
                    bpy.ops.preferences.addon_disable(module="io_export_i3d_reworked")
                except Exception:
                    pass

                try:
                    bpy.ops.preferences.addon_install(filepath=temp_zip, overwrite=True)
                except TypeError:
                    bpy.ops.preferences.addon_install(filepath=temp_zip)

                try:
                    bpy.ops.preferences.addon_enable(module="io_export_i3d_reworked")
                except Exception:
                    pass

                # Record which update channel the currently installed add-on build came from (used for ALPHA <-> BETA reinstall prompts).
                try:
                    prefs.update_installed_channel = str(getattr(prefs, 'update_channel', 'STABLE')).upper()
                    bpy.ops.wm.save_userpref()
                except Exception:
                    pass

                try:
                    bpy.ops.wm.save_userpref()
                except Exception:
                    pass

                _I3D_UPDATE_INSTALL_ERROR = None
                return None
            except Exception as e:
                _I3D_UPDATE_INSTALL_ERROR = f"Install failed: {e}"
                try:
                    bpy.ops.i3d.update_failed_dialog('INVOKE_DEFAULT')
                except Exception:
                    pass
                return None

        try:
            bpy.app.timers.register(_install_timer, first_interval=0.1)
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
        warn.label(text="After installing manually, restart Blender.", icon='INFO')

    def execute(self, context):
        return {'FINISHED'}


def register():
    bpy.utils.register_class(I3D_OT_UpdateCheckInfoDialog)
    bpy.utils.register_class(I3D_OT_OpenURL)
    bpy.utils.register_class(I3D_OT_CheckForUpdates)
    bpy.utils.register_class(I3D_OT_UpdateCheckProgress)
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