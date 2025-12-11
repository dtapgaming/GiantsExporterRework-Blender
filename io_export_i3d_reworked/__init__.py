##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
# ##### END GPL LICENSE BLOCK #####

print(__file__)

bl_info = {
    "name": "GIANTS I3D Exporter Tools Reworked",
    "author": "GIANTS Software | Dtap Gaming",
    "blender": (4, 3, 0),
    "version": (10, 0, 11),
    "location": "GIANTS I3D",
    "description": "GIANTS Utilities and Exporter Reworked for Blender 4.3+",
    "warning": "Designed for Blender 4.3 and above.",
    "wiki_url": "http://gdn.giants-software.com",
    "tracker_url": "https://discord.gg/NazY3trnnm",
    "category": "Game Engine",
}

global DCC_PLATFORM
DCC_PLATFORM = "blender"

if "bpy" in locals():
    import importlib
    importlib.reload(i3d_ui)
    importlib.reload(dcc)
    importlib.reload(i3d_export)
else:
    from . import i3d_ui
    from . import dcc
    from . import i3d_export

import bpy
from bpy.app.handlers import persistent
from .dcc.dccBlender import getFormattedNodeName
from .i3d_globals import I3DExporterAddonPreferences

import sys

# Session flags (reset at every Blender process)
_i3d_reworked_conflict_popup_scheduled = False
_i3d_reworked_restart_popup_scheduled = False


# -------------------------------------------------------
# QUIT / SAVE & QUIT POPUPS
# -------------------------------------------------------

class I3DREWORKED_OT_quit_now(bpy.types.Operator):
    bl_idname = "i3d_reworked.quit_now"
    bl_label = "Quit Blender"

    def execute(self, context):
        bpy.ops.wm.quit_blender()
        return {'FINISHED'}


class I3DREWORKED_OT_save_and_quit(bpy.types.Operator):
    bl_idname = "i3d_reworked.save_and_quit"
    bl_label = "Save & Quit Blender"

    def execute(self, context):
        # If file already saved, we can save+quit immediately
        if bpy.data.filepath:
            bpy.ops.wm.save_mainfile()
            bpy.ops.wm.quit_blender()
            return {'FINISHED'}

        # Otherwise, file has never been saved — show Save As first
        def _invoke_save_as():
            try:
                bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT')
            except RuntimeError:
                # UI not ready, retry
                return 0.25

            # After user picks filename, quit automatically
            def _quit_after_save():
                # user finished saving when filepath is no longer empty
                if bpy.data.filepath:
                    bpy.ops.wm.quit_blender()
                    return None
                return 0.25

            bpy.app.timers.register(_quit_after_save, first_interval=0.25)
            return None

        bpy.app.timers.register(_invoke_save_as, first_interval=0.25)
        return {'FINISHED'}


class I3DREWORKED_OT_cancel_quit(bpy.types.Operator):
    bl_idname = "i3d_reworked.cancel_quit"
    bl_label = "Cancel"

    def execute(self, context):
        return {'CANCELLED'}


def i3d_reworked_show_restart_popup():
    """
    Triggers a Quit / Save & Quit popup exactly once per Blender session.
    """
    global _i3d_reworked_restart_popup_scheduled

    if _i3d_reworked_restart_popup_scheduled:
        return None
    _i3d_reworked_restart_popup_scheduled = True

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(
            text="Blender should quit and be reopened for changes to fully apply.",
            icon='INFO'
        )
        col.separator()
        col.label(text="Choose an option below:")
        col.separator()
        col.operator("i3d_reworked.quit_now", text="Quit Blender")
        col.operator("i3d_reworked.save_and_quit", text="Save & Quit Blender")
        col.operator("i3d_reworked.cancel_quit", text="Cancel")

    bpy.context.window_manager.popup_menu(
        draw, title="Restart Recommended", icon='INFO'
    )
    return None


# -------------------------------------------------------
# ADDON CONFLICT POPUP (GIANTS Exporter + Delta Tool)
# -------------------------------------------------------

