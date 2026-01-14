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

# -----------------------------------------------------------------------------
# Modder's Edge toolset integration (UI is in i3d_ui.py)
#
# Portions of the operator logic below are adapted from "Modder’s Edge"
# by GamerDesigns (MIT License). Adapted files included:
# - modders_edge/operators/cleanup_materials.py
# - modders_edge/operators/cleanup_vertices.py
# - modders_edge/operators/better_tris.py
# - modders_edge/operators/uv_tools.py
#
# License note:
# - Upstream code is MIT, which is compatible with GPL distribution.
# - Credit is shown in the UI per user request.
# -----------------------------------------------------------------------------

import bpy


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def _active_mesh_objects(context):
    return [o for o in (context.selected_objects or []) if getattr(o, "type", None) == "MESH"]


def _ensure_mode(context, target_mode: str):
    """Switch modes safely and return the previous mode."""
    prev_mode = context.mode
    if prev_mode != target_mode:
        try:
            bpy.ops.object.mode_set(mode=target_mode)
        except Exception:
            # Some contexts may not allow mode changes (e.g. no active object)
            pass
    return prev_mode


# -------------------------------------------------------------------------
# Material cleanup
# -------------------------------------------------------------------------

class I3D_OT_ME_RemoveUnusedMaterials(bpy.types.Operator):
    bl_idname = "i3d.me_remove_unused_materials"
    bl_label = "Remove Unused Materials"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Remove unused material slots from all mesh objects in the scene (GamerDesigns / Modder’s Edge logic)."

    def execute(self, context):
        scene = context.scene
        cleaned_slots = 0
        removed_mats = 0

        # We remove:
        # 1) Material slots on mesh objects that are not referenced by any face.
        # 2) Orphan materials in bpy.data.materials with users == 0 (no fake user, not linked).
        prev_mode = _ensure_mode(context, 'OBJECT')
        try:
            # 1) Strip unused material slots per object
            for obj in scene.objects:
                if obj.type != 'MESH':
                    continue

                mesh = obj.data
                if mesh is None:
                    continue

                # Face-used material indices
                used_indices = set()
                try:
                    used_indices = {p.material_index for p in mesh.polygons}
                except Exception:
                    used_indices = set()

                slot_count = len(obj.material_slots)
                if slot_count == 0:
                    continue

                # Any slot index not referenced by faces is considered unused.
                unused_indices = [i for i in range(slot_count) if i not in used_indices]
                if not unused_indices:
                    continue

                # Pop from highest -> lowest to avoid index shifting problems.
                for idx in sorted(unused_indices, reverse=True):
                    try:
                        mesh.materials.pop(index=idx)
                        cleaned_slots += 1
                    except Exception:
                        # Keep going; some slots/materials may be protected/linked/etc.
                        pass

            # 2) Remove orphan materials from the file (no users, no fake user, not linked)
            orphan_mats = []
            try:
                orphan_mats = [m for m in bpy.data.materials if m is not None and m.users == 0 and m.library is None]
            except Exception:
                orphan_mats = []

            for mat in orphan_mats:
                try:
                    # Disable Fake User so cleanup can delete 0-user materials.
                    if getattr(mat, "use_fake_user", False):
                        mat.use_fake_user = False
                    bpy.data.materials.remove(mat, do_unlink=True)
                    removed_mats += 1
                except Exception:
                    pass

        finally:
            _ensure_mode(context, prev_mode)

        if cleaned_slots == 0 and removed_mats == 0:
            self.report({'INFO'}, "Removed 0 unused material slots; deleted 0 orphan materials")
        else:
            self.report({'INFO'}, f"Removed {cleaned_slots} unused material slots; deleted {removed_mats} orphan materials")
        return {'FINISHED'}
class I3D_OT_ME_VertexCleanup(bpy.types.Operator):
    bl_idname = "i3d.me_vertex_cleanup"
    bl_label = "Vertex Cleanup"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Delete loose geometry and merge by distance on selected mesh objects (GamerDesigns / Modder’s Edge logic)."

    merge_distance: bpy.props.FloatProperty(
        name="Merge Distance",
        default=0.0001,
        min=0.0,
        max=1.0
    )

    def execute(self, context):
        objs = _active_mesh_objects(context)
        if not objs:
            self.report({'WARNING'}, "No mesh objects selected.")
            return {'CANCELLED'}

        prev_active = context.view_layer.objects.active
        prev_mode = context.mode

        try:
            for o in objs:
                try:
                    context.view_layer.objects.active = o
                    _ensure_mode(context, "EDIT")
                    bpy.ops.mesh.select_all(action='SELECT')
                    bpy.ops.mesh.delete_loose()
                    # Blender renamed this operator; keep both for compatibility.
                    try:
                        bpy.ops.mesh.remove_doubles(distance=self.merge_distance)
                    except Exception:
                        bpy.ops.mesh.merge_by_distance(distance=self.merge_distance)
                    _ensure_mode(context, "OBJECT")
                except Exception:
                    # Keep going for the rest
                    try:
                        _ensure_mode(context, "OBJECT")
                    except Exception:
                        pass
                    continue
        finally:
            # restore
            try:
                context.view_layer.objects.active = prev_active
            except Exception:
                pass
            _ensure_mode(context, prev_mode)

        self.report({'INFO'}, f"Cleaned vertices on {len(objs)} object(s).")
        return {'FINISHED'}


# -------------------------------------------------------------------------
# Better tris / quads
# -------------------------------------------------------------------------

