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

import bpy, bpy_extras
from bpy.app.handlers import persistent
import bmesh
import platform
import os.path
import re
import addon_utils
import bpy.utils.previews
from os import listdir
from os.path import isfile, join
from . import i3d_export
from . import i3d_changelog
from . import dcc as dcc
from .util import i3d_directoryFinderUtil as dirf
from .helpers.pathHelper import getGamePath, resolveGiantsPath
from .util import logUtil, pathUtil, stringUtil, selectionUtil, i3d_shaderUtil
from .dcc import UINT_MAX_AS_STRING, dccBlender, g_colMaskFlags, g_collisionBitmaskAttributes, TYPE_BOOL, TYPE_INT, TYPE_FLOAT, TYPE_ENUM, TYPE_STRING, TYPE_STRING_UINT

# Color Library (My Color Library / Giants Library)
from . import i3d_colorLibrary


import math
import time
from mathutils import Vector, Matrix, Euler


from .tools import *

# ----------------------------
# UI performance: cache IndexPath calculation
# ----------------------------
_I3D_INDEXPATH_CACHE = {"key": None, "value": "", "t": 0.0}

def _i3d_get_indexpath_cached(context, obj, bone_name: str = "") -> str:
    """Cache the expensive node index path computation.
    Scrolling the sidebar triggers many redraws; computing IndexPath each time can lag large scenes.
    """
    global _I3D_INDEXPATH_CACHE
    if obj is None:
        _I3D_INDEXPATH_CACHE["key"] = None
        _I3D_INDEXPATH_CACHE["value"] = ""
        _I3D_INDEXPATH_CACHE["t"] = time.monotonic()
        return "N/A"

    scene = context.scene
    parent = getattr(obj, "parent", None)
    parent_name = parent.name if parent else ""
    parent_child_count = len(parent.children) if parent else 0

    # Cheap invalidation signature + time-based refresh.
    key = (obj.name, bone_name or "", parent_name, len(scene.objects), parent_child_count)

    now = time.monotonic()
    if _I3D_INDEXPATH_CACHE["key"] == key and (now - _I3D_INDEXPATH_CACHE["t"]) < 1.0:
        return _I3D_INDEXPATH_CACHE["value"] or "N/A"

    try:
        if bone_name:
            val = dcc.I3DgetNodeIndex(obj.name, bone_name)
        else:
            val = dcc.I3DgetNodeIndex(obj.name)
    except Exception:
        val = ""

    _I3D_INDEXPATH_CACHE["key"] = key
    _I3D_INDEXPATH_CACHE["value"] = val
    _I3D_INDEXPATH_CACHE["t"] = now
    return val or "N/A"


# --- Add-on conflict detection (GIANTS official exporter / original Delta->Vertex tool) ---
_I3D_CONFLICT_POPUP_SHOWN = False

_I3D_ABORT_PENDING = False
_I3D_ABORT_SAVE_PREFS = False
def _i3d_find_enabled_addon_by_bl_info_name(target_name: str):
    for mod in addon_utils.modules():
        try:
            if getattr(mod, "bl_info", {}).get("name") == target_name:
                enabled, loaded = addon_utils.check(mod.__name__)
                if enabled:
                    return mod.__name__
        except Exception:
            continue
    return None

def _i3d_get_enabled_conflicts():
    conflicts = []
    giants_mod = _i3d_find_enabled_addon_by_bl_info_name("GIANTS I3D Exporter Tools")
    if giants_mod:
        conflicts.append(("GIANTS I3D Exporter Tools", giants_mod))
    delta_mod = _i3d_find_enabled_addon_by_bl_info_name("Positiona Delta to Vertex Color")
    if delta_mod:
        conflicts.append(("Positiona Delta to Vertex Color", delta_mod))
    return conflicts




# ----------------------------------------------------------------------------
# Draw-error throttling: Blender will call panel draw many times per second.
# If a draw exception occurs, printing every time floods the console.
# ----------------------------------------------------------------------------
_I3D_DRAW_FAIL_CACHE = {}  # tag -> last error signature

def _i3d_print_draw_fail_once(tag: str, e: Exception):
    try:
        sig = f"{type(e).__name__}: {e}"
        if _I3D_DRAW_FAIL_CACHE.get(tag) == sig:
            return
        _I3D_DRAW_FAIL_CACHE[tag] = sig
    except Exception:
        pass
    print(f"[{tag}] draw failed: {e}")

class I3D_OT_ReopenConflictDialog(bpy.types.Operator):
    bl_idname = "i3d.reopen_conflict_dialog"
    bl_label = "Reopen Conflict Dialog"
    bl_description = "Reopen Conflict Dialog: opens the related window or resource."
    bl_options = {'INTERNAL'}

    def execute(self, context):
        global _I3D_CONFLICT_POPUP_SHOWN
        _I3D_CONFLICT_POPUP_SHOWN = False

        def _open():
            try:
                bpy.ops.i3d.addon_conflict_dialog('INVOKE_DEFAULT')
            except Exception as e:
                print(f"Unable to reopen conflict dialog: {e}")
            return None

        bpy.app.timers.register(_open, first_interval=0.1)
        return {'FINISHED'}





class I3D_OT_AddonConflictDialog(bpy.types.Operator):
    bl_idname = "i3d.addon_conflict_dialog"
    bl_label = "Add-on Conflict Detected"
    bl_description = "Add-on Conflict Detected."
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        global _I3D_CONFLICT_POPUP_SHOWN
        _I3D_CONFLICT_POPUP_SHOWN = True
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Conflicting add-ons are enabled:", icon='ERROR')

        for name, mod in _i3d_get_enabled_conflicts():
            box = layout.box()
            box.alert = True
            box.label(text=f"{name}  (module: {mod})", icon='CANCEL')

        layout.separator()
        layout.label(text="Recommended: disable conflicts to avoid add-on issues.", icon='INFO')

        row = layout.row()
        row.operator("i3d.resolve_addon_conflicts", text="Disable Conflicts", icon='REMOVE')

        row = layout.row()
        op = row.operator("preferences.addon_show", text="Open Add-on Preferences", icon="PREFERENCES")
        op.module = "io_export_i3d_reworked"

        layout.separator()

        if _I3D_ABORT_PENDING:
            pending_box = layout.box()
            pending_box.alert = True
            pending_row = pending_box.row()
            pending_row.label(text="ABORT REQUESTED: close this dialog to complete uninstall.", icon='ERROR')
        else:
            row = layout.row()
            row.scale_y = 1.1
            abort = row.operator("i3d.abort_installation", text="Abort Installation", icon='CANCEL')
            abort.use_save_preferences = False
        warning_box = layout.box()
        warning_box.alert = True

        warning_row = warning_box.row()
        warning_row.label(text="WARNING: Use the buttons above to resolve this.", icon='ERROR')

        warning_row = warning_box.row()
        warning_row.label(text="OK/Cancel only closes this dialog.")

        warning_row = warning_box.row()
        warning_row.label(text="Conflicts stay active; add-ons may not work.")

    def execute(self, context):
        return {'FINISHED'}


class I3D_OT_ResolveAddonConflicts(bpy.types.Operator):
    bl_idname = "i3d.resolve_addon_conflicts"
    bl_label = "Resolve Add-on Conflicts"
    bl_description = "Resolve Add-on Conflicts."
    bl_options = {'INTERNAL'}

    def execute(self, context):
        conflicts = _i3d_get_enabled_conflicts()

        for _name, mod in conflicts:
            try:
                bpy.ops.preferences.addon_disable(module=mod)
            except Exception as e:
                print(f"Unable to disable add-on {mod}: {e}")

        # Save preferences if we changed anything
        try:
            bpy.ops.wm.save_userpref()
        except Exception as e:
            print(f"Unable to save user preferences: {e}")

        return {'FINISHED'}




_I3D_ABORT_SAVE_PREFS = False

def _i3d_is_conflict_dialog_open():
    """Best-effort detection for whether our conflict dialog is still on screen."""
    try:
        for op in bpy.context.window_manager.operators:
            if getattr(op, "bl_idname", None) == "i3d.addon_conflict_dialog":
                return True
    except Exception:
        pass
    return False


def _i3d_abort_installation_when_safe():
    """Abort/uninstall must not happen while our dialog UI is still alive (tooltips can crash Blender)."""
    global _I3D_ABORT_PENDING, _I3D_ABORT_SAVE_PREFS
    import os
    import shutil

    # Wait until the conflict dialog is fully closed.
    if _i3d_is_conflict_dialog_open():
        return 0.25

    # Also wait until the mouse is not hovering our dialog (best-effort).
    # If Blender still has a tooltip being generated for our buttons, removing now can crash.
    # We can't directly query tooltip state, so we just give it a short grace period.
    # (Timer will only reach here once the dialog is closed.)
    # ----

    # Disable this add-on first
    try:
        bpy.ops.preferences.addon_disable(module="io_export_i3d_reworked")
    except Exception as e:
        print(f"Abort Installation: unable to disable add-on io_export_i3d_reworked: {e}")

    # Try Blender's built-in remove operator (preferred)
    removed = False
    try:
        bpy.ops.preferences.addon_remove(module="io_export_i3d_reworked")
        removed = True
    except Exception as e:
        print(f"Abort Installation: unable to remove add-on via preferences.addon_remove: {e}")

    # Fallback: best-effort delete of the add-on folder
    if not removed:
        try:
            addon_dir = os.path.dirname(__file__)
            shutil.rmtree(addon_dir, ignore_errors=False)
        except Exception as e:
            print(f"Abort Installation: unable to delete add-on folder: {e}")

    if _I3D_ABORT_SAVE_PREFS:
        try:
            bpy.ops.wm.save_userpref()
        except Exception as e:
            print(f"Abort Installation: unable to save user preferences: {e}")

    _I3D_ABORT_SAVE_PREFS = False
    _I3D_ABORT_PENDING = False
    return None


class I3D_OT_AbortInstallation(bpy.types.Operator):
    bl_idname = "i3d.abort_installation"
    bl_label = "Abort Installation"
    bl_description = "Abort Installation."
    bl_options = {'INTERNAL'}

    use_save_preferences: bpy.props.BoolProperty(
        name="Save Preferences",
        description="If enabled, user preferences will be saved after disabling/removing the add-on.",
        default=False
    )

    def execute(self, context):
        global _I3D_ABORT_SAVE_PREFS

        # Cache before any disable/remove work happens (RNA can disappear if we disable immediately)
        _I3D_ABORT_SAVE_PREFS = bool(getattr(self, "use_save_preferences", False))

        # Run the disable/remove on a short timer so this operator can finish cleanly first
        global _I3D_ABORT_PENDING
        _I3D_ABORT_PENDING = True

        bpy.app.timers.register(_i3d_abort_installation_when_safe, first_interval=0.25)

        return {'FINISHED'}


def _i3d_conflict_check_timer():
    global _I3D_CONFLICT_POPUP_SHOWN
    if _I3D_CONFLICT_POPUP_SHOWN:
        return None

    conflicts = _i3d_get_enabled_conflicts()
    if conflicts:
        try:
            bpy.ops.i3d.addon_conflict_dialog('INVOKE_DEFAULT')
        except Exception as e:
            print(f"Unable to show conflict dialog: {e}")
    return None

# --- Delta Bake Flash Logic ---
FLASH_DURATION = 4
FLASH_INTERVAL = 0.2
_flash_counter = 0
_flash_state = False

def flash_timer():
    global _flash_counter, _flash_state
    if _flash_counter <= 0:
        return None  # stop timer

    _flash_state = not _flash_state
    _flash_counter -= 1

    # Only redraw PROPERTIES areas
    for area in bpy.context.screen.areas:
        if area.type == "PROPERTIES":
            area.tag_redraw()

    return FLASH_INTERVAL


class I3D_OT_ShowDeltaBakeLocation(bpy.types.Operator):
    bl_idname = "i3d.show_delta_bake_location"
    bl_label = "Show Delta Bake Button"
    bl_description = "Highlights the real Delta Bake button location"

    def execute(self, context):

        # Find an already existing properties editor
        props_area = None
        for area in context.screen.areas:
            if area.type == "PROPERTIES":
                props_area = area
                break

        # If user has a Properties Editor open, switch to DATA tab
        if props_area is not None:
            try:
                props_area.spaces.active.context = 'DATA'
            except:
                pass  # Safe fallback if DATA context fails (rare)

        # Start flashing
        global _flash_counter, _flash_state
        _flash_counter = FLASH_DURATION * 2  # toggle = half flash
        _flash_state = True

        bpy.app.timers.register(flash_timer)

        return {'FINISHED'}


#trying to use lxml package. Fallback is standard xml package
g_usingLXML = True
try:
    from lxml import etree as xml_ET
except:
    import xml.etree.cElementTree as xml_ET
    g_usingLXML = False

g_dynamicGUIClsDict = {}
g_modalsRunning = False


# --------------------------------------------------------------
# Shader folder auto-initialization (session start / file load)
# --------------------------------------------------------------
g_autoShaderInitEnabled = True
_g_autoShaderInitDoneScenes = set()
_g_autoShaderInitAttempts = {}



# --------------------------------------------------------------
# Selected material auto-sync + legacy customShader normalization
# --------------------------------------------------------------
_I3D_LAST_ACTIVE_OBJECT_NAME = None
_I3D_LAST_ACTIVE_MATERIAL_NAME = None

def i3d_normalize_customshader_value(value):
    """Convert legacy absolute shader paths to $data/shaders/... tokens."""
    if not isinstance(value, str):
        return None

    v = value.strip()
    if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
        v = v[1:-1]

    # Normalize slashes for parsing
    v_norm = v.replace('\\', '/')
    v_norm = re.sub(r'/{2,}', '/', v_norm)

    # Already tokenized
    if v_norm.startswith('$'):
        return v_norm

    low = v_norm.lower()

    # Common absolute/relative patterns
    needle = '/data/shaders/'
    pos = low.find(needle)
    if pos == -1:
        # also accept relative 'data/shaders/...'
        if low.startswith('data/shaders/'):
            tail = v_norm[len('data/shaders/'):]
            tail = tail.lstrip('/')
            tail = re.sub(r'/{2,}', '/', tail)
            return f"$data/shaders/{tail}" if tail else None
        return None

    tail = v_norm[pos + len(needle):]
    tail = tail.lstrip('/')
    tail = re.sub(r'/{2,}', '/', tail)

    if not tail:
        return None

    return f"$data/shaders/{tail}"

@persistent
def i3d_selected_material_sync_handler(scene, depsgraph):
    """Keep Selected Material dropdown synced to the active object's *active* material slot.

    This makes the Shader Setup tab follow the Material Properties panel selection when
    a mesh has multiple materials.
    """
    global _I3D_LAST_ACTIVE_OBJECT_NAME, _I3D_LAST_ACTIVE_MATERIAL_NAME
    global g_disableSelectedMaterialEnumUpdateCallback

    try:
        settings = bpy.context.scene.I3D_UIexportSettings
    except Exception:
        return

    try:
        activeObject = bpy.context.active_object
        if not isinstance(activeObject, bpy.types.Object):
            activeObject = None
    except Exception:
        activeObject = None

    obj_name = activeObject.name if activeObject is not None else ''
    activeMat = None
    if activeObject is not None:
        # Prefer the *active* material slot (changes when user clicks another slot in Properties).
        try:
            activeMat = getattr(activeObject, 'active_material', None)
        except Exception:
            activeMat = None

        # If the active slot has no material, try resolving via index.
        if activeMat is None:
            try:
                slots = getattr(activeObject, 'material_slots', None)
                if slots and len(slots) > 0:
                    idx = int(getattr(activeObject, 'active_material_index', 0))
                    if idx < 0:
                        idx = 0
                    if idx >= len(slots):
                        idx = len(slots) - 1
                    activeMat = slots[idx].material
            except Exception:
                activeMat = None

        # Final fallback: first non-empty slot.
        if activeMat is None:
            try:
                slots = getattr(activeObject, 'material_slots', None)
                if slots:
                    for ms in slots:
                        if ms is not None and ms.material is not None:
                            activeMat = ms.material
                            break
            except Exception:
                activeMat = None

    mat_name = activeMat.name if activeMat is not None else 'None'

    # Throttle: only act on real changes
    if obj_name == _I3D_LAST_ACTIVE_OBJECT_NAME and mat_name == _I3D_LAST_ACTIVE_MATERIAL_NAME:
        return
    _I3D_LAST_ACTIVE_OBJECT_NAME = obj_name
    _I3D_LAST_ACTIVE_MATERIAL_NAME = mat_name

    # Convert legacy absolute customShader paths to tokens (old .blend files)
    if activeMat is not None:
        try:
            if 'customShader' in activeMat:
                old_val = activeMat['customShader']
                new_val = i3d_normalize_customshader_value(old_val)
                if new_val and new_val != old_val:
                    activeMat['customShader'] = new_val
        except Exception:
            pass

    # Sync the dropdown
    try:
        if settings.i3D_selectedMaterialEnum != mat_name:
            g_disableSelectedMaterialEnumUpdateCallback = True
            try:
                settings.i3D_selectedMaterialEnum = mat_name
            except Exception:
                settings.i3D_selectedMaterialEnum = 'None'
            g_disableSelectedMaterialEnumUpdateCallback = False
    except Exception:
        pass

# --------------------------------------------------------------
# Safe UI bootstrap (Blender 5+): never call bpy.ops from draw()
# --------------------------------------------------------------
_I3D_BOOTSTRAP_SCHEDULED = False

def _i3d_find_override(area_type="VIEW_3D"):
    wm = bpy.context.window_manager
    if wm is None:
        return None

    for win in wm.windows:
        scr = win.screen
        if scr is None:
            continue
        for area in scr.areas:
            if area.type != area_type:
                continue
            for region in area.regions:
                if region.type == "WINDOW":
                    return {"window": win, "screen": scr, "area": area, "region": region}
    return None


def _i3d_bootstrap_timer():
    global _I3D_BOOTSTRAP_SCHEDULED, g_modalsRunning

    if g_modalsRunning:
        _I3D_BOOTSTRAP_SCHEDULED = False
        return None

    wm = bpy.context.window_manager
    if wm is None or not wm.windows:
        return 0.25  # retry soon

    try:
        override = _i3d_find_override("VIEW_3D") or _i3d_find_override("PROPERTIES")
        if override:
            with bpy.context.temp_override(**override):
                bpy.ops.i3d.active_object('INVOKE_DEFAULT')
                bpy.ops.i3d.predef_check('INVOKE_DEFAULT')
        else:
            bpy.ops.i3d.active_object('INVOKE_DEFAULT')
            bpy.ops.i3d.predef_check('INVOKE_DEFAULT')

        g_modalsRunning = True

    except RuntimeError:
        return 0.25  # context not ready yet, retry
    except Exception as e:
        print(e)
        _I3D_BOOTSTRAP_SCHEDULED = False
        return None

    # Force redraw so panels appear immediately
    try:
        for win in wm.windows:
            for area in win.screen.areas:
                area.tag_redraw()
    except Exception:
        pass

    _I3D_BOOTSTRAP_SCHEDULED = False
    return None


def i3d_schedule_bootstrap():
    global _I3D_BOOTSTRAP_SCHEDULED, g_modalsRunning
    if g_modalsRunning:
        return
    if _I3D_BOOTSTRAP_SCHEDULED:
        return
    _I3D_BOOTSTRAP_SCHEDULED = True
    bpy.app.timers.register(_i3d_bootstrap_timer, first_interval=0.1)


#g_materialTemplateThumbnails = None
g_loadedMaterialTemplates = {'templates': {}}
g_selectedMaterialTemplateCategory = None
g_disableTemplatedParameterUpdatedCallback = False
g_disableParameterTemplateSelectedCallback = False
g_disableSelectedMaterialEnumUpdateCallback = False
g_disableTemplateSelectedForParameterCallback = False
g_disableShaderVariationEnumUpdateCallback = False


def prettify_name(name):
    """Convert CamelCase to readable format: e.g., wood1Cedar -> Wood 1 Cedar"""
    words = re.findall(r'[A-Z][a-z]*|[a-z]+|[0-9]+', name)
    return ' '.join(words).capitalize()


def extractXMLShaderData():
    gamePath = getGamePath()
    if gamePath is None or gamePath == "":
        gamePath = bpy.context.scene.I3D_UIexportSettings.i3D_gameLocationDisplay
    dirPath = resolveGiantsPath(bpy.context.scene.I3D_UIexportSettings.i3D_shaderFolderLocation, gamePath)
    #dirPath = bpy.path.abspath(dirPath)
    fileName = bpy.context.scene.I3D_UIexportSettings.i3D_shaderEnum

    xmlFile = dirPath + os.sep + fileName

    return i3d_shaderUtil.extractXMLShaderData(xmlFile)

def toggleAutoAssign(self, context):
    if self.UI_autoAssign:
        # dcc.I3DSaveObjectAttributes()
        dcc.I3DLoadObjectAttributes()
    else:
        dcc.I3DSaveObjectAttributes()

def updateFromPredefinePhysic(self, context):
    """Update function if a predefined Setting is selected"""

    predefineName = self.i3D_predefinedPhysic
    if predefineName == 'NONE':
        return

    # reset all settings to default
    for key, value in dcc.SETTINGS_ATTRIBUTES.items():
        setattr(self, key, value['defaultValue'])

    for key, value in dcc.I3DgetPredefinePhysicAttr(predefineName).items():
        setattr(self, key, value)

    context.scene.I3D_UIexportSettings.i3D_selectedPredefined = [tup[1] for tup in dcc.UIgetPredefinePhysicItems(self,context) if tup[0] == predefineName][0]
    self.i3D_predefinedPhysic = 'NONE'

def updateFromPredefineNonPhysic(self, context):
    """Update function if a predefined Setting is selected"""

    predefineName = self.i3D_predefinedNonPhysic
    if predefineName == 'NONE':
        return

    # reset all settings to default
    for key, value in dcc.SETTINGS_ATTRIBUTES.items():
        setattr(self, key, value['defaultValue'])

    for key, value in dcc.I3DgetPredefineNonPhysicAttr(predefineName).items():
        setattr(self, key, value)

    context.scene.I3D_UIexportSettings.i3D_selectedPredefined = [tup[1] for tup in dcc.UIgetPredefineNonPhysicItems(self,context) if tup[0] == predefineName][0]
    self.i3D_predefinedNonPhysic = 'NONE'

def updateFromPredefineCollision(self, context):
    """Update function if a predefined Collision is selected"""

    predefineName = self.i3D_predefinedCollision
    if predefineName == 'NONE' or predefineName == '':
        return

    groupDec, maskDec = g_colMaskFlags.getPresetGroupAndMask(self.i3D_predefinedCollision, asHex=False)

    self.i3D_collisionFilterMask = str(maskDec)
    self.i3D_collisionFilterGroup = str(groupDec)

def lightUseShadowUpdate(self, context):
    softShadowParams = [
        "i3D_softShadowsLightSize",
        "i3D_softShadowsLightDistance",
        "i3D_softShadowsDepthBiasFactor",
        "i3D_softShadowsMaxPenumbraSize"
    ]
    if not self.UI_lightUseShadow:
        for softShadowParam in softShadowParams:
            setattr(self, softShadowParam, dcc.SETTINGS_ATTRIBUTES[softShadowParam]['defaultValue'])
    else:
        node = self.i3D_nodeName
        nodeData = bpy.data.objects[node]
        for softShadowParam in softShadowParams:
            if softShadowParam in nodeData:
                setattr(self, softShadowParam, nodeData[softShadowParam])
            else:
                setattr(self, softShadowParam, dcc.SETTINGS_ATTRIBUTES[softShadowParam]['defaultValue'])

def lightScatteringUpdate(self, context):
    node = self.i3D_nodeName
    nodeObj = bpy.data.objects[node]
    if "i3D_isLightScattering" in context.scene.I3D_UIexportSettings:
        if context.scene.I3D_UIexportSettings.i3D_isLightScattering:
            if nodeObj.type == 'LIGHT' and nodeObj.data.type == 'SPOT':
                spot_size = nodeObj.data.spot_size
                # Convert the cone angle from radians to degrees
                spot_size_degrees = spot_size * (180.0 / 3.141592653589793)
                setattr(self, "i3D_lightScatteringConeAngle", spot_size_degrees)
        else:
            setattr(self, "i3D_lightScatteringConeAngle", 40)

def lightScatteringIntensityUpdate(self, context):
    if "i3D_lightScatteringIntensity" in context.scene.I3D_UIexportSettings:
        intensity = context.scene.I3D_UIexportSettings.i3D_lightScatteringIntensity
        if intensity < 0:
            setattr(self, "i3D_lightScatteringIntensity", 0)
        elif intensity > 50:
            setattr(self, "i3D_lightScatteringIntensity", 50)

def lightScatteringConeAngleUpdate(self, context):
    node = self.i3D_nodeName
    nodeObj = bpy.data.objects[node]
    if "i3D_lightScatteringConeAngle" in context.scene.I3D_UIexportSettings:
        if nodeObj.type == 'LIGHT' and nodeObj.data.type == 'SPOT':
            myNewSize = context.scene.I3D_UIexportSettings.i3D_lightScatteringConeAngle
            spot_size = nodeObj.data.spot_size
            # Convert the cone angle from radians to degrees
            spot_size_degrees = spot_size * (180.0 / 3.141592653589793)
            if myNewSize > spot_size_degrees:
                setattr(self, "i3D_lightScatteringConeAngle", spot_size_degrees)
            elif myNewSize < 0:
                setattr(self, "i3D_lightScatteringConeAngle", 0)

def setExportRelativePath(self, context):
    """Update function for dynamic GUI behavior"""

    if self.i3D_exportGameRelativePath:
        # self.i3D_exportRelativePaths = True
        pass

def setGameRelativePath(self,context):
    if not self.i3D_exportRelativePaths:
        # self.i3D_exportGameRelativePath = False
        pass

def updateShaderFolderLocation(context):
    """ Sets the currently defined shader folder location to be relative to the game location, if
    it is set, or to an absolute path otherwise. """
    path = context.scene.I3D_UIexportSettings.i3D_shaderFolderLocation
    if path is None or path == "" or path[0] == "$":
        return

    gamePath = getGamePath()
    if gamePath is None or gamePath == "":
        gamePath = context.scene.I3D_UIexportSettings.i3D_gameLocationDisplay

    if gamePath is not None and gamePath != "":
        path = "$" + os.path.relpath(path, start = gamePath)
    else:
        path = os.path.abspath(path)
    context.scene.I3D_UIexportSettings.i3D_shaderFolderLocation = path

def onWriteShaderPath(self,context):
    if not context.scene.I3D_UIexportSettings.i3D_shaderEnum in [t[0] for t in I3D_PT_PanelExport.getShadersFromDirectory(self,context)]:
        context.scene.I3D_UIexportSettings.i3D_shaderEnum = [t[0] for t in I3D_PT_PanelExport.getShadersFromDirectory(self,context)][0]

def boundingVolumeMergeGroupUpdate(self,context):
    context.scene.I3D_UIexportSettings.i3D_boundingVolume = context.scene.I3D_UIexportSettings.i3D_boundingVolumeMergeGroup

def refractionMapUpdate(self, context):
    if context.scene.I3D_UIexportSettings.i3D_refractionMap:
        context.scene.I3D_UIexportSettings.i3D_refractionMapLightAbsorbance = dcc.SETTINGS_ATTRIBUTES["i3D_refractionMapLightAbsorbance"]["defaultValue"]
        context.scene.I3D_UIexportSettings.i3D_refractionMapBumpScale = dcc.SETTINGS_ATTRIBUTES["i3D_refractionMapBumpScale"]["defaultValue"]
        context.scene.I3D_UIexportSettings.i3D_refractionMapWithSSRData = dcc.SETTINGS_ATTRIBUTES["i3D_refractionMapWithSSRData"]["defaultValue"]
    else:
        context.scene.I3D_UIexportSettings.i3D_refractionMapLightAbsorbance = dcc.SETTINGS_ATTRIBUTES["i3D_refractionMapLightAbsorbance"]["defaultValue"]
        context.scene.I3D_UIexportSettings.i3D_refractionMapBumpScale = dcc.SETTINGS_ATTRIBUTES["i3D_refractionMapBumpScale"]["defaultValue"]
        context.scene.I3D_UIexportSettings.i3D_refractionMapWithSSRData = dcc.SETTINGS_ATTRIBUTES["i3D_refractionMapWithSSRData"]["defaultValue"]

def selectedMaterialEnumUpdate(self, context):
    if g_disableSelectedMaterialEnumUpdateCallback:
        return

    # Keep the Shader Setup "Select Material" dropdown in sync with Blender's active material slot.
    # If the user picks a material from the dropdown, switch the *active material slot* on the active object.
    # (This also means picking a different slot in Blender's Material Properties panel will be reflected back
    # into this dropdown via the timer/modal sync code.)
    mat_name = getattr(self, 'i3D_selectedMaterialEnum', 'None')
    if mat_name in (None, '', 'None'):
        return

    active_obj = getattr(context, 'active_object', None)
    if active_obj is None or not isinstance(active_obj, bpy.types.Object):
        return

    try:
        slots = getattr(active_obj, 'material_slots', None)
    except Exception:
        slots = None
    if not slots:
        return

    # Find the slot index matching the chosen material name.
    target_idx = None
    for i, ms in enumerate(slots):
        try:
            if ms and ms.material and ms.material.name == mat_name:
                target_idx = i
                break
        except Exception:
            continue

    if target_idx is None:
        return

    # Switch the active material slot.
    try:
        active_obj.active_material_index = target_idx
    except Exception:
        pass

def templatedParameterEnabled(self, context, parameterTemplateId, subTemplateId, paramName):
    # Reset the template for this parameter if the checkbox is unset.
    if not getattr(self, paramName + "Bool"):
        setattr(self, "templatedParameterTemplateMenu_" + parameterTemplateId + "_" + paramName, "None")

def templatedParameterEnableCallback(parameterTemplateId, subTemplateId, paramName):
    return lambda self, context : templatedParameterEnabled(self, context, parameterTemplateId, subTemplateId, paramName)

def templatedParameterUpdated(self, context, parameterTemplateId, subTemplateId, paramName):
    global g_disableTemplatedParameterUpdatedCallback

    if g_disableTemplatedParameterUpdatedCallback:
        return

    setattr(self, "templatedParameterTemplateMenu_" + parameterTemplateId + "_" + paramName, "None")

def templatedParameterUpdateCallback(parameterTemplateId, subTemplateId, paramName):
    return lambda self, context : templatedParameterUpdated(self, context, parameterTemplateId, subTemplateId, paramName)

def templateForParameterSelected(self, context, parameterTemplateId, subTemplateId, paramName):
    global g_disableTemplatedParameterUpdatedCallback, g_disableTemplateSelectedForParameterCallback

    if g_disableTemplateSelectedForParameterCallback:
        return

    shaderData = extractXMLShaderData()

    parameterTemplateDict = shaderData["parameterTemplates"][parameterTemplateId]
    subTemplateDict = parameterTemplateDict["subtemplates"][subTemplateId]
    selectedTemplateName = getattr(self, "templatedParameterTemplateMenu_" + parameterTemplateId + "_" + paramName)
    try:
        selectedTemplateName = selectedTemplateName.split()[0]
    except:
        selectedTemplateName = "None"

    if selectedTemplateName in subTemplateDict["templates"]:
        selectedTemplate = subTemplateDict["templates"][selectedTemplateName]

        value = selectedTemplate[paramName]
        try:
            valueList = [float(x) for x in value.strip().split(" ")]
        except Exception as e:
            # TODO(jdellsperger): Inform about malformed xml?
            valueList = parameterTemplateDict["parameters"][paramName]
        valueList = valueList + [1.0,1.0,1.0,1.0]

        g_disableTemplatedParameterUpdatedCallback = True
        setattr(self, paramName + "_0", valueList[0])
        setattr(self, paramName + "_1", valueList[1])
        setattr(self, paramName + "_2", valueList[2])
        setattr(self, paramName + "_3", valueList[3])
        g_disableTemplatedParameterUpdatedCallback = False
    else:
        g_disableTemplateSelectedForParameterCallback = True
        setattr(self, "templatedParameterTemplateMenu_" + parameterTemplateId + "_" + paramName, "None")
        g_disableTemplateSelectedForParameterCallback = False

