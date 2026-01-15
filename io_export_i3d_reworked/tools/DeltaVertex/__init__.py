# Delta Vertex Color Tool (FS25 / Blender 4–5 safe)
# Supports automatic creation of "Delta Shapekey" like the original tool.

import bpy
import bmesh
from mathutils import Vector


def delta_to_vcolor(self, context):
    obj = context.active_object

    if obj is None or obj.type != 'MESH':
        self.report({'ERROR'}, "Active object must be a mesh.")
        return

    mesh = obj.data

    # Validate shape keys
    shape_keys = mesh.shape_keys
    key_blocks = shape_keys.key_blocks if shape_keys else None

    # ---------------------------------------
    # CASE 1 — No shapekeys → auto-create pair
    # ---------------------------------------
    if shape_keys is None:
        obj.shape_key_add(name="Basis", from_mix=False)
        obj.shape_key_add(name="Delta Shapekey", from_mix=False)
        obj.active_shape_key_index = 1

        self.report(
            {'INFO'},
            "Created 'Basis' + 'Delta Shapekey'. Edit the Delta Shapekey in Edit Mode, then run Bake again."
        )
        return

    # Only Basis exists → create Delta Shapekey
    if len(key_blocks) == 1:
        obj.shape_key_add(name="Delta Shapekey", from_mix=False)
        obj.active_shape_key_index = 1
        self.report(
            {'INFO'},
            "Created 'Delta Shapekey'. Edit it in Edit Mode, then run Bake again."
        )
        return

    # ---------------------------------------
    # CASE 2 — Find target shapekey
    # ---------------------------------------
    basis_key = key_blocks[0]
    target_key = None

    # If active key is Basis, force user to select Delta
    if obj.active_shape_key_index == 0:
        # Use Delta Shapekey if it exists
        if "Delta Shapekey" in key_blocks:
            target_key = key_blocks["Delta Shapekey"]
            obj.active_shape_key_index = target_key.index
        else:
            self.report(
                {'ERROR'},
                "Select the shapekey you want to bake deltas from."
            )
            return
    else:
        target_key = key_blocks[obj.active_shape_key_index]

    if target_key is None:
        self.report({'ERROR'}, "Could not determine target Shape Key.")
        return

    # ---------------------------------------
    # Store original shapekey values to restore later
    # ---------------------------------------
    original_values = {kb.name: kb.value for kb in key_blocks}

    try:
        # Zero all keys, set only target to 1
        for kb in key_blocks:
            kb.value = 0.0
        target_key.value = 1.0

        # ---- Get evaluated mesh (Blender 5 compatible) ----
        depsgraph = context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(depsgraph)
        mesh_eval = obj_eval.to_mesh()

        # Basis vertex positions
        base_positions = [v.co.copy() for v in mesh.vertices]

        # Compute deltas
        delta_vectors = []
        for idx, v in enumerate(mesh_eval.vertices):
            base_co = base_positions[idx]
            delta = v.co - base_co

            # Clamp to [-1..1]
            delta.x = max(min(delta.x, 1.0), -1.0)
            delta.y = max(min(delta.y, 1.0), -1.0)
            delta.z = max(min(delta.z, 1.0), -1.0)

            # Convert to [0..1]
            delta = (delta * 0.5) + Vector((0.5, 0.5, 0.5))

            # Reorder for the FS22 snowheap format
            x = delta.x
            y = 1.0 - delta.y
            z = delta.z

            delta_vec = Vector((x, z, y, 1.0))
            delta_vectors.append(delta_vec)

        # ---- Write vertex colors to ORIGINAL mesh ----
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()

        color_layer = bm.loops.layers.color.get("Delta Vector Colors")
        if color_layer is None:
            color_layer = bm.loops.layers.color.new("Delta Vector Colors")
            self.report({'INFO'}, "Created vertex color layer 'Delta Vector Colors'.")

        for face in bm.faces:
            for loop in face.loops:
                loop[color_layer] = delta_vectors[loop.vert.index]

        bm.to_mesh(mesh)
        mesh.update()
        bm.free()

        self.report({'INFO'}, "Delta Vertex Colors baked successfully.")
        print("Delta Vertex Colors baked successfully.")

    finally:
        try:
            obj_eval.to_mesh_clear()
        except:
            pass

        # Restore all shapekey values
        for kb in key_blocks:
            kb.value = original_values[kb.name]


# -------------------------------------------------------------------------
# Operator
# -------------------------------------------------------------------------

class deltatovcolor(bpy.types.Operator):
    bl_idname = "mesh.deltatovcolor"
    bl_label = "Bake Delta Positions"
    bl_description = "Creates or bakes delta shapekey into vertex color."
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        delta_to_vcolor(self, context)
        return {'FINISHED'}


# -------------------------------------------------------------------------
# Mesh Data Panel
# -------------------------------------------------------------------------

class I3D_DELTAVERTEXCOLORS_PT_scenepanel(bpy.types.Panel):
    bl_label = "Bake Position Delta to Vertex Color"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "data"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "MESH"

    def draw(self, context):
        from ...i3d_ui import _flash_state
        layout = self.layout

        # Create flashing box
        box = layout.box()

        # Flash red when triggered
        if _flash_state:
            box.alert = True

        row = box.row()
        row.operator("mesh.deltatovcolor", text="Bake Deltas to Vertex Colors")



# -------------------------------------------------------------------------
# Registration
# -------------------------------------------------------------------------

classes = (
    deltatovcolor,
    I3D_DELTAVERTEXCOLORS_PT_scenepanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
