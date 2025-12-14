import os
import bpy
import math

try:
    from lxml import etree as xml_ET
except:
    import xml.etree.cElementTree as xml_ET

g_shaderDataCache = {}

def extractXMLShaderData(xmlFile):
    """
    Extracts the data from the specified file

    :returns: a dictionary with keys: parameters, textures and variations according
    to the data contained in the file
    :returns: None if file is not valid
    """
    if xmlFile[0] == "$":
        xmlFile = bpy.context.scene.I3D_UIexportSettings.i3D_gameLocationDisplay + xmlFile[1:]

    if xmlFile in g_shaderDataCache:
        return g_shaderDataCache[xmlFile]

    if not os.path.isfile(xmlFile):
        print('Could not find xml file! (%s)' % xmlFile)
        return None
    if not xmlFile.endswith(".xml"):
        print("Selected File is not xml format: {}".format(xmlFile.split("\\")[-1]))
        return None

    file = open(xmlFile, 'rb')
    if file is None:
        print('Could not find xml file! (%s)' % xmlFile)
        return None
    xmlTree = xml_ET.parse(file)
    file.close()

    variations, variations_groups = getVariationsFromShaderFile(xmlTree.getroot())
    parameterTemplates = getParameterTemplatesFromShaderFile(xmlTree.getroot())
    textures, textures_group = getTextureFromShaderFile(xmlTree.getroot(), parameterTemplates)
    parameters, parameters_group = getParametersFromShaderFile(xmlTree.getroot(), parameterTemplates)
    shaderData = {"parameters" : parameters, "textures" : textures, "variations" : variations, "parameters_group" : parameters_group, "textures_group" : textures_group, "variations_groups" : variations_groups, "parameterTemplates" : parameterTemplates}

    g_shaderDataCache[xmlFile] = shaderData

    return shaderData

def getParametersFromShaderFile(xmlRoot, parameterTemplatesDict):
    """Extracts the name and default value from Parameters"""

    parameterDict = {}
    parameterGroupDict = {}
    currentLine = 0

    parameters = xmlRoot.find("Parameters")
    if parameters:
        for parameter in parameters.findall("Parameter"):
            name = parameter.get("name")
            value = parameter.get("defaultValue")
            val_type = parameter.get("type")
            group = parameter.get("group")
            template = parameter.get("template")

            if template and template not in parameterTemplatesDict:
                #TODO(jdellsperger): Bleet about malformed xml?
                parameterTemplatesDict[template] = {'filename': '', 'parameters': {}}

            # if arraySize set the following lines are <Default index="0">value</Default>
            arraySize = parameter.get("arraySize")
            if arraySize and name:
                for defaultElement in parameter.findall("Default"):
                    indexDft = defaultElement.get("index")
                    valueDft = defaultElement.text
                    if indexDft and valueDft:
                        if template:
                            parameterTemplatesDict[template]["parameters"][name + indexDft] = valueDft
                        else:
                            parameterDict[name + indexDft] = valueDft
                        if group is not None:
                            parameterGroupDict[name + indexDft] = group
            if name and value:
                if template:
                    parameterTemplatesDict[template]["parameters"][name] = value
                else:
                    parameterDict[name] = value
                if group is not None:
                    parameterGroupDict[name] = group
            elif name and val_type:
                #defined type but no default values specified
                val_type_str = val_type
                val = None
                if val_type_str == 'float4':
                    val = "1 1 1 1"
                elif val_type_str == 'float3':
                    val = "1 1 1"
                elif val_type_str == 'float':
                    val = "1"
                if val:
                    if template:
                        parameterTemplatesDict[template]["parameters"][name] = val
                    else:
                        parameterDict[name] = val
                    if group is not None:
                        parameterGroupDict[name] = group

        currentLine = currentLine + 1
    return parameterDict, parameterGroupDict