def templateForParameterSelectedCallback(parameterTemplateId, subTemplateId, paramName):
    return lambda self, context : templateForParameterSelected(self, context, parameterTemplateId, subTemplateId, paramName)

def parameterTemplateSelected(self, context, parameterTemplateId, subTemplateId):
    global g_disableParameterTemplateSelectedCallback

    if g_disableParameterTemplateSelectedCallback:
        return

    shaderData = extractXMLShaderData()
    if not shaderData:
        print("parameterTemplateSelected: no shader data")
        return

    if parameterTemplateId not in shaderData["parameterTemplates"]:
        print("parameterTemplateSelected: invalid parameterTemplateId")
        return

    parameterTemplateDict = shaderData["parameterTemplates"][parameterTemplateId]
    if subTemplateId not in parameterTemplateDict["subtemplates"]:
        print("parameterTemplateSelected: invalid subTemplateId")
        return

    g_disableParameterTemplateSelectedCallback = True

    parametersToHandle = [paramName for paramName, _ in parameterTemplateDict["parameters"].items() if not getattr(self, paramName + "Bool", False)]
    texturesToHandle = [textureName for textureName, _ in parameterTemplateDict["textures"].items() if not getattr(self, textureName + "Bool", False)]

    # Unset checkboxes for all other subtemplates.
    for k, _ in parameterTemplateDict["subtemplates"].items():
        if k != subTemplateId:
            setattr(self, k + "Bool", False)
            setattr(self, k + "_Template", "None")

    # Reset selected template if checkbox is unchecked.
    if not getattr(self, subTemplateId + "Bool"):
        setattr(self, subTemplateId + "_Template", "None")

    while subTemplateId is not None:
        subTemplateDict = parameterTemplateDict["subtemplates"][subTemplateId]

        selectedSubTemplateName = getattr(self, subTemplateId + "_Template")

        # Handle template names with description
        try:
            selectedSubTemplateName = selectedSubTemplateName.split()[0]
        except:
            pass

        if selectedSubTemplateName not in subTemplateDict["templates"]:
            setattr(self, subTemplateId + "_Template", "None")
            print("parameterTemplateSelected: invalid selectedSubTemplateName {}".format(selectedSubTemplateName))
            g_disableParameterTemplateSelectedCallback = False
            return

        selectedTemplate = subTemplateDict["templates"][selectedSubTemplateName]

        parametersHandledBySubTemplate = [paramName for paramName in parametersToHandle if paramName in selectedTemplate]
        parametersToHandle = [paramName for paramName in parametersToHandle if paramName not in selectedTemplate]
        for paramName in parametersHandledBySubTemplate:
            value = selectedTemplate[paramName]
            try:
                valueList = [float(x) for x in value.strip().split(" ")]
            except Exception as e:
                # TODO(jdellsperger): Inform about malformed xml?
                valueList = parameterTemplateDict["parameters"][paramName]
            valueList = valueList + [1.0,1.0,1.0,1.0]

            setattr(self, paramName + "_0", valueList[0])
            setattr(self, paramName + "_1", valueList[1])
            setattr(self, paramName + "_2", valueList[2])
            setattr(self, paramName + "_3", valueList[3])

        texturesHandledBySubTemplate = [textureName for textureName in texturesToHandle if textureName in selectedTemplate]
        texturesToHandle = [textureName for textureName in texturesToHandle if textureName not in selectedTemplate]
        for textureName in texturesHandledBySubTemplate:
            setattr(self, textureName, selectedTemplate[textureName])

        subTemplateId = subTemplateDict["parentId"]
        if subTemplateId is not None:
            if getattr(self, subTemplateId + "Bool", False):
                selectedSubTemplateName = getattr(self, subTemplateId + "_Template", "None")
            elif "parentTemplate" in selectedTemplate:
                selectedSubTemplateName = selectedTemplate["parentTemplate"]
                setattr(self, subTemplateId + "_Template", selectedSubTemplateName)
            else:
                selectedSubTemplateName = subTemplateDict["defaultParentTemplate"]
                setattr(self, subTemplateId + "_Template", selectedSubTemplateName)

    g_disableParameterTemplateSelectedCallback = False

def parameterTemplateSelectedCallback(parameterTemplateId, subTemplateId):
    return lambda self, context : parameterTemplateSelected(self, context, parameterTemplateId, subTemplateId)

def parameterTemplateSearchCallback(enums):
    return lambda self, context, searchText: ["None"] + enums

def updateDynamicUIClassesForShaderParameters(shaderData, variation_groups, shaderValues = {"parameters": {},"textures": {}, "parameterTemplates": {}}, materialObj = {}):
    # materialObj can be None if the active object has no material assigned
    if materialObj is None:
        materialObj = {}

    # Custom Parameters
    dynamicGUIDict = {}
    for paramName, value in shaderData["parameters"].items():
        # Only show parameters that share a group with the variation.
        parameter_group = shaderData["parameters_group"][paramName]
        if parameter_group not in variation_groups:
            continue

        # Use custom value if available
        if paramName in shaderValues["parameters"]:
            boolValue = True
            value = shaderValues["parameters"][paramName]
        else:
            boolValue = False

        try:
            valueList = [float(x) for x in value.strip().split(" ")]
        except Exception as e:
            print(e)
            valueList = []
        valueList = valueList + [1.0,1.0,1.0,1.0]
        dynamicGUIDict.update({
                paramName + "Bool": bpy.props.BoolProperty(name = paramName+"Bool",default=boolValue),
                paramName + "_0": bpy.props.FloatProperty(default = valueList[0] , precision = dcc.FLOAT_PRECISION ),
                paramName + "_1": bpy.props.FloatProperty(default = valueList[1] , precision = dcc.FLOAT_PRECISION ),
                paramName + "_2": bpy.props.FloatProperty(default = valueList[2] , precision = dcc.FLOAT_PRECISION ),
                paramName + "_3": bpy.props.FloatProperty(default = valueList[3] , precision = dcc.FLOAT_PRECISION )
        })
    paramClss = type('I3D_UIShaderParameters', (bpy.types.PropertyGroup,), {'__annotations__': dynamicGUIDict})
    bpy.utils.register_class(paramClss)
    bpy.types.Scene.I3D_UIShaderParameters = bpy.props.PointerProperty(type=paramClss)

    # Custom Textures
    dynamicGUIDict = {}
    for textureName, value in shaderData["textures"].items():
        # Only show textures that share a group with the variation.
        texture_group = shaderData["textures_group"][textureName]
        if texture_group not in variation_groups:
            continue

        # Use custom value if available
        if textureName in shaderValues["textures"]:
            boolValue = True
            value = shaderValues["textures"][textureName]
        else:
            boolValue = False

        dynamicGUIDict.update({
                textureName + "Bool": bpy.props.BoolProperty(name=textureName, default=boolValue),
                textureName: bpy.props.StringProperty(default=value)
                })
    textClss = type('I3D_UIShaderTextures', (bpy.types.PropertyGroup,), {'__annotations__': dynamicGUIDict})
    bpy.utils.register_class(textClss)
    bpy.types.Scene.I3D_UIShaderTextures = bpy.props.PointerProperty(type=textClss)
    g_dynamicGUIClsDict["parameters"] = paramClss
    g_dynamicGUIClsDict["textures"] = textClss

    # Parameter templates.
    for parameterTemplateId, parameterTemplate in shaderData["parameterTemplates"].items():
        dynamicGUIDict = {}

        clssName = 'I3D_UITemplateParameters_'+parameterTemplateId
        if bpy.context.scene.get(clssName):
            del bpy.context.scene[clssName]
        try:
            delattr(bpy.types.Scene, clssName)
        except:
            pass

        parameterTemplatesToHandle = {subtemplateId: {'isCustom': False, 'value': 'None'} for subtemplateId, subtemplate in parameterTemplate["subtemplates"].items()}
        paramsToHandle = [paramName for paramName, _ in parameterTemplate["parameters"].items()]
        texturesToHandle = [textureName for textureName, _ in parameterTemplate["textures"].items()]

        paramValues = {paramName: {'isCustom': False, 'value': param} for paramName, param in parameterTemplate["parameters"].items()}
        textureValues = {textureName: {'isCustom': False, 'value': texture} for textureName, texture in parameterTemplate["textures"].items()}

        # First, handle parameters and textures which have a custom value set.
        handledParams = []
        for paramName in paramsToHandle:
            if paramName not in shaderValues["parameters"]:
                continue

            handledParams.append(paramName)

            # TODO(jdellsperger): Load selected parameter templates into shaderValues variable instead of passing materialObj
            templatedParameterTemplateMenuName = "templatedParameterTemplateMenu_" + parameterTemplateId + "_" + paramName
            if materialObj is not None and templatedParameterTemplateMenuName in materialObj:
                templatedParameterTemplate = materialObj[templatedParameterTemplateMenuName]
                try:
                    value = parameterTemplate["subtemplates"][parameterTemplate["rootSubTemplateId"]]["templates"][templatedParameterTemplate][paramName]
                except:
                    value = shaderValues["parameters"][paramName]
            else:
                value = shaderValues["parameters"][paramName]

            paramValues[paramName]["isCustom"] = True
            paramValues[paramName]["value"] = value
        paramsToHandle = [paramName for paramName in paramsToHandle if paramName not in handledParams]

        handledTextures = []
        for textureName in texturesToHandle:
            if textureName not in shaderValues["textures"]:
                continue

            handledTextures.append(textureName)

            value = shaderValues["textures"][textureName]

            textureValues[textureName]["isCustom"] = True
            textureValues[textureName]["value"] = value
        texturesToHandle = [textureName for textureName in texturesToHandle if textureName not in handledTextures]

        subTemplateId = parameterTemplate["rootSubTemplateId"]
        while subTemplateId is not None:
            subTemplate = parameterTemplate["subtemplates"][subTemplateId]
            parentSubTemplateId = subTemplate["parentId"]

            boolValue = False
            selectedTemplateId = parameterTemplatesToHandle[subTemplateId]["value"]

            try:
                boolValue = subTemplateId in shaderValues["parameterTemplates"][parameterTemplateId]
                if boolValue:
                    selectedTemplateId = shaderValues["parameterTemplates"][parameterTemplateId][subTemplateId]
            except KeyError:
                pass

            parameterTemplatesToHandle[subTemplateId]["isCustom"] = boolValue
            parameterTemplatesToHandle[subTemplateId]["value"] = selectedTemplateId

            parentSubTemplate = "None"

            selectedTemplateName = None
            try:
                selectedTemplateName = selectedTemplateId.split()[0]
            except:
                selectedTemplateName = selectedTemplateId

            # Get selected template
            selectedTemplate = None
            if selectedTemplateName in subTemplate["templates"]:
                selectedTemplate = subTemplate["templates"][selectedTemplateName]

                # Handle parameters and textures set by this subtemplate
                handledParams = []
                for paramName in paramsToHandle:
                    if paramName not in selectedTemplate:
                        continue

                    handledParams.append(paramName)

                    value = selectedTemplate[paramName]

                    paramValues[paramName]["isCustom"] = False
                    paramValues[paramName]["value"] = value

                paramsToHandle = [paramName for paramName in paramsToHandle if paramName not in handledParams]

                handledTextures = []
                for textureName in texturesToHandle:
                    if textureName not in selectedTemplate:
                        continue

                    handledTextures.append(textureName)

                    value = selectedTemplate[textureName]

                    textureValues[textureName]["isCustom"] = False
                    textureValues[textureName]["value"] = value
                texturesToHandle = [textureName for textureName in texturesToHandle if textureName not in handledTextures]

                # Find which parent sub template should be used if its not set.
                if "parentTemplate" in selectedTemplate:
                    parentSubTemplate = selectedTemplate["parentTemplate"]
                else:
                    parentSubTemplate = subTemplate["defaultParentTemplate"]

            if parentSubTemplateId is not None:
                parameterTemplatesToHandle[parentSubTemplateId]["value"] = parentSubTemplate

            enums = [templateName + ((" (" + templateParams["description"] + ")") if "description" in templateParams else "") for templateName, templateParams in subTemplate["templates"].items()]
            dynamicGUIDict.update({
                subTemplateId + "Bool": bpy.props.BoolProperty(name = subTemplateId + "Bool", default = boolValue, update = parameterTemplateSelectedCallback(parameterTemplateId, subTemplateId)),
                subTemplateId + "_Template": bpy.props.StringProperty(name = subTemplate["name"], search = parameterTemplateSearchCallback(enums), update = parameterTemplateSelectedCallback(parameterTemplateId, subTemplateId), default = selectedTemplateId)
            })

            subTemplateId = subTemplate["parentId"]

        rootSubTemplateId = parameterTemplate["rootSubTemplateId"]
        rootTemplates = [templateName + ((" (" + templateParams["description"] + ")") if "description" in templateParams else "") for templateName, templateParams in parameterTemplate["subtemplates"][rootSubTemplateId]["templates"].items()]
        for paramName, param in paramValues.items():
            value = param["value"]

            try:
                valueList = [float(x) for x in value.strip().split(" ")]
            except Exception as e:
                #print(e)
                valueList = []
            valueList = valueList + [1.0,1.0,1.0,1.0]

            dynamicGUIDict.update({
                paramName+"Bool": bpy.props.BoolProperty(name = paramName+"Bool", default=param["isCustom"], update = templatedParameterEnableCallback(parameterTemplateId, rootSubTemplateId, paramName)),
                paramName+"_0": bpy.props.FloatProperty(default = valueList[0], precision = dcc.FLOAT_PRECISION, update = templatedParameterUpdateCallback(parameterTemplateId, rootSubTemplateId, paramName)),
                paramName+"_1": bpy.props.FloatProperty(default = valueList[1], precision = dcc.FLOAT_PRECISION, update = templatedParameterUpdateCallback(parameterTemplateId, rootSubTemplateId, paramName)),
                paramName+"_2": bpy.props.FloatProperty(default = valueList[2], precision = dcc.FLOAT_PRECISION, update = templatedParameterUpdateCallback(parameterTemplateId, rootSubTemplateId, paramName)),
                paramName+"_3": bpy.props.FloatProperty(default = valueList[3], precision = dcc.FLOAT_PRECISION, update = templatedParameterUpdateCallback(parameterTemplateId, rootSubTemplateId, paramName)),
                "templatedParameterTemplateMenu_" + parameterTemplateId + "_" + paramName: bpy.props.StringProperty(name = subTemplate["name"], search = parameterTemplateSearchCallback(rootTemplates), update = templateForParameterSelectedCallback(parameterTemplateId, rootSubTemplateId, paramName), default = (materialObj["templatedParameterTemplateMenu_" + parameterTemplateId + "_" + paramName] if (materialObj is not None and ("templatedParameterTemplateMenu_" + parameterTemplateId + "_" + paramName) in materialObj) else "None"))
            })

        for textureName, texture in textureValues.items():
            dynamicGUIDict.update({
                    textureName+"Bool": bpy.props.BoolProperty(name=textureName, default=texture["isCustom"]),
                    textureName: bpy.props.StringProperty(default=texture["value"])
                    })

        templateParameterClss = type(clssName, (bpy.types.PropertyGroup,), {'__annotations__': dynamicGUIDict})
        bpy.utils.register_class(templateParameterClss)

        try:
            setattr(bpy.types.Scene, clssName, bpy.props.PointerProperty(type=templateParameterClss))
        except Exception as e:
            print("Could not add class {} to scene".format(clssName))
            print(e)
            continue
        else:
            # Blender 5.0+ behavior: defaults on dynamically created PointerProperty instances
            # (especially StringProperty with search callbacks) may not be applied reliably.
            # Explicitly push the resolved template selections/values into the instance so
            # the Load button works consistently across Blender versions.
            _prev_disable_pt = None
            _prev_disable_tu = None
            _prev_disable_tsp = None
            try:
                scene = bpy.context.scene
                inst = getattr(scene, clssName, None)

                if inst is not None:
                    global g_disableParameterTemplateSelectedCallback
                    global g_disableTemplatedParameterUpdatedCallback
                    global g_disableTemplateSelectedForParameterCallback

                    _prev_disable_pt = g_disableParameterTemplateSelectedCallback
                    _prev_disable_tu = g_disableTemplatedParameterUpdatedCallback
                    _prev_disable_tsp = g_disableTemplateSelectedForParameterCallback

                    g_disableParameterTemplateSelectedCallback = True
                    g_disableTemplatedParameterUpdatedCallback = True
                    g_disableTemplateSelectedForParameterCallback = True

                    # Sub-template selections (e.g. brandColor/material).
                    for _sub_id, _info in parameterTemplatesToHandle.items():
                        try:
                            setattr(inst, _sub_id + "Bool", bool(_info.get("isCustom", False)))
                        except Exception:
                            pass
                        try:
                            _val = _info.get("value", "None")
                            if _val is None or str(_val).strip() == "":
                                _val = "None"
                            else:
                                _val = str(_val)
                            setattr(inst, _sub_id + "_Template", _val)
                        except Exception:
                            pass

                    # Per-parameter template menus (templatedParameterTemplateMenu_...).
                    for _param_name in parameterTemplate["parameters"].keys():
                        _menu_name = "templatedParameterTemplateMenu_" + parameterTemplateId + "_" + _param_name
                        try:
                            if materialObj is not None and _menu_name in materialObj:
                                _menu_val = str(materialObj[_menu_name])
                            else:
                                _menu_val = "None"
                            setattr(inst, _menu_name, _menu_val)
                        except Exception:
                            pass

                    # Parameter and texture values.
                    for _param_name, _pv in paramValues.items():
                        try:
                            setattr(inst, _param_name + "Bool", bool(_pv.get("isCustom", False)))
                        except Exception:
                            pass
                        try:
                            _vl = _pv.get("value", None)
                            if isinstance(_vl, (list, tuple)):
                                _lst = list(_vl) + [1.0, 1.0, 1.0, 1.0]
                            else:
                                try:
                                    _lst = [float(x) for x in str(_vl).strip().split(" ")] + [1.0, 1.0, 1.0, 1.0]
                                except Exception:
                                    _lst = [1.0, 1.0, 1.0, 1.0]
                            setattr(inst, _param_name + "_0", _lst[0])
                            setattr(inst, _param_name + "_1", _lst[1])
                            setattr(inst, _param_name + "_2", _lst[2])
                            setattr(inst, _param_name + "_3", _lst[3])
                        except Exception:
                            pass

                    for _tex_name, _tv in textureValues.items():
                        try:
                            setattr(inst, _tex_name + "Bool", bool(_tv.get("isCustom", False)))
                        except Exception:
                            pass
                        try:
                            _tval = _tv.get("value", "")
                            if _tval is None:
                                _tval = ""
                            setattr(inst, _tex_name, str(_tval))
                        except Exception:
                            pass
            except Exception:
                pass
            finally:
                try:
                    if _prev_disable_pt is not None:
                        g_disableParameterTemplateSelectedCallback = _prev_disable_pt
                    if _prev_disable_tu is not None:
                        g_disableTemplatedParameterUpdatedCallback = _prev_disable_tu
                    if _prev_disable_tsp is not None:
                        g_disableTemplateSelectedForParameterCallback = _prev_disable_tsp
                except Exception:
                    pass

            g_dynamicGUIClsDict[parameterTemplateId] = templateParameterClss

def getShaderDataFromMaterialObj(self, materialObj):
    shaderData =  {"shader": None, "variation": None, "parameters": {},"textures": {}, "parameterTemplates": {}}
    if materialObj:
        for name, value in materialObj.items():
            if name.startswith("customParameterTemplate"):
                parts = name.split("_")
                templateId = parts[1]
                subTemplateId = parts[2]
                if templateId not in shaderData["parameterTemplates"]:
                    shaderData["parameterTemplates"][templateId] = {}
                shaderData["parameterTemplates"][templateId][subTemplateId] = value
            elif name.startswith("customParameter"):
                shaderData["parameters"][name.split("_")[1]] = value
            elif name == "customShader":
                # print("value: {}".format(value))
                try:
                    if value[0] == '$':
                        fullShaderPath = value
                        fullShaderPath = fullShaderPath.replace("/", os.sep)
                        fullShaderPath = fullShaderPath.replace("\\",os.sep)
                    elif os.path.isfile(value):
                        fullShaderPath = pathUtil.resolvePath(value, referenceDirectory = None, targetDirectory = None)
                    else:
                        fullShaderPath = pathUtil.resolvePath(value, referenceDirectory = bpy.path.abspath("//"), targetDirectory = None)
                    shaderData["shader"] = fullShaderPath.split(os.sep)[-1]
                except pathUtil.InputError as e:
                    self.report({'WARNING'},e.message)
            elif name == "customShaderVariation":
                shaderData["variation"] = value
            elif name.startswith("customTexture"):
                shaderData["textures"][name.split("_")[1]] = value
    return shaderData

def shaderEnumUpdate(self,context):
    """ Creates and registers dynamic classes for dynamic GUI elements """

    global g_dynamicGUIClsDict

    # Remove any per-parameter-template pointer properties we previously registered.
    # Blender 5.0 removed dict-like access to runtime-defined bpy.props properties, so
    # clearing only IDProperties isn't enough anymore.
    for _template_id in [k for k in list(g_dynamicGUIClsDict.keys()) if k not in ("parameters", "textures")]:
        _prop_name = "I3D_UITemplateParameters_" + _template_id
        # Best-effort: older Blender stored runtime props in IDProperties.
        try:
            if _prop_name in bpy.context.scene:
                del bpy.context.scene[_prop_name]
        except Exception:
            pass
        # Always remove the Scene RNA property definition.
        try:
            delattr(bpy.types.Scene, _prop_name)
        except Exception:
            pass
    if bpy.context.scene.get( 'I3D_UIShaderParameters' ):
        del bpy.context.scene[ 'I3D_UIShaderParameters' ]
    try:
        del bpy.types.Scene.I3D_UIShaderParameters
    except:
        pass
    if bpy.context.scene.get( 'I3D_UIShaderTextures' ):
        del bpy.context.scene[ 'I3D_UIShaderTextures' ]
    try:
        del bpy.types.Scene.I3D_UIShaderTextures
    except:
        pass
    for dynamicClass in g_dynamicGUIClsDict.values():
        bpy.utils.unregister_class(dynamicClass)
    g_dynamicGUIClsDict = {}

    shaderData = extractXMLShaderData()
    if shaderData:
        # Create variation dropdown
        if context.scene.get( 'I3D_UIshaderVariation' ):
            del context.scene[ 'I3D_UIshaderVariation' ]
        try:
            del bpy.types.Scene.I3D_UIshaderVariation
        except:
            pass

        variationsTuple = (("None","None","None"),)
        for variation in shaderData["variations"].keys():
            variationsTuple = variationsTuple + ((variation,variation,variation),)
        dynamicGUIDict = {"i3D_shaderVariationEnum": bpy.props.EnumProperty(items = variationsTuple, name = "Shader Variation", update = shaderVariationEnumUpdate)}
        paramClss = type('I3D_UIshaderVariation', (bpy.types.PropertyGroup,), {'__annotations__': dynamicGUIDict})
        bpy.utils.register_class(paramClss)
        bpy.types.Scene.I3D_UIshaderVariation = bpy.props.PointerProperty(type=paramClss)

        updateDynamicUIClassesForShaderParameters(shaderData, ["base"])
    else:
        print("No shader to load")

def shaderVariationEnumUpdate(self,context):
    """ Creates and registers dynamic classes for dynamic GUI elements """

    global g_dynamicGUIClsDict, g_disableShaderVariationEnumUpdateCallback
    if g_disableShaderVariationEnumUpdateCallback:
        return

    if bpy.context.scene.get( 'I3D_UIShaderParameters' ):
        del bpy.context.scene[ 'I3D_UIShaderParameters' ]
    try:
        del bpy.types.Scene.I3D_UIShaderParameters
    except:
        pass
    if bpy.context.scene.get( 'I3D_UIShaderTextures' ):
        del bpy.context.scene[ 'I3D_UIShaderTextures' ]
    try:
        del bpy.types.Scene.I3D_UIShaderTextures
    except:
        pass
    for dynamicClass in g_dynamicGUIClsDict.values():
        bpy.utils.unregister_class(dynamicClass)
    g_dynamicGUIClsDict = {}

    # check if data is overridden
    try:
        actObjName = context.active_object.name
    except:
        try:
            actObjName = dccBlender.getSelectedNodes()[0]
        except:
            actObjName = None
    materialObj = None
    if actObjName is not None:
        activeObject = bpy.data.objects[actObjName]
        materialObj = activeObject.active_material

    shaderData =  getShaderDataFromMaterialObj(self, materialObj)
    fileShaderData = extractXMLShaderData()
    if fileShaderData:
        variation_groups = ["base"]
        selected_variation = context.scene.I3D_UIshaderVariation.i3D_shaderVariationEnum
        variation_groups_str = None
        if selected_variation in fileShaderData["variations_groups"]:
            variation_groups_str = fileShaderData["variations_groups"][selected_variation]
        if variation_groups_str is not None:
            variation_groups = variation_groups_str.split()

        updateDynamicUIClassesForShaderParameters(fileShaderData, variation_groups, shaderData, materialObj)
    else:
        print("No shader to load")


class I3D_OT_SelectionToOrigin(bpy.types.Operator):
    """Sets the origin position to the center of the selected vertices/edges/faces"""
    bl_idname = "i3d.selectiontoorigin"
    bl_label = "SelectionToOrigin"
    bl_description = "SelectionToOrigin: selects items related to the current view."
    bl_options = {'UNDO'}
    CONTEXT_MENU_ICON = "OBJECT_ORIGIN"

    def execute(self, context):
        if context.space_data.type == 'VIEW_3D':
            bpy.ops.object.mode_set(mode='OBJECT')

            avgPosition = Vector()
            numVertices = 0

            for vertex in bpy.context.object.data.vertices:
                if vertex.select:
                    worldPosition = bpy.context.object.matrix_world @ vertex.co
                    avgPosition += worldPosition
                    numVertices = numVertices + 1

            if numVertices > 0:
                pos = avgPosition / numVertices

                cursor_location = bpy.context.scene.cursor.location.xyz

                bpy.context.scene.cursor.location.xyz = pos
                bpy.ops.object.origin_set(type='ORIGIN_CURSOR')

                bpy.context.scene.cursor.location.xyz = cursor_location
            else:
                self.report({'WARNING'}, "Nothing selected!")
                return {'CANCELLED'}

            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}

    def getShowInContextMenu(context):
        if context.space_data.type == 'VIEW_3D':
            if context.object is not None:
                bm = bmesh.from_edit_mesh(context.object.data)
                for vert in bm.verts:
                    if vert.select:
                        return True

        return False


class I3D_OT_FaceNormalToOrigin(bpy.types.Operator):
    """Sets the origin rotation to equal the orientation of the selected face"""
    bl_idname = "i3d.facenormaltoorigin"
    bl_label = "FaceNormalToOrigin"
    bl_description = "FaceNormalToOrigin."
    bl_options = {'UNDO'}
    CONTEXT_MENU_ICON = "ORIENTATION_NORMAL"

    def execute(self, context):
        if context.space_data.type == 'VIEW_3D':
            if context.object is None:
                self.report({'WARNING'}, "No face selected!")
                return {'CANCELLED'}

            mode = bpy.context.active_object.mode
            bpy.ops.object.mode_set(mode='OBJECT')

            object = context.object
            bm = bmesh.new()
            bm.from_mesh(object.data)

            bm.transform(object.matrix_world)
            bm.normal_update()
            face = bm.select_history.active

            if face is None:
                bpy.ops.object.mode_set(mode=mode)
                self.report({'WARNING'}, "No face selected!")
                return {'CANCELLED'}

            if not isinstance(face, bmesh.types.BMFace):
                bpy.ops.object.mode_set(mode=mode)
                self.report({'WARNING'}, "Function 'FaceNormalToOrigin' does only work with faces!")
                return {'CANCELLED'}

            tangent = face.calc_tangent_edge_pair().normalized()
            bt = face.normal.cross(tangent).normalized()

            worldMatrix = Matrix([tangent, bt, face.normal]).transposed().to_4x4()
            worldMatrix.translation = object.matrix_world.translation

            R = worldMatrix.to_3x3().normalized().to_4x4()

            worldMatrix = object.matrix_world
            location = worldMatrix.to_3x3().normalized().to_4x4().inverted() @ R
            object.matrix_world = (Matrix.Translation(worldMatrix.translation) @ R @ Matrix.Diagonal(worldMatrix.to_scale()).to_4x4())
            object.data.transform(location.inverted())

            bpy.ops.object.mode_set(mode=mode)

            bm.free()

            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}

    def getShowInContextMenu(context):
        if context.space_data.type == 'VIEW_3D':
            if context.object is not None:
                bm = bmesh.from_edit_mesh(context.object.data)
                for face in bm.faces:
                    if face.select:
                        return True
        return False


class I3D_OT_FreezeTranslation(bpy.types.Operator):
    """Equals the origin translation with the translation of the parent object"""
    bl_idname = "i3d.freezetranslation"
    bl_label = "FreezeTranslation"
    bl_description = "FreezeTranslation."
    bl_options = {'UNDO'}
    CONTEXT_MENU_ICON = "CON_LOCLIMIT"

    def execute(self, context):
        if context.space_data.type == 'VIEW_3D':
            bpy.ops.object.mode_set(mode='OBJECT')

            object = context.object
            loc = (0, 0, 0)
            if object.parent is not None:
                loc = object.parent.location.xyz

            if object.type == "MESH":
                cursor_location = bpy.context.scene.cursor.location.xyz

                bpy.context.scene.cursor.location.xyz = loc
                bpy.ops.object.origin_set(type='ORIGIN_CURSOR')

                bpy.context.scene.cursor.location.xyz = cursor_location
            elif object.type == "ARMATURE":
                loc = (0, 0, 0)
                if object.parent is not None:
                    loc = object.parent.location.xyz

                object.location.xyz = loc
                for bone in object.pose.bones:
                    bone.location.xyz = (0, 0, 0)
            else:
                self.report({'WARNING'}, "'FreezeTranslation' not supported for '%s'" % object.type)

            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}

    def getShowInContextMenu(context):
        if context.space_data.type == 'VIEW_3D':
            if context.mode == "OBJECT":
                if len(bpy.context.selected_objects) > 0:
                    return True

        return False


class I3D_OT_FreezeRotation(bpy.types.Operator):
    """Equals the origin rotation with the rotation of the parent object"""
    bl_idname = "i3d.freezerotation"
    bl_label = "FreezeRotation"
    bl_description = "FreezeRotation."
    bl_options = {'UNDO'}
    CONTEXT_MENU_ICON = "CON_ROTLIMIT"

    def execute(self, context):
        if context.space_data.type == 'VIEW_3D':
            bpy.ops.object.mode_set(mode='OBJECT')

            if len(bpy.context.selected_objects) == 0:
                self.report({'WARNING'}, "No object(s) selected!")
                return {'CANCELLED'}

            for object in bpy.context.selected_objects:
                listOfChildren = []
                for child in object.children:
                    listOfChildren += [child]
                    bpy.ops.object.select_all(action='DESELECT')
                    child.select_set(True)
                    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')

                worldMatrix = None
                if object.parent is None:
                    worldMatrix = Euler((0, 0, 0)).to_matrix()
                else:
                    worldMatrix = object.parent.matrix_world

                R = worldMatrix.to_3x3().normalized().to_4x4()

                worldMatrix = object.matrix_world
                location = worldMatrix.to_3x3().normalized().to_4x4().inverted() @ R
                object.matrix_world = (Matrix.Translation(worldMatrix.translation) @ R @ Matrix.Diagonal(worldMatrix.to_scale()).to_4x4())
                if hasattr(object.data, "transform"):
                    object.data.transform(location.inverted())

                # set parent back again
                for child in listOfChildren:
                    bpy.data.scenes['Scene'].tool_settings.use_transform_data_origin = False
                    child.parent = object
                    child.matrix_parent_inverse = object.matrix_world.inverted()
                    bpy.data.scenes['Scene'].tool_settings.use_transform_data_origin = True
                    child.select_set(False)

                object.select_set(True)

            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}

    def getShowInContextMenu(context):
        if context.space_data.type == 'VIEW_3D':
            if context.mode == "OBJECT":
                if len(bpy.context.selected_objects) > 0:
                    return True

        return False


