""" Exports dds array with position, orientation and scale data stored into the pixels of the texture"""

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


#-----------------------------------------------------------------------------------
#   Copy of maya exporter maya/plugins/external/exportObjectDataTexture.py
#
#   string i3D_objectDataFilePath             if not empty string -> export texture
#                                             path to the texture relative from mayafile
#   bool i3D_objectDataExportPosition         if True, export position
#   bool i3D_objectDataExportOrientation      if True, export orientation
#   bool i3D_objectDataExportScale            if True, export scale
#   bool i3D_objectDataHideFirstAndLastObject sets position.w to 0, used as visibility in the shader (apply before exporting data)
#   bool i3D_objectDataHierarchicalSetup      if True, number of poses is the number of children, the y axis is the number of children in each pose (objectSet)
#                                             (if not identical -> error), the x axis is the max number of children in each objectSet
#                                             missing x values in the texture are created by duplicating the last object value
#                                             expects following objects hierarchy (or similar) to be present:
#                                             array
#                                                 pose1
#                                                     y0
#                                                         x1, x2
#                                                     y1
#                                                         x1, x2, x3, x4
#                                                 pose2
#                                                     y0
#                                                         x1, x2, x3
#                                                     y1
#                                                         x1, x2, x3, x4
#                                             pose1.y0 and pose2.y0 will be extended (in export time) to match maximum size
#                                             pose1.y0 will get x3, x4 (x2 will be copied)
#                                             pose2.y0 will get x4 (x3 will be copied)
#
#-----------------------------------------------------------------------------------

import bpy
import os
import re
import math
import mathutils
from ..util import ddsUtil as ddsWriter
from . import dccBlender

g_prevQuat = None

def exportObjectDataTexture():
    dccBlender.UIAddMessage("exportObjectDataTexture:")
    processScene()

def processScene():
    m_shapeArrays = []
    for m_obj in bpy.data.objects:
        if ( isExported(m_obj) ):
            m_shapeArrays.append(shapeArray(m_obj))
    # =================================
    for m_shape in m_shapeArrays:
        m_shape.export()

