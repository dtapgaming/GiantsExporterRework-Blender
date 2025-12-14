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

import bpy, bmesh
from ctypes import c_int, c_float, c_void_p, c_short, \
    c_char, c_char_p, c_uint, POINTER, Structure
from time import monotonic
import os
import re
import math, mathutils
from ..util import logUtil, i3d_densityUtil, selectionUtil, i3d_shaderUtil
from ..util import i3d_directoryFinderUtil as dirf
import copy
import numpy as np
from .. import i3d_globals
from ..helpers.pathHelper import getGamePath
from ..util import pathUtil

version_ctypes_interface = bpy.app.version[:2]

def getSpecularVariableName():
    specularName = 'Specular'
    if version_ctypes_interface >= (4, 0):
        specularName = 'Specular IOR Level'
    return specularName

def getEmissionVariableName():
    emissionName = 'Emission'
    if version_ctypes_interface >= (4, 0):
        emissionName = 'Emission Color'
    return emissionName

def getFilePath():
    return bpy.path.ensure_ext( os.path.splitext(bpy.data.filepath)[0], ".i3d" )    #remove .blend from path

def getFileBasename():
    return bpy.path.basename( bpy.data.filepath )

def getAbsPath(path):
    return bpy.path.abspath(path)

def isFileSaved():
    if bpy.data.filepath:
        return True
    else:
        return False

def appVersion():
    return bpy.app.version

def UISetLoadedNode(nodeStr):
    if(nodeStr in bpy.data.objects):
        node = bpy.data.objects[nodeStr]
        UISetAttrString("i3D_nodeName",node.name)
        UISetAttrString("i3D_nodeIndex",getNodeIndex(node.name))

def UIGetLoadedNode():
    objPath = UIGetAttrString("i3D_nodeName")
    if (objPath in bpy.data.objects):
        return objPath
    else:
        return None

def I3DAddAttrBool(nodeStr,attr):
    I3DSetAttrBool(nodeStr,attr,bool(False))

def I3DSetAttrBool(nodeStr,attr,val):
    node = bpy.data.objects[nodeStr]
    node[attr] = val

def I3DAddAttrInt(nodeStr,attr):
    I3DSetAttrInt(nodeStr,attr,int(0))

def I3DSetAttrInt(nodeStr,attr,val):
    node = bpy.data.objects[nodeStr]
    node[attr] = val

def I3DAddAttrFloat(nodeStr,attr):
    I3DSetAttrFloat(nodeStr,attr,float(0.0))

def I3DSetAttrFloat(nodeStr,attr,val):
    m_node = bpy.data.objects[nodeStr]
    m_node[attr] = round(val, 6)     #gui elements are not very exact

def I3DAddAttrString(nodeStr,attr):
    I3DSetAttrString(nodeStr,attr,str(""))

def I3DSetAttrString(nodeStr,attr,val):
    node = bpy.data.objects[nodeStr]
    node[attr] = val

def I3DAddAttrEnum(nodeStr,attr):
    I3DSetAttrEnum(nodeStr,attr,"None")

def I3DSetAttrEnum(nodeStr, attr, val):
    node = bpy.data.objects[nodeStr]
    node[attr] = val

def I3DGetAttr(nodeStr, attr):
    node = bpy.data.objects[nodeStr]
    if(attr == "I3D_boundingVolume" and node[attr] == ""):    #backwards compatibility
        node[attr] = 'None'
    return node[attr]

def I3DAttributeExists(nodeStr, attr):
    if nodeStr in bpy.data.objects:
        m_node = bpy.data.objects[nodeStr]
        if (attr in m_node):
            return True
    return False

def I3DRemoveAttribute(nodeStr, attr):
    node = bpy.data.objects[nodeStr]
    if(I3DAttributeExists(nodeStr, attr)):
        del node[attr]

def getXMLConfigID(nodeStr, boneStr=""):
    try:
        if bpy.data.objects[nodeStr].type == 'ARMATURE':
            return bpy.data.objects[nodeStr].data.bones[boneStr]["I3D_XMLconfigID"]
        return bpy.data.objects[nodeStr]["I3D_XMLconfigID"]
    except:
        return nodeStr

def getXMLConfigBool(nodeStr, boneStr=""):
    try:
        if bpy.data.objects[nodeStr].type == 'ARMATURE':
            return bpy.data.objects[nodeStr].data.bones[boneStr]["I3D_XMLconfigBool"] == 1
        return bpy.data.objects[nodeStr]["I3D_XMLconfigBool"] == 1
    except:
        return False

def UIAttrExists(attr):
    try:
        m_str = "bpy.context.scene.I3D_UIexportSettings.{0}".format(attr)
        eval(m_str)
        return True
    except Exception as exception:
        UIShowError(exception)
        return False

def UIGetAttrBool(key):
    m_str = "bpy.context.scene.I3D_UIexportSettings.{0}".format(key)
    return eval(m_str)

def UISetAttrBool(key,val):
    bpy.context.scene.I3D_UIexportSettings[key] = val
    #m_str = "bpy.context.scene.I3D_UIexportSettings.{0}=bool({1})".format(key,val)
    #exec(m_str)

def UIGetAttrInt(key):
    m_str = "bpy.context.scene.I3D_UIexportSettings.{0}".format(key)
    return eval(m_str)

def UISetAttrInt(key, val):
    m_str = "bpy.context.scene.I3D_UIexportSettings.{0}=int({1})".format(key,val)
    exec(m_str)

def UIGetAttrFloat(key):
    m_str = "bpy.context.scene.I3D_UIexportSettings.{0}".format(key)
    return eval(m_str)

def UISetAttrFloat(key, val):
    m_str = "bpy.context.scene.I3D_UIexportSettings.{0}=float({1})".format(key,val)
    exec(m_str)

def UIGetAttrString(key):
    return getattr(bpy.context.scene.I3D_UIexportSettings, key)

def UISetAttrString(key, val):
    setattr(bpy.context.scene.I3D_UIexportSettings, key, str(val))

def UIGetAttrEnum(key):
    string = "bpy.context.scene.I3D_UIexportSettings.{0}".format(key)
    return eval(string)

def UISetAttrEnum(key, val):
    if (val is not None and val != ""):
        UISetAttrString(key,val)

def UIShowError(errorMsg):
    if (UIGetAttrBool('i3D_exportVerbose')):
        # print("Error: {0}".format(errorMsg))
        logUtil.ActionLog.addMessage(errorMsg, messageType = 'ERROR')

def UIShowWarning(warningMsg):
    if (UIGetAttrBool('i3D_exportVerbose')):
        # print("Warning: {0}".format(warningMsg))
        logUtil.ActionLog.addMessage(warningMsg,messageType = 'WARNING')

def UIAddMessage(msg):
    if (UIGetAttrBool('i3D_exportVerbose')):
        # print(msg)
        logUtil.ActionLog.addMessage(msg)



def getSelectedNodes():
    """ Returns a list of all bpy.context.selected_objects names. """

    return selectionUtil.getSelectedNodes()


def getSelectedNodesToExport():
    """ Returns a list with all bpy.context.selected_objects and its parents. """

    iterItems = []
    nodes = getSelectedNodes()
    for nodeStr in nodes:
        if nodeStr is None or nodeStr == "":
            continue
        if nodeStr not in iterItems:
            iterItems.append(nodeStr)
            addParentNodeToList(nodeStr,iterItems)
    iterItems.sort(key=natural_keys)
    return iterItems

def addParentNodeToList(nodeStr,iterItems):
    """ Appends all parents of bpy.data.object[nodeStr] up to the root to iterItems. """

    # SAFEGUARD: ignore None/empty node names.
    if nodeStr is None or nodeStr == "":
        return iterItems

    parentStr = getParentObjectWithoutWorld(nodeStr)
    if (parentStr):
        if (parentStr not in iterItems):
            iterItems.append(parentStr)
        addParentNodeToList(parentStr, iterItems)
    else:
        return iterItems

def isParentedToWorld(nodeStr):
    """ Returns True if there exists no parent. """

    node = bpy.data.objects[nodeStr]
    parent = node.parent
    if (None==parent):
        return True
    else:
        return False

def getAllNodesToExport():
    """ Returns a list with all bpy.data.objects names """

    result = []
    nodes = getWorldObjects()
    addChildObjects(nodes,result)
    return result

def getParentObjectWithoutWorld(nodeStr):
    """ Returns the parent object name of nodeStr if existing """

    # SAFEGUARD: never index bpy_prop_collection with None/empty.
    if nodeStr is None or nodeStr == "":
        return None

    try:
        node = bpy.data.objects[nodeStr]
    except Exception:
        return None

    # if parented to the world return None
    if node.parent:
        return node.parent.name
    else:
        return None

def getChildObjects(parentStr):
    """ Returns a list of all bpy.data.objects[parentStr].children names. """

    # SAFEGUARD: never index bpy_prop_collection with None/empty.
    if parentStr is None or parentStr == "":
        return []

    try:
        parent = bpy.data.objects[parentStr]
    except Exception:
        return []

    iterItems = []

    for node in parent.children:
        iterItems.append(node.name)
    iterItems.sort(key=natural_keys)
    return iterItems

def getNodeInstances(nodeStr):
    """ Returns [], only placeholder implementation """

    nodes = []
    return nodes

def getFormattedNodeName(nodeName):
    """ Formats a given node name for export (removal of sorting prefix) """
    return nodeName.split(":")[-1]

def getNodeName(nodeStr):
    """ Get bpy.data.object[].name """

    return getFormattedNodeName(bpy.data.objects[nodeStr].name)

def getNodeData(nodeStr, nodeData = {}):
    """ returns a dictionary with the basic data of the bpy.data.objects[nodeStr] object"""

    nodeObj = bpy.data.objects[nodeStr]
    nodeData["fullPathName"] = nodeObj.name
    nodeData["name"] = getNodeName(nodeStr)
    nodeData["type"] = getNodeType(nodeStr)
    return nodeData

def getBoneData(boneStr, armStr, nodeData = {}):
    """ Gets bpy.data of the requested bone and writes it to nodeData """

    boneObj = bpy.data.objects[armStr].data.bones[boneStr]
    nodeData["fullPathName"] = armStr + "_" + boneObj.name
    nodeData["name"] = boneObj.name
    return nodeData

def transformPath(objStr, inverted = False):
    """ Recursively calculates the translation of the objStr object to the root object"""

    obj = bpy.data.objects[objStr]
    objMat = obj.matrix_local
    if ( "BAKE_TRANSFORMS"  == UIGetAttrString('i3D_exportAxisOrientations')): #meshTransformation
        objMat = bakeTransformMatrix(objMat)
    if obj.parent:
        if inverted:
            return (objMat.inverted() @ transformPath(obj.parent.name, inverted= inverted)).inverted()
        else:
            return objMat @ transformPath(obj.parent.name)
    else:
        if inverted:
            return objMat.inverted()
        else:
            return objMat