class I3D_OT_CreateEmpty(bpy.types.Operator):
    """Creates empty group at selected vertex position or as child of selected object(s) or at root level if nothing selected"""
    bl_idname = "i3d.createempty"
    bl_label = "CreateEmpty"
    bl_description = "CreateEmpty."
    bl_options = {'UNDO'}
    CONTEXT_MENU_ICON = "OUTLINER_OB_EMPTY"

    def execute(self, context):
        def createEmpty(parent, pos):
            bpy.ops.object.empty_add(type='PLAIN_AXES', location=pos, radius=0.25)
            empty = bpy.context.view_layer.objects.active

            if parent is not None:
                empty.matrix_world = parent.matrix_world
                empty.location.xyz = pos
                empty.parent = parent
                empty.matrix_parent_inverse = empty.matrix_world.inverted()

                if "Punch" in parent.name:
                    empty.name = parent.name.replace("Punch", "Ref")
                else:
                    empty.name = parent.name + "_Empty"
            else:
                empty.name = "EmptyGroup"

        if context.space_data.type == 'VIEW_3D':
            if bpy.context.active_object is not None:
                mode = bpy.context.active_object.mode
                if mode == "EDIT":
                    bpy.ops.object.mode_set(mode='OBJECT')

                    avgPosition = Vector()
                    numVertices = 0

                    for vertex in bpy.context.object.data.vertices:
                        if vertex.select:
                            worldPosition = bpy.context.object.matrix_world @ vertex.co
                            avgPosition += worldPosition
                            numVertices = numVertices + 1

                    if numVertices > 0:
                        pos = avgPosition / numVertices
                        createEmpty(bpy.context.object, pos)
                    else:
                        self.report({'WARNING'}, "No vertices selected to create empty at. Switch to object mode or select vertices!")
                        return {'CANCELLED'}

                elif mode == "OBJECT":
                    for object in bpy.context.selected_objects:
                        createEmpty(object, object.location.xyz)

                    if len(bpy.context.selected_objects) == 0:
                        createEmpty(None, (0, 0, 0))
            else:
                if len(bpy.context.selected_objects) == 0:
                    createEmpty(None, (0, 0, 0))

            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}

    def getShowInContextMenu(context):
        if context.space_data.type == 'VIEW_3D':
            if context.mode == "OBJECT":
                return True
            else:
                if context.object is not None:
                    bm = bmesh.from_edit_mesh(context.object.data)
                    for vert in bm.verts:
                        if vert.select:
                            return True

        return False


class I3D_OT_AlignYAxis(bpy.types.Operator):
    """Rotate origin towards other objects origin"""
    bl_idname = "i3d.alignyaxis"
    bl_label = "AlignYAxis"
    bl_description = "AlignYAxis."
    bl_options = {'UNDO'}
    CONTEXT_MENU_ICON = "ORIENTATION_GLOBAL"

    def execute(self, context):

        if context.space_data.type == 'VIEW_3D':
            if len(bpy.context.selected_objects) != 2:
                self.report({"WARNING"}, "Select exactly 2 objects to align")
                return {'FINISHED'}

            targetObject = bpy.context.active_object

            sourceObject = targetObject
            if bpy.context.selected_objects[0] == targetObject:
                sourceObject = bpy.context.selected_objects[1]
            else:
                sourceObject = bpy.context.selected_objects[0]

            listOfChildren = []
            for child in sourceObject.children:
                listOfChildren += [child]
                bpy.ops.object.select_all(action='DESELECT')
                child.select_set(True)
                bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')

            obj1_trans = Vector((sourceObject.matrix_world.translation[0], sourceObject.matrix_world.translation[1], sourceObject.matrix_world.translation[2]))
            obj2_trans = Vector((targetObject.matrix_world.translation[0], targetObject.matrix_world.translation[1], targetObject.matrix_world.translation[2]))

            t = (obj1_trans - obj2_trans).normalized()

            tangent = t.cross(Vector((0, 0, 1))).normalized()
            bt = t.cross(tangent).normalized()

            targetMatrix = (Matrix([tangent, bt, t]).transposed() @ Euler((math.pi * 0.5, 0, 0)).to_matrix()).to_4x4()
            targetMatrix.translation = sourceObject.matrix_world.translation

            R = targetMatrix.to_3x3().normalized().to_4x4()

            worldMatrix = sourceObject.matrix_world
            location = worldMatrix.to_3x3().normalized().to_4x4().inverted() @ R
            sourceObject.matrix_world = (Matrix.Translation(worldMatrix.translation) @ R @ Matrix.Diagonal(worldMatrix.to_scale()).to_4x4())
            sourceObject.data.transform(location.inverted())

            if targetObject in listOfChildren:
                targetMatrix.translation = targetObject.matrix_world.translation

                R = targetMatrix.to_3x3().normalized().to_4x4()

                worldMatrix = targetObject.matrix_world
                location = worldMatrix.to_3x3().normalized().to_4x4().inverted() @ R
                targetObject.matrix_world = (Matrix.Translation(worldMatrix.translation) @ R @ Matrix.Diagonal(worldMatrix.to_scale()).to_4x4())
                targetObject.data.transform(location.inverted())

            # set parent back again
            for child in listOfChildren:
                bpy.data.scenes['Scene'].tool_settings.use_transform_data_origin = False
                child.parent = sourceObject
                child.matrix_parent_inverse = sourceObject.matrix_world.inverted()
                bpy.data.scenes['Scene'].tool_settings.use_transform_data_origin = True

            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}

    def getShowInContextMenu(context):
        if context.space_data.type == 'VIEW_3D':
            if context.mode == "OBJECT":
                if len(bpy.context.selected_objects) == 2:
                    return True

        return False


class I3D_OT_MenuExport( bpy.types.Operator ):
    """
    Button to open the GIANTS I3D Exporter
    """

    bl_label = "I3D Exporter"
    bl_idname = "i3d.menuexport"
    bl_description = "Button to open the GIANTS I3D Exporter REWORKED panel in the 3D View Sidebar (N-menu)"

    def execute( self, context ):
        # Switch exporter UI mode to Export (so the correct panel content is shown).
        try:
            context.scene.I3D_UIexportSettings.UI_settingsMode = 'exp'
        except Exception:
            pass

        opened = False
        try:
            wm = bpy.context.window_manager
            for win in wm.windows:
                scr = getattr(win, 'screen', None)
                if scr is None:
                    continue

                for area in getattr(scr, 'areas', []):
                    if getattr(area, 'type', None) != 'VIEW_3D':
                        continue

                    # Ensure sidebar (N-menu) is visible.
                    try:
                        for space in getattr(area, 'spaces', []):
                            if getattr(space, 'type', None) == 'VIEW_3D':
                                space.show_region_ui = True

                                # Switch the Sidebar tab to our add-on panel category.
                                # Without this, Blender may keep whatever tab was last active (Item/Tool/etc.).
                                target_category = "GIANTS I3D Exporter REWORKED"

                                # 1) Direct assignment works in many Blender versions.
                                try:
                                    if hasattr(space, "active_panel_category"):
                                        space.active_panel_category = target_category
                                except Exception:
                                    pass

                                # 2) Some builds only update the UI if we use the context operator.
                                #    This is a best-effort approach: if it fails, the direct assignment above
                                #    still leaves the correct value set.
                                try:
                                    ui_region = None
                                    for r in getattr(area, 'regions', []):
                                        if getattr(r, 'type', None) == 'UI':
                                            ui_region = r
                                            break

                                    if ui_region is not None:
                                        override2 = {'window': win, 'screen': scr, 'area': area, 'region': ui_region}
                                        bpy.ops.wm.context_set_enum(
                                            override2,
                                            data_path='space_data.active_panel_category',
                                            value=target_category
                                        )
                                except Exception:
                                    pass
                    except Exception:
                        pass

                    opened = True

                    # Older Blender builds sometimes need a nudge to refresh the panel list after switching tabs.
                    # This is safe to ignore if unavailable.
                    try:
                        override = {'window': win, 'screen': scr, 'area': area}
                        bpy.ops.wm.redraw_timer(override, type='DRAW_WIN_SWAP', iterations=1)
                    except Exception:
                        pass

                    break

                if opened:
                    break
        except Exception:
            opened = False

        if not opened:
            try:
                self.report({'WARNING'}, 'No 3D View found to open the GIANTS I3D Exporter panel')
            except Exception:
                pass

        return {'FINISHED'}


#-------------------------------------------------------------------------------
#   Refresh Add-on After Update (Drag-and-drop friendly)
#-------------------------------------------------------------------------------
class I3D_OT_RefreshAddonAfterUpdate(bpy.types.Operator):
    """Disable + purge module cache + re-enable the add-on so Blender loads updated code from disk."""

    bl_idname = "i3d.refresh_addon_after_update"
    bl_label = "Refresh Addon After Update"
    bl_description = (
        "Disable and re-enable the add-on to load updated code from disk (no Blender restart required). "
        "Useful after drag-and-drop installing a new ZIP while the add-on is enabled."
    )

    _in_progress = False

    def execute(self, context):
        if I3D_OT_RefreshAddonAfterUpdate._in_progress:
            try:
                self.report({'WARNING'}, "Refresh already in progress")
            except Exception:
                pass
            return {'CANCELLED'}

        I3D_OT_RefreshAddonAfterUpdate._in_progress = True

        addon_pkg = "io_export_i3d_reworked"

        def _tag_redraw_all_windows():
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

            try:
                bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
            except Exception:
                pass

        def _phase_enable():
            import sys
            import addon_utils

            # Purge cached modules so enable() imports fresh code from disk.
            try:
                for mod_name in list(sys.modules.keys()):
                    if mod_name == addon_pkg or mod_name.startswith(addon_pkg + "."):
                        sys.modules.pop(mod_name, None)
            except Exception as e:
                print(f"[I3D Refresh] Module purge failed: {e}")

            # Re-enable add-on.
            try:
                # IMPORTANT: do not use default_set=True here; that can reset
                # add-on preferences (including skipped update versions).
                addon_utils.enable(addon_pkg)
                print("[I3D Refresh] Add-on enabled")
            except Exception as e:
                print(f"[I3D Refresh] Enable failed: {e}")

            # Force redraw a few times to ensure UI panels refresh.
            try:
                for i in range(6):
                    bpy.app.timers.register(_tag_redraw_all_windows, first_interval=0.10 + (i * 0.10))
            except Exception:
                pass

            I3D_OT_RefreshAddonAfterUpdate._in_progress = False
            return None

        def _phase_disable():
            import addon_utils

            # Disable first (unregisters classes cleanly).
            try:
                # IMPORTANT: do not use default_set=True here; that can reset
                # add-on preferences (including skipped update versions).
                addon_utils.disable(addon_pkg)
                print("[I3D Refresh] Add-on disabled")
            except Exception as e:
                print(f"[I3D Refresh] Disable failed: {e}")

            # Then enable on a short timer.
            try:
                bpy.app.timers.register(_phase_enable, first_interval=0.35)
            except Exception:
                # If timers fail for any reason, fall back to immediate enable attempt.
                _phase_enable()

            return None

        # Schedule disable *after* this operator returns, to avoid RNA invalidation crashes.
        try:
            bpy.app.timers.register(_phase_disable, first_interval=0.10)
        except Exception as e:
            print(f"[I3D Refresh] Could not schedule refresh: {e}")
            I3D_OT_RefreshAddonAfterUpdate._in_progress = False
            return {'CANCELLED'}

        try:
            self.report({'INFO'}, "Refreshing add-on…")
        except Exception:
            pass

        return {'FINISHED'}

class I3D_PT_PanelExport( bpy.types.Panel ):
    """ GUI Panel for the GIANTS I3D Exporter visible in the 3D Viewport """

    bl_idname       = "I3D_PT_PanelExport"
    bl_label        = "GIANTS I3D Exporter REWORKED"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GIANTS I3D Exporter REWORKED"


    def draw( self, context ):
        global g_modalsRunning
        if not g_modalsRunning:
            i3d_schedule_bootstrap()
        if i3d_changelog.getHasChangedAnythingSinceLastView():
            i3d_export.I3DShowChangelog()


        layout = self.layout
        obj = context.object


        # ============================
        # --- Missing Game Installation Warning ---
        # ============================
        addon_entry = bpy.context.preferences.addons.get("io_export_i3d_reworked")
        missing_path = (
            addon_entry is None or
            addon_entry.preferences is None or
            not addon_entry.preferences.game_install_path
        )

        top_box = layout.box()
        first_row = top_box.row()
        first_row_left = first_row.row()
        first_row_left.alignment = "LEFT"
        first_row_left.label(text="IndexPath:")
        first_row_right = first_row.row()
        first_row_right.alignment = "RIGHT"
        first_row_right.label(text="Node Name:")
        second_row = top_box.row()

        # Fetch values based on object type and mode
        if obj:
            if obj.type == 'ARMATURE' and context.mode == 'EDIT_ARMATURE':
                active_bone = context.active_bone
                if active_bone:  # Check if there's an active edit bone
                    first_row_left.label(text=_i3d_get_indexpath_cached(context, obj, active_bone.name))
                    first_row_right.label(text=active_bone.name)

                    second_row.prop(active_bone, "I3D_XMLconfigBool", text="")
                    disabled_row = second_row.row()
                    disabled_row.enabled = active_bone.I3D_XMLconfigBool
                    disabled_row.prop(active_bone, "I3D_XMLconfigID", text="")
                    disabled_row.operator("i3d.panelxmlidentification_buttonadd", text="Use Node Name")
            else:
                first_row_left.label(text=_i3d_get_indexpath_cached(context, obj))
                first_row_right.label(text=obj.name)

                second_row.prop(obj, "I3D_XMLconfigBool", text="")
                disabled_row = second_row.row()
                disabled_row.enabled = obj.I3D_XMLconfigBool
                disabled_row.prop(obj, "I3D_XMLconfigID", text="")
                disabled_row.operator("i3d.panelxmlidentification_buttonadd", text="Use Node Name")
        else:
            # Placeholder UI elements when there's no active object
            first_row_left.label(text="N/A")
            first_row_right.label(text="N/A")

        # Refresh button (useful after drag-and-drop updating the ZIP while the add-on is enabled)
        refresh_row = top_box.row()
        refresh_row.scale_y = 1.1
        refresh_row.operator("i3d.refresh_addon_after_update", text="Refresh Addon After Update", icon='FILE_REFRESH')



        if missing_path:
            warning_box = layout.box()
            warning_box.alert = True  # yellow warning style
            
            row = warning_box.row()
            row.label(text="⚠  MISSING GAME INSTALLATION ⚠", icon='ERROR')
    
            row = warning_box.row()
            row.label(text="⚠  LOCATION NOT SET ⚠")
            
            row = warning_box.row()
            row.scale_x = 1.4
            op = row.operator("preferences.addon_show", text="Set", icon="FILE_FOLDER")
            op.module = "io_export_i3d_reworked"

