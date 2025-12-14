"""i3d_densityUtil.py is used to calculate the uvDensity of a mesh"""


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

import math
import mathutils

_max_tex_coord_sets = 4
_flt_max = 3.402823466e+38 

class OnlineMeanVarianceData():
    """ Holds the values to compute the mean value"""

    def __init__(self):
        self.count = 0   #the number of values so far
        self.m2 = 0.0    #the sum of squares of differences from the current mean
        self.mean = 0.0  #the current mean

class StatisticsUtil:
    """ Some statistics utilits functions translated from the c++ script"""
    
    @staticmethod
    def errorFunction(x):   #unused
        """ Calculates an appromixation (maximum error: 5x10^-4) of the error function (erf(x)) """
        
        ax = abs(x)
        div = 1.0 + 0.278393*ax + 0.230389*ax**2 + 0.000972*ax**3 + 0.078108*ax**4 
        div = div**4
        f = 1.0 - 1.0 / div
        if x >= 0.0:
            return f
        else:
            return -f
            
    @staticmethod
    def complementaryErrorFunction(x):  #unused
        """
        Calculates the complementary error function of the value x.
        
        Calculates an appromixation (maximum error: 5x10^-4) of the complementary error function (erfc(x) = 1-erf(x))
        Can be used to transform a normal distribution (0,1) into a uniform distribution (0,1) with uniformV = 0.5*erfc(-normalV / sqrt(2))
        """
        ax = abs(x)
        div = 1.0 + 0.278393*ax + 0.230389*ax**2 + 0.000972*ax**3 + 0.078108*ax**4
        div = div**4
        cf = 1.0 / div
        if x >= 0.0:
            return cf
        else:
            return 2.0 - cf
            
    @staticmethod
    def convertToUniformRandom(randomValue,pCDF,cfdSize):   #unused
        """ Calculates a uniformly distributed random value given a random value [0,1) and its corresponding commulative distribution function (as a table) """
    
        indexCdfF = randomValue * 64
        indexCdf = min(int(indexCdfF), cfdSize-1)
        cdf1 = pCDF[indexCdf]

        if indexCdf == 0:
            cdf0 = 0.0
        else:
            cdf0 = pCDF[indexCdf-1]
        alpha = indexCdfF - indexCdf
        return cdf0 + alpha * (cdf1 - cdf0)
        
    @staticmethod
    def updateMeanVariance(x, data: OnlineMeanVarianceData):
        """ Adds a new sample point to the OnlineMeanVarianceData to calculate both the variance and the mean in a single pass in a relatively robust way """
        
        data.count += 1
        delta = x - data.mean
        data.mean += delta / data.count
        delta2 = x - data.mean
        data.m2 += delta * delta2
        return data
           
    @staticmethod
    def calculateMeanVariance(data):
        """ Calculates the mean and the variance based on the gathered data from previous calls to updateMeanVariance """
        
        mean = data.mean
        try:
            if (data.count == 1):
                variance = 0
            else:
                variance = data.m2 / (data.count - 1)
            return (mean, variance)
        except Exception as e:
            print(e)
            return (-1,-1)
            
def determineUvDensity(mininum, mean, stdDeviation):
    """
    Calculates the UV density
    
    assuming a standard normal distribution of uv density, we want to pick the smallest 'regular' sample
    in this ideal case, about 68% of the samples around the mean are considered 'regular'
    BUT some meshes doesn't have a normal distribution, so we must write some defensive code
    if the density is widely spread / irregular, we stay close to the mean
    Later, the editor/exporter will provide feedback if the data needs to be fixed
    
    :param minimum: the minimum value
    :param mean: the mean value
    :param stdDeviation: 
    """
    idealSmallest = mean - stdDeviation;
    safeSmallest = 0.75 * mean
    determinedSmallest = max(idealSmallest, safeSmallest)
    return float(max(mininum, determinedSmallest))       #the final uv density cannot be smaller than the minimum
    
