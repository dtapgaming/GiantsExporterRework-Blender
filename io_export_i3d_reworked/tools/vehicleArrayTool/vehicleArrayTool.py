"""FS25 Vehicle UV Array Tool for Blender 4.0+ and 5.x
Fully rewritten with:
- MANUAL material_id_to_uvs dictionary
- Pre-filled coordinate-based FS25 UV slots
- BMESH UV selection (correct for Blender 4+)
- Compass nudge tools
- Clean collapsible UI boxes
"""

# ##### BEGIN GPL LICENSE BLOCK #####
# Licensed under GPLv2 or later
# ##### END GPL LICENSE BLOCK #####

print(__file__)

import bpy
import bmesh
import mathutils
import math

# ------------------------------------------------------------------------------
# ERROR POPUP
# ------------------------------------------------------------------------------

def draw_error(msg: str):
    def draw(self, context):
        self.layout.label(text=msg)
    bpy.context.window_manager.popup_menu(draw, title="Error", icon='ERROR')


# ------------------------------------------------------------------------------
# BMESH UV SELECTION HELPERS — Blender 4/5 COMPATIBLE
# ------------------------------------------------------------------------------

def get_selected_uvs(obj):
    """Return (bm, uv_layer, list_of_(loop,luv)) safely via BMESH."""
    if obj.mode != 'EDIT':
        bpy.ops.object.mode_set(mode='EDIT')

    me = obj.data
    bm = bmesh.from_edit_mesh(me)
    uv_layer = bm.loops.layers.uv.verify()

    selected = []
    sync = bpy.context.tool_settings.use_uv_select_sync

    if sync:
        # UV selection = face selection
        for face in bm.faces:
            if face.select:
                for loop in face.loops:
                    luv = loop[uv_layer]
                    selected.append((loop, luv))
    else:
        # True UV selection
        for face in bm.faces:
            for loop in face.loops:
                luv = loop[uv_layer]
                if luv.select:
                    selected.append((loop, luv))

    return bm, uv_layer, selected


# ------------------------------------------------------------------------------
# OPERATOR — MOVE UVs TO A SPECIFIC FS25 SLOT
# ------------------------------------------------------------------------------

class UV_OP_moveToVehicleArray(bpy.types.Operator):
    bl_idname = "uv.move_to_vehicle_array"
    bl_label  = "Move UVs to FS25 Slot"
    bl_options = {'UNDO'}

    material_id: bpy.props.IntProperty()

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'MESH'

    def execute(self, context):
        item = material_id_to_uvs.get(self.material_id)
        if not item:
            draw_error("Invalid slot ID.")
            return {'CANCELLED'}

        _, (tx, ty), _ = item
        return self._move_to_tile(tx, ty)

    def _move_to_tile(self, tx, ty):
        obj = bpy.context.object
        bm, uv_layer, selected = get_selected_uvs(obj)

        if not selected:
            draw_error("No UVs selected.")
            return {'CANCELLED'}

        # Average coord to find current tile
        cu = sum(luv.uv.x for _, luv in selected) / len(selected)
        cv = sum(luv.uv.y for _, luv in selected) / len(selected)

        cur_tile = mathutils.Vector((math.floor(cu), math.floor(cv)))
        tgt_tile = mathutils.Vector((tx, ty))
        offset = tgt_tile - cur_tile

        # Safety: all must be within 1 tile
        for _, luv in selected:
            if not (cur_tile.x <= luv.uv.x <= cur_tile.x+1 and
                    cur_tile.y <= luv.uv.y <= cur_tile.y+1):
                draw_error("UVs span multiple tiles — cannot move.")
                return {'CANCELLED'}

        # Apply
        for _, luv in selected:
            luv.uv += offset

        bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}


# ------------------------------------------------------------------------------
# OPERATOR — COMPASS / NUDGE MOVEMENT
# ------------------------------------------------------------------------------