def getTextureFromShaderFile(xmlRoot, parameterTemplatesDict):
    """Extracts the name and default file name from Texture"""

    textureDict = {}
    textureGroupDict = {}
    textures = xmlRoot.find("Textures")
    if textures:
        for texture in textures.findall("Texture"):
            name = texture.get("name")
            value = texture.get("defaultFilename")
            group = texture.get("group")
            template = texture.get("template")

            if template and template not in parameterTemplatesDict:
                #TODO(jdellsperger): Bleet about malformed xml?
                parameterTemplatesDict[template] = {'filename': '', 'textures': {}}

            if not value:
                value = ""

            if name:
                if template:
                    parameterTemplatesDict[template]["textures"][name] = value
                else:
                    textureDict[name] = value
                textureGroupDict[name] = group

    return textureDict, textureGroupDict

def getVariationsFromShaderFile(xmlRoot):
    """Extracts the name from Variation"""

    variationDict = {}
    variationGroupsDict = {}

    variations = xmlRoot.find("Variations")
    if variations:
        for variation in variations.findall("Variation"):
            groups = variation.get("groups")
            name = variation.get("name")
            variationDict[name] = name
            variationGroupsDict[name] = groups

    return variationDict, variationGroupsDict

def getParameterTemplatesFromShaderFile(xmlRoot):
    parameterTemplatesDict = {}
    parameterTemplates = xmlRoot.find("ParameterTemplates")
    if parameterTemplates:
        for parameterTemplate in parameterTemplates.findall("ParameterTemplate"):
            parameterTemplateId = parameterTemplate.get("id")
            parameterTemplateFilename = parameterTemplate.get("filename")

            parameterTemplatesDict[parameterTemplateId] = {'filename': parameterTemplateFilename, 'parameters': {}, 'textures': {}, 'subtemplates': {}}

            if parameterTemplateFilename is not None:
                tree = None
                try:
                    templatesXmlFilename = parameterTemplateFilename.replace("$", bpy.context.scene.I3D_UIexportSettings.i3D_gameLocationDisplay)
                    tree = xml_ET.parse(templatesXmlFilename)
                except xml_ET.ParseError as err:
                    print("Failed to load parameter templates from '%s': %s" % (templatesXmlFilename, err))
                else:
                    templatesFileRoot = tree.getroot()
                    parameterTemplatesDict[parameterTemplateId]["name"] = templatesFileRoot.get("name")
                    parameterTemplatesDict[parameterTemplateId]["rootSubTemplateId"] = templatesFileRoot.get("id")

                # Parse the templates xml file.
                while tree is not None:
                    templatesFileRoot = tree.getroot()
                    parentTemplateFilename = templatesFileRoot.get("parentTemplateFilename")
                    parentTree = None
                    parentId = None
                    if parentTemplateFilename is not None:
                        try:
                            templatesXmlFilename = parentTemplateFilename.replace("$", bpy.context.scene.I3D_UIexportSettings.i3D_gameLocationDisplay)
                            parentTree = xml_ET.parse(templatesXmlFilename)
                        except xml_ET.ParseError as err:
                            print("Failed to load parameter templates from '%s': %s" % (templatesXmlFilename, err))
                        else:
                            parentTemplatesFileRoot = parentTree.getroot()
                            parentId = parentTemplatesFileRoot.get("id")
                    defaultParentTemplate = templatesFileRoot.get("parentTemplateDefault")
                    subTemplateId = templatesFileRoot.get("id")
                    parameterTemplatesDict[parameterTemplateId]["subtemplates"][subTemplateId] = {'name': templatesFileRoot.get("name"), 'parentId': parentId, 'defaultParentTemplate': defaultParentTemplate, 'templates': {}}
                    for template in templatesFileRoot.findall("template"):
                        name = template.get("name")
                        parameterTemplatesDict[parameterTemplateId]["subtemplates"][subTemplateId]['templates'][name] = {}
                        attributes = template.attrib
                        del attributes["name"]
                        for attr in attributes:
                            parameterTemplatesDict[parameterTemplateId]["subtemplates"][subTemplateId]['templates'][name][attr] = template.get(attr)
                    tree = parentTree

            #print("Parameter template {}, {}".format(parameterTemplateId, parameterTemplateFilename))
    return parameterTemplatesDict