class I3DREWORKED_OT_conflict_popup(bpy.types.Operator):
    bl_idname = "i3d_reworked.conflict_popup"
    bl_label = "Addon Conflict Detected"

    giants_module: bpy.props.StringProperty(default="")
    delta_module: bpy.props.StringProperty(default="")

    def execute(self, context):
        import addon_utils

        # GIANTS official exporter conflict
        if self.giants_module:
            addon_utils.disable(self.giants_module, default_set=True)
            self.report({'INFO'}, "Disabled GIANTS I3D Exporter Tools addon.")

        # Original Delta → Vertex Color conflict
        elif self.delta_module:
            addon_utils.disable(self.delta_module, default_set=True)
            self.report(
                {'INFO'},
                "Disabled 'Positiona Delta to Vertex Color' addon."
            )
        else:
            self.report({'WARNING'}, "No conflicting addon module specified.")
            return {'CANCELLED'}

        # Once conflict is resolved → show restart popup
        bpy.app.timers.register(
            lambda: i3d_reworked_show_restart_popup(),
            first_interval=0.5
        )

        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        col = self.layout.column(align=True)

        if self.giants_module:
            col.label(
                text="The official GIANTS I3D Exporter Tools addon is active.",
                icon='ERROR'
            )
            col.label(text="Both exporters cannot run at the same time.")
            col.separator()
            col.label(text="Click OK to disable the GIANTS addon.")

        elif self.delta_module:
            col.label(
                text="The original 'Positiona Delta to Vertex Color' addon is active.",
                icon='ERROR'
            )
            col.label(text="Giants I3D Exporter REWORKED and Delta > Vertex Color")
            col.label(text="cannot run at the same time. It is built into Giants I3D Reworked")
            col.separator()
            col.label(text="Click OK to disable the old Delta > Vertex Color addon.")

        else:
            col.label(
                text="A conflicting addon is active.",
                icon='ERROR'
            )


# -------------------------------------------------------
# CONFLICT CHECK LOGIC
# -------------------------------------------------------

def _i3d_reworked_check_conflict_and_schedule_popup():
    """
    Checks if GIANTS & REWORKED exporters are both enabled.
    Returns True if conflict was detected.
    """
    global _i3d_reworked_conflict_popup_scheduled

    import addon_utils

    prefs = bpy.context.preferences
    if __package__ not in prefs.addons:
        return False

    giants_enabled = False
    giants_module = None

    for mod in addon_utils.modules():
        info = addon_utils.module_bl_info(mod)
        if info.get("name") == "GIANTS I3D Exporter Tools":
            loaded, enabled = addon_utils.check(mod.__name__)
            if enabled:
                giants_enabled = True
                giants_module = mod.__name__
            break

    if not giants_enabled:
        return False

    # Already shown this session
    if _i3d_reworked_conflict_popup_scheduled:
        return True

    _i3d_reworked_conflict_popup_scheduled = True

    def _show():
        try:
            bpy.ops.i3d_reworked.conflict_popup(
                "INVOKE_DEFAULT",
                giants_module=giants_module,
                delta_module=""
            )
        except RuntimeError:
            return 0.25
        return None

    bpy.app.timers.register(_show, first_interval=0.25)
    return True


def _i3d_reworked_check_delta_conflict_and_schedule_popup():
    """
    Checks if the original 'Positiona Delta to Vertex Color' addon
    is enabled alongside this reworked exporter.
    Returns True if conflict was detected.
    """
    global _i3d_reworked_conflict_popup_scheduled

    import addon_utils

    prefs = bpy.context.preferences
    if __package__ not in prefs.addons:
        return False

    delta_enabled = False
    delta_module = None

    for mod in addon_utils.modules():
        info = addon_utils.module_bl_info(mod)
        if info.get("name") == "Positiona Delta to Vertex Color":
            loaded, enabled = addon_utils.check(mod.__name__)
            if enabled:
                delta_enabled = True
                delta_module = mod.__name__
            break

    if not delta_enabled:
        return False

    # Already scheduled a conflict popup this session
    if _i3d_reworked_conflict_popup_scheduled:
        return True

    _i3d_reworked_conflict_popup_scheduled = True

    def _show():
        try:
            bpy.ops.i3d_reworked.conflict_popup(
                "INVOKE_DEFAULT",
                giants_module="",
                delta_module=delta_module
            )
        except RuntimeError:
            return 0.25
        return None

    bpy.app.timers.register(_show, first_interval=0.25)
    return True