class shapeArray(object):
    def __init__(self,m_obj):
        self.m_obj              = m_obj #bpy.data.object
        self.m_filepath         = ""
        self.m_x                = 1
        self.m_y                = 1
        self.m_z                = 1
        self.m_poseData         = []
        self.m_hierarchical     = False
        self.m_hideFirstAndLast = False
        self.m_exportPosition   = True
        self.m_exportOrient     = True
        self.m_exportScale      = False
        self.m_isValid          = True
        self.init()

    def init(self):
        self.m_filepath         = getFilePath(getAttributeValue(self.m_obj,"i3D_objectDataFilePath"))
        self.m_hierarchical     = getAttributeValue(self.m_obj,"i3D_objectDataHierarchicalSetup",self.m_hierarchical)
        self.m_hideFirstAndLast = getAttributeValue(self.m_obj,"i3D_objectDataHideFirstAndLastObject",self.m_hideFirstAndLast)
        self.m_exportPosition   = getAttributeValue(self.m_obj,"i3D_objectDataExportPosition",self.m_exportPosition)
        self.m_exportOrient     = getAttributeValue(self.m_obj,"i3D_objectDataExportOrientation",self.m_exportOrient)
        self.m_exportScale      = getAttributeValue(self.m_obj,"i3D_objectDataExportScale",self.m_exportScale)

    def export(self):
        #dccBlender.UIAddMessage("export: z:{} y:{} x:{}".format(self.m_z,self.m_y,self.m_x))
        #print(" ")
        if (self.m_hierarchical):
            self.shapeArrayGetHierarchical()
            self.shapeArrayValidateAndAdjust()
        else:
            self.shapeArrayGetFlat()
        #print("z:{} y:{} x:{}".format(self.m_z,self.m_y,self.m_x))
        self.shapeArraysExport()

    def shapeArraysExport(self):
        if not self.m_isValid:
            dccBlender.UIAddMessage("Export Failed")
            return False
        m_dataList = []
        m_arrayTmp = []
        for z in range(len(self.m_poseData)):
            if (self.m_exportPosition):
                # =================================
                # position
                m_arrayTmp.append("position{}".format(z))
                for y in range(self.m_y-1,-1,-1):
                    for x in range(self.m_x):
                        #i = x + y*self.m_x
                        m_dataItem = self.m_poseData[z][y][x]
                        for m_channel in range(4):
                            m_dataList.append(m_dataItem["position"][m_channel])
            if (self.m_exportOrient):
                # =================================
                # orient
                m_arrayTmp.append("orient{}".format(z))
                for y in range(self.m_y-1,-1,-1):
                    for x in range(self.m_x):
                        m_dataItem = self.m_poseData[z][y][x]
                        for m_channel in range(4):
                            m_dataList.append(m_dataItem["orient"][m_channel])
            if (self.m_exportScale):
                # =================================
                # scale
                m_arrayTmp.append("scale{}".format(z))
                for y in range(self.m_y-1,-1,-1):
                    for x in range(self.m_x):
                        m_dataItem = self.m_poseData[z][y][x]
                        for m_channel in range(4):
                            m_dataList.append(m_dataItem["scale"][m_channel])
        #print(m_arrayTmp)
        m_arraySize = len(m_arrayTmp)
        try:
            ddsWriter.writeCustomDDS(self.m_filepath, self.m_x, self.m_y, 4, m_arraySize, m_dataList)
            dccBlender.UIAddMessage("Exported: {}".format(self.m_filepath))
        except:
            dccBlender.UIAddMessage("Export Failed: {}".format(self.m_filepath))

    def shapeArrayGetFlat(self):
        #dccBlender.UIAddMessage("shapeArrayGetFlat: 1")
        self.m_x = len(self.m_obj.children)
        #dccBlender.UIAddMessage("shapeArrayGetFlat: len({})".format(len(self.m_obj.children)))
        m_arrayX = []
        m_arrayY = []
        m_arrayZ = []
        x = 0
        sortedZChilds = sorted(self.m_obj.children, key = lambda x: x.name)
        for child in sortedZChilds:
            #m_x = self.m_obj.children[x]
            m_dataItem = getDataItem(child)
            #dccBlender.UIAddMessage("m_dataItem: {}".format(m_dataItem))
            #
            # sets position.w to 0, used as visibility in the shader (apply before exporting data)
            #
            if (self.m_hideFirstAndLast):
                if (0==x or len(self.m_obj.children)-1 == x):
                    m_dataItem["position"][3] = 0.0
            #
            #dccBlender.UIAddMessage("m_dataItem: {}".format(3))
            m_arrayX.append(m_dataItem)
            x += 1
        m_arrayY.append(m_arrayX)
        m_arrayZ.append(m_arrayY)
        self.m_poseData = m_arrayZ
        #dccBlender.UIAddMessage("m_dataItem: {}".format(4))

    def shapeArrayGetHierarchical(self):
        # calculates x, y, z dimentions of the texture
        dccBlender.UIAddMessage("shapeArrayGetHierarchical: 1")
        m_arrayX = []
        m_arrayY = []
        m_arrayZ = []
        #
        # z dimention of the texture
        self.m_z = len(self.m_obj.children)
        sortedZChilds = sorted(self.m_obj.children, key = lambda x: x.name)
        for m_pose in sortedZChilds:

            # y dimention of the texture
            self.m_x = 0
            self.m_y = len(m_pose.children)
            m_arrayY = []
            sortedYChilds = sorted(m_pose.children, key = lambda x: x.name)
            for m_y in sortedYChilds:
                # x dimention of the texture
                # defined by the longest
                if self.m_x <= len(m_y.children):
                    self.m_x = len(m_y.children)
                m_arrayX = []
                sortedXChilds = sorted(m_y.children, key = lambda x: x.name)
                x = 0
                for m_x in sortedXChilds:
                    m_dataItem = getDataItem(m_x)

                    # sets position.w to 0, used as visibility in the shader (apply before exporting data)
                    #
                    if (self.m_hideFirstAndLast):
                        if (0==x or len(m_y.children)-1 == x):
                            m_dataItem["position"][3] = 0.0
                    #
                    m_arrayX.append(m_dataItem)
                    x += 1
                m_arrayY.append(m_arrayX)
                #print(m_yPath.fullPathName())
            m_arrayZ.append(m_arrayY)
        self.m_poseData = m_arrayZ

    def shapeArrayValidateAndAdjust(self):
        if (0 == len(self.m_poseData)):
            dccBlender.UIAddMessage("array has no z")
            self.m_isValid = False
            return self.m_isValid
        # validate y dimention of the texture
        for z in range(len(self.m_poseData)):
            if (0==len(self.m_poseData[z])):
                dccBlender.UIAddMessage("z:{} has no y".format(z))
                self.m_isValid = False
                return self.m_isValid
            if self.m_y != len(self.m_poseData[z]):
                dccBlender.UIAddMessage("y:{} != pose{}.y size:{}".format(self.m_y,z,len(self.m_poseData[z])))
                self.m_isValid = False
                return self.m_isValid
            for y in range(len(self.m_poseData[z])):
                if (0 == len(self.m_poseData[z][y])):
                    dccBlender.UIAddMessage("z:{} y:{} has no x".format(z,y))
                    self.m_isValid = False
                    return self.m_isValid
                #
                # missing x values in the texture are created by duplicating the last object value
                #
                m_last = self.m_poseData[z][y][-1]
                if len(self.m_poseData[z][y]) < self.m_x:
                    for m in range(self.m_x-len(self.m_poseData[z][y])):
                        self.m_poseData[z][y].append(m_last)
                #
                #print(len(self.m_poseData[z][y]),self.m_x)

    def _str_(self):
        #m_str += "{}\n".format(self.m_filepath)
        m_str = "z:{} y:{} x:{}".format(self.m_z,self.m_y,self.m_x)
        return m_str

    def __str__(self):
        return self._str_()

    def __str__(self):
        return self._str_()

