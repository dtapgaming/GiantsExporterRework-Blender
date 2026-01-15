"""motionPathTool.py is used to generate empty objects along of predefined tracks"""


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


import bpy
import mathutils
import math
from ..dcc import dccBlender as dcc
from ..util import selectionUtil

class I3D_PT_motionPath( bpy.types.Panel ):
    """ GUI Panel for the GIANTS I3D TOOLS visible in the 3D Viewport """

    bl_idname       = "TOOLS_PT_MotionPath"
    bl_label        = "GIANTS Motion Path Tool (Curves)"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GIANTS I3D Exporter REWORKED"

    # NOTE:
    # Some tool panels can appear "above" the main exporter panel depending on
    # register order and Blender version. We push this panel toward the bottom
    # of the tab explicitly.
    bl_order = -2000
    selectedCurves = []

    def draw(self, context):
        layout = self.layout
        ui = getattr(context.scene, "TOOLS_UIMotionPath", None)
        row = layout.row()
        op = row.operator("tools.motionpathpopupactionbutton", text="Load Selected")
        if op is not None:
            op.state = 2
        op = row.operator("tools.motionpathpopupactionbutton", text="Clear List")
        if op is not None:
            op.state = 3

        box = layout.box()
        col = box.column()
        if len(self.selectedCurves) > 0:
            for curve in self.selectedCurves:
                col.label(text=curve)
        else:
            col.label(text="Nothing selected...")

        if ui is None:
            layout.label(text="Motion Path UI properties not registered (TOOLS_UIMotionPath).", icon='ERROR')
            layout.label(text="Try: Preferences → Add-ons → disable/enable the add-on.")
            return

        row = layout.row()
        row.prop(ui, 'motionTypes', expand=True)
        row = layout.row()
        row.prop(ui, "creationType", expand=True)
        row = layout.row()
        row.prop(ui, 'amount')
        row.prop(ui, 'distance')
        row = layout.row()
        row.prop(ui, "parentName")
        row = layout.row()
        op = row.operator("tools.motionpathpopupactionbutton", text="Create")
        if op is not None:
            op.state = 1
        # row = layout.row()
        # row.operator('i3d.motionpathpopup',text="Close",icon = 'X')

class TOOLS_UIMotionPath( bpy.types.PropertyGroup ):

    def __getAllNurbsCurves(self, context):
        """ Returns enum elements of all Curves of the current Scene. """

        curves = tuple()
        curves += (("None","None","None",0),)
        try:
            num = 1
            for curveName in [ obj.name for obj in context.scene.objects if obj.type == 'CURVE']:
                curves += ((curveName,curveName,curveName,num),)
                num += 1
            return curves
        except:
            return curves

    nurbs : bpy.props.EnumProperty ( items = __getAllNurbsCurves, name = "Nurbs Curve")
    motionTypes : bpy.props.EnumProperty ( items = [("EFFECT", "Effect", ""),("MOTION_PATH","Motion Path", ""),], name = "motionTypes")
    creationType : bpy.props.EnumProperty ( items = [("AMOUNT", "Amount", "Amount of objects to be placed on the curve"),("DISTANCE","Distance", "The equal distance to be applied between the objects"),], name = "motionTypes")
    amount : bpy.props.IntProperty(name= "Amount", default= 64, min=2)
    distance : bpy.props.FloatProperty(name= "Distance", default= 0.1, min=0.01)
    parentName : bpy.props.StringProperty(name = "Group Name", default = "curveArray", description="Name of the Merge Group of the objects")

    @classmethod
    def register( cls ):
        # Blender does NOT automatically call PropertyGroup.register() when
        # bpy.utils.register_class() is used. We call this explicitly from the
        # module register() below.
        if not hasattr(bpy.types.Scene, "TOOLS_UIMotionPath"):
            bpy.types.Scene.TOOLS_UIMotionPath = bpy.props.PointerProperty(
                name="Tools UI Motion Path",
                type=cls,
                description="Tools UI Motion Path",
            )
    @classmethod
    def unregister( cls ):
        try:
            if hasattr(bpy.types.Scene, "TOOLS_UIMotionPath"):
                del bpy.types.Scene.TOOLS_UIMotionPath
        except Exception:
            pass

