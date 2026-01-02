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
import os
import json

# --------------------------------------------------------------
# Persistent preferences (survive uninstall/reinstall rollbacks)
# --------------------------------------------------------------
_I3D_PREFS_CACHE_FILE = "io_export_i3d_reworked_prefs.json"

def _i3d_prefs_cache_path():
    try:
        cfg = bpy.utils.user_resource('CONFIG')
    except Exception:
        cfg = ""
    if not cfg:
        return ""
    return os.path.join(cfg, _I3D_PREFS_CACHE_FILE)

def _i3d_find_addon_prefs():
    try:
        addon_entry = bpy.context.preferences.addons.get("io_export_i3d_reworked")
        if addon_entry is None:
            for addon_key, addon_val in bpy.context.preferences.addons.items():
                if addon_key.endswith(".io_export_i3d_reworked"):
                    addon_entry = addon_val
                    break
        if addon_entry and getattr(addon_entry, "preferences", None):
            return addon_entry.preferences
    except Exception:
        pass
    return None


def _i3d_prefs_save_from_prefs(prefs):
    path = _i3d_prefs_cache_path()
    if not path:
        return
    try:
        data = {
            "game_install_path": getattr(prefs, "game_install_path", ""),
            "enable_update_checks": bool(getattr(prefs, "enable_update_checks", True)),
            "update_channel": getattr(prefs, "update_channel", "STABLE"),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def _i3d_prefs_load():
    path = _i3d_prefs_cache_path()
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}

def _i3d_prefs_restore_into_prefs(prefs):
    data = _i3d_prefs_load()
    if not data:
        return
    try:
        # Only fill in missing path; never overwrite an explicit user selection.
        if (not getattr(prefs, "game_install_path", "")) and data.get("game_install_path"):
            prefs.game_install_path = data.get("game_install_path", "")
        # Restore update flag + channel (safe defaults if missing)
        if "enable_update_checks" in data:
            prefs.enable_update_checks = bool(data.get("enable_update_checks"))
        if data.get("update_channel") in ("STABLE", "BETA", "ALPHA"):
            prefs.update_channel = data.get("update_channel")
    except Exception:
        pass

def _i3d_prefs_on_update(self, context):
    _i3d_prefs_save_from_prefs(self)


class I3DExporterAddonPreferences(bpy.types.AddonPreferences):
    """Addon preferences for GIANTS I3D Exporter.
    Stores the global Farming Simulator installation directory."""
    bl_idname = "io_export_i3d_reworked"

    game_install_path: bpy.props.StringProperty(
        name="FS25 Game Path",
        description="Path to the Farming Simulator 25 game folder",
        default="",
        subtype='DIR_PATH',
            update=_i3d_prefs_on_update,
    )

    # --------------------------------------------------------------
    # Update Checker Preferences (Opt-in)
    # --------------------------------------------------------------
    enable_update_checks: bpy.props.BoolProperty(
        name="Enable Update Checks (Internet)",
        description="Allows this add-on to access the internet to check for updates on Blender startup",
        default=True,
            update=_i3d_prefs_on_update,
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
            update=_i3d_prefs_on_update,
    )

    # Internal: remembers the previously selected update channel in the UI.
    update_channel_prev: bpy.props.StringProperty(
        name="Previous Update Channel (Internal)",
        description="Internal: previous value of the Update Channel dropdown",
        default="STABLE",
        options={'HIDDEN'},
    )

    # Internal: remembers which update channel the currently installed add-on came from.
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
        options={'HIDDEN'},
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

        # Respect Blender's "Allow Online Access"
        online_access = True
        try:
            online_access = bool(getattr(bpy.app, "online_access", True))
        except Exception:
            online_access = True

        update_box.prop(self, "enable_update_checks")

        body = update_box.column()
        body.enabled = bool(self.enable_update_checks)

        if bool(self.enable_update_checks) and not online_access:
            warn = body.box()
            warn.alert = True
            warn.label(text="Blender 'Allow Online Access' is OFF. Update checks are blocked.", icon='ERROR')

        body.prop(self, "update_channel")

        # Read-only manifest URL (not user-editable)
        url_col = body.column()
        url_col.enabled = False
        url_col.prop(self, "update_manifest_url")

        row = body.row()
        row.enabled = bool(online_access)
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
    bpy.utils.register_class(I3DExporterAddonPreferences)

    # Restore persisted prefs (survive uninstall/reinstall rollbacks)
    try:
        prefs = _i3d_find_addon_prefs()
        if prefs is not None:
            _i3d_prefs_restore_into_prefs(prefs)
            _i3d_prefs_save_from_prefs(prefs)
    except Exception:
        pass

def unregister():
    # Save prefs before unregister (best effort)
    try:
        prefs = _i3d_find_addon_prefs()
        if prefs is not None:
            _i3d_prefs_save_from_prefs(prefs)
    except Exception:
        pass

    bpy.utils.unregister_class(I3DExporterAddonPreferences)
