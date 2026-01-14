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

import os
import math
import bpy
from mathutils import Vector


def _addon_root_dir() -> str:
    # tools/trackArrayTools.py -> tools -> addon root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _template_blend_path() -> str:
    return os.path.join(_addon_root_dir(), "resources", "3dtracks.blend")


def _choose_collection_name(collection_names):
    # Prefer a known/likely collection name, otherwise fall back to first available.
    preferred = [
        "TRACK_SETUP",
        "Track Setup",
        "Track_Setup",
        "TrackSetup",
        "TRACKS",
        "Tracks",
        "3dtracks",
        "3DTracks",
        "RMC_TRACK_SETUP",
        "RMC_Track_Setup",
        "TrackArraySetup",
    ]
    for name in preferred:
        if name in collection_names:
            return name
    return collection_names[0] if collection_names else None



def _ensure_track_curve_rig(context, curve_obj, fwd_span, forward_axis, vertical_axis, thickness_axis):
    """Ensure the template-like armature + Spline IK rig exists and targets the generated curve."""
    arm_name = "3. EXPORT me"
    arm_obj = bpy.data.objects.get(arm_name)
    if arm_obj and arm_obj.type != 'ARMATURE':
        arm_obj = None

    if not arm_obj:
        arm_data = bpy.data.armatures.new(arm_name)
        arm_obj = bpy.data.objects.new(arm_name, arm_data)
        # Link to the active collection if possible, else scene root.
        try:
            context.collection.objects.link(arm_obj)
        except:
            context.scene.collection.objects.link(arm_obj)

    # Reset transforms so the rig is anchored at world origin.
    arm_obj.location = (0.0, 0.0, 0.0)
    arm_obj.rotation_euler = (0.0, 0.0, 0.0)
    arm_obj.scale = (1.0, 1.0, 1.0)

    desired_names = ["Bone"] + [f"Bone.{i:03d}" for i in range(2, 101)]
    existing = set(arm_obj.data.bones.keys())
    needs_rebuild = (len(arm_obj.data.bones) != 100) or any(n not in existing for n in desired_names)

    # Build a straight rest-chain along the forward axis; Spline IK will deform it to the curve.
    if needs_rebuild:
        # Preserve current selection/active
        prev_active = context.view_layer.objects.active
        prev_selected = [o for o in context.selected_objects]

        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except:
            pass

        for o in prev_selected:
            o.select_set(False)

        arm_obj.select_set(True)
        context.view_layer.objects.active = arm_obj

        try:
            bpy.ops.object.mode_set(mode='EDIT')
        except:
            # If we can't enter edit mode, bail out gracefully (curve will still be generated)
            return

        eb = arm_obj.data.edit_bones

        # Clear existing edit bones
        for b in list(eb):
            eb.remove(b)

        span = max(abs(float(fwd_span)), 0.001)
        step = span / 100.0
        start = -span * 0.5

        prev_bone = None
        for idx in range(100):
            name = "Bone" if idx == 0 else f"Bone.{idx+1:03d}"

            head = Vector((0.0, 0.0, 0.0))
            tail = Vector((0.0, 0.0, 0.0))

            head[forward_axis] = start + (idx * step)
            tail[forward_axis] = start + ((idx + 1) * step)

            b = eb.new(name)
            b.head = head
            b.tail = tail

            if prev_bone:
                b.parent = prev_bone
                b.use_connect = True

            prev_bone = b

        # Back to object mode
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except:
            pass

        # Restore selection/active
        for o in prev_selected:
            o.select_set(True)
        context.view_layer.objects.active = prev_active

    # Ensure Spline IK constraint exists on the last bone and targets the curve
    try:
        prev_active = context.view_layer.objects.active
        prev_selected = [o for o in context.selected_objects]

        bpy.ops.object.mode_set(mode='OBJECT')
        for o in prev_selected:
            o.select_set(False)
        arm_obj.select_set(True)
        context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='POSE')

        pb = arm_obj.pose.bones.get("Bone.100")
        if pb:
            c = None
            for cc in pb.constraints:
                if cc.type == 'SPLINE_IK':
                    c = cc
                    break
            if c is None:
                c = pb.constraints.new('SPLINE_IK')

            c.target = curve_obj
            c.chain_count = 100
            c.use_even_divisions = True
            c.use_curve_radius = False
            c.y_scale_mode = 'FIT_CURVE'
            c.xz_scale_mode = 'BONE_ORIGINAL'
            c.influence = 1.0

        bpy.ops.object.mode_set(mode='OBJECT')

        # Restore selection/active
        for o in prev_selected:
            o.select_set(True)
        context.view_layer.objects.active = prev_active
    except:
        # Non-fatal
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except:
            pass