# Map from FS22 to FS25 custom shader variation names
FS22customShaderVariation = {
                     'secondUV_colorMask':'vmaskUV2',
                               'secondUV':'vmaskUV2',
                                  'Decal':'vmaskUV2',
                        'Decal_colorMask':'vmaskUV2',
                    'Decal_normalThirdUV':'vmaskUV2_normalUV3',
          'Decal_normalThirdUV_colorMask':'vmaskUV2_normalUV3',
                               'uvScroll':'uvTransform',
                     'uvScroll_colorMask':'uvTransform',
                               'uvRotate':'uvTransform',
                     'uvRotate_colorMask':'uvTransform',
                                'uvScale':'uvTransform',
                      'uvScale_colorMask':'uvTransform',
                         'Decal_uvScroll':'uvTransform_vmaskUV2',
                'tirePressureDeformation':'tirePressureDeformation',
       'tirePressureDeformation_secondUV':'tirePressureDeformation_vmaskUV2',
                       'motionPathRubber':'motionPathRubber',
    'motionPathRubber_secondUV_colorMask':'motionPathRubber_vmaskUV2',
                             'motionPath':'motionPath',
          'motionPath_secondUV_colorMask':'motionPath_vmaskUV2',
                    'vtxRotate_colorMask':'vtxRotate',
                              'vtxRotate':'vtxRotate',
                             'meshScroll':'meshScroll',
                   'meshScroll_colorMask':'meshScroll',
                                    'rim':'rim',
                          'rim_colorMask':'rim',
          'rim_numberOfStatics_colorMask':'rim_numberOfStatics',
                      'rimDual_colorMask':'rimDual_numberOfStatics',
                      'hubDual_colorMask':'hubDual',
                               'windBend':'windBend',
                     'windBend_colorMask':'windBend',
            'windBend_colorMask_vtxColor':'windBend_vtxColor',
                'windBend_vtxColor_Decal':'windBend_vtxColor_vmaskUV2',
      'windBend_vtxColor_Decal_colorMask':'windBend_vtxColor_vmaskUV2',
                      'shaking_colorMask':'shaking',
                'shaking_colorMask_Decal':'shaking_vmaskUV2',
                     'jiggling_colorMask':'jiggling',
               'cableTrayChain_colorMask':'cableTrayChain',
                        'localCatmullRom':'localCatmullRom_uvTransform',
              'localCatmullRom_colorMask':'localCatmullRom_uvTransform',
      'localCatmullRom_colorMask_uvScale':'localCatmullRom_uvTransform',
                    'reflector_colorMask':'reflector',
                    'backLight_colorMask':'backLight',
                            }

# Map  from FS22 to FS25 custom shader parameter names
FS22customParameter = {
    'customParameter_morphPosition'        :'customParameter_morphPos' ,
    'customParameter_scrollPosition'       :'customParameter_scrollPos',
    'customParameter_blinkOffset'          :'customParameter_blinkMulti',
    'customParameter_offsetUV'             :'customParameter_offsetUV' ,
    'customParameter_uvCenterSize'         :'customParameter_uvCenterSize' ,
    'customParameter_uvScale'              :'customParameter_uvScale' ,
    'customParameter_lengthAndRadius'      :'customParameter_lengthAndRadius',
    'customParameter_widthAndDiam'         :'customParameter_widthAndDiam',
    'customParameter_connectorPos'         :'customParameter_connectorPos',
    'customParameter_numberOfStatics'      :'customParameter_numberOfStatics',
    'customParameter_connectorPosAndScale' :'customParameter_connectorPosAndScale',
    'customParameter_lengthAndDiameter'    :'customParameter_lengthAndDiameter',
    'customParameter_backLightScale'       :'customParameter_backLightScale',
    'customParameter_amplFreq'             :'customParameter_amplFreq',
    'customParameter_shaking'              :'customParameter_shaking',
    'customParameter_rotationAngle'        :'customParameter_rotationAngle',
    'customParameter_directionBend'        :'customParameter_directionBend',
    'customParameter_controlPointAndLength':'customParameter_controlPointAndLength',
                      }