class UV_OP_moveVehicleArrayNudge(bpy.types.Operator):
    bl_idname = "uv.move_vehicle_array_nudge"
    bl_label  = "Nudge UV Tile"
    bl_options = {'UNDO'}

    dx: bpy.props.IntProperty(default=0)
    dy: bpy.props.IntProperty(default=0)

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'MESH'

    def execute(self, context):
        obj = bpy.context.object
        bm, uv_layer, selected = get_selected_uvs(obj)

        if not selected:
            draw_error("No UVs selected.")
            return {'CANCELLED'}

        cu = sum(luv.uv.x for _, luv in selected) / len(selected)
        cv = sum(luv.uv.y for _, luv in selected) / len(selected)
        cur_tile = mathutils.Vector((math.floor(cu), math.floor(cv)))
        tgt_tile = cur_tile + mathutils.Vector((self.dx, self.dy))
        offset = tgt_tile - cur_tile

        # Check that selection does not span multiple tiles
        for _, luv in selected:
            if not (cur_tile.x <= luv.uv.x <= cur_tile.x+1 and
                    cur_tile.y <= luv.uv.y <= cur_tile.y+1):
                draw_error("UVs span multiple tiles — cannot nudge.")
                return {'CANCELLED'}

        for _, luv in selected:
            luv.uv += offset

        bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}


# ------------------------------------------------------------------------------
# SETTINGS FOR COLLAPSIBLE UI
# ------------------------------------------------------------------------------

class I3D_VehicleArraySettings(bpy.types.PropertyGroup):
    show_lights:      bpy.props.BoolProperty(name="Lights",        default=False)
    show_wet:         bpy.props.BoolProperty(name="Wet",           default=False)
    show_dry:         bpy.props.BoolProperty(name="Dry",           default=False)
    show_wet_no_snow: bpy.props.BoolProperty(name="Wet No Snow",   default=False)
    show_dry_no_snow: bpy.props.BoolProperty(name="Dry No Snow",   default=False)
    show_manual:      bpy.props.BoolProperty(name="Manual Move",   default=True)

    # Show-more toggles (category specific)
    show_more_wet:         bpy.props.BoolProperty(default=False)
    show_more_dry:         bpy.props.BoolProperty(default=False)
    show_more_wet_no_snow: bpy.props.BoolProperty(default=False)
    show_more_dry_no_snow: bpy.props.BoolProperty(default=False)


# ------------------------------------------------------------------------------
# OPERATOR — TOGGLE SHOW MORE / LESS
# ------------------------------------------------------------------------------

class I3D_OT_ToggleShowMore(bpy.types.Operator):
    bl_idname = "i3d.toggle_show_more"
    bl_label = "Toggle Show More"

    target: bpy.props.StringProperty()
    state: bpy.props.BoolProperty()

    def execute(self, context):
        settings = context.scene.i3d_vehicle_array_settings
        if hasattr(settings, self.target):
            setattr(settings, self.target, self.state)
        return {'FINISHED'}


