"""Blender Panel for the UV Editor for moving selected UVs to predefined GIANTS vehicle array UDIM locations"""


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

# TODO improvements
# - improve uv selection / prevent moving if not all connected vertices are selected
# - increase default panel width
# - more compact grid
#   - e.g. icons clickable remove buttons
#   - less padding
# - group materials by type

print(__file__)

from pathlib import Path

import bpy
import mathutils
import math
import bpy.utils.previews

class I3D_OT_VehicleArrayPanel( bpy.types.Panel ):
    """ GUI Panel for the GIANTS I3D TOOLS visible in the UV Editor """

    bl_idname       = "I3D_PT_VehicleArray"
    bl_label        = "Vehicle Material Array Tool"
    bl_space_type   = 'IMAGE_EDITOR'
    bl_region_type  = 'UI'
    bl_category     = "GIANTS I3D Exporter"

    def draw(self, context):
        layout = self.layout

        # variable number of colums based on panel width
        cell_w = 128
        num_cols = int(max(1, context.region.width / cell_w))

        # contains icons
        pcoll = preview_collections["vehicleMaterialIcons"]

        boxMats = layout.box()
        boxMats.label(text="Materials")
        gridMats = boxMats.grid_flow(columns=num_cols, row_major=True, even_columns=True, even_rows=True)

        boxColors = layout.box()
        boxColors.label(text="Color Masks")
        gridColor = boxColors.grid_flow(columns=num_cols, row_major=True, even_columns=True, even_rows=True)

        for int_key, (desc, _, _) in material_id_to_uvs.items():
            if int_key < 60:
                boxMat = gridMats.box()
                props = boxMat.operator("uv.move_to_vehicle_array", text=f"{desc}")
                props.material_id = int_key

                # add icon
                my_icon = pcoll.get(f"{int_key}", None)
                if my_icon != None:
                    boxMat.template_icon(icon_value=my_icon.icon_id, scale=5)
            else:
                props = gridColor.operator("uv.move_to_vehicle_array", text=f"{desc}")
                props.material_id = int_key



class UV_OP_moveToVehicleArray( bpy.types.Operator ):
    """Move selected UVs to a specified UV UDIM of the vehicle array"""
    bl_idname = "uv.move_to_vehicle_array"
    bl_label = "Move selected UVs"
    bl_options = {'UNDO'}

    material_id: bpy.props.IntProperty(
        name='Material ID',
        description='Material Id',
        default=0,
        min=0,
        max=128,
    )

    @classmethod
    def poll(cls, context):
        #return of the operator can run
        return True

    def execute(self, context):
        # retrieve uv space for material id
        (_, uv, _) = material_id_to_uvs.get(self.material_id, None)

        if uv is None:
            self.drawError(f"No UV space coordinates defined for material {self.material_id}")
            return {"CANCELLED"}

        # self.report({'INFO'}, "Operator executed")
        return self.moveUvsTo(*uv)

    def moveUvsTo(self, u, v):
        targetGridVec = mathutils.Vector((u, v))

        # based on https://blender.stackexchange.com/questions/3532/obtain-uv-selection-in-python/3537#3537
        # UV data is accessible only in object mode
        prev_mode = bpy.context.object.mode
        bpy.ops.object.mode_set(mode='OBJECT')

        # Load the objects edit-mode data into the object data
        bpy.context.object.update_from_editmode()
        uv_map = bpy.context.object.data.uv_layers.active

        selected_uv_loops = []
        for uvloop in uv_map.data:
            if uvloop.select:
                selected_uv_loops.append(uvloop)

        # if bpy.context.scene.tool_settings.use_uv_select_sync is selected, the uvloop.select is always false.
        # in this case we loop over all selected triangles and append corresponding uv_map.data[loop_index]
        if not selected_uv_loops:
            me = bpy.context.object.data
            me.calc_loop_triangles()
            uv_loop_added = []
            for tri in me.loop_triangles:
                all_corners_sel = True
                for i in range(3):
                    vert_index = tri.vertices[i]
                    if not me.vertices[vert_index].select:
                        all_corners_sel = False
                if all_corners_sel:
                    for i in range(3):
                        loop_index = tri.loops[i]
                        if not loop_index in uv_loop_added:
                            selected_uv_loops.append(uv_map.data[loop_index])
                            uv_loop_added.append(loop_index)

        if not selected_uv_loops:
            self.drawError("No UVs selected")
            bpy.ops.object.mode_set(mode=prev_mode)
            return {"CANCELLED"}

        # determinte current grid location / integer block based on average of selected uv coords
        centerU = (sum(uvloop.uv[0] for uvloop in selected_uv_loops)) / len(selected_uv_loops)
        centerV = (sum(uvloop.uv[1] for uvloop in selected_uv_loops)) / len(selected_uv_loops)
        currentGridVec = mathutils.Vector((math.floor(centerU), math.floor(centerV)))

        # vector to apply to existing UVs to move to target
        offsetVec = targetGridVec - currentGridVec

        # only update coordinates if target is different from current location
        if offsetVec.length == 0.0:
            bpy.ops.object.mode_set(mode=prev_mode)
            return {"FINISHED"}

        # check if affected UV coords are within one resp the current grid
        minU, maxU, minV, maxV = currentGridVec[0], currentGridVec[0] + 1, currentGridVec[1], currentGridVec[1] + 1
        for uvloop in selected_uv_loops:
            u, v = uvloop.uv
            if u < minU or u > maxU or v < minV or v > maxV:
                self.drawError("Selected vertices are not within a single integer block / UDIM")
                bpy.ops.object.mode_set(mode=prev_mode)
                return {"CANCELLED"}

        for uv_loop in selected_uv_loops:
            uv_loop.uv += offsetVec
        print(f"moved {len(selected_uv_loops)} uv vertices")

        # Restore whatever mode the object is in previously
        bpy.ops.object.mode_set(mode=prev_mode)
        return {"FINISHED"}

    def drawError(self, message):
        def draw(self, context):
            self.layout.label(text=message)
        bpy.context.window_manager.popup_menu(draw, title = "Error", icon = 'ERROR')