def getDataItem(m_obj):
    m_poisition = getPosition(m_obj)
    m_orient    = getOrient(m_obj)
    m_scale     = getScale(m_obj)
    m_dataItem = {}
    m_dataItem["position"] = m_poisition
    m_dataItem["orient"]   = m_orient
    m_dataItem["scale"]    = m_scale
    return m_dataItem

def getPosition(m_obj):
    #dccBlender.UIAddMessage("getPosition: ")
    matrix= dccBlender.bakeTransformMatrix(m_obj.matrix_local)
    translation   = matrix.to_translation()[:] + (1.0,)
    return list(translation)

def getOrient(m_obj):
    #dccBlender.UIAddMessage("getOrient: ")
    global g_prevQuat

    if bpy.context.scene.TOOLS_UIMotionPath.motionTypes == 'MOTION_PATH':
        m_rx = m_obj.rotation_euler[0]
        m_ry = m_obj.rotation_euler[1]
        m_rz = m_obj.rotation_euler[2]
        rotationQuad = eulerToQuaternion(m_rz, m_ry, m_rx)
        rotation = rotationQuad[:]
        rotCor = list(map(lambda x: round(x,6),(rotation[0],rotation[1],rotation[2],rotation[3])))      #DDS quaternion is x,y,z,w
    else:
        matrix= dccBlender.bakeTransformMatrix(m_obj.matrix_local)
        rotationQuad = matrix.to_euler().to_quaternion()     #blender quaternion is w,x,y,z
        if g_prevQuat != None:
            rotationQuad.make_compatible(g_prevQuat)
        g_prevQuat = rotationQuad
        rotation = rotationQuad[:]
        rotCor = list(map(lambda x: round(x,6),(rotation[1],rotation[2],rotation[3],rotation[0])))      #DDS quaternion is x,y,z,w
    #dccBlender.UIAddMessage("getOrient: obj({}) mat({})".format(m_obj, matrix))
    #print("getOrient: obj({}) mat({})".format(m_obj, matrix))
    #rotCor = list(map(lambda x: round(x,6),(rotation[1],rotation[2],rotation[3],rotation[0])))      #DDS quaternion is x,y,z,w
    return rotCor


def getScale(m_obj):
    #dccBlender.UIAddMessage("getScale: ")
    matrix= dccBlender.bakeTransformMatrix(m_obj.matrix_local)
    scale          = matrix.to_scale()[:] + (1.0,)
    return list(scale)

def eulerToQuaternion(rx,ry,rz):
    cy = math.cos(rx * 0.5);
    sy = math.sin(rx * 0.5);
    cp = math.cos(ry * 0.5);
    sp = math.sin(ry * 0.5);
    cr = math.cos(rz * 0.5);
    sr = math.sin(rz * 0.5);
    q = [0.0,0.0,0.0,0.0];
    q[3] = cy * cp * cr + sy * sp * sr;
    q[0] = cy * cp * sr - sy * sp * cr;
    q[1] = sy * cp * sr + cy * sp * cr;
    q[2] = sy * cp * cr - cy * sp * sr;
    return q;

def isAttributeExists(m_obj,m_attrStr):
    return m_attrStr in m_obj

def getAttributeValue(m_obj,m_attrStr,m_default=None):
    if isAttributeExists(m_obj,m_attrStr):
        return m_obj[m_attrStr]
    return m_default

def isExported( m_obj ):
    if (isAttributeExists(m_obj,"i3D_objectDataFilePath")):
        if "" != getAttributeValue(m_obj,"i3D_objectDataFilePath"):
            return True
    return False

def getFilePath(m_str):
    path = bpy.path.ensure_ext( os.path.splitext(bpy.data.filepath)[0].rsplit("\\",1)[0] +"\\"+ m_str, ".dds" )
    return path