def getMergeGroupShapeData(shapeNameStr, shapeData, sceneNodeData):
    """
    Merges the shape data of multiple shapes according to the settings provided

    differs i3D_mergeChildren and others which should be merge groups. These two modes are very similar, but request slightly different datasets
    merge Children merges all children objects, merge groups combines all objects from ["mergeGroupMember"]

    :param shapeNameStr: the name of the shape
    :param shapeData: the dictionary for the return value
    :param sceneNodeData: the SceneNodeData with the detailed export settings
    :returns: dictionary shapeData
    """

    mergeChildrevDivider = 32767    #fixed value
    if ("i3D_mergeChildren" in sceneNodeData):  #mergeChildren
        rootName = "ORIGIN"
        mergeData = {}
        #shapeNameStr is MergedChildren
        for i in range(len(sceneNodeData["children"])):
            child = sceneNodeData["children"][i]
            g = i/mergeChildrevDivider
            freezeRot = False
            freezeTrans = False
            freezeScale = False
            if 'i3D_mergeChildrenFreezeRotation' in sceneNodeData:
                freezeRot = sceneNodeData['i3D_mergeChildrenFreezeRotation'] == 1
                rootName = shapeNameStr
            if 'i3D_mergeChildrenFreezeTranslation' in sceneNodeData:
                freezeTrans = sceneNodeData['i3D_mergeChildrenFreezeTranslation'] == 1
                rootName = shapeNameStr
            if 'i3D_mergeChildrenFreezeScale' in sceneNodeData:
                freezeScale = sceneNodeData['i3D_mergeChildrenFreezeScale'] == 1
                rootName = shapeNameStr
            memberResult = getMergeMemberShapeData(child, float(g),rootName,freezeTrans,freezeRot,freezeScale)      # g is a multiple of 1/32767, one g value per mesh, detect empty for a g increase
            if memberResult:
                if ("i3D_cpuMesh" in sceneNodeData):
                    memberResult["meshUsage"] = getMeshUsage(sceneNodeData["i3D_cpuMesh"])
                if i == 0:
                    shapeData = memberResult
                    mergeData[i] = memberResult
                else:
                    mergeData[i] = memberResult

        if (not overrideBV(shapeNameStr, shapeData, sceneNodeData)):
            #BV-values loop
            bVmergeData = {}
            for i in range(len(sceneNodeData["children"])):
                child = sceneNodeData["children"][i]
                bvMemberResult = getMergeMemberShapeData(child, float(0),shapeNameStr, True,True,True)      # g is a multiple of 1/32767 one g value per mesh, detect empty for a g increase
                if bvMemberResult:
                    bVmergeData[i] = bvMemberResult
            vSum = mathutils.Vector((0,0,0))
            bvCenter = mathutils.Vector((0,0,0)) #TODO: check init value
            bvRadius = 0
            vCount = 0
            # print([vert["p"] for vert in [vertItem for vertItemsLists in [i["Vertices"]["data"] for k,i in bVmergeData.items()] for vertItem in vertItemsLists]])
            vertPos = [vert["p"] for vert in [vertItem for vertItemsLists in [i["Vertices"]["data"] for k,i in bVmergeData.items()] for vertItem in vertItemsLists]]
            for v in vertPos:
                pos = v.strip().split(" ")
                vSum += mathutils.Vector((float(pos[0]),float(pos[1]),float(pos[2])))        #x,y,z vector
                vCount += 1
                bvCenter = vSum / vCount
            for v in vertPos:
                pos = v.strip().split(" ")
                vect = bvCenter - mathutils.Vector((float(pos[0]),float(pos[1]),float(pos[2])))
                bvRadius = max(vect.length, bvRadius )

            shapeData["bvCenter"] = "{:g} {:g} {:g}".format(bvCenter.x,bvCenter.y,bvCenter.z)
            shapeData["bvRadius"] = "{:g}".format(bvRadius)

        shapeData['name'] = "MergedChildren{:d}".format(sceneNodeData["id"])       # rename the shape to MergedChildrenX
        shapeData['isOptimized'] = "false"
    else:   #mergeGroup
        rootName = getMeshOwners(shapeNameStr)[0]
        mergeData = {}
        skinBindNodeIds = []
        shapeData = {}  # Initialize to an empty dict as default

        # Making sure the root is the first entry in the mergeData dict
        rootIndex = sceneNodeData["mergeGroupMember"].index(rootName)
        rootMemberId = sceneNodeData['skinBindNodeIds'][rootIndex]
        rootMemberResult = getMergeMemberShapeData(rootName, int(rootIndex), rootName, True, True, True)
        mergeData[rootIndex] = rootMemberResult
        skinBindNodeIds.insert(0, rootMemberId)
        shapeData = rootMemberResult  # Initialize shapeData with root data

        # Rest of the merge group members
        for index, memberNameStr in enumerate(sceneNodeData["mergeGroupMember"]):
            if memberNameStr == rootName:
                # Skip the root since it's already handled
                continue
            memberId = sceneNodeData['skinBindNodeIds'][index]
            memberResult = getMergeMemberShapeData(memberNameStr, int(index), rootName, True, True, True)
            mergeData[index] = memberResult
            skinBindNodeIds.append(memberId)
        overrideBV(shapeNameStr, shapeData, sceneNodeData)
        shapeData['name'] = f"mergeGroupShape{sceneNodeData['mergeGroupNum']:d}"
        shapeData['isOptimized'] = "false"
        shapeData['skinBindNodeIds'] = " ".join(map(str, skinBindNodeIds))

    if 'i3D_vertexCompressionRange' in sceneNodeData:
        shapeData['vertexCompressionRange'] = sceneNodeData['i3D_vertexCompressionRange']

    #merge results
    #integrate all items of mergeData into the shapeData structure
    finalVertexBuffer = []
    finalIndexBuffer = []
    finalSubsets = []
    finalMaterials = []
    finalTriangles = []
    vertexBufferDict = {}
    indexBufferDict = {}
    for k, item in mergeData.items():
        vertexBuffer = []
        indexBuffer = []
        for vertex in item["Vertices"]['data']:
            vertexBuffer.append(vertex)
            # if a child has color set -> enable color for whole merged group
            if "c" in vertex:
                shapeData["Vertices"]["color"] = "true"
        for triangle in item["Triangles"]['data']:
            for trianlgeEntry in triangle.values():
                for index in trianlgeEntry.strip().split(" "):
                    indexBuffer.append(int(index))
        vertexBufferDict[k] = vertexBuffer
        indexBufferDict[k] = indexBuffer
    # for vB in vertexBufferDict.values():
        # print(vB)
    # for iB in indexBufferDict.values():
        # print(iB)
    materialList = []
    materialSlotNames = []
    for k, item in mergeData.items():
        for matId, material in enumerate(item["Materials"]):
            if not material in materialList:
                materialList.append(material)
                materialSlotNames.append(item["MaterialSlotNames"][matId])

    baseVertexIndex = 0
    baseIndexIndex = 0
    for matId, material in enumerate(materialList):
        subsetDict = {}
        #find subsets to material
        for k, item in mergeData.items():
            if material in item["Materials"]:
                subsetDict[k] = item["Subsets"]["data"][item["Materials"].index(material)]
        # print(subsetDict)
        #put all data of subset together
        mergeSubset = {"firstVertex" : str(baseVertexIndex),"numVertices": "0", "firstIndex":str(baseIndexIndex), "numIndices": "0"}
        if materialSlotNames[matId] is not None and materialSlotNames[matId] != "":
            mergeSubset["materialSlotName"] = materialSlotNames[matId]
        for k, subsets in subsetDict.items():
            numVertices = int(subsets["numVertices"])
            numIndices = int(subsets["numIndices"])
            vertexList = vertexBufferDict[k][int(subsets["firstVertex"]):int(subsets["firstVertex"])+numVertices]
            indexList = indexBufferDict[k][int(subsets["firstIndex"]):int(subsets["firstIndex"])+numIndices]
            minIndexList = min(indexList)
            indexList = [i-minIndexList+baseVertexIndex for i in indexList]   #normalize count to start by zero and apply offset
            # print("baseIndexIndex: {}, baseVertexIndex: {}, ".format(baseIndexIndex,baseVertexIndex))
            # print("index first: {}, num: {} \nindexList: {}".format(subsets["firstIndex"],int(subsets["firstIndex"])+numIndices,indexList))
            # print("vertex first: {}, num: {} \nvertexList: {}".format(subsets["firstVertex"],int(subsets["firstVertex"])+numVertices,vertexList))
            finalIndexBuffer+=indexList
            finalVertexBuffer+=vertexList
            mergeSubset["numVertices"] = "{}".format(int(mergeSubset["numVertices"]) + numVertices)
            mergeSubset["numIndices"] = "{}".format(int(mergeSubset["numIndices"]) + numIndices)
            baseVertexIndex += numVertices
            baseIndexIndex += numIndices

        finalSubsets.append(mergeSubset)
        finalMaterials.append(material)

    # print(finalMaterials)
    # for i in finalSubsets:
        # print("i:{}".format(i))
    # print("{} entries".format(len(finalIndexBuffer)))
    # print(finalIndexBuffer)
    # print("{} vertices".format(len(finalVertexBuffer)))
    # for i in finalVertexBuffer:
        # print("vertex: {}".format(i))
    #overwrite shapeData with final values

    if ("i3D_mergeChildren" in sceneNodeData):  #mergeChildren material behavior like maya exporter
        if len(finalMaterials) == 0:
            shapeData["Materials"] = ["default"]
        else:
            shapeData["Materials"] = [finalMaterials[0]]
    else:
        shapeData["Materials"] = finalMaterials
    shapeData["Subsets"]['data'] = finalSubsets
    shapeData["Subsets"]["count"] = str(len(finalSubsets))

    for i in range(0,len(finalIndexBuffer),3):
        finalTriangles.append({"vi" : "{} {} {}".format(finalIndexBuffer[i],finalIndexBuffer[i+1],finalIndexBuffer[i+2])})
    # print("finalTriangles: {}".format(finalTriangles))
    shapeData["Triangles"]['data'] = finalTriangles
    shapeData["Triangles"]['count'] = str(len(finalTriangles))
    shapeData["Vertices"]['data'] = finalVertexBuffer
    shapeData["Vertices"]['count'] = str(len(finalVertexBuffer))
    #uvDensity
    for subset in finalSubsets:
        subset.update(i3d_densityUtil.computeUvDensity(shapeData["Triangles"]["data"],shapeData["Vertices"],int(subset["firstIndex"]),int(subset["numIndices"])))

    if ("i3D_mergeChildren" in sceneNodeData):  #mergeChildren
        shapeData["Vertices"]["generic"] = "true"
    else:
        shapeData["Vertices"]["singleblendweights"] = "true"

    return shapeData

