# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

print(__file__)

bl_info = {
    "name": "GIANTS I3D Exporter REWORKED",
    "author": "GIANTS Software | Dtap Gaming",
    "blender": (4, 3, 0),
    "version": (10, 0, 17),
    "location": "GIANTS I3D",
    "description": "GIANTS Utilities and Exporter Reworked for Blender 4.3+",
    "warning": "Designed for Blender 4.3 and above.",
    "wiki_url": "http://gdn.giants-software.com",
    "tracker_url": "https://discord.gg/NazY3trnnm",
    "category": "Game Engine",}
# NOTE: Blender only supports a 3-part add-on version in bl_info['version'].
# This build number is used ONLY by the updater to distinguish rebuilds
# of the same semantic version (e.g. 10.0.18 build 1 vs build 2).
I3D_REWORKED_BUILD = 63
global DCC_PLATFORM
DCC_PLATFORM = "blender"

if "bpy" in locals():
    import importlib
    importlib.reload(i3d_ui)
    try:
        importlib.reload(i3d_colorLibrary)
    except Exception:
        pass
    importlib.reload(dcc)
    importlib.reload(i3d_export)
    importlib.reload(i3d_globals)
    try:
        importlib.reload(updateChecker)
    except Exception:
        pass
else:
    from . import i3d_ui
    from . import i3d_colorLibrary
    from . import dcc
    from . import i3d_export
    from . import i3d_globals
    from .helpers import updateChecker
import bpy
from .dcc.dccBlender import getFormattedNodeName


class I3D_MT_Menu( bpy.types.Menu ):
    """  GUI element in bottom left corner to open the GIANTS I3D Exporter """

    bl_label = "GIANTS I3D"
    bl_idname = "I3D_MT_Menu"
    def draw( self, context ):
        """pop up menu when clicked"""

        layout = self.layout

        v = bl_info.get("version", (0, 0, 0))
        try:
            v_str = f"{int(v[0])}.{int(v[1])}.{int(v[2])}"
        except Exception:
            v_str = str(v)

        try:
            b_int = int(globals().get("I3D_REWORKED_BUILD", 0))
        except Exception:
            b_int = 0

        layout.label(text=f"v {v_str}.{b_int}")

        # Installed/selected update channel info + quick update tools
        try:
            from .helpers import updateChecker as _uc
            prefs = _uc._get_addon_prefs()
        except Exception:
            prefs = None

        if prefs is not None:
            try:
                installed_ch = str(getattr(prefs, "update_installed_channel", getattr(prefs, "update_channel", "STABLE")) or "STABLE").upper()
            except Exception:
                installed_ch = "STABLE"

            try:
                selected_ch = str(getattr(prefs, "update_channel", "STABLE") or "STABLE").upper()
            except Exception:
                selected_ch = installed_ch

            layout.separator()
            installed_known = bool(getattr(prefs, "update_installed_by_updater", False))
            installed_display = installed_ch.title() if installed_known else "Custom (Manual Install)"
            layout.label(text=f"Installed channel: {installed_display}")
            if selected_ch != installed_ch:
                layout.label(text=f"Pref channel: {selected_ch.title()}")

            layout.operator("i3d.check_for_updates_installed", text="Check for Updates", icon='FILE_REFRESH')

            try:
                last = str(getattr(prefs, "update_last_action", "") or "")
            except Exception:
                last = ""
            if last:
                layout.label(text=f"Last: {last}")
            try:
                status_msg = str(getattr(_uc, "_I3D_UPDATE_STATUS_MESSAGE", "") or "")
                if getattr(_uc, "_I3D_UPDATE_STATUS_ACTIVE", False) and status_msg:
                    layout.label(text="Status: " + status_msg)
            except Exception:
                pass


            # Show skipped version info for the effective channel (with undo).
            # - If installed by updater: show the installed channel.
            # - If manual install: show the preferred channel (this is where Skip stores values).
            try:
                skip_ch = installed_ch if installed_known else selected_ch
            except Exception:
                skip_ch = selected_ch

            try:
                if skip_ch == "ALPHA":
                    sv = str(getattr(prefs, "update_skip_version_alpha", "") or "")
                    sb = int(getattr(prefs, "update_skip_build_alpha", 0) or 0)
                elif skip_ch == "BETA":
                    sv = str(getattr(prefs, "update_skip_version_beta", "") or "")
                    sb = int(getattr(prefs, "update_skip_build_beta", 0) or 0)
                else:
                    sv = str(getattr(prefs, "update_skip_version_stable", "") or "")
                    sb = int(getattr(prefs, "update_skip_build_stable", 0) or 0)
            except Exception:
                sv, sb = "", 0

            if sv:
                layout.label(text=f"Skipped: {sv}.{int(sb or 0)}")
                op = layout.operator("i3d.clear_skipped_update_menu", text="Undo Skip Version", icon='LOOP_BACK')
                op.channel = skip_ch

        layout.separator()
        layout.operator("i3d.open_addon_preferences_menu", text="Addon Preferences", icon='PREFERENCES')


