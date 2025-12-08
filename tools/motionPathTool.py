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
    bl_category = "GIANTS I3D Exporter"

    selectedCurves = []

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.operator("tools.motionpathpopupactionbutton", text="Load Selected").state = 2
        row.operator("tools.motionpathpopupactionbutton", text="Clear List").state = 3

        box = layout.box()
        col = box.column()
        if len(self.selectedCurves) > 0:
            for curve in self.selectedCurves:
                col.label(text=curve)
        else:
            col.label(text="Nothing selected...")

        row = layout.row()
        row.prop(context.scene.TOOLS_UIMotionPath, 'motionTypes', expand=True)
        row = layout.row()
        row.prop(context.scene.TOOLS_UIMotionPath,"creationType",expand=True)
        row = layout.row()
        row.prop(context.scene.TOOLS_UIMotionPath,'amount')
        row.prop(context.scene.TOOLS_UIMotionPath,'distance')
        row = layout.row()
        row.prop(context.scene.TOOLS_UIMotionPath,"parentName")
        row = layout.row()
        row.operator("tools.motionpathpopupactionbutton",text="Create").state = 1
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
        bpy.types.Scene.TOOLS_UIMotionPath = bpy.props.PointerProperty(
            name = "Tools UI Motion Path",
            type =  cls,
            description = "Tools UI Motion Path"
        )
    @classmethod
    def unregister( cls ):
        if bpy.context.scene.get( 'TOOLS_UIMotionPath' ):  del bpy.context.scene[ 'TOOLS_UIMotionPath' ]
        try:    del bpy.types.Scene.TOOLS_UIMotionPath
        except: pass

class I3D_OT_motionPathPopUp(bpy.types.Operator):
    """Open the Pop up window"""

    bl_label = "Object Data from Curve"
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

            if bpy.context.scene.TOOLS_UIMotionPath.motionTypes == 'MOTION_PATH':
                offset = i/amount
                bpy.context.object.constraints["Follow Path"].offset_factor = offset
                bpy.ops.constraint.followpath_path_animate({'constraint':emptyObj.constraints["Follow Path"]},constraint='Follow Path')
                emptyObj.matrix_basis = emptyObj.matrix_local
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
                offset = i/amount          #adjust offset to the amount-curve length
                emptyObj.constraints['Follow Path'].offset_factor = offset
                bpy.ops.constraint.followpath_path_animate(constraint='Follow Path')
                emptyObj.matrix_basis = emptyObj.matrix_local
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

    def __createByAmount(self, amount, curveName):
        """ Creates the given amount of 'empty'-objects on the provided curve. """

        if len(I3D_PT_motionPath.selectedCurves) > 0:
            targetParent = None
            arrayRootObjectName = bpy.context.scene.TOOLS_UIMotionPath.parentName + "_ignore"
            hierarchicalSetup = len(I3D_PT_motionPath.selectedCurves) > 1

            if arrayRootObjectName in bpy.data.objects:
                oldObject = bpy.data.objects[arrayRootObjectName]
                targetParent = oldObject.parent
                dcc.deleteHierarchy(oldObject)

            bpy.ops.object.empty_add()
            parentObj = bpy.context.active_object
            parentObj.name = arrayRootObjectName

            #set attributes for dds
            self.__ddsExportSettings(parentObj.name, amount, hierarchicalSetup)
            parentObj.location = (0,0,0)
            parentObj.rotation_euler = (0,0,0)
            parentObj.scale = (1,1,1)

            if not hierarchicalSetup:
                curveName = I3D_PT_motionPath.selectedCurves[0]
                if curveName in bpy.data.objects:
                    self.__createEmptiesForCurve(parentObj, curveName, amount)
            else:
                bpy.ops.object.empty_add()
                poseNode = bpy.context.active_object
                poseNode.parent = parentObj
                poseNode.name = "pose1"
                poseNode.location = (0,0,0)
                poseNode.rotation_euler = (0,0,0)
                poseNode.scale = (1,1,1)

                for i in range(0, len(I3D_PT_motionPath.selectedCurves)):
                    curveName = I3D_PT_motionPath.selectedCurves[i]
                    if curveName in bpy.data.objects:
                        bpy.ops.object.empty_add()
                        rowParent = bpy.context.active_object
                        rowParent.parent = poseNode
                        rowParent.name = "row%d" % (i + 1)
                        rowParent.location = (0,0,0)
                        rowParent.rotation_euler = (0,0,0)
                        rowParent.scale = (1,1,1)

                        self.__createEmptiesForCurve(rowParent, curveName, amount)

            if targetParent is not None:
                parentObj.parent = targetParent
                parentObj.matrix_parent_inverse = targetParent.matrix_world.inverted()

    def __createByDistance(self, distance, curveName):
        """ Creates the 'empty'-objects in the given interval on the provided curve. """

        length = dcc.getCurveLength(curveName)   #get length of curve
        if(length > 0):
            amount = int(round(length/distance))    #calc amount with provided distance
            self.__createByAmount(amount, curveName)

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
                self.report({'INFO'},"Create {} empties on {}".format(context.scene.TOOLS_UIMotionPath.amount,context.scene.TOOLS_UIMotionPath.nurbs))
                self.__createByAmount(context.scene.TOOLS_UIMotionPath.amount, context.scene.TOOLS_UIMotionPath.nurbs)
            if context.scene.TOOLS_UIMotionPath.creationType == "DISTANCE":
                if context.scene.TOOLS_UIMotionPath.distance <= 0:
                    self.report({'WARNING'},"Invalid Distance value: {}".format(context.scene.TOOLS_UIMotionPath.distance))
                    return{'CANCELLED'}
                self.report({'INFO'},"Create empties in {} intervals on {}".format(round(context.scene.TOOLS_UIMotionPath.distance,3),context.scene.TOOLS_UIMotionPath.nurbs))
                self.__createByDistance(context.scene.TOOLS_UIMotionPath.distance, context.scene.TOOLS_UIMotionPath.nurbs)
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
    bpy.utils.register_class(I3D_OT_motionPathPopUp)
    bpy.utils.register_class(TOOLS_OT_motionPathPopUpActionButton)


def unregister():
    """ Unregister UI elements """

    bpy.utils.unregister_class(TOOLS_OT_motionPathPopUpActionButton)
    bpy.utils.unregister_class(I3D_OT_motionPathPopUp)
    bpy.utils.unregister_class(TOOLS_UIMotionPath)