class I3D_OT_importTrackSetupSystem(bpy.types.Operator):
    bl_idname = "i3d.import_track_setup_system"
    bl_label = "Import Basic Oval Track Setup System"
    bl_description = "Append the track setup system template into the current .blend"
    bl_options = {'UNDO'}

    def execute(self, context):
        blend_path = _template_blend_path()

        if not os.path.exists(blend_path):
            self.report({'ERROR'}, f"Missing template: {blend_path}")
            return {'CANCELLED'}

        try:
            # Read library index first
            with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
                available_collections = list(data_from.collections)
                available_objects = list(data_from.objects)

            # Prefer appending a collection (best for whole-system injection)
            target_collection_name = _choose_collection_name(available_collections)

            if target_collection_name:
                with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
                    data_to.collections = [target_collection_name]

                imported_col = data_to.collections[0] if data_to.collections else None
                if not imported_col:
                    self.report({'ERROR'}, "Failed to append collection from template.")
                    return {'CANCELLED'}

                # Link into scene collection
                scene_root = context.scene.collection
                if imported_col.name not in scene_root.children:
                    scene_root.children.link(imported_col)

                self.report({'INFO'}, f"Imported Track Setup Collection: {imported_col.name}")
                return {'FINISHED'}

            # Fallback: append objects if no collections exist
            if available_objects:
                with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
                    data_to.objects = available_objects

                imported = [o for o in data_to.objects if o is not None]
                if not imported:
                    self.report({'ERROR'}, "Failed to append objects from template.")
                    return {'CANCELLED'}

                scene_root = context.scene.collection
                for obj in imported:
                    # Link only if not already linked to any collection
                    if obj.users_collection:
                        continue
                    scene_root.objects.link(obj)

                self.report({'INFO'}, f"Imported Track Setup Objects: {len(imported)}")
                return {'FINISHED'}

            self.report({'ERROR'}, "Template contains no collections or objects to append.")
            return {'CANCELLED'}

        except Exception as e:
            self.report({'ERROR'}, f"Import failed: {e}")
            return {'CANCELLED'}


def _axis_ranges(vectors):
    # vectors: list[Vector]
    mins = [min(v[i] for v in vectors) for i in range(3)]
    maxs = [max(v[i] for v in vectors) for i in range(3)]
    return [maxs[i] - mins[i] for i in range(3)]


def _pick_track_plane_axes(centers):
    # Pick the "thickness" axis as the axis with least variation.
    # Track plane is the other two axes.
    ranges = _axis_ranges(centers)
    thickness_axis = min(range(3), key=lambda i: ranges[i])

    remaining = [i for i in range(3) if i != thickness_axis]
    # Forward axis: greater variation; Vertical axis: other.
    if ranges[remaining[0]] >= ranges[remaining[1]]:
        forward_axis = remaining[0]
        vertical_axis = remaining[1]
    else:
        forward_axis = remaining[1]
        vertical_axis = remaining[0]

    return forward_axis, vertical_axis, thickness_axis


def _guide_radius_world(obj, forward_axis, vertical_axis):
    # Approximate wheel/roller radius from object dimensions.
    dims = obj.dimensions
    d = [dims.x, dims.y, dims.z]
    return 0.5 * max(d[forward_axis], d[vertical_axis])


def _convex_hull(points):
    # Andrew monotonic chain. points: list[(x,y)]
    points = sorted(set(points))
    if len(points) <= 1:
        return points

    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])

    lower = []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    # Exclude last point of each (it is the starting point of the other list).
    return lower[:-1] + upper[:-1]


def _chain_points(hull, start_i, end_i, step):
    n = len(hull)
    out = []
    i = start_i
    while True:
        out.append(hull[i])
        if i == end_i:
            break
        i = (i + step) % n
    return out


