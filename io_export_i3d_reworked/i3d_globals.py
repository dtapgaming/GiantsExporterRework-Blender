#-------------------------------------------------------------------------------
#   Global variables and methods
#-------------------------------------------------------------------------------
import time
from .util import logUtil

g_meshCache = {}

#-------------------------------------------------------------------------------
#   Debugging Profiling
#-------------------------------------------------------------------------------
g_logPerformance = True
g_logPerformanceStartTime = None

def I3DLogPerformanceInit():
    """ inits start time """
    global g_logPerformanceStartTime
    g_logPerformanceStartTime = time.time()

def I3DLogPerformance(text):
    """ Prints time elapsed """
    global g_logPerformanceStartTime
    if g_logPerformanceStartTime is not None:
        time_now = time.time()
        #dcc.UIShowError('time elapsed {0:.2f} seconds at '.format(time_now - g_logPerformanceStartTime) + text)
        logUtil.ActionLog.addMessage('time elapsed {0:.2f} seconds at '.format(time_now - g_logPerformanceStartTime) + text, messageType = 'ERROR')


# to profile with internal tools
# import cProfile, pstats, io
# from pstats import SortKey
#     pr = cProfile.Profile()
#     pr.enable()
#     # execute code to profile
#     pr.disable()
#     s = io.StringIO()
#     sortby = SortKey.CUMULATIVE
#     ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
#     ps.print_stats()
#     dcc.UIShowError(s.getvalue())

# how to load and use a c++ library
# # install msgpack
# import ensurepip
# ensurepip.bootstrap()

# import subprocess
# import sys

# try:
#     #subprocess.check_call([bpy.app.binary_path_python, "-m", "ensurepip", "--user"])
#     subprocess.check_call([sys.executable, "-m", "ensurepip", "--user"])
# except subprocess.CalledProcessError as e:
#     pass

# try:
#     #subprocess.check_call([bpy.app.binary_path_python, "-m", "pip", "install", "msgpack"])
#     subprocess.check_call([sys.executable, "-m", "pip", "install", "msgpack"])
# except subprocess.CalledProcessError as e:
#     pass

#import sys
#sys.path.append("c:/users/nicolas wrobel/appdata/roaming/python/python310/site-packages")

import bpy

# Tracks the last Update Channel selection (runtime) so ALPHA<->BETA switches
# can be detected even if the saved 'update_channel_prev' marker is stale.
_I3D_LAST_UPDATE_CHANNEL_VALUE = None

# --------------------------------------------------------------
# Online Access Guidance (Blender Preferences > Get Extensions)
# --------------------------------------------------------------
ONLINE_ACCESS_FLASH_DURATION = 6
ONLINE_ACCESS_FLASH_INTERVAL = 0.35
_online_access_flash_counter = 0
_online_access_flash_state = False
_online_access_watch_counter = 0

def _i3d_online_access_flash_timer():
    global _online_access_flash_counter, _online_access_flash_state
    if _online_access_flash_counter <= 0:
        return None

    _online_access_flash_state = not _online_access_flash_state
    _online_access_flash_counter -= 1

    # Redraw Preferences & Properties areas
    try:
        wm = bpy.context.window_manager
        for win in wm.windows:
            for area in win.screen.areas:
                if area.type in {"PREFERENCES", "PROPERTIES"}:
                    area.tag_redraw()
    except Exception:
        pass

    return ONLINE_ACCESS_FLASH_INTERVAL


def _i3d_start_online_access_flash():
    global _online_access_flash_counter, _online_access_flash_state
    _online_access_flash_counter = int(ONLINE_ACCESS_FLASH_DURATION / ONLINE_ACCESS_FLASH_INTERVAL)
    _online_access_flash_state = True
    try:
        bpy.app.timers.register(_i3d_online_access_flash_timer)
    except Exception:
        pass


def _i3d_open_preferences_extensions():
    # Open Preferences window & try to jump to Extensions / Get Extensions.
    try:
        bpy.ops.screen.userpref_show('INVOKE_DEFAULT')
    except Exception:
        pass
    try:
        bpy.context.preferences.active_section = 'EXTENSIONS'
    except Exception:
        # Older / different builds may not have this enum value.
        pass


def _i3d_open_preferences_addon(module_name: str):
    try:
        bpy.ops.preferences.addon_show(module=module_name)
    except Exception:
        # Fallback: open preferences window (user can navigate manually)
        try:
            bpy.ops.screen.userpref_show('INVOKE_DEFAULT')
        except Exception:
            pass