class I3D_OT_motionPathPopUp(bpy.types.Operator):
    """Open the Pop up window"""

    bl_label = "Object Data from Curve"
    bl_description = "Object Data from Curve."
    bl_idname = "i3d.motionpathpopup"
    state : bpy.props.IntProperty(name = "State", default = 0)

    def execute(self, context):
        if self.state == 0:
            try:
                if bpy.context.active_object:
                    if bpy.context.active_object.type == 'CURVE':
                        bpy.context.scene.TOOLS_UIMotionPath.nurbs = bpy.context.active_object.name
                bpy.utils.register_class(I3D_PT_motionPath)
                self.state = 1
            except:
                return {'CANCELLED'}
        elif self.state == 1:
            try:
                bpy.utils.unregister_class(I3D_PT_motionPath)
                self.state = 0
            except:
                return {'CANCELLED'}
        return {'FINISHED'}

class TOOLS_OT_motionPathPopUpActionButton(bpy.types.Operator):

    bl_label = "Action Button"
    bl_description = "Action Button."
    bl_idname = "tools.motionpathpopupactionbutton"
    bl_options = {'UNDO'}
    state : bpy.props.IntProperty(name = "State", default=0)


    def __ddsExportSettings(self, objectName, amount, hierarchicalSetup):
        """ Exporter settings for correct .dds export of collection. """
        dcc.I3DSetAttrString(objectName, 'i3D_objectDataFilePath', bpy.context.scene.TOOLS_UIMotionPath.parentName + ".dds")
        dcc.I3DSetAttrBool(objectName, 'i3D_objectDataHierarchicalSetup', hierarchicalSetup)
        dcc.I3DSetAttrBool(objectName, 'i3D_objectDataHideFirstAndLastObject', hierarchicalSetup)
        dcc.I3DSetAttrBool(objectName, 'i3D_objectDataExportPosition', True)
        dcc.I3DSetAttrBool(objectName, 'i3D_objectDataExportOrientation', True)
        dcc.I3DSetAttrBool(objectName, 'i3D_objectDataExportScale', False)

    def __createEmptiesForCurve(self, parent, curveName, amount):
        listOfEmpties = []

        # IMPORTANT (Blender 5+ / tester crash reports):
        # Do NOT use bpy.ops.object.empty_add() or bpy.ops.object.constraint_add()
        # here. Those operators are context-sensitive and will silently CANCEL
        # when invoked from a non-View3D context (e.g. Properties, Outliner),
        # which makes it *look* like we "created 50 empties" while actually
        # creating none.
        #
        # Use the data API instead (context-independent): bpy.data.objects.new()
        # + collection.objects.link() + constraints.new().
        depsgraph = bpy.context.evaluated_depsgraph_get()
        view_layer = bpy.context.view_layer
        target_curve = bpy.data.objects.get(curveName)
        if target_curve is None or target_curve.type != 'CURVE':
            self.report({'WARNING'}, f"Invalid curve: {curveName}")
            return []

        # Pick a safe collection to link new empties into.
        try:
            target_collection = bpy.context.collection
        except Exception:
            target_collection = None
        if target_collection is None:
            try:
                target_collection = view_layer.active_layer_collection.collection
            except Exception:
                target_collection = bpy.context.scene.collection

        for i in range(0, amount):
            emptyObj = bpy.data.objects.new("", None)
            emptyObj.name = "ce_{}_{:03d}".format(parent.name, i)
            emptyObj.empty_display_size = 0.25
            emptyObj.empty_display_type = 'ARROWS'

            # Link + parent
            try:
                target_collection.objects.link(emptyObj)
            except Exception:
                # Fallback: always link to Scene collection
                bpy.context.scene.collection.objects.link(emptyObj)

            emptyObj.parent = parent
            try:
                emptyObj.matrix_parent_inverse = parent.matrix_world.inverted()
            except Exception:
                pass

            emptyObj.location = (0, 0, 0)
            emptyObj.rotation_euler = (0, 0, 0)
            emptyObj.scale = (1, 1, 1)

            # Follow Path constraint (data API)
            cns = emptyObj.constraints.new(type='FOLLOW_PATH')
            cns.target = target_curve

            cns.use_curve_radius = False
            cns.use_fixed_location = True
            cns.use_curve_follow = True
            cns.forward_axis = 'FORWARD_Y'
            cns.up_axis = 'UP_Z'

            listOfEmpties.append(emptyObj)

            # Compute a stable 0..1 offset (include 1.0 on the last element when possible).
            denom = (amount - 1) if amount > 1 else 1
            offset = i / denom

            if bpy.context.scene.TOOLS_UIMotionPath.motionTypes == 'MOTION_PATH':
                cns.offset_factor = offset

                # Evaluate + bake transform.
                view_layer.update()
                eval_obj = emptyObj.evaluated_get(depsgraph)
                emptyObj.matrix_world = eval_obj.matrix_world.copy()

                emptyObj.constraints.remove(cns)
                #print("node {} x={} y={} z={}".format(i, emptyObj.rotation_euler[0], emptyObj.rotation_euler[1], emptyObj.rotation_euler[2]))
                if abs(round(emptyObj.rotation_euler[2], 3)) > 0 or abs(round(emptyObj.rotation_euler[1], 3)) > 0:
                    emptyObj.rotation_euler[0] = -emptyObj.rotation_euler[0]
                    if abs(round(emptyObj.rotation_euler[1], 3)) == 0 and abs(round(emptyObj.rotation_euler[2], 3)) > 0:
                        emptyObj.rotation_euler[0] += math.pi

                if (emptyObj.rotation_euler[0] < 0):
                    emptyObj.rotation_euler[0] += 2*math.pi
                elif (emptyObj.rotation_euler[0] > 2*math.pi):
                    emptyObj.rotation_euler[0] -= 2*math.pi
                emptyObj.rotation_euler[1] = 0
                emptyObj.rotation_euler[2] = 0
                #emptyObj.lock_rotation = (True, True, True)
                #emptyObj.keyframe_insert(data_path="rotation_euler", frame=i)

            elif bpy.context.scene.TOOLS_UIMotionPath.motionTypes == 'EFFECT':
                # Same evaluation/bake approach for EFFECT mode.
                cns.offset_factor = offset

                view_layer.update()
                eval_obj = emptyObj.evaluated_get(depsgraph)
                emptyObj.matrix_world = eval_obj.matrix_world.copy()

                emptyObj.constraints.remove(cns)

        if bpy.context.scene.TOOLS_UIMotionPath.motionTypes == 'MOTION_PATH':
            for i in range(len(listOfEmpties)):
                emptyObj = listOfEmpties[i]
                if (0 == i):
                    # first item
                    m_p1 = listOfEmpties[len(listOfEmpties)-1].location
                    m_p2 = listOfEmpties[i+1].location
                elif( (len(listOfEmpties)-1) == i):
                    # last item
                    m_p1 = listOfEmpties[i-1].location
                    m_p2 = listOfEmpties[0].location
                else:
                    m_p1 = listOfEmpties[i-1].location
                    m_p2 = listOfEmpties[i+1].location
                m_vector = m_p1 - m_p2
                m_vector.normalize()
                m_vectorZ = mathutils.Vector((0.0,1.0,0.0))
                m_dot = m_vector.dot(m_vectorZ)
                m_angle = math.degrees(math.acos(m_dot))
                # -------------
                if m_vector.z<0.0:
                    m_angle = 360.0 - m_angle
                if (0.0==round(m_angle)):
                    m_angle = 360.0
                #print(emptyObj.name, m_vector, m_angle)
                emptyObj.rotation_euler[0] = math.radians(m_angle)
                emptyObj.rotation_euler[1] = 0.0
                emptyObj.rotation_euler[2] = 0.0
                emptyObj.keyframe_insert(data_path="rotation_euler", frame=i)

        return listOfEmpties
    def __createByAmount(self, context, amount, curveName):
        """Creates the given amount of 'empty'-objects on the provided curve (or selected curves).

        Returns:
            int: Number of child empties actually created (excludes the root/pose/row empties).
        """

        # Context-independent empty creation helper (safe even when invoked from non-View3D UI).
        def _new_empty(obj_name, parent=None):
            try:
                col = bpy.context.collection
            except Exception:
                col = None
            if col is None:
                try:
                    col = bpy.context.view_layer.active_layer_collection.collection
                except Exception:
                    col = bpy.context.scene.collection

            o = bpy.data.objects.new(obj_name, None)
            o.empty_display_size = 0.5
            o.empty_display_type = 'PLAIN_AXES'
            try:
                col.objects.link(o)
            except Exception:
                bpy.context.scene.collection.objects.link(o)
            if parent is not None:
                o.parent = parent
                try:
                    o.matrix_parent_inverse = parent.matrix_world.inverted()
                except Exception:
                    pass
            o.location = (0, 0, 0)
            o.rotation_euler = (0, 0, 0)
            o.scale = (1, 1, 1)
            return o

        # Prefer curves loaded via "Load Selected".
        curves_to_use = list(I3D_PT_motionPath.selectedCurves) if len(I3D_PT_motionPath.selectedCurves) > 0 else []

        # Fallback to dropdown selection or active curve when nothing was loaded.
        if not curves_to_use:
            if curveName and curveName != "None":
                obj = bpy.data.objects.get(curveName)
                if obj is not None and obj.type == 'CURVE':
                    curves_to_use = [curveName]
            elif context.active_object and context.active_object.type == 'CURVE':
                curves_to_use = [context.active_object.name]

        # De-dupe while preserving order and keep only valid curve objects.
        seen = set()
        cleaned = []
        for name in curves_to_use:
            if name in seen:
                continue
            seen.add(name)
            obj = bpy.data.objects.get(name)
            if obj is None or obj.type != 'CURVE':
                continue
            cleaned.append(name)
        curves_to_use = cleaned

        if not curves_to_use:
            self.report({'WARNING'}, "No curve selected. Use 'Load Selected' or choose a curve in the dropdown.")
            return 0

        targetParent = None
        arrayRootObjectName = bpy.context.scene.TOOLS_UIMotionPath.parentName + "_ignore"
        hierarchicalSetup = len(curves_to_use) > 1

        if arrayRootObjectName in bpy.data.objects:
            oldObject = bpy.data.objects[arrayRootObjectName]
            targetParent = oldObject.parent
            dcc.deleteHierarchy(oldObject)

        parentObj = _new_empty(arrayRootObjectName, parent=None)
        if parentObj is None:
            self.report({'WARNING'}, "Failed to create root empty object.")
            return 0

        # set attributes for dds
        self.__ddsExportSettings(parentObj.name, amount, hierarchicalSetup)
        parentObj.location = (0,0,0)
        parentObj.rotation_euler = (0,0,0)
        parentObj.scale = (1,1,1)

        created_count = 0

        if not hierarchicalSetup:
            curveName = curves_to_use[0]
            created_count += len(self.__createEmptiesForCurve(parentObj, curveName, amount))
        else:
            poseNode = _new_empty("pose1", parent=parentObj)
            if poseNode is None:
                self.report({'WARNING'}, "Failed to create pose node empty.")
                return 0

            for i, curveName in enumerate(curves_to_use):
                rowParent = _new_empty("row%d" % (i + 1), parent=poseNode)
                if rowParent is None:
                    continue

                created_count += len(self.__createEmptiesForCurve(rowParent, curveName, amount))

        if targetParent is not None:
            parentObj.parent = targetParent
            parentObj.matrix_parent_inverse = targetParent.matrix_world.inverted()

        return created_count

    def __createByDistance(self, context, distance, curveName):
        """Creates the 'empty'-objects in the given interval on the provided curve.

        Returns:
            int: Number of child empties actually created.
        """

        # Resolve a curve to use for length calculation.
        curves_to_use = list(I3D_PT_motionPath.selectedCurves) if len(I3D_PT_motionPath.selectedCurves) > 0 else []

        if not curves_to_use:
            if curveName and curveName != "None":
                obj = bpy.data.objects.get(curveName)
                if obj is not None and obj.type == 'CURVE':
                    curves_to_use = [curveName]
            elif context.active_object and context.active_object.type == 'CURVE':
                curves_to_use = [context.active_object.name]

        curves_to_use = [n for n in curves_to_use if (bpy.data.objects.get(n) is not None and bpy.data.objects[n].type == 'CURVE')]

        if not curves_to_use:
            self.report({'WARNING'}, "No curve selected. Use 'Load Selected' or choose a curve in the dropdown.")
            return 0

        length = dcc.getCurveLength(curves_to_use[0])
        if length <= 0:
            self.report({'WARNING'}, "Selected curve has invalid length.")
            return 0

        amount = int(round(length / distance))
        return self.__createByAmount(context, amount, curves_to_use[0])

    def execute(self, context):

        """ Creates the empty objects as specified within the settings. """

        if self.state == 1:
            try:
                #work in object mode without object selected
                current_mode = bpy.context.object.mode
                bpy.ops.object.mode_set ( mode = 'OBJECT' )
                bpy.ops.object.select_all(action='DESELECT')
            except:
                pass

            if context.scene.TOOLS_UIMotionPath.creationType == "AMOUNT":
                if context.scene.TOOLS_UIMotionPath.amount <= 0:
                    self.report({'WARNING'},"Invalid Amount value: {}".format(context.scene.TOOLS_UIMotionPath.amount))
                    return{'CANCELLED'}
                created = self.__createByAmount(context, context.scene.TOOLS_UIMotionPath.amount, context.scene.TOOLS_UIMotionPath.nurbs)
                if created <= 0:
                    return {'CANCELLED'}
                self.report({'INFO'}, "Created {} empties.".format(created))
            if context.scene.TOOLS_UIMotionPath.creationType == "DISTANCE":
                if context.scene.TOOLS_UIMotionPath.distance <= 0:
                    self.report({'WARNING'},"Invalid Distance value: {}".format(context.scene.TOOLS_UIMotionPath.distance))
                    return{'CANCELLED'}
                created = self.__createByDistance(context, context.scene.TOOLS_UIMotionPath.distance, context.scene.TOOLS_UIMotionPath.nurbs)
                if created <= 0:
                    return {'CANCELLED'}
                self.report({'INFO'}, "Created {} empties at ~{}m intervals.".format(created, round(context.scene.TOOLS_UIMotionPath.distance,3)))
            # avoid blender crash when undoing immediate after creating objects
            bpy.ops.ed.undo_push()
            return {'FINISHED'}
        elif self.state == 2:
            objects = selectionUtil.getSelectedObjects(context)
            for object in objects:
                if object.type == "CURVE":
                    I3D_PT_motionPath.selectedCurves.append(object.name)
                    I3D_PT_motionPath.selectedCurves = (list(set(I3D_PT_motionPath.selectedCurves)))
            return {'FINISHED'}
        elif self.state == 3:
            I3D_PT_motionPath.selectedCurves = []
            return {'FINISHED'}


def register():
    """ Register UI elements """

    bpy.utils.register_class(TOOLS_UIMotionPath)
    try:
        TOOLS_UIMotionPath.register()
    except Exception:
        pass
    bpy.utils.register_class(I3D_OT_motionPathPopUp)
    bpy.utils.register_class(TOOLS_OT_motionPathPopUpActionButton)


def unregister():
    """ Unregister UI elements """

    bpy.utils.unregister_class(TOOLS_OT_motionPathPopUpActionButton)
    bpy.utils.unregister_class(I3D_OT_motionPathPopUp)
    try:
        TOOLS_UIMotionPath.unregister()
    except Exception:
        pass
    bpy.utils.unregister_class(TOOLS_UIMotionPath)