def getMergeMemberShapeData(shapeNameStr, specialValue, rootStr, applyTrans, applyRot, applyScale):
    """
    Returns all data necessary to write the xml output file in the case the shape object is root of a merge group.
    vertices are transformed to root space.

    :param shapeNameStr: Name of the shape
    :param specialValue: the special value, dependent if it is called for a merge children or merge group
    :param rootStr: the name of the root object
    :returns: a dictionary with all necessary shape data
    """

    shapeData = {}
    try:
        mesh = bpy.data.meshes[bpy.data.objects[shapeNameStr].data.name]
        shapeData["name"] = mesh.name
    except:
        return None
    # --- generate exporting mesh
    meshOwners = getMeshOwners(bpy.data.objects[shapeNameStr].data.name)
    ownerObj = bpy.data.objects[meshOwners[0]]

    nodeVisible = isNodeVisible(ownerObj.name)
    if not nodeVisible:
        ownerObj.hide_set(False)

    for modifier in ownerObj.modifiers:    #cannot have skinning and merge shapes
        if modifier.type == 'ARMATURE':
            raise Exception("Cannot have armature and merge shapes within the same Object")

    m_meshGen = getMeshFromDepsGraph(ownerObj, UIGetAttrString('i3D_exportApplyModifiers'))

    # -------------------------------------------------------------
    # --------------------------------------------
    # Snow Heap mode flag from UI
    useSnowHeap = False
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        ui_settings = getattr(scene, "I3D_UIexportSettings", None)
        if ui_settings is not None:
            useSnowHeap = getattr(ui_settings, "i3D_exportSnowHeapMode", False)

    m_vtxColorLayerName = None

    # --- calculate triangles and normals with applied modifiers
    m_meshGen.calc_loop_triangles()
    if version_ctypes_interface < (4, 1):
        m_meshGen.calc_normals_split()

    # -------------------------------------------------------------
    #--- root -> member transformation
    if rootStr == 'ORIGIN':
        matrixTransform = mathutils.Matrix.Identity(4)
    else:
        l2 = bpy.data.objects[shapeNameStr].matrix_world
        l1 = bpy.data.objects[rootStr].matrix_world
        matrixTransform = l1.inverted() @ l2
        translation, rotationQuat, scale = matrixTransform.decompose()
        if applyTrans:
            translationMat = mathutils.Matrix.Translation(translation)
        else:
            translationMat = mathutils.Matrix.Translation((0.0, 0.0, 0.0))      #identity
        if applyRot:
            rotationMat = rotationQuat.to_matrix().to_4x4()
        else:
            rotationMat = mathutils.Matrix.Rotation(math.radians(0.0), 4, 'X')  #identity
        if applyScale:
            scaleMat = mathutils.Matrix.Diagonal(scale).to_4x4()
        else:
            scaleMat = mathutils.Matrix.Scale(1, 4)                             #identity
        matrixTransform = translationMat @ rotationMat @ scaleMat

    # -------------------------------------------------------------
    materialsList, materialSlotNames = getShapeMaterials(m_meshGen.name)
    m_materials = {}
    for mat in materialsList:
        m_materials[mat] = []
    if (len(materialsList) > 1):
        for m_triangle in m_meshGen.loop_triangles:
            m_mat = m_meshGen.materials[m_triangle.material_index]
            if None == m_mat:
                m_mat = "default"
            else:
                m_mat = m_mat.name
            m_materials[m_mat].append(m_triangle.index)
    else:
        for m_triangle in m_meshGen.loop_triangles:
            m_materials[materialsList[0]].append(m_triangle.index)

    # -------------------------------------------------------------
    m_vertices  = {}
    m_triangles = {}
    m_subsets   = {}
    m_vertices["data"]  = []
    m_triangles["data"] = []
    m_subsets["data"]   = []
    # -------------------------------------------------------------
    if UIGetAttrBool("i3D_exportNormals"):
        m_vertices["normal"] = "true"
    if UIGetAttrBool("i3D_exportColors"):
        m_vtxColorLayerName = getRenderColorName(m_meshGen.name)
        if (m_vtxColorLayerName):
            m_vertices["color"] = "true"
    # SnowHeap Mode: enforce vertex colors
    if useSnowHeap:
        color_attrs = getattr(m_meshGen, "color_attributes", None)
        if not color_attrs or len(color_attrs) == 0:
            UIShowError(
                "No Vertex Color detected during export while Snow Heap Mode is enabled.\n\n"
                "Use the 'Bake Deltas to Vertex Colors' tool first, or disable "
                "'Snow Heap Mode' if this mesh is not a snow heap."
            )
            return None

        # If no layer chosen yet, pick the first available color layer
        if not m_vtxColorLayerName:
            try:
                m_vtxColorLayerName = list(color_attrs.keys())[0]
            except Exception:
                m_vtxColorLayerName = None

        if m_vtxColorLayerName:
            m_vertices["color"] = "true"

    if UIGetAttrBool("i3D_exportTexCoords"):
        for m_i in range( len(m_meshGen.uv_layers) ):
            if m_i == 4: break
            m_str = "uv{:d}".format(m_i)
            m_vertices[m_str] = "true"

    # -------------------------------------------------------------
    bakeTransforms = "BAKE_TRANSFORMS" == UIGetAttrString('i3D_exportAxisOrientations')
    normalInVert = "normal" in m_vertices
    colorInVert = "color" in m_vertices
    uv0InVert = "uv0" in m_vertices
    uv1InVert = "uv1" in m_vertices
    uv2InVert = "uv2" in m_vertices
    uv3InVert = "uv3" in m_vertices
    blendweightsInVert = "blendweights" in m_vertices

    m_indexBuffer    = {}
    m_currentIndex   = 0
    m_firstIndex     = 0
    m_numVerticesSet = set()
    m_trainglesCount = 0
    m_subsetsCount   = 0
    m_counter        = 0
    for matId, m_mat in enumerate(materialsList):
        m_matItem = m_materials[m_mat]
        m_trainglesCount += len( m_matItem )
        m_subsetsCount  += 1
        m_numIndices    = 0
        m_numVerticesSet.clear()
        for m_primIndex in m_matItem:
            m_triangle = m_meshGen.loop_triangles[ m_primIndex ]
            m_strVI = ''
            for m_loopIndex in m_triangle.loops:
                m_loop        = m_meshGen.loops[m_loopIndex]
                m_vertexIndex = m_loop.vertex_index
                m_vertItem = {}
                # convert to root local space
                posMat =  mathutils.Matrix.Translation(m_meshGen.vertices[ m_vertexIndex ].co.xyz)
                posMat =  matrixTransform @ posMat
                m_pos = posMat.to_translation()
                if (bakeTransforms): # x z -y
                    m_pos = ( m_pos[0], m_pos[2], -m_pos[1] )
                m_vertItem["p"] = "{:g} {:g} {:g}".format(m_pos[0],m_pos[1],m_pos[2])
                if (normalInVert):
                    normalMat = mathutils.Matrix.Translation(m_loop.normal)

                    rotMat = matrixTransform.to_euler().to_matrix().to_4x4()
                    normalMat = rotMat @ normalMat
                    m_value = normalMat.to_translation()[:]
                    if (bakeTransforms): # x z -y
                        m_value = ( m_value[0], m_value[2], -m_value[1] )
                    m_vertItem["n"] = "{:g} {:g} {:g}".format(m_value[0],m_value[1],m_value[2])
                if (colorInVert):
                    # SnowHeap Mode: use linear vertex colors (no sRGB conversion) so (2*color-1) deformation behaves like FS22
                    try:
                        colorAttr = m_meshGen.color_attributes[m_vtxColorLayerName].data[m_loop.index]
                        if useSnowHeap:
                            col = colorAttr.color
                            colorSRGB = (col[0], col[1], col[2], col[3])
                        else:
                            colorSRGB = colorAttr.color_srgb
                    except Exception:
                        colorSRGB = (1.0, 1.0, 1.0, 1.0)
                    m_vertItem["c"] = "{:g} {:g} {:g} {:g}".format(colorSRGB[0], colorSRGB[1], colorSRGB[2], colorSRGB[3])
                if (uv0InVert):
                    m_value = m_meshGen.uv_layers[0].data[m_loopIndex].uv
                    m_vertItem["t0"] = "{:g} {:g}".format(m_value[0],m_value[1])
                if (uv1InVert):
                    m_value = m_meshGen.uv_layers[1].data[m_loopIndex].uv
                    m_vertItem["t1"] = "{:g} {:g}".format(m_value[0],m_value[1])
                if (uv2InVert):
                    m_value = m_meshGen.uv_layers[2].data[m_loopIndex].uv
                    m_vertItem["t2"] = "{:g} {:g}".format(m_value[0],m_value[1])
                if (uv3InVert):
                    m_value = m_meshGen.uv_layers[3].data[m_loopIndex].uv
                    m_vertItem["t3"] = "{:g} {:g}".format(m_value[0],m_value[1])

                if type(specialValue) == float:
                    m_vertItem["g"] = "{:g}".format(specialValue)
                elif type(specialValue) == int:
                    m_vertItem["bi"] = "{:g}".format(specialValue)
                m_indexData = IndexBufferItem(m_vertItem,m_mat)
                if ( m_indexData not in m_indexBuffer ):
                    m_indexBuffer[ m_indexData ] = m_counter
                    m_counter += 1
                    m_vertices["data"].append(m_vertItem)
                m_currentIndexVertex = m_indexBuffer[ m_indexData ]
                m_strVI  += " {:d}".format(m_currentIndexVertex)
                if ( 0 == m_numIndices ):
                    m_firstIndex  = m_currentIndex
                m_numVerticesSet.add( m_currentIndexVertex )
                m_currentIndex += 1
                m_numIndices   += 1
            m_triItem = {}
            m_triItem["vi"] = m_strVI.strip()
            m_triangles["data"].append(m_triItem)
        m_subsetItem = {}
        m_subsetItem["firstVertex"] = "{:g}".format(min(m_numVerticesSet))
        m_subsetItem["numVertices"] = "{:g}".format(len(m_numVerticesSet))
        m_subsetItem["firstIndex"]  = "{:g}".format(m_firstIndex)
        m_subsetItem["numIndices"]  = "{:g}".format(m_numIndices)
        if materialSlotNames[matId] != None:
            m_subsetItem["materialSlotName"] = materialSlotNames[matId]
        m_subsets["data"].append(m_subsetItem)
    m_vertices["count"]  = "{:g}".format(len(m_indexBuffer))
    m_triangles["count"] = "{:g}".format(m_trainglesCount)
    m_subsets["count"]   = "{:g}".format(m_subsetsCount)
    shapeData["Materials"] = materialsList
    shapeData["MaterialSlotNames"] = materialSlotNames
    shapeData["Vertices"]  = m_vertices
    shapeData["Triangles"] = m_triangles
    shapeData["Subsets"]   = m_subsets
    if not nodeVisible:
        ownerObj.hide_set(True)

    return shapeData

def overrideBV(m_shapeStr,m_nodeData, m_sceneNodeData):
    if "boundingVolume" in m_sceneNodeData:
        target_obj = bpy.data.objects[m_sceneNodeData['fullPathName']]
        bv_obj = bpy.data.objects[m_sceneNodeData["boundingVolume"]]
        # Compute the local center of the BV by averaging the corner points of the object
        bv_local_center = sum((mathutils.Vector(b) for b in bv_obj.bound_box), mathutils.Vector()) / 8
        # Transform the local center to world space coordinates
        bv_world_center = bv_obj.matrix_world @ bv_local_center
        # Calculate the offset of the BV center in the local space of the target object
        bv_center_offset_local = target_obj.matrix_world.inverted() @ bv_world_center
        bv_radius = max(bv_obj.dimensions) / 2
        bv_center_coord = f"{bv_center_offset_local.x:g} {bv_center_offset_local.z:g} {-bv_center_offset_local.y:g}"
        m_nodeData["bvCenter"] = bv_center_coord
        m_nodeData["bvRadius"] = f"{bv_radius:g}"
        return True
    return False