material_icons_dir = Path(__file__).parent / "icons/"
preview_collections = {}

material_id_to_uvs = {
    #ID     # Button Text               # UV UDIM       # icon name
     0 :    ("Painted Metal",           (0,  0),        '_00_.png'),
     1 :    ('Painted Plastic',         (1,  0),        '_01_.png'),
     2 :    ('Chrome',                  (2,  0),        '_02_.png'),
     3 :    ('Copper',                  (3,  0),        '_03_.png'),
     4 :    ('Galvanized Metal',        (4,  0),        '_04_.png'),
     5 :    ('Rubber',                  (5,  0),        '_05_.png'),
     6 :    ('Painted Metal Old',       (6,  0),        '_06_.png'),
     7 :    ('Fabric',                  (7,  0),        '_07_.png'),
     8 :    ('Silver Scratched',        (0,  1),        '_08_.png'),
     9 :    ('Silver Bumpy',            (1,  1),        '_09_.png'),
    10 :    ('Fabric',                  (2,  1),        '_10_.png'),
    11 :    ('Fabric',                  (3,  1),        '_11_.png'),
    12 :    ('Leather',                 (4,  1),        '_12_.png'),
    13 :    ('Leather',                 (5,  1),        '_13_.png'),
    14 :    ('Wood',                    (6,  1),        '_14_.png'),
    15 :    ('Dirt',                    (7,  1),        '_15_.png'),
    16 :    ('Painted Metal Black',     (0,  2),        '_16_.png'),
    17 :    ('Painted Plastic',         (1,  2),        '_17_.png'),
    18 :    ('Silver Rough',            (2,  2),        '_18_.png'),
    19 :    ('Brass Scratched',         (3,  2),        '_19_.png'),
    20 :    ('Reflector White',         (4,  2),        '_20_.png'),
    21 :    ('Reflector Red',           (5,  2),        '_21_.png'),
    22 :    ('Reflector Yellow',        (6,  2),        '_22_.png'),
    23 :    ('Reflector Daylight',      (7,  2),        '_23_.png'),
    24 :    ('Gear-Stick Plastic',      (0,  3),        '_24_.png'),
    25 :    ('Leather',                 (1,  3),        '_25_.png'),
    26 :    ('Perforated Plastic',      (2,  3),        '_26_.png'),
    27 :    ('Glass Clear',             (3,  3),        '_27_.png'),
    28 :    ('Glass Square',            (4,  3),        '_28_.png'),
    29 :    ('Glass Line',              (5,  3),        '_29_.png'),
    30 :    ('Palladium',               (6,  3),        '_30_.png'),
    31 :    ('Bronze',                  (7,  3),        '_31_.png'),
    32 :    ('Graphite Black',          (0,  4),        '_32_.png'),
    33 :    ('Half Metal Black',        (1,  4),        '_33_.png'),
    34 :    ('Gray Plastic',            (2,  4),        '_34_.png'),
    35 :    ('Gold',                    (3,  4),        '_35_.png'),
    36 :    ('Rough Metal Painted',     (4,  4),        '_36_.png'),
    37 :    ('Perforated',              (5,  4),        '_37_.png'),
    38 :    ('Fell',                    (6,  4),        '_38_.png'),
    39 :    ('Metal Ground',            (7,  4),        '_39_.png'),
    40 :    ('Shiny Car Paint',         (0,  5),        '_40_.png'),
    41 :    ('Fabric',                  (1,  5),        '_41_.png'),
    42 :    ('Wood',                    (2,  5),        '_42_.png'),
    43 :    ('Silver Scratch Shiny',    (3,  5),        '_43_.png'),
    44 :    ('Reflector Yellow',        (4,  5),        '_44_.png'),
    45 :    ('Circular Brushed',        (5,  5),        '_45_.png'),

    60 :    ('Color 0',                (0, -1),        None),
    61 :    ('Color 1',                (1, -1),        None),
    62 :    ('Color 2',                (2, -1),        None),
    63 :    ('Color 3',                (3, -1),        None),
    64 :    ('Color 4',                (4, -1),        None),
    65 :    ('Color 5',                (5, -1),        None),
    66 :    ('Color 6',                (6, -1),        None),
    67 :    ('Color 7',                (7, -1),        None),
    70 :    ('Blinking 0',                (0, -2),        None),
    71 :    ('Blinking 1',                (1, -2),        None),
    72 :    ('Blinking 2',                (2, -2),        None),
    73 :    ('Blinking 3',                (3, -2),        None),
    74 :    ('Blinking 4',                (4, -2),        None),
    75 :    ('Blinking 5',                (5, -2),        None),
    76 :    ('Blinking 6',                (6, -2),        None),
    77 :    ('Blinking 7',                (7, -2),        None),
}


classes = [
    I3D_OT_VehicleArrayPanel,
    UV_OP_moveToVehicleArray,
]

def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except:
            pass

    # load icons for materials
    pcoll = bpy.utils.previews.new()

    for mat_id, (_, _, image_name) in material_id_to_uvs.items():
        if image_name != None:
            pcoll.load(f"{mat_id}", f"{material_icons_dir}/{image_name}", 'IMAGE')

    preview_collections["vehicleMaterialIcons"] = pcoll


def unregister():
    # unload icons
    for pcoll in preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    preview_collections.clear()

    for cls in classes:
        try:
            bpy.utils.unregister_class(cls)
        except:
            pass