# ------------------------------------------------------------------------------
# UI PANEL
# ------------------------------------------------------------------------------
class I3D_OT_VehicleArrayPanel(bpy.types.Panel):
    bl_idname = "I3D_PT_VehicleArray"
    bl_label = "UV MAPPING TOOL (FS25)"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "GIANTS I3D Exporter REWORKED"

    def draw_header_section(self, box, prop, text, icon='NONE'):
        s = bpy.context.scene.i3d_vehicle_array_settings
        expanded = getattr(s, prop)
        row = box.row()
        row.prop(s, prop, text="", emboss=False,
                 icon='TRIA_DOWN' if expanded else 'TRIA_RIGHT')
        row.label(text=text, icon=icon)

    def draw_slot_buttons(self, layout, id_list, num_cols, show_more_prop=None):
        s = bpy.context.scene.i3d_vehicle_array_settings

        # Determine which IDs to show based on the show-more flag
        if show_more_prop is not None:
            show_more = getattr(s, show_more_prop)
            display_ids = id_list if show_more else id_list[:16]
        else:
            display_ids = id_list

        # ROW-MAJOR ordering (Left → Right, then next row)
        flow = layout.grid_flow(columns=num_cols, even_columns=True, even_rows=True)
        for mid in display_ids:
            label, (x, y), _ = material_id_to_uvs[mid]
            op = flow.operator("uv.move_to_vehicle_array", text=label)
            op.material_id = mid

        # Show More / Show Less button
        if show_more_prop is not None and len(id_list) > 16:
            row = layout.row()
            show_more = getattr(s, show_more_prop)
            if show_more:
                op = row.operator("i3d.toggle_show_more", text="Show Less")
                op.target = show_more_prop
                op.state = False
            else:
                op = row.operator("i3d.toggle_show_more", text="Show More")
                op.target = show_more_prop
                op.state = True

    def draw(self, context):
        layout = self.layout
        s = context.scene.i3d_vehicle_array_settings
        # Fixed grid layout (4 columns) for predictable button rows
        num_cols = 4

        # Lights (no Show More/Show Less, only 16)
        box = layout.box()
        self.draw_header_section(box, "show_lights", "Lights", icon='LIGHT')
        if s.show_lights:
            self.draw_slot_buttons(box, LIGHT_IDS, num_cols)

        # Wet
        box = layout.box()
        self.draw_header_section(box, "show_wet", "Wet", icon='MOD_OCEAN')
        if s.show_wet:
            self.draw_slot_buttons(box, WET_IDS, num_cols, "show_more_wet")

        # Dry
        box = layout.box()
        self.draw_header_section(box, "show_dry", "Dry", icon='SHADING_SOLID')
        if s.show_dry:
            self.draw_slot_buttons(box, DRY_IDS, num_cols, "show_more_dry")

        # Wet No Snow
        box = layout.box()
        self.draw_header_section(box, "show_wet_no_snow", "Wet No Snow", icon='MOD_OCEAN')
        if s.show_wet_no_snow:
            self.draw_slot_buttons(box, WET_NS_IDS, num_cols, "show_more_wet_no_snow")

        # Dry No Snow
        box = layout.box()
        self.draw_header_section(box, "show_dry_no_snow", "Dry No Snow", icon='SHADING_SOLID')
        if s.show_dry_no_snow:
            self.draw_slot_buttons(box, DRY_NS_IDS, num_cols, "show_more_dry_no_snow")

        # Manual Move — Compass
        box = layout.box()
        self.draw_header_section(box, "show_manual", "Manual Move (1 Tile)", icon='ORIENTATION_NORMAL')
        if s.show_manual:
            col = box.column(align=True)

            # Up
            r = col.row(align=True)
            r.alignment = 'CENTER'
            op = r.operator("uv.move_vehicle_array_nudge", text="↑ Up")
            op.dx = 0; op.dy = 1

            # Left / Right
            r = col.row(align=True)
            op = r.operator("uv.move_vehicle_array_nudge", text="← Left")
            op.dx = -1; op.dy = 0

            op = r.operator("uv.move_vehicle_array_nudge", text="Right →")
            op.dx = 1; op.dy = 0

            # Down
            r = col.row(align=True)
            r.alignment = 'CENTER'
            op = r.operator("uv.move_vehicle_array_nudge", text="↓ Down")
            op.dx = 0; op.dy = -1


# ------------------------------------------------------------------------------
# REGISTRATION
# ------------------------------------------------------------------------------

classes = [
    I3D_VehicleArraySettings,
    I3D_OT_ToggleShowMore,
    I3D_OT_VehicleArrayPanel,
    UV_OP_moveToVehicleArray,
    UV_OP_moveVehicleArrayNudge,
]

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.i3d_vehicle_array_settings = bpy.props.PointerProperty(
        type=I3D_VehicleArraySettings)

def unregister():
    del bpy.types.Scene.i3d_vehicle_array_settings
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