FS22customTexture = { 'customTexture_mTrackArray': 'customTexture_trackArray' }

FS22ColoredMaterialTemplates = [ 'metalPaintedGray','plasticPaintedBlack','chrome','copperScratched','metalGalvanized','rubberBlack','metalPaintedOldGray','fabric1Bluish',
                    'silverScratched','silverBumpy','fabric2Gray','fabric3Gray','leather1Brown','leather2Brown','wood1Cedar','dirt',
                    'metalPaintedBlack','plasticPaintedGray','silverRough','brassScratched','reflectorWhite','reflectorRed','reflectorOrange','reflectorOrangeDaylight',
                    'plasticGearShiftGrayDark','leather3GrayDark','perforatedSynthetic1Black','glassClear01','glassSquare01','glassLine01','palladiumScratched','bronzeScratched',
                    'metalPaintedGraphiteBlack','halfMetalNoise1Black','plasticPaintedShinyGray','goldScratched','metalPaintedRoughGray','perforatedSynthetic2Black','fellGray','steelTreadPlate',
                    'halfMetalNoise2','fabric4Beige','wood2Oak','silverScratchedShiny','reflectorYellow','silverCircularBrushed','fabric5Dark','glassClear02',
                    'glassClear03','fabric6Bluish']
FS22MaterialTemplates  = ['metalPainted','plasticPainted','chrome','silverScratched','metalGalvanized','rubber','metalPaintedOld','fabric1',
                   'silverScratched','silverBumpy','fabric2','fabric3','leather1','leather2','wood1','dirt',
                   'metalPainted','plasticPainted','silverRough','silverScratched','reflectorWhite','reflectorWhite','reflectorWhite','reflectorOrangeDaylight',
                   'plasticGearShift','leather3','perforatedSynthetic1','glassClear01','glassSquare01','glassLine01','silverScratched','silverScratched',
                   'metalPaintedGraphite','halfMetalNoise1','plasticPaintedShinyGray','silverScratched','metalPaintedRough','perforatedSynthetic2','fell','steelTreadPlate',
                   'halfMetalNoise2','fabric4','wood2','silverScratchedShiny','reflectorWhite','silverCircularBrushed','fabric5','glassClear02',
                   'glassClear03','fabric6']

brandColorTemplateParameters = [
    'customParameter_colorScale',
    'customParameter_smoothnessScale',
    'customParameter_clearCoatIntensity',
    'customParameter_clearCoatSmoothness',
    'customParameter_porosity',

    'customTexture_detailSpecular',
    'customTexture_detailNormal',
    'customTexture_detailDiffuse',
]

# Map  from FS22 to FS25 custom shader texture names
FS22customTexture = { 'customTexture_mTrackArray': 'customTexture_trackArray' }

def extractColorScaleToMaterialTemplateMapFromXML(xmlPath):
    templates = {}

    file = open(xmlPath, 'rb')
    if file is None:
        return templates

    xmlTree = xml_ET.parse(file)
    file.close()

    xmlRoot = xmlTree.getroot()
    xmlTemplates = xmlRoot.findall("template")
    templates = {xmlTemplate.attrib["colorScale"]: {"name": xmlTemplate.attrib["name"], "parentTemplate": xmlTemplate.attrib["parentTemplate"] if "parentTemplate" in xmlTemplate.attrib else None} for xmlTemplate in xmlTemplates if "colorScale" in xmlTemplate.attrib}

    return templates

