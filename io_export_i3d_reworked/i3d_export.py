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

import bpy, bpy_extras
import time
import traceback
import os.path

#trying to use lxml package. Fallback is standard xml package
g_usingLXML = True
g_doProfiling = False

try:
    from lxml import etree as xml_ET
except:
    import xml.etree.cElementTree as xml_ET
    g_usingLXML = False

import re
from .dcc import *
from .dcc import ddsExporter
from .util import logUtil,i3d_binaryUtil

# to profile with internal tools
import cProfile, pstats, io
from pstats import SortKey
from . import i3d_globals
from . import i3d_changelog

def I3DExportAll():
    """ Exports every object with settings selected in the Export GUI """

    # unhide all objects so everything can be selected
    hideList = []
    hideViewportList = []
    for obj in bpy.data.objects:
        if obj:
            if obj.hide_get():
                hideList += [obj.name]
            if obj.hide_viewport:
                hideViewportList += [obj.name]
            obj.hide_set(False)
            obj.hide_viewport = False
    I3DExport(False)
    # hide object to the state before
    for obj in bpy.data.objects:
        if obj:
            if obj.name in hideList:
                obj.hide_set(True)
            if obj.name in hideViewportList:
                obj.hide_viewport = True

def I3DExportSelected():
    """ Exports all selected object with settings selected in the Export GUI """

    I3DExport(True)

def I3DUpdateXML():
    """ Updates the defined xml files """

    pr = None
    if g_doProfiling:
        pr = cProfile.Profile()
        pr.enable()
        i3d_globals.I3DLogPerformanceInit()
    i3d_globals.g_meshCache = {}

    dcc.UIAddMessage('Updating config xml file...')
    start_time = time.time()
    updateObj = I3DIOexport()
    err = updateObj.updateXML()
    end_time = time.time()
    if err == 1:
        dcc.UIShowError('FAILED XML Update time is {0:.2f} seconds'.format(end_time - start_time))
    elif err == 0:
        dcc.UIAddMessage('XML Update time is {0:.2f} seconds'.format(end_time - start_time))

    # execute code to profile
    if g_doProfiling:
        pr.disable()
        s = io.StringIO()
        sortby = SortKey.CUMULATIVE
        ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
        ps.print_stats()
        dcc.UIShowError(s.getvalue())

def I3DExport(exportSelection):
    """ Main export function"""
    pr = None
    if g_doProfiling:
        pr = cProfile.Profile()
        pr.enable()
        i3d_globals.I3DLogPerformanceInit()
    i3d_globals.g_meshCache = {}

    dcc.UIAddMessage('Start export...')
    m_start_time = time.time()
    m_expObj = I3DIOexport()
    err = m_expObj.export(exportSelection)
    m_end_time = time.time()
    if err == 1:
        dcc.UIShowError('FAILED Export time is {0:.2f} seconds'.format(m_end_time - m_start_time))
    elif err == 0:
        dcc.UIAddMessage('SUCCESS Export time is {0:.2f} seconds'.format(m_end_time - m_start_time))

    # execute code to profile
    if g_doProfiling:
        pr.disable()
        s = io.StringIO()
        sortby = SortKey.CUMULATIVE
        ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
        ps.print_stats()
        dcc.UIShowError(s.getvalue())


def I3DExportDDS():
    dcc.UIAddMessage('Start export DDS...')
    startTime = time.time()
    exportObj = I3DIOexport()
    exportObj.exportDDS()
    endTime = time.time()
    dcc.UIAddMessage('DDS Export time is {0:.2f} ms'.format((endTime - startTime) * 1000))

# --------------------------------------------------------------
# Safe changelog popup (Blender 5+): never call bpy.ops from draw()
# --------------------------------------------------------------
_I3D_CHANGELOG_SCHEDULED = False

def _i3d_changelog_timer():
    global _I3D_CHANGELOG_SCHEDULED
    try:
        bpy.ops.object.change_log_operator('INVOKE_DEFAULT')
    except RuntimeError:
        return 0.25
    except Exception as e:
        print(e)
        _I3D_CHANGELOG_SCHEDULED = False
        return None
    _I3D_CHANGELOG_SCHEDULED = False
    return None

def I3DShowChangelog():
    global _I3D_CHANGELOG_SCHEDULED
    if _I3D_CHANGELOG_SCHEDULED:
        return
    _I3D_CHANGELOG_SCHEDULED = True
    bpy.app.timers.register(_i3d_changelog_timer, first_interval=0.1)

#------------------------------------------------------------------------
# Classes
#------------------------------------------------------------------------

class I3DSceneNode(object):
    """ General I3D Node to represent the blender object structure """

    def __init__(self, node,parent="ROOT",armature = None,nodeID=0):
        """
        Initialize the I3DSceneNode with minimal data.

        :param self: I3DSceneNode instance
        :param node: Name of the object
        :param parent: optional, default is "ROOT", give the parent I3DSceneNode
        :param armature: optional, default is None, this is only used if node is a bone
        :param nodeID: optional, default is 0, this is the unique node identifier

        """

        self._children = []
        if(armature): #isBone
            m_nodeData = getBoneData(node,armature)

            # check if parent is a bone too
            parentIsBone = False
            armObj = bpy.data.objects[armature]
            if armObj and armObj.type == 'ARMATURE':
                for pose_bone in armObj.pose.bones:
                    if pose_bone.name == parent:
                        parentIsBone = True
                        break
            if (parent != armature and parentIsBone):
                self._parent = dcc.getBoneData(parent, armature)["fullPathName"]
            else:
                self._parent = getNodeData(parent)["fullPathName"]
        else:
            m_nodeData     = getNodeData(node)
            self._parent   = getNodeData(parent)["fullPathName"]
        self._treeID   = m_nodeData["fullPathName"]
        self._data     = m_nodeData
        self._nodeID   = nodeID

    def addChild(self, m_cTreeID):
        self._children.append(m_cTreeID)

    def removeChild(self, m_cTreeID):
        self._children.remove(m_cTreeID)

    def sortChilder(self):
        """ sorts the children for a desired scene output format """

        boneList = []
        objList = []
        for child in self._children:
            armature = child.split("_")[0]
            if dcc.isTypeArmature(armature):
                try:
                    if dcc.isBoneOfArmature(child.split("_")[1],armature):
                        boneList.append(child)
                    else:
                        objList.append(child)
                except:
                    objList.append(child)
            else:
                objList.append(child)
        boneList.sort()
        objList.sort()
        self._children = objList + boneList

class I3DShapeNode(object):
    """ I3D Node to represent shape objects """

    def __init__(self, shapeID, sceneNodeData):
        """
        Initialize the I3DShapeNode with minimal data

        :param self: I3DShapeNode instance
        :param shapeID: this is the unique node identifier
        :param sceneNodeData: dictionary of all necessary data
        """

        self._shapeID   = shapeID
        self._shapeType = sceneNodeData["type"]
        self._treeID    = dcc.getShapeNode(sceneNodeData) #returns bpy.data.object name
        self._data      = {}
        self._sceneNodeData = sceneNodeData

    def _generateData(self):
        """ generate Shape specific data """

        self._data      = getShapeData(self._treeID,self._sceneNodeData)

class I3DMaterialNode(object):
    """ I3DMaterialNode Node to represent material data"""

    def __init__(self, materialID, treeID : str):
        """
        Initialize the I3DMaterialNode

        :param self: I3DMatrialNode instance
        :param materialID: this is the unique material identifier
        :param treeID: this is a string with the name of the material
        """

        self._materialID = materialID
        self._treeID     = treeID
        self._data       = getMaterialData(treeID)

class I3DFileNode(object):
    """ I3DFileNode to represent File data"""

    def __init__(self, fileID, treeID, fileType = "Texture"):
        """
        Initialize the I3DFileNode

        :param self: I3DFileNode instance
        :param fileID: this int is the unique file identifier
        :param treeID: this is the filepath of the corresponding file
        :param fileType: this is the file type, e.g. ("Emissivemap","Normalmap","Texture","Glossmap")
        """

        self._fileID = fileID
        self._treeID = treeID
        self._data   = getFileData(treeID,fileType)

class I3DAnimationSet(object):
    """ I3DAnimationSet is the container to group up the animations """

    def __init__(self, data : dict ):
        """
        Initialize the I3DAnimationSet

        :param self: I3DAnimationSet instance
        :param data: this is the dictionary with the I3DSceneNode data
        """

        self._name = data["name"]
        self._data = data
        self._treeID = data["fullPathName"]
        self._I3DClip = {}

    def _generateClips(self):
        """ generate dictionary with all AnimationSet relevant Clips """

        for actionName in dcc.getAllActionsFromObj(self._treeID):
            for ownerName in dcc.getActionOwners(actionName):
                if( ownerName == self._treeID):
                    m_clip = I3DClip(actionName,ownerName)
                    self._I3DClip[m_clip._treeID] = m_clip

class I3DClip(object):
    """ Container to hold Blender actions, Concept of Clips from Maya is called Actions in Blender 2.8 """

    def __init__(self, actionName : str, ownerName ):
        """
        Initialize the individual clips

        :param self: I3DClip instance
        :param actionName: this is the string of the name of the action
        :param ownerName: this is the name of the owner of the action
        """
        self._treeID = actionName
        self._duration = dcc.calculateClipDuration(self._treeID)
        self._owner = ownerName
        self._I3DKeyframes = {}

    def _generateKeyframes(self):
        """
        Generates the keyframe datasets for _I3DKeyframes,
        the process is divided in armature animation and object animation
        """

        groups =  dcc.getActionGroupNames(self._treeID)
        if dcc.isTypeArmature(self._owner):     #armature
            for boneName in groups:             #group names
                boneFullPath = self._owner + "_" + boneName
                self._I3DKeyframes[boneFullPath] = I3DKeyframe(boneName,self._treeID,self._owner)
                # see dccBlender.py
                # if(not dcc.boneHasChildBone(boneName,self._owner)):           #add tailbones
                #     boneFullPath = self._owner + "_" + boneName + "_tail"
                #     tailBoneName = boneName+"_tail"
                #     self._I3DKeyframes[boneFullPath] = I3DKeyframe(tailBoneName,self._treeID,self._owner)
        else:   #not armature
            # for mesh in groups: #should only be one
            self._I3DKeyframes[self._owner] = I3DKeyframe(self._owner,self._treeID,self._owner)