# -------------------------------------------
        layout.prop( context.scene.I3D_UIexportSettings,  "UI_settingsMode", expand = True )
        #-----------------------------------------
        # "Export" tab
        if   'exp'  == context.scene.I3D_UIexportSettings.UI_settingsMode:
            #-----------------------------------------
            # "Export Options" box
            box = layout.box()
            row = box.row()
            # expand button for "Export Options"
            row.prop(   context.scene.I3D_UIexportSettings,
                        "UI_exportOptions",
                        text = "Export Options",
                        icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_exportOptions else 'TRIA_RIGHT',
                        icon_only = False,
                        emboss = False )
            # expanded view
            if context.scene.I3D_UIexportSettings.UI_exportOptions:
                row = box.row()
                split = row.split(factor=0.4)
                col = split.column()
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_exportAnimation" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_exportShapes"    )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_exportLights"      )
                split = split.split(factor = 0.16)
                col = split.column()
                split = split.split(factor = 0.8)
                col = split.column()
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_exportUserAttributes"  )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_exportNurbsCurves" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_binaryFiles"     )

            # -----------------------------------------
            # "Shape Export Subparts" box
            box = layout.box()
            row = box.row()
            # expand button for "Shape Export Subparts"
            row.prop(   context.scene.I3D_UIexportSettings,
                        "UI_shapeExportSubparts",
                        text = "Shape Export Subparts",
                        icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_shapeExportSubparts else 'TRIA_RIGHT',
                        icon_only = False,
                        emboss = False )
            if context.scene.I3D_UIexportSettings.UI_shapeExportSubparts:
                row = box.row()
                split = row.split(factor=0.4)
                col = split.column()
                col.prop( context.scene.I3D_UIexportSettings, "i3D_exportNormals"     )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_exportColors"      )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_exportMergeGroups")
                split = split.split(factor = 0.16)
                col = split.column()
                split = split.split(factor = 0.8)
                col = split.column()
                col.prop( context.scene.I3D_UIexportSettings, "i3D_exportTexCoords"   )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_exportSkinWeigths" )
            # -----------------------------------------
            # "Miscellaneous" box
            box = layout.box()
            row = box.row()
            # expand button for "Miscellaneous"
            row.prop(   context.scene.I3D_UIexportSettings,
                        "UI_miscellaneous",
                        text = "Miscellaneous",
                        icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_miscellaneous else 'TRIA_RIGHT',
                        icon_only = False,
                        emboss = False )
            if context.scene.I3D_UIexportSettings.UI_miscellaneous:
                row = box.row()
                split = row.split(factor=0.4)
                col = split.column()
                col.prop( context.scene.I3D_UIexportSettings, "i3D_exportVerbose"       )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_exportApplyModifiers"  )
                split = split.split(factor = 0.16)
                col = split.column()
                split = split.split(factor = 0.8)
                col = split.column()
                col.prop( context.scene.I3D_UIexportSettings, "i3D_exportEmissionOverride" )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_exportSnowHeapMode" )
                split = box.split()
                split.prop( context.scene.I3D_UIexportSettings, "i3D_exportAxisOrientations"  )
            # -----------------------------------------
            # "Game Location" is now configured in addon preferences (FS25 Game Path). in addon preferences (FS25 Game Path).
            # "XML config File" box
            box = layout.box()
            row = box.row()
            row.prop(   context.scene.I3D_UIexportSettings,
                        "UI_xmlConfig",
                        text = "XML Config Files",
                        icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_xmlConfig else 'TRIA_RIGHT',
                        icon_only = False,
                        emboss = False )
            if context.scene.I3D_UIexportSettings.UI_xmlConfig:    #Tab
                xmlPaths = context.scene.I3D_UIexportSettings.i3D_updateXMLFilePath.split(";")
                for xmlPath in xmlPaths:
                    if xmlPath != "":
                        xmlPathRel = xmlPath
                        if bpy.data.filepath != "":
                            if os.path.isfile(bpy.data.filepath):
                                try:
                                    xmlPathRel = os.path.relpath(xmlPath, bpy.data.filepath).replace("..\\", "")
                                except ValueError:
                                    pass

                        row = box.row()
                        row.label(text=xmlPathRel)
                        row.operator("i3d.panelremovexmlpath_buttonremove", text="", icon='X').state = xmlPath

                row = box.row(align=True)
                row.alignment = 'RIGHT'
                row.label(text="Add XML Config File  ")
                row.operator("i3d.openxmlfilebrowser", text="", icon='PLUS')
            # -----------------------------------------


            # Warning message (TOP of panel)
            if missing_path:
                warning_box = layout.box()
                warning_box.alert = True  # yellow warning style

                row = warning_box.row()
                row.label(text="⚠  MISSING GAME INSTALLATION ⚠", icon='ERROR')

                row = warning_box.row()
                row.label(text="⚠  LOCATION NOT SET ⚠")

                row = warning_box.row()
                row.scale_x = 1.4
                op = row.operator("preferences.addon_show", text="Set", icon="FILE_FOLDER")
                op.module = "io_export_i3d_reworked"
            # "Output File" box
            box = layout.box()
            row = box.row()
            # expand button for "Output File"
            row.prop(   context.scene.I3D_UIexportSettings,
                        "UI_outputFile",
                        text = "Output File",
                        icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_outputFile else 'TRIA_RIGHT',
                        icon_only = False,
                        emboss = False )
            if context.scene.I3D_UIexportSettings.UI_outputFile:    #Tab
                row = box.row()
                row.prop( context.scene.I3D_UIexportSettings, "i3D_exportUseSoftwareFileName" )
                row = box.row()
                row.enabled = not context.scene.I3D_UIexportSettings.i3D_exportUseSoftwareFileName
                row.prop( context.scene.I3D_UIexportSettings, "i3D_exportFileLocation" )
                row.operator("i3d.openi3dfilebrowser",icon = 'FILEBROWSER',text = "")
            #-----------------------------------------
            row = layout.row()
            row.operator("i3d.colorlib_clear_preview_material_nodes", text="Clear all temporary preview material shader Nodes", icon='X')
            row = layout.row( align = True )
            if(bpy.context.scene.I3D_UIexportSettings.i3D_exportUseSoftwareFileName):
                row.enabled =  not(bpy.data.filepath == "")
            else:
                row.enabled =  not(bpy.context.scene.I3D_UIexportSettings.i3D_exportFileLocation == "")
            row.operator( "i3d.panelexport_buttonexport", text = "Export All"      ).state = 1
            row.operator( "i3d.panelexport_buttonexport", text = "Export Selected" ).state = 2
            row = layout.row()
            row.operator( "i3d.panelexport_buttonexport", text = "Update XML" ).state = 3
        #-----------------------------------------
        # "Attributes" tab
        elif 'attr' == context.scene.I3D_UIexportSettings.UI_settingsMode:
            #-----------------------------------------
            # "Current Node" box
            box = layout.box()
            row = box.row()
            # expand button for "Current Node"
            row.prop(   context.scene.I3D_UIexportSettings,
                        "UI_currentNode",
                        text = "Loaded Node",
                        icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_currentNode else 'TRIA_RIGHT',
                        icon_only = False,
                        emboss = False )
            # expanded view
            if context.scene.I3D_UIexportSettings.UI_currentNode:
                row = box.row()
                row.prop( context.scene.I3D_UIexportSettings, "UI_autoAssign", text = "Auto Assign")
                row = box.row()
                row.enabled = False
                row.prop( context.scene.I3D_UIexportSettings, "i3D_nodeName", text = "Loaded Node" )
                row = box.row()
                row.enabled = False
                row.prop( context.scene.I3D_UIexportSettings, "i3D_nodeIndex", text = "Node Index" )
                row = box.row()
                row.prop( context.scene.I3D_UIexportSettings, "i3D_lockedGroup", text = "Locked Group" )
            #-----------------------------------------
            # "Predefined Body" box
            box = layout.box()
            row = box.row()
            row.prop(   context.scene.I3D_UIexportSettings,
                        "UI_predefined",
                        text = "Predefined",
                        icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_predefined else 'TRIA_RIGHT',
                        icon_only = False,
                        emboss = False )
            if context.scene.I3D_UIexportSettings.UI_predefined:
                row = box.row()
                row.prop(context.scene.I3D_UIexportSettings,"i3D_predefinedPhysic")
                row = box.row()
                row.prop(context.scene.I3D_UIexportSettings,"i3D_predefinedNonPhysic")
                row = box.row()
                row.label(text = "Current Preset:")
                row.label(text = context.scene.I3D_UIexportSettings.i3D_selectedPredefined + ("*" if context.scene.I3D_UIexportSettings.i3D_predefHasChanged  else ""))
            #-----------------------------------------
            # "Rigid Body" box
            box = layout.box()
            row = box.row()
            # expand button for "Rigid Body"
            row.prop(   context.scene.I3D_UIexportSettings,
                        "UI_rigidBody",
                        text = "Rigid Body",
                        icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_rigidBody else 'TRIA_RIGHT',
                        icon_only = False,
                        emboss = False)
            # expanded view
            if context.scene.I3D_UIexportSettings.UI_rigidBody:
                col = box.column()
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_static",                text = "Static" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_kinematic",             text = "Kinematic" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_dynamic",               text = "Dynamic" )
                subcol = col.column()
                subcol.enabled = not context.scene.I3D_UIexportSettings.i3D_compoundChild
                subcol.prop( context.scene.I3D_UIexportSettings,  "i3D_compound",              text = "Compound" )
                subcol2 = col.column()
                subcol2.enabled = not context.scene.I3D_UIexportSettings.i3D_compound
                subcol2.prop( context.scene.I3D_UIexportSettings,  "i3D_compoundChild",         text = "Compound Child" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_collision",             text = "Collision" )
                box = col.box()
                row = box.row()
                row.prop(context.scene.I3D_UIexportSettings,"i3D_predefinedCollision")
                row = box.row(align=True)
                row.prop( context.scene.I3D_UIexportSettings,  "i3D_collisionFilterMask",   text = "Colli Fltr Mask" )
                row.operator('i3d.bitmaskeditor', icon='THREE_DOTS',text='').state = 4
                row = box.row(align=True)
                row.prop( context.scene.I3D_UIexportSettings,  "i3D_collisionFilterGroup",  text = "Colli Fltr Group" )
                row.operator('i3d.bitmaskeditor', icon='THREE_DOTS',text='').state = 5
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_restitution",           text = "Restitution" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_staticFriction",        text = "Static Friction" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_dynamicFriction",       text = "Dynamic Friction" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_linearDamping",         text = "Linear Damping" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_angularDamping",        text = "Angular Damping" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_density",               text = "Density" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_solverIterationCount",  text = "Solver Iterations" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_ccd",                   text = "Continues Collision Detection" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_trigger",               text = "Trigger" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_splitType",             text = "Split Type" )
                row = col.row()
                row.prop( context.scene.I3D_UIexportSettings,  "i3D_splitMinU",             text = "Split Min U" )
                row.prop( context.scene.I3D_UIexportSettings,  "i3D_splitMaxU",             text = "Split Max U" )
                row = box.row()
                row.prop( context.scene.I3D_UIexportSettings,  "i3D_splitMinV",             text = "Split Min V" )
                row.prop( context.scene.I3D_UIexportSettings,  "i3D_splitMaxV",             text = "Split Max V" )
                row = box.row()
                row.prop( context.scene.I3D_UIexportSettings,  "i3D_splitUvWorldScale",     text = "Split UV's worldScale" )
            #-----------------------------------------
            # "Joint" box
            box = layout.box()
            row = box.row()
            # expand button for "Joint"
            row.prop(   context.scene.I3D_UIexportSettings,
                        "UI_joint",
                        text = "Joint",
                        icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_joint else 'TRIA_RIGHT',
                        icon_only = False,
                        emboss = False )
            # expanded view
            if context.scene.I3D_UIexportSettings.UI_joint:
                col = box.column()
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_joint",            text = "Joint" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_projection",       text = "Projection" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_projDistance",     text = "Projection Distance" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_projAngle",        text = "Projection Angle" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_xAxisDrive",       text = "X-Axis Drive" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_yAxisDrive",       text = "Y-Axis Drive" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_zAxisDrive",       text = "Z-Axis Drive" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_drivePos",         text = "Drive Position" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_driveForceLimit",  text = "Drive Force Limit" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_driveSpring",      text = "Drive Spring" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_driveDamping",     text = "Drive Damping" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_breakableJoint",   text = "Breakable" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_jointBreakForce",  text = "Break Force" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_jointBreakTorque", text = "Break Torque" )
            #-----------------------------------------
            # "Rendering" box
            box = layout.box()
            row = box.row()
            # expand button for "Rendering"
            row.prop(   context.scene.I3D_UIexportSettings,
                        "UI_rendering",
                        text = "Rendering",
                        icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_rendering else 'TRIA_RIGHT',
                        icon_only = False,
                        emboss = False )
            # expanded view
            if context.scene.I3D_UIexportSettings.UI_rendering:
                col = box.column()
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_oc",             text = "Occluder" )
                row = col.row()
                row.prop( context.scene.I3D_UIexportSettings,  "i3D_castsShadows",   text = "Casts Shadows" )
                row.prop( context.scene.I3D_UIexportSettings,  "i3D_castsShadowsPerInstance",   text = "Per Instance" )
                row = col.row()
                row.prop( context.scene.I3D_UIexportSettings,  "i3D_receiveShadows", text = "Receives Shadows" )
                row.prop( context.scene.I3D_UIexportSettings,  "i3D_receiveShadowsPerInstance", text = "Per Instance" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_renderedInViewports", text = "Rendered in Viewports" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_nonRenderable",  text = "Non Renderable" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_clipDistance",   text = "Clip Distance" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_objectMask",     text = "Object Mask" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_navMeshMask",    text = "Nav Mesh Mask" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_doubleSided",    text = "Double Sided" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_decalLayer",     text = "Decal Layer" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_mergeGroup",     text = "Merge Group" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_mergeGroupRoot", text = "Merge Group Root" )

                split = col.split(factor=0.25)
                split.label(text="Bounding Volume")
                split.prop( context.scene.I3D_UIexportSettings,  "i3D_boundingVolume", text = "" )
                col2 = split.column()
                col2.prop(context.scene.I3D_UIexportSettings, "i3D_boundingVolumeMergeGroup")

                col = col.column()
                try:

                    if context.scene.I3D_UIexportSettings.i3D_nodeName in bpy.data.objects and bpy.data.objects[context.scene.I3D_UIexportSettings.i3D_nodeName].type == "EMPTY":
                        split = col.split(factor=0.3)
                        split.prop(  context.scene.I3D_UIexportSettings, "i3D_mergeChildren")

                        col2 = split.column()
                        # col2.enabled = context.scene.I3D_UIexportSettings.i3D_mergeChildren   #alternative option
                        if context.scene.I3D_UIexportSettings.i3D_mergeChildren:
                            col2.label(text="Freeze Attribute")
                            subSplit = col2.split()
                            col2.prop(context.scene.I3D_UIexportSettings,"i3D_mergeChildrenFreezeTranslation")
                            col2.prop(context.scene.I3D_UIexportSettings,"i3D_mergeChildrenFreezeRotation")
                            col2.prop(context.scene.I3D_UIexportSettings,"i3D_mergeChildrenFreezeScale")
                except Exception as e:
                    print(e)
                    pass

                col.prop( context.scene.I3D_UIexportSettings,  "i3D_terrainDecal",   text = "Terrain Decal" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_cpuMesh",        text = "CPU Mesh" )
                col.prop( context.scene.I3D_UIexportSettings,  "i3D_lod",            text = "LOD" )
                row = col.row()
                row.enabled = False
                row.prop( context.scene.I3D_UIexportSettings, "i3D_lod0", text = "Child 0 Distance" )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_lod1", text = "Child 1 Distance" )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_lod2", text = "Child 2 Distance" )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_lod3", text = "Child 3 Distance" )
                row = box.row()
                row.prop( context.scene.I3D_UIexportSettings, "i3D_vertexCompressionRange")
            #-----------------------------------------
            # "Environment" box
            box = layout.box()
            row = box.row()
            row.prop( context.scene.I3D_UIexportSettings,
                        "UI_environment",
                        text = "Visibility Conditions",
                        icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_environment else 'TRIA_RIGHT',
                        icon_only = False,
                        emboss = False )
            if context.scene.I3D_UIexportSettings.UI_environment:
                col = box.column()
                col.prop( context.scene.I3D_UIexportSettings, "i3D_minuteOfDayStart", text = "Minute Of Day Start" )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_minuteOfDayEnd", text = "Minute Of Day End" )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_dayOfYearStart", text = "Day Of Year Start" )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_dayOfYearEnd", text = "Day Of Year End" )
                box = col.box()
                row = box.row()
                row.prop( context.scene.I3D_UIexportSettings, "i3D_weatherMask", text = "Weather Mask (Dec)" )
                row.operator('i3d.bitmaskeditor', icon='THREE_DOTS',text='').state = 0
                row = box.row()
                row.prop( context.scene.I3D_UIexportSettings, "i3D_weatherPreventMask", text = "Weather Prevent Mask (Dec)" )
                row.operator('i3d.bitmaskeditor',  icon='THREE_DOTS',text='').state = 1
                row = box.row()
                row.prop( context.scene.I3D_UIexportSettings, "i3D_viewerSpacialityMask", text = "Viewer Spaciality Mask (Dec)" )
                row.operator('i3d.bitmaskeditor',  icon='THREE_DOTS',text='').state = 2
                row = box.row()
                row.prop( context.scene.I3D_UIexportSettings, "i3D_viewerSpacialityPreventMask", text = "Viewer Spaciality Prevent Mask (Dec)" )
                row.operator('i3d.bitmaskeditor',  icon='THREE_DOTS',text='').state = 3
                col.prop( context.scene.I3D_UIexportSettings, "i3D_renderInvisible", text = "Render Invisible")
                col.prop( context.scene.I3D_UIexportSettings, "i3D_visibleShaderParam", text = "Visible Shader Param" )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_forceVisibilityCondition", text = "Force Visibility Condition" )

            #-----------------------------------------
            # "Object Data Texture" box
            box = layout.box()
            row = box.row()
            row.prop( context.scene.I3D_UIexportSettings,
                        "UI_objectDataTexture",
                        text = "Object Data Texture",
                        icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_objectDataTexture else 'TRIA_RIGHT',
                        icon_only = False,
                        emboss = False )
            if context.scene.I3D_UIexportSettings.UI_objectDataTexture:
                col = box.column()
                col.prop( context.scene.I3D_UIexportSettings, "i3D_objectDataFilePath", text = "File Path" )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_objectDataHierarchicalSetup", text = "Hierarchical Setup" )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_objectDataHideFirstAndLastObject", text = "HideFirst And Last" )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_objectDataExportPosition", text = "Export Position" )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_objectDataExportOrientation", text = "Export Orientation" )
                col.prop( context.scene.I3D_UIexportSettings, "i3D_objectDataExportScale", text = "Export Scale" )

            #-----------------------------------------
            # "Light" attributes box
            if context.scene.I3D_UIexportSettings.UI_showLightAttributes:
                box = layout.box()
                row = box.row()
                row.prop( context.scene.I3D_UIexportSettings,
                            "UI_lightAttributes",
                            text = "Light",
                            icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_lightAttributes else 'TRIA_RIGHT',
                            icon_only = False,
                            emboss = False )
                if context.scene.I3D_UIexportSettings.UI_lightAttributes:
                    col = box.column()
                    col.prop( context.scene.I3D_UIexportSettings, "UI_lightUseShadow")
                    enableShadowSettings = False
                    if context.scene.I3D_UIexportSettings.UI_lightUseShadow:
                        enableShadowSettings = True
                    propRow = col.row()
                    propRow.prop( context.scene.I3D_UIexportSettings, "i3D_softShadowsLightSize")
                    propRow.enabled = enableShadowSettings
                    propRow = col.row()
                    propRow.prop( context.scene.I3D_UIexportSettings, "i3D_softShadowsLightDistance")
                    propRow.enabled = enableShadowSettings
                    propRow = col.row()
                    propRow.prop( context.scene.I3D_UIexportSettings, "i3D_softShadowsDepthBiasFactor")
                    propRow.enabled = enableShadowSettings
                    propRow = col.row()
                    propRow.prop( context.scene.I3D_UIexportSettings, "i3D_softShadowsMaxPenumbraSize")
                    propRow.enabled = enableShadowSettings

                    iesProfileFileRow = col.row()
                    iesProfileFileRow.prop( context.scene.I3D_UIexportSettings, "i3D_iesProfileFile", text = "IES Profile File")
                    iesProfileFileRow.operator("i3d.openiesfilebrowser", icon = 'FILEBROWSER', text = "")

                    scatteringEnabled = False
                    currentNodeIsSpotLight = False
                    if "i3D_nodeName" in context.scene.I3D_UIexportSettings:
                        currentNode = bpy.data.objects[context.scene.I3D_UIexportSettings.i3D_nodeName]
                        if currentNode.type == 'LIGHT' and (currentNode.data.type == 'SPOT' or currentNode.data.type == 'POINT'):
                            scatteringEnabled = True
                            currentNodeIsSpotLight = currentNode.data.type == 'SPOT'
                    propRow = col.row()
                    propRow.prop( context.scene.I3D_UIexportSettings, "i3D_isLightScattering")
                    propRow.enabled = scatteringEnabled
                    propRow = col.row()
                    propRow.prop( context.scene.I3D_UIexportSettings, "i3D_lightScatteringIntensity")
                    propRow.enabled = scatteringEnabled and context.scene.I3D_UIexportSettings.i3D_isLightScattering
                    propRow = col.row()
                    propRow.prop( context.scene.I3D_UIexportSettings, "i3D_lightScatteringConeAngle")
                    propRow.enabled = currentNodeIsSpotLight and context.scene.I3D_UIexportSettings.i3D_isLightScattering

            #-----------------------------------------
            row = layout.row( align = True )
            # row.enabled = not context.scene.I3D_UIexportSettings.UI_autoAssign
            col = row.column()
            col.enabled = not context.scene.I3D_UIexportSettings.UI_autoAssign
            col.operator( "i3d.panelexport_buttonattr", text = "Load"    ).state = 1
            col = row.column()
            col.enabled = not context.scene.I3D_UIexportSettings.UI_autoAssign
            col.operator( "i3d.panelexport_buttonattr", text = "Apply"    ).state = 2
            col = row.column()
            # col.enabled = not context.scene.I3D_UIexportSettings.UI_autoAssign
            col.operator( "i3d.panelexport_buttonattr", text = "Remove"  ).state = 3
            row = layout.row( align = True )
            row.enabled = not context.scene.I3D_UIexportSettings.UI_autoAssign

            #-----------------------------------------
        # "Shader" tab
        #-----------------------------------------
        elif 'shader' == context.scene.I3D_UIexportSettings.UI_settingsMode:
            # Custom shader folder.
            box = layout.box()
            row = box.row()
            row.prop(   context.scene.I3D_UIexportSettings,
                        "UI_shaderFolder",
                        text = "Shaders Folder",
                        icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_shaderFolder else 'TRIA_RIGHT',
                        icon_only = False,
                        emboss = False )

            if context.scene.I3D_UIexportSettings.UI_shaderFolder:
                split = box.split(factor = 0.8)
                split.prop(context.scene.I3D_UIexportSettings, "i3D_shaderFolderLocation")
                row = split.row()
                row.operator("i3d.openfolderfilebrowser", icon='FILEBROWSER',text = "").state = 2

                if dirf.isWindows():

                    row.operator("i3d.panelsetgameshader", icon='ZOOM_ALL')
            # Shader Setup (collapsible)
            ss_box = layout.box()
            ss_row = ss_box.row()
            ss_row.prop(   context.scene.I3D_UIexportSettings,
                        "UI_shaderSetup",
                        text = "Shader Setup",
                        icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_shaderSetup else 'TRIA_RIGHT',
                        icon_only = False,
                        emboss = False )

            if context.scene.I3D_UIexportSettings.UI_shaderSetup:
                # Selected material dropdown.
                box = ss_box.box()
                row = box.row()
                split = row.split(factor = 0.8)
                row = split.row()
                row.prop(context.scene.I3D_UIexportSettings, "i3D_selectedMaterialEnum")
                row = split.row()
                row.operator("i3d.openmaterialtemplateswindow")

                # Shader and variation dropdowns.
                box = ss_box.box()
                row = box.row()
                row.prop(context.scene.I3D_UIexportSettings,"i3D_shaderEnum")
                row = box.row()
                try:
                    row.prop(context.scene.I3D_UIshaderVariation, "i3D_shaderVariationEnum")
                except:
                    row.prop(context.scene.I3D_UIexportSettings, "i3D_shaderVariationEnum")

                # Custom parameters and textures.
                box = ss_box.box()
                row = box.row()
                row.label(text="Parameters")

                global g_dynamicGUIClsDict
                if "parameters" in g_dynamicGUIClsDict:
                    enableText = False
                    for k,i in g_dynamicGUIClsDict["parameters"].__annotations__.items():
                        if k.endswith("Bool"):
                            row = box.row()
                            row.prop(context.scene.I3D_UIShaderParameters,k,text="")
                            if (getattr(context.scene.I3D_UIShaderParameters, k)):
                                enableText = True
                            else:
                                enableText = False
                        else:
                            if(k.endswith("_0")):
                                row.label(text=k.strip("_0"))
                            row_items = row.row()
                            row_items.enabled = enableText
                            row_items.prop(context.scene.I3D_UIShaderParameters,k,text= "")

                box = ss_box.box()
                row = box.row()
                row.label(text="Textures")
                if "textures" in g_dynamicGUIClsDict:
                    enableText = False
                    for k,i in g_dynamicGUIClsDict["textures"].__annotations__.items():
                        if k.endswith("Bool"):
                            row = box.row()
                            row.prop(context.scene.I3D_UIShaderTextures,k,text="")
                            if (getattr(context.scene.I3D_UIShaderTextures, k)):
                                enableText = True
                            else:
                                enableText = False
                        else:
                            row_items = row.row()
                            row_items.enabled = enableText
                            row_items.prop(context.scene.I3D_UIShaderTextures,k)

                for dynamicGUIClsName, dynamicGUICls in g_dynamicGUIClsDict.items():
                    if dynamicGUIClsName == "textures" or dynamicGUIClsName == "parameters":
                        continue
                    # Otherwise we assume that its a template parameter
                    clssName = 'I3D_UITemplateParameters_'+dynamicGUIClsName

                    box = ss_box.box()
                    row = box.row()
                    row.label(text=dynamicGUIClsName) # TODO(jdellsperger): brandColor instead of Brand Color...

                    try:
                        dataClass = getattr(context.scene, clssName)
                    except Exception as e:
                        print("Could not add class {} to scene".format(clssName))
                        print(e)
                        continue
                    else:
                        enableText = False
                        for k,i in dynamicGUICls.__annotations__.items():
                            if k.endswith("Bool"):
                                row = box.row()
                                row.prop(dataClass, k,text="")
                                if (getattr(dataClass, k)):
                                    enableText = True
                                else:
                                    enableText = False
                            else:
                                if k.endswith("_0"):
                                    split = row.split(factor=0.195)
                                    c = split.column()
                                    c.label(text=k[:-2])
                                    row = split.split()
                                elif not k.endswith("_1") and not k.endswith("_2") and not k.endswith("_3") and not k.startswith("templatedParameterTemplateMenu_"):
                                    if "name" in i.keywords:
                                        # This is a template dropdown
                                        split = row.split(factor=0.195)
                                        c = split.column()
                                        c.label(text=i.keywords["name"])
                                        row = split.split()
                                    else:
                                        split = row.split(factor=0.195)
                                        c = split.column()
                                        c.label(text=k)
                                        row = split.split()
                                row_items = row.row()
                                row_items.enabled = enableText
                                row_items.prop(dataClass, k, text = "")

                box = ss_box.box()
                row = box.row()
                row.prop(context.scene.I3D_UIexportSettings,'i3D_shadingRate')
                row = box.row()
                split = row.split(factor = 0.7)
                row = split.row()
                row.prop(context.scene.I3D_UIexportSettings, "i3D_materialSlotName")
                row = split.row()
                row.operator("i3d.usematerialnameasslotname")
                row = box.row()
                row.prop(context.scene.I3D_UIexportSettings,'i3D_alphaBlending')

                box = ss_box.box()
                row = box.row()
                row.prop(   context.scene.I3D_UIexportSettings,
                            "UI_refractionMap",
                            text = "Refraction Map",
                            icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_refractionMap else 'TRIA_RIGHT',
                            icon_only = False,
                            emboss = False )
                if context.scene.I3D_UIexportSettings.UI_refractionMap:
                    row = box.row()
                    row.prop(context.scene.I3D_UIexportSettings, 'i3D_refractionMap')
                    row = box.row()
                    row.prop(context.scene.I3D_UIexportSettings, 'i3D_refractionMapLightAbsorbance')
                    row.enabled = context.scene.I3D_UIexportSettings.i3D_refractionMap
                    row = box.row()
                    row.prop(context.scene.I3D_UIexportSettings, 'i3D_refractionMapBumpScale')
                    row.enabled = context.scene.I3D_UIexportSettings.i3D_refractionMap
                    row = box.row()
                    row.prop(context.scene.I3D_UIexportSettings, 'i3D_refractionMapWithSSRData')
                    row.enabled = context.scene.I3D_UIexportSettings.i3D_refractionMap


                # Load / Apply (moved into Shader Setup)
                box = ss_box.box()
                row = box.row(align=True)
                row.operator("i3d.paneladdshader_buttonload")
                row.operator("i3d.paneladdshader_buttonadd")
            # Color Library (below Refraction Map box)
            cl_box = layout.box()
            cl_row = cl_box.row()
            cl_row.prop(
                context.scene.I3D_UIexportSettings,
                "UI_colorLibrary",
                text="Color Library",
                icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_colorLibrary else 'TRIA_RIGHT',
                icon_only=False,
                emboss=False,
            )
            if context.scene.I3D_UIexportSettings.UI_colorLibrary:
                try:
                    i3d_colorLibrary.draw_color_library(cl_box, context)
                except Exception as e:
                    _i3d_print_draw_fail_once("I3D Color Library", e)


            # Vehicle Light Setup Tool (between Color Library and Material Tools)
            try:
                from .tools import i3d_vehicle_light_tool
                i3d_vehicle_light_tool.draw_vehicle_light_setup_tool(layout, context)
            except Exception as e:
                _i3d_print_draw_fail_once("I3D Vehicle Light Tool", e)

            # Material Tools (GamerDesigns / Modders Edge)
            mat_tools_outer_box = layout.box()
            row = mat_tools_outer_box.row()
            row.prop(
                context.scene.I3D_UIexportSettings,
                "UI_meMaterialToolsMain",
                text="Material Tools",
                icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_meMaterialToolsMain else 'TRIA_RIGHT',
                icon_only=False,
                emboss=False
            )

            if context.scene.I3D_UIexportSettings.UI_meMaterialToolsMain:
                mat_tools_box = mat_tools_outer_box.box()

                # -------------------------
                # Cleanup: Material Cleanup
                # -------------------------
                me_mat_outer_box = mat_tools_box.box()
                row = me_mat_outer_box.row()
                row.prop(
                    context.scene.I3D_UIexportSettings,
                    "UI_meMaterialCleanup",
                    text="Material Cleanup",
                    icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_meMaterialCleanup else 'TRIA_RIGHT',
                    icon_only=False,
                    emboss=False
                )

                if context.scene.I3D_UIexportSettings.UI_meMaterialCleanup:
                    me_mat_box = me_mat_outer_box.box()
                    row = me_mat_box.row(align=True); row.scale_y = 1.1
                    row.operator("i3d.me_remove_unused_materials", text="Remove Unused Materials", icon="MATERIAL")


                # -------------------------
                # Tools: Replace Material A → B
                # -------------------------
                me_replace_outer_box = mat_tools_box.box()
                row = me_replace_outer_box.row()
                row.prop(
                    context.scene.I3D_UIexportSettings,
                    "UI_meMaterialReplace",
                    text="Replace Material A → B",
                    icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_meMaterialReplace else 'TRIA_RIGHT',
                    icon_only=False,
                    emboss=False
                )

                if context.scene.I3D_UIexportSettings.UI_meMaterialReplace:
                    me_replace_box = me_replace_outer_box.box()
                    col = me_replace_box.column(align=True)

                    col.prop(context.scene.I3D_UIexportSettings, "me_replace_scope", text="Scope")

                    row = col.row(align=True)
                    row.prop(context.scene.I3D_UIexportSettings, "me_replace_from", text="From")
                    row.prop(context.scene.I3D_UIexportSettings, "me_replace_to", text="To")

                    col.operator("i3d.me_material_replace_batch", text="Replace Material A → B", icon='FILE_REFRESH')

                mat_tools_box.separator()
                row = mat_tools_box.row(); row.alignment = 'CENTER'
                row.label(text="License MIT")
                row = mat_tools_box.row(); row.alignment = 'CENTER'
                row.label(text="Made by GamerDesigns")

            #-----------------------------------------
            # FS22 → FS25 Convert Tool (Material/Shader Tab)
            # NOTE: This folder should stay at the VERY BOTTOM of the Material tab.
            #-----------------------------------------
            convert_outer_box = layout.box()
            row = convert_outer_box.row()
            row.prop(
                context.scene.I3D_UIexportSettings,
                "UI_materialTools",
                text="Tools",
                icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_materialTools else 'TRIA_RIGHT',
                icon_only=False,
                emboss=False
            )
            if context.scene.I3D_UIexportSettings.UI_materialTools:
                row = convert_outer_box.row()
                row.operator("i3d.paneladdshader_buttonconvertfs22fs25")


#-----------------------------------------

        # row = layout.row( )
        # row.operator( "i3d.panelexport_buttonclose", icon = 'X' )


# "Tools" tab
        #-----------------------------------------
        elif 'tools' == context.scene.I3D_UIexportSettings.UI_settingsMode:
            box = layout.box()

            row = box.row()
            row.operator( "i3d.paneltools_buttonchangelog", text = "Show Change Log")


            #-----------------------------------------
            # Delta Vertex Color Tool (Roof Snow Heap Tool)
            #-----------------------------------------
            delta_outer_box = layout.box()

            row = delta_outer_box.row()
            row.prop(   context.scene.I3D_UIexportSettings,
                        "UI_deltaVertexTool",
                        text = "Delta → Vertex Color (Roof Snow Heap Tool)",
                        icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_deltaVertexTool else 'TRIA_RIGHT',
                        icon_only = False,
                        emboss = False )

            if context.scene.I3D_UIexportSettings.UI_deltaVertexTool:
                delta_box = delta_outer_box.box()
                row = delta_box.row()
                row.label(text="Tutorials")

                split = row.split(factor=0.4)
                col_left = split.column()
                col_left.operator(
                    "i3d.open_english_tutorial",
                    text="English",
                    icon='PLAY'
                )

                split = split.split(factor=0.4)
                col_right = split.column()
                col_right.operator(
                    "i3d.open_french_tutorial",
                    text="French",
                    icon='PLAY'
                )

                row = delta_box.row()
                row.alignment = 'CENTER'

                row.prop(
                    context.scene.I3D_UIexportSettings,
                    "i3D_exportSnowHeapMode",
                    text="Snow Heap Mode"
                )

                row.operator(
                    "i3d.show_delta_bake_location",
                    text="Show Me Where this Tool Is!",
                    icon='INFO'
                )

                row = delta_box.row()
                row.alignment = 'CENTER'
                row.label(text="License GNU GPL")

                row = delta_box.row()
                row.alignment = 'CENTER'
                row.label(text="Made by Fuxna & Redphoenix")

            row = box.row()
            row.prop(   context.scene.I3D_UIexportSettings,
                "UI_customTools",
                text = "Custom Tools",
                icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_customTools else 'TRIA_RIGHT',
                icon_only = False,
                emboss = False )

            row = box.row()
            if context.scene.I3D_UIexportSettings.UI_customTools:
                # row.label(text="export DDS")
                col = row.column()

                row = col.row(align = True)
                row.operator("i3d.selectiontoorigin", text="SelectionToOrigin")
                row.operator("i3d.facenormaltoorigin", text="FaceNormalToOrigin")

                row = col.row(align = True)
                row.operator("i3d.freezetranslation", text="FreezeTranslation")
                row.operator("i3d.freezerotation", text="FreezeRotation")

                row = col.row(align = True)
                row.operator("i3d.createempty", text="Create Empty")
                row.operator("i3d.alignyaxis", text="AlignYAxis")

                col.operator("i3d.paneltools_button", text="Export Object Data Texture").state = 1
                try:
                #TODO: smart loop for UI elements
                    row = col.row(align = True)
                    row.operator("i3d.motionpathpopup")
                    row.operator("i3d.motionpathobjectpopup")

                    row = col.row(align = True)
                    row.operator("i3d.vertexcolorpopup")
                    row.operator("i3d.splinetoolpopup")
                except:
                    pass


            #-----------------------------------------
            # Track Array Tools
            # Created by DtapGaming and RMC Gamer Designs
            #-----------------------------------------
            track_outer_box = layout.box()
            row = track_outer_box.row()
            row.prop(
                context.scene.I3D_UIexportSettings,
                "UI_trackArrayToolsMain",
                text="Track Array Tools",
                icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_trackArrayToolsMain else 'TRIA_RIGHT',
                icon_only=False,
                emboss=False
            )
            # Always-available quick button (even when collapsed)
            row.operator("i3d.import_track_setup_system", text="", icon='FILE_BLEND')
            row.operator("i3d.generate_track_curve_from_guides", text="", icon='CURVE_DATA')

            if context.scene.I3D_UIexportSettings.UI_trackArrayToolsMain:
                track_box = track_outer_box.box()
                row = track_box.row()
                row.alignment = 'CENTER'
                row.label(text="Created by DtapGaming and RMC Gamer Designs")

                row = track_box.row()
                row.operator("i3d.import_track_setup_system", icon='FILE_BLEND')

                row = track_box.row()
                row.operator("i3d.generate_track_curve_from_guides", text="Generate Custom Track Setup System From Guides", icon='CURVE_DATA')

                row = track_box.row()
                op = row.operator("wm.url_open", text="Open Tutorial (YouTube)", icon='URL')
                op.url = "https://youtu.be/CZ7a_hW3T1E"
            #-----------------------------------------
            # Modders Edge Toolset (Tools + Cleanup)
            # Credit: GamerDesigns (MIT License)
            #-----------------------------------------
            me_tools_outer_box = layout.box()
            row = me_tools_outer_box.row()
            row.prop(
                context.scene.I3D_UIexportSettings,
                "UI_meToolsMain",
                text="Modders Edge Tools",
                icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_meToolsMain else 'TRIA_RIGHT',
                icon_only=False,
                emboss=False
            )

            if context.scene.I3D_UIexportSettings.UI_meToolsMain:
                me_tools_box = me_tools_outer_box.box()
                mode = context.mode


                # -------------------------
                # Cleanup: Vertex / Geometry Tools
                # -------------------------
                me_vtx_outer_box = me_tools_box.box()
                row = me_vtx_outer_box.row()
                row.prop(
                    context.scene.I3D_UIexportSettings,
                    "UI_meVertexGeoTools",
                    text="Vertex / Geometry Tools",
                    icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_meVertexGeoTools else 'TRIA_RIGHT',
                    icon_only=False,
                    emboss=False
                )

                if context.scene.I3D_UIexportSettings.UI_meVertexGeoTools:
                    me_vtx_box = me_vtx_outer_box.box()
                    row = me_vtx_box.row(align=True)
                    row.prop(context.scene.I3D_UIexportSettings, "i3D_ME_mergeDistance", text="Merge")
                    row.prop(context.scene.I3D_UIexportSettings, "i3D_ME_convertToQuads", text="To Quads")

                    row = me_vtx_box.row(align=True); row.scale_y = 1.1
                    op = row.operator("i3d.me_vertex_cleanup", text="Vertex Cleanup", icon="VERTEXSEL")
                    op.merge_distance = context.scene.I3D_UIexportSettings.i3D_ME_mergeDistance

                    op = row.operator("i3d.me_better_tris", text="Better Tris / Quads", icon="MESH_DATA")
                    op.convert_to_quads = context.scene.I3D_UIexportSettings.i3D_ME_convertToQuads

                # -------------------------
                # Tools: Cursor & Origin
                # -------------------------
                me_cursor_outer_box = me_tools_box.box()
                row = me_cursor_outer_box.row()
                row.prop(
                    context.scene.I3D_UIexportSettings,
                    "UI_meCursorOrigin",
                    text="Cursor & Origin",
                    icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_meCursorOrigin else 'TRIA_RIGHT',
                    icon_only=False,
                    emboss=False
                )

                if context.scene.I3D_UIexportSettings.UI_meCursorOrigin:
                    me_cursor_box = me_cursor_outer_box.box()
                    col = me_cursor_box.column(align=True)

                    row = col.row(align=True); row.scale_y = 1.1
                    row.operator("view3d.snap_cursor_to_selected", text="Cursor to Selected", icon="RESTRICT_SELECT_OFF")
                    row.operator("view3d.snap_cursor_to_center", text="Cursor to World Origin", icon="CURSOR")
                    row.operator("view3d.snap_selected_to_cursor", text="Selection to Cursor", icon="PIVOT_CURSOR").use_offset = False

                    row = col.row(align=True); row.scale_y = 1.1
                    op = row.operator("object.origin_set", text="Origin to 3D Cursor", icon="PIVOT_CURSOR")
                    op.type = 'ORIGIN_CURSOR'
                    op = row.operator("object.origin_set", text="Origin to Center of Mass", icon="OBJECT_ORIGIN")
                    op.type = 'ORIGIN_CENTER_OF_MASS'

                # -------------------------
                # Tools: Add Objects
                # -------------------------
                me_add_outer_box = me_tools_box.box()
                row = me_add_outer_box.row()
                row.prop(
                    context.scene.I3D_UIexportSettings,
                    "UI_meAddObjects",
                    text="Add Objects",
                    icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_meAddObjects else 'TRIA_RIGHT',
                    icon_only=False,
                    emboss=False
                )

                if context.scene.I3D_UIexportSettings.UI_meAddObjects:
                    me_add_box = me_add_outer_box.box()
                    col = me_add_box.column(align=True)

                    if mode != 'OBJECT':
                        col.enabled = False
                        col.label(text="Switch to Object Mode to add objects here.")
                    else:
                        row = col.row(align=True); row.scale_y = 1.1
                        row.operator("mesh.primitive_cube_add", text="Cube", icon="CUBE")
                        row.operator("mesh.primitive_plane_add", text="Plane", icon="MESH_PLANE")
                        row.operator("mesh.primitive_uv_sphere_add", text="UV Sphere", icon="SPHERE")

                        row = col.row(align=True); row.scale_y = 1.1
                        row.operator("mesh.primitive_cylinder_add", text="Cylinder", icon="MESH_CYLINDER")
                        op = row.operator("object.light_add", text="Light (Point)", icon="LIGHT")
                        op.type = 'POINT'

                        col.operator("object.empty_add", text="Empty (Plain Axes)", icon="EMPTY_AXIS").type = 'PLAIN_AXES'

                # -------------------------
                # Tools: Apply Transforms
                # -------------------------
                me_apply_outer_box = me_tools_box.box()
                row = me_apply_outer_box.row()
                row.prop(
                    context.scene.I3D_UIexportSettings,
                    "UI_meApplyTransforms",
                    text="Apply Transforms",
                    icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_meApplyTransforms else 'TRIA_RIGHT',
                    icon_only=False,
                    emboss=False
                )

                if context.scene.I3D_UIexportSettings.UI_meApplyTransforms:
                    me_apply_box = me_apply_outer_box.box()
                    col = me_apply_box.column(align=True)

                    row = col.row(align=True); row.scale_y = 1.1
                    op = row.operator("object.transform_apply", text="Apply Rotation & Scale", icon="FILE_REFRESH")
                    op.location = False; op.rotation = True; op.scale = True

                    row = col.row(align=True); row.scale_y = 1.1
                    op = row.operator("object.transform_apply", text="Apply Scale", icon="DRIVER_DISTANCE")
                    op.location = False; op.rotation = False; op.scale = True

                # -------------------------
                # Tools: Mesh Cleanup (Edit Mode)
                # -------------------------
                me_meshclean_outer_box = me_tools_box.box()
                row = me_meshclean_outer_box.row()
                row.prop(
                    context.scene.I3D_UIexportSettings,
                    "UI_meMeshCleanup",
                    text="Mesh Cleanup (Edit Mode)",
                    icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_meMeshCleanup else 'TRIA_RIGHT',
                    icon_only=False,
                    emboss=False
                )

                if context.scene.I3D_UIexportSettings.UI_meMeshCleanup:
                    me_meshclean_box = me_meshclean_outer_box.box()
                    col = me_meshclean_box.column(align=True)

                    if mode == 'EDIT_MESH':
                        row = col.row(align=True); row.scale_y = 1.1
                        row.operator("mesh.delete_loose", text="Delete Loose", icon="TRASH")
                        row.operator("mesh.decimate", text="Decimate Geometry", icon="MOD_DECIM")

                        row = col.row(align=True); row.scale_y = 1.1
                        row.operator("mesh.dissolve_degenerate", text="Degenerate Dissolve", icon="X")
                        row.operator("mesh.dissolve_limited", text="Limited Dissolve", icon="FACESEL")

                        row = col.row(align=True); row.scale_y = 1.1
                        row.operator("mesh.fill_holes", text="Fill Holes", icon="MOD_BUILD")
                        row.operator("mesh.tris_convert_to_quads", text="Tris to Quads", icon="MOD_MESHDEFORM")

                        col.operator("mesh.normals_make_consistent", text="Flip Normals", icon="LOOP_BACK").inside = False
                    else:
                        col.enabled = False
                        col.label(text="Switch to Edit Mode to access mesh cleanup tools.")

                # -------------------------
                # Tools: UV Map
                # -------------------------
                me_uv_outer_box = me_tools_box.box()
                row = me_uv_outer_box.row()
                row.prop(
                    context.scene.I3D_UIexportSettings,
                    "UI_meUVMap",
                    text="UV Map",
                    icon='TRIA_DOWN' if context.scene.I3D_UIexportSettings.UI_meUVMap else 'TRIA_RIGHT',
                    icon_only=False,
                    emboss=False
                )

                if context.scene.I3D_UIexportSettings.UI_meUVMap:
                    me_uv_box = me_uv_outer_box.box()
                    col = me_uv_box.column(align=True)

                    if mode == 'EDIT_MESH':
                                            row = col.row(align=True)
                                            row.prop(context.scene.I3D_UIexportSettings, "i3D_ME_uvMargin", text="Margin")
                                            row.prop(context.scene.I3D_UIexportSettings, "i3D_ME_uvIslandMargin", text="Island")

                                            row = col.row(align=True); row.scale_y = 1.1
                                            op = row.operator("i3d.me_uv_unwrap_angle_based", text="Unwrap (Angle Based)", icon="UV")
                                            op.margin = context.scene.I3D_UIexportSettings.i3D_ME_uvMargin

                                            op = row.operator("i3d.me_uv_smart_project_005", text="Smart UV Project (0.005)", icon="UV")
                                            op.island_margin = context.scene.I3D_UIexportSettings.i3D_ME_uvIslandMargin
                    else:
                        col.enabled = False
                        col.label(text="Switch to Edit Mode on a mesh to access UV tools.")


                me_tools_box.separator()
                row = me_tools_box.row(); row.alignment = 'CENTER'
                row.label(text="License MIT")
                row = me_tools_box.row(); row.alignment = 'CENTER'
                row.label(text="Made by GamerDesigns")