# -------------------------------------------------------
# STARTUP HANDLER
# -------------------------------------------------------

@persistent
def i3d_reworked_conflict_handler(scene):
    """
    Runs at Blender startup (load_post) to warn if conflicting addons are enabled.
    Does NOT show restart popup, only the conflict popup.
    """
    _i3d_reworked_check_conflict_and_schedule_popup()
    _i3d_reworked_check_delta_conflict_and_schedule_popup()


# -------------------------------------------------------
# ADDON MENU & PROPERTIES
# -------------------------------------------------------

class I3D_MT_ExporterMenu(bpy.types.Menu):
    bl_label = "GIANTS I3D"
    bl_idname = "I3D_MT_ExporterMenu"

    def draw(self, context):
        layout = self.layout
        layout.label(text=f"v {bl_info['version']}")
        layout.operator("i3d.menuexport")


def draw_I3D_Menu(self, context):
    self.layout.menu(I3D_MT_ExporterMenu.bl_idname)


def update_xml_config_id(self, context):
    if self.I3D_XMLconfigBool:
        self.I3D_XMLconfigID = getFormattedNodeName(self.name)
    else:
        self.I3D_XMLconfigID = ''


# -------------------------------------------------------
# REGISTER
# -------------------------------------------------------

def register():
    global _i3d_reworked_conflict_popup_scheduled
    global _i3d_reworked_restart_popup_scheduled

    _i3d_reworked_conflict_popup_scheduled = False
    _i3d_reworked_restart_popup_scheduled = False

    bpy.utils.register_class(I3DExporterAddonPreferences)
    bpy.utils.register_class(I3DREWORKED_OT_quit_now)
    bpy.utils.register_class(I3DREWORKED_OT_save_and_quit)
    bpy.utils.register_class(I3DREWORKED_OT_cancel_quit)
    bpy.utils.register_class(I3DREWORKED_OT_conflict_popup)
    bpy.utils.register_class(I3D_MT_ExporterMenu)

    bpy.types.STATUSBAR_HT_header.prepend(draw_I3D_Menu)

    bpy.types.Object.I3D_XMLconfigBool = bpy.props.BoolProperty(
        default=False, update=update_xml_config_id)
    bpy.types.Object.I3D_XMLconfigID = bpy.props.StringProperty(default='')
    bpy.types.EditBone.I3D_XMLconfigBool = bpy.props.BoolProperty(
        default=False, update=update_xml_config_id)
    bpy.types.EditBone.I3D_XMLconfigID = bpy.props.StringProperty(default='')

    i3d_ui.register()

    # startup conflict detection
    if i3d_reworked_conflict_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(i3d_reworked_conflict_handler)

    # conflict check during initial install
    _i3d_reworked_check_conflict_and_schedule_popup()
    _i3d_reworked_check_delta_conflict_and_schedule_popup()


# -------------------------------------------------------
# UNREGISTER
# -------------------------------------------------------

def unregister():
    if i3d_reworked_conflict_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(i3d_reworked_conflict_handler)

    bpy.types.STATUSBAR_HT_header.remove(draw_I3D_Menu)

    bpy.utils.unregister_class(I3D_MT_ExporterMenu)
    bpy.utils.unregister_class(I3DREWORKED_OT_conflict_popup)
    bpy.utils.unregister_class(I3DREWORKED_OT_cancel_quit)
    bpy.utils.unregister_class(I3DREWORKED_OT_save_and_quit)
    bpy.utils.unregister_class(I3DREWORKED_OT_quit_now)
    bpy.utils.unregister_class(I3DExporterAddonPreferences)

    i3d_ui.unregister()

    del bpy.types.Object.I3D_XMLconfigBool
    del bpy.types.Object.I3D_XMLconfigID
    del bpy.types.EditBone.I3D_XMLconfigBool
    del bpy.types.EditBone.I3D_XMLconfigID


if __name__ == "__main__":
    register()