def isTriangleUvDensityUseless(triangleUvDensity):  #tested
    """ Checks if the triangleUvDensity is a reasonable value """

    maxPossibleTextureResolution = 4096;
    minPixelPerSpaceUnit = 64;
    log2MinPixelPerSpaceUnit = math.log2(minPixelPerSpaceUnit)
    log2TextureResolutionUpperLimit = math.log2(maxPossibleTextureResolution)
    diffPow = log2TextureResolutionUpperLimit - log2MinPixelPerSpaceUnit
    threshold = 1.0 / pow(2, diffPow)       # 0.015625 (run from C-code)
    return triangleUvDensity < threshold

def computeTriangleUvDensity(positions, uvs):
    """ 
    Requires the three positions of the triangle vertices and their uv (tX) value 
    
    :param positions: list of position Vectors of the triangle
    :param uvs: list of uv Vectors of the trangles 
    """
    
    uvDensity = 0.0
    for vertexIndex in range(0,3):
        nextVertexIndex = (vertexIndex + 1) % 3
        pCur = positions[vertexIndex]
        pNex = positions[nextVertexIndex]
        sqMagnPosCurNex = (pCur - pNex).dot(pCur - pNex)
        if sqMagnPosCurNex == 0:
            return 0.0             #squashed vertexes
        uvCur = uvs[vertexIndex]
        uvNex = uvs[nextVertexIndex]
        sqMagnUVCurNex = (uvCur - uvNex).dot(uvCur - uvNex)
        if sqMagnUVCurNex == 0:
            return 0.0              #squashed uv coords

        uvDensitySq = sqMagnUVCurNex / sqMagnPosCurNex
        uvDensity += math.sqrt(uvDensitySq)
        vertexIndex +=1
    uvDensity = uvDensity / 3.0
    return uvDensity

def computeUvDensity( trianglesDict, verticesProperty, firstIndex, numIndices):
    """
    Computes the uv Denstiy for the given Shapes.
    
    :param trianglesDict: IndexBuffer data as triangle seperated dictionary
    :param verticesProperty: Vertex Buffer data as dictionary
    :param firstIndex: Start index for uvDensity calculation
    :param numIndices: Number of entries evaluated for the uv density calculation
    :returns: Returns a dictionary with uvDensityX entries
    """
    verticesDict = verticesProperty['data']
    uvDensity = {}
    densitySet = []
    for i in range(_max_tex_coord_sets):
        if "uv{}".format(i) in verticesProperty and verticesProperty["uv{}".format(i)] == "true":
            densitySet.append(i)
            uvDensity["uvDensity{}".format(i)] = 0.0
    if len(densitySet) == 0:
        return uvDensity
    
    minUVDensity = _flt_max          
    atLeastOneGoodTriangle = False
    meanVarianceData = OnlineMeanVarianceData()
   
    for setNumber in densitySet:
        indexBuffer = 0
        for triangle in trianglesDict:
            # print("indexBuffer: {}, triangle: {}, valid buffer Range: [{},{}]".format(indexBuffer,triangle,firstIndex,firstIndex+numIndices))
            if firstIndex <= indexBuffer and indexBuffer < firstIndex+numIndices:  #must be in requested range of the indexbuffer
                triangleVertices = [int(i) for i in triangle["vi"].strip().split(" ")]
                positions = [ mathutils.Vector([float(i) for i in verticesDict[triangleVertices[0]]["p"].strip().split(" ")]),
                            mathutils.Vector([float(i) for i in verticesDict[triangleVertices[1]]["p"].strip().split(" ")]),
                            mathutils.Vector([float(i) for i in verticesDict[triangleVertices[2]]["p"].strip().split(" ")]) ]  
                uvs = [ mathutils.Vector([float(i) for i in verticesDict[triangleVertices[0]]["t{}".format(setNumber)].strip().split(" ")]),
                        mathutils.Vector([float(i) for i in verticesDict[triangleVertices[1]]["t{}".format(setNumber)].strip().split(" ")]),
                            mathutils.Vector([float(i) for i in verticesDict[triangleVertices[2]]["t{}".format(setNumber)].strip().split(" ")]) ]
                triangleUvDensity = min(1.0, computeTriangleUvDensity(positions, uvs))
                if isTriangleUvDensityUseless(triangleUvDensity):
                    indexBuffer += 3
                    continue
                meanVarianceData = StatisticsUtil.updateMeanVariance(triangleUvDensity, meanVarianceData)
                minUVDensity = min(minUVDensity, triangleUvDensity)
                atLeastOneGoodTriangle = True
            indexBuffer += 3
            
        if not atLeastOneGoodTriangle:
            return uvDensity
        
        mean, variance = StatisticsUtil.calculateMeanVariance(meanVarianceData)
        stdDeviation = math.sqrt(variance)
        uvDensity["uvDensity{}".format(setNumber)] = determineUvDensity(minUVDensity, mean, stdDeviation)
    return uvDensity
    