def getShapeData(m_shapeStr,m_nodeData, m_sceneNodeData):
    """
    Returns all data necessary to write the xml output file in the case the shape object is root of a merge group.
    vertices are transformed to root space.

    :param m_shapeStr: Name of the shape
    :param m_nodeData: the dictionary for the return value
    :param m_sceneNodeData: the SceneNodeData with the detailed export settings
    :returns: a dictionary with all necessary shape data
    """
    if("mergeGroupMember" in m_sceneNodeData) or ("i3D_mergeChildren" in m_sceneNodeData):   #mergeGroupRoot or mergeChildren
        return getMergeGroupShapeData(m_shapeStr,m_nodeData, m_sceneNodeData)

    # override BV
    overrideBV(m_shapeStr,m_nodeData, m_sceneNodeData)

    m_mesh = bpy.data.meshes[m_shapeStr]
    m_nodeData["name"] = m_mesh.name
    meshOwners = getMeshOwners(m_shapeStr)
    m_obj = bpy.data.objects[meshOwners[0]]

    nodeVisible = isNodeVisible(m_obj.name)
    if not nodeVisible:
        m_obj.hide_set(False)
    # --- generate exporting mesh
    #original or without modifier and animation applied
    m_meshGen = getMeshFromDepsGraph(m_obj, UIGetAttrString('i3D_exportApplyModifiers'))

    # -------------------------------------------------------------
    if ("i3D_cpuMesh" in m_sceneNodeData):
        m_nodeData["meshUsage"] = getMeshUsage(m_sceneNodeData["i3D_cpuMesh"])
    if "i3D_vertexCompressionRange" in m_sceneNodeData:
        m_nodeData['vertexCompressionRange'] = m_sceneNodeData['i3D_vertexCompressionRange']
    # -------------------------------------------------------------
    m_materialsList, m_materialSlotNames = getShapeMaterials(m_meshGen.name)
    m_materials = {}
    for m_mat in m_materialsList:
        m_materials[m_mat] = []
    # -------------------------------------------------------------
    # --- calculate triangles and normals with applied modifiers
    m_meshGen.calc_loop_triangles()
    if version_ctypes_interface < (4, 1):
        m_meshGen.calc_normals_split()

    # -------------------------------------------------------------
    if (len(m_materialsList) > 1):
        for m_triangle in m_meshGen.loop_triangles:
            m_mat = m_meshGen.materials[m_triangle.material_index]
            if None == m_mat:
                m_mat = "default"
            else:
                m_mat = m_mat.name
            m_materials[m_mat].append(m_triangle.index)
    else:
        for m_triangle in m_meshGen.loop_triangles:
            m_materials[m_materialsList[0]].append(m_triangle.index)

    # -------------------------------------------------------------
    m_vertices  = {}
    m_triangles = {}
    m_subsets   = {}
    m_vertices["data"]  = []
    m_triangles["data"] = []
    m_subsets["data"]   = []
    # -------------------------------------------------------------
    # Snow Heap mode flag from UI
    useSnowHeap = False
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        ui_settings = getattr(scene, "I3D_UIexportSettings", None)
        if ui_settings is not None:
            useSnowHeap = getattr(ui_settings, "i3D_exportSnowHeapMode", False)

    m_vtxColorLayerName = None

    if UIGetAttrBool("i3D_exportNormals"):
        m_vertices["normal"] = "true"
    if UIGetAttrBool("i3D_exportColors"):
        m_vtxColorLayerName = getRenderColorName(m_meshGen.name)
        if (m_vtxColorLayerName):
            m_vertices["color"] = "true"

    # SnowHeap Mode: enforce vertex colors
    if useSnowHeap:
        color_attrs = getattr(m_meshGen, "color_attributes", None)
        if not color_attrs or len(color_attrs) == 0:
            UIShowError(
                "No Vertex Color detected during export while Snow Heap Mode is enabled.\n\n"
                "Use the 'Bake Deltas to Vertex Colors' tool first, or disable "
                "'Snow Heap Mode' if this mesh is not a snow heap."
            )
            return None

        # If no layer chosen yet, pick the first available color layer
        if not m_vtxColorLayerName:
            try:
                m_vtxColorLayerName = list(color_attrs.keys())[0]
            except Exception:
                m_vtxColorLayerName = None

        if m_vtxColorLayerName:
            m_vertices["color"] = "true"

    if UIGetAttrBool("i3D_exportTexCoords"):
        for m_i in range( len(m_meshGen.uv_layers) ):
            if m_i == 4: break
            m_str = "uv{:d}".format(m_i)
            m_vertices[m_str] = "true"

    #skinning
    armature_modifier = next((mod for mod in m_obj.modifiers if mod.type == 'ARMATURE' and
                              mod.object and UIGetAttrBool("i3D_exportSkinWeigths")), None)
    if armature_modifier:
        boneMap = {}
        m_vertices["blendweights"] = "true"
        vertex_groups = bpy.data.objects[m_sceneNodeData['fullPathName']].vertex_groups
        for group in vertex_groups:
            if 'bones' in m_sceneNodeData:
                bone_node_id = m_sceneNodeData['bones'].get(group.name)
                if bone_node_id is not None:
                    UIAddMessage(f"skinning: group.index {group.index} name {group.name}")
                    boneMap[group.index] = bone_node_id

        m_nodeData["skinBindNodeIds"] = " ".join(str(boneMap[key]) for key in boneMap)

        # GIANTS Editor cannot handle empty skinBindNodeIds
        if not boneMap:
            m_vertices["blendweights"] = "false"
            m_nodeData.pop("skinBindNodeIds", None)

    # -------------------------------------------------------------
    m_indexBuffer    = {}
    m_currentIndex   = 0
    m_firstIndex     = 0
    m_numVerticesSet = set()
    m_trainglesCount = 0
    m_subsetsCount   = 0
    m_counter        = 0

    bakeTransforms = "BAKE_TRANSFORMS" == UIGetAttrString('i3D_exportAxisOrientations')
    normalInVert = "normal" in m_vertices
    colorInVert = "color" in m_vertices
    uv0InVert = "uv0" in m_vertices
    uv1InVert = "uv1" in m_vertices
    uv2InVert = "uv2" in m_vertices
    uv3InVert = "uv3" in m_vertices
    blendweightsInVert = "blendweights" in m_vertices

    for matId, m_mat in enumerate(m_materialsList):
        m_matItem = m_materials[m_mat]
        m_trainglesCount += len( m_matItem )
        m_subsetsCount  += 1
        m_numIndices    = 0
        m_numVerticesSet.clear()
        for m_primIndex in m_matItem:
            m_triangle = m_meshGen.loop_triangles[m_primIndex]

            m_strVI = ''
            for m_loopIndex in m_triangle.loops:
                m_loop        = m_meshGen.loops[m_loopIndex]
                m_vertexIndex = m_loop.vertex_index
                m_vertItem = {}
                m_pos      = m_meshGen.vertices[ m_vertexIndex ].co.xyz
                if (bakeTransforms): # x z -y
                    m_pos = ( m_pos[0], m_pos[2], -m_pos[1] )
                m_vertItem["p"] = "{:g} {:g} {:g}".format(m_pos[0],m_pos[1],m_pos[2])
                if (normalInVert):
                    m_value = m_loop.normal
                    if (bakeTransforms): # x z -y
                        m_value = ( m_value[0], m_value[2], -m_value[1] )
                    m_vertItem["n"] = "{:g} {:g} {:g}".format(m_value[0],m_value[1],m_value[2])
                if (colorInVert):
                    # SnowHeap Mode: use linear vertex colors (no sRGB conversion) so (2*color-1) deformation behaves like FS22
                    try:
                        colorAttr = m_meshGen.color_attributes[m_vtxColorLayerName].data[m_loop.index]
                        if useSnowHeap:
                            col = colorAttr.color
                            colorSRGB = (col[0], col[1], col[2], col[3])
                        else:
                            colorSRGB = colorAttr.color_srgb
                    except Exception:
                        colorSRGB = (1.0, 1.0, 1.0, 1.0)

                    m_vertItem["c"] = "{:g} {:g} {:g} {:g}...".format(colorSRGB[0], colorSRGB[1], colorSRGB[2], colorSRGB[3])
                if (uv0InVert):
                    m_value = m_meshGen.uv_layers[0].data[m_loopIndex].uv
                    m_vertItem["t0"] = "{:g} {:g}".format(m_value[0],m_value[1])
                if (uv1InVert):
                    m_value = m_meshGen.uv_layers[1].data[m_loopIndex].uv
                    m_vertItem["t1"] = "{:g} {:g}".format(m_value[0],m_value[1])
                if (uv2InVert):
                    m_value = m_meshGen.uv_layers[2].data[m_loopIndex].uv
                    m_vertItem["t2"] = "{:g} {:g}".format(m_value[0],m_value[1])
                if (uv3InVert):
                    m_value = m_meshGen.uv_layers[3].data[m_loopIndex].uv
                    m_vertItem["t3"] = "{:g} {:g}".format(m_value[0],m_value[1])
                if (blendweightsInVert):
                    m_vertItem["bw"] = ""
                    m_vertItem["bi"] = ""
                    m_boneData = {}
                    for groups in m_meshGen.vertices[ m_vertexIndex ].groups:
                        m_boneData[groups.group] = groups.weight
                    for key in m_boneData:
                        m_vertItem["bw"] = m_vertItem["bw"] + "{:g} ".format(m_boneData[key])
                        m_vertItem["bi"] = m_vertItem["bi"] + "{:g} ".format(key)
                    for i in range(0,4-len(m_boneData)):
                        m_vertItem["bw"] = m_vertItem["bw"] + "{:g} ".format(0)
                        m_vertItem["bi"] = m_vertItem["bi"] + "{:g} ".format(0)
                    m_vertItem["bw"] = m_vertItem["bw"].strip()
                    m_vertItem["bi"] = m_vertItem["bi"].strip()

                m_indexData = IndexBufferItem(m_vertItem,m_mat)
                if ( m_indexData not in m_indexBuffer ):
                    m_indexBuffer[ m_indexData ] = m_counter
                    m_counter += 1
                    m_vertices["data"].append(m_vertItem)
                m_currentIndexVertex = m_indexBuffer[ m_indexData ]
                m_strVI  += " {:d}".format(m_currentIndexVertex)
                if ( 0 == m_numIndices ):
                    m_firstIndex  = m_currentIndex
                m_numVerticesSet.add( m_currentIndexVertex )
                m_currentIndex += 1
                m_numIndices   += 1
            m_triItem = {}
            m_triItem["vi"] = m_strVI.strip()
            m_triangles["data"].append(m_triItem)
        m_subsetItem = {}
        m_subsetItem["firstVertex"] = "{:g}".format(min(m_numVerticesSet))
        m_subsetItem["numVertices"] = "{:g}".format(len(m_numVerticesSet))
        m_subsetItem["firstIndex"]  = "{:g}".format(m_firstIndex)
        m_subsetItem["numIndices"]  = "{:g}".format(m_numIndices)
        if m_materialSlotNames[matId] != None:
            m_subsetItem["materialSlotName"] = m_materialSlotNames[matId]
        m_subsetItem.update(i3d_densityUtil.computeUvDensity(m_triangles["data"],m_vertices,m_firstIndex,m_numIndices))
        m_subsets["data"].append(m_subsetItem)

    m_vertices["count"]  = "{:g}".format(len(m_indexBuffer))
    m_triangles["count"] = "{:g}".format(m_trainglesCount)
    m_subsets["count"]   = "{:g}".format(m_subsetsCount)
    m_nodeData["Materials"] = m_materialsList
    m_nodeData["Vertices"]  = m_vertices
    m_nodeData["Triangles"] = m_triangles
    m_nodeData["Subsets"]   = m_subsets
    if not nodeVisible:
        m_obj.hide_set(True)

    return m_nodeData

def getRenderColorName(shapeStr):
    """
    Returns name of the Color Attributes set to be rendered

    :param shapeStr: string name from bpy.data.meshes

    """
    m_name = None
    try:
        m_mesh = bpy.data.meshes[shapeStr]
        m_colorLayerNames = m_mesh.color_attributes.keys()
        if (len(m_colorLayerNames)>0):
            m_index = m_mesh.color_attributes.render_color_index
            if ( -1!=m_index ):
                m_name = m_colorLayerNames[ m_index ]
    except:
        UIShowWarning("Blender version is lower than 3.2, vertex colors is not exported!")
    return m_name

def getMeshFromDepsGraph(obj, mod = False):
    """
    Returns the Mesh from the depsgraph.

    If mod is false it returns the original object, otherwise the mesh with animation and modifiers applied
    """

    m_meshGen = None
    depsgraph = bpy.context.evaluated_depsgraph_get()       #2.8 changes
    if obj.name not in i3d_globals.g_meshCache:
        for object_instance in depsgraph.object_instances:
            # print("object_instance.object.name: " +object_instance.object.name +" obj.name: " + obj.name)
            if (object_instance.object.name == obj.name):            #operate on right object
                if(mod):
                    object_eval = object_instance.object.evaluated_get(depsgraph)
                else:
                    object_eval = object_instance.object.original           #original, without modifier and animation applied
                m_meshGen = bpy.data.meshes.new_from_object(object_eval,preserve_all_data_layers=True,depsgraph=depsgraph)
                i3d_globals.g_meshCache[obj.name] = m_meshGen
                return m_meshGen
        return None
    else:
        m_meshGen = i3d_globals.g_meshCache[obj.name]
    return m_meshGen

def getMeshUsage(isCpuMesh):
    if(isCpuMesh):
        return 256
    else:
        return 0

def getMeshOwners(m_shapeStr):
    """ Returns a list of bpy.data.objects.name who have bpy.data.objects.data.name == m_shapeStr. """

    m_meshOwners = []
    for m_obj in bpy.data.objects:
        if 'MESH' == m_obj.type:
            m_mesh = m_obj.data
            if m_mesh.name == m_shapeStr:
                m_meshOwners.append(m_obj.name)
    return m_meshOwners

def getBvCenterRadius(objStr):
    """ returns bvCenter and bvRadius of the mesh of a given object objStr is the name of an object with a mesh attached """

    m_mesh      = bpy.data.meshes[bpy.data.objects[objStr].data.name]
    m_vSum      = mathutils.Vector( (0,0,0) )
    m_bvRadius  = mathutils.Vector( (0,0,0) )
    m_vCount    = 0
    bVObjMat = bpy.data.objects[objStr].matrix_world
    if ( "BAKE_TRANSFORMS"  == UIGetAttrString('i3D_exportAxisOrientations')): #meshTransformation
        bVObjMat = bakeTransformMatrix(bVObjMat)

    for m_v in m_mesh.vertices:
        vertexWorld = bVObjMat @ m_v.co
        m_vSum += vertexWorld
        m_vCount    += 1
    m_bvCenter = m_vSum / m_vCount
    for m_v in m_mesh.vertices:
        vertexWorld = bVObjMat @ m_v.co
        m_vect      = m_bvCenter - vertexWorld
        m_bvRadius  = max( m_vect.length, m_bvRadius )
    return m_bvCenter, m_bvRadius

def getNurbsCurveData(m_shapeStr,m_nodeData):
    m_curve = bpy.data.curves[m_shapeStr]
    m_nodeData["name"] = m_curve.name
    m_nodeData["form"] = "open"
    if ( len( m_curve.splines ) ):
        m_spline = m_curve.splines[0]
        if m_spline.use_cyclic_u: m_nodeData["form"] = "closed"
        m_splinePoints = m_spline.points
        if ( "POLY"   == m_spline.type ):   m_splinePoints = m_spline.points
        if ( "NURBS"  == m_spline.type ):   m_splinePoints = m_spline.points
        if ( "BEZIER" == m_spline.type ):   m_splinePoints = m_spline.bezier_points
        if ( m_splinePoints ):
            m_points = []
            for m_p in m_splinePoints:
                m_pointCoords  = m_p.co.xyz[:]
                m_orient = UIGetAttrString('i3D_exportAxisOrientations')
                if ( "BAKE_TRANSFORMS"  == m_orient ): # x z -y
                    m_pointCoords = ( m_pointCoords[0], m_pointCoords[2], - m_pointCoords[1] )
                m_points.append( "{:g} {:g} {:g}".format(m_pointCoords[0],m_pointCoords[1],m_pointCoords[2]) )
            m_nodeData['points'] = m_points
    return m_nodeData

def getShapeMaterials(shapeStr):
    """ Returns a list of all material names related to the mesh object """

    materialIndexes = []
    m_materials = []
    m_materialSlotNames = []
    try:
        mesh = bpy.data.meshes[shapeStr]
        for triangle in mesh.loop_triangles:
            if ( triangle.material_index  not in materialIndexes ):
                materialIndexes.append( triangle.material_index )
        for matIndex in  materialIndexes:
            if mesh.materials:
                m_mat = mesh.materials[matIndex]
                if m_mat:
                    m_materials.append(m_mat.name)
                    if "materialSlotName" in m_mat:
                        m_materialSlotNames.append(m_mat["materialSlotName"])
                    else:
                        m_materialSlotNames.append(None)
                else:
                    if "default" not in m_materials:
                        m_materials.append("default")
                        m_materialSlotNames.append(None)
            else:
                if "default" not in m_materials:
                    m_materials.append("default")
                    m_materialSlotNames.append(None)
    except:
        # print(shapeStr + " is no mesh")
        if "default" not in m_materials:
            m_materials.append("default")
            m_materialSlotNames.append(None)
    return m_materials, m_materialSlotNames

