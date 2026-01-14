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

        # We avoid bpy.ops.constraint.followpath_path_animate() here.
        # In Blender 5.0+ that operator is strict about override contexts and
        # can raise: "ValueError: 1-2 args execution context is supported".
        # All we need is to evaluate the Follow Path constraint at a specific
        # offset, bake the resulting transform, then remove the constraint.
        depsgraph = bpy.context.evaluated_depsgraph_get()
        view_layer = bpy.context.view_layer

        #prevObj = None
        for i in range(0,amount):
            bpy.ops.object.empty_add()
            emptyObj = bpy.context.active_object
            listOfEmpties.append(emptyObj)
            #empties[i] = emptyObj
            emptyObj.parent = parent
            bpy.ops.object.constraint_add(type='FOLLOW_PATH')
            emptyObj.name = "ce_{}_{:03d}".format(parent.name,i)
            emptyObj.location = (0,0,0)
            emptyObj.rotation_euler = (0,0,0)
            emptyObj.scale = (1,1,1)
            emptyObj.constraints['Follow Path'].target = bpy.data.objects[curveName]
            emptyObj.empty_display_size = 0.25
            emptyObj.empty_display_type = 'ARROWS'
            #TODO: check if animated

            emptyObj.constraints['Follow Path'].use_curve_radius = False
            emptyObj.constraints['Follow Path'].use_fixed_location = True
            emptyObj.constraints['Follow Path'].use_curve_follow = True
            emptyObj.constraints['Follow Path'].forward_axis = 'FORWARD_Y'
            emptyObj.constraints['Follow Path'].up_axis = 'UP_Z'

            # Compute a stable 0..1 offset (include 1.0 on the last element when possible).
            denom = (amount - 1) if amount > 1 else 1
            offset = i / denom

            if bpy.context.scene.TOOLS_UIMotionPath.motionTypes == 'MOTION_PATH':
                emptyObj.constraints['Follow Path'].offset_factor = offset

                # Evaluate + bake transform.
                view_layer.update()
                eval_obj = emptyObj.evaluated_get(depsgraph)
                emptyObj.matrix_world = eval_obj.matrix_world.copy()

                emptyObj.constraints.remove(emptyObj.constraints['Follow Path'])
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
                emptyObj.constraints['Follow Path'].offset_factor = offset

                view_layer.update()
                eval_obj = emptyObj.evaluated_get(depsgraph)
                emptyObj.matrix_world = eval_obj.matrix_world.copy()

                emptyObj.constraints.remove(emptyObj.constraints['Follow Path'])

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
    def __createByAmount(self, context, amount, curveName):
        """Creates the given amount of 'empty'-objects on the provided curve (or selected curves)."""

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
            return False

        targetParent = None
        arrayRootObjectName = bpy.context.scene.TOOLS_UIMotionPath.parentName + "_ignore"
        hierarchicalSetup = len(curves_to_use) > 1

        if arrayRootObjectName in bpy.data.objects:
            oldObject = bpy.data.objects[arrayRootObjectName]
            targetParent = oldObject.parent
            dcc.deleteHierarchy(oldObject)

        bpy.ops.object.empty_add()
        parentObj = bpy.context.active_object
        if parentObj is None:
            self.report({'WARNING'}, "Failed to create root empty object.")
            return False
        parentObj.name = arrayRootObjectName

        # set attributes for dds
        self.__ddsExportSettings(parentObj.name, amount, hierarchicalSetup)
        parentObj.location = (0,0,0)
        parentObj.rotation_euler = (0,0,0)
        parentObj.scale = (1,1,1)

        if not hierarchicalSetup:
            curveName = curves_to_use[0]
            self.__createEmptiesForCurve(parentObj, curveName, amount)
        else:
            bpy.ops.object.empty_add()
            poseNode = bpy.context.active_object
            if poseNode is None:
                self.report({'WARNING'}, "Failed to create pose node empty.")
                return False
            poseNode.parent = parentObj
            poseNode.name = "pose1"
            poseNode.location = (0,0,0)
            poseNode.rotation_euler = (0,0,0)
            poseNode.scale = (1,1,1)

            for i, curveName in enumerate(curves_to_use):
                bpy.ops.object.empty_add()
                rowParent = bpy.context.active_object
                if rowParent is None:
                    continue
                rowParent.parent = poseNode
                rowParent.name = "row%d" % (i + 1)
                rowParent.location = (0,0,0)
                rowParent.rotation_euler = (0,0,0)
                rowParent.scale = (1,1,1)

                self.__createEmptiesForCurve(rowParent, curveName, amount)

        if targetParent is not None:
            parentObj.parent = targetParent
            parentObj.matrix_parent_inverse = targetParent.matrix_world.inverted()

        return True

    def __createByDistance(self, context, distance, curveName):
        """Creates the 'empty'-objects in the given interval on the provided curve."""

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
            return False

        length = dcc.getCurveLength(curves_to_use[0])
        if length <= 0:
            self.report({'WARNING'}, "Selected curve has invalid length.")
            return False

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
                ok = self.__createByAmount(context, context.scene.TOOLS_UIMotionPath.amount, context.scene.TOOLS_UIMotionPath.nurbs)
                if not ok:
                    return {'CANCELLED'}
                self.report({'INFO'}, "Created {} empties.".format(context.scene.TOOLS_UIMotionPath.amount))
            if context.scene.TOOLS_UIMotionPath.creationType == "DISTANCE":
                if context.scene.TOOLS_UIMotionPath.distance <= 0:
                    self.report({'WARNING'},"Invalid Distance value: {}".format(context.scene.TOOLS_UIMotionPath.distance))
                    return{'CANCELLED'}
                ok = self.__createByDistance(context, context.scene.TOOLS_UIMotionPath.distance, context.scene.TOOLS_UIMotionPath.nurbs)
                if not ok:
                    return {'CANCELLED'}
                self.report({'INFO'}, "Created empties in {} intervals.".format(round(context.scene.TOOLS_UIMotionPath.distance,3)))
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



