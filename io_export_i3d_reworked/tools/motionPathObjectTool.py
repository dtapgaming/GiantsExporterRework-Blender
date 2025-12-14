"""motionPathObjectTool.py is used to generate empty objects along of predefined object animation tracks"""


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
from ..dcc import dccBlender as dcc
# from timeit import default_timer as timer



class I3D_PT_motionPathObject( bpy.types.Panel ):
    """ GUI Panel for the GIANTS I3D Exporter visible in the 3D Viewport """

    bl_idname       = "TOOLS_PT_MotionPathObject"
    bl_label        = "GIANTS Motion Path Tool (Animations)"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GIANTS I3D Exporter"

    animatedTransforms = []
    curveLength = {}

    def __amountFixDistVal(self,context):
        """ Update function to display correct empty distance for set count. """

        distance = 0
        # for objName in I3D_PT_motionPathObject.animatedTransforms:
            # length = dcc.getFcurveLength(bpy.data.objects[objName].animation_data.action)[-1]   #get length of curve
        for objName in self.curveLength.keys():
            length = self.curveLength[objName]
            if(length > 0 and context.scene.TOOLS_UIMotionPathObject.amountFix != 0):
                distance = max(distance,length/context.scene.TOOLS_UIMotionPathObject.amountFix)    #calc amount with provided distance
        return distance

    def __distanceAmountVal(self,context):
        """ Update function to display correct empty count for set distance. """

        emptyCount = 0
        # for objName in I3D_PT_motionPathObject.animatedTransforms:
            # length = dcc.getFcurveLength(bpy.data.objects[objName].animation_data.action)[-1]   #get length of curve
        for objName in self.curveLength.keys():
            length = self.curveLength[objName]
            if(length > 0 and context.scene.TOOLS_UIMotionPathObject.distance != 0):
                emptyCount = max(emptyCount,int(round(length/context.scene.TOOLS_UIMotionPathObject.distance)))    #calc amount with provided distance
        return emptyCount

    @classmethod
    def updateLengths(cls,context):

        for objName in I3D_PT_motionPathObject.animatedTransforms:
            cls.curveLength[objName] = dcc.getFcurveLength(bpy.data.objects[objName].animation_data.action)[-1][0]   #get length of curve

    @classmethod
    def clearLengths(cls,context):
        cls.curveLength = {}

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.label(text="Animated Transforms")

        row.operator('tools.motionpathobjectpopupactionbutton',text="Load Selected").state = 1
        row.operator('tools.motionpathobjectpopupactionbutton',text="Clear List").state = 2
        box = layout.box()
        col = box.column()
        if len(self.animatedTransforms) > 0:
            for item in self.animatedTransforms:
                col.label(text=item)
        else:
            col.label(text="Nothing selected...")

        row = layout.row()

        row.prop(context.scene.TOOLS_UIMotionPathObject,'creationType',expand=True)
        row = layout.row()
        row.prop(context.scene.TOOLS_UIMotionPathObject,'amountRel',)
        row.prop(context.scene.TOOLS_UIMotionPathObject,'amountFix')
        row.prop(context.scene.TOOLS_UIMotionPathObject,'distance')
        split = layout.split(factor=0.3)
        split.label()
        split = split.split(factor=0.5)
        split.label(text="    Distance: {:.5f}".format(self.__amountFixDistVal(context)))
        split.label(text="  Amount: {}".format(self.__distanceAmountVal(context)))
        row = layout.row()
        row.prop(context.scene.TOOLS_UIMotionPathObject,"parentName")
        row = layout.row()
        row.operator('tools.motionpathobjectpopupactionbutton',text="Create").state = 3
        # row = layout.row()
        # row.operator('i3d.motionpathobjectpopup',text="Close",icon = 'X')

class TOOLS_UIMotionPathObject( bpy.types.PropertyGroup ):

    creationType : bpy.props.EnumProperty ( items = [("AMOUNT_REL", "Fixed Amount", "Places Objects on every animation path in equal distances per animation path"),
                                                    ("AMOUNT_FIX", "Distance from Amount", "Places Objects on longest path in equal distance. Apply this distance on other animation paths"),
                                                    ("DISTANCE","Fixed Distance", "Places Objects in fixed equal distance"),],
                                                    name = "motionTypes")
    amountRel : bpy.props.IntProperty(name= "AmountRel", default= 32)
    amountFix : bpy.props.IntProperty(name= "AmountFix", default= 32)
    distance : bpy.props.FloatProperty(name= "Distance", default= 0.2)
    parentName : bpy.props.StringProperty(name = "Group Name", default = "curveArray")


    @classmethod
    def register( cls ):
        bpy.types.Scene.TOOLS_UIMotionPathObject = bpy.props.PointerProperty(
            name = "Tools UI Motion Path Object",
            type =  cls,
            description = "Tools UI Motion Path Object"
        )
    @classmethod
    def unregister( cls ):
        if bpy.context.scene.get( 'TOOLS_UIMotionPathObject' ):  del bpy.context.scene[ 'TOOLS_UIMotionPathObject' ]
        try:    del bpy.types.Scene.TOOLS_UIMotionPathObject
        except: pass