def getMaterialFiles(materialStr):
    """ Returns a dictionary with a filepath assigned to a material """

    m_files = {}
    #2.8 update
    if materialStr in bpy.data.materials:
        mat = bpy.data.materials[materialStr]
        if(mat.use_nodes):
            textures = [x for x in mat.node_tree.nodes if x.type=='TEX_IMAGE']
            for textureNode in textures:
                image = textureNode.image
                if(image):
                    m_files[os.path.normpath(bpy.path.abspath(image.filepath))] = getTextureTypeInSlot(mat, textureNode)
        shaderFileData = None
        if "customShader" in mat:
            #take shader location to put together an absolute path
            shaderFile = mat["customShader"]
            shaderFilePath = os.path.normpath(os.path.join(bpy.path.abspath("//"), shaderFile))
            if shaderFile.startswith("$"):
                shaderFilePath = shaderFile
            shaderFileData = i3d_shaderUtil.extractXMLShaderData(shaderFilePath)
            # shaderFilePath = os.path.dirname(shaderFile)
        handledTextures = []
        for key in mat.keys():
            m_str = "{}".format(key)
            if ( "customShader" == m_str ):
                absPath = shaderFilePath.replace(os.sep, "/")
                m_files[absPath] = "customShader"
            elif ( 0 == m_str.find("customTexture_") ):
                # weird path behavior -> evgen 05.06.2020
                # absPath = os.path.normpath(shaderFilePath + "\\" + mat[m_str])
                absPath = os.path.splitext(bpy.data.filepath)[0].rsplit("\\",1)[0] +"\\" + mat[m_str]
                if mat[m_str].startswith("$"):
                    absPath = mat[m_str]
                m_files[absPath] = m_str
                handledTextures.append(m_str.split("_")[1])
        
        # Add textures selected through a parameter template and not overriden by a user-defined value.
        if shaderFileData is not None and "parameterTemplates" in shaderFileData:
            for parameterTemplateId, parameterTemplate in shaderFileData["parameterTemplates"].items():
                selectedParentSubTemplateId = None
                subTemplateId = parameterTemplate["rootSubTemplateId"]
                while subTemplateId is not None:
                    subTemplate = parameterTemplate["subtemplates"][subTemplateId]
                    parentSubTemplateId = subTemplate["parentId"]

                    subTemplateKey = "customParameterTemplate_{}_{}".format(parameterTemplateId, subTemplateId)
                    selectedSubTemplateId = None
                    if subTemplateKey in mat:
                        selectedSubTemplateId = mat[subTemplateKey]
                    elif selectedParentSubTemplateId is not None:
                        selectedSubTemplateId = selectedParentSubTemplateId

                    if selectedSubTemplateId is not None:
                        selectedSubTemplate = subTemplate["templates"][selectedSubTemplateId]
                        for textureName, _ in parameterTemplate["textures"].items():
                            if textureName not in handledTextures and textureName in selectedSubTemplate:
                                m_files[selectedSubTemplate[textureName]] = "customTexture_{}".format(textureName)
                                handledTextures.append(textureName)

                        if "parentTemplate" in selectedSubTemplateId:
                            selectedParentSubTemplateId = selectedSubTemplateId["parentTemplate"]
                        else:
                            selectedParentSubTemplateId = subTemplate["defaultParentTemplate"]

                    subTemplateId = parentSubTemplateId

    return m_files

def getTextureTypeInSlot( mat, textureNode ):
    """ Checks on which input slot the texture is mapped and returns type accordingly """

    #maybe solid recursive search necessary..
    if(mat.use_nodes):
        #check for values in immediate connected node -> add search to check further down in the hierarchy
        surfaceNode = mat.node_tree.nodes['Material Output'].inputs['Surface'].links[0].from_node

        specularName = getSpecularVariableName()
        emissionName = getEmissionVariableName()

        if specularName in surfaceNode.inputs and surfaceNode.inputs[specularName].is_linked:
            for links in surfaceNode.inputs[specularName].links:
                if(links.from_node == textureNode):
                    return "Glossmap"
        if 'Roughness' in surfaceNode.inputs and surfaceNode.inputs['Roughness'].is_linked:
            for links in surfaceNode.inputs['Roughness'].links:
                if(links.from_node == textureNode):
                    return "Glossmap"
        if 'Base Color' in surfaceNode.inputs and surfaceNode.inputs['Base Color'].is_linked:
            for links in surfaceNode.inputs['Base Color'].links:
                if(links.from_node == textureNode):
                    return "Texture"
        if 'Normal' in surfaceNode.inputs and surfaceNode.inputs['Normal'].is_linked:
            for links in surfaceNode.inputs['Normal'].links:
                if(links.from_node == textureNode):
                    return "Normalmap"
                elif(links.from_node.type == 'NORMAL_MAP'):
                    normalMapNode = links.from_node
                    if 'Color' in normalMapNode.inputs and normalMapNode.inputs['Color'].is_linked:
                        for linksNormalMap in normalMapNode.inputs['Color'].links:
                            if(linksNormalMap.from_node == textureNode):
                                return "Normalmap"
        if emissionName in surfaceNode.inputs and surfaceNode.inputs[emissionName].is_linked:
            for links in surfaceNode.inputs[emissionName].links:
                if(links.from_node == textureNode):
                    return "Emissivemap"
    return "Texture"

def getNormalMapStrength(mat):
    """ gets the strength of the normal map from the normal map node """
    if(mat.use_nodes):
        surfaceNode = mat.node_tree.nodes['Material Output'].inputs['Surface'].links[0].from_node
        if 'Normal' in surfaceNode.inputs and surfaceNode.inputs['Normal'].is_linked:
            return surfaceNode.inputs['Normal'].links[0].from_node.inputs['Strength'].default_value

def getShapeNode(nodeData):
    """ Returns bpy.data.objects[nodeStr].data.name """

    if "i3D_mergeChildren" in nodeData:
        return nodeData["fullPathName"]
    nodeStr = nodeData["fullPathName"]
    if nodeStr in bpy.data.objects:
        obj = bpy.data.objects[nodeStr]
        return obj.data.name
    else:
        if ("fullPathNameOrig" in nodeData):
            nodeStr = nodeData["fullPathNameOrig"]
            if nodeStr in bpy.data.objects:
                obj = bpy.data.objects[nodeStr]
                return obj.data.name
    return None

def getNodeType(nodeStr):
    """ Returns the correspondent type """

    nodeObj = bpy.data.objects[nodeStr]
    nodeTypeStr = nodeObj.type
    if ('EMPTY'  == nodeTypeStr):
        return 'TYPE_TRANSFORM_GROUP'
    if ('LIGHT'   == nodeTypeStr):
        return 'TYPE_LIGHT'
    if ('CAMERA' == nodeTypeStr):
        return 'TYPE_CAMERA'
    if ('CURVE'  == nodeTypeStr):
        return 'TYPE_NURBS_CURVE'
    if ('MESH'   == nodeTypeStr):
        return 'TYPE_MESH'
    return 'TYPE_TRANSFORM_GROUP'

def bakeTransformMatrix(matrix):
    rotation_minus90_x = np.array([
        [1, 0, 0, 0],
        [0, 0, 1, 0],
        [0, -1, 0, 0],
        [0, 0, 0, 1]
    ])
    rotation_plus90_x = np.array([
        [1, 0, 0, 0],
        [0, 0, -1, 0],
        [0, 1, 0, 0],
        [0, 0, 0, 1]
    ])
    return mathutils.Matrix(rotation_minus90_x.tolist()) @ matrix @ mathutils.Matrix(rotation_plus90_x.tolist())

def getNodeTranslationRotationScale(nodeStr):
    """ Returns the Transformation of the nodes """

    node = bpy.data.objects[nodeStr]
    orient = UIGetAttrString('i3D_exportAxisOrientations')
    if ( "BAKE_TRANSFORMS"  == orient ):
        # transform matrix Blender -> OpenGL
        m_matrix = bakeTransformMatrix( node.matrix_local )
        if ( "CAMERA"  ==  node.type or "LIGHT"  ==  node.type ):
            m_matrix = m_matrix @ mathutils.Matrix.Rotation( math.radians( -90 ), 4, "X" )
        if ( node.parent ):
            if ( "CAMERA"  ==  node.parent.type or "LIGHT"  ==  node.parent.type ):
                m_matrix = mathutils.Matrix.Rotation( math.radians( 90 ), 4, "X" ) @ m_matrix
    elif ( "KEEP_TRANSFORMS"  == orient ):
        m_matrix        = node.matrix_local
    m_translation   = m_matrix.to_translation()[:]
    m_rotation      = m_matrix.to_euler( "XYZ" )
    m_rotation      = ( math.degrees( m_rotation.x ),
                        math.degrees( m_rotation.y ),
                        math.degrees( m_rotation.z ) )
    m_scale         = m_matrix.to_scale()[:]
    m_translation  = "%g %g %g" %( m_translation )
    m_rotation     = "%g %g %g" %( m_rotation  )
    m_scale        = "%g %g %g" %( m_scale )
    return ( m_translation, m_rotation, m_scale )

def getRootBoneName(boneStr,armStr):
    """ Returns the bone name of the root bone of the given bone """

    boneObj = bpy.data.objects[armStr].data.bones[boneStr]
    while boneObj.parent:
        boneObj = boneObj.parent
    return boneObj.name

def updateNodeTransformation(nodeStr, boneStr, armatureStr):
    """ Adjusts the transformation of the bone in respect to the node it belongs to"""

    nodeObj = bpy.data.objects[nodeStr]
    boneObj = bpy.data.objects[armatureStr].data.bones[boneStr]
    rootBoneObj = bpy.data.objects[armatureStr].data.bones[getRootBoneName(boneStr,armatureStr)]
    if ( "BAKE_TRANSFORMS"  == UIGetAttrString('i3D_exportAxisOrientations')): #meshTransformation
        objMat = bakeTransformMatrix( nodeObj.matrix_local )
        rootBoneMat = bakeTransformMatrix( rootBoneObj.matrix_local )
        boneMat = bakeTransformMatrix(boneObj.matrix_local)
        # b0 = rootBoneMat
        # b1 = boneMat
        # m1 = objMat
        # l0 = b0
        # l1 = l0.inverted() @ b1
        # l2 = l1.inverted() @ l0.inverted() @ m1
        # matrix = l2
        matrix = (rootBoneMat.inverted() @ boneMat).inverted() @ rootBoneMat.inverted() @ objMat
    else:
        objMat = nodeObj.matrix_local
        rootBoneMat = rootBoneObj.matrix_local
        boneMat = boneObj.matrix_local
        matrix = (rootBoneMat.inverted() @ boneMat).inverted() @ rootBoneMat.inverted() @ objMat

    translation   = matrix.to_translation()[:]
    rotation      = matrix.to_euler( "XYZ" )
    rotation      = ( math.degrees( rotation.x ), math.degrees( rotation.y ), math.degrees( rotation.z ) )
    scale         = matrix.to_scale()[:]
    translation  = "%g %g %g" %( translation )
    rotation     = "%g %g %g" %( rotation  )
    scale        = "%g %g %g" %( scale )
    return ( translation, rotation, scale )

def getBoneTranslationRotationScale(boneStr,armStr):
    """
    Calculates translation, rotation and scale for the bone.

    :param boneStr: name of bone
    :param armStr: name of the armature that the bone belongs to
    """

    armature = bpy.data.objects[armStr]
    bone = armature.pose.bones[boneStr]
    child_of_constraint = next((c for c in bone.constraints if c.type == 'CHILD_OF' and c.target), None)
    if UIGetAttrString('i3D_exportAxisOrientations') == "BAKE_TRANSFORMS":
        if child_of_constraint:
            target_world_mat = bakeTransformMatrix(child_of_constraint.target.matrix_world)
            bone_world_mat = bakeTransformMatrix(bone.matrix)

            matrix = target_world_mat.inverted() @ bone_world_mat
        else:
            if bone.parent:
                parent_matrix = bakeTransformMatrix(bone.parent.matrix)
                matrix = parent_matrix.inverted() @ bakeTransformMatrix(bone.matrix)
            else:
                matrix = bakeTransformMatrix(bone.matrix)
    else:
        if bone.parent:
            matrix = bone.parent.matrix.inverted() @ bone.matrix
        else:
            matrix = bone.matrix
    translation = matrix.to_translation()[:]
    rotation = matrix.to_euler("XYZ")
    rotation = (math.degrees(rotation.x) - 90,
                math.degrees(rotation.y),
                math.degrees(rotation.z))
    scale = matrix.to_scale()[:]
    translation = "%g %g %g" % (translation)
    rotation = "%g %g %g" % (rotation)
    scale = "%g %g %g" % (scale)
    return translation, rotation, scale

def getBoneTailTranslation(boneStr,armStr):
    """ Calculates the bone tail translation """

    if ( "BAKE_TRANSFORMS"  == UIGetAttrString('i3D_exportAxisOrientations') ):
        return "%g %g %g" %(0,0,- bpy.data.objects[armStr].data.bones[boneStr].length*bpy.data.objects[armStr].data.bones[boneStr].matrix_local.to_scale()[1]) #x z -y
    else:
        return "%g %g %g" %(0,bpy.data.objects[armStr].data.bones[boneStr].length*bpy.data.objects[armStr].data.bones[boneStr].matrix_local.to_scale()[1],0) #x z -y