class I3D_OT_ME_BetterTris(bpy.types.Operator):
    bl_idname = "i3d.me_better_tris"
    bl_label = "Better Tris / Quads"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Convert tris to quads on selected mesh objects (GamerDesigns / Modder’s Edge logic)."

    convert_to_quads: bpy.props.BoolProperty(
        name="Convert to Quads",
        default=True
    )

    def execute(self, context):
        objs = _active_mesh_objects(context)
        if not objs:
            self.report({'WARNING'}, "No mesh objects selected.")
            return {'CANCELLED'}

        prev_active = context.view_layer.objects.active
        prev_mode = context.mode

        try:
            for o in objs:
                try:
                    context.view_layer.objects.active = o
                    _ensure_mode(context, "EDIT")
                    if self.convert_to_quads:
                        bpy.ops.mesh.tris_convert_to_quads()
                    _ensure_mode(context, "OBJECT")
                except Exception:
                    try:
                        _ensure_mode(context, "OBJECT")
                    except Exception:
                        pass
                    continue
        finally:
            try:
                context.view_layer.objects.active = prev_active
            except Exception:
                pass
            _ensure_mode(context, prev_mode)

        self.report({'INFO'}, f"Processed {len(objs)} object(s).")
        return {'FINISHED'}


# -------------------------------------------------------------------------
# UV tools
# -------------------------------------------------------------------------

def _ensure_edit_mesh(context) -> bool:
    obj = context.active_object
    return bool(obj and obj.type == 'MESH' and context.mode == 'EDIT_MESH')


class I3D_OT_ME_UV_UnwrapAngleBased(bpy.types.Operator):
    bl_idname = "i3d.me_uv_unwrap_angle_based"
    bl_label = "Unwrap (Angle Based)"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Run UV Unwrap (Angle Based) in Edit Mode (GamerDesigns / Modder’s Edge logic)."

    margin: bpy.props.FloatProperty(
        name="Margin",
        description="UV island margin (Blender Unwrap)",
        default=0.001,
        min=0.0,
        max=1.0,
        precision=4,
        step=0.01
    )

    def execute(self, context):
        if not _ensure_edit_mesh(context):
            self.report({'WARNING'}, "Switch to Edit Mode on a mesh to unwrap UVs.")
            return {'CANCELLED'}

        try:
            bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=self.margin)
        except Exception as e:
            self.report({'ERROR'}, f"Unwrap failed: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}


class I3D_OT_ME_UV_SmartProject005(bpy.types.Operator):
    bl_idname = "i3d.me_uv_smart_project_005"
    bl_label = "Smart UV Project (0.005)"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Run Smart UV Project with island margin 0.005 in Edit Mode (GamerDesigns / Modder’s Edge logic)."

    island_margin: bpy.props.FloatProperty(
        name="Island Margin",
        description="Island margin for Smart UV Project",
        default=0.005,
        min=0.0,
        max=1.0,
        precision=4,
        step=0.01
    )

    def execute(self, context):
        if not _ensure_edit_mesh(context):
            self.report({'WARNING'}, "Switch to Edit Mode on a mesh to run Smart UV Project.")
            return {'CANCELLED'}

        try:
            bpy.ops.uv.smart_project(island_margin=self.island_margin)
            return {'FINISHED'}
        except Exception:
            # Fallback: open the options window
            try:
                bpy.ops.uv.smart_project('INVOKE_DEFAULT')
                return {'FINISHED'}
            except Exception as e:
                self.report({'ERROR'}, f"Smart UV Project failed: {e}")
                return {'CANCELLED'}



# -------------------------------------------------------------------------
# Material Replace (A -> B)
# -------------------------------------------------------------------------

class I3D_OT_ME_MaterialReplaceBatch(bpy.types.Operator):
    bl_idname = "i3d.me_material_replace_batch"
    bl_label = "Replace Material A → B"
    bl_description = "Replaces every use of Material A with Material B on the selected objects."
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = getattr(context.scene, "I3D_UIexportSettings", None)
        if settings is None:
            self.report({'WARNING'}, "I3D export settings not available.")
            return {'CANCELLED'}

        from_name = getattr(settings, "me_replace_from", "NONE")
        to_name = getattr(settings, "me_replace_to", "NONE")
        scope = getattr(settings, "me_replace_scope", "SELECTED")

        if not from_name or from_name == "NONE" or not to_name or to_name == "NONE":
            self.report({'WARNING'}, "Choose both 'From' and 'To' materials.")
            return {'CANCELLED'}

        if from_name == to_name:
            self.report({'WARNING'}, "From and To are the same.")
            return {'CANCELLED'}

        from_mat = bpy.data.materials.get(from_name)
        to_mat = bpy.data.materials.get(to_name)
        if not from_mat or not to_mat:
            self.report({'WARNING'}, "Material not found.")
            return {'CANCELLED'}

        if scope == "ALL":
            objs = [o for o in bpy.data.objects if o.type == 'MESH']
        else:
            objs = [o for o in (context.selected_objects or []) if o.type == 'MESH']

        changed_slots = 0
        changed_objs = 0

        for obj in objs:
            if not obj.material_slots:
                continue
            obj_changed = False
            for slot in obj.material_slots:
                if slot.material == from_mat:
                    slot.material = to_mat
                    changed_slots += 1
                    obj_changed = True
            if obj_changed:
                changed_objs += 1

        self.report({'INFO'}, f"Replaced on {changed_objs} object(s), {changed_slots} slot(s).")
        return {'FINISHED'}


classes = (
    I3D_OT_ME_RemoveUnusedMaterials,
    I3D_OT_ME_MaterialReplaceBatch,
    I3D_OT_ME_VertexCleanup,
    I3D_OT_ME_BetterTris,
    I3D_OT_ME_UV_UnwrapAngleBased,
    I3D_OT_ME_UV_SmartProject005,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