material_id_to_uvs = {
    #ID     # Button Text               # UV UDIM       # icon name
    #Lights
     0 :    ("Default Light",                            (0,  0),           '_00_.png'),
     1 :    ('Default Light & HighBeam',                 (1,  0),           '_01_.png'),
     2 :    ('HighBeam',                                 (2,  0),           '_02_.png'),
     3 :    ('Bottom Light',                             (3,  0),           '_03_.png'),
     4 :    ('Top Light',                                (4,  0),           '_04_.png'),
     5 :    ('Daytime Running Light',                    (5,  0),           '_05_.png'),
     6 :    ('Turn Light Left',                          (6,  0),           '_06_.png'),
     7 :    ('Turn Light Right',                         (7,  0),           '_07_.png'),
     8 :    ('Back Light',                               (0,  1),           '_08_.png'),
     9 :    ('Brake Light',                              (1,  1),           '_09_.png'),
    10 :    ('Back & Brake Light',                       (2,  1),           '_10_.png'),
    11 :    ('Reverse Light',                            (3,  1),           '_11_.png'),
    12 :    ('Work Light Front',                         (4,  1),           '_12_.png'),
    13 :    ('Work Light Back',                          (5,  1),           '_13_.png'),
    14 :    ('Work Light Additional',                    (6,  1),           '_14_.png'),
    15 :    ('Work Light Additional 2',                  (7,  1),           '_15_.png'),
    #Wet UVs          
    100 :    ('Wet 1',                                    (0,  2),          None),
    101 :    ('Wet 2',                                    (1,  2),          None),
    102 :    ('Wet 3',                                    (2,  2),          None),
    103 :    ('Wet 4',                                    (3,  2),          None),
    104 :    ('Wet 5',                                    (4,  2),          None),
    105 :    ('Wet 6',                                    (5,  2),          None),
    106 :    ('Wet 7',                                    (6,  2),          None),
    107 :    ('Wet 8',                                    (7,  2),          None),
    108 :    ('Wet 9',                                    (0,  3),          None),
    109 :    ('Wet 10',                                   (1,  3),          None),
    110 :    ('Wet 11',                                   (2,  3),          None),
    111 :    ('Wet 12',                                   (3,  3),          None),
    112 :    ('Wet 13',                                   (4,  3),          None),
    113 :    ('Wet 14',                                   (5,  3),          None),
    114 :    ('Wet 15',                                   (6,  3),          None),
    115 :    ('Wet 16',                                   (7,  3),          None),
    116 :    ('Wet 17',                                   (0,  4),          None),
    117 :    ('Wet 18',                                   (1,  4),          None),
    118 :    ('Wet 19',                                   (2,  4),          None),
    119 :    ('Wet 20',                                   (3,  4),          None),
    120 :    ('Wet 21',                                   (4,  4),          None),
    121 :    ('Wet 22',                                   (5,  4),          None),
    122 :    ('Wet 23',                                   (6,  4),          None),
    123 :    ('Wet 24',                                   (7,  4),          None),
    124 :    ('Wet 25',                                   (0,  5),          None),
    125 :    ('Wet 26',                                   (1,  5),          None),
    126 :    ('Wet 27',                                   (2,  5),          None),
    127 :    ('Wet 28',                                   (3,  5),          None),
    128 :    ('Wet 29',                                   (4,  5),          None),
    129 :    ('Wet 30',                                   (5,  5),          None),
    130 :    ('Wet 31',                                   (6,  5),          None),
    131 :    ('Wet 32',                                   (7,  5),          None),
    132 :    ('Wet 33',                                   (0,  6),          None),
    133 :    ('Wet 34',                                   (1,  6),          None),
    134 :    ('Wet 35',                                   (2,  6),          None),
    135 :    ('Wet 36',                                   (3,  6),          None),
    136 :    ('Wet 37',                                   (4,  6),          None),
    137 :    ('Wet 38',                                   (5,  6),          None),
    138 :    ('Wet 39',                                   (6,  6),          None),
    139 :    ('Wet 40',                                   (7,  6),          None),
    140 :    ('Wet 41',                                   (0,  7),          None),
    141 :    ('Wet 42',                                   (1,  7),          None),
    142 :    ('Wet 43',                                   (2,  7),          None),
    143 :    ('Wet 44',                                   (3,  7),          None),
    144 :    ('Wet 45',                                   (4,  7),          None),
    145 :    ('Wet 46',                                   (5,  7),          None),
    146 :    ('Wet 47',                                   (6,  7),          None),
    147 :    ('Wet 48',                                   (7,  7),          None),
    148 :    ('Wet 49',                                   (0,  8),          None),
    149 :    ('Wet 50',                                   (1,  8),          None),
    150 :    ('Wet 51',                                   (2,  8),          None),
    151 :    ('Wet 52',                                   (3,  8),          None),
    152 :    ('Wet 53',                                   (4,  8),          None),
    153 :    ('Wet 54',                                   (5,  8),          None),
    154 :    ('Wet 55',                                   (6,  8),          None),
    155 :    ('Wet 56',                                   (7,  8),          None),
    #Dry UVs          
    200 :    ('Dry 1',                                    (0,  -1),         None),
    201 :    ('Dry 2',                                    (1,  -1),         None),
    202 :    ('Dry 3',                                    (2,  -1),         None),
    203 :    ('Dry 4',                                    (3,  -1),         None),
    204 :    ('Dry 5',                                    (4,  -1),         None),
    205 :    ('Dry 6',                                    (5,  -1),         None),
    206 :    ('Dry 7',                                    (6,  -1),         None),
    207 :    ('Dry 8',                                    (7,  -1),         None),
    208 :    ('Dry 9',                                    (0,  -2),         None),
    209 :    ('Dry 10',                                   (1,  -2),         None),
    210 :    ('Dry 11',                                   (2,  -2),         None),
    211 :    ('Dry 12',                                   (3,  -2),         None),
    212 :    ('Dry 13',                                   (4,  -2),         None),
    213 :    ('Dry 14',                                   (5,  -2),         None),
    214 :    ('Dry 15',                                   (6,  -2),         None),
    215 :    ('Dry 16',                                   (7,  -2),         None),
    216 :    ('Dry 17',                                   (0,  -3),         None),
    217 :    ('Dry 18',                                   (1,  -3),         None),
    218 :    ('Dry 19',                                   (2,  -3),         None),
    219 :    ('Dry 20',                                   (3,  -3),         None),
    220 :    ('Dry 21',                                   (4,  -3),         None),
    221 :    ('Dry 22',                                   (5,  -3),         None),
    222 :    ('Dry 23',                                   (6,  -3),         None),
    223 :    ('Dry 24',                                   (7,  -3),         None),
    224 :    ('Dry 25',                                   (0,  -4),         None),
    225 :    ('Dry 26',                                   (1,  -4),         None),
    226 :    ('Dry 27',                                   (2,  -4),         None),
    227 :    ('Dry 28',                                   (3,  -4),         None),
    228 :    ('Dry 29',                                   (4,  -4),         None),
    229 :    ('Dry 30',                                   (5,  -4),         None),
    230 :    ('Dry 31',                                   (6,  -4),         None),
    231 :    ('Dry 32',                                   (7,  -4),         None),
    232 :    ('Dry 33',                                   (0,  -5),         None),
    233 :    ('Dry 34',                                   (1,  -5),         None),
    234 :    ('Dry 35',                                   (2,  -5),         None),
    235 :    ('Dry 36',                                   (3,  -5),         None),
    236 :    ('Dry 37',                                   (4,  -5),         None),
    237 :    ('Dry 38',                                   (5,  -5),         None),
    238 :    ('Dry 39',                                   (6,  -5),         None),
    239 :    ('Dry 40',                                   (7,  -5),         None),
    240 :    ('Dry 41',                                   (0,  -6),         None),
    241 :    ('Dry 42',                                   (1,  -6),         None),
    242 :    ('Dry 43',                                   (2,  -6),         None),
    243 :    ('Dry 44',                                   (3,  -6),         None),
    244 :    ('Dry 45',                                   (4,  -6),         None),
    245 :    ('Dry 46',                                   (5,  -6),         None),
    246 :    ('Dry 47',                                   (6,  -6),         None),
    247 :    ('Dry 48',                                   (7,  -6),         None),
    248 :    ('Dry 49',                                   (0,  -7),         None),
    249 :    ('Dry 50',                                   (1,  -7),         None),
    250 :    ('Dry 51',                                   (2,  -7),         None),
    251 :    ('Dry 52',                                   (3,  -7),         None),
    252 :    ('Dry 53',                                   (4,  -7),         None),
    253 :    ('Dry 54',                                   (5,  -7),         None),
    254 :    ('Dry 55',                                   (6,  -7),         None),
    255 :    ('Dry 56',                                   (7,  -7),         None),
    #Dry UVs No Snow
    300 :    ('Dry No Snow 1',                            (-1,  -1),        None),
    301 :    ('Dry No Snow 2',                            (-2,  -1),        None),
    302 :    ('Dry No Snow 3',                            (-3,  -1),        None),
    303 :    ('Dry No Snow 4',                            (-4,  -1),        None),
    304 :    ('Dry No Snow 5',                            (-5,  -1),        None),
    305 :    ('Dry No Snow 6',                            (-6,  -1),        None),
    306 :    ('Dry No Snow 7',                            (-7,  -1),        None),
    307 :    ('Dry No Snow 8',                            (-8,  -1),        None),
    308 :    ('Dry No Snow 9',                            (-1,  -2),        None),
    309 :    ('Dry No Snow 10',                           (-2,  -2),        None),
    310 :    ('Dry No Snow 11',                           (-3,  -2),        None),
    311 :    ('Dry No Snow 12',                           (-4,  -2),        None),
    312 :    ('Dry No Snow 13',                           (-5,  -2),        None),
    313 :    ('Dry No Snow 14',                           (-6,  -2),        None),
    314 :    ('Dry No Snow 15',                           (-7,  -2),        None),
    315 :    ('Dry No Snow 16',                           (-8,  -2),        None),
    316 :    ('Dry No Snow 17',                           (-1,  -3),        None),
    317 :    ('Dry No Snow 18',                           (-2,  -3),        None),
    318 :    ('Dry No Snow 19',                           (-3,  -3),        None),
    319 :    ('Dry No Snow 20',                           (-4,  -3),        None),
    320 :    ('Dry No Snow 21',                           (-5,  -3),        None),
    321 :    ('Dry No Snow 22',                           (-6,  -3),        None),
    322 :    ('Dry No Snow 23',                           (-7,  -3),        None),
    323 :    ('Dry No Snow 24',                           (-8,  -3),        None),
    324 :    ('Dry No Snow 25',                           (-1,  -4),        None),
    325 :    ('Dry No Snow 26',                           (-2,  -4),        None),
    326 :    ('Dry No Snow 27',                           (-3,  -4),        None),
    327 :    ('Dry No Snow 28',                           (-4,  -4),        None),
    328 :    ('Dry No Snow 29',                           (-5,  -4),        None),
    329 :    ('Dry No Snow 30',                           (-6,  -4),        None),
    330 :    ('Dry No Snow 31',                           (-7,  -4),        None),
    331 :    ('Dry No Snow 32',                           (-8,  -4),        None),
    332 :    ('Dry No Snow 33',                           (-1,  -5),        None),
    333 :    ('Dry No Snow 34',                           (-2,  -5),        None),
    334 :    ('Dry No Snow 35',                           (-3,  -5),        None),
    335 :    ('Dry No Snow 36',                           (-4,  -5),        None),
    336 :    ('Dry No Snow 37',                           (-5,  -5),        None),
    337 :    ('Dry No Snow 38',                           (-6,  -5),        None),
    338 :    ('Dry No Snow 39',                           (-7,  -5),        None),
    339 :    ('Dry No Snow 40',                           (-8,  -5),        None),
    340 :    ('Dry No Snow 41',                           (-1,  -6),        None),
    341 :    ('Dry No Snow 42',                           (-2,  -6),        None),
    342 :    ('Dry No Snow 43',                           (-3,  -6),        None),
    343 :    ('Dry No Snow 44',                           (-4,  -6),        None),
    344 :    ('Dry No Snow 45',                           (-5,  -6),        None),
    345 :    ('Dry No Snow 46',                           (-6,  -6),        None),
    346 :    ('Dry No Snow 47',                           (-7,  -6),        None),
    347 :    ('Dry No Snow 48',                           (-8,  -6),        None),
    348 :    ('Dry No Snow 49',                           (-1,  -7),        None),
    349 :    ('Dry No Snow 50',                           (-2,  -7),        None),
    350 :    ('Dry No Snow 51',                           (-3,  -7),        None),
    351 :    ('Dry No Snow 52',                           (-4,  -7),        None),
    352 :    ('Dry No Snow 53',                           (-5,  -7),        None),
    353 :    ('Dry No Snow 54',                           (-6,  -7),        None),
    354 :    ('Dry No Snow 55',                           (-7,  -7),        None),
    355 :    ('Dry No Snow 56',                           (-8,  -7),        None),
    #Wet UVs No Snow
    400 :    ('Wet No Snow 1',                            (-1,  2),         None),
    401 :    ('Wet No Snow 2',                            (-2,  2),         None),
    402 :    ('Wet No Snow 3',                            (-3,  2),         None),
    403 :    ('Wet No Snow 4',                            (-4,  2),         None),
    404 :    ('Wet No Snow 5',                            (-5,  2),         None),
    405 :    ('Wet No Snow 6',                            (-6,  2),         None),
    406 :    ('Wet No Snow 7',                            (-7,  2),         None),
    407 :    ('Wet No Snow 8',                            (-8,  2),         None),
    408 :    ('Wet No Snow 9',                            (-1,  3),         None),
    409 :    ('Wet No Snow 10',                           (-2,  3),         None),
    410 :    ('Wet No Snow 11',                           (-3,  3),         None),
    411 :    ('Wet No Snow 12',                           (-4,  3),         None),
    412 :    ('Wet No Snow 13',                           (-5,  3),         None),
    413 :    ('Wet No Snow 14',                           (-6,  3),         None),
    414 :    ('Wet No Snow 15',                           (-7,  3),         None),
    415 :    ('Wet No Snow 16',                           (-8,  3),         None),
    416 :    ('Wet No Snow 17',                           (-1,  4),         None),
    417 :    ('Wet No Snow 18',                           (-2,  4),         None),
    418 :    ('Wet No Snow 19',                           (-3,  4),         None),
    419 :    ('Wet No Snow 20',                           (-4,  4),         None),
    420 :    ('Wet No Snow 21',                           (-5,  4),         None),
    421 :    ('Wet No Snow 22',                           (-6,  4),         None),
    422 :    ('Wet No Snow 23',                           (-7,  4),         None),
    423 :    ('Wet No Snow 24',                           (-8,  4),         None),
    424 :    ('Wet No Snow 25',                           (-1,  5),         None),
    425 :    ('Wet No Snow 26',                           (-2,  5),         None),
    426 :    ('Wet No Snow 27',                           (-3,  5),         None),
    427 :    ('Wet No Snow 28',                           (-4,  5),         None),
    428 :    ('Wet No Snow 29',                           (-5,  5),         None),
    429 :    ('Wet No Snow 30',                           (-6,  5),         None),
    430 :    ('Wet No Snow 31',                           (-7,  5),         None),
    431 :    ('Wet No Snow 32',                           (-8,  5),         None),
    432 :    ('Wet No Snow 33',                           (-1,  6),         None),
    433 :    ('Wet No Snow 34',                           (-2,  6),         None),
    434 :    ('Wet No Snow 35',                           (-3,  6),         None),
    435 :    ('Wet No Snow 36',                           (-4,  6),         None),
    436 :    ('Wet No Snow 37',                           (-5,  6),         None),
    437 :    ('Wet No Snow 38',                           (-6,  6),         None),
    438 :    ('Wet No Snow 39',                           (-7,  6),         None),
    439 :    ('Wet No Snow 40',                           (-8,  6),         None),
    440 :    ('Wet No Snow 41',                           (-1,  7),         None),
    441 :    ('Wet No Snow 42',                           (-2,  7),         None),
    442 :    ('Wet No Snow 43',                           (-3,  7),         None),
    443 :    ('Wet No Snow 44',                           (-4,  7),         None),
    444 :    ('Wet No Snow 45',                           (-5,  7),         None),
    445 :    ('Wet No Snow 46',                           (-6,  7),         None),
    446 :    ('Wet No Snow 47',                           (-7,  7),         None),
    447 :    ('Wet No Snow 48',                           (-8,  7),         None),
    448 :    ('Wet No Snow 49',                           (-1,  8),         None),
    449 :    ('Wet No Snow 50',                           (-2,  8),         None),
    450 :    ('Wet No Snow 51',                           (-3,  8),         None),
    451 :    ('Wet No Snow 52',                           (-4,  8),         None),
    452 :    ('Wet No Snow 53',                           (-5,  8),         None),
    453 :    ('Wet No Snow 54',                           (-6,  8),         None),
    454 :    ('Wet No Snow 55',                           (-7,  8),         None),
    455 :    ('Wet No Snow 56',                           (-8,  8),         None),
}

# ------------------------------------------------------------------
# Build ID groups from the manual FS25 grid dictionary
# ------------------------------------------------------------------

LIGHT_IDS   = sorted(i for i in material_id_to_uvs.keys() if 0   <= i <=  99)
WET_IDS     = sorted(i for i in material_id_to_uvs.keys() if 100 <= i <= 199)
DRY_IDS     = sorted(i for i in material_id_to_uvs.keys() if 200 <= i <= 299)
DRY_NS_IDS  = sorted(i for i in material_id_to_uvs.keys() if 300 <= i <= 399)
WET_NS_IDS  = sorted(i for i in material_id_to_uvs.keys() if 400 <= i <= 499)

print(f"[FS25 VehicleArrayTool] Loaded {len(material_id_to_uvs)} UV slots: "
      f"{len(LIGHT_IDS)} Lights, {len(WET_IDS)} Wet, {len(DRY_IDS)} Dry, "
      f"{len(DRY_NS_IDS)} Dry No Snow, {len(WET_NS_IDS)} Wet No Snow.")