def _i3d_online_access_watch_timer():
    global _online_access_watch_counter
    _online_access_watch_counter += 1

    # Stop after ~2 minutes to avoid a "forever" timer.
    if _online_access_watch_counter > 240:
        _online_access_watch_counter = 0
        return None

    try:
        online = bool(getattr(bpy.app, "online_access", False))
    except Exception:
        online = False

    if online:
        _online_access_watch_counter = 0
        _i3d_open_preferences_addon("io_export_i3d_reworked")
        _i3d_start_online_access_flash()
        return None

    return 0.5


class I3D_OT_EnableOnlineAccess(bpy.types.Operator):
    bl_idname = "i3d.enable_online_access"
    bl_label = "Activate Internet"
    bl_description = "Enable Blender's 'Allow Online Access' setting"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        # Try to enable online access directly (preferred UX).
        try:
            context.preferences.system.use_online_access = True
            try:
                bpy.ops.wm.save_userpref()
            except Exception:
                pass
        except Exception:
            pass

        _i3d_start_online_access_flash()

        # If Blender still reports online access disabled, auto-launch the guide.
        try:
            if bool(getattr(bpy.app, "online_access", True)):
                self.report({'INFO'}, "Online access enabled. Update checks are now available.")
                return {'FINISHED'}
        except Exception:
            # If we can't query it, assume it's enabled.
            self.report({'INFO'}, "Online access enabled. Update checks are now available.")
            return {'FINISHED'}

        # Still disabled -> guidance flow.
        try:
            bpy.ops.i3d.guide_enable_online_access('INVOKE_DEFAULT')
        except Exception:
            _i3d_open_preferences_extensions()

        self.report({'WARNING'}, "Unable to enable online access automatically. Please enable it in Preferences > Get Extensions.")
        return {'FINISHED'}



class I3D_OT_GuideEnableOnlineAccess(bpy.types.Operator):
    bl_idname = "i3d.guide_enable_online_access"
    bl_label = "Show me how to Enable Internet Access"
    bl_description = "Open Blender preferences to the Get Extensions area so you can enable online access"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        _i3d_open_preferences_extensions()
        _i3d_start_online_access_flash()

        # Watch for the user enabling online access, then return to this add-on prefs.
        global _online_access_watch_counter
        _online_access_watch_counter = 0
        try:
            bpy.app.timers.register(_i3d_online_access_watch_timer, first_interval=0.5)
        except Exception:
            pass

        self.report({'INFO'}, "Enable 'Allow Online Access' in Preferences > Get Extensions.")
        return {'FINISHED'}



def _i3d_on_update_channel_changed(self, context):
    """Triggered when the Update Channel dropdown changes.

    We only intercept ALPHA <-> BETA switches to force an explicit install prompt.
    """
    global _I3D_LAST_UPDATE_CHANNEL_VALUE

    # If this change was triggered internally (e.g. revert), ignore.
    try:
        from .helpers import updateChecker as _i3d_updateChecker
        if getattr(_i3d_updateChecker, "_I3D_CHANNEL_SWITCH_INTERNAL_SET", False):
            try:
                cur = str(getattr(self, "update_channel", "STABLE") or "STABLE").upper()
                self.update_channel_prev = cur
                _I3D_LAST_UPDATE_CHANNEL_VALUE = cur
            except Exception:
                pass
            return
    except Exception:
        pass

    new_channel = str(getattr(self, "update_channel", "STABLE") or "STABLE").upper()

    # Determine the previous value as reliably as possible.
    # IMPORTANT: Prefer the stored marker on the preferences object first, because the
    # runtime tracker can be stale (e.g. on the first change after launching Blender).
    old_channel = str(getattr(self, "update_channel_prev", "") or "").upper()
    if old_channel not in ("STABLE", "BETA", "ALPHA") or old_channel == new_channel:
        try:
            if _I3D_LAST_UPDATE_CHANNEL_VALUE in ("STABLE", "BETA", "ALPHA") and _I3D_LAST_UPDATE_CHANNEL_VALUE != new_channel:
                old_channel = _I3D_LAST_UPDATE_CHANNEL_VALUE
        except Exception:
            pass
    # First-time init: if we still don't have a reliable previous value, set it and return.
    if old_channel not in ("STABLE", "BETA", "ALPHA"):
        try:
            self.update_channel_prev = new_channel
            _I3D_LAST_UPDATE_CHANNEL_VALUE = new_channel
            bpy.ops.wm.save_userpref()
        except Exception:
            pass
        return

    # Only intercept ALPHA <-> BETA (no STABLE involvement).
    if (old_channel in ("ALPHA", "BETA")) and (new_channel in ("ALPHA", "BETA")) and (new_channel != old_channel):
        try:
            from .helpers import updateChecker as _i3d_updateChecker
            _i3d_updateChecker.request_alpha_beta_switch(old_channel=old_channel, new_channel=new_channel, context=context)
        except Exception:
            # If we cannot show the prompt, revert selection back to previous.
            try:
                from .helpers import updateChecker as _i3d_updateChecker
                _i3d_updateChecker._set_update_channel_internal(self, old_channel)
            except Exception:
                try:
                    self.update_channel = old_channel
                except Exception:
                    pass
        finally:
            # Do not advance the runtime tracker until the user commits or cancels the channel switch.
            # The commit/cancel paths update this via internal-set or explicit assignment.
            pass
        return

    # Non-intercepted changes: commit the "previous" marker.
    try:
        self.update_channel_prev = new_channel
        _I3D_LAST_UPDATE_CHANNEL_VALUE = new_channel
        bpy.ops.wm.save_userpref()
    except Exception:
        pass