class I3DKeyframe(object):
    """ I3DKeyframe is the container to store the individual keyframe data """

    def __init__(self, treeID , actionName,root):
        """
        Initialize the I3DKeyframe

        :param self: I3DKeyframe instance
        :param treeID: the name of the owner/bone which performs the action
        :param actionName: this is the name of the action
        :param root: this is the name of the owner of the action, this can be the same as treeID.
        It is different when the treeID is a bone (armature or animation Object)
        """

        self._treeID = treeID
        self._action = actionName
        self._root = root
        self._nodeID = 0
        self._I3DKeyframePoints = {}

    def _setNodeID(self, nodeID):   #get nodeID from related bone
        """ Set Node ID"""

        self._nodeID = nodeID

    def _setKeyframesData(self):
        """ Set keyframe data points """

        self._I3DKeyframePoints = dcc.getKeyframePointsLocationRotation(self._treeID,self._root,self._action)

    def _setEmptyKeyframe(self, nodeID):
        """ Creates a dummy I3DKeyframe """

        self._treeID = ""
        self._action = ""
        self._root = ""
        self._nodeID = nodeID
        self._I3DKeyframePoints = { 1: {}}

class I3DSceneGraph(object):
    """ I3DSceneGraph holds the relevant structure for the export data """

    def __init__(self):
        """ Initialize an empty I3DSceneGraph """

        self._nodeID    = 0
        self._shapeID   = 0
        self._matID     = 0
        self._fileID    = 0
        self._nodes     = {}
        self._shapes    = {}
        self._materials = {}
        self._files     = {}
        self._animationSet = {}
        self._nodes["ROOT"] = I3DSceneNode("ROOT")

    def addNode(self, nodeName, parentName="ROOT"):
        """
        Adds a node to the I3DSceneGraph

        :param self: I3DSceneGraph instance
        :param nodeName: Name of the Object which will be added to the SceneGraph
        :param parentName: Name of the parent Object
        """

        self._nodeID +=1
        treeItem   = I3DSceneNode(nodeName,parent = parentName,nodeID = self._nodeID)
        self._nodes[treeItem._treeID] = treeItem    #_treeID <=> object name
        treeParent = self._nodes[treeItem._parent]
        treeParent.addChild(treeItem._treeID)
        # UI check
        self.checkUI(treeItem)
        # Add IES profile file to file list, if not already present
        if "i3D_iesProfileFile" in treeItem._data and treeItem._data["type"] == "TYPE_LIGHT":
            self._fileID += 1
            fileItem = I3DFileNode(self._fileID,treeItem._data["i3D_iesProfileFile"])
            self._files[fileItem._treeID] = fileItem

    def addBone(self, bone, parent, armature):
        """
        Adds a bone to the I3DSceneGraph

        :param self: I3DSceneGraph instance
        :param bone: Name of the bone which will be added to the SceneGraph
        :param parent: Name of the parent bone
        :param armature: Name of the armature
        """

        self._nodeID +=1
        treeItem   = I3DSceneNode(bone, parent = parent, armature = armature, nodeID = self._nodeID)
        self._nodes[treeItem._treeID] = treeItem    #_treeID <=> object name
        m_treeParent = self._nodes[treeItem._parent]
        m_treeParent.addChild(treeItem._treeID)
        # UI check
        self.checkUI(treeItem)

    def generateShapes(self):
        """
        Generate the shapes which are added to the _shapes dictionary.

        The generation of the data takes different options into account.
        It checks for: mergeGroups and bounding Volumes, mergeChildren and if the
        objects are TYPE_NURBS_CURVE or TYPE_MESH
        """

        boundingVolumes = {}
        for treeID in self.traverse(m_node="DEPTH"):
            treeItem = self._nodes[treeID]
            data = treeItem._data
            value = data.get("i3D_boundingVolume", None)
            if value and value != "None":
                boundingVolumes[value] = treeID

        mergeGroupRoot = {}
        mergeGroupDict = {}
        export_merge_groups = UIGetAttrBool('i3D_exportMergeGroups')

        for m_treeID in self.traverse(m_node="DEPTH"):
            m_treeItem = self._nodes[m_treeID]
            m_data = m_treeItem._data

            if "i3D_mergeChildren" in m_treeItem._data:
                m_data["children"] = m_treeItem._children
                m_data["id"] = m_treeItem._nodeID
                hasMeshChildren = False
                for mergedChildNode in m_treeItem._children:
                    if self._nodes[mergedChildNode]._data["type"] == "TYPE_MESH":
                        hasMeshChildren = True
                    self._nodes[mergedChildNode]._data["type"] = "TYPE_TRANSFORM_GROUP"
                if hasMeshChildren:     # only make type mesh if any child is type mesh
                    m_data["type"] = "TYPE_MESH"

            # override BV
            if m_treeID in boundingVolumes.keys():
                m_data["boundingVolume"] = boundingVolumes[m_treeID]

            # merge groups
            mg_val = I3DGetAttributeValue(m_treeID, "i3D_mergeGroup")
            is_mg = mg_val != 0
            is_regular_shape = (not export_merge_groups or mg_val == 0) and m_data["type"] in ("TYPE_MESH", "TYPE_NURBS_CURVE")
            bv_key = "i3D_boundingVolume"

            if export_merge_groups:  # check if mergeGroups are enabled
                if is_mg:    # mergeGroup
                    if bv_key not in m_data or not m_data[bv_key] or m_data[bv_key] == "None":
                        mergeGroupDict[mg_val] = mergeGroupDict.setdefault(mg_val, []) + [m_treeID]
                        if not (mg_val in mergeGroupRoot):
                            mergeGroupRoot[mg_val] = m_treeID     # set default root
                        if I3DGetAttributeValue(m_treeID, "i3D_mergeGroupRoot"):
                            mergeGroupRoot[mg_val] = m_treeID     # set choosen root
                            # override BV for root node
                            mg_bv = f"MERGEGROUP_{mg_val}"
                            if mg_bv in boundingVolumes.keys():
                                m_data["boundingVolume"] = boundingVolumes[mg_bv]
                elif is_regular_shape:  # regular shape
                    self._shapeID += 1
                    m_shapeItem = I3DShapeNode(self._shapeID, m_data)
                    self._shapes[m_shapeItem._treeID] = m_shapeItem
            else:       # no mergeGroups
                if is_regular_shape:
                    self._shapeID += 1
                    if "i3D_mergeChildren" in m_treeItem._data:
                        m_data["name"] = f"MergedChildren{self._shapeID}"
                    m_shapeItem = I3DShapeNode(self._shapeID, m_data)
                    self._shapes[m_shapeItem._treeID] = m_shapeItem

        for boundVolKey, boundVolumeNode in boundingVolumes.items():
            if not self._nodes[boundVolumeNode]._children:  # delete bv if it has no children
                parent = self._nodes[boundVolumeNode]._parent
                self._nodes[parent].removeChild(boundVolumeNode)
                del self._nodes[boundVolumeNode]

        for mergeGroup, rootMemberId in mergeGroupRoot.items():
            members = mergeGroupDict[mergeGroup]
            if members:
                # Initialize data for the root member
                rootData = self._nodes[rootMemberId]._data
                rootData.update({'mergeGroupNum': mergeGroup,
                                 'mergeGroupMember': [rootMemberId],
                                 'skinBindNodeIds': [self._nodes[rootMemberId]._nodeID]})

                # If there is more than one member, process additional members
                if len(members) > 1:
                    nonRootMembers = [m for m in members if m != rootMemberId]
                    rootData['mergeGroupMember'].extend(nonRootMembers)
                    rootData['skinBindNodeIds'].extend(self._nodes[m]._nodeID for m in nonRootMembers)

                    for m in nonRootMembers:
                        self._nodes[m]._data['type'] = "TYPE_TRANSFORM_GROUP"

                # Check if the data type is one that requires a shape ID
                if rootData["type"] in ("TYPE_MESH", "TYPE_NURBS_CURVE"):
                    self._shapeID += 1
                    m_shapeItem = I3DShapeNode(self._shapeID, rootData)
                    self._shapes[m_shapeItem._treeID] = m_shapeItem

        for m_key, m_shape in self._shapes.items():
            m_shape._generateData()     # access data

    def mapSkinning(self):
        """ Maps bones to armature with their nodeIds and then maps the same set to all objects which have armature applied """

        armatures = []
        #get nodeID's of bones and assign to armatures
        for key, node in self._nodes.items():
            if(dcc.isTypeArmature(node._data['name'])): #isArmature
                armatureNode = node
                armatureNode._data['bones'] = {}        #armature get bones
                armatures.append(armatureNode)

                #list of all boneNodes with the current armature
                for boneNode in [ refNode for refNode in self._nodes.values() if "armature" in refNode._data if armatureNode._data["name"] == refNode._data["armature"]]:
                    boneName = boneNode._data["name"]
                    boneFullPath = armatureNode._data['name']  + "_" + boneName
                    armatureNode._data['bones'][boneName] = self._nodes[boneFullPath]._nodeID
        #maps bone Ids to object with armatures
        for key, node in self._nodes.items():
            for armature in armatures:
                try:
                    dcc.UIAddMessage('mapSkinning node {0} {1}'.format(key, node._data['name']))
                    for modifier in bpy.data.objects[node._data['name']].modifiers:
                        dcc.UIAddMessage('mapSkinning modifier {0}'.format(modifier.object.name))
                        if modifier.type == 'ARMATURE' and modifier.object and modifier.object.name == armature._data["name"] and UIGetAttrBool("i3D_exportSkinWeigths"):
                            dcc.UIAddMessage('mapSkinning if passed {0}'.format(modifier.object.name))
                            for group in bpy.data.objects[node._data['name']].vertex_groups:
                                try:
                                    # boneMap[group.index] = m_sceneNodeData['bones'][group.name]     #assign bone nodeID to bone index
                                    #node._data['bones'] = armature._data['bones']
                                    dcc.UIAddMessage('vertex_group {0}'.format(group.name))
                                    if 'bones' not in node._data:
                                        node._data['bones'] = {}
                                    node._data['bones'].update(armature._data['bones'])
                                    dcc.UIAddMessage('mapSkinning update bones {0}'.format(armature._data['bones']))
                                    node._data['armature'] = armature._data['name']
                                except Exception as e:
                                    dcc.UIAddMessage("exception {0}".format(e))
                except Exception as e:
                    dcc.UIAddMessage("exception {0}".format(e))

        #single bone Influence
        # print(str([node._data["name"] for node in self._nodes.values() if dcc.isTypeMesh(node._data['name'])]))
        for node in [node for node in self._nodes.values() if dcc.isTypeMesh(node._data['name'])]:
            if "armature" in node._data:
                vertexGroupName = dcc.getSingleBoneInfluence(node._data["name"])
                if vertexGroupName:
                    #get influencer bone
                    if(node._parent == node._data['armature'] and len(node._children) == 0):    #child of armature and no children
                        boneNodeName = node._data['armature'] + "_" + vertexGroupName
                        boneNode = self._nodes[boneNodeName]        #boneNode
                        parentNodeName = node._parent               #parentNode
                        parentNode = self._nodes[parentNodeName]
                        parentNode._children.remove(node._data["name"])
                        boneNode._children.append(node._data["name"])
                        node._parent = boneNodeName
                        #recompute transformation
                        translation, rotation, scale = dcc.updateNodeTransformation(node._data["name"],vertexGroupName, node._data['armature'])
                        node._data["translation"] = translation
                        node._data["rotation"] = rotation
                        node._data["scale"] = scale

    def generateMaterials(self):
        """ Generates an I3DMaterialNode for all materials defined within the mesh-type objects"""

        for shape in self._shapes.values():
            if "TYPE_MESH" == shape._shapeType:
                materialsList, _ = dcc.getShapeMaterials(shape._treeID)
                for mat in materialsList:
                    self._matID += 1
                    materialItem = I3DMaterialNode(self._matID,mat)
                    self._materials[materialItem._treeID] = materialItem

    def updateMaterials(self):
        """ Updates the _materials with all materials from all shapes"""

        for shape in self._shapes.values():
            if "TYPE_MESH" == shape._shapeType and "Materials" in shape._data:
                for material in shape._data["Materials"]:
                    if not material in  self._materials:
                        self._matID += 1
                        materialItem = I3DMaterialNode(self._matID,material)
                        self._materials[materialItem._treeID] = materialItem

    def generateFiles(self):
        """ Generate I3DFileNode's for every file used in a material"""

        self.updateMaterials()
        for material in self._materials.values():
            filesDict = dcc.getMaterialFiles(material._treeID)
            for file, fileType in filesDict.items():
                self._fileID += 1
                fileItem = I3DFileNode(self._fileID,file,fileType)
                self._files[fileItem._treeID] = fileItem

    def generateAnimation(self):
        """
        Generate the animation data hierarchy and generates all data.

        Every animated object receives an I3DAnimationSet. For every Action of this object
        are clips created with animationSet._generateClips
        From all Clips the keyframe data is structured as I3DKeyframe which contain the keyframe datapoints

        Clips with the same name codex are merged and restructured for the GIANTS editor
        """

        for treeID in self.traverse(m_node="DEPTH"):
            treeItem   = self._nodes[treeID]
            data       = treeItem._data
            if(dcc.hasAnimation(treeItem._data["name"])):    #bpy.data.object with associated animation
                animationSet = I3DAnimationSet(data)
                self._animationSet[treeID] = animationSet

        for key, animationSet in self._animationSet.items():
            animationSet._generateClips()
            for key, clip in animationSet._I3DClip.items():
                clip._generateKeyframes()
                for key, keyframe in clip._I3DKeyframes.items():
                    keyframe._setNodeID(self._nodes[key]._nodeID)   #key is supposed to be a bone/tailBone or animation Object
                    keyframe._setKeyframesData()
        #merge clips
        mergeCandidateClips = []
        regex = re.compile('^\w+_\w+\.\d{1,3}')
        for animationSetKey, animationSetItem in self._animationSet.items():
            for clipKey, clipItem in animationSetItem._I3DClip.items():
                if regex.search(clipItem._treeID):
                    animationSetItem._name = clipItem._treeID.split("_")[0]
                    clipItem._treeID = clipItem._treeID.split(".")[0].split("_")[1]
                    mergeCandidateClips.append(clipItem)        #fill candidate List per animationSet
        #identify matches
        deleteList = []
        for i in range(0,len(mergeCandidateClips)):
            for k in range(i+1,len(mergeCandidateClips)):
                if(mergeCandidateClips[i]._treeID == mergeCandidateClips[k]._treeID and not mergeCandidateClips[i] in deleteList and not mergeCandidateClips[k] in deleteList):
                    mergeCandidateClips[i]._I3DKeyframes[mergeCandidateClips[k]._owner] = mergeCandidateClips[k]._I3DKeyframes[mergeCandidateClips[k]._owner]       #merge I3DKeyframes
                    deleteList.append(mergeCandidateClips[k])
                    if (not (mergeCandidateClips[i]._duration > mergeCandidateClips[k]._duration)): mergeCandidateClips[i]._duration = mergeCandidateClips[k]._duration     #take larger duration
        #delete clip
        for delItem in deleteList:
            for animationSetKey, animationSetItem in self._animationSet.items():
                for clipKey, clipItem in animationSetItem._I3DClip.items():
                    if clipItem == delItem:
                        del animationSetItem._I3DClip[clipKey]
                        break
        #if no clips remain, delete animation set
        for key in [k for k in self._animationSet.keys() if not self._animationSet[k]._I3DClip]:
            del self._animationSet[key]
        #fill up with empty data to fullfill requirements
        for k, i in self._animationSet.items():
            keyframeDict = {}
            for clipKey,clipItem in i._I3DClip.items():
                for keyframeKey,keyframeItem in clipItem._I3DKeyframes.items():
                    keyframeDict[keyframeKey] = keyframeItem
            for clipKey,clipItem in i._I3DClip.items():
                for checkKey, checkItem in keyframeDict.items():
                    if checkKey in clipItem._I3DKeyframes.keys():
                        pass
                    else:
                        clipItem._I3DKeyframes[checkKey] = I3DKeyframe("","","")     #emptyKeyframe, only nodeID
                        clipItem._I3DKeyframes[checkKey]._setEmptyKeyframe(checkItem._nodeID)

    def generateInstances(self):
        """ Generates an I3DSceneNode for every TYPE_INSTANCER object from the SceneGraph """

        for treeID in self.traverse(m_node="DEPTH"):
            treeItem   = self._nodes[treeID]
            data       = treeItem._data
            if ("TYPE_INSTANCER" == data["type"]):
                nodes = getInstances(treeID)        #always empty list
                for i in range(len(nodes)):
                    self._nodeID +=1
                    node = nodes[i]
                    treeItemNew   = I3DSceneNode(node["fullPathNameOrig"],parent = treeID,nodeID = self._nodeID)
                    treeItemNew._treeID = "{}_{}".format(treeItemNew._treeID,i)
                    treeItemNew._data['fullPathNameOrig'] = node["fullPathNameOrig"]
                    treeItemNew._data['translation']      = node["translation"]
                    treeItemNew._data['rotation']         = node["rotation"]
                    treeItemNew._data['scale']            = node["scale"]
                    self._nodes[treeItemNew._treeID] = treeItemNew
                    treeParent = self._nodes[treeItemNew._parent]
                    treeParent.addChild(treeItemNew._treeID)

    def checkUI(self, treeItem ):
        """ Checks Export settings and set every unused object to TYPE_TRANSFORM_GROUP """

        data = treeItem._data
        if "TYPE_LIGHT" == data["type"] and (False==UIGetAttrBool('i3D_exportLights')):
            data["type"] = "TYPE_TRANSFORM_GROUP"
        elif "TYPE_CAMERA" == data["type"] and (False==UIGetAttrBool('i3D_exportCameras')):
            data["type"] = "TYPE_TRANSFORM_GROUP"
        elif "TYPE_NURBS_CURVE" == data["type"] and (False==UIGetAttrBool('i3D_exportNurbsCurves')):
            data["type"] = "TYPE_TRANSFORM_GROUP"
        elif ("TYPE_MESH" == data["type"] or "TYPE_NURBS_CURVE" == data["type"] or "TYPE_MERGED_MESH" == data["type"] or "TYPE_SPLIT_SHAPE" == data["type"]) and (False==UIGetAttrBool('i3D_exportShapes')):
            data["type"] = "TYPE_TRANSFORM_GROUP"
        # elif ("TYPE_EMITTER" == data["type"] and (False==UIGetAttrBool('i3D_exportParticleSystems'))):
            # data["type"] = "TYPE_TRANSFORM_GROUP"
        elif ("TYPE_MERGED_MESH" == data["type"] and (False==UIGetAttrBool('i3D_exportMergeGroups'))):
            data["type"] = "TYPE_MESH"

    def removeNode(self,treeID):
        """ Removes treeID and all its children from _nodes """

        treeItem   = self._nodes[treeID]
        treeParent = self._nodes[treeItem._parent]
        treeChildren = treeItem._children
        for treeChild in treeChildren:
            self.removeNode(treeChild)
        treeParent.removeChild(treeItem._treeID)
        del self._nodes[treeItem._treeID]

    def traverse(self, m_treeID = "ROOT", m_node = "DEPTH"):
        """
        Returns one by one all the nodes (by name) in the subtree of m_treeID.
        m_node only specifies the type of the traverse
        """

        yield m_treeID
        m_queue = self._nodes[m_treeID]._children
        while m_queue:
            yield m_queue[0]
            m_expansion = self._nodes[m_queue[0]]._children
            if  "DEPTH" == m_node:
                m_queue = m_expansion + m_queue[1:]  # depth-first
            elif "BREADTH" == m_node:
                m_queue = m_queue[1:] + m_expansion  # width-first

    def display(self, m_treeID = "ROOT", m_depth =0):
        """ Displays the _nodes hierarchy """

        treeItem      = self._nodes[m_treeID]
        data          = treeItem._data
        treeChildren  = treeItem._children
        dcc.UIAddMessage("    "*m_depth + "{0} {1} {2}".format(treeItem._nodeID,m_treeID,data["type"]) )
        m_depth += 1
        for m_treeChild in treeChildren:
            self.display(m_treeChild,m_depth)

    def xmlWriteScene(self,xmlParent,treeID="ROOT"):
        """
        Write the xml Scene entries recursively

        :param self: I3DSceneGraph instance
        :param xmlParent: current xml layer to write data
        :param treeID: current node
        """

        treeItem = self._nodes[treeID]
        treeItem.sortChilder()
        treeChildren = treeItem._children
        if "i3D_mergeChildren" in treeItem._data:
            treeChildren = []

        for treeChildID in treeChildren:
            treeChildItem = self._nodes[treeChildID]
            data          = treeChildItem._data
            if ("TYPE_LIGHT" == data["type"]):
                xmlCurrent  = xml_ET.SubElement( xmlParent, "Light" )
                self._xmlWriteSceneObject_Light( treeChildItem, xmlCurrent )
            elif ("TYPE_CAMERA" == data["type"]):
                xmlCurrent  = xml_ET.SubElement( xmlParent, "Camera" )
                self._xmlWriteSceneObject_Camera( treeChildItem, xmlCurrent )
            elif ("TYPE_MESH" == data["type"]):
                xmlCurrent  = xml_ET.SubElement( xmlParent, "Shape" )
                self._xmlWriteSceneObject_ShapeMesh( treeChildItem, xmlCurrent )
            elif ("TYPE_NURBS_CURVE" == data["type"]):
                xmlCurrent  = xml_ET.SubElement( xmlParent, "Shape" )
                self._xmlWriteSceneObject_ShapeCurve( treeChildItem, xmlCurrent )
            else:
                xmlCurrent  = xml_ET.SubElement( xmlParent, "TransformGroup" )
                self._xmlWriteSceneObject_TransformGroup( treeChildItem, xmlCurrent )
            self.xmlWriteScene(xmlCurrent,treeChildID)

    def _xmlWriteSceneObject_General(self, treeItem, xmlCurrent ):
        """
        Writes general attributes to the .i3d file

        :param self: I3DSceneGraph instance
        :param treeItem: current node
        :param xmlCurrent: current xml layer to write data
        """

        data = treeItem._data
        self._xmlWriteString( xmlCurrent, "name", data["name"] )
        self._xmlWriteInt( xmlCurrent ,"nodeId", treeItem._nodeID )

        if "translation" in data:
            self._xmlWriteString( xmlCurrent, "translation", data["translation"] )
        if "rotation" in data:
            self._xmlWriteString( xmlCurrent, "rotation",    data["rotation"] )
        if "scale" in data:
            self._xmlWriteString( xmlCurrent, "scale",       data["scale"] )
        if "visibility" in data:
            if False == data["visibility"]:
                xmlCurrent.set( "visibility", "false" )
        self._xmlWriteAttr( xmlCurrent, "clipDistance", data, "i3D_clipDistance")
        self._xmlWriteAttr( xmlCurrent, "objectMask",   data, "i3D_objectMask")
        self._xmlWriteAttr( xmlCurrent, "buildNavMeshMask",   data, "i3D_navMeshMask")
        self._xmlWriteAttr( xmlCurrent ,"lockedgroup", data, "i3D_lockedGroup")

    def _xmlWriteSceneObject_TransformGroup(self, treeItem, xmlCurrent):
        """
        Writes Transform Group specific attributes to the .i3d file

        :param self: I3DSceneGraph instance
        :param treeItem: current node
        :param xmlCurrent: current xml layer to write data
        """

        self._xmlWriteSceneObject_General(treeItem,xmlCurrent)
        m_data  = treeItem._data
        m_joint = None
        if ( "i3D_joint" in m_data):
            m_joint = m_data["i3D_joint"]
        if ( "i3D_lod" in m_data):
            m_lodDistance = ""
            m_lod1 = 0
            m_lod2 = 0
            m_lod3 = 0
            if ("i3D_lod1" in m_data): m_lod1 = m_data["i3D_lod1"]
            if ("i3D_lod2" in m_data): m_lod2 = m_data["i3D_lod2"]
            if ("i3D_lod3" in m_data): m_lod3 = m_data["i3D_lod3"]
            if ("i3D_lod1" in m_data):
                m_lodDistance = "0 {:g}".format(m_lod1)
            if (m_lod2 > m_lod1):
                m_lodDistance += " {:g}".format(m_lod2)
            if (m_lod3 > m_lod2):
                m_lodDistance += " {:g}".format(m_lod3)
            if (m_lodDistance):
                self._xmlWriteString( xmlCurrent, "lodDistance", m_lodDistance )
                m_joint = None
        if (m_joint):
            # i3dConverter expects joint="true" if joint parameters are added
            self._xmlWriteAttr( xmlCurrent, "joint",            m_data, "i3D_joint" )
            self._xmlWriteAttr( xmlCurrent, "projection",       m_data, "i3D_projection" )
            self._xmlWriteAttr( xmlCurrent, "xAxisDrive",       m_data, "i3D_xAxisDrive" )
            self._xmlWriteAttr( xmlCurrent, "yAxisDrive",       m_data, "i3D_yAxisDrive" )
            self._xmlWriteAttr( xmlCurrent, "zAxisDrive",       m_data, "i3D_zAxisDrive" )
            self._xmlWriteAttr( xmlCurrent, "drivePos",         m_data, "i3D_drivePos" )
            self._xmlWriteAttr( xmlCurrent, "breakableJoint",   m_data, "i3D_breakableJoint" )
            self._xmlWriteAttr( xmlCurrent, "projDistance",     m_data, "i3D_projDistance" )
            self._xmlWriteAttr( xmlCurrent, "projAngle",        m_data, "i3D_projAngle" )
            self._xmlWriteAttr( xmlCurrent, "driveForceLimit",  m_data, "i3D_driveForceLimit" )
            self._xmlWriteAttr( xmlCurrent, "driveSpring",      m_data, "i3D_driveSpring" )
            self._xmlWriteAttr( xmlCurrent, "driveDamping",     m_data, "i3D_driveDamping" )
            self._xmlWriteAttr( xmlCurrent, "jointBreakForce",  m_data, "i3D_jointBreakForce" )
            self._xmlWriteAttr( xmlCurrent, "jointBreakTorque", m_data, "i3D_jointBreakTorque" )

    def _xmlWriteSceneObject_Light(self, treeItem, xmlCurrent):
        """
        Writes Light specific attributes to the .i3d file

        :param self: I3DSceneGraph instance
        :param treeItem: current node
        :param xmlCurrent: current xml layer to write data
        """

        self._xmlWriteSceneObject_General(treeItem,xmlCurrent)
        self._wmlWriteSceneObject_EnvironmentAttributes(treeItem, xmlCurrent)
        data  = treeItem._data
        if ( "lightData" in data):
            light = data["lightData"]
            for key,value in light.items():
                self._xmlWriteString( xmlCurrent, key, value )

            if light["castShadowMap"]:
                self._xmlWriteAttr( xmlCurrent, "softShadowsLightSize", data, "i3D_softShadowsLightSize")
                self._xmlWriteAttr( xmlCurrent, "softShadowsLightDistance", data, "i3D_softShadowsLightDistance")
                self._xmlWriteAttr( xmlCurrent, "softShadowsDepthBiasFactor", data, "i3D_softShadowsDepthBiasFactor")
                self._xmlWriteAttr( xmlCurrent, "softShadowsMaxPenumbraSize", data, "i3D_softShadowsMaxPenumbraSize")

            if "i3D_isLightScattering" in data and data["i3D_isLightScattering"]:
                self._xmlWriteAttr( xmlCurrent, "scattering", data, "i3D_isLightScattering")
                self._xmlWriteAttr( xmlCurrent, "scatteringIntensity", data, "i3D_lightScatteringIntensity")
                self._xmlWriteAttr( xmlCurrent, "scatteringConeAngle", data, "i3D_lightScatteringConeAngle")

            # IES Profile files are only supported for spot lights for now
            if light["type"] == "spot" and "i3D_iesProfileFile" in data:
                fileItem = self._files[data["i3D_iesProfileFile"]]
                self._xmlWriteInt( xmlCurrent, "iesProfileFileId", fileItem._fileID )

    def _xmlWriteSceneObject_Camera( self, treeItem, xmlCurrent ):
        """
        Writes Camera specific attributes to the .i3d file

        :param self: I3DSceneGraph instance
        :param treeItem: current node
        :param xmlCurrent: current xml layer to write data
        """
        self._xmlWriteSceneObject_General(treeItem,xmlCurrent)
        data  = treeItem._data
        if ( "cameraData" in data):
            camera = data["cameraData"]
            for key,value in camera.items():
                self._xmlWriteString( xmlCurrent, key, value )

    def _xmlWriteSceneObject_ShapeMesh(self, treeItem, xmlCurrent):
        """
        Writes Shape Mesh specific attributes to the .i3d file

        :param self: I3DSceneGraph instance
        :param treeItem: current node
        :param xmlCurrent: current xml layer to write data
        """

        self._xmlWriteSceneObject_General(treeItem,xmlCurrent)
        self._wmlWriteSceneObject_EnvironmentAttributes(treeItem, xmlCurrent)
        data  = treeItem._data
        shapeStr      = dcc.getShapeNode(data)
        if (shapeStr not in self._shapes):
            return

        shapeID       = self._shapes[shapeStr]._shapeID
        materialsList = self._shapes[shapeStr]._data["Materials"]
        # -------------------------------------------------------------
        matIdList = []
        for mat in materialsList:
            matID = self._materials[mat]._materialID
            matIdList.append(matID)
        materialIDs = ' '.join(map(str, matIdList))

        if "i3D_mergeChildren" in data and data["i3D_mergeChildren"] == 1:          #merge children material list
            materialIDs = ' '.join(map(str, [matIdList[0]] * int(self._shapes[shapeStr]._data["Subsets"]["count"])))
        # -------------------------------------------------------------
        isRigidBody = False
        isStatic    = False
        isKinematic = False
        isDynamic   = False
        isCompound  = False
        isCompoundChild = False
        if ( "i3D_static" in data):
            isStatic    = data["i3D_static"]
        if ( "i3D_kinematic" in data):
            isKinematic = data["i3D_kinematic"]
        if ( "i3D_dynamic" in data):
            isDynamic   = data["i3D_dynamic"]
        if ( "i3D_compound" in data):
            isCompound  = data["i3D_compound"]
        if ( "i3D_compoundChild" in data):
            isCompoundChild = data["i3D_compoundChild"]
        if   ( isStatic ):
            isRigidBody = True
            isKinematic = False
            isDynamic   = False
        elif ( isDynamic ):
            isRigidBody = True
            isKinematic = False
        elif ( isKinematic ):
            isRigidBody = True
        if ( not isRigidBody ):
            isCompound  = False
        if ( isCompound )       : isCompoundChild = False
        if ( isCompoundChild )  : isRigidBody = True
        self._xmlWriteInt( xmlCurrent ,"shapeId", shapeID )
        if ( isStatic )        : self._xmlWriteString( xmlCurrent, "static",        "true" )
        if ( isDynamic )       : self._xmlWriteString( xmlCurrent, "dynamic",       "true" )
        if ( isKinematic )     : self._xmlWriteString( xmlCurrent, "kinematic",     "true" )
        if ( isCompound )      : self._xmlWriteString( xmlCurrent, "compound",      "true" )
        if ( isCompoundChild ) : self._xmlWriteString( xmlCurrent, "compoundChild", "true" )
        if ( isRigidBody ):
            self._xmlWriteAttr( xmlCurrent, "restitution",          data, "i3D_restitution" )
            self._xmlWriteAttr( xmlCurrent, "staticFriction",       data, "i3D_staticFriction" )
            self._xmlWriteAttr( xmlCurrent, "dynamicFriction",      data, "i3D_dynamicFriction" )
            self._xmlWriteAttr( xmlCurrent, "linearDamping",        data, "i3D_linearDamping" )
            self._xmlWriteAttr( xmlCurrent, "angularDamping",       data, "i3D_angularDamping" )
            self._xmlWriteAttr( xmlCurrent, "density",              data, "i3D_density" )
            self._xmlWriteAttr( xmlCurrent, "ccd",                  data, "i3D_ccd" )
            self._xmlWriteAttr( xmlCurrent, "solverIterationCount", data, "i3D_solverIterationCount" )
        self._xmlWriteAttr( xmlCurrent, "collision",      data, "i3D_collision" )
        self._xmlWriteAttr( xmlCurrent, "trigger",        data, "i3D_trigger" )
        self._xmlWriteAttr( xmlCurrent, "nonRenderable",  data, "i3D_nonRenderable" )
        self._xmlWriteAttr( xmlCurrent, "castsShadows",   data, "i3D_castsShadows" )
        self._xmlWriteAttr( xmlCurrent, "receiveShadows", data, "i3D_receiveShadows" )
        self._xmlWriteAttr( xmlCurrent, "renderedInViewports",    data, "i3D_renderedInViewports" )
        self._xmlWriteAttr( xmlCurrent, "doubleSided",    data, "i3D_doubleSided" )
        self._xmlWriteAttr( xmlCurrent, "decalLayer",     data, "i3D_decalLayer" )
        self._xmlWriteAttr( xmlCurrent, "collisionFilterMask",  data, "i3D_collisionFilterMask" )
        self._xmlWriteAttr( xmlCurrent, "collisionFilterGroup",  data, "i3D_collisionFilterGroup" )
        splitMinU = 0
        splitMinV = 0
        splitMaxU = 1
        splitMaxV = 1
        splitUvWorldScale = 1
        if ( "i3D_splitMinU" in data): splitMinU = data["i3D_splitMinU"]
        if ( "i3D_splitMinV" in data): splitMinV = data["i3D_splitMinV"]
        if ( "i3D_splitMaxU" in data): splitMaxU = data["i3D_splitMaxU"]
        if ( "i3D_splitMaxV" in data): splitMaxV = data["i3D_splitMaxV"]
        if ( "i3D_splitUvWorldScale" in data): splitUvWorldScale = data["i3D_splitUvWorldScale"]
        if self._xmlWriteAttr( xmlCurrent, "splitType", data, "i3D_splitType" ):
            splitUVstr = "{:g} {:g} {:g} {:g} {:g}".format(splitMinU,splitMinV,splitMaxU,splitMaxV,splitUvWorldScale)
            self._xmlWriteString( xmlCurrent, "splitUvs", splitUVstr )
        self._xmlWriteString( xmlCurrent, "materialIds", materialIDs )
        if ( "skinBindNodeIds" in self._shapes[shapeStr]._data):
            self._xmlWriteString( xmlCurrent, "skinBindNodeIds", self._shapes[shapeStr]._data["skinBindNodeIds"] )
        self._xmlWriteAttr( xmlCurrent, "occluder",     data, "i3D_oc" )
        self._xmlWriteAttr( xmlCurrent, "terrainDecal", data, "i3D_terrainDecal")

    def _xmlWriteSceneObject_ShapeCurve(self, treeItem, xmlCurrent):
        """
        Writes Shape Curve specific attributes to the .i3d file

        :param self: I3DSceneGraph instance
        :param treeItem: current node
        :param xmlCurrent: current xml layer to write data
        """

        self._xmlWriteSceneObject_General(treeItem,xmlCurrent)
        self._wmlWriteSceneObject_EnvironmentAttributes(treeItem, xmlCurrent)
        data     = treeItem._data
        shapeStr = dcc.getShapeNode(data)
        shapeID  = self._shapes[shapeStr]._shapeID
        self._xmlWriteInt( xmlCurrent,"shapeId", shapeID )

    def _wmlWriteSceneObject_EnvironmentAttributes(self, treeItem, xmlCurrent):
        """
        Writes Environment specific attributes to the .i3d file
        Environment attributes are used with Shape / Light / AudioSource

        :param self: I3DSceneGraph instance
        :param treeItem: current node
        :param xmlCurrent: current xml layer to write data
        """

        data = treeItem._data

        self._xmlWriteAttr( xmlCurrent, "minuteOfDayStart", data, "i3D_minuteOfDayStart")
        self._xmlWriteAttr( xmlCurrent, "minuteOfDayEnd", data, "i3D_minuteOfDayEnd")
        self._xmlWriteAttr( xmlCurrent, "dayOfYearStart", data, "i3D_dayOfYearStart")
        self._xmlWriteAttr( xmlCurrent, "dayOfYearEnd", data, "i3D_dayOfYearEnd")
        self._xmlWriteAttr( xmlCurrent, "weatherRequiredMask", data, "i3D_weatherMask")
        self._xmlWriteAttr( xmlCurrent, "viewerSpacialityRequiredMask", data, "i3D_viewerSpacialityMask")
        self._xmlWriteAttr( xmlCurrent, "weatherPreventMask",data,'i3D_weatherPreventMask')
        self._xmlWriteAttr( xmlCurrent, "viewerSpacialityPreventMask", data,'i3D_viewerSpacialityPreventMask')
        self._xmlWriteAttr( xmlCurrent, "renderInvisible", data, 'i3D_renderInvisible')
        self._xmlWriteAttr( xmlCurrent, "visibleShaderParameter", data, 'i3D_visibleShaderParam')
        # if 'i3D_forceVisibilityCondition' in data: self._xmlWriteAttr( xmlCurrent, "")

    def xmlWriteFiles(self,xmlParent):
        """ Writes alle files to the .i3d file """

        for file in self._files.values():
            xmlCurrent = xml_ET.SubElement( xmlParent, "File" )
            data       = file._data
            self._xmlWriteInt(    xmlCurrent, "fileId",       file._fileID )
            self._xmlWriteString( xmlCurrent, "relativePath", data["relativePath"]  )
            self._xmlWriteString( xmlCurrent, "filename",     data["filename"] )

    def xmlWriteMaterials(self,xmlParent):
        """ Writes all Materials to the .i3d file """

        for key, material in self._materials.items():
            xmlCurrent = xml_ET.SubElement( xmlParent, "Material" )
            data = material._data
            self._xmlWriteInt(    xmlCurrent, "materialId",    material._materialID )
            self._xmlWriteString( xmlCurrent, "name",          data["name"]  )
            if "diffuseColor" in data:
                self._xmlWriteString( xmlCurrent, "diffuseColor",  data["diffuseColor"]  )
            self._xmlWriteString( xmlCurrent, "specularColor", data["specularColor"]  )
            if "emissiveColor" in data:
                self._xmlWriteString( xmlCurrent, "emissiveColor", data["emissiveColor"] )
            if "alphaBlending" in data:
                self._xmlWriteString( xmlCurrent, "alphaBlending", data["alphaBlending"] )
            for m_item in ["Texture","Glossmap","Normalmap","Emissivemap"]:
                if m_item in data:
                    xmlChild = xml_ET.SubElement( xmlCurrent, m_item )
                    fileID = self._files[data[m_item]]._fileID
                    self._xmlWriteInt( xmlChild, "fileId", fileID )
                    if m_item == "Normalmap":
                        if "bumpDepth" in data:
                            self._xmlWriteFloat(xmlChild, "bumpDepth", data["bumpDepth"])
            if "customShaderVariation" in data:
                self._xmlWriteString( xmlCurrent, "customShaderVariation", data["customShaderVariation"] )
            if "CustomParameter" in data:
                for key, m_value in data["CustomParameter"].items():
                    xmlChild = xml_ET.SubElement( xmlCurrent, "CustomParameter" )
                    self._xmlWriteString( xmlChild, "name",  key )
                    self._xmlWriteString( xmlChild, "value", m_value )
            if "needsReflectionMap" in data:
                xmlChild = xml_ET.SubElement( xmlCurrent, "Reflectionmap" )
                self._xmlWriteString( xmlChild, "type",  "planar" )
                self._xmlWriteString( xmlChild, "refractiveIndex", "10" )
                self._xmlWriteString( xmlChild, "bumpScale", "0.1" )
            if "needsRefractionMap" in data and data["needsRefractionMap"]:
                xmlChild = xml_ET.SubElement( xmlCurrent, "Refractionmap")
                self._xmlWriteString( xmlChild, "type", "planar" )

                lightAbsorbance = 0.0
                if "refractionMapLightAbsorbance" in data:
                    lightAbsorbance = float(data["refractionMapLightAbsorbance"])
                self._xmlWriteString( xmlChild, "coeff", str(1.0 - lightAbsorbance))

                bumpScale = 0.1
                if "refractionMapBumpScale" in data:
                    bumpScale = data["refractionMapBumpScale"]
                self._xmlWriteString( xmlChild, "bumpScale", bumpScale)

                withSSRData = "false"
                if "refractionMapWithSSRData" in data and data["refractionMapWithSSRData"]:
                    withSSRData = "true"
                self._xmlWriteString( xmlChild, "withSSRData", withSSRData)
            if "customShader" in data:
                fileID = self._files[data["customShader"]]._fileID
                self._xmlWriteInt( xmlCurrent, "customShaderId", fileID )
            if "Custommap" in data:
                for key, m_value in data["Custommap"].items():
                    xmlChild = xml_ET.SubElement( xmlCurrent, "Custommap" )
                    fileID = self._files[m_value]._fileID
                    self._xmlWriteString( xmlChild, "name",   key )
                    self._xmlWriteInt(    xmlChild, "fileId", fileID )
            if "shadingRate" in data:
                self._xmlWriteString( xmlCurrent, "shadingRate", data["shadingRate"] )

    def xmlWriteShapes(self,xmlParent):
        """ Write all shapes to .i3d file """

        for key, shape in self._shapes.items():
            #dcc.UIAddMessage("{1} {0} {2}".format( key, shape._shapeID, shape._treeID ))
            if "TYPE_MESH" == shape._shapeType:
                self._xmlWriteShape_Mesh( xmlParent, shape )
            if "TYPE_NURBS_CURVE" == shape._shapeType:
                self._xmlWriteShape_Curve( xmlParent, shape )

    def xmlWriteAnimation(self, xmlParent):
        """ Write all animation data to the .i3d file """

        xmlCurrent = xml_ET.SubElement( xmlParent, "AnimationSets" )
        for animationSet in self._animationSet.values():
            xmlAnimationSet = xml_ET.SubElement( xmlCurrent, "AnimationSet" )
            self._xmlWriteString(xmlAnimationSet,"name",animationSet._name)
            for clip in animationSet._I3DClip.values():
                xmlClip = xml_ET.SubElement( xmlAnimationSet, "Clip" )
                self._xmlWriteString(xmlClip,"name",clip._treeID)
                self._xmlWriteFloat(xmlClip,"duration",clip._duration)
                for key in sorted(clip._I3DKeyframes):
                    keyframe = clip._I3DKeyframes[key]
                    xmlKeyframe = xml_ET.SubElement( xmlClip, "Keyframes" )
                    self._xmlWriteInt(xmlKeyframe,"nodeId",keyframe._nodeID)
                    for keyframePointDataKey, keyframePointData in keyframe._I3DKeyframePoints.items():
                        xmlKeyframePoint = xml_ET.SubElement( xmlKeyframe, "Keyframe" )
                        data = dcc.formatKeyframePointData(keyframePointDataKey,keyframePointData)
                        if('time' in data): self._xmlWriteFloat(xmlKeyframePoint,"time",data['time'])
                        if('translation' in data): self._xmlWriteString(xmlKeyframePoint,"translation",data['translation'])
                        if('iptin' in data): self._xmlWriteString(xmlKeyframePoint,"iptin",data['iptin'])
                        if('iptout' in data): self._xmlWriteString(xmlKeyframePoint,"iptout",data['iptout'])
                        if('rotation' in data): self._xmlWriteString(xmlKeyframePoint,"rotation",data['rotation'])
                        if('iprin' in data): self._xmlWriteString(xmlKeyframePoint,"iprin",data['iprin'])
                        if('iprout' in data): self._xmlWriteString(xmlKeyframePoint,"iprout",data['iprout'])
                        if('scale' in data): self._xmlWriteString(xmlKeyframePoint,"scale",data['scale'])
                        if('ipsin' in data): self._xmlWriteString(xmlKeyframePoint,"ipsin",data['ipsin'])
                        if('ipsout' in data): self._xmlWriteString(xmlKeyframePoint,"ipsout",data['ipsout'])

    def xmlWriteUserAttributes(self,xmlParent):
        """ Write all user attributes to the .i3d file """

        for treeID in self.traverse(m_node="DEPTH"):
            treeItem = self._nodes[treeID]
            attributes = dcc.getNodeUserAttributes(treeID)
            if len(attributes):
                xmlCurrent  = xml_ET.SubElement( xmlParent, "UserAttribute" )
                self._xmlWriteInt( xmlCurrent, "nodeId", treeItem._nodeID )
                for attr in attributes:
                    xmlAttr  = xml_ET.SubElement( xmlCurrent, "Attribute" )
                    self._xmlWriteString( xmlAttr, "name",  attr["name"] )
                    self._xmlWriteString( xmlAttr, "type",  attr["type"] )
                    self._xmlWriteString( xmlAttr, "value", attr["value"] )

    def  _xmlWriteShape_Curve(self, xmlParent, shape):
        """ Write Shape Curve data to the .i3d file """

        xmlCurrent  = xml_ET.SubElement( xmlParent, "NurbsCurve" )
        data = shape._data
        self._xmlWriteInt( xmlCurrent, "shapeId", shape._shapeID)
        self._xmlWriteString( xmlCurrent, "name", data["name"])
        self._xmlWriteString( xmlCurrent, "degree", data["degree"])
        self._xmlWriteString( xmlCurrent, "form", data["form"])
        for point in data["points"]:
            xmlItem = xml_ET.SubElement( xmlCurrent,  "cv" )
            self._xmlWriteString( xmlItem, "c", point )

    def _xmlWriteShape_Mesh(self, xmlParent, shape):
        """ Write all Shape Mesh data to the .i3d file """

        xmlCurrent  = xml_ET.SubElement( xmlParent, "IndexedTriangleSet" )
        data = shape._data
        self._xmlWriteString( xmlCurrent, "name", data["name"]  )
        self._xmlWriteInt( xmlCurrent, "shapeId", shape._shapeID )
        if "meshUsage" in data:
            self._xmlWriteInt( xmlCurrent, "meshUsage", data["meshUsage"]  )
        if "bvCenter" in data:
            self._xmlWriteString( xmlCurrent, "bvCenter", data["bvCenter"]  )
        if "bvRadius" in data:
            self._xmlWriteString( xmlCurrent, "bvRadius", data["bvRadius"]  )
        if "vertexCompressionRange" in data:
            self._xmlWriteString( xmlCurrent, "vertexCompressionRange", data["vertexCompressionRange"]  )
        if "isOptimized" in data:
            self._xmlWriteString( xmlCurrent, "isOptimized", data["isOptimized"]  )
        vertices = data["Vertices"]
        triangles = data["Triangles"]
        subsets = data["Subsets"]
        # -------------------------------------------------------------
        xmlVertices  = xml_ET.SubElement( xmlCurrent, "Vertices" )
        self._xmlWriteString( xmlVertices, "count", vertices["count"]  )
        if ( "normal" in vertices and UIGetAttrBool("i3D_exportNormals")):
            self._xmlWriteString( xmlVertices, "normal",  vertices["normal"] )
            self._xmlWriteString( xmlVertices, "tangent", "true" )    #wrong place
        if ( "uv0" in vertices and UIGetAttrBool("i3D_exportTexCoords")):
            self._xmlWriteString( xmlVertices, "uv0",   vertices["uv0"] )
        if ( "uv1" in vertices and UIGetAttrBool("i3D_exportTexCoords")):
            self._xmlWriteString( xmlVertices, "uv1",   vertices["uv1"] )
        if ( "uv2" in vertices and UIGetAttrBool("i3D_exportTexCoords")):
            self._xmlWriteString( xmlVertices, "uv2",   vertices["uv2"] )
        if ( "uv3" in vertices and UIGetAttrBool("i3D_exportTexCoords")):
            self._xmlWriteString( xmlVertices, "uv3",   vertices["uv3"] )
        if ( "color" in vertices and UIGetAttrBool("i3D_exportColors")):
            self._xmlWriteString( xmlVertices, "color", vertices["color"] )
        if ( "blendweights" in vertices and UIGetAttrBool("i3D_exportSkinWeigths")):
            self._xmlWriteString( xmlVertices, "blendweights", vertices["blendweights"] )
        if ( "singleblendweights" in vertices and UIGetAttrBool("i3D_exportMergeGroups")):
            self._xmlWriteString( xmlVertices, "singleblendweights", vertices["singleblendweights"] )
        if ("generic" in vertices):
            self._xmlWriteString( xmlVertices, "generic", vertices["generic"])

        normalSet = "normal" in vertices and  UIGetAttrBool("i3D_exportNormals")
        colorSet = "color"  in vertices and UIGetAttrBool("i3D_exportColors")
        uv0Set = "uv0" in vertices and UIGetAttrBool("i3D_exportTexCoords")
        uv1Set = "uv1" in vertices and UIGetAttrBool("i3D_exportTexCoords")
        uv2Set = "uv2" in vertices and UIGetAttrBool("i3D_exportTexCoords")
        uv3Set = "uv3" in vertices and UIGetAttrBool("i3D_exportTexCoords")
        blendWSet = "blendweights" in vertices and UIGetAttrBool("i3D_exportSkinWeigths")
        singleBlendWSet = "singleblendweights" in vertices and UIGetAttrBool("i3D_exportMergeGroups")
        genericSet = "generic" in vertices
        for m_vert in vertices["data"]:
            xmlV  = xml_ET.SubElement( xmlVertices, "v" )
            self._xmlWriteString( xmlV, "p", m_vert["p"]  )
            if (normalSet):
                self._xmlWriteString( xmlV, "n",  m_vert["n"] )
            if (colorSet):
                # for merge children or merge group the key "c" might not be set
                if "c" in m_vert:
                    self._xmlWriteString( xmlV, "c",  m_vert["c"] )
                else:
                    self._xmlWriteString( xmlV, "c",  "1 1 1 1" )
            if (uv0Set):
                self._xmlWriteString( xmlV, "t0", m_vert["t0"] )
            if (uv1Set):
                self._xmlWriteString( xmlV, "t1", m_vert["t1"] )
            if (uv2Set):
                self._xmlWriteString( xmlV, "t2", m_vert["t2"] )
            if (uv3Set):
                self._xmlWriteString( xmlV, "t3", m_vert["t3"] )
            if (blendWSet):
                self._xmlWriteString( xmlV, "bw", m_vert['bw'] )
                self._xmlWriteString( xmlV, "bi", m_vert['bi'] )
            if (singleBlendWSet):
                self._xmlWriteString( xmlV, "bi", m_vert['bi'] )
            if (genericSet):
                self._xmlWriteString( xmlV, "g", m_vert["g"])
        # -------------------------------------------------------------
        xmlTriangles = xml_ET.SubElement( xmlCurrent, "Triangles" )
        self._xmlWriteString( xmlTriangles, "count", triangles["count"]  )
        for m_tri in triangles["data"]:
            xmlT = xml_ET.SubElement( xmlTriangles, "t" )
            self._xmlWriteString( xmlT, "vi", m_tri["vi"]  )
        # -------------------------------------------------------------
        xmlSubsets = xml_ET.SubElement( xmlCurrent, "Subsets" )
        self._xmlWriteString( xmlSubsets, "count", subsets["count"]  )
        for m_subs in subsets["data"]:
            xmlS = xml_ET.SubElement( xmlSubsets, "Subset" )
            self._xmlWriteString( xmlS, "firstVertex", m_subs["firstVertex"]  )
            self._xmlWriteString( xmlS, "numVertices", m_subs["numVertices"]  )
            self._xmlWriteString( xmlS, "firstIndex",  m_subs["firstIndex"]  )
            self._xmlWriteString( xmlS, "numIndices",  m_subs["numIndices"]  )
            if ( "uv0"    in vertices and UIGetAttrBool("i3D_exportTexCoords") and "uvDensity0" in m_subs):
                self._xmlWriteFloat( xmlS, "uvDensity0",  m_subs["uvDensity0"]  )
            if ( "uv1"    in vertices and UIGetAttrBool("i3D_exportTexCoords") and "uvDensity1" in m_subs):
                self._xmlWriteFloat( xmlS, "uvDensity1",  m_subs["uvDensity1"]  )
            if ( "uv2"    in vertices and UIGetAttrBool("i3D_exportTexCoords") and "uvDensity2" in m_subs):
                self._xmlWriteFloat( xmlS, "uvDensity2",  m_subs["uvDensity2"]  )
            if ( "uv3"    in vertices and UIGetAttrBool("i3D_exportTexCoords") and "uvDensity3" in m_subs):
                self._xmlWriteFloat( xmlS, "uvDensity3",  m_subs["uvDensity3"]  )
            if ("materialSlotName" in m_subs and m_subs["materialSlotName"] != ""):
                self._xmlWriteString(xmlS, "materialSlotName", m_subs["materialSlotName"])

    def _xmlWriteAttr(self, xmlCurrent, attrStr, data, valStr ):
        """ Write specific attributes to the given xml layer """
        if valStr in data:
            value = data[valStr]
        else:
            value = SETTINGS_ATTRIBUTES[valStr]['defaultValue']

        if 'i3dDefaultValue' in SETTINGS_ATTRIBUTES[valStr]:
            i3dDefaultValue = SETTINGS_ATTRIBUTES[valStr]['i3dDefaultValue']
        else:
            i3dDefaultValue = SETTINGS_ATTRIBUTES[valStr]['defaultValue']

        
        attrType = SETTINGS_ATTRIBUTES[valStr]['type']
        if TYPE_INT == attrType and isinstance(value, str):
            value = int(value, 0)
        elif TYPE_STRING == attrType and isinstance(value, int):
            value = "{:d}".format(value)

        if value != i3dDefaultValue:
            if TYPE_BOOL == attrType:
                self._xmlWriteBool(xmlCurrent,attrStr,value)
            elif TYPE_INT == attrType:
                self._xmlWriteInt(xmlCurrent,attrStr,value)
            elif TYPE_FLOAT == attrType:
                self._xmlWriteFloat(xmlCurrent,attrStr,value)
            elif TYPE_STRING == attrType:
                self._xmlWriteString(xmlCurrent,attrStr,value)
            elif TYPE_STRING_UINT == attrType:
                try:
                    asInt = int(value, 0)
                    if asInt < 0:
                        raise ValueError('Unexpected signed number.')
                    self._xmlWriteString(xmlCurrent, attrStr, hex(asInt))
                except Exception as e:
                    dcc.UIShowError('Attribute ' + valStr + ' with value "' + value + '" is not an unsigned int, details: ' + repr(e))
            return True
        return False

    @staticmethod
    def _xmlWriteBool( xmlCurrent, attrStr, val ):
        """ Write boolean attribute to given xml layer """

        if ( val ):
            xmlCurrent.set( attrStr , "true" )
        else:
            xmlCurrent.set( attrStr , "false" )

    @staticmethod
    def _xmlWriteInt( xmlCurrent, attrStr, val ):
        """ Write integer attribute to given xml layer """

        xmlCurrent.set( attrStr, "{:d}".format(val) )

    @staticmethod
    def _xmlWriteFloat( xmlCurrent, attrStr, val ):
        """ Write float attribute to given xml layer """

        xmlCurrent.set( attrStr, "{:g}".format(val) )

    @staticmethod
    def _xmlWriteString( xmlCurrent, attrStr, val ):
        """ Write string attribute to given xml layer """

        xmlCurrent.set( attrStr, val )

