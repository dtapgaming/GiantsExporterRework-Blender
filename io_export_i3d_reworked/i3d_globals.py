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

        # Respect Blender's "Allow Online Access"
        online_access = True
        try:
            online_access = bool(getattr(bpy.app, "online_access", True))
        except Exception:
            online_access = True

        row = update_box.row()
        row.prop(self, "enable_update_checks")

        body = update_box.column()
        body.enabled = bool(self.enable_update_checks)

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
    bpy.utils.register_class(I3D_OT_EnableOnlineAccess)
    bpy.utils.register_class(I3D_OT_GuideEnableOnlineAccess)
    bpy.utils.register_class(I3DExporterAddonPreferences)

def unregister():
    bpy.utils.unregister_class(I3DExporterAddonPreferences)
    bpy.utils.unregister_class(I3D_OT_GuideEnableOnlineAccess)
    bpy.utils.unregister_class(I3D_OT_EnableOnlineAccess)