class I3DExporterAddonPreferences(bpy.types.AddonPreferences):
    """Addon preferences for GIANTS I3D Exporter.
    Stores the global Farming Simulator installation directory."""
    bl_idname = "io_export_i3d_reworked"

    game_install_path: bpy.props.StringProperty(
        name="FS25 Game Path",
        description="Path to the Farming Simulator 25 game folder",
        default="",
        subtype='DIR_PATH',
    )

    # --------------------------------------------------------------
    # Update Checker Preferences (Opt-in)
    # --------------------------------------------------------------
    enable_update_checks: bpy.props.BoolProperty(
        name="Enable Update Checks (Internet)",
        description="Allows this add-on to access the internet to check for updates on Blender startup",
        default=False,
    )

    update_channel: bpy.props.EnumProperty(
        name="Update Channel",
        description="Which update channel to check",
        items=[
            ("STABLE", "Stable", "Stable releases"),
            ("BETA", "Beta", "Beta/pre-release builds"),
            ("ALPHA", "Alpha", "Alpha/dev builds"),
        ],
        default="STABLE",
        update=_i3d_on_update_channel_changed,
    )



    # Internal: remembers the previously selected update channel in the UI.
    # Used to detect ALPHA <-> BETA switches and prompt for a forced install even when the version matches.
    update_channel_prev: bpy.props.StringProperty(
        name="Previous Update Channel (Internal)",
        description="Internal: previous value of the Update Channel dropdown",
        default="STABLE",
        options={'HIDDEN'},
    )
    # Internal: remembers which update channel the currently installed add-on came from.
    # Used to force a reinstall prompt when switching between ALPHA <-> BETA even if the version number is identical.
    update_installed_channel: bpy.props.EnumProperty(
        name="Installed Channel (Internal)",
        description="Internal: which update channel the currently installed add-on build came from",
        items=[
            ("STABLE", "Stable", "Stable releases"),
            ("BETA", "Beta", "Beta/pre-release builds"),
            ("ALPHA", "Alpha", "Alpha/dev builds"),
        ],
        default="STABLE",
        options={'HIDDEN'},
    )


    update_manifest_url: bpy.props.StringProperty(
        name="Update Manifest URL",
        description="URL to a JSON file describing the latest versions for each channel",
        default="https://i3dexportupdatechecker.dtapgaming.com",
    )



    update_manifest_url_fallback: bpy.props.StringProperty(
        name="Update Manifest URL (Fallback)",
        description="Fallback URL used if the primary manifest URL fails (timeout/offline).",
        default="https://raw.githubusercontent.com/dtapgaming/GiantsExporterRework-Blender/main/i3dexport_latest.json",
    )
    update_skip_version_stable: bpy.props.StringProperty(
        name="Skip Version (Stable)",
        description="Internal: skip update prompts for this stable version",
        default="",
        options={'HIDDEN'},
    )

    update_skip_version_beta: bpy.props.StringProperty(
        name="Skip Version (Beta)",
        description="Internal: skip update prompts for this beta version",
        default="",
        options={'HIDDEN'},
    )

    update_skip_version_alpha: bpy.props.StringProperty(
        name="Skip Version (Alpha)",
        description="Internal: skip update prompts for this alpha version",
        default="",
        options={'HIDDEN'},
    )

    # --------------------------------------------------------------
    # First-run / Update Init Marker
    # --------------------------------------------------------------
    # Used to detect when the add-on was first enabled (or updated) so we can
    # show a one-time "restart required" dialog.
    # Stored in preferences so it survives restarts.
    initialized_version: bpy.props.StringProperty(
        name="Initialized Version",
        default="",
        options={'HIDDEN'},
    )

    def draw(self, context):
        layout = self.layout

        layout.label(text="Farming Simulator 25 Game Path")

        # =========================
        # Highlight in RED if empty
        # =========================
        if not self.game_install_path:
            box = layout.box()
            box.alert = True  # red warning style box
            col = box.column()
            col.label(text="⚠  Farming Simulator 25 Directory is EMPTY  ⚠", icon='ERROR')
            col.prop(self, "game_install_path", text="")
        else:
            # Normal field (not red)
            layout.prop(self, "game_install_path")
        # --------------------------------------------------------------
        # Update Checker (Opt-in)
        # --------------------------------------------------------------
        layout.separator()
        layout.label(text="Update Checker")

        update_box = layout.box()

        # While we are gathering build information for an ALPHA<->BETA channel switch,
        # lock (grey out) the update controls so the user can't spam changes or fire
        # overlapping queries.
        channel_switch_busy = False
        try:
            from .helpers import updateChecker as _i3d_updateChecker
            channel_switch_busy = bool(getattr(_i3d_updateChecker, "is_channel_switch_in_progress", lambda: False)())
        except Exception:
            channel_switch_busy = False
        if channel_switch_busy:
            # While gathering (or after gathering) channel switch build info, we lock the normal
            # update controls and instead present a Commit/Cancel workflow directly in the prefs UI.
            offer = {}
            err = ""
            ready = False
            try:
                from .helpers import updateChecker as _i3d_updateChecker
                offer = dict(getattr(_i3d_updateChecker, "get_channel_switch_offer", lambda: {})() or {})
                err = str(getattr(_i3d_updateChecker, "get_channel_switch_error", lambda: "")() or "")
                ready = bool(getattr(_i3d_updateChecker, "is_channel_switch_ready", lambda: False)())
            except Exception:
                offer = {}
                err = ""
                ready = False

            # Harden readiness detection: in some Blender contexts the helper
            # "is_channel_switch_ready" can return False even though the offer
            # payload is already populated (thread completed, offer contains
            # download URL / remote version). Prefer the actual offer content.
            if (not err) and isinstance(offer, dict) and offer.get("error"):
                err = str(offer.get("error"))
            if (not ready) and isinstance(offer, dict):
                try:
                    if (
                        (offer.get("remote_version") is not None)
                        or bool(offer.get("download_primary") or offer.get("download_secondary"))
                        or bool(offer.get("notes") or offer.get("notes_url"))
                        or bool(offer.get("message"))
                        or bool(offer.get("error"))
                    ):
                        ready = True
                except Exception:
                    pass

            if err:
                busy_box = update_box.box()
                busy_box.alert = True
                busy_box.label(text="⚠ Channel switch failed while gathering build info.", icon='ERROR')
                busy_box.label(text=str(err)[:220])
                row = busy_box.row(align=True)
                op = row.operator("i3d.channel_switch_cancel", text="OK (Revert)", icon='CANCEL')
                op.old_channel = str(offer.get("old_channel", getattr(self, "update_channel_prev", "STABLE"))).upper()
            elif not ready:
                busy_box = update_box.box()
                busy_box.label(text="Please wait while we get information on that Update Channel...", icon='TIME')
                busy_box.label(text="Update controls are temporarily locked.", icon='LOCKED')

                # Provide an explicit escape hatch so users can back out of a
                # pending ALPHA<->BETA switch if the network is slow/unreachable.
                row = busy_box.row(align=True)
                row.scale_y = 1.15
                op = row.operator("i3d.channel_switch_cancel", text="Cancel (Revert)", icon='CANCEL')
                op.old_channel = str(offer.get("old_channel", getattr(self, "update_channel_prev", "STABLE"))).upper()
            else:
                # Build info ready: show Commit/Cancel UI (no popup).
                old_ch = str(offer.get("old_channel", getattr(self, "update_channel_prev", "STABLE"))).upper()
                new_ch = str(offer.get("new_channel", getattr(self, "update_channel", "STABLE"))).upper()

                ready_box = update_box.box()
                ready_box.alert = True
                ready_box.label(text=f"Pending switch: {old_ch.title()} → {new_ch.title()}", icon='ERROR')
                ready_box.label(text="To apply this change, you must install now and then quit Blender.", icon='INFO')

                msg = offer.get("message")
                if msg:
                    ready_box.label(text=str(msg)[:240])

                notes = offer.get("notes")
                if notes:
                    notes_lines = []
                    try:
                        notes_lines = [ln.strip() for ln in str(notes).replace("\r", "").split("\n") if ln.strip()]
                    except Exception:
                        notes_lines = []
                    if notes_lines:
                        nb = ready_box.box()
                        nb.label(text="Patch Notes:", icon='TEXT')
                        for ln in notes_lines[:12]:
                            nb.label(text=ln[:140])
                        if len(notes_lines) > 12:
                            nb.label(text="(More in Release Notes)", icon='DOT')

                if offer.get("notes_url"):
                    row = ready_box.row()
                    op = row.operator("i3d.open_url", text="Release Notes", icon='HELP')
                    op.url = offer.get("notes_url")

                btn = ready_box.row(align=True)
                btn.scale_y = 1.2
                c = btn.operator("i3d.channel_switch_commit", text=f"Commit {new_ch.title()} Install", icon='CHECKMARK')
                c.old_channel = old_ch
                c.new_channel = new_ch
                x = btn.operator("i3d.channel_switch_cancel", text="Cancel (Revert)", icon='CANCEL')
                x.old_channel = old_ch

        # Respect Blender's "Allow Online Access"
        online_access = True
        try:
            online_access = bool(getattr(bpy.app, "online_access", True))
        except Exception:
            online_access = True

        row = update_box.row()
        row.enabled = (not channel_switch_busy)
        row.prop(self, "enable_update_checks")

        body = update_box.column()
        body.enabled = bool(self.enable_update_checks) and (not channel_switch_busy)

        if bool(self.enable_update_checks) and not online_access:
            warn = body.box()
            warn.alert = True

            # Flash the warning a bit when we guide the user here.
            header_row = warn.row()
            header_row.alert = bool(_online_access_flash_state)
            header_row.label(text="Blender 'Allow Online Access' is OFF. Update checks are blocked.", icon='ERROR')

            btn_row = warn.row()
            btn_row.scale_y = 1.2
            btn_row.operator("i3d.enable_online_access", text="Activate Internet", icon='URL')


        body.prop(self, "update_channel")

        # Read-only manifest URLs (not user-editable)
        url_col = body.column()
        url_col.enabled = False
        url_col.prop(self, "update_manifest_url")

        row = body.row()
        row.enabled = bool(online_access) and (not channel_switch_busy)
        row.operator("i3d.check_for_updates", text="Check Now", icon='FILE_REFRESH')

        # Show installed version
        try:
            import importlib
            mod = importlib.import_module("io_export_i3d_reworked")
            v = mod.bl_info.get("version", (0, 0, 0))
            body.label(text="Installed Version: {:d}.{:d}.{:d}".format(int(v[0]), int(v[1]), int(v[2])))
        except Exception:
            pass