class I3DIOexport( object ):
    """ I3DIOexport is the top level structure for the export pipeline """

    __instance = None
    def __new__(cls):
        if cls.__instance == None:
            cls.__instance = object.__new__(cls)
        return cls.__instance

    def __init__( self ):
        self._fileID          = 0
        self._nodeID          = 0
        self._shapeID         = 0
        self._dynamicsID      = 0
        self._sceneGraph      = I3DSceneGraph()
        self._exportSelection = False

    def export( self, exportSelection = False ):
        """
        Executes the different export functions

        :param exportSelection: This boolean specifies which dataset is exported
        """

        self._exportSelection = exportSelection
        try:
            self._generateSceneGraph()
            err = self._xmlBuild()
            ddsExporter.exportObjectDataTexture()
            if UIGetAttrBool("i3D_updateXMLOnExport") and not exportSelection:
                self._updateXML()
            return err
        except Exception as exception:
            # Show full traceback to make export failures actionable.
            print(traceback.format_exc())
            dcc.UIShowError(traceback.format_exc())
            dcc.UIShowWarning("Export failed")

    def exportDDS(self):
        try:
            ddsExporter.exportObjectDataTexture()
        except Exception as exception:
            dcc.UIShowError(exception)
            dcc.UIShowWarning("DDS Export failed")

    def updateXML(self):
        """ Executes the differen steps to update the configuration XML """

        self._exportSelection = False
        try:
            self._generateSceneGraph(onlyScenegraphNodes=True)
            err = self._updateXML()
            return err
        except Exception as exception:
            dcc.UIShowError(exception)
            dcc.UIShowWarning("XML Update failed")



    def _generateSceneGraph(self, onlyScenegraphNodes=False):
        """ Sequential build up of the I3DSceneGraph """

        self._objectsToExportList = dcc.getAllNodesToExport()
        if (self._exportSelection):
            self._objectsToExportList = dcc.getSelectedNodesToExport()
        # add nodes and their children to the sceneGraph
        for node in self._objectsToExportList:
            if (dcc.isParentedToWorld(node)):
                self._generateSceneGraphItem(node,"ROOT")

        if not onlyScenegraphNodes:
            self._sceneGraph.mapSkinning()
            self._sceneGraph.generateInstances()
            # self._sceneGraph.display()
            self._sceneGraph.generateShapes()
            self._sceneGraph.generateMaterials()
            self._sceneGraph.generateFiles()
            if UIGetAttrBool("i3D_exportAnimation"):
                self._sceneGraph.generateAnimation()

    def _generateSceneGraphItem(self,node,parent):
        """
        Generates I3DSceneNode for the node and all it's children and appends them in I3DSceneGraph._nodes

        :param self: instance of I3DIOexport
        :param node: node name which should be added to the I3DSceneGraph
        :param parent: name of the parent of node
        """

        if(node.lower().endswith("_ignore")):     #check for ignore suffix
            dcc.UIAddMessage("Node {} (and descendants) was not exported, name ends with _ignore.".format(node))
            return
        self._sceneGraph.addNode(node,parent)
        if(node.lower().find("decal") != -1 and I3DGetAttributeValue(node, "i3D_castsShadows")):
            dcc.UIShowWarning("Node {} is named 'decal' but has casts shadows enabled.".format(node))
        if(dcc.hasBone(node)):
            self._generateSceneGraphBoneItem(node)

        for child in dcc.getChildObjects(node):
            if (child in self._objectsToExportList):
                self._generateSceneGraphItem(child,node)

    def _generateSceneGraphBoneItem(self,armatureStr):
        """
        Generates I3DSceneNodes for the bones in the armature and appends them in I3DSceneGraph._nodes

        :param armatureStr: Name of the armature, of which all bones are added to the I3DSceneGraph
        """

        for boneName in dcc.getBoneNameList(armatureStr):
            if (dcc.boneHasParentBone(boneName,armatureStr)):
                parentBoneName = dcc.getBoneParent(boneName,armatureStr)
                self._sceneGraph.addBone(boneName,parentBoneName,armatureStr)
            else:
                # Get the active pose mode object
                pose_mode_obj = bpy.data.objects[armatureStr]

                # Get the active pose bone
                pose_bone = pose_mode_obj.pose.bones[boneName]

                # Check if the pose bone has a "Child Of" constraint
                child_of_constraint = None
                for constraint in pose_bone.constraints:
                    if constraint.type == 'CHILD_OF':
                        child_of_constraint = constraint
                        break

                # Retrieve the target name from the "Child Of" constraint
                target_name = armatureStr
                if child_of_constraint:
                    target_name = child_of_constraint.target.name

                self._sceneGraph.addBone(boneName,target_name,armatureStr)

            # see dccBlender.py
            # if(not dcc.boneHasChildBone(boneName,armatureStr)):
            #     self._sceneGraph.addBone(boneName + "_tail",boneName, armatureStr)  #generate Tail

    def _xmlWriteFiles(self):
        """ Top level function to write files to the i3d file """

        self._sceneGraph.xmlWriteFiles(self._xml_files)

    def _xmlWriteMaterials(self):
        """ Top level function to write materials to the i3d file """

        self._sceneGraph.xmlWriteMaterials(self._xml_materials)

    def _xmlWriteShapes(self):
        """ Top level function to write shapes to the i3d file """

        self._sceneGraph.xmlWriteShapes(self._xml_shapes)

    def _xmlWriteDynamics(self):
        """ no implementation """

        pass

    def _xmlWriteAnimation(self):
        """ Top level function to write animations to the i3d file """

        self._sceneGraph.xmlWriteAnimation(self._xml_animation)

    def _xmlWriteUserAttributes(self):
        """ Top level function to write custom attributes to the i3d file """

        self._sceneGraph.xmlWriteUserAttributes(self._xml_userAttributes)

    def _xmlWriteScene(self):
        """ Top level function to write scene to the i3d file """

        self._sceneGraph.xmlWriteScene(self._xml_scene)

    def _xmlBuild( self ):
        """ Top level XML builder function """

        # i3D
        name = "untitled"
        if (dcc.isFileSaved()):
            name = dcc.getFileBasename()
        if (g_usingLXML):
            root_attributes = {
                'version': '1.6',
            }
            nsmap = {
                'xsi': 'http://www.w3.org/2001/XMLSchema-instance'
            }
            attr_qname = xml_ET.QName("http://www.w3.org/2001/XMLSchema-instance", 'noNamespaceSchemaLocation')
            self._xml_i3d = xml_ET.Element('i3D', attrib={'name': name, **root_attributes,
                                            attr_qname: 'http://i3d.giants.ch/schema/i3d-1.6.xsd'}, nsmap=nsmap)
        else:
            self._xml_i3d = xml_ET.Element( "i3D" )
            self._xml_i3d.set( "name", name )
            self._xml_i3d.set( "version", "1.6" )
            self._xml_i3d.set( "xsi:noNamespaceSchemaLocation", "http://i3d.giants.ch/schema/i3d-1.6.xsd" ) #https://gdn.giants-software.com/documentation_i3d.php
            self._xml_i3d.set( "xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance" )
        # Asset
        self._xml_asset = xml_ET.SubElement( self._xml_i3d,   "Asset" )
        self._xml_software = xml_ET.SubElement( self._xml_asset, "Export" )
        self._xml_software.set( "program", DCC_PLATFORM )
        self._xml_software.set( "version", "{0}".format( dcc.appVersion() ) )
        # Files
        if len(self._sceneGraph._files) > 0:
            self._xml_files = xml_ET.SubElement( self._xml_i3d, "Files" )
            self._xmlWriteFiles()
        # Materials
        self._sceneGraph.updateMaterials()
        if len(self._sceneGraph._materials) > 0:
            self._xml_materials = xml_ET.SubElement( self._xml_i3d, "Materials" )
            self._xmlWriteMaterials()
        # Shapes
        if len(self._sceneGraph._shapes) > 0:
            self._xml_shapes = xml_ET.SubElement( self._xml_i3d, "Shapes" )
            self._xmlWriteShapes()
        # Dynamics
        # if ( UIGetAttrBool("i3D_exportParticleSystems") ):
            # self._xml_dynamics   = xml_ET.SubElement( self._xml_i3d, "Dynamics" )
            # self._xmlWriteDynamics()
        # Scene
        if len(self._sceneGraph._nodes) > 0:
            self._xml_scene = xml_ET.SubElement( self._xml_i3d, "Scene" )
            self._xmlWriteScene()
        # Animation
        if ( UIGetAttrBool("i3D_exportAnimation") and len(self._sceneGraph._animationSet) > 0):
            self._xml_animation = xml_ET.SubElement( self._xml_i3d, "Animation" )
            self._xmlWriteAnimation()
        # UserAttributes
        if ( UIGetAttrBool("i3D_exportUserAttributes")and len([treeID for treeID in self._sceneGraph.traverse(m_node="DEPTH") if len( dcc.getNodeUserAttributes(treeID)) > 0]) > 0):
            self._xml_userAttributes = xml_ET.SubElement( self._xml_i3d, "UserAttributes" )
            self._xmlWriteUserAttributes()
        self._indent( self._xml_i3d ) #prettyprint
        self._xml_tree = xml_ET.ElementTree( self._xml_i3d )
        # Export Path
        if ( UIGetAttrBool('i3D_exportUseSoftwareFileName') ):
            if ( dcc.isFileSaved() ):
                filepath = dcc.getFilePath()  #something *.i3d
            else:
                #should not occure
                dcc.UIShowWarning("no save location specified")
                filepath = "c:/tmp/untitled.i3d"
        else:
            filepath = dcc.getAbsPath( UIGetAttrString("i3D_exportFileLocation") )
            filepath = "{0}.i3d".format(os.path.splitext(filepath)[0])
        try:
            fwrite = open(filepath,'w')
            fwrite.close()
        except IOError:
            dcc.UIShowError('Invalid filepath: {0}'.format(filepath))
            return 1
        try:
            self._xml_tree.write( filepath, xml_declaration = True, encoding = "iso-8859-1", method = "xml" )
            dcc.UIAddMessage('Exported to {0}'.format(filepath))
        except Exception as m_exception:
            dcc.UIShowError(m_exception)
            return 1

        if UIGetAttrBool("i3D_binaryFiles"):
            dcc.UIAddMessage('BUILD BINARY')
            gamepath = ""
            if ("i3D_gameLocationDisplay" in bpy.context.scene.I3D_UIexportSettings):
                gamepath = bpy.context.scene.I3D_UIexportSettings.i3D_gameLocationDisplay
            msgList = i3d_binaryUtil.create_binary_from_exe(filepath, gamepath)
            for msg in msgList:
                dcc.UIAddMessage(msg)
        return 0

    def _updateXML(self):
        """ Top level configuration XML update function"""

        if UIGetAttrString("i3D_updateXMLFilePath") == '':
            dcc.UIShowWarning('No config xml file set!')
            return 1
        for xmlFile in [p for p in UIGetAttrString("i3D_updateXMLFilePath").split(";") if p != ""]:
            xmlFile = os.path.abspath(xmlFile)
            if xmlFile == '':
                dcc.UIShowWarning('No config xml file set!')
                continue
            if not os.path.isfile(xmlFile):
                dcc.UIShowWarning('Could not find xml file! (%s)' % xmlFile)
                continue
            if not xmlFile.endswith(".xml"):
                dcc.UIShowWarning("Selected File is not xml format: {}".format(xmlFile.split("\\")[-1]))
                continue
            file = open(xmlFile, 'r')
            if file is None:
                dcc.UIShowWarning('Could not find xml file! (%s)' % xmlFile)
                continue
            lines = file.readlines()
            file.close()
            newLines = self._removeI3dMapping(lines)
            endRootTag = 0
            found = False
            for line in newLines:
                endRootTag = endRootTag + 1
                if len(re.findall('</vehicle>', line)) > 0 or len(re.findall('</placeable>', line)) > 0:
                    found = True
                    break
            if found:
                i3dMappings = []
                self._addI3dMapping(i3dMappings)
                if len(i3dMappings) > 0:
                    i3dMappings.insert(0, '    <i3dMappings>\n')
                    i3dMappings.append('    </i3dMappings>\n')
                    for i in range(len(i3dMappings)-1, -1, -1):
                        mapping = i3dMappings[i]
                        newLines.insert(endRootTag-1, mapping)
                    file = open(xmlFile, 'w')
                    for line in newLines:
                        file.write(line)
                    file.close()
                dcc.UIAddMessage('')
                dcc.UIAddMessage('Updated xml config file! (%s)' % xmlFile)
            else:
                dcc.UIShowWarning('Could not find end tag "</vehicle>". Ignoring i3dMappings!')
        return 0

    def _removeI3dMapping(self, lines):
        """ Remove all lines relevant to the i3d mapping """

        cleanedLines = []
        for line in lines:
            found = re.findall('i3dMapping', line)
            if len(found) == 0:
                cleanedLines.append(line)
        return cleanedLines

    def _addI3dMapping(self, mappingList, localRoot = "ROOT"):
        """
        Recursive function to construct the i3d mapping for the configuration xml

        :param self: instance of I3DIOexport
        :param mappingList: list final return structure of all mappings
        :param localRoot: current level of recursion, starts at the ROOT and propagetes down
        """

        for childNodeStr in self._sceneGraph._nodes[localRoot]._children:
            obj = bpy.data.objects.get(childNodeStr)

            # If the childNodeStr corresponds to a real object
            if obj:
                if obj.type == 'ARMATURE':
                    for bone in obj.pose.bones:
                        self._processNode(obj.name, mappingList, bone.name)

                # If not an armature, process as usual
                self._processNode(childNodeStr, mappingList)

            # Recurse deeper if there are more children
            childNode = self._sceneGraph._nodes[childNodeStr]
            if len(childNode._children) > 0:
                self._addI3dMapping(mappingList, localRoot=childNodeStr)

    def _processNode(self, nodeStr, mappingList, bone_str=""):
        """ Processes individual nodes (either objects or bones) """
        xmlIdentifier = dcc.getXMLConfigID(nodeStr, bone_str).strip()
        indexPath = dcc.getNodeIndex(nodeStr, bone_str)

        if dcc.getXMLConfigBool(nodeStr, bone_str):
            mappingList.append('        <i3dMapping id="' + xmlIdentifier + '" node="' + indexPath + '" />\n')

    @staticmethod
    def _indent( elem, level = 0 ):
        """ source http://effbot.org/zone/element-lib.htm#prettyprint """

        i = "\n" + level*"  "
        if len( elem ):
            if not elem.text or not elem.text.strip():
                elem.text = i + "  "
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
            for elem in elem:
                I3DIOexport._indent( elem, level + 1 )
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i