def getKeyframePointsLocationRotation(keyframeStr,rootStr,actionStr):
    """ Returns dictionary of global transformation matrices keyed with timestamps """

    if isType(rootStr, "ARMATURE"):  #armature
        armStr = rootStr
        boneStr = keyframeStr

        isTailBone = False
        if(boneStr.split("_")[-1] == "tail"):
            isTailBone = True
            boneStr = boneStr[:-5]

        timestamps = []
        #get all timestamps for the bone's keyframes
        for group in bpy.data.actions[actionStr].groups:
            if group.name == boneStr:  #group to bone
                for fcrv in group.channels:
                    for kfp in fcrv.keyframe_points:
                        if not(kfp.co.x in timestamps):
                            timestamps.append(kfp.co.x)

        KeyframeDataPoints = {}
        sumInterpolationData =  []
        if(isTailBone):     #TailBone case
            for timestamp in timestamps:
                KeyframeDataPoints[timestamp] = {}
                matrixData, interpolation = getTailBoneKeyframePoint(timestamp,boneStr,armStr,actionStr)
                KeyframeDataPoints[timestamp]["matrixData"] = matrixData
                # KeyframeDataPoints[timestamp]["interpolationData"] = interpolation
                sumInterpolationData.append(interpolation)
            overallInterpolationData = {}
            for index in range(len(sumInterpolationData)):
                for key, value in sumInterpolationData[index].items():
                    if key in overallInterpolationData.keys():
                        continue
                overallInterpolationData[key] = value
            for timestamp in timestamps:
                KeyframeDataPoints[timestamp]["interpolationData"] = overallInterpolationData

            return KeyframeDataPoints
        sumInterpolationData =  []
        for timestamp in timestamps: #loop timestamps
            KeyframeDataPoints[timestamp] = {}
            animationDelta, interpolationData = getDataMatrixFormKeyframes(timestamp,boneStr,actionStr) #change Data   #local transform
            boneObj = bpy.data.objects[armStr].data.bones[boneStr]
            parentObj = boneObj.parent
            if ( "BAKE_TRANSFORMS"  == UIGetAttrString('i3D_exportAxisOrientations') ):
                if(boneObj.parent == None): #rootBone is in armature space
                    t1 = bakeTransformMatrix(animationDelta)
                    m1 = bakeTransformMatrix(boneObj.matrix_local)
                    matrixData = m1 @ t1
                else:   #bone is in parentBone Space
                    t2 = bakeTransformMatrix(animationDelta)
                    m2 = bakeTransformMatrix(boneObj.matrix_local)
                    l1 = bakeTransformMatrix(parentObj.matrix_local)
                    matrixData = l1.inverted() @ m2 @ t2
            else:
                if(boneObj.parent == None): #rootBone is in armature space
                    t1 = animationDelta
                    m1 = boneObj.matrix_local
                    matrixData = m1 @ t1
                else:   #bone is in parentBone Space
                    t2 = animationDelta
                    m2 = boneObj.matrix_local
                    l1 = parentObj.matrix_local
                    matrixData = l1.inverted() @ m2 @ t2
            KeyframeDataPoints[timestamp]["matrixData"] = matrixData #<- rotation and translation
            # KeyframeDataPoints[timestamp]["interpolationData"] = interpolationData
            sumInterpolationData.append(interpolationData)
        overallInterpolationData = {}
        for index in range(len(sumInterpolationData)):
            for key, value in sumInterpolationData[index].items():
                if key in overallInterpolationData.keys():
                    continue
                overallInterpolationData[key] = value

        for timestamp in timestamps: #loop timestamps
            KeyframeDataPoints[timestamp]["interpolationData"] = overallInterpolationData
        # returns a dict with the finished global transformed data per [timestamp] as key
        # for I3DKeyframe -> self._I3DKeyframePoints
        return KeyframeDataPoints
    else:
        timestamps = []
        #get all timestamps for the bone's keyframes
        for group in bpy.data.actions[actionStr].groups:    #should only contain single group
            groupName = group.name
            for fcrv in group.channels:
                for kfp in fcrv.keyframe_points:
                    if not(kfp.co.x in timestamps):
                        timestamps.append(kfp.co.x)
        KeyframeDataPoints = {}
        sumInterpolationData =  []
        for timestamp in timestamps: #loop timestamps
            KeyframeDataPoints[timestamp] = {}
            animationDelta, interpolationData = getDataMatrixFormKeyframes(timestamp,groupName,actionStr) #change Data   #local transform
            rootObj = bpy.data.objects[rootStr]
            parentObj = rootObj.parent
            if ( "BAKE_TRANSFORMS"  == UIGetAttrString('i3D_exportAxisOrientations')):
                if(parentObj == None):#parenting
                    matrixData = bakeTransformMatrix(animationDelta)
                else:
                    t1 = bakeTransformMatrix(animationDelta)
                    m1 =bakeTransformMatrix(parentObj.matrix_local)
                    matrixData = m1.inverted() @ t1
            else:
                if(parentObj == None):#parenting
                    matrixData = animationDelta
                else:
                    t1 = animationDelta
                    m1 = parentObj.matrix_local
                    matrixData = m1.inverted() @ t1
            KeyframeDataPoints[timestamp]["matrixData"] = matrixData #<- rotation and translation
            # KeyframeDataPoints[timestamp]["interpolationData"] = interpolationData
            sumInterpolationData.append(interpolationData)
        overallInterpolationData = {}
        for index in range(len(sumInterpolationData)):
            for key, value in sumInterpolationData[index].items():
                if key in overallInterpolationData.keys():
                    continue
                overallInterpolationData[key] = value

        for timestamp in timestamps: #loop timestamps
            KeyframeDataPoints[timestamp]["interpolationData"] = overallInterpolationData
        return KeyframeDataPoints

def getTailBoneKeyframePoint(timestamp,boneStr,armStr,actionStr):
    """ Return length * y-scale of bone in matrix form. """

    length = bpy.data.objects[armStr].data.bones[boneStr].length
    scale = [0,0,1] #default
    interpolation = {}
    for group in bpy.data.actions[actionStr].groups:
        if group.name == boneStr:  #group to bone
            for fcrv in group.channels:
                for kfp in fcrv.keyframe_points:
                    if(kfp.co.x == timestamp):
                        data = kfp.co.y
                        if("scale" in fcrv.data_path):
                            scale[fcrv.array_index] = data
                        interpolation[fcrv.data_path.split(".")[-1]] = kfp.interpolation    #get interpolation
    matrix = mathutils.Matrix.Translation((0,0,-(length*scale[1]))) @ mathutils.Euler((0,0,0)).to_matrix().to_4x4()
    return matrix, interpolation

def getDataMatrixFormKeyframes(timestamp, groupStr, actionStr): #T = Location@Rotation
    """ Return local Transformation, Location @ Rotation. """

    #Data Extraction
    location = [0,0,0]
    rotation = [0,0,0,0]
    scale = [1,1,1]
    interpolation = {}
    hasQuaternion = False

    for group in bpy.data.actions[actionStr].groups:
        if group.name == groupStr:  #group to bone
            for fcrv in group.channels:
                for kfp in fcrv.keyframe_points:

                    data = kfp.co.y
                    if("location" in fcrv.data_path):    #get rotation
                        location[fcrv.array_index] = data
                    elif("rotation" in fcrv.data_path):  #get location
                        if("quaternion" in fcrv.data_path):
                            hasQuaternion = True
                        rotation[fcrv.array_index] = data
                    elif("scale" in fcrv.data_path):      #get scale
                        scale[fcrv.array_index] = data
                    interpolation[fcrv.data_path.split(".")[-1]] = kfp.interpolation    #get interpolation
                    if(kfp.co.x >= timestamp):
                        break
    if(hasQuaternion):  #quaternion
        rotation = quaternionToEulerFormat(rotation)
    scaleMat = mathutils.Matrix.Scale(scale[0],4,(1,0,0)) @ mathutils.Matrix.Scale(scale[1],4,(0,1,0)) @ mathutils.Matrix.Scale(scale[2],4,(0,0,1))
    matrix =  mathutils.Matrix.Translation((location[0],location[1],location[2])) @ mathutils.Euler((rotation[0],rotation[1],rotation[2])).to_matrix().to_4x4() @ scaleMat    #scale @ location@rotation
    return matrix, interpolation

def formatKeyframePointData(timestamp,data):
    """ Return dictionary with formatted strings of the data """

    # interpolationMap = { "BEZIER": "bezier", "LINEAR": "linear"} #correct mapping GE-Blender
    formatData = {}
    formatData['time'] = timestamp * getFps()
    if "matrixData" in data:
        matrix = data["matrixData"]
        translation   = matrix.to_translation()[:]
        rotation      = matrix.to_euler( "XYZ" )
        rotation      = ( math.degrees( rotation.x ),
                            math.degrees( rotation.y ),
                            math.degrees( rotation.z ) )
        scale = matrix.to_scale()[:]
        if "interpolationData" in data:     #is always exported "linear"
            interpolation = data["interpolationData"]
            if("location" in interpolation):
                formatData['translation']  = "%g %g %g" %( translation )
                formatData['iptin'] = "linear"
                formatData['iptout'] = "linear"
                # formatData['iptin'] = interpolation["location"]
                # formatData['iptout'] = interpolation["location"]
            if("rotation_quaternion" in interpolation):
                formatData['rotation'] = "%g %g %g" %( rotation  )
                formatData['iprin'] = "linear"
                formatData['iprout'] = "linear"
                # formatData['iprin'] = interpolation["rotation_quaternion"]
                # formatData['iprout'] = interpolation["rotation_quaternion"]
            elif("rotation_euler" in interpolation):
                formatData['rotation'] = "%g %g %g" %( rotation  )
                formatData['iprin'] = "linear"
                formatData['iprout'] = "linear"
                # formatData['iprin'] = interpolation["rotation_euler"]
                # formatData['iprout'] = interpolation["rotation_euler"]
            if "scale" in interpolation:
                formatData['scale'] = "%g %g %g" %( scale)
                formatData['ipsin'] = "linear"
                formatData['ipsout'] = "linear"
    return formatData

def isNodeVisible(m_nodeStr):
    m_node = bpy.data.objects[m_nodeStr]
    return m_node.visible_in_viewport_get(bpy.context.space_data)

def getFileData(pathStr,data):
    """
    Configurates the data path

    If pathStr is relative, it is assumed that it is relative to the blender file,
    which is not necessarily true, thus pathStr should be an absolute path

    :param pathStr: for proper functionality, this is expected to be the absolute path to be configured
    :param data: container dictionary for the return data
    :returns: the dictionary data with "relativePath" and "filename" set
    """
    if pathStr.startswith("$"):
        data["relativePath"] = "true"
        data["filename"] = pathStr
        return data

    # ------------------------------------------------------------------
    # Automatic pathing (no UI checkboxes required)
    # ------------------------------------------------------------------
    # If pathStr is relative, resolve it relative to the .blend folder.
    # If it is absolute, keep it absolute.
    if not os.path.isabs(pathStr):
        absPath = os.path.normpath(os.path.join(bpy.path.abspath("//"), pathStr))
    else:
        absPath = os.path.normpath(pathStr)

    # 1) If the file lives inside the configured game install, export as $data/$dataS/$shared.
    gamePath = getGamePath()
    if not gamePath:
        # Backwards-compat fallback (older UI stored this value in the scene)
        try:
            gamePath = UIGetAttrString('i3D_gameLocationDisplay')
        except Exception:
            gamePath = ""

    varPath = pathUtil.makeGameVariablePath(absPath, gamePath)
    if varPath is not None:
        data["relativePath"] = "true"
        data["filename"] = varPath
        return data

    # 2) Otherwise, export absolute paths so mixed setups work (game shader + external textures).
    data["relativePath"] = "false"
    data["filename"] = absPath.replace("\\", "/")
    return data