def register():
    bpy.utils.register_class(I3D_OT_EnableOnlineAccess)
    bpy.utils.register_class(I3D_OT_GuideEnableOnlineAccess)
    bpy.utils.register_class(I3DExporterAddonPreferences)

    # Ensure the "previous channel" marker is synced on first run after installing this version.
    try:
        prefs = bpy.context.preferences.addons["io_export_i3d_reworked"].preferences
        cur = str(getattr(prefs, "update_channel", "STABLE") or "STABLE").upper()

        try:
            global _I3D_LAST_UPDATE_CHANNEL_VALUE
            _I3D_LAST_UPDATE_CHANNEL_VALUE = cur
        except Exception:
            pass
        prev = str(getattr(prefs, "update_channel_prev", "") or "").upper()
        if prev not in ("STABLE", "BETA", "ALPHA"):
            prefs.update_channel_prev = cur
        # If the add-on was already set to ALPHA/BETA before this marker existed, keep them in sync
        # so the first ALPHA <-> BETA switch is detected correctly.
        if cur in ("ALPHA", "BETA") and prefs.update_channel_prev == "STABLE":
            prefs.update_channel_prev = cur
        bpy.ops.wm.save_userpref()
    except Exception:
        pass


def unregister():
    bpy.utils.unregister_class(I3DExporterAddonPreferences)
    bpy.utils.unregister_class(I3D_OT_GuideEnableOnlineAccess)
    bpy.utils.unregister_class(I3D_OT_EnableOnlineAccess)