def draw_I3D_Menu( self, context ):
    """ Draw I3D Menu """

    self.layout.menu( I3D_MT_Menu.bl_idname )



class I3D_OT_CheckForUpdatesInstalled(bpy.types.Operator):
    """Check for updates using the installed channel (STABLE/BETA/ALPHA)."""
    bl_idname = "i3d.check_for_updates_installed"
    bl_label = "Check for Updates"
    bl_description = "Check for Updates."
    bl_options = {'INTERNAL'}

    def execute(self, context):
        try:
            from .helpers import updateChecker as _uc
        except Exception as e:
            self.report({'ERROR'}, f"UpdateChecker missing: {e}")
            return {'CANCELLED'}

        prefs = _uc._get_addon_prefs()
        if prefs is None:
            self.report({'ERROR'}, "Add-on preferences not available")
            return {'CANCELLED'}

        try:
            installed = str(getattr(prefs, "update_installed_channel", getattr(prefs, "update_channel", "STABLE")) or "STABLE").upper()
        except Exception:
            installed = "STABLE"

        try:
            old = str(getattr(prefs, "update_channel", "STABLE") or "STABLE").upper()
        except Exception:
            old = "STABLE"

        installed_known = bool(getattr(prefs, "update_installed_by_updater", False))
        channel_to_check = installed if installed_known else old
        # If this build was installed manually, we cannot reliably know its channel; check the preferred channel instead.

        # Temporarily run the check on the installed channel without triggering channel-switch prompts.
        try:
            _uc._set_update_channel_internal(prefs, channel_to_check)
        except Exception:
            try:
                prefs.update_channel = channel_to_check
            except Exception:
                pass

        try:
            bpy.ops.i3d.check_for_updates()
        except Exception as e:
            self.report({'ERROR'}, f"Unable to start update check: {e}")
            # best-effort restore
            try:
                _uc._set_update_channel_internal(prefs, old)
            except Exception:
                try:
                    prefs.update_channel = old
                except Exception:
                    pass
            return {'CANCELLED'}

        # Restore channel immediately (thread already captured the channel_key).
        try:
            _uc._set_update_channel_internal(prefs, old)
        except Exception:
            try:
                prefs.update_channel = old
            except Exception:
                pass

        try:
            prefs.update_channel_prev = old
        except Exception:
            pass

        return {'FINISHED'}


class I3D_OT_OpenAddonPreferencesMenu(bpy.types.Operator):
    """Open the Add-on Preferences for GIANTS I3D Exporter REWORKED."""
    bl_idname = "i3d.open_addon_preferences_menu"
    bl_label = "Addon Preferences"
    bl_options = {'INTERNAL'}
    bl_description = "Open the Add-on Preferences for GIANTS I3D Exporter REWORKED"

    def execute(self, context):
        try:
            bpy.ops.screen.userpref_show()
        except Exception:
            pass

        module_name = __package__ or "io_export_i3d_reworked"
        try:
            bpy.ops.preferences.addon_show(module=module_name)
        except Exception as e:
            try:
                bpy.ops.preferences.addon_show(module="io_export_i3d_reworked")
            except Exception as e2:
                self.report({'ERROR'}, f"Unable to open add-on preferences: {e2 or e}")
                return {'CANCELLED'}

        return {'FINISHED'}