class I3D_OT_generateTrackCurveFromGuides(bpy.types.Operator):
    bl_idname = "i3d.generate_track_curve_from_guides"
    bl_label = "Generate Custom Track Setup System From Guides"
    bl_description = "Create a curve that follows the outer shape of selected track guide wheels/rollers (bottom segment forced flat)"
    bl_options = {'UNDO'}

    samples_per_guide: bpy.props.IntProperty(
        name="Samples Per Guide",
        description="Higher values make the curve follow wheels more accurately but may be slower",
        default=72,
        min=24,
        max=360
    )

    bottom_epsilon: bpy.props.FloatProperty(
        name="Bottom Epsilon",
        description="Tolerance used to detect the lowest points for the flat bottom segment",
        default=0.002,
        min=0.0,
        max=0.1
    )

    def execute(self, context):
        sel = [o for o in context.selected_objects if o is not None]
        if len(sel) < 2:
            self.report({'ERROR'}, "Select at least two track guide objects (wheels/rollers) first.")
            return {'CANCELLED'}

        centers = [o.matrix_world.translation.copy() for o in sel]
        forward_axis, vertical_axis, thickness_axis = _pick_track_plane_axes(centers)

        thickness_value_selected = sum(c[thickness_axis] for c in centers) / float(len(centers))

        # Enforce the on-axis "0 requirements" workflow, but do NOT force world Z to 0.
        # - If thickness axis is Y (common XZ track plane), we keep the curve on Y=0.
        # - If thickness axis is Z (common XY track plane), preserve the selected Z so we don't flatten height.
        thickness_value = 0.0
        if thickness_axis == 2:
            thickness_value = thickness_value_selected

        guides = []
        for o in sel:
            c = o.matrix_world.translation
            cx = c[forward_axis]
            cy = c[vertical_axis]
            r = _guide_radius_world(o, forward_axis, vertical_axis)
            guides.append((cx, cy, r))

        # Determine bottom line (flat) from the lowest circle bottom.
        bottom_y = min(cy - r for (cx, cy, r) in guides)

        # Sample points around each guide circle.
        pts = []
        n = int(self.samples_per_guide)
        for (cx, cy, r) in guides:
            for i in range(n):
                t = (float(i) / float(n)) * (math.pi * 2.0)
                pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))

        hull = _convex_hull(pts)
        if len(hull) < 3:
            self.report({'ERROR'}, "Failed to compute an outer hull from the selected guides.")
            return {'CANCELLED'}

        eps = float(self.bottom_epsilon)
        bottom_candidates = [(i, p) for i, p in enumerate(hull) if p[1] <= bottom_y + eps]

        if not bottom_candidates:
            # Fallback: use minimum y from hull if something weird happens.
            bottom_y = min(p[1] for p in hull)
            bottom_candidates = [(i, p) for i, p in enumerate(hull) if p[1] <= bottom_y + eps]

        # Choose left and right bottom anchors.
        left_i, left_p = min(bottom_candidates, key=lambda t: (t[1][0], t[1][1]))
        right_i, right_p = max(bottom_candidates, key=lambda t: (t[1][0], t[1][1]))

        x_left = left_p[0]
        x_right = right_p[0]

        chain_fwd = _chain_points(hull, left_i, right_i, step=1)
        chain_bwd = _chain_points(hull, left_i, right_i, step=-1)

        # Pick the chain that represents the "top" path (higher average Y).
        def chain_score(chain):
            ys = [p[1] for p in chain]
            return sum(ys) / float(len(ys))

        top_chain = chain_fwd if chain_score(chain_fwd) >= chain_score(chain_bwd) else chain_bwd

        # Build final 2D path: start at left bottom, go around top, end at right bottom.
        path2d = [(x_left, bottom_y)]
        for p in top_chain[1:-1]:
            # Keep points above the bottom line to preserve the flat lower run.
            if p[1] > bottom_y + eps:
                path2d.append(p)
        path2d.append((x_right, bottom_y))

        if len(path2d) < 4:
            # If selection is tiny (e.g., 2 wheels), keep a few more points for a usable curve.
            path2d = [(x_left, bottom_y)] + top_chain[1:-1] + [(x_right, bottom_y)]

        # Center the generated path on the world origin *only on the forward axis*.
        # Do NOT recenter the vertical axis (user may have real wheel height), and do NOT shift world Z.
        u_vals = [p[0] for p in path2d]
        v_vals = [p[1] for p in path2d]
        u_off = (min(u_vals) + max(u_vals)) * 0.5
        if forward_axis == 2:
            u_off = 0.0
        path2d = [(u - u_off, v) for (u, v) in path2d]

        fwd_span = (max(u_vals) - min(u_vals))
        # Create (or update) the main editable track curve.
        curve_name = "2. EDIT me"
        curve_obj = bpy.data.objects.get(curve_name)
        if curve_obj and curve_obj.type == 'CURVE':
            curve_data = curve_obj.data
            curve_data.splines.clear()
        else:
            curve_data = bpy.data.curves.new(curve_name, type='CURVE')
            curve_obj = bpy.data.objects.new(curve_name, curve_data)

            # Link to the active collection if possible, else scene root.
            try:
                context.collection.objects.link(curve_obj)
            except:
                context.scene.collection.objects.link(curve_obj)

        curve_data.dimensions = '3D'

        # Reset object transforms so the curve is anchored at world origin.
        curve_obj.location = (0.0, 0.0, 0.0)
        curve_obj.rotation_euler = (0.0, 0.0, 0.0)
        curve_obj.scale = (1.0, 1.0, 1.0)

        spline = curve_data.splines.new(type='BEZIER')
        spline.bezier_points.add(len(path2d) - 1)
        spline.use_cyclic_u = True

        for i, (u, v) in enumerate(path2d):
            co = [0.0, 0.0, 0.0]
            co[forward_axis] = u
            co[vertical_axis] = v
            co[thickness_axis] = thickness_value

            bp = spline.bezier_points[i]
            bp.co = Vector(co)
            bp.handle_left_type = 'AUTO'
            bp.handle_right_type = 'AUTO'

        # Select and activate the curve.
        for o in context.selected_objects:
            o.select_set(False)
        curve_obj.select_set(True)
        context.view_layer.objects.active = curve_obj

        # Ensure the template-like armature rig exists and targets this curve.
        _ensure_track_curve_rig(context, curve_obj, fwd_span, forward_axis, vertical_axis, thickness_axis)

        self.report({'INFO'}, f"Generated {curve_obj.name} + rig at world origin from {len(sel)} guides (flat bottom).")
        return {'FINISHED'}




_CLASSES = (
    I3D_OT_importTrackSetupSystem,
    I3D_OT_generateTrackCurveFromGuides,
)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(c)
        except:
            pass