def getMaterialData(m_nodeStr, m_data):
    """ Configure  export parameters according to the material properties """

    if m_nodeStr in bpy.data.materials:
        m_mat = bpy.data.materials[m_nodeStr]
        m_data["name"] = m_mat.name

        #default values
        diffuseColorRed = m_mat.diffuse_color[0]
        diffuseColorGreen = m_mat.diffuse_color[1]
        diffuseColorBlue = m_mat.diffuse_color[2]

        smoothness = 1- m_mat.roughness
        specularIntensity = m_mat.specular_intensity
        metallic = m_mat.metallic

        if(m_mat.use_nodes):
            #check for values in immediate connected node -> add search to check further down in the hierarchy
            surfaceNode = m_mat.node_tree.nodes['Material Output'].inputs['Surface'].links[0].from_node
            specularName = getSpecularVariableName()
            emissionName = getEmissionVariableName()

            if "Base Color" in surfaceNode.inputs:
                # if surfaceNode.inputs["Base Color"].is_linked:
                diffuseColorRed = surfaceNode.inputs["Base Color"].default_value[0]
                diffuseColorGreen = surfaceNode.inputs["Base Color"].default_value[1]
                diffuseColorBlue = surfaceNode.inputs["Base Color"].default_value[2]
            elif "Color" in surfaceNode.inputs:
                diffuseColorRed = surfaceNode.inputs["Color"].default_value[0]
                diffuseColorGreen = surfaceNode.inputs["Color"].default_value[1]
                diffuseColorBlue = surfaceNode.inputs["Color"].default_value[2]
            if emissionName in surfaceNode.inputs:
                # if surfaceNode.inputs[emissionName].is_linked:
                emissiveRed = surfaceNode.inputs[emissionName].default_value[0]
                emissiveGreen = surfaceNode.inputs[emissionName].default_value[1]
                emissiveBlue = surfaceNode.inputs[emissionName].default_value[2]
                emissiveAlpha = surfaceNode.inputs[emissionName].default_value[3]
                if not (0, 0, 0, 1) == (emissiveRed,emissiveGreen,emissiveBlue,emissiveAlpha):  #exclude default
                    m_data["emissiveColor"]  = "{:g} {:g} {:g} {:g}".format(emissiveRed,emissiveGreen,emissiveBlue,emissiveAlpha)

            if "Roughness" in surfaceNode.inputs:
                # if surfaceNode.inputs["Roughness"].is_linked:
                smoothness = 1 - surfaceNode.inputs['Roughness'].default_value
            if "Metallic" in surfaceNode.inputs:
                # if surfaceNode.inputs["Metallic"].is_linked:
                metallic = surfaceNode.inputs['Metallic'].default_value
            if specularName in surfaceNode.inputs:
                # if surfaceNode.inputs["Specular"].is_linked:
                specularIntensity = surfaceNode.inputs[specularName].default_value

        # Check if "Reflectionmap" needs to be inserted in i3d
        if "customShader" in m_mat.keys() and "mirrorShader.xml" in m_mat["customShader"]:
            m_data["needsReflectionMap"] = True

        if "refractionMap" in m_mat.keys():
            m_data["needsRefractionMap"] = m_mat["refractionMap"]
            if "refractionMapLightAbsorbance" in m_mat.keys():
                m_data["refractionMapLightAbsorbance"] = m_mat["refractionMapLightAbsorbance"]
                
            if "refractionMapBumpScale" in m_mat.keys():
                m_data["refractionMapBumpScale"] = m_mat["refractionMapBumpScale"]

            if "refractionMapWithSSRData" in m_mat.keys():
                m_data["refractionMapWithSSRData"] = m_mat["refractionMapWithSSRData"]

        m_data["diffuseColor"]  = "{:g} {:g} {:g} 1".format(diffuseColorRed,diffuseColorGreen,diffuseColorBlue)
        if (0, 0, 0) == (diffuseColorRed,diffuseColorGreen,diffuseColorBlue):
            del m_data["diffuseColor"]

        m_data["specularColor"]  = "{:g} {:g} {:g}".format(smoothness,specularIntensity,metallic)


        if(m_mat.blend_method == 'BLEND'):
            m_data["alphaBlending"] = "true"
        if 'shadingRate' in m_mat.keys():
            m_data['shadingRate'] = m_mat['shadingRate']
        if 'materialSlotName' in m_mat.keys():
            m_data['materialSlotName'] = m_mat['materialSlotName']
        if ("customShaderVariation") in m_mat.keys():
            m_data["customShaderVariation"] = m_mat["customShaderVariation"]
        m_files = getMaterialFiles(m_nodeStr)
        m_customParameters = {}
        m_customTextures = {}
        for m_file, m_type in m_files.items():
            if ("Texture"      == m_type): m_data["Texture"]      = m_file
            if ("Glossmap"     == m_type): m_data["Glossmap"]     = m_file
            if ("Normalmap"    == m_type):
                m_data["Normalmap"]    = m_file
                normalMapStrength = getNormalMapStrength(m_mat)
                if(normalMapStrength != 1):
                    m_data["bumpDepth"] = normalMapStrength
            if ("Emissivemap"   == m_type): m_data["Emissivemap"]   = m_file
            if ("customShader" == m_type): m_data["customShader"] = m_file
            if (0 == m_type.find("customTexture_")):
                m_key = m_type.split("customTexture_")[1]
                m_customTextures[m_key] = m_file

        handledParams = []
        for m_item in m_mat.keys():
            if (0 == m_item.find("customParameter_")):
                m_key = m_item.split("customParameter_")[1]
                m_customParameters[m_key] = m_mat[m_item]
                handledParams.append(m_key)

        # Add params selected through a parameter template and not overriden by a user-defined value.
        shaderFileData = None
        if "customShader" in m_mat:
            #take shader location to put together an absolute path
            shaderFile = m_mat["customShader"]
            shaderFilePath = os.path.normpath(os.path.join(bpy.path.abspath("//"), shaderFile))
            if shaderFile.startswith("$"):
                shaderFilePath = shaderFile
            shaderFileData = i3d_shaderUtil.extractXMLShaderData(shaderFilePath)
        if shaderFileData is not None and "parameterTemplates" in shaderFileData:
            for parameterTemplateId, parameterTemplate in shaderFileData["parameterTemplates"].items():
                selectedParentSubTemplateId = None
                subTemplateId = parameterTemplate["rootSubTemplateId"]
                while subTemplateId is not None:
                    subTemplate = parameterTemplate["subtemplates"][subTemplateId]
                    parentSubTemplateId = subTemplate["parentId"]

                    subTemplateKey = "customParameterTemplate_{}_{}".format(parameterTemplateId, subTemplateId)
                    selectedSubTemplateId = None
                    if subTemplateKey in m_mat:
                        selectedSubTemplateId = m_mat[subTemplateKey]
                    elif selectedParentSubTemplateId is not None:
                        selectedSubTemplateId = selectedParentSubTemplateId

                    if selectedSubTemplateId is not None:
                        selectedSubTemplate = subTemplate["templates"][selectedSubTemplateId]
                        for paramName, _ in parameterTemplate["parameters"].items():
                            if paramName not in handledParams and paramName in selectedSubTemplate:
                                m_customParameters[paramName] = selectedSubTemplate[paramName]
                                handledParams.append(paramName)

                        if "parentTemplate" in selectedSubTemplateId:
                            selectedParentSubTemplateId = selectedSubTemplateId["parentTemplate"]
                        else:
                            selectedParentSubTemplateId = subTemplate["defaultParentTemplate"]

                    subTemplateId = parentSubTemplateId

        if len(m_customParameters):
            m_data["CustomParameter"] = m_customParameters
        if len(m_customTextures):
            m_data["Custommap"] = m_customTextures
    # If enabled, override emissive color when there is no emissive texture assigned.
    # This prevents accidental emissive export from pure color-only emissions
    # (e.g. when the user forgot to drag the emission slider back to black).
    # Emission Override Logic (per-material)
    try:
        if UIGetAttrBool('i3D_exportEmissionOverride'):
    
            # true only if emissive texture is assigned
            hasTexture = (
                "Emissivemap" in m_data and 
                m_data["Emissivemap"] not in ("", None, "None")
            )
    
            # Materials without emissive textures get emission removed
            if not hasTexture:
    
                # Remove emissiveColor entirely so default black is used
                if "emissiveColor" in m_data:
                    del m_data["emissiveColor"]
    
                # Remove stray / empty Emissivemap
                if "Emissivemap" in m_data:
                    if not m_data["Emissivemap"]:
                        del m_data["Emissivemap"]
    
    except Exception:
        pass

    return m_data

def getLightData(m_nodeStr, m_light):
    """ Configure  export parameters according to the light properties """

    if (isObjDataExists(m_nodeStr,"type")):
        m_type = getObjData(m_nodeStr,"type")
        #case 'AREA' not supported by GIANTSEditor
        if ('SUN'   == m_type): m_light["type"] = "directional"
        if ('POINT' == m_type): m_light["type"] = "point"
        if ('SPOT'  == m_type):
            m_light["type"] = "spot"
            if (isLightDataExists(m_nodeStr,"spot_size")):
                m_light["coneAngle"] = "{:g}".format(math.degrees(getLightDataFromAPI(m_nodeStr,"spot_size")))
            if (isLightDataExists(m_nodeStr,"spot_blend")):
                m_light["dropOff"] = "{:.3f}".format(5.0*getLightDataFromAPI(m_nodeStr,"spot_blend"))
    if (isLightDataExists(m_nodeStr,"color")):
        m_color = getLightDataFromAPI(m_nodeStr,"color")
        m_light["color"] = "{:g} {:g} {:g}".format(m_color.r,m_color.g,m_color.b)
    if (isLightDataExists(m_nodeStr,"cutoff_distance")):
        m_light["range"] = "{:.2f}".format(getLightDataFromAPI(m_nodeStr,"cutoff_distance"))
    if (isLightDataExists(m_nodeStr,"use_shadow")):
        m_castShadowMap = getLightDataFromAPI(m_nodeStr,"use_shadow")
        if (m_castShadowMap):  m_light["castShadowMap"] = "true"
        else: m_light["castShadowMap"] = "false"
    return m_light

def getCameraData(m_nodeStr, m_camera):
    """ Configure  export parameters according to the camera properties """

    if (isObjDataExists(m_nodeStr,"lens")):
        m_camera["fov"] = "{:.3f}".format(getObjData(m_nodeStr,"lens"))
    if (isObjDataExists(m_nodeStr,"clip_start")):
        m_camera["nearClip"] = "{:g}".format(getObjData(m_nodeStr,"clip_start"))
    if (isObjDataExists(m_nodeStr,"clip_end")):
        m_camera["farClip"] = "{:g}".format(getObjData(m_nodeStr,"clip_end"))
    if (isObjDataExists(m_nodeStr,"type")):
        m_type = getObjData(m_nodeStr,"type")
        if ('ORTHO'== m_type):
            m_camera["orthographic"] = "true"
            if (isObjDataExists(m_nodeStr,"ortho_scale")):
                m_camera["orthographicHeight"]  = "{}".format(getObjData(m_nodeStr,"ortho_scale"))
    return m_camera

def isLightDataExists(m_nodeStr,m_parm):
    m_str = 'bpy.data.objects["{}"].data.{}'.format(m_nodeStr,m_parm)
    try:
        eval(m_str)
        return True
    except:
        return False

def getLightDataFromAPI(m_nodeStr,m_parm):
    m_str = 'bpy.data.objects["{}"].data.{}'.format(m_nodeStr,m_parm)
    return eval(m_str)

def setLightData(m_nodeStr, m_parm, m_value):
    if hasattr(bpy.data.objects[m_nodeStr].data, m_parm):
        setattr(bpy.data.objects[m_nodeStr].data, m_parm, m_value)

def isObjDataExists(m_nodeStr,m_parm):
    m_str = 'bpy.data.objects["{}"].data.{}'.format(m_nodeStr,m_parm)
    try:
        eval(m_str)
        return True
    except:
        return False

def getObjData(m_nodeStr,m_parm):
    m_str = 'bpy.data.objects["{}"].data.{}'.format(m_nodeStr,m_parm)
    return eval(m_str)

def addChildObjects(m_nodes,m_result):
    """
    Appends all names of m_nodes and all their children to m_result.

    :param m_nodes: list of nodes without a parent
    :param m_result: list of all nodes which are a children of another node.
    """
    for m_nodeStr in m_nodes:
        m_result.append(m_nodeStr)
        m_childs = getChildObjects(m_nodeStr)
        addChildObjects(m_childs,m_result)

def boneHasParentBone(boneStr, armatureStr):
    """
    Returns True if the bone has a parent node.
    """
    bone = bpy.data.objects[armatureStr].data.bones[boneStr]
    if(bone.parent):
        return True
    return False

def boneHasChildBone(boneStr, armatureStr):
    """ Returns True if the bone has a child node. """

    bone = bpy.data.objects[armatureStr].data.bones[boneStr]
    if(bone.children):
        return True
    return False

def getBoneParent(boneStr, armatureStr):
    """ Returns the name of the parent if it has a parent. """

    if(boneHasParentBone(boneStr,armatureStr)):
        return bpy.data.objects[armatureStr].pose.bones[boneStr].parent.name
    return ""

def getBoneNameList(armatureStr):
    """ Returns a list of all bone names of the object if it has bones """

    if(bpy.data.objects[armatureStr].data.bones):    #hasBones, alternative check if type armature
        return  bpy.data.objects[armatureStr].data.bones.keys()
    return []

def isType(m_objStr, m_type):
    try:
        return (bpy.data.objects[m_objStr].type == m_type)
    except:
        pass
    return False

def isTypeArmature(objStr):
    return isType(objStr,"ARMATURE")

def isTypeMesh(objStr):
    return isType(objStr,"MESH")

def getAppliedArmatureName(objStr):
    """
    multiple armature modifiers not supported

    :returns: the armature name which is applied on given object
    """
    try:
        obj = bpy.data.objects[objStr]
        for modifier in obj.modifiers:
            if modifier.type == "ARMATURE":
                return modifier.object.name
    except:
        pass
    return None