#-----------------------------------------

        # row = layout.row( )
        # row.operator( "i3d.panelexport_buttonclose", icon = 'X' )
    def getMaterials(self, context):
        result = [(mat.name, mat.name, "", "NONE", i + 1) for i, mat in enumerate(bpy.data.materials)]
        result.insert(0, ("None", "None", "", "NONE", 0))
        return result

    def getShadersFromDirectory(self, context):
        """
        Reads the directory and returns a List for the Shader enumerate

        :returns: a Tuple formatted for an bpy.EnumProperty, default is (("None","None","None"))
        """

        gamePath = getGamePath()
        if gamePath is None or gamePath == "":
            gamePath = bpy.context.scene.I3D_UIexportSettings.i3D_gameLocationDisplay
        dirPath = resolveGiantsPath(bpy.context.scene.I3D_UIexportSettings.i3D_shaderFolderLocation, gamePath)
        dirPath = os.path.abspath(dirPath)
        # print(dirPath)
        try:
            onlyfiles = [f for f in listdir(dirPath) if isfile(join(dirPath, f)) if f.endswith("Shader.xml")]
            fileTuple = tuple()
            # fileTuple = fileTuple + (("None","None","None", 0),)
            index = 0
            for file in onlyfiles:
                fileTuple = fileTuple + ((file,file,file,index),)
                index += 1
            if len(onlyfiles) == 0:
                return (("None","None","None", 0),)
            return fileTuple
        except FileNotFoundError as e:
            # print(e)
            # print("file not found")
            return (("None","None","None", 0),)  #Problem
        except Exception as e:
            print(e)
            print("f2")
            return (("None","None","None", 0),)  #Problem

    def getActiveObjectType(self,context):      #unused
        """ returns the type of the active object """

        objName = context.scene.I3D_UIexportSettings.UI_ActiveObjectName
        return bpy.data.objects[objName].type

    def updateXMLconfigId(self,context):
        """ Updates the XML configuration Id of the active object to the manually set value """
        objName = context.scene.I3D_UIexportSettings.UI_ActiveObjectName
        if objName in bpy.data.objects:
            bpy.data.objects[objName]["I3D_XMLconfigID"] = context.scene.I3D_UIexportSettings.i3D_XMLConfigIdentification
            # bpy.ops.i3d.panelupdatexmli3dmapping()

    def updateXMLconfigBool(self, context):
        """ Updates the XML configuration checkbox of the active object to the manually set value """

        objects = selectionUtil.getSelectedObjects(context)
        for object in objects:
            objName = object.name
            if object.name in bpy.data.objects:
                # while enabeling the xml identifier we directly set the node name as identifier
                if not bpy.data.objects[object.name]["I3D_XMLconfigBool"]:
                    bpy.data.objects[object.name]["I3D_XMLconfigID"] = dccBlender.getFormattedNodeName(object.name)

                bpy.data.objects[objName]["I3D_XMLconfigBool"] = context.scene.I3D_UIexportSettings.i3D_XMLConfigExport

    def sceneObjectItems(self, context):
        """
        Returns a listing of all objects in the scene, except the loaded Node

        :returns: a list of Tuples formatted for a bpy.EnumProperty
        """
        objectList = [("None","None","None")]
        try:
            objectList = [(obj.name,obj.name,obj.name) for obj in context.scene.objects]
            #objectList.remove((context.scene.I3D_UIexportSettings.i3D_nodeName,context.scene.I3D_UIexportSettings.i3D_nodeName,context.scene.I3D_UIexportSettings.i3D_nodeName))
            objectList.append(("None","None","None"))
        except:
            pass
        return objectList

class I3D_UIMaterialTemplateProperties(bpy.types.PropertyGroup):
    fileLocation : bpy.props.StringProperty()

    @classmethod
    def register( cls ):
        bpy.types.Scene.I3D_UIMaterialTemplateProperties = bpy.props.PointerProperty(
            name = "I3D UI Material Template Properties",
            type =  cls,
            description = "I3D UI Material Template Properties"
        )
    @classmethod
    def unregister( cls ):
        if bpy.context.scene.get( 'I3D_UIMaterialTemplateProperties' ):  del bpy.context.scene[ 'I3D_UIMaterialTemplateProperties' ]
        try:    del bpy.types.Scene.I3D_UIMaterialTemplateProperties
        except: pass

class I3D_OT_MaterialTemplateCategoryMenu(bpy.types.Operator):
    bl_idname = "i3d.material_template_category_menu_entry_selected"
    bl_label = "Select material template category menu item"
    bl_description = "Select material template category menu item: selects items related to the current view."

    categoryName: bpy.props.StringProperty()

    def execute(self, context):
        global g_selectedMaterialTemplateCategory
        if g_selectedMaterialTemplateCategory == self.categoryName:
            g_selectedMaterialTemplateCategory = None
        else:
            g_selectedMaterialTemplateCategory = self.categoryName
        #self.report({"INFO"}, "{} material template category selected".format(self.categoryName))
        return {'FINISHED'}

class I3D_OT_MaterialTemplateCategoryMenuEntryExpand(bpy.types.Operator):
    bl_idname = "i3d.material_template_category_menu_entry_expand"
    bl_label = "Expand material template category menu item"
    bl_description = "Expand material template category menu item."

    categoryName: bpy.props.StringProperty()

    def execute(self, context):
        categoryPath = self.categoryName.split("_")

        currentMaterialTemplateCategoryDict = g_loadedMaterialTemplates
        for category in categoryPath:
            currentMaterialTemplateCategoryDict = currentMaterialTemplateCategoryDict[category]

        currentMaterialTemplateCategoryDict["expanded"] = not currentMaterialTemplateCategoryDict["expanded"]

        #self.report({"INFO"}, "{} material template category expanded".format(self.categoryName))
        return {'FINISHED'}

class I3D_PT_MaterialTemplates(bpy.types.Panel):
    """GUI Panel for the GIANTS Material Templates Library"""
    bl_idname = "I3D_PT_MaterialTemplates"
    bl_label = "GIANTS Material Templates Library"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GIANTS I3D Exporter REWORKED"

    def renderCategoryMenuEntry(self, context, parentBox, category, categoryTitle, categoryOpen, childList):
        hasChildren = len(childList) > 2 # expanded, thumbnails

        row = parentBox.row()

        iconName = "NONE"
        if hasChildren:
            if categoryOpen:
                iconName = "TRIA_DOWN"
            else:
                iconName = "TRIA_RIGHT"

            o = row.operator("i3d.material_template_category_menu_entry_expand", text = "", icon = iconName)
            o.categoryName = category
        else:
            row.label(text="", icon="DOT")

        o = row.operator("i3d.material_template_category_menu_entry_selected", text = categoryTitle, depress = g_selectedMaterialTemplateCategory == category)
        o.categoryName = category

        if not hasChildren or not categoryOpen:
            return

        childBoxRow = parentBox.row()
        childBox = childBoxRow.box()
        for subCategoryName, subCategory in childList.items():
            if subCategoryName == 'templates' or subCategoryName == "expanded" or subCategoryName == "thumbnails":
                continue
            self.renderCategoryMenuEntry(context, childBox, category + "_" + subCategoryName, subCategoryName, childList["expanded"], subCategory)

    def renderPreviewThumbnails(self, previewGrid, categoryDict):
        previewCollection = categoryDict["thumbnails"]
        for materialTemplateName, materialTemplate in previewCollection.items():
            cell = previewGrid.column().box()

            name = prettify_name(materialTemplateName)

            col = cell.column(align=True)
            col.template_icon(materialTemplate.icon_id, scale=10)
            col.label(text=name)
            o = col.operator("i3d.apply_material_template_to_selection")
            # o = col.operator("i3d.apply_material_template_to_selection", text=name)
            o.templateName = materialTemplateName
            o.description_name = name

        for subCategory, subCategoryDict in categoryDict.items():
            if subCategory in ["templates", "expanded", "thumbnails"]:
                continue
            self.renderPreviewThumbnails(previewGrid, subCategoryDict)

    def draw(self, context):
        layout = self.layout

        row = layout.row()
        row.prop(context.scene.I3D_UIMaterialTemplateProperties, "fileLocation", text = "Templates XML File")
        row.operator("i3d.openfolderfilebrowser", icon='FILEBROWSER',text = "").state = 2

        row = layout.row()
        menuLayout = row.split(factor = 0.2)
        menuBox = menuLayout.box()
        previewBox = menuLayout.box()

        for subCategoryName, subCategory in g_loadedMaterialTemplates.items():
            if subCategoryName == 'templates' or subCategoryName == 'expanded' or subCategoryName == "thumbnails":
                continue
            self.renderCategoryMenuEntry(context, menuBox, subCategoryName, subCategoryName, subCategory["expanded"], subCategory)

        previewGrid = previewBox.grid_flow()

        currentMaterialTemplateCategoryDict = g_loadedMaterialTemplates

        if g_selectedMaterialTemplateCategory is not None:
            selectedCategoryPath = g_selectedMaterialTemplateCategory.split("_")
            for category in selectedCategoryPath:
                currentMaterialTemplateCategoryDict = currentMaterialTemplateCategoryDict[category]

            self.renderPreviewThumbnails(previewGrid, currentMaterialTemplateCategoryDict)
        else:
            for category, categoryDict in currentMaterialTemplateCategoryDict.items():
                if category == "templates" or category == "expanded" or category == "thumbnails":
                    continue
                self.renderPreviewThumbnails(previewGrid, categoryDict)

#-------------------------------------------------------------------------------
# Buttons Operators
#-------------------------------------------------------------------------------

class I3D_OT_BitmaskEditor(bpy.types.Operator):
    bl_idname = "i3d.bitmaskeditor"
    bl_label = "Bitmask Editor"
    bl_description = "Bitmask Editor."

    def updtVal(self, context):
        str_dec = stringUtil.int2string_base(int(self.mask_value,10),10)
        str_hex = stringUtil.int2string_base(int(self.mask_value,10),16)
        str_bin = stringUtil.int2string_base(int(self.mask_value,10),2)
        bitList = [self.bit0,self.bit1,self.bit2,self.bit3,self.bit4,self.bit5,self.bit6,self.bit7,self.bit8,self.bit9,self.bit10,self.bit11,self.bit12,self.bit13,self.bit14,self.bit15,self.bit16,
                    self.bit17,self.bit18,self.bit19,self.bit20,self.bit21,self.bit22,self.bit23,self.bit24,self.bit25,self.bit26,self.bit27,self.bit28,self.bit29,self.bit30,self.bit31]
        bitList = list(map(int, bitList))
        bitList.reverse()
        strList = list(map(str,bitList))
        str_bit = ''.join(strList)
        if self.dec_mask != str_dec:
            self.dec_mask = str_dec
        if self.hex_mask != str_hex:
            self.hex_mask = str_hex
        if self.bin_mask != str_bin:
            self.bin_mask = str_bin
        compare_str_bit = list(str_bin)
        compare_str_bit.reverse()
        compare_str_bit = compare_str_bit[:32] + ['0']*(32- len(compare_str_bit))
        compare_str_bit = ''.join(compare_str_bit)
        if not str_bit == compare_str_bit:
            val_list = list(map(bool,list(map(int,list(compare_str_bit)))))
            self.bit0 = val_list[0]; self.bit1 = val_list[1]; self.bit2 = val_list[2]; self.bit3 = val_list[3]
            self.bit4 = val_list[4]; self.bit5 = val_list[5]; self.bit6 = val_list[6]; self.bit7 = val_list[7]
            self.bit8 = val_list[8]; self.bit9 = val_list[9]; self.bit10 = val_list[10]; self.bit11 = val_list[11]; self.bit12 = val_list[12]; self.bit13 = val_list[13]; self.bit14 = val_list[14]; self.bit15 = val_list[15]
            self.bit16 = val_list[16]; self.bit17 = val_list[17]; self.bit18 = val_list[18]; self.bit19 = val_list[19]; self.bit20 = val_list[20]; self.bit21 = val_list[21]; self.bit22 = val_list[22]; self.bit23 = val_list[23]
            self.bit24 = val_list[24]; self.bit25 = val_list[25]; self.bit26 = val_list[26]; self.bit27 = val_list[27]; self.bit28 = val_list[28]; self.bit29 = val_list[29]; self.bit30 = val_list[30]; self.bit31 = val_list[31]

    def updtBin(self, context):
        try:
            if int(self.mask_value,10) == int(self.bin_mask,base=2) or len(list(self.bin_mask)) > self.bitCount:
                return
            self.mask_value = str(int(self.bin_mask,base=2))
        except Exception as e:
            pass
            # self.report({'WARNING'}, str(e))

    def updtHex(self, context):
        try:
            if int(self.mask_value,10) == int(self.hex_mask,base=16) or len(list(self.hex_mask)) >  self.bitCount/4:
                return
            self.mask_value = str(int(self.hex_mask,base=16))
        except Exception as e:
            pass
            # self.report({'WARNING'}, str(e))

    def updtDec(self, context):
        try:
            if int(self.mask_value,10) == int(self.dec_mask, base=10) or int(self.dec_mask, base=10) > int(2**self.bitCount)-1:
                return
            self.mask_value = str(int(self.dec_mask, base=10))
        except Exception as e:
            print(e)
            pass
            # self.report({'WARNING'}, str(e))

    def updtBit(self,context):
        bitList = [self.bit0,self.bit1,self.bit2,self.bit3,self.bit4,self.bit5,self.bit6,self.bit7,self.bit8,self.bit9,self.bit10,self.bit11,self.bit12,self.bit13,self.bit14,self.bit15,
                self.bit16,self.bit17,self.bit18,self.bit19,self.bit20,self.bit21,self.bit22,self.bit23,self.bit24,self.bit25,self.bit26,self.bit27,self.bit28,self.bit29,self.bit30,self.bit31]
        bitList = list(map(int, bitList))
        bitList.reverse()
        strList = list(map(str,bitList))
        str_bit = ''.join(strList)
        # print(str_bit)
        if int(self.mask_value,10) == int(str_bit,base=2):
            return
        self.mask_value = str(int(str_bit,base=2))


    bitCount : bpy.props.IntProperty(default=32)
    state      : bpy.props.IntProperty()
    mask_value: bpy.props.StringProperty(name="Value",update = updtVal)
    hex_mask: bpy.props.StringProperty(name="Bit Mask (Hex)",update=updtHex)
    dec_mask: bpy.props.StringProperty(name="Bit Mask (Dec)",update=updtDec)
    bin_mask: bpy.props.StringProperty(name="Bit Mask (Bin)",update=updtBin)

    bit0: bpy.props.BoolProperty(name="0",update=updtBit); bit1: bpy.props.BoolProperty(name="1",update=updtBit);bit2: bpy.props.BoolProperty(name="2",update=updtBit);bit3: bpy.props.BoolProperty(name="3",update=updtBit)
    bit4: bpy.props.BoolProperty(name="4",update=updtBit);bit5: bpy.props.BoolProperty(name="5",update=updtBit);bit6: bpy.props.BoolProperty(name="6",update=updtBit);bit7: bpy.props.BoolProperty(name="7",update=updtBit)
    bit8: bpy.props.BoolProperty(name="8",update=updtBit);bit9: bpy.props.BoolProperty(name="9",update=updtBit);bit10: bpy.props.BoolProperty(name="10",update=updtBit);bit11: bpy.props.BoolProperty(name="11",update=updtBit)
    bit12: bpy.props.BoolProperty(name="12",update=updtBit);bit13: bpy.props.BoolProperty(name="13",update=updtBit);bit14: bpy.props.BoolProperty(name="14",update=updtBit);bit15: bpy.props.BoolProperty(name="15",update=updtBit)
    bit16: bpy.props.BoolProperty(name="16",update=updtBit);bit17: bpy.props.BoolProperty(name="17",update=updtBit);bit18: bpy.props.BoolProperty(name="18",update=updtBit);bit19: bpy.props.BoolProperty(name="19",update=updtBit)
    bit20: bpy.props.BoolProperty(name="20",update=updtBit);bit21: bpy.props.BoolProperty(name="21",update=updtBit);bit22: bpy.props.BoolProperty(name="22",update=updtBit);bit23: bpy.props.BoolProperty(name="23",update=updtBit)
    bit24: bpy.props.BoolProperty(name="24",update=updtBit);bit25: bpy.props.BoolProperty(name="25",update=updtBit);bit26: bpy.props.BoolProperty(name="26",update=updtBit);bit27: bpy.props.BoolProperty(name="27",update=updtBit)
    bit28: bpy.props.BoolProperty(name="28",update=updtBit);bit29: bpy.props.BoolProperty(name="29",update=updtBit);bit30: bpy.props.BoolProperty(name="30",update=updtBit);bit31: bpy.props.BoolProperty(name="31",update=updtBit)

    def execute(self, context):
        if self.state == 0:
            context.scene.I3D_UIexportSettings.i3D_weatherMask = self.mask_value
        elif self.state == 1:
            context.scene.I3D_UIexportSettings.i3D_weatherPreventMask = self.mask_value
        elif self.state == 2:
            context.scene.I3D_UIexportSettings.I3D_viewerSpacialityMask = self.mask_value
        elif self.state == 3:
            context.scene.I3D_UIexportSettings.I3D_viewerSpacialityPreventMask = self.mask_value
        elif self.state == 4:
            context.scene.I3D_UIexportSettings.i3D_collisionFilterMask = self.mask_value
        elif self.state == 5:
            context.scene.I3D_UIexportSettings.i3D_collisionFilterGroup = self.mask_value
        return {'FINISHED'}

    def invoke(self, context, event):
        #do initialzation
        wm = context.window_manager
        dlgWidth=400
        if self.state == 0:
            if not context.scene.I3D_UIexportSettings.i3D_weatherMask.isdigit():
                self.report({'WARNING'}, "{} is not an integer".format(context.scene.I3D_UIexportSettings.i3D_weatherMask))
                return {'CANCELLED'}
            self.mask_value = context.scene.I3D_UIexportSettings.i3D_weatherMask
            self.bitCount = 32
        elif self.state == 1:
            if not context.scene.I3D_UIexportSettings.i3D_weatherPreventMask.isdigit():
                self.report({'WARNING'}, "{} is not an integer".format(context.scene.I3D_UIexportSettings.i3D_weatherPreventMask))
                return {'CANCELLED'}
            self.mask_value = context.scene.I3D_UIexportSettings.i3D_weatherPreventMask
            self.bitCount = 32
        elif self.state == 2:
            if not context.scene.I3D_UIexportSettings.I3D_viewerSpacialityMask.isdigit():
                self.report({'WARNING'}, "{} is not an integer".format(context.scene.I3D_UIexportSettings.I3D_viewerSpacialityMask))
                return {'CANCELLED'}
            self.mask_value = context.scene.I3D_UIexportSettings.I3D_viewerSpacialityMask
            self.bitCount = 32
        elif self.state == 3:
            if not context.scene.I3D_UIexportSettings.I3D_viewerSpacialityPreventMask.isdigit():
                self.report({'WARNING'}, "{} is not an integer".format(context.scene.I3D_UIexportSettings.I3D_viewerSpacialityPreventMask))
                return {'CANCELLED'}
            self.mask_value = context.scene.I3D_UIexportSettings.I3D_viewerSpacialityPreventMask
            self.bitCount = 32
        elif self.state == 4:
            if not context.scene.I3D_UIexportSettings.i3D_collisionFilterMask.isdigit():
                self.report({'WARNING'}, "{} is not an integer".format(context.scene.I3D_UIexportSettings.i3D_collisionFilterMask))
                return {'CANCELLED'}
            self.mask_value = context.scene.I3D_UIexportSettings.i3D_collisionFilterMask
            self.bitCount = 32
            dlgWidth=1700
        elif self.state == 5:
            if not context.scene.I3D_UIexportSettings.i3D_collisionFilterGroup.isdigit():
                self.report({'WARNING'}, "{} is not an integer".format(context.scene.I3D_UIexportSettings.i3D_collisionFilterGroup))
                return {'CANCELLED'}
            self.mask_value = context.scene.I3D_UIexportSettings.i3D_collisionFilterGroup
            self.bitCount = 32
            dlgWidth=1700
        return wm.invoke_props_dialog(self,width=dlgWidth)

    def draw(self,context):
        textLabel = []
        if self.state == 4 or self.state == 5:
            for i in range(32):
                if (i in g_collisionBitmaskAttributes["bit_names"]):
                    textLabel.append(str(i) + " " + g_collisionBitmaskAttributes["bit_names"][i])
                else:
                    textLabel.append(str(i))
        else:
            for i in range(32):
                textLabel.append(str(i))
        layout = self.layout
        col = layout.column()
        col.prop(self, "hex_mask")
        col.prop(self, "dec_mask")
        col.prop(self, "bin_mask")
        box = layout.box()
        if self.bitCount >= 32:
            row = box.row()
            row.prop(self,'bit31', text=textLabel[31])
            row.prop(self,'bit30', text=textLabel[30])
            row.prop(self,'bit29', text=textLabel[29])
            row.prop(self,'bit28', text=textLabel[28])
            row.prop(self,'bit27', text=textLabel[27])
            row.prop(self,'bit26', text=textLabel[26])
            row.prop(self,'bit25', text=textLabel[25])
            row.prop(self,'bit24', text=textLabel[24])
        if self.bitCount >= 24:
            row = box.row()
            row.prop(self,'bit23', text=textLabel[23])
            row.prop(self,'bit22', text=textLabel[22])
            row.prop(self,'bit21', text=textLabel[21])
            row.prop(self,'bit20', text=textLabel[20])
            row.prop(self,'bit19', text=textLabel[19])
            row.prop(self,'bit18', text=textLabel[18])
            row.prop(self,'bit17', text=textLabel[17])
            row.prop(self,'bit16', text=textLabel[16])
        if self.bitCount >= 16:
            row = box.row()
            row.prop(self,'bit15', text=textLabel[15])
            row.prop(self,'bit14', text=textLabel[14])
            row.prop(self,'bit13', text=textLabel[13])
            row.prop(self,'bit12', text=textLabel[12])
            row.prop(self,'bit11', text=textLabel[11])
            row.prop(self,'bit10', text=textLabel[10])
            row.prop(self,'bit9', text=textLabel[9])
            row.prop(self,'bit8', text=textLabel[8])
        row = box.row()
        if self.bitCount >= 8:
            row.prop(self,'bit7', text=textLabel[7])
            row.prop(self,'bit6', text=textLabel[6])
            row.prop(self,'bit5', text=textLabel[5])
            row.prop(self,'bit4', text=textLabel[4])
        if self.bitCount >= 4:
            row.prop(self,'bit3', text=textLabel[3])
            row.prop(self,'bit2', text=textLabel[2])
            row.prop(self,'bit1', text=textLabel[1])
            row.prop(self,'bit0', text=textLabel[0])