if __name__ == "__main__":
    """ Test function with dummy data """
    
    print(__file__)
    print("StatisticsUtil")
    print("errorFunction: {}".format(StatisticsUtil.errorFunction(5)))
    print("complementaryErrorFunction: {}".format(StatisticsUtil.complementaryErrorFunction(5)))
    print("convertToUniformRandom: {}".format(StatisticsUtil.convertToUniformRandom(0.5,[1,2,3,4,5,6,7,8],8)))
    OMVD = OnlineMeanVarianceData
    OMVD.count = 1   
    OMVD.m2 = 2.0    
    OMVD.mean = 3.0 
    print("updateMeanVariance: {}".format(StatisticsUtil.updateMeanVariance(5,OMVD)))
    print("calculateMeanVariance: {}".format(StatisticsUtil.calculateMeanVariance(OMVD)))    
    verticesDict = {"data" : [{"n":"-0.577349 0.577349 -0.577349", "p":"-1 1 -1", "t0" : "0.875 0.5","t1" : "0.875 0.5"},
                {"n":"0.577349 0.577349 0.577349", "p":"1 1 1", "t0":"0.625 0.75","t1" : "0.875 0.5"},
                {"n":"0.577349 0.577349 -0.577349", "p":"1 1 -1", "t0":"0.625 0.5" ,"t1" : "0.875 0.5"},
                {"n":"-0.577349 -0.577349 0.577349", "p":"-1 -1 1", "t0":"0.375 1" ,"t1" : "0.875 0.5"},
                {"n":"0.577349 -0.577349 0.577349", "p":"1 -1 1", "t0":"0.375 0.75" ,"t1" : "0.875 0.5"},
                {"n":"-0.577349 0.577349 0.577349", "p":"-1 1 1", "t0":"0.625 0" ,"t1" : "0.875 0.5"},
                {"n":"-0.577349 -0.577349 -0.577349", "p":"-1 -1 -1", "t0":"0.375 0.25" ,"t1" : "0.875 0.5"},
                {"n":"-0.577349 -0.577349 0.577349", "p":"-1 -1 1", "t0":"0.375 0" ,"t1" : "0.875 0.5"},
                {"n":"0.577349 -0.577349 -0.577349", "p":"1 -1 -1", "t0":"0.375 0.5" ,"t1" : "0.875 0.5"},
                {"n":"-0.577349 -0.577349 0.577349", "p":"-1 -1 1", "t0":"0.125 0.75" ,"t1" : "0.875 0.5"},
                {"n":"-0.577349 -0.577349 -0.577349", "p":"-1 -1 -1", "t0":"0.125 0.5" ,"t1" : "0.875 0.5"},
                {"n":"-0.577349 0.577349 -0.577349", "p":"-1 1 -1", "t0":"0.625 0.25" ,"t1" : "0.875 0.5"},
                {"n":"-0.577349 0.577349 0.577349", "p":"-1 1 1", "t0":"0.875 0.75" ,"t1" : "0.875 0.5"},
                {"n":"-0.577349 0.577349 0.577349", "p":"-1 1 1", "t0":"0.625 1" ,"t1" : "0.875 0.5"}], "uv0":"true","uv1": "true"}
    trianglesDict = [{"vi":"0 1 2" },
                {"vi":"1 3 4" },
                {"vi":"5 6 7" },
                {"vi":"8 9 10" },
                {"vi":"2 4 8" },
                {"vi":"11 8 6" },
                {"vi":"0 12 1" },
                {"vi":"1 13 3" },
                {"vi":"5 11 6" },
                {"vi":"8 4 9" },
                {"vi":"2 1 4" },
                {"vi":"11 2 8" }]
    print("computeUvDensity: {}".format(computeUvDensity(trianglesDict,verticesDict, 0, 0)))
    
    
    
    
    
    