def extractMaterialTemplatesFromXML(xmlPath):
    templates = {}

    file = open(xmlPath, 'rb')
    if file is None:
        return templates

    xmlTree = xml_ET.parse(file)
    file.close()

    xmlRoot = xmlTree.getroot()
    xmlTemplates = xmlRoot.findall("template")
    templates = {xmlTemplate.attrib["name"] : xmlTemplate.attrib["colorScale"] if "colorScale" in xmlTemplate.attrib else None for xmlTemplate in xmlTemplates}

    return templates

def remapMaterialParameters(mat):
    print(mat.name)

    # Remap custom shader variation
    oldCustomShaderVariation = None
    variationDecal = False
    #variationSecondUV = False
    #variationThirdUV = False
    if "customShaderVariation" in mat:
        if mat["customShaderVariation"] in FS22customShaderVariation:
            oldCustomShaderVariation = mat["customShaderVariation"]
            variationDecal = (oldCustomShaderVariation.find("Decal") != -1)
            #variationSecondUV = (oldCustomShaderVariation.find("secondUV") != -1)
            #variationThirdUV = (oldCustomShaderVariation.find("thirdUV") != -1)
            mat["customShaderVariation"] = FS22customShaderVariation[oldCustomShaderVariation]
        else:
            del mat["customShaderVariation"]

    # Add additional properties depending on old variation
    if variationDecal:
        mat["customParameter_alphaBlendingClipThreshold"] = "1.0"

    # Remap custom shader parameters
    params = [param for param, _ in mat.items() if param.find("customParameter_") == 0 and param in FS22customParameter]
    for param in params:
        mat[FS22customParameter[param]] = mat[param]
        del mat[param]

    # Remap custom shader textures
    texs = [tex for tex, _ in mat.items() if tex.find("customTexture_") == 0 and tex in FS22customTexture]
    for tex in texs:
        mat[FS22customTexture[tex]] = mat[tex]
        del mat[tex]