class I3D_OT_modal_active_object(bpy.types.Operator):
    """Tooltip"""
    bl_idname = "i3d.active_object"
    bl_label = "Active Object"
    bl_description = "Active Object."

    # @classmethod
    # def poll(cls, context):
    #     return context.area.type == 'OUTLINER'

    def modal(self, context, event):
        if event.type != "TIMER":
            return {'PASS_THROUGH'}

        global g_disableSelectedMaterialEnumUpdateCallback

        currentObjName = context.scene.I3D_UIexportSettings.UI_ActiveObjectName
        global TYPE_BOOL
        global TYPE_INT
        global TYPE_FLOAT
        global TYPE_STRING
        global TYPE_STRING_UINT
        global TYPE_ENUM

        activeObject = context.active_object if isinstance(getattr(context, "active_object", None), bpy.types.Object) else None
        if activeObject is None:
            objects = selectionUtil.getSelectedObjects(context)
            for obj in objects:
                if isinstance(obj, bpy.types.Object):
                    activeObject = obj
                    break

        if context.scene.I3D_UIexportSettings.UI_autoAssign:
            if activeObject is not None:
                if currentObjName != activeObject.name:
                    dcc.I3DLoadObjectAttributes()
                else:
                    for k,v in dcc.SETTINGS_ATTRIBUTES.items():
                        if (k == "i3D_predefinedCollision" or k == 'i3D_selectedPredefined'):
                            continue
                        if k in context.scene.I3D_UIexportSettings:
                            valNode = dcc.I3DGetAttributeValue(currentObjName, k)
                            valProp = None
                            if   v['type'] == TYPE_BOOL:
                                valProp = dcc.UIGetAttrBool(k)
                            elif v['type'] == TYPE_INT:
                                valProp = dcc.UIGetAttrInt(k)
                            elif v['type'] == TYPE_FLOAT:
                                valProp = dcc.UIGetAttrFloat(k)
                                valProp = round(valProp, 6)
                            elif v['type'] == TYPE_STRING:
                                valProp = dcc.UIGetAttrString(k)
                            elif v['type'] == TYPE_STRING_UINT:
                                valProp = dcc.UIGetAttrString(k)
                            elif v['type'] == TYPE_ENUM:
                                valProp = dcc.UIGetAttrEnum(k)

                            if valNode != valProp:
                                dcc.I3DSaveObjectAttributes()

        # Update selected material
        # IMPORTANT: follow Blender's *active material slot* (NOT slot 0).
        # This keeps the Shader Setup dropdown in sync when the user clicks a different
        # material in Blender's Material Properties panel.
        activeMat = None
        if activeObject is not None:
            try:
                activeMat = getattr(activeObject, "active_material", None)
            except Exception:
                activeMat = None

            # Fallback: resolve from active_material_index.
            if activeMat is None:
                try:
                    slots = getattr(activeObject, "material_slots", None)
                    if slots and len(slots) > 0:
                        idx = int(getattr(activeObject, "active_material_index", 0))
                        if idx < 0:
                            idx = 0
                        if idx >= len(slots):
                            idx = len(slots) - 1
                        activeMat = slots[idx].material
                except Exception:
                    activeMat = None

            # Final fallback: first non-empty material slot.
            if activeMat is None:
                try:
                    slots = getattr(activeObject, "material_slots", None)
                    if slots:
                        for ms in slots:
                            if ms and ms.material:
                                activeMat = ms.material
                                break
                except Exception:
                    activeMat = None

        new_mat = activeMat.name if activeMat is not None else "None"

        if context.scene.I3D_UIexportSettings.i3D_selectedMaterialEnum != new_mat:
            g_disableSelectedMaterialEnumUpdateCallback = True
            try:
                context.scene.I3D_UIexportSettings.i3D_selectedMaterialEnum = new_mat
            except Exception:
                # If the enum list doesn't contain this material, fall back to None
                context.scene.I3D_UIexportSettings.i3D_selectedMaterialEnum = "None"
            g_disableSelectedMaterialEnumUpdateCallback = False

        if activeObject is not None:
            context.scene.I3D_UIexportSettings.UI_ActiveObjectName = activeObject.name

        return {'PASS_THROUGH'}
    def execute(self, context):
        wm = context.window_manager
        if wm is None:
            return {'CANCELLED'}
        # Run this modal on a timer only to avoid UI lag during scroll/mouse move
        self._timer = wm.event_timer_add(0.25, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        wm = getattr(context, 'window_manager', None)
        t = getattr(self, '_timer', None)
        if wm is not None and t is not None:
            try:
                wm.event_timer_remove(t)
            except Exception:
                pass
        self._timer = None
        
class I3D_OT_modal_predef_check(bpy.types.Operator):
    """Tooltip"""
    bl_idname = "i3d.predef_check"
    bl_label = "Predefined has change check"
    bl_description = "Predefined has change check."

    def modal(self, context, event):

        if event.type != "TIMER":
            return {'PASS_THROUGH'}

        if True:
            hasNoChange = True
            predefineName =  context.scene.I3D_UIexportSettings.i3D_selectedPredefined
            physics = dcc.UIgetPredefinePhysicItems(self, context)
            predefinedTagList = [tup[0] for tup in physics if tup[1] == predefineName]
            if len(predefinedTagList) > 0:
                predefinedTag = predefinedTagList[0]
                if predefinedTag in [tup[0] for tup in physics]:
                    for key, value in dcc.I3DgetPredefinePhysicAttr(predefinedTag).items():
                        if (key == "i3D_predefinedCollision"):
                            continue
                        # print("k: {}, v: {}, curr: {}, same: {}".format(key,value,context.scene.I3D_UIexportSettings[key],value == context.scene.I3D_UIexportSettings[key]))
                        hasNoChange = hasNoChange and (value == getattr(context.scene.I3D_UIexportSettings, key))
            nonPhysics = dcc.UIgetPredefineNonPhysicItems(self, context)
            predefinedTagList = [tup[0] for tup in nonPhysics if tup[1] == predefineName]
            if len(predefinedTagList) > 0:
                predefinedTag = predefinedTagList[0]
                if predefinedTag in [tup[0] for tup in nonPhysics]:
                    for key, value in dcc.I3DgetPredefineNonPhysicAttr(predefinedTag).items():
                        if key in context.scene.I3D_UIexportSettings.keys():
                            if (key == "i3D_predefinedCollision"):
                                continue
                            #print("k: {}, v: {}, curr: {}, same: {}".format(key,value,context.scene.I3D_UIexportSettings[key],value == context.scene.I3D_UIexportSettings[key]))
                            hasNoChange = hasNoChange and (value == getattr(context.scene.I3D_UIexportSettings, key))
            # print("hasChanged? {}".format(not hasNoChange))
            context.scene.I3D_UIexportSettings.i3D_predefHasChanged = not hasNoChange

        return {'PASS_THROUGH'}
    def execute(self, context):
        wm = context.window_manager
        if wm is None:
            return {'CANCELLED'}
        # Timer-driven predef check to avoid processing on every UI event
        self._timer = wm.event_timer_add(0.50, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        wm = getattr(context, 'window_manager', None)
        t = getattr(self, '_timer', None)
        if wm is not None and t is not None:
            try:
                wm.event_timer_remove(t)
            except Exception:
                pass
        self._timer = None

class I3D_OT_PanelUpdateXMLi3dmapping( bpy.types.Operator):
    """ Textfield Operator """

    bl_idname= "i3d.panelupdatexmli3dmapping"
    bl_label = "XML i3d mapping check"
    bl_description = "XML i3d mapping check."
    bl_options = {'REGISTER'}

    def execute(self,context):
        """ purely to have reasonable user feedback for xml i3d mappings """

        currentObjName = bpy.data.scenes[context.scene.name].I3D_UIexportSettings.UI_ActiveObjectName
        currentObject = bpy.data.objects[currentObjName]
        currentIDDict = {currentObject["I3D_XMLconfigID"] : currentObject.name}
        # print(self.state)
        for (objName,obj) in bpy.data.objects.items():
            if obj == currentObject:
                continue
            if 'I3D_XMLconfigID' in obj.keys() and 'I3D_XMLconfigBool' in obj.keys():
                if not obj['I3D_XMLconfigBool']:
                    continue
                if obj["I3D_XMLconfigID"] in currentIDDict:
                    # obj is a duplicate name of currentObject's i3d id
                    # currentIDDict[obj["I3D_XMLconfigID"]] = objName
                    self.report({'WARNING'},  currentObject.name + " has a Duplicate i3dMapping ID \"" +context.scene.I3D_UIexportSettings.i3D_XMLConfigIdentification + "\" with Object: "+ objName)
        return {'FINISHED'}

class I3D_OT_PanelExport_ButtonAttr( bpy.types.Operator ):
    """ Multi purpose GUI Button element for Node manipulation"""

    bl_idname  = "i3d.panelexport_buttonattr"
    bl_label   = "Attributes"
    bl_description = "Attributes: exports using the current settings."
    state      : bpy.props.IntProperty()

    def execute( self, context ):
        if   1 == self.state:
            dcc.I3DLoadObjectAttributes()
        elif 2 == self.state:
            dcc.I3DSaveObjectAttributes()
        elif 3 == self.state:
            dcc.I3DRemoveObjectAttributes()
        return {'FINISHED'}

class I3D_OT_PanelExport_ButtonExport( bpy.types.Operator ):
    """ Multi purpose GUI Button element for Export options"""

    bl_idname  = "i3d.panelexport_buttonexport"
    bl_label   = "Export"
    bl_description = "Exports I3D files or updates XML depending on the selected action."
    state      : bpy.props.IntProperty()
    @classmethod
    def description(cls, context, properties):
        st = int(getattr(properties, "state", 0) or 0)
        if st == 1:
            return "Export All: exports all export-enabled objects using the current export settings."
        if st == 2:
            return "Export Selected: exports only the currently selected objects using the current export settings."
        if st == 3:
            return "Update XML: updates XML mapping IDs/config data without exporting geometry."
        return cls.bl_description


    def execute( self, context ):
        # bpy.ops.wm.console_toggle()     #DEBUG command

        frame = bpy.context.scene.frame_current
        try:
            current_mode = bpy.context.object.mode
            bpy.ops.object.mode_set ( mode = 'OBJECT' ) #export in object mode
        except:
            current_mode = 'OBJECT'

        bpy.context.scene.frame_set(0)      #export bind pose
        if   1 == self.state:
            i3d_export.I3DExportAll()
        elif 2 == self.state:
            i3d_export.I3DExportSelected()
        elif 3 == self.state:
            i3d_export.I3DUpdateXML()
        elif 4 == self.state:
            i3d_export.I3DShowChangelog()
            return {'FINISHED'}
        bpy.context.scene.frame_set(frame)
        try:
            bpy.ops.object.mode_set ( mode = current_mode )
        except:
            pass
         #Info Log output
        for header in logUtil.ActionLog.header:
            self.report(header[0],header[1])
        for message in logUtil.ActionLog.message:
            self.report(message[0],message[1])
        logUtil.ActionLog.reset()

        currentIDDict = {}
        for (objName,obj) in bpy.data.objects.items():
            if 'I3D_XMLconfigID' in obj.keys() and 'I3D_XMLconfigBool' in obj.keys():
                if not obj['I3D_XMLconfigBool']:
                    continue
                if obj["I3D_XMLconfigID"] in currentIDDict :
                    self.report({'WARNING'}, "Duplicate i3dMappings: Object: "+ objName + ", i3dmapping: " + obj["I3D_XMLconfigID"])
                    self.report({'WARNING'}, "Duplicate i3dMappings: Object: "+ currentIDDict[obj["I3D_XMLconfigID"]] + ", i3dmapping: " + obj["I3D_XMLconfigID"])
                else:
                    currentIDDict[obj["I3D_XMLconfigID"]] = objName

        return {'FINISHED'}

class I3D_OT_PanelTools_ButtonChangelog( bpy.types.Operator ):
    """Show a summary of recent changes to the GIANTS exporter"""

    bl_idname  = "i3d.paneltools_buttonchangelog"
    bl_label   = "Show Changelog"
    bl_description = "Show Changelog."

    def execute( self, context ):
        i3d_export.I3DShowChangelog()
        return {'FINISHED'}

class I3D_OT_PanelRemoveXMLPath_ButtonRemove( bpy.types.Operator):
    """ GUI element Button to remove XML File path """

    bl_idname= "i3d.panelremovexmlpath_buttonremove"
    bl_label = "XMLPath"
    bl_description = "XMLPath: clears/removes the current selection."
    state : bpy.props.StringProperty()

    def execute(self,context):
        context.scene.I3D_UIexportSettings.i3D_updateXMLFilePath = context.scene.I3D_UIexportSettings.i3D_updateXMLFilePath.replace(";{};;".format(self.state), "")
        return {'FINISHED'}

class I3D_OT_PanelAddShader_ButtonLoad( bpy.types.Operator):
    """ Load the shader settings from the select object"""

    bl_idname= "i3d.paneladdshader_buttonload"
    bl_label = "Load"
    bl_description = "Load."

    def execute(self,context):
        """ Creates and registers dynamic classes for dynamic GUI elements """

        global g_dynamicGUIClsDict, g_disableShaderVariationEnumUpdateCallback

        # Remove any per-parameter-template pointer properties we previously registered.
        # Blender 5.0 removed dict-like access to runtime-defined bpy.props properties, so
        # clearing only IDProperties isn't enough anymore.
        for _template_id in [k for k in list(g_dynamicGUIClsDict.keys()) if k not in ("parameters", "textures")]:
            _prop_name = "I3D_UITemplateParameters_" + _template_id
            # Best-effort: older Blender stored runtime props in IDProperties.
            try:
                if _prop_name in bpy.context.scene:
                    del bpy.context.scene[_prop_name]
            except Exception:
                pass
            # Always remove the Scene RNA property definition.
            try:
                delattr(bpy.types.Scene, _prop_name)
            except Exception:
                pass

        #delete previous values
        if bpy.context.scene.get( 'I3D_UIShaderParameters' ):
            del bpy.context.scene[ 'I3D_UIShaderParameters' ]
        try:
            del bpy.types.Scene.I3D_UIShaderParameters
        except:
            pass
        if bpy.context.scene.get( 'I3D_UIShaderTextures' ):
            del bpy.context.scene[ 'I3D_UIShaderTextures' ]
        try:
            del bpy.types.Scene.I3D_UIShaderTextures
        except:
            pass
        #delete previous gui elements
        for dynamicClass in g_dynamicGUIClsDict.values():
            bpy.utils.unregister_class(dynamicClass)

        g_dynamicGUIClsDict = {}

        # Get selected material from the material selection dropdown
        materialObjName = bpy.context.scene.I3D_UIexportSettings.i3D_selectedMaterialEnum
        materialObj = None
        if materialObjName != "None":
            materialObj = bpy.data.materials.get(materialObjName)

        # Fallback: if the dropdown isn't synced yet, use the active object material
        if materialObj is None:
            try:
                activeObject = context.active_object
                if activeObject is not None and isinstance(activeObject, bpy.types.Object):
                    materialObj = activeObject.active_material

                # If the active mesh has no material assigned, create one so the shader UI can load safely.
                if materialObj is None and activeObject is not None and getattr(activeObject, 'type', None) == 'MESH':
                    try:
                        mat_name = "I3D_Reworked_Material"
                        mat = bpy.data.materials.get(mat_name)
                        if mat is None:
                            mat = bpy.data.materials.new(name=mat_name)
                            mat.use_nodes = True
                        # Ensure the mesh has at least one material slot
                        if len(activeObject.data.materials) == 0:
                            activeObject.data.materials.append(mat)
                        else:
                            activeObject.data.materials[0] = mat
                        activeObject.active_material = mat
                        materialObj = mat
                        try:
                            self.report({'INFO'}, "Active object had no material; created and assigned 'I3D_Reworked_Material'.")
                        except Exception:
                            pass
                    except Exception:
                        pass
            except Exception:
                pass

        # Normalize legacy customShader on the material (old .blend files)
        if materialObj is not None:
            try:
                if "customShader" in materialObj:
                    old_val = materialObj["customShader"]
                    new_val = i3d_normalize_customshader_value(old_val)
                    if new_val and new_val != old_val:
                        materialObj["customShader"] = new_val
            except Exception:
                pass

        shaderData = getShaderDataFromMaterialObj(self, materialObj)

        # Decide which shader xml to load into the UI:
        #  - Prefer the material's customShader (if present and available)
        #  - Otherwise keep the current dropdown selection
        #  - Otherwise pick the first real shader file from the directory list
        shaderCandidates = [t[0] for t in I3D_PT_PanelExport.getShadersFromDirectory(self,context)]
        currentShader = context.scene.I3D_UIexportSettings.i3D_shaderEnum
        desiredShader = shaderData.get("shader") if shaderData else None

        selectedShader = None
        if desiredShader and desiredShader in shaderCandidates:
            selectedShader = desiredShader
        elif currentShader and currentShader in shaderCandidates and currentShader != "None":
            selectedShader = currentShader
        else:
            for s in shaderCandidates:
                if s and s != "None":
                    selectedShader = s
                    break

        if not selectedShader or selectedShader == "None":
            self.report({'WARNING'}, "No shader xml found to load (check Game Path and Shader Folder)")
            return {'CANCELLED'}

        context.scene.I3D_UIexportSettings.i3D_shaderEnum = selectedShader

        try:
            fileShaderData = extractXMLShaderData()
        except Exception as e:
            self.report({'WARNING'}, "Unable to load shader XML: {}".format(e))
            return {'CANCELLED'}

        if fileShaderData:
            variationGroupsStr = None
            variationGroups = ["base"]
            shaderVariation = None
            try:
                shaderVariation = shaderData["variation"]
            except:
                shaderVariation = "None"
            if shaderVariation in fileShaderData["variations_groups"]:
                variationGroupsStr = fileShaderData["variations_groups"][shaderVariation]
            if variationGroupsStr is not None:
                variationGroups = variationGroupsStr.split()
            updateDynamicUIClassesForShaderParameters(fileShaderData, variationGroups, shaderData, materialObj)

            if materialObj is not None:
                if "shadingRate" in materialObj:
                    context.scene.I3D_UIexportSettings.i3D_shadingRate = materialObj["shadingRate"]
                else:
                    context.scene.I3D_UIexportSettings.i3D_shadingRate = "1x1"

                if "materialSlotName" in materialObj:
                    context.scene.I3D_UIexportSettings.i3D_materialSlotName = materialObj["materialSlotName"]
                else:
                    context.scene.I3D_UIexportSettings.i3D_materialSlotName = ""

                if materialObj.blend_method == 'BLEND':
                    context.scene.I3D_UIexportSettings.i3D_alphaBlending = True
                else:
                    context.scene.I3D_UIexportSettings.i3D_alphaBlending = False

                if "refractionMap" in materialObj:
                    context.scene.I3D_UIexportSettings.i3D_refractionMap = True

                    if "refractionMapLightAbsorbance" in materialObj:
                        context.scene.I3D_UIexportSettings.i3D_refractionMapLightAbsorbance = materialObj["refractionMapLightAbsorbance"]
                    else:
                        context.scene.I3D_UIexportSettings.i3D_refractionMapLightAbsorbance = dcc.SETTINGS_ATTRIBUTES["i3D_refractionMapLightAbsorbance"]["defaultValue"]

                    if "refractionMapBumpScale" in materialObj:
                        context.scene.I3D_UIexportSettings.i3D_refractionMapBumpScale = materialObj["refractionMapBumpScale"]
                    else:
                        context.scene.I3D_UIexportSettings.i3D_refractionMapBumpScale = dcc.SETTINGS_ATTRIBUTES["i3D_refractionMapBumpScale"]["defaultValue"]

                    if "refractionMapWithSSRData" in materialObj:
                        context.scene.I3D_UIexportSettings.i3D_refractionMapWithSSRData = True
                    else:
                        context.scene.I3D_UIexportSettings.i3D_refractionMapWithSSRData = False
                else:
                    context.scene.I3D_UIexportSettings.i3D_refractionMap = False
                    context.scene.I3D_UIexportSettings.i3D_refractionMapLightAbsorbance = dcc.SETTINGS_ATTRIBUTES["i3D_refractionMapLightAbsorbance"]["defaultValue"]
                    context.scene.I3D_UIexportSettings.i3D_refractionMapBumpScale = dcc.SETTINGS_ATTRIBUTES["i3D_refractionMapBumpScale"]["defaultValue"]
                    context.scene.I3D_UIexportSettings.i3D_refractionMapWithSSRData = False

            g_disableShaderVariationEnumUpdateCallback = True
            try:
                context.scene.I3D_UIshaderVariation.i3D_shaderVariationEnum = shaderVariation
            except:
                print("Variation not existing in loaded file")
            g_disableShaderVariationEnumUpdateCallback = False
        return {'FINISHED'}

class I3D_OT_PanelAddShader_ButtonConvertFs22Fs25(bpy.types.Operator):
    """ Convert the FS22 material of the scene to the new multi material system of FS25"""

    bl_idname = "i3d.paneladdshader_buttonconvertfs22fs25"
    bl_label = "Convert FS22 -> FS25"
    bl_description = "Convert FS22 -> FS25."

    def execute(self, context):

        gamePath = getGamePath()
        if gamePath == "":
            gamePath = bpy.context.scene.I3D_UIexportSettings.i3D_gameLocationDisplay
        i3d_shaderUtil.convertVehicleMaterialFS22ToFS25(gamePath)

        return {'FINISHED'}

class I3D_OT_PanelAddShader_ButtonAdd( bpy.types.Operator):
    """ Apply the custom shader values to the selected object"""

    bl_idname= "i3d.paneladdshader_buttonadd"
    bl_label = "Apply"
    bl_description = "Apply: applies the current selection to the active material."

    def execute(self,context):
        """ Creates and registers dynamic classes for dynamic GUI elements """
        # try:
        #     actObjName = context.active_object.name
        # except:
        #     try:
        #         actObjName = dccBlender.getSelectedNodes()[0]
        #     except:
        #         actObjName = bpy.data.scenes[context.scene.name].I3D_UIexportSettings.UI_PrevActiveObjectName
        # activeObject = bpy.data.objects[actObjName]
        # materialObj = activeObject.active_material
        # if materialObj == None:
        #     self.report({'WARNING'},"Cannot Add Shader")
        #     if context.active_object == None:
        #         self.report({'WARNING'},"No Object is Selected")
        #         return {'CANCELLED'}
        #     else:
        #         self.report({'WARNING'},"{} has no Material".format(context.active_object.name))
        #         return {'CANCELLED'}

        materialObjName = bpy.context.scene.I3D_UIexportSettings.i3D_selectedMaterialEnum
        materialObj = None
        if materialObjName != "None":
            materialObj = bpy.data.materials[materialObjName]

        if materialObj == None:
            self.report({'WARNING'},"Cannot Add Shader, no material is selected")
            return {'CANCELLED'}

        for delKey in [k for k in materialObj.keys() if k.startswith("custom") or k.startswith("templatedParameterTemplateMenu_")]:
            del materialObj[delKey]
        if materialObj:
            shaderFolderRaw = context.scene.I3D_UIexportSettings.i3D_shaderFolderLocation
            gamePath = getGamePath()
            if gamePath is None or gamePath == "":
                gamePath = bpy.context.scene.I3D_UIexportSettings.i3D_gameLocationDisplay
            if shaderFolderRaw and shaderFolderRaw[0] == "$":
                dirPath = resolveGiantsPath(shaderFolderRaw, gamePath)
            else:
                dirPath = resolveGiantsPath(bpy.path.abspath(shaderFolderRaw), gamePath)
            fileName = context.scene.I3D_UIexportSettings.i3D_shaderEnum
            if fileName == "None":
                self.report({'WARNING'},'No config xml file set!')
                return {'FINISHED'}
            xmlFilePathAbs = dirPath + os.sep + fileName
            if not os.path.isfile(xmlFilePathAbs):
                self.report({'WARNING'},'Could not find xml file! (%s)' % xmlFilePathAbs)
                return {'FINISHED'}
            if not xmlFilePathAbs.endswith(".xml"):
                self.report({'WARNING'},"Selected File is not xml format: {}".format(xmlFilePathAbs.split("\\")[-1]))
                return {'FINISHED'}

            if shaderFolderRaw and shaderFolderRaw[0] == "$":
                portableFolder = shaderFolderRaw.rstrip("/\\")
                xmlFilePath = portableFolder + "/" + fileName
            else:
                xmlFilePath = pathUtil.resolvePath(xmlFilePathAbs,targetDirectory = bpy.path.abspath("//"))
            materialObj["customShader"] = xmlFilePath
            if "parameters" in g_dynamicGUIClsDict:
                for k,i in g_dynamicGUIClsDict["parameters"].__annotations__.items():
                    try:
                        i = i.keywords
                    except:
                        i = i[1]
                    if k.endswith("Bool"):
                        if (hasattr(context.scene.I3D_UIShaderParameters, k) and getattr(context.scene.I3D_UIShaderParameters, k)) or (i['default'] and not hasattr(context.scene.I3D_UIShaderParameters, k)):      #default test, since default values are not accesable from the API
                            name = "customParameter_"+k[:-4]        #add prefix customParameter_ and remove "Bool" postfix
                            postfix = ['_0','_1','_2','_3']
                            value = ''
                            for postf in postfix:
                                postf_key = k[:-4]+postf
                                if hasattr(context.scene.I3D_UIShaderParameters, postf_key):
                                    value = value + str(getattr(bpy.context.scene.I3D_UIShaderParameters, postf_key)) + " "
                                else:
                                    try:
                                        value = value + str(g_dynamicGUIClsDict["parameters"].__annotations__[postf_key].keywords['default']) + " "
                                    except:
                                        value = value + str(g_dynamicGUIClsDict["parameters"].__annotations__[postf_key][1]['default']) + " "
                            value = value.strip()
                            #legacy check
                            if hasattr(context.scene.I3D_UIShaderParameters, k[:-4]) and value == '':
                                value = getattr(bpy.context.scene.I3D_UIShaderParameters, k[:-4])
                            elif value == '':
                                try:
                                    value = g_dynamicGUIClsDict["parameters"].__annotations__[k[:-4]].keywords['default']
                                except:
                                    value = g_dynamicGUIClsDict["parameters"].__annotations__[k[:-4]][1]['default']
                            materialObj[name] = value

            if "textures" in g_dynamicGUIClsDict:
                for k,i in g_dynamicGUIClsDict["textures"].__annotations__.items():
                    try:
                        i = i.keywords
                    except:
                        i = i[1]
                    if k.endswith("Bool"):
                        if (hasattr(context.scene.I3D_UIShaderTextures, k) and getattr(context.scene.I3D_UIShaderTextures, k)) or (i['default'] and not hasattr(context.scene.I3D_UIShaderTextures, k)):
                            name = "customTexture_"+k[:-4]        #add prefix customParameter_ and remove "Bool" postfix
                            if hasattr(context.scene.I3D_UIShaderTextures, k[:-4]):
                                value = getattr(bpy.context.scene.I3D_UIShaderTextures, k[:-4])
                            else:
                                try:
                                    value = g_dynamicGUIClsDict["textures"].__annotations__[k[:-4]].keywords['default']
                                except:
                                    value = g_dynamicGUIClsDict["textures"].__annotations__[k[:-4]][1]['default']
                            materialObj[name] = value

            for dynamicGUIClsName, dynamicGUICls in g_dynamicGUIClsDict.items():
                # Skip textures and parameters entries, otherwise we assume that its a template parameter
                if dynamicGUIClsName == "textures" or dynamicGUIClsName == "parameters":
                    continue

                clssName = 'I3D_UITemplateParameters_'+dynamicGUIClsName
                try:
                    dataClass = getattr(context.scene, clssName)
                except Exception as exception:
                    # TODO(jdellsperger): Warning / Error
                    continue
                else:
                    # Differentiate types of parameters by their ending string:
                    # Bool: Checkbox whether the parameter is enabled or not
                    # _0 to _3: Regular parameter (float4)
                    # _Template: Template parameter (string/enum)
                    # Starts with templatedParameterTemplateMenu_: Template for specific parameter (enum)
                    # Otherwise: Texture parameter (string)

                    for k, v in dynamicGUICls.__annotations__.items():
                        if not k.endswith("Bool"):
                            continue

                        if not getattr(dataClass, k):
                            # Custom parameter is not enabled, skip
                            # TODO(jdellsperger): Remove stored attribute on material if any
                            continue

                        paramName = k[:-4] # Remove trailing "Bool"
                        prefix = ""
                        value = ""
                        if hasattr(dataClass, paramName + "_0") and \
                           hasattr(dataClass, paramName + "_1") and \
                           hasattr(dataClass, paramName + "_2") and \
                           hasattr(dataClass, paramName + "_3"):
                            # Is a regular parameter
                            prefix = "customParameter_"
                            value = \
                                str(getattr(dataClass, paramName + "_0")) + " " + \
                                str(getattr(dataClass, paramName + "_1")) + " " + \
                                str(getattr(dataClass, paramName + "_2")) + " " + \
                                str(getattr(dataClass, paramName + "_3"))
                        elif hasattr(dataClass, paramName + "_Template"):
                            # Parameter template
                            prefix = "customParameterTemplate_" + dynamicGUIClsName + "_"
                            value = getattr(dataClass, paramName + "_Template")
                        elif hasattr(dataClass, paramName):
                            # Texture
                            prefix = "customTexture_"
                            value = getattr(dataClass, paramName)
                        else:
                            # Invalid parameter
                            self.report({"ERROR"}, "Invalid parameter '{}' encountered".format(paramName))
                            continue

                        # Store specific template selected for this parameter, if any.
                        parameterTemplateName = "templatedParameterTemplateMenu_" + dynamicGUIClsName + "_" + paramName
                        try:
                            selectedParameterTemplate = getattr(dataClass, parameterTemplateName)
                            if selectedParameterTemplate == "None":
                                del(materialObj[parameterTemplateName])
                            else:
                                materialObj[parameterTemplateName] = selectedParameterTemplate
                        except Exception as e:
                            # no selected parameter.
                            pass

                        materialObj[prefix + paramName] = value

            if context.scene.I3D_UIshaderVariation.i3D_shaderVariationEnum != "None":
                materialObj["customShaderVariation"] = context.scene.I3D_UIshaderVariation.i3D_shaderVariationEnum
            else:
                try:
                    del materialObj["customShaderVariation"]
                except:
                    pass

            if context.scene.I3D_UIexportSettings.i3D_shadingRate != "":
                materialObj["shadingRate"] = context.scene.I3D_UIexportSettings.i3D_shadingRate
            elif "shadingRate" in materialObj:
                del(materialObj["shadingRate"])

            if context.scene.I3D_UIexportSettings.i3D_materialSlotName != "":
                materialObj["materialSlotName"] = context.scene.I3D_UIexportSettings.i3D_materialSlotName
            elif "materialSlotName" in materialObj:
                del(materialObj["materialSlotName"])

            if context.scene.I3D_UIexportSettings.i3D_alphaBlending:
                materialObj.blend_method = 'BLEND'
            elif materialObj.blend_method == 'BLEND':
                materialObj.blend_method = 'OPAQUE'

            if context.scene.I3D_UIexportSettings.i3D_refractionMap:
                materialObj["refractionMap"] = True
            elif "refractionMap" in materialObj:
                del(materialObj["refractionMap"])

            if context.scene.I3D_UIexportSettings.i3D_refractionMapLightAbsorbance != dcc.SETTINGS_ATTRIBUTES["i3D_refractionMapLightAbsorbance"]["defaultValue"]:
                materialObj["refractionMapLightAbsorbance"] = context.scene.I3D_UIexportSettings.i3D_refractionMapLightAbsorbance
            elif "refractionMapLightAbsorbance" in materialObj:
                del(materialObj["refractionMapLightAbsorbance"])

            if context.scene.I3D_UIexportSettings.i3D_refractionMapBumpScale != dcc.SETTINGS_ATTRIBUTES["i3D_refractionMapBumpScale"]["defaultValue"]:
                materialObj["refractionMapBumpScale"] = context.scene.I3D_UIexportSettings.i3D_refractionMapBumpScale
            elif "refractionMapBumpScale" in materialObj:
                del(materialObj["refractionMapBumpScale"])

            if context.scene.I3D_UIexportSettings.i3D_refractionMapWithSSRData:
                materialObj["refractionMapWithSSRData"] = True
            elif "refractionMapWithSSRData" in materialObj:
                del(materialObj["refractionMapWithSSRData"])
        return {'FINISHED'}

class I3D_OT_PanelExport_ButtonClose( bpy.types.Operator ):
    """ GUI element Buttom to close GIANTS I3D Exporter"""

    bl_idname  = "i3d.panelexport_buttonclose"
    bl_label   = "Close"
    bl_description = "Close: exports using the current settings."

    def execute( self, context ):
        for cls in reversed(classes):
            bpy.utils.unregister_class(cls)
        return {'FINISHED'}

class I3D_OT_PanelXMLidentification_ButtonAdd( bpy.types.Operator):
    """ GUI element Button to set Node Id for XML configuration to object name """

    bl_idname= "i3d.panelxmlidentification_buttonadd"
    bl_label = "XML Id"
    bl_description = "Sets Node Id to the default value, the Node Name"
    state : bpy.props.StringProperty()

    def execute(self,context):

        actObjName = bpy.data.scenes[context.scene.name].I3D_UIexportSettings.UI_ActiveObjectName
        actObjName = dccBlender.getFormattedNodeName(actObjName)
        context.scene.I3D_UIexportSettings.i3D_XMLConfigIdentification = actObjName
        return {'FINISHED'}

class I3D_OT_PanelOpenXMLFilebrowser(bpy.types.Operator,bpy_extras.io_utils.ImportHelper):
    """ GUI element Button to open a Filebrowser with *.xml filter applied"""

    bl_idname = "i3d.openxmlfilebrowser"
    bl_label = "select XML"
    bl_description = "select XML: selects items related to the current view."
    filter_glob: bpy.props.StringProperty( default='*.xml', options={'HIDDEN'} )

    def execute(self, context):
        filename, extension = os.path.splitext(self.filepath)
        path = filename + extension
        if not os.path.isfile(path):
            self.report({'WARNING'},"{} is no valid xml file".format(path))
            return {'CANCELLED'}
        abspath = bpy.path.abspath(path) #bpy.path.relpath(path)
        if abspath not in context.scene.I3D_UIexportSettings.i3D_updateXMLFilePath:
            context.scene.I3D_UIexportSettings.i3D_updateXMLFilePath = context.scene.I3D_UIexportSettings.i3D_updateXMLFilePath +";{};;".format(abspath)
        return {'FINISHED'}

class I3D_OT_PanelOpenFolderFilebrowser(bpy.types.Operator,bpy_extras.io_utils.ImportHelper):
    """ GUI element Button to select a Folder Path """

    bl_idname = "i3d.openfolderfilebrowser"
    bl_label = "Select Folder"
    bl_description = "Search and select game location"
    state      : bpy.props.IntProperty()

    def execute(self, context):
        filename, extension = os.path.splitext(self.filepath)
        if self.state == 1: # Game location
            path = filename.rsplit("\\",1)[0] + "\\" #remove filename and extension
            abspath = bpy.path.abspath(path)
            context.scene.I3D_UIexportSettings.i3D_gameLocationDisplay = abspath

        elif self.state == 2: # Shaders
            path = filename.rsplit("\\",1)[0] + "\\"    #remove filename and extension
            context.scene.I3D_UIexportSettings.i3D_shaderFolderLocation = path
            updateShaderFolderLocation(context)
            if not context.scene.I3D_UIexportSettings.i3D_shaderEnum in [t[0] for t in I3D_PT_PanelExport.getShadersFromDirectory(self,context)]:
                context.scene.I3D_UIexportSettings.i3D_shaderEnum = [t[0] for t in I3D_PT_PanelExport.getShadersFromDirectory(self,context)][0]
            shaderEnumUpdate(self,context)

        return {'FINISHED'}

class I3D_OT_PanelRefreshGamePath(bpy.types.Operator):
    """ GUI element Button to auto search and update the game installation path only available on Windows """

    bl_idname = "i3d.panelrefreshgamepath"
    bl_label = "Search for Game Installation"
    bl_description = "Search automatically for a game installation"

    def execute(self, context):
        # context.scene.I3D_UIexportSettings.i3D_gameLocation = ""
        context.scene.I3D_UIexportSettings.i3D_gameLocationDisplay = dirf.findFS22Path()
        return {'FINISHED'}

class I3D_OT_PanelSetGameShader(bpy.types.Operator):
    """ GUI element Button to auto search and set the shader to the game shader location only available on Windows """

    bl_idname = "i3d.panelsetgameshader"
    bl_label = "Detect Path"
    bl_description = "Search automatically for the shader folder in the Game Installation"

    def execute(self, context):
        gameInstallationPath = getGamePath()
        if gameInstallationPath == "":
            gameInstallationPath = context.scene.I3D_UIexportSettings.i3D_gameLocationDisplay

        if gameInstallationPath == "":
            if dirf.isWindows():
                gameInstallationPath = dirf.findFS22Path()
                if gameInstallationPath != "":
                    try:
                        # Persist for future sessions (supports classic and namespaced add-on keys)
                        addon_entry = bpy.context.preferences.addons.get("io_export_i3d_reworked")
                        if addon_entry is None:
                            for addon_key, addon_val in bpy.context.preferences.addons.items():
                                if addon_key.endswith(".io_export_i3d_reworked"):
                                    addon_entry = addon_val
                                    break
                        if addon_entry and getattr(addon_entry, "preferences", None):
                            addon_entry.preferences.game_install_path = gameInstallationPath
                    except Exception:
                        pass

        if gameInstallationPath == "":
            self.report({'WARNING'},"No Game Installation found")
            return {'FINISHED'}

        # Keep legacy scene setting in sync (the addon still reads from this in many places)
        context.scene.I3D_UIexportSettings.i3D_gameLocationDisplay = gameInstallationPath

        gameShaderFolder = os.path.join(gameInstallationPath, "data", "shaders")
        if not os.path.isdir(bpy.path.abspath(gameShaderFolder)):
            self.report({'WARNING'},"{} is no valid path".format(gameShaderFolder))
            return {'FINISHED'}

        # Store as portable GIANTS path so .blend files work across different install locations
        context.scene.I3D_UIexportSettings.i3D_shaderFolderLocation = "$data/shaders"
        shaderEnumUpdate(self,context)
        self.report({'INFO'},"Game Shader Path set")
        return {'FINISHED'}

class I3D_OT_PanelOpenI3DFilebrowser(bpy.types.Operator,bpy_extras.io_utils.ImportHelper):
    """ GUI element Button to open a Filebrowser with *.i3d filter applied"""

    bl_idname = "i3d.openi3dfilebrowser"
    bl_label = "Set i3d File"
    bl_description = "Set i3d File: opens the related window or resource."
    filter_glob: bpy.props.StringProperty( default='*.i3d', options={'HIDDEN'} )

    def execute(self, context):
        filename, extension = os.path.splitext(self.filepath)
        if extension != ".i3d":
            self.report({'WARNING'},"Changed File Location extension from {} to '.i3d'".format(extension))
            extension = ".i3d"
        path = filename + extension
        try:
            relpath = bpy.path.relpath(path)
        except:
            relpath = path
        context.scene.I3D_UIexportSettings.i3D_exportFileLocation = relpath
        return {'FINISHED'}

class I3D_OT_PanelOpenDDSFilebrowser(bpy.types.Operator,bpy_extras.io_utils.ImportHelper):
    """ GUI element Button to open a Filebrowser with *.dds filter applied"""

    bl_idname = "i3d.openddsfilebrowser"
    bl_label = "Set dds File"
    bl_description = "Set dds File: opens the related window or resource."
    filter_glob: bpy.props.StringProperty( default='*.dds', options={'HIDDEN'} )

    def execute(self, context):
        filename, extension = os.path.splitext(self.filepath)
        if extension != ".dds":
            self.report({'WARNING'},"Changed File Location extension from {} to '.dds'".format(extension))
            extension = ".dds"
        path = filename + extension
        try:
            relpath = bpy.path.relpath(path)
        except:
            relpath = path
        context.scene.I3D_UIexportSettings.i3D_objectDataFilePath = relpath
        return {'FINISHED'}

class I3D_OT_PanelOpenIESFilebrowser(bpy.types.Operator, bpy_extras.io_utils.ImportHelper):
    """ GUI element Button to open a Filebrowser with *.ies filter applied"""

    bl_idname = "i3d.openiesfilebrowser"
    bl_label = "Set ies File"
    bl_description = "Set ies File: opens the related window or resource."
    filter_glob: bpy.props.StringProperty( default='*.ies', options={'HIDDEN'} )

    def execute(self, context):
        filename, extension = os.path.splitext(self.filepath)
        if extension != ".ies":
            self.report({'WARNING'},"Changed File Location extension from {} to '.ies'".format(extension))
            extension = ".ies"
        path = filename + extension
        #try:
        #    relpath = bpy.path.abspath(path)
        #except:
        #    relpath = path
        #context.scene.I3D_UIexportSettings.i3D_iesProfileFile = relpath
        context.scene.I3D_UIexportSettings.i3D_iesProfileFile = path
        return {'FINISHED'}


class I3D_OT_ExportObjectDataTexture_UnsavedPrompt(bpy.types.Operator, bpy_extras.io_utils.ExportHelper):
    """When the .blend isn't saved yet, pick a safe destination for the Object Data DDS export."""

    bl_idname = "i3d.export_object_data_texture_unsaved"
    bl_label = "Save Object Data Texture"
    bl_description = "Choose where the generated *.dds (e.g. curveArray.dds) should be saved when the .blend is not saved yet."

    filename_ext = ".dds"
    filter_glob: bpy.props.StringProperty(default="*.dds", options={'HIDDEN'})
    check_existing: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    def invoke(self, context, event):
        # Default name: first exported object's filename (if available) or curveArray.dds
        default_name = "curveArray.dds"
        try:
            for obj in bpy.data.objects:
                if "i3D_objectDataFilePath" in obj and str(obj["i3D_objectDataFilePath"]).strip():
                    default_name = os.path.basename(str(obj["i3D_objectDataFilePath"]))
                    break
        except Exception:
            pass

        if not default_name.lower().endswith(".dds"):
            default_name += ".dds"

        # Start directory: previously chosen folder this session -> temp dir -> home
        start_dir = bpy.app.tempdir or os.path.expanduser("~")
        try:
            prev_dir = context.scene.get("i3d_unsaved_dds_export_dir", "")
            if prev_dir and os.path.isdir(prev_dir):
                start_dir = prev_dir
        except Exception:
            pass

        self.filepath = os.path.join(start_dir, default_name)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        export_dir = os.path.dirname(self.filepath)
        if not export_dir:
            self.report({'ERROR'}, "No export folder selected.")
            return {'CANCELLED'}

        # Store chosen folder so the exporter can resolve relative filenames safely.
        context.scene["i3d_unsaved_dds_export_dir"] = export_dir

        # If there's exactly one export object, also honor the chosen filename.
        try:
            export_objs = [
                o for o in bpy.data.objects
                if ("i3D_objectDataFilePath" in o and str(o["i3D_objectDataFilePath"]).strip())
            ]
            if len(export_objs) == 1:
                export_objs[0]["i3D_objectDataFilePath"] = os.path.basename(self.filepath)
        except Exception:
            pass

        # Export in Object Mode, then restore the previous mode.
        try:
            current_mode = bpy.context.object.mode
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            current_mode = 'OBJECT'

        i3d_export.I3DExportDDS()

        try:
            bpy.ops.object.mode_set(mode=current_mode)
        except Exception:
            pass

        return {'FINISHED'}


class I3D_OT_PanelTools_Button( bpy.types.Operator ):
    """ Multi purpose GUI Button element for Tools tab"""

    bl_idname  = "i3d.paneltools_button"
    bl_label   = ""
    bl_description = "i3d.paneltools_button."
    state      : bpy.props.IntProperty()

    def execute( self, context ):

        # bpy.ops.wm.console_toggle() #DEBUG command
        try:
            current_mode = bpy.context.object.mode
            bpy.ops.object.mode_set ( mode = 'OBJECT' ) #export in object mode
        except:
            current_mode = 'OBJECT'

        if   1 == self.state:  #export dds
            # If the user hasn't saved the .blend yet, avoid exporting to the drive root (e.g. \\curveArray.dds).
            # Prompt for a destination folder instead.
            if not dccBlender.isFileSaved():
                bpy.ops.i3d.export_object_data_texture_unsaved('INVOKE_DEFAULT')
            else:
                i3d_export.I3DExportDDS()

        try:
            bpy.ops.object.mode_set ( mode = current_mode )
        except:
            pass
        #Info Log output
        for header in logUtil.ActionLog.header:
            self.report(header[0],header[1])
        for message in logUtil.ActionLog.message:
            self.report(message[0],message[1])
        logUtil.ActionLog.reset()
        return {'FINISHED'}

class I3D_OT_PanelMaterial_OpenMaterialTemplatesWindowButton(bpy.types.Operator):
    """ GUI element Button to open the material library """

    bl_idname = "i3d.openmaterialtemplateswindow"
    bl_label = "Material Templates"
    bl_description = "Opens a preview window of reusable material templates."

    # State to track whether the material templates window is open or not.
    state      : bpy.props.IntProperty(name = "State", default = 0)

    def execute(self, context):
        #self.report({'INFO'}, 'I3D_OT_PanelMaterial_OpenMaterialTemplatesWindowButton::execute()')
        if self.state == 0:
            try:
                global g_loadedMaterialTemplates

                try:
                    materialTemplateFilename = "$data/shared/detailLibrary/materialTemplates.xml"
                    gameInstallationPath = getGamePath()
                    if gameInstallationPath == "":
                        gameInstallationPath = bpy.context.scene.I3D_UIexportSettings.i3D_gameLocationDisplay
                    if not gameInstallationPath:
                        self.report({'WARNING'},"FS25 Game Path is empty (Addon Preferences)")
                        return {'CANCELLED'}
                    templatesXmlFilename = resolveGiantsPath(materialTemplateFilename, gameInstallationPath)
                    if not os.path.exists(templatesXmlFilename):
                        self.report({'ERROR'}, f"Material Templates XML not found: {templatesXmlFilename}")
                        self.report({'ERROR'}, f"FS25 Game Path resolved to: {gameInstallationPath}")
                        return {'CANCELLED'}
                    xmlTree = xml_ET.parse(templatesXmlFilename)
                except xml_ET.ParseError as err:
                    self.report({"INFO"}, "Failed to load parameter templates from '%s': %s" % (templatesXmlFilename, err))
                    return {'CANCELLED'}
                else:
                    # TODO(jdellsperger): Make xml file actually selectable
                    context.scene.I3D_UIMaterialTemplateProperties.fileLocation = materialTemplateFilename
                    templatesFileRoot = xmlTree.getroot()
                    for template in templatesFileRoot.findall("template"):
                        iconFilename = template.get("iconFilename")
                        iconFilenamePath = resolveGiantsPath(iconFilename, gameInstallationPath)
                        name = template.get("name")
                        categoryString = template.get("category") or "Uncategorized"
                        categories = categoryString.split("/")

                        templateAttributesDict = {}
                        templateAttributes = template.attrib

                        # Delete meta attributes
                        del templateAttributes["name"]
                        del templateAttributes["category"]
                        del templateAttributes["iconFilename"]

                        for templateAttribute in templateAttributes:
                            templateAttributesDict[templateAttribute] = template.get(templateAttribute)

                        categoryDict = g_loadedMaterialTemplates
                        categoryString = ""
                        for category in categories:
                            categoryString = categoryString + category
                            if not category in categoryDict:
                                categoryDict[category] = {'expanded': False, "thumbnails": None}
                                categoryDict[category]["thumbnails"] = bpy.utils.previews.new()
                            categoryDict = categoryDict[category]
                            categoryString = categoryString + "_"

                        g_loadedMaterialTemplates['templates'][name] = templateAttributesDict
                        if name not in categoryDict["thumbnails"]:
                            try:
                                if iconFilenamePath and os.path.exists(iconFilenamePath):
                                    categoryDict["thumbnails"].load(name, iconFilenamePath, "IMAGE")
                            except Exception:
                                pass

                bpy.utils.register_class(I3D_PT_MaterialTemplates)
                self.state = 1
            except Exception as e:
                import traceback
                print(traceback.format_exc())
                self.report({'ERROR'}, f"I3D_OT_PanelMaterial_OpenMaterialTemplatesWindowButton::execute exception: {e}")
                try:
                    self.report({'ERROR'}, f"Templates XML attempted: {templatesXmlFilename}")
                except Exception:
                    pass
                return {'CANCELLED'}
        elif self.state == 1:
            #TODO(jdellsperger): Should we unload everything (including thumbnails) in case of close?

            try:
                bpy.utils.unregister_class(I3D_PT_MaterialTemplates)
                self.state = 0
            except:
                self.report({'INFO'}, 'I3D_OT_PanelMaterial_OpenMaterialTemplatesWindowButton::execute::cancelled2')
                return {'CANCELLED'}
        return {'FINISHED'}

class I3D_OT_PanelMaterial_ApplyMaterialTemplateToSelection(bpy.types.Operator):
    """Event triggered when a material template preview was clicked."""

    bl_idname = "i3d.apply_material_template_to_selection"
    bl_label = "Apply to Selection"
    bl_description = "Creates a new material from the template parameters and assigns it to the selected object."

    templateName : bpy.props.StringProperty()
    description_name: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, properties):
        name = properties.description_name
        return f"Apply the material template '{name}' to the selected object."

    def execute(self, context):
        # TODO(jdellsperger): Assign material to entire object or to faces, depending on mode
        mat = bpy.data.materials.new(self.templateName + "_mat")
        mat["customShader"] = "$data/shaders/vehicleShader.xml"
        mat["customParameterTemplate_brandColor_material"] = self.templateName

        # Assign material to active object
        obj = context.object
        obj.data.materials.append(mat)

        # self.report({'INFO'}, "template clicked: {}".format(self.templateName))
        return {'FINISHED'}

class I3D_OT_PanelMaterial_UseMaterialNameAsSlotNameButton(bpy.types.Operator):
    """ GUI element Button to copy the selected material name to the slot name text input """

    bl_idname = "i3d.usematerialnameasslotname"
    bl_label = "Use Material Name"
    bl_description = "Copies the name of the currently selected material to the slot name text input."

    def execute(self, context):
        try:
            context.scene.I3D_UIexportSettings.i3D_materialSlotName = context.object.active_material.name
        except:
            return {'CANCELLED'}
        return {'FINISHED'}

#-------------------------------------------------------------------------------
#   Init Scene PropertyGroups
#-------------------------------------------------------------------------------


def _i3d_enum_all_materials(self, context):
    items = [("NONE", "None", "")]
    try:
        for m in bpy.data.materials:
            items.append((m.name, m.name, ""))
    except Exception:
        pass
    return items


class I3D_UIexportSettings( bpy.types.PropertyGroup ):
    """ Definition of all static GUI element properties """

    i3D_XMLConfigExport : bpy.props.BoolProperty (name = "", description = "Export to config. XML if checked", default = False, update=I3D_PT_PanelExport.updateXMLconfigBool)
    i3D_XMLConfigIdentification : bpy.props.StringProperty (name = "Node Id", description = "XML config. i3dMapping identification", update=I3D_PT_PanelExport.updateXMLconfigId)
    UI_settingsMode : bpy.props.EnumProperty(
                items = [ ('exp' ,  'Export'   ,  ''),
                          ('attr',  'Attributes', ''),
                          ('tools',  'Tools', ''),
                          ('shader',  'Material', '')],
                name = "Settings Mode"
                )
    UI_exportOptions        : bpy.props.BoolProperty   ( name = "Export Options",        default = True )
    UI_shapeExportSubparts  : bpy.props.BoolProperty   ( name = "Shape Export Subparts", default = True )
    UI_miscellaneous        : bpy.props.BoolProperty   ( name = "Miscellaneous",         default = True )
    UI_gameLocation         : bpy.props.BoolProperty   ( name = "Game Location",         default = False )
    UI_xmlConfig            : bpy.props.BoolProperty   ( name = "XML config File",       default = True )
    UI_outputFile           : bpy.props.BoolProperty   ( name = "Output File",           default = True )
    UI_currentNode          : bpy.props.BoolProperty   ( name = "Current Node",          default = True )
    UI_predefined           : bpy.props.BoolProperty   ( name = "Predefined",            default = False )
    UI_rigidBody            : bpy.props.BoolProperty   ( name = "Rigid Body",            default = False )
    UI_joint                : bpy.props.BoolProperty   ( name = "Joint",                 default = False )
    UI_rendering            : bpy.props.BoolProperty   ( name = "Rendering",             default = False )
    UI_environment          : bpy.props.BoolProperty   ( name = "Environment",           default = False )
    UI_objectDataTexture    : bpy.props.BoolProperty   ( name = "Object Data Texture",   default = False )
    UI_showLightAttributes  : bpy.props.BoolProperty   ( name = "Show Light Attributes", default = False )
    UI_lightAttributes      : bpy.props.BoolProperty   ( name = "Light Attributes",      default = False )
    UI_ddsExportOptions     : bpy.props.BoolProperty   ( name = "DDS Export Options",    default = False )
    UI_shaderFolder         : bpy.props.BoolProperty   ( name = "Shaders Folder",        default = False, options={'SKIP_SAVE'} )
    UI_shaderSetup          : bpy.props.BoolProperty   ( name = "Shader Setup",         default = False, options={'SKIP_SAVE'} )
    UI_colorLibrary         : bpy.props.BoolProperty   ( name = "Color Library",         default = False, options={'SKIP_SAVE'} )
    UI_customTools          : bpy.props.BoolProperty   ( name = "Custom Tools",          default = False, options={'SKIP_SAVE'} )
    UI_deltaVertexTool      : bpy.props.BoolProperty   ( name = "Delta → Vertex Color (Roof Snow Heap Tool)", default = False, options={'SKIP_SAVE'} )
    UI_meToolsMain          : bpy.props.BoolProperty   ( name = "Modders Edge Tools",       default = False , options={'SKIP_SAVE'} )
    
    UI_trackArrayToolsMain  : bpy.props.BoolProperty   ( name = "Track Array Tools",       default = False , options={'SKIP_SAVE'} )
    UI_meMaterialToolsMain  : bpy.props.BoolProperty   ( name = "Material Tools",          default = False , options={'SKIP_SAVE'} )
    UI_meMaterialCleanup     : bpy.props.BoolProperty   ( name = "Material Cleanup",       default = False , options={'SKIP_SAVE'} )
    UI_meMaterialReplace     : bpy.props.BoolProperty   ( name = "Replace Material A → B",   default = False , options={'SKIP_SAVE'} )

    me_replace_scope          : bpy.props.EnumProperty(
        name="Scope",
        items=[
            ("SELECTED", "Selected Objects", ""),
            ("ALL", "All Objects", ""),
        ],
        default="SELECTED",
    )

    me_replace_from           : bpy.props.EnumProperty(
        name="From",
        items=_i3d_enum_all_materials,
    )

    me_replace_to             : bpy.props.EnumProperty(
        name="To",
        items=_i3d_enum_all_materials,
    )
    UI_meVertexGeoTools      : bpy.props.BoolProperty   ( name = "Vertex / Geometry Tools", default = False )
    UI_meCursorOrigin        : bpy.props.BoolProperty   ( name = "Cursor & Origin",        default = False )
    UI_meAddObjects          : bpy.props.BoolProperty   ( name = "Add Objects",            default = False )
    UI_meApplyTransforms     : bpy.props.BoolProperty   ( name = "Apply Transforms",       default = False )
    UI_meMeshCleanup         : bpy.props.BoolProperty   ( name = "Mesh Cleanup (Edit Mode)", default = False )
    UI_meUVMap               : bpy.props.BoolProperty   ( name = "UV Map",                default = False )
    i3D_ME_mergeDistance : bpy.props.FloatProperty(
        name="Merge Distance",
        description="Merge distance for Vertex Cleanup (GamerDesigns toolset).",
        default=0.0001,
        min=0.0,
        max=1.0
    )
    i3D_ME_convertToQuads : bpy.props.BoolProperty(
        name="Convert to Quads",
        description="Convert tris to quads where possible (GamerDesigns toolset).",
        default=True
    )
    i3D_ME_uvMargin : bpy.props.FloatProperty(
        name="UV Margin",
        description="UV island margin for Angle Based Unwrap (GamerDesigns toolset).",
        default=0.001,
        min=0.0,
        max=1.0,
        precision=4,
        step=0.01
    )
    i3D_ME_uvIslandMargin : bpy.props.FloatProperty(
        name="Island Margin",
        description="Island margin for Smart UV Project (GamerDesigns toolset).",
        default=0.005,
        min=0.0,
        max=1.0,
        precision=4,
        step=0.01
    )
    UI_ActiveObjectName     : bpy.props.StringProperty ( name = "Active Object Name", default = "empty")
    UI_PrevActiveObjectName : bpy.props.StringProperty ( name = "Previously Active Object Name", default = "empty" """, update=test""")
    UI_autoAssign           : bpy.props.BoolProperty   ( name = "Auto Assign", default = False, description = "Update attributes automatic to selected object",update = toggleAutoAssign)

    UI_lightUseShadow       : bpy.props.BoolProperty   ( name = "Use Shadow", default = False, update = lightUseShadowUpdate )

    UI_refractionMap   : bpy.props.BoolProperty ( name = "Refraction Map", default = True)
    UI_materialTools   : bpy.props.BoolProperty ( name = "Tools", default = True)

    # i3D_exportIK                  : bpy.props.BoolProperty   ( name = "IK",                   default = dcc.SETTINGS_UI['i3D_exportIK']['defaultValue'] )
    i3D_exportAnimation           : bpy.props.BoolProperty   ( name = "Animation", description="Export Animation Data",            default = dcc.SETTINGS_UI['i3D_exportAnimation']['defaultValue']  )
    i3D_exportShapes              : bpy.props.BoolProperty   ( name = "Shapes", description="Export Shapes as Transform Groups if unchecked", default = dcc.SETTINGS_UI['i3D_exportShapes']['defaultValue']  )
    i3D_exportNurbsCurves         : bpy.props.BoolProperty   ( name = "Nurbs Curves",description="Export Nurbs Curves as Transform Groups if unchecked",         default = dcc.SETTINGS_UI['i3D_exportNurbsCurves']['defaultValue'] )
    i3D_exportLights              : bpy.props.BoolProperty   ( name = "Lights", description="Export Lights as Transform Groups if unchecked",              default = dcc.SETTINGS_UI['i3D_exportLights']['defaultValue']  )
    i3D_exportCameras             : bpy.props.BoolProperty   ( name = "Cameras",description="Export Cameras as Transform Groups if unchecked",              default = dcc.SETTINGS_UI['i3D_exportCameras']['defaultValue']  )
    i3D_binaryFiles             : bpy.props.BoolProperty   ( name = "Binary Files",description="Export i3d in binary format",              default = dcc.SETTINGS_UI['i3D_binaryFiles']['defaultValue']  )

    # i3D_exportParticleSystems     : bpy.props.BoolProperty   ( name = "Particle Systems",     default = dcc.SETTINGS_UI['i3D_exportParticleSystems']['defaultValue'] )
    i3D_exportUserAttributes      : bpy.props.BoolProperty   ( name = "User Attributes",description="Export User Attributes if checked",       default = dcc.SETTINGS_UI['i3D_exportUserAttributes']['defaultValue']  )
    i3D_exportNormals             : bpy.props.BoolProperty   ( name = "Normals",description="Export Normals if checked",              default = dcc.SETTINGS_UI['i3D_exportNormals']['defaultValue']  )
    i3D_exportColors              : bpy.props.BoolProperty   ( name = "Vertex Colors",description="Export Vertex Colors if checked",        default = dcc.SETTINGS_UI['i3D_exportColors']['defaultValue']  )
    i3D_exportTexCoords           : bpy.props.BoolProperty   ( name = "UVs",description="Export UV mapping if checked",                  default = dcc.SETTINGS_UI['i3D_exportTexCoords']['defaultValue']  )
    i3D_exportSkinWeigths         : bpy.props.BoolProperty   ( name = "Skin Weigths",description="Export Bones and Skinning attributes if checked",         default = dcc.SETTINGS_UI['i3D_exportSkinWeigths']['defaultValue']  )
    i3D_exportMergeGroups         : bpy.props.BoolProperty   ( name = "Merge Groups", description="Export Merge Groups if checked",        default = dcc.SETTINGS_UI['i3D_exportMergeGroups']['defaultValue']  )
    i3D_exportVerbose             : bpy.props.BoolProperty   ( name         = "Verbose",
                                                               description  = "Print info to System Console",
                                                               default      = dcc.SETTINGS_UI['i3D_exportVerbose']['defaultValue'] )
    i3D_exportEmissionOverride : bpy.props.BoolProperty(
        name = "Delete Blank Emissions",
        description = "If enabled, any emission with no texture will be forced to black (0,0,0) on export. Turn this off if you need GE emissive map generation.",
        default = True
    )

    i3D_exportSnowHeapMode         : bpy.props.BoolProperty ( name = "Snow Heap Mode", description="Exports vertex colors in linear space for snowHeapShader deformation (no sRGB conversion).", default = False )

    # ------------------------------------------------------------
    # Color Library XML Export - L10N naming / dictionaries
    i3D_exportColorLibrariesGenerateL10N : bpy.props.BoolProperty(
        name = "Generate English L10N",
        description = "When exporting ColorConfigurations.xml from the Color Library XML tool, replace wrapper titles and color names with $l10n_* keys and write L10N dictionary files next to the export.",
        default = True
    )

    i3D_exportColorLibrariesGermanL10N : bpy.props.BoolProperty(
        name = "Generate German L10N (Online)",
        description = "If enabled and Blender has online access, also generate a German L10N dictionary for Color Library XML exports. (Popular Library uses a local preset; 'My Color Library' and wrapper titles may use online translation.)",
        default = True
    )

    i3D_exportRelativePaths       : bpy.props.BoolProperty   ( name = "Export Relative Paths",description="Export File Paths relative to the *.i3d File",      default = dcc.SETTINGS_UI['i3D_exportRelativePaths']['defaultValue'])
    i3D_exportGameRelativePath       : bpy.props.BoolProperty   ( name = "Export Game Relative Path",description="Export File Paths relative to the Game Installation Path",       default = dcc.SETTINGS_UI['i3D_exportGameRelativePath']['defaultValue'], update=setExportRelativePath  )
    i3D_gameLocationDisplay         : bpy.props.StringProperty ( name = "Location",description="Game Installation Path used for Game Relative Path export option",  default="")
    i3D_exportApplyModifiers      : bpy.props.BoolProperty   ( name = "Apply Modifiers",description="Applies Modifiers if checked",      default = True  )
    i3D_exportAxisOrientations    : bpy.props.EnumProperty   (
                                    items = [   ( "BAKE_TRANSFORMS" , "Bake Transforms" , "Change axis Z = Y" ),
                                    ( "KEEP_TRANSFORMS" , "Keep Transforms" , "Export without any changes" )   ],
                                    name    = "Axis Orientations",
                                    default = "BAKE_TRANSFORMS" )
    i3D_exportUseSoftwareFileName : bpy.props.BoolProperty   ( name = "Use Blender Filename",description="Export Location and Name are the same as the current *.blend File", default = dcc.SETTINGS_UI['i3D_exportUseSoftwareFileName']['defaultValue']  )
    i3D_updateXMLOnExport : bpy.props.BoolProperty   ( name = "Update XML on Export", description="Update the selected XML config Files when Exported",default = dcc.SETTINGS_UI['i3D_updateXMLOnExport']['defaultValue']  )
    i3D_exportFileLocation        : bpy.props.StringProperty ( name = "File Location", description="Target File, if extention does not match, it is replaced by .i3d")
    i3D_predefinedPhysic    : bpy.props.EnumProperty   (
                                    default=0,
                                    items = dcc.UIgetPredefinePhysicItems,
                                    name="Physics",
                                    update=updateFromPredefinePhysic
                                    )
    i3D_predefinedNonPhysic    : bpy.props.EnumProperty   (
                                    default=0,
                                    items = dcc.UIgetPredefineNonPhysicItems,
                                    name="Non Physics",
                                    update=updateFromPredefineNonPhysic
                                    )
    i3D_predefinedCollision    : bpy.props.EnumProperty   (
                                    default=0,
                                    items = dcc.UIgetPredefineCollision,
                                    name="Collision Presets",
                                    update=updateFromPredefineCollision
                                    )
    i3D_selectedPredefined :    bpy.props.StringProperty ( name = "Selected Predef.", default = dcc.SETTINGS_ATTRIBUTES['i3D_selectedPredefined']['defaultValue'])
    i3D_predefHasChanged    :   bpy.props.BoolProperty  (name = "Predef change state", default = dcc.SETTINGS_ATTRIBUTES['i3D_predefHasChanged']['defaultValue'])

    i3D_updateXMLFilePath : bpy.props.StringProperty ( name = "XML File Paths",   default = dcc.SETTINGS_UI['i3D_updateXMLFilePath']['defaultValue']  )
    i3D_shaderFolderLocation : bpy.props.StringProperty (name = "Shader Folder", update=onWriteShaderPath)
    i3D_materialSlotName : bpy.props.StringProperty (name = "Slot Name")
    i3D_shadingRate             : bpy.props.EnumProperty(
                items = [ ('1x1' ,  '1x1'   ,  ''),
                          ('1x2',  '1x2', ''),
                          ('2x1',  '2x1', ''),
                          ('2x2',  '2x2', ''),
                          ('2x4',  '2x4', ''),
                          ('4x2',  '4x2', ''),
                          ('4x4',  '4x4', '')],
                name = "Shading Rate"
                )
    i3D_alphaBlending           : bpy.props.BoolProperty ( name = 'Alpha Blending', default = dcc.SETTINGS_ATTRIBUTES['i3D_alphaBlending']['defaultValue'])
    i3D_refractionMap           : bpy.props.BoolProperty ( name = 'Refraction Map', default = dcc.SETTINGS_ATTRIBUTES['i3D_refractionMap']['defaultValue'], update = refractionMapUpdate)
    i3D_refractionMapLightAbsorbance : bpy.props.StringProperty ( name = 'Light Absorbance', default = dcc.SETTINGS_ATTRIBUTES['i3D_refractionMapLightAbsorbance']['defaultValue'])
    i3D_refractionMapBumpScale : bpy.props.StringProperty ( name = 'Bump Scale', default = dcc.SETTINGS_ATTRIBUTES['i3D_refractionMapBumpScale']['defaultValue'])
    i3D_refractionMapWithSSRData: bpy.props.BoolProperty ( name = 'With SSR Data', default = dcc.SETTINGS_ATTRIBUTES['i3D_refractionMapWithSSRData']['defaultValue'])
    i3D_nodeName              : bpy.props.StringProperty ( name = "Loaded Node",         default = dcc.SETTINGS_UI['i3D_nodeName']['defaultValue'])
    i3D_nodeIndex             : bpy.props.StringProperty ( name = "Node Index",          default = dcc.SETTINGS_UI['i3D_nodeIndex']['defaultValue'] )
    i3D_lockedGroup           : bpy.props.BoolProperty   ( name = "Locked Group",        default = dcc.SETTINGS_ATTRIBUTES['i3D_lockedGroup']['defaultValue'] )
    i3D_static                : bpy.props.BoolProperty   ( name = "Static",              default = dcc.SETTINGS_ATTRIBUTES['i3D_static']['defaultValue'],  description = "passive Rigid Body non movable"  )
    i3D_dynamic               : bpy.props.BoolProperty   ( name = "Dynamic",             default = dcc.SETTINGS_ATTRIBUTES['i3D_dynamic']['defaultValue'], description = "active Rigid Body simulated"     )
    i3D_kinematic             : bpy.props.BoolProperty   ( name = "Kinematic",           default = dcc.SETTINGS_ATTRIBUTES['i3D_kinematic']['defaultValue'], description = "passive Rigid Body movable"      )
    i3D_compound              : bpy.props.BoolProperty   ( name = "Compound",            default = dcc.SETTINGS_ATTRIBUTES['i3D_compound']['defaultValue'], description = "group of Rigid Bodies"           )
    i3D_compoundChild         : bpy.props.BoolProperty   ( name = "Compound Child",      default = dcc.SETTINGS_ATTRIBUTES['i3D_compoundChild']['defaultValue'], description = "part of a group of Rigid Bodies" )
    i3D_collision             : bpy.props.BoolProperty   ( name = "Collision",           default = dcc.SETTINGS_ATTRIBUTES['i3D_collision']['defaultValue']   )
    i3D_collisionFilterMask   : bpy.props.StringProperty ( name = "Collision Filter Mask",  default = dcc.SETTINGS_ATTRIBUTES['i3D_collisionFilterMask']['defaultValue']    )
    i3D_collisionFilterGroup  : bpy.props.StringProperty ( name = "Collision Filter Group", default = dcc.SETTINGS_ATTRIBUTES['i3D_collisionFilterGroup']['defaultValue']    )
    i3D_solverIterationCount  : bpy.props.IntProperty    ( name = "Solver Iterations",   default = dcc.SETTINGS_ATTRIBUTES['i3D_solverIterationCount']['defaultValue']      )
    i3D_restitution           : bpy.props.FloatProperty  ( name = "Restitution",         default = dcc.SETTINGS_ATTRIBUTES['i3D_restitution']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_staticFriction        : bpy.props.FloatProperty  ( name = "Static Friction",     default = dcc.SETTINGS_ATTRIBUTES['i3D_staticFriction']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_dynamicFriction       : bpy.props.FloatProperty  ( name = "Dynamic Friction",    default = dcc.SETTINGS_ATTRIBUTES['i3D_dynamicFriction']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_linearDamping         : bpy.props.FloatProperty  ( name = "Linear Damping",      default = dcc.SETTINGS_ATTRIBUTES['i3D_linearDamping']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_angularDamping        : bpy.props.FloatProperty  ( name = "Angular Damping",     default = dcc.SETTINGS_ATTRIBUTES['i3D_angularDamping']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_density               : bpy.props.FloatProperty  ( name = "Density",             default = dcc.SETTINGS_ATTRIBUTES['i3D_density']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_ccd                   : bpy.props.BoolProperty   ( name = "Continues Collision Detection" , default = dcc.SETTINGS_ATTRIBUTES['i3D_ccd']['defaultValue']  )
    i3D_trigger               : bpy.props.BoolProperty   ( name = "Trigger",             default = dcc.SETTINGS_ATTRIBUTES['i3D_trigger']['defaultValue']  )
    i3D_splitType             : bpy.props.IntProperty    ( name = "Split Type",          default = dcc.SETTINGS_ATTRIBUTES['i3D_splitType']['defaultValue']  )
    i3D_splitMinU             : bpy.props.FloatProperty  ( name = "Split Min U",         default = dcc.SETTINGS_ATTRIBUTES['i3D_splitMinU']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_splitMinV             : bpy.props.FloatProperty  ( name = "Split Min V",         default = dcc.SETTINGS_ATTRIBUTES['i3D_splitMinV']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_splitMaxU             : bpy.props.FloatProperty  ( name = "Split Max U",         default = dcc.SETTINGS_ATTRIBUTES['i3D_splitMaxU']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_splitMaxV             : bpy.props.FloatProperty  ( name = "Split Max V",         default = dcc.SETTINGS_ATTRIBUTES['i3D_splitMaxV']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_splitUvWorldScale     : bpy.props.FloatProperty  ( name = "Split UV's worldScale",         default = dcc.SETTINGS_ATTRIBUTES['i3D_splitUvWorldScale']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_joint                 : bpy.props.BoolProperty   ( name = "Joint",               default = dcc.SETTINGS_ATTRIBUTES['i3D_joint']['defaultValue']   )
    i3D_projection            : bpy.props.BoolProperty   ( name = "Projection",          default = dcc.SETTINGS_ATTRIBUTES['i3D_projection']['defaultValue']  )
    i3D_projDistance          : bpy.props.FloatProperty  ( name = "Projection Distance", default = dcc.SETTINGS_ATTRIBUTES['i3D_projDistance']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_projAngle             : bpy.props.FloatProperty  ( name = "Projection Angle",    default = dcc.SETTINGS_ATTRIBUTES['i3D_projAngle']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_xAxisDrive            : bpy.props.BoolProperty   ( name = "X-Axis Drive",        default = dcc.SETTINGS_ATTRIBUTES['i3D_xAxisDrive']['defaultValue']  )
    i3D_yAxisDrive            : bpy.props.BoolProperty   ( name = "Y-Axis Drive",        default = dcc.SETTINGS_ATTRIBUTES['i3D_yAxisDrive']['defaultValue']  )
    i3D_zAxisDrive            : bpy.props.BoolProperty   ( name = "Z-Axis Drive",        default = dcc.SETTINGS_ATTRIBUTES['i3D_zAxisDrive']['defaultValue']  )
    i3D_drivePos              : bpy.props.BoolProperty   ( name = "Drive Position",      default = dcc.SETTINGS_ATTRIBUTES['i3D_drivePos']['defaultValue']  )
    i3D_driveForceLimit       : bpy.props.FloatProperty  ( name = "Drive Force Limit",   default = dcc.SETTINGS_ATTRIBUTES['i3D_driveForceLimit']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_driveSpring           : bpy.props.FloatProperty  ( name = "Drive Spring",        default = dcc.SETTINGS_ATTRIBUTES['i3D_driveSpring']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_driveDamping          : bpy.props.FloatProperty  ( name = "Drive Damping",       default = dcc.SETTINGS_ATTRIBUTES['i3D_driveDamping']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_breakableJoint        : bpy.props.BoolProperty   ( name = "Breakable",           default = dcc.SETTINGS_ATTRIBUTES['i3D_breakableJoint']['defaultValue']  )
    i3D_jointBreakForce       : bpy.props.FloatProperty  ( name = "Break Force",         default = dcc.SETTINGS_ATTRIBUTES['i3D_jointBreakForce']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_jointBreakTorque      : bpy.props.FloatProperty  ( name = "Break Torque",        default = dcc.SETTINGS_ATTRIBUTES['i3D_jointBreakTorque']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_oc                    : bpy.props.BoolProperty   ( name = "Occluder",            default = dcc.SETTINGS_ATTRIBUTES['i3D_oc']['defaultValue'] )
    i3D_castsShadows          : bpy.props.BoolProperty   ( name = "Casts Shadows",       default = dcc.SETTINGS_ATTRIBUTES['i3D_castsShadows']['defaultValue'])
    i3D_castsShadowsPerInstance : bpy.props.BoolProperty   ( name = "Per Instance",      default = dcc.SETTINGS_ATTRIBUTES['i3D_castsShadowsPerInstance']['defaultValue'])
    i3D_receiveShadows        : bpy.props.BoolProperty   ( name = "Receive Shadows",     default = dcc.SETTINGS_ATTRIBUTES['i3D_receiveShadows']['defaultValue'])
    i3D_receiveShadowsPerInstance : bpy.props.BoolProperty   ( name = "Per Instance",    default = dcc.SETTINGS_ATTRIBUTES['i3D_receiveShadowsPerInstance']['defaultValue'])
    i3D_renderedInViewports   : bpy.props.BoolProperty   ( name = "Rendered in Viewports", default = dcc.SETTINGS_ATTRIBUTES['i3D_renderedInViewports']['defaultValue']  )
    i3D_nonRenderable         : bpy.props.BoolProperty   ( name = "Non Renderable",      default = dcc.SETTINGS_ATTRIBUTES['i3D_nonRenderable']['defaultValue']  )
    i3D_clipDistance          : bpy.props.FloatProperty  ( name = "Clip Distance",       default = dcc.SETTINGS_ATTRIBUTES['i3D_clipDistance']['defaultValue'], min=0, precision = 1)
    i3D_objectMask            : bpy.props.IntProperty    ( name = "Object Mask",         default = dcc.SETTINGS_ATTRIBUTES['i3D_objectMask']['defaultValue'], min=0)
    i3D_navMeshMask           : bpy.props.IntProperty    ( name = "Nav Mesh Mask",       default = dcc.SETTINGS_ATTRIBUTES['i3D_navMeshMask']['defaultValue'], min=0)
    i3D_doubleSided           : bpy.props.BoolProperty   ( name = "Double Sided",        default = dcc.SETTINGS_ATTRIBUTES['i3D_doubleSided']['defaultValue'] )
    i3D_decalLayer            : bpy.props.IntProperty    ( name = "Decal Layer",         default = dcc.SETTINGS_ATTRIBUTES['i3D_decalLayer']['defaultValue'], min=0, max=9)
    i3D_mergeGroup            : bpy.props.IntProperty    ( name = "Merge Group",         default = dcc.SETTINGS_ATTRIBUTES['i3D_mergeGroup']['defaultValue'], min=0, max=9)
    i3D_mergeGroupRoot        : bpy.props.BoolProperty   ( name = "Merge Group Root",    default = dcc.SETTINGS_ATTRIBUTES['i3D_mergeGroupRoot']['defaultValue'])
    i3D_boundingVolume        : bpy.props.StringProperty ( name = "Bounding Volume",     default = dcc.SETTINGS_ATTRIBUTES['i3D_boundingVolume']['defaultValue'])
    i3D_boundingVolumeMergeGroup  : bpy.props.EnumProperty ( items = [
                                                                ("MERGEGROUP_1", "Merge Group 1", "Set bounding Volume for merge group 1"),
                                                                ("MERGEGROUP_2", "Merge Group 2", "Set bounding Volume for merge group 2"),
                                                                ("MERGEGROUP_3", "Merge Group 3", "Set bounding Volume for merge group 3"),
                                                                ("MERGEGROUP_4", "Merge Group 4", "Set bounding Volume for merge group 4"),
                                                                ("MERGEGROUP_5", "Merge Group 5", "Set bounding Volume for merge group 5"),
                                                                ("MERGEGROUP_6", "Merge Group 6", "Set bounding Volume for merge group 6"),
                                                                ("MERGEGROUP_7", "Merge Group 7", "Set bounding Volume for merge group 7"),
                                                                ("MERGEGROUP_8", "Merge Group 8", "Set bounding Volume for merge group 8"),
                                                                ("MERGEGROUP_9", "Merge Group 9", "Set bounding Volume for merge group 9")],
                                                             name = "",
                                                             update = boundingVolumeMergeGroupUpdate)

    i3D_selectedMaterialEnum : bpy.props.EnumProperty(items = I3D_PT_PanelExport.getMaterials,
                                                     name = "Selected Material",
                                                     update = selectedMaterialEnumUpdate,
                                                     get = None, set = None)
    i3D_shaderEnum : bpy.props.EnumProperty(items = I3D_PT_PanelExport.getShadersFromDirectory,
                                            name = "Shader File",
                                            update=shaderEnumUpdate, get=None, set=None)
    i3D_shaderVariationEnum : bpy.props.EnumProperty(items = (("None", "None", "None"),), name="Shader Variation")
    i3D_mergeChildren   : bpy.props.BoolProperty(name="Merge Children", default = dcc.SETTINGS_ATTRIBUTES['i3D_mergeChildren']['defaultValue'])
    i3D_mergeChildrenFreezeRotation : bpy.props.BoolProperty(name="Rotation", default = dcc.SETTINGS_ATTRIBUTES['i3D_mergeChildrenFreezeRotation']['defaultValue'])
    i3D_mergeChildrenFreezeTranslation  : bpy.props.BoolProperty(name="Translation", default = dcc.SETTINGS_ATTRIBUTES['i3D_mergeChildrenFreezeTranslation']['defaultValue'])
    i3D_mergeChildrenFreezeScale    : bpy.props.BoolProperty(name="Scale", default = dcc.SETTINGS_ATTRIBUTES['i3D_mergeChildrenFreezeScale']['defaultValue'])

    i3D_terrainDecal          : bpy.props.BoolProperty   ( name = "Terrain Decal",       default = dcc.SETTINGS_ATTRIBUTES['i3D_terrainDecal']['defaultValue']  )
    i3D_cpuMesh               : bpy.props.BoolProperty   ( name = "CPU Mesh",            default = dcc.SETTINGS_ATTRIBUTES['i3D_cpuMesh']['defaultValue']  )
    i3D_lod                   : bpy.props.BoolProperty   ( name = "LOD",                 default = dcc.SETTINGS_ATTRIBUTES['i3D_lod']['defaultValue']  )
    i3D_lod0                  : bpy.props.FloatProperty  ( name = "Child 0 Distance",    default = 0, precision = 1 )
    i3D_lod1                  : bpy.props.FloatProperty  ( name = "Child 1 Distance",    default = dcc.SETTINGS_ATTRIBUTES['i3D_lod1']['defaultValue'], min = 0, precision = 1 )
    i3D_lod2                  : bpy.props.FloatProperty  ( name = "Child 2 Distance",    default = dcc.SETTINGS_ATTRIBUTES['i3D_lod2']['defaultValue'], min = 0, precision = 1 )
    i3D_lod3                  : bpy.props.FloatProperty  ( name = "Child 3 Distance",    default = dcc.SETTINGS_ATTRIBUTES['i3D_lod3']['defaultValue'], min = 0, precision = 1 )
    i3D_vertexCompressionRange: bpy.props.EnumProperty   (
                                    items = [
                                        ("Auto", "Auto", ""),
                                        ("0.5", "0.5", ""),
                                        ("1", "1", ""),
                                        ("2", "2", ""),
                                        ("4", "4", ""),
                                        ("8", "8", ""),
                                        ("16", "16", ""),
                                        ("32", "32", ""),
                                        ("64", "64", ""),
                                        ("128", "128", ""),
                                        ("256", "256", ""),
                                    ],
                                    name="Vertex Compression Range",)

    i3D_minuteOfDayStart      : bpy.props.IntProperty       ( name = "Minute Of Day Start",          default = dcc.SETTINGS_ATTRIBUTES['i3D_minuteOfDayStart']['defaultValue'] )
    i3D_minuteOfDayEnd        : bpy.props.IntProperty       ( name = "Minute Of Day End",            default = dcc.SETTINGS_ATTRIBUTES['i3D_minuteOfDayEnd']['defaultValue'] )
    i3D_dayOfYearStart        : bpy.props.IntProperty       ( name = "Day Of Year Start",            default = dcc.SETTINGS_ATTRIBUTES['i3D_dayOfYearStart']['defaultValue'] )
    i3D_dayOfYearEnd          : bpy.props.IntProperty       ( name = "Day Of Year End",              default = dcc.SETTINGS_ATTRIBUTES['i3D_dayOfYearEnd']['defaultValue'] )
    i3D_weatherMask           : bpy.props.StringProperty    ( name = "Weather Mask (Dec)",           default = dcc.SETTINGS_ATTRIBUTES['i3D_weatherMask']['defaultValue'] )
    i3D_viewerSpacialityMask  : bpy.props.StringProperty    ( name = "Viewer Spaciality Mask (Dec)", default = dcc.SETTINGS_ATTRIBUTES['i3D_viewerSpacialityMask']['defaultValue'] )
    i3D_weatherPreventMask      :bpy.props.StringProperty   ( name = "Weather Prevent Mask (Dec)",  default = dcc.SETTINGS_ATTRIBUTES['i3D_weatherPreventMask']['defaultValue'])
    i3D_viewerSpacialityPreventMask      :bpy.props.StringProperty   ( name = "Viewer Spaciality Prevent Mask (Dec)",  default = dcc.SETTINGS_ATTRIBUTES['i3D_viewerSpacialityPreventMask']['defaultValue'])
    i3D_renderInvisible         :bpy.props.BoolProperty     ( name = "Render Invisible",            default = dcc.SETTINGS_ATTRIBUTES['i3D_renderInvisible']['defaultValue'])
    i3D_visibleShaderParam      :bpy.props.FloatProperty    ( name = "Visible Shader Param",        default = dcc.SETTINGS_ATTRIBUTES['i3D_visibleShaderParam']['defaultValue'] , precision = dcc.FLOAT_PRECISION )
    i3D_forceVisibilityCondition :bpy.props.BoolProperty     ( name = "Force Visibility Condition", default = dcc.SETTINGS_ATTRIBUTES['i3D_forceVisibilityCondition']['defaultValue'])

    i3D_objectDataFilePath                : bpy.props.StringProperty ( name = "File Path",           default = dcc.SETTINGS_ATTRIBUTES['i3D_objectDataFilePath']['defaultValue'])
    i3D_objectDataHierarchicalSetup       : bpy.props.BoolProperty   ( name = "Hierarchical Setup",  default = dcc.SETTINGS_ATTRIBUTES['i3D_objectDataHierarchicalSetup']['defaultValue']  )
    i3D_objectDataHideFirstAndLastObject  : bpy.props.BoolProperty   ( name = "HideFirst And Last",  default = dcc.SETTINGS_ATTRIBUTES['i3D_objectDataHideFirstAndLastObject']['defaultValue']  )
    i3D_objectDataExportPosition          : bpy.props.BoolProperty   ( name = "Export Position",     default = dcc.SETTINGS_ATTRIBUTES['i3D_objectDataExportPosition']['defaultValue'] )
    i3D_objectDataExportOrientation       : bpy.props.BoolProperty   ( name = "Export Orientation",  default = dcc.SETTINGS_ATTRIBUTES['i3D_objectDataExportOrientation']['defaultValue']  )
    i3D_objectDataExportScale             : bpy.props.BoolProperty   ( name = "Export Scale",        default = dcc.SETTINGS_ATTRIBUTES['i3D_objectDataExportScale']['defaultValue']  )

    i3D_softShadowsLightSize       : bpy.props.FloatProperty  ( name = "Soft Shadow Light Size",        default = dcc.SETTINGS_ATTRIBUTES["i3D_softShadowsLightSize"]["defaultValue"] )
    i3D_softShadowsLightDistance   : bpy.props.FloatProperty  ( name = "Soft Shadow Light Distance",    default = dcc.SETTINGS_ATTRIBUTES["i3D_softShadowsLightDistance"]["defaultValue"] )
    i3D_softShadowsDepthBiasFactor : bpy.props.FloatProperty  ( name = "Soft Shadow Depth Bias Factor", default = dcc.SETTINGS_ATTRIBUTES["i3D_softShadowsDepthBiasFactor"]["defaultValue"] )
    i3D_softShadowsMaxPenumbraSize : bpy.props.FloatProperty  ( name = "Soft Shadow Max Penumbra Size", default = dcc.SETTINGS_ATTRIBUTES["i3D_softShadowsMaxPenumbraSize"]["defaultValue"] )
    i3D_iesProfileFile             : bpy.props.StringProperty ( name = "IES Profile File",              default = dcc.SETTINGS_ATTRIBUTES['i3D_iesProfileFile']['defaultValue'] )
    i3D_isLightScattering          : bpy.props.BoolProperty   ( name = "Enable Light Scattering",       default = False, update = lightScatteringUpdate )
    i3D_lightScatteringIntensity   : bpy.props.FloatProperty  ( name = "Light Scattering Intensity",    default = dcc.SETTINGS_ATTRIBUTES["i3D_lightScatteringIntensity"]["defaultValue"], update = lightScatteringIntensityUpdate )
    i3D_lightScatteringConeAngle   : bpy.props.FloatProperty  ( name = "Light Scattering Cone Angle",   default = dcc.SETTINGS_ATTRIBUTES["i3D_lightScatteringConeAngle"]["defaultValue"], update = lightScatteringConeAngleUpdate )

    @classmethod
    def register( cls ):
        bpy.types.Scene.I3D_UIexportSettings = bpy.props.PointerProperty(
            name = "I3D UI Export Settings",
            type =  cls,
            description = "I3D UI Export Settings"
        )
    @classmethod
    def unregister( cls ):
        if bpy.context.scene.get( 'I3D_UIexportSettings' ):  del bpy.context.scene[ 'I3D_UIexportSettings' ]
        try:    del bpy.types.Scene.I3D_UIexportSettings
        except: pass

#-------------------------------------------------------------------------------
#   Handlers
#-------------------------------------------------------------------------------

# --------------------------------------------------------------
# Shader folder auto init
# --------------------------------------------------------------
# The shader folder path (scene property) can persist across sessions, but
# the dynamic UI (parameter templates, variation dropdowns, etc.) is rebuilt
# at runtime by shaderEnumUpdate(). On Blender restart, the path will look
# "filled in" while the runtime classes are not initialized yet, which makes
# shader tools appear broken until the user clicks "Detect Path".
#
# We auto-run a best-effort init once per scene load if a shader folder path
# is already present.

def _i3d_autoinit_shader_ui_timer():
    """Auto-run shaderEnumUpdate once per scene after startup / file load.

    Returns:
        None to stop the timer, or a float (seconds) to retry later.
    """
    global g_autoShaderInitEnabled, _g_autoShaderInitDoneScenes, _g_autoShaderInitAttempts

    if not g_autoShaderInitEnabled:
        return None

    ctx = bpy.context
    scene = getattr(ctx, "scene", None)
    if scene is None:
        return 0.5

    # Scene export settings might not exist yet if registration hasn't completed.
    settings = getattr(scene, "I3D_UIexportSettings", None)
    if settings is None:
        return 0.5

    scene_ptr = scene.as_pointer()
    if scene_ptr in _g_autoShaderInitDoneScenes:
        return None

    try:
        shader_folder_raw = getattr(settings, "i3D_shaderFolderLocation", "") or ""
        if shader_folder_raw.strip() == "":
            _g_autoShaderInitDoneScenes.add(scene_ptr)
            return None

        # If we're using a portable $data/... path, ensure game path is available first.
        if shader_folder_raw.startswith("$"):
            game_path = getGamePath() or getattr(settings, "i3D_gameLocationDisplay", "") or ""
            if not game_path:
                # Wait a bit; load_handler will usually populate this.
                raise RuntimeError("Game path not initialized yet for $data shader folder resolution")

        # Ensure shader enum is valid for the directory
        shader_items = I3D_PT_PanelExport.getShadersFromDirectory(settings, ctx)
        shader_ids = [t[0] for t in shader_items] if shader_items else []
        if shader_ids and getattr(settings, "i3D_shaderEnum", None) not in shader_ids:
            settings.i3D_shaderEnum = shader_ids[0]

        # Build the runtime UI classes
        shaderEnumUpdate(settings, ctx)

        _g_autoShaderInitDoneScenes.add(scene_ptr)
        return None

    except Exception as e:
        attempts = _g_autoShaderInitAttempts.get(scene_ptr, 0) + 1
        _g_autoShaderInitAttempts[scene_ptr] = attempts

        if attempts < 10:
            return 0.5

        print(f"[I3D] Auto-init shader UI failed after {attempts} attempts: {e}")
        _g_autoShaderInitDoneScenes.add(scene_ptr)
        return None


def schedule_i3d_shader_autoinit(force=False):
    """Schedule the shader UI auto-init timer (safe to call repeatedly)."""
    global _g_autoShaderInitDoneScenes, _g_autoShaderInitAttempts

    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        scene_ptr = scene.as_pointer()
        if force:
            _g_autoShaderInitAttempts.pop(scene_ptr, None)
            _g_autoShaderInitDoneScenes.discard(scene_ptr)

    try:
        if bpy.app.timers.is_registered(_i3d_autoinit_shader_ui_timer):
            return
    except Exception:
        # Older Blender builds may not expose is_registered reliably
        pass

    try:
        bpy.app.timers.register(_i3d_autoinit_shader_ui_timer, first_interval=0.35)
    except Exception as e:
        print(f"[I3D] Unable to schedule shader auto-init timer: {e}")

@persistent
def load_handler(dummy):
    """ not executed if addon is enabled in the preferences, only on load file (eg. startup or load file)"""

    try:
        # Validate and, if necessary, auto-detect the game path in addon preferences
        addon_entry = bpy.context.preferences.addons.get("io_export_i3d_reworked")
        if addon_entry and getattr(addon_entry, "preferences", None):
            prefs = addon_entry.preferences
            game_path = prefs.game_install_path or ""
            if game_path and not os.path.isdir(game_path):
                print(f"\"{game_path}\" is no valid game path")
                game_path = ""

            if not game_path and dirf.isWindows():
                try:
                    auto_path = dirf.findFS22Path()
                except Exception:
                    auto_path = ""

                if auto_path and os.path.isdir(auto_path):
                    prefs.game_install_path = auto_path
                    game_path = auto_path
                    print("Auto-detected game path:", auto_path)

                        # Keep scene export setting in sync (many parts of the addon read from this)
            scene_settings = bpy.context.scene.I3D_UIexportSettings

            # If a legacy IDProperty exists, migrate it into the RNA property BEFORE cleaning it up.
            legacy_keys = set()
            try:
                legacy_keys = set(scene_settings.keys())
            except Exception:
                legacy_keys = set()

            legacy_val = ""
            if "i3D_gameLocationDisplay" in legacy_keys:
                try:
                    legacy_val = scene_settings.get("i3D_gameLocationDisplay", "") or ""
                except Exception:
                    legacy_val = ""

            # If prefs/autodetect are empty but the legacy value is valid, keep it (and persist it back to prefs)
            if not game_path and legacy_val and os.path.isdir(legacy_val):
                game_path = legacy_val
                prefs.game_install_path = legacy_val

            if getattr(scene_settings, "i3D_gameLocationDisplay", "") != game_path:
                scene_settings.i3D_gameLocationDisplay = game_path

            # Remove ONLY the legacy IDProperty key (do NOT touch the RNA property)
            if "i3D_gameLocationDisplay" in legacy_keys:
                try:
                    del scene_settings["i3D_gameLocationDisplay"]
                except Exception:
                    pass


    except Exception as e:
        print(e)

    # Handle legacy attribute names (written with an upper case I)
    legacySettingsAttributeMap = {
        "I3D_gameLocationDisplay": "i3D_gameLocationDisplay",
        "I3D_shaderFolderLocation": "i3D_shaderFolderLocation",
        "I3D_XMLConfigIdentification": "i3D_XMLConfigIdentification",
        "I3D_XMLConfigExport": "i3D_XMLConfigExport"
    }
    for oldAttrName, newAttrName in legacySettingsAttributeMap.items():
        if oldAttrName in bpy.context.scene.I3D_UIexportSettings:
            old_val = bpy.context.scene.I3D_UIexportSettings.get(oldAttrName)
            if old_val is None and hasattr(bpy.context.scene.I3D_UIexportSettings, oldAttrName):
                old_val = getattr(bpy.context.scene.I3D_UIexportSettings, oldAttrName)
            if old_val is not None:
                setattr(bpy.context.scene.I3D_UIexportSettings, newAttrName, old_val)
            if oldAttrName in bpy.context.scene.I3D_UIexportSettings:
                del bpy.context.scene.I3D_UIexportSettings[oldAttrName]

    legacyNodeAttributeMap = {"I" + attrName[1::] : attrName for attrName, _ in dcc.SETTINGS_ATTRIBUTES.items() if attrName[0] == "i"}
    for m_node in bpy.data.objects:
        nodeAttributeMap = {oldAttrName : newAttrName for oldAttrName, newAttrName in legacyNodeAttributeMap.items() if oldAttrName in m_node}
        for oldAttrName, newAttrName in nodeAttributeMap.items():
            m_node[newAttrName] = m_node[oldAttrName]
            del m_node[oldAttrName]
    # End handle legacy attribute names

    # Handle legacy locked groups
    legacyLockedGroupAttributeName = 'i3D_lockedGroup'
    if legacyLockedGroupAttributeName in bpy.context.scene.I3D_UIexportSettings:
        if bpy.context.scene.I3D_UIexportSettings.get(legacyLockedGroupAttributeName, False) == True:
            for m_node in bpy.context.scene.objects:
                if (None is m_node.parent):
                    m_node['i3D_lockedGroup'] = True
        bpy.context.scene.I3D_UIexportSettings[legacyLockedGroupAttributeName] = 0
            # Keep legacy as IDProperty only; the new system uses RNA properties for locking state.
    # End handle legacy locked groups


    # Auto-initialize shader UI for this session/file load
    try:
        schedule_i3d_shader_autoinit(force=True)
    except Exception as e:
        print(f"[I3D] Shader auto-init scheduling failed: {e}")


@persistent
def modal_handler(dummy):
    global g_modalsRunning

    try:
        i3d_schedule_bootstrap()
    except Exception as e:
        print(e)


editMeshContextMenuClasses = [I3D_OT_FaceNormalToOrigin, I3D_OT_SelectionToOrigin, I3D_OT_CreateEmpty]
def drawEditMeshContextMenu(self, context):
    isFirstItem = True
    for editMeshContextMenuClass in editMeshContextMenuClasses:
        if editMeshContextMenuClass.getShowInContextMenu(context):
            if isFirstItem:
                self.layout.separator()
                isFirstItem = False

            self.layout.operator(editMeshContextMenuClass.bl_idname, icon=editMeshContextMenuClass.CONTEXT_MENU_ICON)

objectContextMenuClasses = [I3D_OT_CreateEmpty, I3D_OT_AlignYAxis, I3D_OT_FreezeTranslation, I3D_OT_FreezeRotation]
def drawObjectContextMenu(self, context):
    isFirstItem = True
    for objectContextMenuClass in objectContextMenuClasses:
        if objectContextMenuClass.getShowInContextMenu(context):
            if isFirstItem:
                self.layout.separator()
                isFirstItem = False

            self.layout.operator(objectContextMenuClass.bl_idname, icon=objectContextMenuClass.CONTEXT_MENU_ICON)


#-------------------------------------------------------------------------------
#   Register
#-------------------------------------------------------------------------------

class I3D_OT_OpenEnglishTutorial(bpy.types.Operator):
    bl_idname = "i3d.open_english_tutorial"
    bl_label = "English"
    bl_description = "Opens a YouTube Tutorial in English in your web browser."

    def execute(self, context):
        bpy.ops.wm.url_open(url="https://youtu.be/NzDNftZ0_gM")
        return {'FINISHED'}


class I3D_OT_OpenFrenchTutorial(bpy.types.Operator):
    bl_idname = "i3d.open_french_tutorial"
    bl_label = "French"
    bl_description = "Opens a YouTube Tutorial in French in your web browser."

    def execute(self, context):
        bpy.ops.wm.url_open(url="https://www.youtube.com/watch?v=RHeDCo2Ud8Q")
        return {'FINISHED'}

classes = (
        I3D_UIMaterialTemplateProperties,
        I3D_PT_PanelExport,
        I3D_OT_RefreshAddonAfterUpdate,
        I3D_OT_PanelExport_ButtonAttr,
        I3D_OT_PanelExport_ButtonExport,
        I3D_OT_PanelTools_ButtonChangelog,
        I3D_OT_OpenEnglishTutorial,
        I3D_OT_OpenFrenchTutorial,
        I3D_OT_ShowDeltaBakeLocation,
        I3D_OT_PanelRemoveXMLPath_ButtonRemove,
        I3D_OT_PanelAddShader_ButtonConvertFs22Fs25,
        I3D_OT_PanelAddShader_ButtonAdd,
        I3D_OT_PanelExport_ButtonClose,
        I3D_OT_PanelUpdateXMLi3dmapping,
        I3D_OT_PanelXMLidentification_ButtonAdd,
        I3D_OT_PanelOpenXMLFilebrowser,
        I3D_OT_PanelOpenFolderFilebrowser,
        I3D_OT_PanelRefreshGamePath,
        I3D_OT_PanelAddShader_ButtonLoad,
        I3D_OT_PanelSetGameShader,
        I3D_OT_PanelOpenI3DFilebrowser,
        I3D_OT_PanelOpenDDSFilebrowser,
        I3D_OT_PanelOpenIESFilebrowser,
        I3D_OT_ExportObjectDataTexture_UnsavedPrompt,
        I3D_OT_PanelTools_Button,
        I3D_OT_PanelMaterial_OpenMaterialTemplatesWindowButton,
        I3D_OT_PanelMaterial_UseMaterialNameAsSlotNameButton,
        I3D_OT_PanelMaterial_ApplyMaterialTemplateToSelection,
        I3D_OT_modal_active_object,
        I3D_OT_modal_predef_check,
        I3D_OT_BitmaskEditor,
        #I3D_OT_MaterialTemplateCategoryMenuItemExpand,
        I3D_OT_MaterialTemplateCategoryMenu,
        I3D_OT_MaterialTemplateCategoryMenuEntryExpand,
        #I3D_MaterialTemplateCategoryMenuItem,
        #I3D_UL_MaterialTemplateCategoryMenu
)

def register():
    bpy.utils.register_class( I3D_OT_ReopenConflictDialog )
    bpy.utils.register_class( I3D_OT_AddonConflictDialog )
    bpy.utils.register_class( I3D_OT_ResolveAddonConflicts )
    bpy.utils.register_class( I3D_OT_AbortInstallation )
    bpy.utils.register_class( I3D_UIexportSettings )
    bpy.utils.register_class( I3D_OT_MenuExport )
    bpy.utils.register_class( I3D_OT_SelectionToOrigin )
    bpy.utils.register_class( I3D_OT_FaceNormalToOrigin )
    bpy.utils.register_class( I3D_OT_FreezeTranslation )
    bpy.utils.register_class( I3D_OT_FreezeRotation )
    bpy.utils.register_class( I3D_OT_CreateEmpty )
    bpy.utils.register_class( I3D_OT_AlignYAxis )
    i3d_changelog.register()

    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            print(f"Error: unable to register class {cls}: {e}")
    # --------------------------Tools-------------------------------------------
    bpy.app.timers.register(_i3d_conflict_check_timer, first_interval=0.25)

    registerTools()
    # --------------------------Handler-------------------------------------------
    bpy.app.handlers.load_post.append(load_handler)
    bpy.app.handlers.load_post.append(modal_handler)
    # Ensure shader tools are ready even when enabling the addon mid-session
    schedule_i3d_shader_autoinit(force=True)
    if i3d_selected_material_sync_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(i3d_selected_material_sync_handler)
    # --------------------------Context Menu-------------------------------------------
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.append(drawEditMeshContextMenu)
    bpy.types.VIEW3D_MT_object_context_menu.append(drawObjectContextMenu)

def unregister():
    global g_autoShaderInitEnabled
    g_autoShaderInitEnabled = False
    for dynamicClass in g_dynamicGUIClsDict.values():
        bpy.utils.unregister_class(dynamicClass)
    # --------------------------Tools-------------------------------------------
    unregisterTools()
    # --------------------------------------------------------------------------

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except:
            print(f"Error: unable to unregister class {cls}")
    # --------------------------------------------------------------------------
    bpy.utils.unregister_class( I3D_OT_SelectionToOrigin )
    bpy.utils.unregister_class( I3D_OT_FaceNormalToOrigin )
    bpy.utils.unregister_class( I3D_OT_FreezeTranslation )
    bpy.utils.unregister_class( I3D_OT_FreezeRotation )
    bpy.utils.unregister_class( I3D_OT_CreateEmpty )
    bpy.utils.unregister_class( I3D_OT_AlignYAxis )
    bpy.utils.unregister_class( I3D_OT_AbortInstallation )
    bpy.utils.unregister_class( I3D_OT_ResolveAddonConflicts )
    bpy.utils.unregister_class( I3D_OT_AddonConflictDialog )
    bpy.utils.unregister_class( I3D_OT_ReopenConflictDialog )
    bpy.utils.unregister_class( I3D_OT_MenuExport )
    bpy.utils.unregister_class( I3D_UIexportSettings )
    i3d_changelog.unregister()

    bpy.app.handlers.load_post.remove(modal_handler)
    bpy.app.handlers.load_post.remove(load_handler)
    try:
        bpy.app.handlers.depsgraph_update_post.remove(i3d_selected_material_sync_handler)
    except:
        pass


    # --------------------------Context Menu-------------------------------------------
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(drawEditMeshContextMenu)
    bpy.types.VIEW3D_MT_object_context_menu.remove(drawObjectContextMenu)

    global g_modalsRunning
    g_modalsRunning = False
if __name__ == "__main__":
    register()

#-------------------------------------------------------------------------------