def getSingleBoneInfluence(objStr):
    """
    Decides if only a single bone has influene on a vertex

    Returns the single Vertex Group which influences a mesh if it exists.
    Therefore every vertex must be assigned to exactly one group with weight 1.0
    """
    try:
        verticesVertexGroups = []
        for vertice in bpy.data.objects[objStr].data.vertices:  #all vertices
            if len(vertice.groups) >= 1:
                for vertexGroup in vertice.groups:                  #all assigned groups
                    # print("objStr: {}\tindex: {}, weight: {}".format(objStr,vertexGroup.group,vertexGroup.weight))
                    if vertexGroup.weight == 1.0:                   #must have weight 1
                        verticesVertexGroups.append(vertexGroup.group)
                    elif vertexGroup.weight == 0.0:                 #can have 0 weight groups
                        pass
                    else:
                        return None
        verticesVertexGroups = list(set(verticesVertexGroups))
        if len(verticesVertexGroups) == 1:
            for vertexGroup in bpy.data.objects[objStr].vertex_groups:
                if vertexGroup.index == verticesVertexGroups[0]:
                    return vertexGroup.name
    except:
        pass
    return None

def hasBone(m_objStr):
    """ Return True if object is armature and has bones assigned. """

    try:
        if(bpy.data.objects[m_objStr].data.bones):
            return True
    except:
        #no armature
        pass
    return False

def hasAnimation(m_objStr):
    """ Returns True if the given object has animations """

    try:
        obj = bpy.data.objects[m_objStr]
        for action in bpy.data.actions:
            for track in obj.animation_data.nla_tracks:
                for strip in track.strips:
                    if( action is strip.action):
                        return True
    except:
        pass
    try:
        obj = bpy.data.objects[m_objStr]
        for action in bpy.data.actions:
            if (action is obj.animation_data.action):
                return True
    except:
        pass
    return False

def hasObject(objStr):
    """ Returns True if the given object exists in bpy.data.objects """

    return objStr in bpy.data.objects

def isBoneOfArmature(m_boneStr,m_armStr):
    """ Returns True if the given bone is part of the armature """

    return m_boneStr in bpy.data.objects[m_armStr].pose.bones

def getAllActionsFromObj(objStr):
    """ Returns a list of all action names assigned to the provided object. Must contain action to function """

    actionNames = []
    obj = bpy.data.objects[objStr]
    try:
        for track in obj.animation_data.nla_tracks:
            for strip in track.strips:
                actionNames.append(strip.action.name)
    except:
        pass
    if(obj.animation_data.action):
        actionNames.append(obj.animation_data.action.name)
    #remove duplicates
    actionNames = list(set(actionNames))
    return actionNames

def getFcurveDataOfAction(action, boneStr):
    """ Returns raw data gathered from the fcurves, no modifier applied. """

    fcurves = {}
    arrayIndexToParameterQuaternion = { 0: "w", 1: "x", 2: "y", 3: "z"}
    arrayIndexToParameterXYZ = {0:"x",1:"y",2:"z"}
    interpolationTransform = {'LINEAR': "linear",'BEZIER':'linear','CONSTANT':'constant'}
    for fcrv in bpy.data.actions[action].fcurves:   #get action from clip parent
        keyframePoints = {}
        boneName = boneStr.split("_")[-1]           #to be save
        if(fcrv.group.name == boneName):
            if("quaternion" in fcrv.data_path.split(".")[-1]):
                dataPath = fcrv.data_path.split(".")[-1] + "_" + arrayIndexToParameterQuaternion[fcrv.array_index]
            else:
                dataPath = fcrv.data_path.split(".")[-1] + "_" + arrayIndexToParameterXYZ[fcrv.array_index]
            for kfp in fcrv.keyframe_points:
                data = {}
                timestamp = kfp.co.x
                data['value'] = kfp.co.y
                data['interpolation'] = interpolationTransform[kfp.interpolation]
                keyframePoints[timestamp] = data
            fcurves[dataPath] = keyframePoints
    return fcurves

def __getFcurveData(fcurve):    #unused

    interpolationTransform = {'LINEAR': "linear",'BEZIER':'bezier','CONSTANT':'constant'}
    fcurveData = {}
    for key, item in fcurve.items(): #fcurves
        for keyframePoint in item.keyframe_points:
            fcurveData['timestamp'] = keyframePoint.co.x
            fcurveData['value'] = keyframePoint.co.y
            fcurveData['interpolation'] = interpolationTransform[keyframePoint.interpolation]

def getActionOwners(actionStr):
    """ Returns owner of the requested action by name """

    ownersList = []
    for obj in bpy.data.objects:
        if(hasAnimation(obj.name)):
            actionNames = getAllActionsFromObj(obj.name)
            if (actionStr in actionNames):
                ownersList.append(obj.name)
    return ownersList

def getActionGroupNames(action):
    """ Returns a list of all groups used in the requested action. if it has more than one group, it must be bones """

    groupNames = []
    for group in bpy.data.actions[action].groups:
        groupNames.append(group.name)
    return groupNames

def calculateClipDuration(actStr):
    """ Returns the length of the action in ms. """

    m_fps = bpy.context.scene.render.fps
    return (bpy.data.actions[actStr].frame_range[1] - bpy.data.actions[actStr].frame_range[0]) * m_fps

def getFps():
    return bpy.context.scene.render.fps

def toDegrees(radiant):
    return math.degrees(radiant)

def quaternionToEulerFormat(quaternion):    #w,x,y,z
    quat = mathutils.Quaternion((quaternion[0], quaternion[1], quaternion[2], quaternion[3]))
    euler = quat.to_euler()
    return [euler.x,euler.y,euler.z]

def getNodeIndex( m_nodeStr, boneStr="" ):
    return getDepth(m_nodeStr, boneStr, "")

def getIndex( m_nodeStr ):
    m_node = bpy.data.objects[m_nodeStr]
    m_objParent = m_node.parent
    # if parented to the world
    if (None == m_objParent):
        m_iterItems = getWorldObjects()
    else:
        m_iterItems = getChildObjects(m_objParent.name)
    for i in range(len(m_iterItems)):
        m_child = m_iterItems[i]
        if (m_node.name == m_child):
            return i
    return None

def getBoneIndex(armature, bone_name):
    """
    Get the index of the bone, taking into account Child Of constraints.

    Returns:
        tuple: (index of the bone, target object of the Child Of constraint or None)
    """
    bone = armature.pose.bones[bone_name]

    # Check for "Child Of" constraint
    child_of_constraint = next((c for c in bone.constraints if c.type == 'CHILD_OF'), None)
    if child_of_constraint and child_of_constraint.target:
        # Index of the bone will be the number of children of the target object
        index = len(child_of_constraint.target.children)
        return index, child_of_constraint.target
    else:
        siblings = [b for b in armature.pose.bones if b.parent == bone.parent]
        index = siblings.index(bone)
        return index, None

def getDepth( node_name, bone_name=None, depth_str="" ):
    """ return the configuration index for the XML configuration file """

    # Function to construct the depth string
    def update_depth_string(current_index, existing_str):
        return f"{current_index}|{existing_str}" if existing_str else str(current_index)
    
    if not bone_name:
        if node_name not in bpy.data.objects:
            return ""

        index = getIndex(node_name)
        parent = bpy.data.objects[node_name].parent

        if parent is None:  # If parented to the world
            return f"{index}>{depth_str}"  # last run
        else:
            depth_str = update_depth_string(index, depth_str)
            return getDepth(parent.name, None, depth_str)

    else:
        armature = bpy.data.objects[node_name]
        if bone_name not in armature.data.bones:
            return ""

        index, child_of_target = getBoneIndex(armature, bone_name)
        depth_str = update_depth_string(index, depth_str)

        if child_of_target:
            return getDepth(child_of_target.name, None, depth_str)

        parent_bone = armature.pose.bones[bone_name].parent
        if parent_bone:  # If the bone has a parent bone
            return getDepth(node_name, parent_bone.name, depth_str)
        else:  # If the bone is parented to the armature.
            return getDepth(node_name, None, depth_str)

def getWorldObjects():
    """  Returns all bpy.data.objects without a parent. """

    m_iterItems = []

    for m_node in bpy.context.scene.objects:    #why context not bpy.data.objects
        if (None is m_node.parent):
            m_iterItems.append(m_node.name)
    m_iterItems.sort(key=natural_keys)
    return m_iterItems

def atoi(text):
    return int(text) if text.isdigit() else text

def natural_keys(text):
    '''
    alist.sort(key=natural_keys) sorts in human order
    http://nedbatchelder.com/blog/200712/human_sorting.html
    (See Toothy's implementation in the comments)
    '''
    return [ atoi(c) for c in re.split(r'(\d+)', text) ]

def getNodeUserAttributes(m_nodeStr):
    m_attributes = []
    m_types = ["boolean","string","scriptCallback","float","integer"]
    if m_nodeStr in bpy.data.objects:
        m_node = bpy.data.objects[m_nodeStr]
        for m_key in m_node.keys():
            if (0==m_key.find("userAttribute_")):
                try:
                    m_list = m_key.split("_",2)
                    m_type = m_list[1]
                    m_name = m_list[2]
                    m_val  = m_node[ m_key ]
                    if m_type in m_types:
                        if ("boolean"==m_type):
                            if m_val: m_val = "true"
                            else:     m_val = "false"
                        m_val = "{}".format(m_val)
                        m_item = {}
                        m_item["name"]  = m_name
                        m_item["type"]  = m_type
                        m_item["value"] = m_val
                        m_attributes.append(m_item)
                except:
                    pass
    return m_attributes


def getCurveLength(curveName):
    """ calculates the length of the given curve """

    if curveName in bpy.data.objects and bpy.data.objects[curveName].type == "CURVE":
        try:
            return bpy.data.objects[curveName].data.splines[0].calc_length(resolution = 1024)
        except Exception as e:
            print(e)
            pass
    return -1


def deleteHierarchy(obj):
    """ Recursively delete the provided object with all it's children. """

    def remove_child_objects(obj):       # recursion
        for child in obj.children:
            if child.children:
                remove_child_objects(child)

            bpy.data.objects.remove(child,do_unlink = True)
    remove_child_objects(obj)
    bpy.data.objects.remove(obj,do_unlink = True)

def getFcurveLength(action):
    """ Returns a dictionary with the distance as key and the frame as value, for the given action's fcurves """

    kfpCount = 1
    # print("action: {}, name: {}".format(action,action.name))
    for fcrvs in action.fcurves:
        # print("fcurvs has {} kfp".format(len(fcrvs.keyframe_points)))
        kfpCount = max(kfpCount,len(fcrvs.keyframe_points))
    # resolution = kfpCount * 100
    resolution = kfpCount * 100

    frameRange = action.frame_range
    frameStep = (frameRange[1] - frameRange[0])/(resolution -1)
    xyzFcurves = [fcvs for fcvs in action.fcurves if 'location' in fcvs.data_path]  #x y z
    distance = 0
    distToFrame = []
    previousFrame = 0
    for i in range(resolution):
        frame = frameRange[0] + (frameStep)*i
        localDistance = 0
        for fc in xyzFcurves:  #euclidian distance (x2-x1^2 + y2-y1^2 + z2-z1^2)^0.5
            localDistance += (fc.evaluate(previousFrame)-fc.evaluate(frame))**2
        distance += localDistance**0.5
        distToFrame.append((distance,frame))
        previousFrame = frame
    #distance is distToFram[-1]
    return distToFrame


def createBezierCurveFromAnimation(objName):
    """ Creates a bezier curve form the animation data and returns the Curve object. """

    tempCurve = bpy.data.curves.new('tempCurve_{}'.format(objName), 'CURVE')
    tempCurve.dimensions = '3D'
    animFcurves = bpy.data.objects[objName].animation_data.action.fcurves
    # index 1 is the Y location fcurve
    srcFcurve = animFcurves.find('location', index=1)
    spline = tempCurve.splines.new('BEZIER')
    spline.bezier_points.add(count=len(srcFcurve.keyframe_points)-1)
    fcurves = zip(*(animFcurves.find('location', index=k).keyframe_points[:] for k in range(3)))
    t = 0
    for xp, yp, zp in fcurves:
        p = spline.bezier_points[t]
        p.co = (xp.co.y, yp.co.y, zp.co.y)
        p.handle_left = (xp.handle_left.y, yp.handle_left.y, zp.handle_left.y)
        #ht = 'AUTO' if xp.handle_left == 'AUTO_CLAMPED' else xp.handle_left_type
        p.handle_left_type = 'FREE'
        p.handle_right = (xp.handle_right.y, yp.handle_right.y, zp.handle_right.y)
        #ht = 'AUTO' if xp.handle_right == 'AUTO_CLAMPED' else xp.handle_right_type
        p.handle_right_type = 'FREE'
        t += 1

    obj = bpy.data.objects.new('tempObj_{}'.format(objName), tempCurve)
    bpy.context.scene.collection.objects.link(obj)

    return obj
#------------------------------------------------------------------------
#------------------------------------------------------------------------
#------------------------------------------------------------------------
class IndexBufferItem( object ):
    def __init__(self,m_vertItem,m_mat):
        self._str  = "{}".format(m_mat)
        for m_key,m_item in m_vertItem.items():
            self._str += " {}".format(m_item)

    def __hash__(self):
        return hash(self._str)

    def __eq__(self, other):
        return self._str == other._str