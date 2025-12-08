# This files is a 1 to 1 copy from the MayaExporter

# Class for loading and managing flags for collision group and collision mask i3d attributes
# also provides presets consisting of a group and mask pair
# data is loaded from xml previously exported from game script

import xml.etree.ElementTree as ET
from os import path

class CollisionMaskFlags:
    def __init__(self, xmlFilepath):
        self.flagsByName = {}
        self.flagsByBit = {}
        self.presetsByName = {}
        self.presetsByMasks = {}
        self.defaultColFilterGroup = 0xFF
        self.defaultColFilterMask = 0xFFFF_FBFF

        self.conversionRules = {}

        self.loadCollisionMaskFlagsFromXML(xmlFilepath)

        # TODO: copy/move to exporter once proofen to include most common cases
        conversionRulesXMLFilepath = path.normpath(path.join(path.dirname(path.realpath(__file__)), "../../../bin/shared/collisionMaskConversionRules.xml"))
        self.loadConversionRulesFromXML(conversionRulesXMLFilepath)

    def loadCollisionMaskFlagsFromXML(self, xmlFilepath):
        self.flagsByName = {}
        self.flagsByBit = {}
        self.presetsByName = {}
        self.presetsByMasks = {}

        try:
            collisionFlagsXML = ET.parse(xmlFilepath)
            root = collisionFlagsXML.getroot()
            for flagElem in root.findall('flag'):
                name = flagElem.get('name')
                bit = int(flagElem.get('bit'))
                desc = flagElem.get('desc')
                value = pow(2, bit)

                self.flagsByName[name] = {"bit":bit, "value":value, "desc":desc}
                self.flagsByBit[bit] = {"name":name, "value":value, "desc":desc}

            self.defaultColFilterMask = parseInt(root.find('defaultMask').text)

            # load presets
            for presetElem in root.findall('preset'):
                name = presetElem.get('name')
                desc = presetElem.get('desc')

                groupMask = self.loadMask(presetElem.find('group'))
                filterMask = self.loadMask(presetElem.find('mask'))

                self.presetsByName[name] = {"group": groupMask, "mask": filterMask, "desc": desc}

                # use string of both masks as identifier for cheap reverse lookup
                combinedKey = "{}|{}".format(groupMask, filterMask)
                self.presetsByMasks[combinedKey] = {"name": name, "group": groupMask, "mask": filterMask, "desc": desc}
        except ET.ParseError:
            print("Warning: CollisionMaskFlags: unable to parse '{}'".format(xmlFilepath))
        except FileNotFoundError:
            print("Warning: CollisionMaskFlags: '{}' does not exist".format(xmlFilepath))

        print("Loaded {} flags and {} presets from {}".format(len(self.flagsByBit), len(self.presetsByMasks), xmlFilepath))

    def loadConversionRulesFromXML(self, xmlFilepath):
        self.conversionRules = {}

        try:
            conversionXML = ET.parse(xmlFilepath)
            root = conversionXML.getroot()
            rules = root.find('conversionRules')
            for ruleElem in rules.findall('rule'):
                maskOld = int(ruleElem.get('maskOld'))

                for output in ruleElem.findall('output'):
                    presetName = output.get('preset')
                    groupMask = 0
                    filterMask = 0

                    if presetName:
                        preset = self.presetsByName.get(presetName)
                        if preset is None:
                            print("Error: Unknown preset '{}'".format(presetName))
                        else:
                            groupMask = preset['group']
                            filterMask = preset['mask']

                    groupElem = output.find('group')
                    maskElem = output.find('mask')
                    if groupElem is not None:
                        groupMask = groupMask | self.loadMask(groupElem)

                    if maskElem is not None:
                        filterMask = filterMask | self.loadMask(maskElem)
                    elif filterMask == 0:
                        filterMask = self.defaultColFilterMask

                    isTrigger = output.get('isTrigger') == "true"

                    if self.conversionRules.get(maskOld) is None:
                        self.conversionRules[maskOld] = []
                    
                    self.conversionRules[maskOld].append({'group': groupMask, 'mask': filterMask, 'isTrigger': isTrigger})
        except ET.ParseError:
            print("Warning: CollisionMaskFlags: unable to parse '{}'".format(xmlFilepath))
        except FileNotFoundError:
            print("Warning: CollisionMaskFlags: '{}' does not exist".format(xmlFilepath))

        print("Loaded {} conversion rules from {}".format(len(self.conversionRules), xmlFilepath))

    def getPresetByMasks(self, group, mask):
        '''Get preset by group and mask decimal values'''
        combinedKey = "{}|{}".format(group, mask)
        return self.presetsByMasks.get(combinedKey)
    
    def getPresetGroupAndMask(self, presetName, asHex=False):
        '''Get preset group and mask as two integers or 0x-prefixed lowercase hex strings if asHex=True'''
        preset = self.presetsByName.get(presetName)
        if preset is not None:
            if asHex:
                return hex(preset["group"]), hex(preset["mask"])
            return preset["group"], preset["mask"]
        return None, None
    
    def loadMask(self, xmlElement):
        maskNew = 0

        if xmlElement is None:
            return maskNew

        # try parsing input directly as number
        valueStr = xmlElement.get("value")
        if valueStr is not None:
            maskValue = parseInt(valueStr)
            if maskValue is None:
                # invalid number literal given
                print("Error: Unable to parse '{}' as a number for {}".format(valueStr, xmlElement))
                return None
            maskNew = maskValue

        for flagElement in xmlElement.findall('flag'):
            # using name identifier
            flagName = flagElement.get("name")
            if flagName is not None:
                if self.flagsByName.get(flagName) is None:
                    print("Error: Unable to find CollisionFlag {} for {}".format(flagName, flagElement))
                    continue

                maskNew = maskNew | (self.flagsByName.get(flagName)["value"])
                continue

            # using bit
            bitNumber = flagElement.get("bit")
            if bitNumber == None:
                continue

            if bitNumber < 0 or bitNumber > 31:
                print("Error: Invalid bit number {} at {}, needs to be between 0 and 31".format(bitNumber, flagElement))
                continue

            maskNew = maskNew | (2 ^ bitNumber)
        
        return maskNew
    
    def getConversionRules(self, mask):
        mask = int(mask)
        return self.conversionRules.get(mask)

# parses an integer from either plain integer string or hex string prefixed with 0x
def parseInt(str):
    if str is None:
        return None
    try:
        str = str.replace("_", "")
        if str.startswith("0x"):
            return int(str[2:], 16)
        else:
            return int(str)
    except ValueError:
        return None