def convertVehicleMaterialFS22ToFS25(gameLocation):
    brandMaterialXML = gameLocation + "data/shared/brandMaterialTemplates.xml"
    if not os.path.exists(brandMaterialXML):
        return

    brandMaterialTemplates = extractColorScaleToMaterialTemplateMapFromXML(brandMaterialXML)

    materialTemplatesXML = gameLocation + "data/shared/detailLibrary/materialTemplates.xml"
    if not os.path.exists(materialTemplatesXML):
        return

    materialTemplates = extractMaterialTemplatesFromXML(materialTemplatesXML)

    # Maps materials to a map of meshes, which in turn maps to a list of face indices
    colorMaskMaterials = {}

    mesh_objects = [obj for obj in bpy.data.objects if obj.type == 'MESH']

    for obj in mesh_objects:
        mesh = obj.data

        #print(mesh.name)
        uvs = [(math.floor(uv.vector.x), math.floor(uv.vector.y)) for uv in mesh.uv_layers.active.uv]

        for face in mesh.polygons:
            materialSlotIndex = face.material_index
            if materialSlotIndex >= len(obj.material_slots):
                continue

            material = obj.material_slots[materialSlotIndex].material
            if material == None:
                continue

            #print("face " + str(face.index) + " has material " + material.name + " assigned")

            # Check that the material uses the vehicleShader
            if "customShader" not in material or material["customShader"].find("vehicleShader.xml") == -1:
                continue

            # Check whether the material uses a colorMat_* custom shader variation, in which case the material
            # has to be converted to the new materialTemplate / brandColorTemplate setup.
            isColorMaskMaterial = False
            if "customShaderVariation" in material and material["customShaderVariation"].find("colorMask") == 0:
                isColorMaskMaterial = True

            # Since we are only interested in the floored int representation of the UV
            # we can simply use the UV coordinate of the first vertex. This value should
            # be the same for all vertices making up the face.
            # TODO(jdellsperger): Verify that all UVs floored int representations are the same?
            uvIndex = face.loop_start
            #print(uvs[uvIndex])

            if uvIndex >= len(uvs):
                continue

            uv = uvs[uvIndex]
            colorScale = None
            if isColorMaskMaterial and uv[1] < 0:
                # This material uses the customParameter_colorMat* to define the diffuse color
                # as well as the index of the material template.
                colorMatParamName = "customParameter_colorMat" + str(uv[0])
                if colorMatParamName not in material:
                    # TODO(jdellsperger): print warning - malformed material
                    continue

                colorMatParamStr = material[colorMatParamName]
                colorMatParams = colorMatParamStr.split(" ")
                colorMatParams = [float(value) for value in colorMatParams]
                #print(colorMatParams)

                colorScale = "{:.4f} {:.4f} {:.4f} 1.0".format(colorMatParams[0], colorMatParams[1], colorMatParams[2])
                #print(colorScale)

                materialTemplateIndex = int(colorMatParams[3])
                materialTemplate = FS22MaterialTemplates[materialTemplateIndex]
            else:
                # Material templates are layed out in a 8*8 grid.
                materialTemplateIndex = uv[1] * 8 + uv[0]
                materialTemplate = FS22ColoredMaterialTemplates[materialTemplateIndex]

                if materialTemplate not in materialTemplates or materialTemplates[materialTemplate] is None:
                    colorScale = "{:.4f} {:.4f} {:.4f} 1.0".format(material.diffuse_color[0], material.diffuse_color[1], material.diffuse_color[2])
                #print(colorScale)

            #print(materialTemplate)

            brandMaterialTemplate = None
            if colorScale in brandMaterialTemplates:
                #brandMaterialTemplate = brandMaterialTemplates[colorScale]["name"]
                pass
                #print(brandMaterialTemplate)

            newMaterialName = "{}_{}{}_mat".format(material.name, materialTemplate, "_" + brandMaterialTemplate if brandMaterialTemplate is not None else "")
            #print(newMaterialName)

            # Check if new materials were already generated from the
            # current material.
            if not material.name in colorMaskMaterials:
                colorMaskMaterials[material.name] = set()

            # Check if this materialTemplate/brandColor combination
            # was already generated from the current material. If
            # not, create it.
            newMaterial = None
            if not newMaterialName in colorMaskMaterials[material.name]:
                newMaterial = material.copy()
                newMaterial.name = newMaterialName
                remapMaterialParameters(newMaterial)

                # Write material template selections
                if brandMaterialTemplate is not None:
                    newMaterial["customParameterTemplate_brandColor_brandColor"] = brandMaterialTemplate
                    defaultMaterialTemplate = brandMaterialTemplates[colorScale]["parentTemplate"] if "parentTemplate" in brandMaterialTemplates[colorScale] else "metalPainted"
                    if materialTemplate != defaultMaterialTemplate:
                        newMaterial["customParameterTemplate_brandColor_material"] = materialTemplate
                else:
                    newMaterial["customParameterTemplate_brandColor_material"] = materialTemplate
                    if colorScale is not None:
                        newMaterial["customParameter_colorScale"] = colorScale
                colorMaskMaterials[material.name].add(newMaterialName)
            else:
                newMaterial = bpy.data.materials.get(newMaterialName)
                # TODO(jdellsperger): Make sure newMaterial is not None?

            materialSlotIndex = mesh.materials.find(newMaterialName)
            if materialSlotIndex == -1:
                mesh.materials.append(newMaterial)
                materialSlotIndex = mesh.materials.find(newMaterialName)

            face.material_index = materialSlotIndex

    for materialName, _ in colorMaskMaterials.items():
        for obj in bpy.data.objects:
            bpy.context.view_layer.objects.active = obj

            for mat in obj.material_slots:
                if mat.name == materialName:
                    bpy.context.object.active_material_index = mat.slot_index
                    bpy.ops.object.material_slot_remove()
        material = bpy.data.materials.get(materialName)
        bpy.data.materials.remove(material)