class I3D_OT_motionPathObjectPopUp(bpy.types.Operator):
    """Open the Pop up window"""

    bl_label = "Object Data from Animations"
    bl_idname = "i3d.motionpathobjectpopup"
    bl_options = {'UNDO'}
    state : bpy.props.IntProperty(name = "State", default = 0)

    def execute(self, context):
        if self.state == 0:
            try:
                bpy.utils.register_class(I3D_PT_motionPathObject)
                self.state = 1
            except:
                return {'CANCELLED'}
        elif self.state == 1:
            try:
                bpy.utils.unregister_class(I3D_PT_motionPathObject)
                self.state = 0
            except:
                return {'CANCELLED'}
        return {'FINISHED'}


class TOOLS_OT_motionPathObjectPopUpActionButton(bpy.types.Operator, bpy.types.PropertyGroup):

    bl_label = "Action Button"
    bl_idname = "tools.motionpathobjectpopupactionbutton"

    state : bpy.props.IntProperty(name = "State", default=0)
    curveLength = {}

    def __ddsExportSettings(self, objectName, amount, objCount):
        """ Exporter settings for correct .dds export of collection. """
        dcc.I3DSetAttrString(objectName, 'i3D_objectDataFilePath', bpy.context.scene.TOOLS_UIMotionPathObject.parentName + ".dds")
        dcc.I3DSetAttrBool(objectName,'i3D_objectDataHierarchicalSetup',True)
        dcc.I3DSetAttrBool(objectName,'i3D_objectDataHideFirstAndLastObject',True)
        dcc.I3DSetAttrBool(objectName,'i3D_objectDataExportPosition',True)
        dcc.I3DSetAttrBool(objectName,'i3D_objectDataExportOrientation',True)
        dcc.I3DSetAttrBool(objectName,'i3D_objectDataExportScale',True)


    def __loadSelected(self, context):
        """ Loads all selected nodes and if they qualify list them in the motion path from object UI """

        for objName in [objName for objName in dcc.getSelectedNodes() if dcc.hasAnimation(objName)]:
            if not objName in I3D_PT_motionPathObject.animatedTransforms:
                I3D_PT_motionPathObject.animatedTransforms.append(objName)

    def __find_index(self, elementList, value, lowerBound = 0):
        """ Binary search to find index to closest value in a sorted list, floors value if not exactly found """
        if lowerBound >= len(elementList):
            lowerBound = 0

        left, right = lowerBound, len(elementList) - 1
        while left <= right:
            middle = (left + right) // 2
            if elementList[middle][0] < value:
                left = middle + 1
            elif elementList[middle][0] > value:
                right = middle - 1
            else:
                return middle
        # return max(right,0)
        # return min(left,len(elementList)-1)
        return left

    def __create(self,context):
        """ Creates Empty's along all selected animathion paths. """

        # startCreate = timer()
        #create/replace parent
        if bpy.context.scene.TOOLS_UIMotionPathObject.parentName in bpy.data.objects:
            dcc.deleteHierarchy(bpy.data.objects[bpy.context.scene.TOOLS_UIMotionPathObject.parentName])

        rootObj = bpy.data.objects.new("empty",None)
        bpy.context.scene.collection.objects.link( rootObj )
        rootObj.name = bpy.context.scene.TOOLS_UIMotionPathObject.parentName

        parentObj = bpy.data.objects.new("empty",None)
        bpy.context.scene.collection.objects.link( parentObj )
        parentObj.name = "pose1"
        parentObj.parent = rootObj

        # endHierachry = timer()
        distanceTotalCount = 0
        amountFixDistance = 0
        curveLengthDict = {}
        for objName in I3D_PT_motionPathObject.animatedTransforms:
            curveLengthDict[objName] = dcc.getFcurveLength(bpy.data.objects[objName].animation_data.action)  #get length of curve
            I3D_PT_motionPathObject.curveLength[objName] = curveLengthDict[objName][-1][0]
        # endLength = timer()
        if context.scene.TOOLS_UIMotionPathObject.creationType == "AMOUNT_FIX":
            maxLength = 0
            for objName in I3D_PT_motionPathObject.animatedTransforms:
                length = curveLengthDict[objName][-1][0]
                maxLength = max(length,maxLength)
                if(length > 0):
                    amountFixDistance = max(amountFixDistance,length/context.scene.TOOLS_UIMotionPathObject.amountFix)    #calc amount with provided distance
            if amountFixDistance > 0.0:
                distanceTotalCount = (int)(maxLength/amountFixDistance)
        elif context.scene.TOOLS_UIMotionPathObject.creationType == "DISTANCE":
            for objName in I3D_PT_motionPathObject.animatedTransforms:
                length = curveLengthDict[objName][-1][0]
                if(length > 0):
                    distanceTotalCount = max(distanceTotalCount,int(round(length/context.scene.TOOLS_UIMotionPathObject.distance)))    #calc amount with provided distance
        # endSetup = timer()

        for objName in I3D_PT_motionPathObject.animatedTransforms:
            emptyCount = 0
            if context.scene.TOOLS_UIMotionPathObject.creationType == "AMOUNT_REL":
                emptyCount = context.scene.TOOLS_UIMotionPathObject.amountRel
            elif context.scene.TOOLS_UIMotionPathObject.creationType == "DISTANCE":
                length = curveLengthDict[objName][-1][0]
                if(length > 0):
                    emptyCount = int(round(length/context.scene.TOOLS_UIMotionPathObject.distance))    #calc amount with provided distance
            elif context.scene.TOOLS_UIMotionPathObject.creationType == "AMOUNT_FIX":
                length = curveLengthDict[objName][-1][0]
                if(length > 0 and amountFixDistance != 0):
                    emptyCount = int(round(length/amountFixDistance))    #calc amount with provided distance
            if emptyCount <= 0:
                self.report({'WARNING'},"Invalid input value")
                return {'CANCELLED'}

            fcurves = bpy.data.objects[objName].animation_data.action.fcurves
            locCurves = [fcvs for fcvs in fcurves if 'location' in fcvs.data_path]
            rotCurves = [fcvs for fcvs in fcurves if 'rotation' in fcvs.data_path]
            scaleCurves = [fcvs for fcvs in fcurves if 'scale' in fcvs.data_path]
            curveLength = curveLengthDict[objName][-1][0]
            distToFrame = curveLengthDict[objName]
            dataMatrix = mathutils.Matrix()
            # print("obj: {}\tlength: {:.5f}\t,precision: {}".format(objName,curveLength,precision))

            yObject = bpy.data.objects.new("empty",None)
            bpy.context.scene.collection.objects.link( yObject )
            yObject.name = objName+"_Y"
            yObject.parent = parentObj

            currentLengthIndex = 0
            for i in range(emptyCount):
                # startInnerLoop = timer()
                currentPosition = curveLength/(emptyCount-1)*i  #target value
                currentLengthIndex = self.__find_index(distToFrame,currentPosition, lowerBound = currentLengthIndex-1)

                lsp = distToFrame[max(currentLengthIndex-1,0)]
                usp = distToFrame[min(currentLengthIndex, len(distToFrame)-1)]
                if usp[0] - lsp[0] > 0:
                    alpha = (currentPosition - lsp[0]) / (usp[0] - lsp[0])
                elif usp[0] - lsp[0] == 0:
                    alpha = 1
                else:
                    return {'CANCELLED'}
                frame = lsp[1] + alpha * (usp[1] - lsp[1])

                if frame == -1:
                    print("something wrong")
                    return {'CANCELLED'}

                # endInnerSearch = timer()
                locVector = mathutils.Vector((1,1,1))
                for locFcrv in locCurves:
                    locVector[locFcrv.array_index] = locFcrv.evaluate(frame)
                translation = mathutils.Matrix.Translation(locVector)   #TODO: add initial object offset, maybe not needed

                scaleVector = mathutils.Vector((1,1,1))
                for scaleFcrv in scaleCurves:
                    scaleVector[scaleFcrv.array_index] = scaleFcrv.evaluate(frame)
                scalex = mathutils.Matrix.Scale(scaleVector[0], 4, mathutils.Vector((1,0,0)))
                scaley = mathutils.Matrix.Scale(scaleVector[1], 4, mathutils.Vector((0,1,0)))
                scalez = mathutils.Matrix.Scale(scaleVector[2], 4, mathutils.Vector((0,0,1)))

                rotVector = mathutils.Vector()
                for rotFcrv in rotCurves:
                    #only works with complete rotation data
                    if rotFcrv.data_path == 'rotation_euler':
                        rotVector[rotFcrv.array_index] = rotFcrv.evaluate(frame)
                    elif rotFcrv.data_path == 'rotation_quaternion':
                        rotVector[rotFcrv.array_index] = rotFcrv.evaluate(frame)
                if len(rotVector) > 3:
                    rotation = mathutils.Quaternion(rotVector).to_euler()
                elif len(rotVector) == 3:
                    rotation = mathutils.Euler(rotVector)
                else:
                    self.report({'WARNING'},"Uncomplete rotation keyframe data")
                    rotation = Matrix.Identity(4)
                dataMatrix = translation.to_4x4() @ rotation.to_matrix().to_4x4() @ scalex @ scaley @ scalez

                # endInnerDataCalls = timer()
                emptyObj = bpy.data.objects.new("empty",None)
                bpy.context.scene.collection.objects.link( emptyObj )
                emptyObj.name = objName+"_X_{:03d}".format(i)
                emptyObj.parent = yObject #parentObj
                emptyObj.matrix_basis = dataMatrix
                # endInnerLoop = timer()
                # print("Inner Timing")
                # print("innerSearch: {}s {}%\tdata: {}s {}%\tobjCreation: {}s {}%\ttotal: {}s".format(endInnerSearch - startInnerLoop,(endInnerSearch - startInnerLoop)/(endInnerLoop - startInnerLoop)*100,
                                                                                # endInnerDataCalls - endInnerSearch,(endInnerDataCalls - endInnerSearch)/(endInnerLoop - startInnerLoop)*100,
                                                                                # endInnerLoop - endInnerDataCalls,(endInnerLoop - endInnerDataCalls)/(endInnerLoop - startInnerLoop)*100,
                                                                                # endInnerLoop - startInnerLoop))
            # print("d: {}, tc: {}".format(distanceTotalCount,emptyCount))
            self.__ddsExportSettings(rootObj.name, max(emptyCount,distanceTotalCount), len(I3D_PT_motionPathObject.animatedTransforms))

        # endCreate = timer()
        # print("Timing for {} Curves with {} object:".format(len(I3D_PT_motionPathObject.animatedTransforms),emptyCount))
        # print("hierarchy: {}s {:g}%\tcurveLength: {}s {:g}%\tsetup: {}s {:g}%\tloop: {}s {:g}%\ttotal: {}s".format(endHierachry - startCreate, (endHierachry - startCreate)/(endCreate - startCreate) *100,
                                                                                            # endLength - endHierachry,( endLength - endHierachry)/(endCreate - startCreate) *100,
                                                                                            # endSetup - endLength,(endSetup - endLength)/(endCreate - startCreate) *100,
                                                                                            # endCreate - endSetup, (endCreate - endSetup)/(endCreate - startCreate) *100,
                                                                                            # endCreate - startCreate))
        return {'FINISHED'}


    def execute(self,context):
        if self.state == 1:
            self.__loadSelected(context)
            I3D_PT_motionPathObject.updateLengths(context)
        elif self.state == 2:
            I3D_PT_motionPathObject.animatedTransforms.clear()
            I3D_PT_motionPathObject.clearLengths(context)
        elif self.state == 3:
            try:
                #work in object mode without object selected
                bpy.ops.object.mode_set ( mode = 'OBJECT' )
                bpy.ops.object.select_all(action='DESELECT')
            except:
                pass
            if len(I3D_PT_motionPathObject.animatedTransforms) > 0:
                return self.__create(context)
        return {'FINISHED'}

def register():
    """ Register UI elements """


    bpy.utils.register_class(TOOLS_UIMotionPathObject)
    bpy.utils.register_class(I3D_OT_motionPathObjectPopUp)
    bpy.utils.register_class(TOOLS_OT_motionPathObjectPopUpActionButton)

def unregister():
    """ Unregister UI elements """

    bpy.utils.unregister_class(TOOLS_OT_motionPathObjectPopUpActionButton)
    bpy.utils.unregister_class(I3D_OT_motionPathObjectPopUp)
    bpy.utils.unregister_class(TOOLS_UIMotionPathObject)