class I3D_OT_ClearSkippedUpdateMenu(bpy.types.Operator):
    """Clear the skipped update version/build for a channel (menu helper)."""
    bl_idname = "i3d.clear_skipped_update_menu"
    bl_label = "Undo Skipped Update"
    bl_description = "Undo Skipped Update: clears/removes the current selection."
    bl_options = {'INTERNAL'}

    channel: bpy.props.StringProperty(default="")

    def execute(self, context):
        try:
            from .helpers import updateChecker as _uc
        except Exception as e:
            self.report({'ERROR'}, f"UpdateChecker missing: {e}")
            return {'CANCELLED'}

        prefs = _uc._get_addon_prefs()
        if prefs is None:
            self.report({'ERROR'}, "Add-on preferences not available")
            return {'CANCELLED'}

        ch = str(self.channel or getattr(prefs, "update_installed_channel", getattr(prefs, "update_channel", "STABLE")) or "STABLE").upper()

        try:
            if ch == "ALPHA":
                prefs.update_skip_version_alpha = ""
                prefs.update_skip_build_alpha = 0
            elif ch == "BETA":
                prefs.update_skip_version_beta = ""
                prefs.update_skip_build_beta = 0
            else:
                prefs.update_skip_version_stable = ""
                prefs.update_skip_build_stable = 0
        except Exception:
            pass

        try:
            _uc.set_last_update_action(f"Undo skip: cleared {ch.title()} skip")
        except Exception:
            try:
                prefs.update_last_action = f"Undo skip: cleared {ch.title()} skip"
            except Exception:
                pass

        try:
            bpy.ops.wm.save_userpref()
        except Exception:
            pass

        self.report({'INFO'}, f"Cleared skipped update for {ch} channel.")
        return {'FINISHED'}


def update_xml_config_id(self, context):
    if self.I3D_XMLconfigBool:
        self.I3D_XMLconfigID = getFormattedNodeName(self.name)
    else:
        self.I3D_XMLconfigID = ''

#-------------------------------------------------------------------------------
#   Register
#-------------------------------------------------------------------------------
def register():
    # TODO(jdellsperger): Why are these properties defined so radically diferent than all the
    # others? As far as I can tell, those are also "per node" properties and could be defined
    # in the same way as all the others...
    bpy.types.Object.I3D_XMLconfigBool = bpy.props.BoolProperty(default=False,
                                                                update=update_xml_config_id)
    bpy.types.Object.I3D_XMLconfigID = bpy.props.StringProperty(default='')
    bpy.types.EditBone.I3D_XMLconfigBool = bpy.props.BoolProperty(default=False,
                                                                  update=update_xml_config_id)
    bpy.types.EditBone.I3D_XMLconfigID = bpy.props.StringProperty(default='')
    i3d_globals.register()
    i3d_colorLibrary.register()
    i3d_ui.register()
    updateChecker.register()
    bpy.utils.register_class( I3D_MT_Menu )
    bpy.utils.register_class( I3D_OT_CheckForUpdatesInstalled )
    bpy.utils.register_class( I3D_OT_OpenAddonPreferencesMenu )
    bpy.utils.register_class( I3D_OT_ClearSkippedUpdateMenu )
    bpy.types.STATUSBAR_HT_header.prepend(draw_I3D_Menu)


def unregister():
    try:
        bpy.types.STATUSBAR_HT_header.remove(draw_I3D_Menu)
    except (ValueError, AttributeError):
        pass
    bpy.utils.unregister_class( I3D_OT_ClearSkippedUpdateMenu )
    bpy.utils.unregister_class( I3D_OT_OpenAddonPreferencesMenu )
    bpy.utils.unregister_class( I3D_OT_CheckForUpdatesInstalled )
    bpy.utils.unregister_class( I3D_MT_Menu )
    i3d_ui.unregister()
    i3d_colorLibrary.unregister()
    updateChecker.unregister()
    i3d_globals.unregister()
    del bpy.types.Object.I3D_XMLconfigBool
    del bpy.types.Object.I3D_XMLconfigID
    del bpy.types.EditBone.I3D_XMLconfigBool
    del bpy.types.EditBone.I3D_XMLconfigID

if __name__ == "__main__":
    register()