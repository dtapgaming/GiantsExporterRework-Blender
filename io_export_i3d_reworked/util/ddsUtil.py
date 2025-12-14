""" 
This module directly writes binary .dds files according to the documentation:
https://docs.microsoft.com/en-us/windows/win32/direct3ddds/dx-graphics-dds-pguide
The written data format is customize for the GIANTS i3d blender exporter
"""

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

import os
import struct 
import numpy as np
import sys


GS_DDS_HEADER_EXT_MAGIC_TAG = 0X288AE8D9

class Flags:
    """ Flag Property options """
    
    #bit flags for header
    DDSD_CAPS       = 0X00000001
    DDSD_HEIGHT     = 0X00000002
    DDSD_WIDTH      = 0X00000004
    DDSD_PITCH      = 0X00000008
    DDSD_PIXELFORMAT    = 0X00001000
    DDSD_MIPMAPCOUNT    = 0X00020000
    DDSD_LINEARSIZE = 0X00080000
    DDSD_DEPTH      = 0X00800000
    #flags for pixel formats
    DDPF_ALPHAPIXELS    = 0X00000001
    DDPF_ALPHA      = 0X00000002
    DDPF_FOURCC     = 0X00000004
    DDPF_RGB        = 0X00000040
    DDPF_RGBA       = 0X00000041
    DDPF_YUV        = 0X00000200
    DDPF_LUMINANCE  = 0X00020000
    #flags for complex caps
    DDSCAPS_COMPLEX = 0X00000008
    DDSCAPS_MIPMAP  = 0X00400000
    DDSCAPS_TEXTURE = 0X00001000
    #flags for cubemaps
    DDSCAPS2_CUBEMAP            = 0X00000200
    DDSCAPS2_CUBEMAP_POSITIVEX  = 0X00000400
    DDSCAPS2_CUBEMAP_NEGATIVEX  = 0X00000800
    DDSCAPS2_CUBEMAP_POSITIVEY  = 0X00001000
    DDSCAPS2_CUBEMAP_NEGATIVEY  = 0X00002000
    DDSCAPS2_CUBEMAP_POSITIVEZ  = 0X00004000
    DDSCAPS2_CUBEMAP_NEGATIVEZ  = 0X00008000
    DDSCUBEMAP_ALL_FACES = (DDSCAPS2_CUBEMAP_POSITIVEX | DDSCAPS2_CUBEMAP_NEGATIVEX | DDSCAPS2_CUBEMAP_POSITIVEY | DDSCAPS2_CUBEMAP_NEGATIVEY | DDSCAPS2_CUBEMAP_POSITIVEZ | DDSCAPS2_CUBEMAP_NEGATIVEZ)
    DDSCAPS2_VOLUME             = 0X00200000
    
class DDSDxgiFormat:
    """ Format Flags """

    DDS_DXGI_FORMAT_R32G32B32A32_FLOAT  = 2
    DDS_DXGI_FORMAT_R32G32B32_FLOAT     = 6
    DDS_DXGI_FORMAT_R16G16B16A16_FLOAT  = 10
    DDS_DXGI_FORMAT_R32G32_FLOAT        = 16
    DDS_DXGI_FORMAT_R8G8B8A8_UNORM      = 28
    DDS_DXGI_FORMAT_R16G16_FLOAT        = 34
    DDS_DXGI_FORMAT_R32_FLOAT           = 41
    DDS_DXGI_FORMAT_R8G8_UNORM          = 49
    DDS_DXGI_FORMAT_R16_FLOAT           = 54
    DDS_DXGI_FORMAT_R8_UNORM            = 61
    DDS_DXGI_FORMAT_BC1_UNORM           = 71
    DDS_DXGI_FORMAT_BC2_UNORM           = 74
    DDS_DXGI_FORMAT_BC3_UNORM           = 77
    DDS_DXGI_FORMAT_BC4_UNORM           = 80
    DDS_DXGI_FORMAT_BC4_SNORM           = 81
    DDS_DXGI_FORMAT_BC5_UNORM           = 83
    DDS_DXGI_FORMAT_BC5_SNORM           = 84
    DDS_DXGI_FORMAT_B8G8R8A8_UNORM      = 87
    DDS_DXGI_FORMAT_BC6H_UF16           = 95
    DDS_DXGI_FORMAT_BC6H_SF16           = 96
    DDS_DXGI_FORMAT_BC7_UNORM           = 98

class DDSPixelFormats:
    """ DDS pixel format options """
    
    DDS_UNKNOWN     =  0
    DDS_R8G8B8      = 20
    DDS_A8R8G8B8    = 21
    DDS_X8R8G8B8    = 22
    DDS_R5G6B5      = 23
    DDS_X1R5G5B5    = 24
    DDS_A1R5G5B5    = 25
    DDS_A4R4G4B4    = 26
    DDS_R3G3B2      = 27
    DDS_A8          = 28
    DDS_A8R3G3B2    = 29
    DDS_X4R4G4B4    = 30
    DDS_A2B10G10R10 = 31
    DDS_A8B8G8R8    = 32
    DDS_X8B8G8R8    = 33
    DDS_G16R16      = 34
    DDS_A2R10G10B10 = 35
    DDS_A16B16G16R16    = 36
    DDS_A8P8        = 40
    DDS_P8          = 41
    DDS_L8          = 50
    DDS_A8L8        = 51
    DDS_A4L4        = 52
    DDS_V8U8        = 60
    DDS_L6V5U5      = 61
    DDS_X8L8V8U8    = 62
    DDS_Q8W8V8U8    = 63
    DDS_V16U16      = 64
    DDS_A2W10V10U10 = 67
    DDS_UYVY        = 0X32595559    #GS_MAKEFOURCC('U', 'Y', 'V', 'Y')
    DDS_R8G8_B8G8   = 0X32595559    #GS_MAKEFOURCC('R', 'G', 'B', 'G')
    DDS_YUY2        = 0X32595559    #GS_MAKEFOURCC('Y', 'U', 'Y', '2')
    DDS_G8R8_G8B8   = 0X42475247    #GS_MAKEFOURCC('G', 'R', 'G', 'B')
    DDS_BC1         = 0X33545844    #GS_MAKEFOURCC('D', 'X', 'T', '1')
    DDS_BC2         = 0X33545844    #GS_MAKEFOURCC('D', 'X', 'T', '3')
    DDS_BC3         = 0X35545844    #GS_MAKEFOURCC('D', 'X', 'T', '5')
    DDS_ATI1        = 0X55344342    #GS_MAKEFOURCC('A', 'T', 'I', '1')     # = 'B', 'C', '4', 'U'
    DDS_BC4         = 0X55344342    #GS_MAKEFOURCC('B', 'C', '4', 'U')     # = 'A', 'T', 'I', '1'
    DDS_BC4S        = 0X53344342    #GS_MAKEFOURCC('B', 'C', '4', 'S')
    DDS_ATI2        = 0X55354342    #GS_MAKEFOURCC('A', 'T', 'I', '2')     # = 'B', 'C', '5', 'U'
    DDS_BC5         = 0X55354342    #GS_MAKEFOURCC('B', 'C', '5', 'U')     # = 'A', 'T', 'I', '2'
    DDS_BC5S        = 0X53354342    #GS_MAKEFOURCC('B', 'C', '5', 'S')
    DDS_DX10        = 0X30315844    #GS_MAKEFOURCC('D', 'X', '1', '0')
    DDS_D16_LOCKABLE    = 70
    DDS_D32         = 71
    DDS_D15S1       = 73
    DDS_D24S8       = 75
    DDS_D24X8       = 77
    DDS_D24X4S4     = 79
    DDS_D16         = 80
    DDS_D32F_LOCKABLE   = 82
    DDS_D24FS8      = 83
    DDS_L16         = 81
    DDS_VERTEXDATA  =100
    DDS_INDEX16     =101
    DDS_INDEX32     =102
    DDS_Q16W16V16U16    =110
    DDS_MULTI2_ARGB8    =0X3154454D     #GS_MAKEFOURCC('M','E','T','1')
    # Floating point surface formats
    # s10e5 formats (16-bits per channel)
    DDS_R16F        = 111
    DDS_G16R16F     = 112
    DDS_A16B16G16R16F   = 113
    # IEEE s23e8 formats (32-bits per channel)
    DDS_R32F        = 114
    DDS_G32R32F     = 115
    DDS_A32B32G32R32F   = 116
    DDS_CxV8U8      = 117
    DDS_FORCE_DWORD = 0X7fffffff

class DDS_EXTENDED_FLAGS:
    """ GIANTS specific extended flags (stored in reserved1[2] of the dds header) """
    
    DDS_EXTENDED_FLIPPED_Y  = 0X00000001    #1U<<0
    DDS_EXTENDED_ALLOW_RAW  = 0X00000002    #1U<<1

class DDSRescourceDimensions:
    """ DDS_RESOURCE_DIMENSION_TEXTURE1D values"""
    
    DDS_RESOURCE_DIMENSION_TEXTURE1D = 2
    DDS_RESOURCE_DIMENSION_TEXTURE2D = 3
    DDS_RESOURCE_DIMENSION_TEXTURE3D = 4
    
class DWORD:
    """
    A 32-bit unsigned integer. 
    
    The range is 0 through 4294967295 decimal.
    This type is declared in IntSafe.h as follows:
    typedef unsigned long DWORD;
    """
    def __init__(self, value=0):
        self.v = np.uint32(value)
  
class FLOAT:
    """
    C type float.
    
    Real floating-point type, usually referred to as a single-precision floating-point type. 
    Actual properties unspecified (except minimum limits), however on most systems this is the IEEE 754 single-precision binary floating-point format (32 bits)
    """
    def __init__(self, value=0.0):
        self.v = np.float32(value)
        
class FLOAT16:
    """
    C type float.
    
    16bit floating-point type, usually referred to as a half-precision floating-point type. 
    """
    def __init__(self, value=0.0):
        self.v = np.float16(value)
        
class UINT:
    """
    A 32-bit unsigned integer. The range is 0 through 4294967295 decimal.
    This type is declared in IntSafe.h as follows:
    typedef unsigned int UINT;
    """
    def __init__(self, value=0):
        self.v = np.uint32(value)       

class DDS_HEADER:
    """ DDS_HEADER specifications """
    
    def __init__(self):
        self.dwSize =  DWORD(124)               #size of the DDSHeader structure
        #determines what fields are valid
        self.dwFlags = DWORD(Flags.DDSD_CAPS    
                        | Flags.DDSD_HEIGHT
                        | Flags.DDSD_WIDTH
                        | Flags.DDSD_PIXELFORMAT
                        )
        self.dwHeight = DWORD(0)                #height of surface to be created (in pixels).
        self.dwWidth = DWORD(0)                 #width of input surface(in pixels).
        self.dwPitchOrLinearSize = self.computePitch()         #distance to start of next line (return value only) or Formless late-allocated optimized surface size
        self.dwDepth = DWORD(0)                 #Depth of a volume texture (in pixels), otherwise unused.
        self.dwMipMapCount = DWORD(0)           #Number of mipmap levels, otherwise unused.
        self.dwReserved1 = [DWORD()] * 11             #reserved
        self.ddspf = DDS_PIXELFORMAT();         #pixel format description of the surface
        self.dwCaps = DWORD(0X1000)             #Specifies the complexity of the surfaces stored.
        self.dwCaps2 = DWORD(0)         #Additional detail about the surfaces stored.
        self.dwCaps3 = DWORD(0)         #Unused.
        self.dwCaps4 = DWORD(0)         #Unused.
        self.dwReserved2 = DWORD(0)     #stage in multitexture cascade

    def computePitch(self, f = '', f2 =''):
        """ distance to start of next line (return value only) or Formless late-allocated optimized surface size """
    
        width = self.dwWidth.v
        if f == 'block compressed':
            if f2 == 'DXT1' or f2 == 'BC1' or f2 ==' BC4':
                blockSize = 8
            else:
                blockSize = 16
            return DWORD(max(1,((width+3)/4) * blockSize))
        elif f == 'R8G8_B8G8' or f == 'G8R8_G8B8' or f == ' UYVY' or f == 'YUY2':
            return DWORD(((width+1) >> 1) * 4)
        else:
            bytesPerPixel = 4
            return DWORD(( width * bytesPerPixel + 7 ) / 8)
            
class DDS_HEADER_DXT10:
    """ DDS_HEADER_DXT10 specifications """
    
    def __init__(self):
        self.dxgiFormat = UINT();        #Of type DXGI_FORMAT
        self.resourceDimension = UINT();
        self.miscFlag = UINT()
        self.arraySize = UINT()
        self.miscFlags2 = UINT()
        
class DDS_PIXELFORMAT:
    """ DDS_PIXELFORMAT """

    def __init__(self):
        self.dwSize = DWORD(0X20)               #Structure size; set to 32 (bytes)
        self.dwFlags = DWORD(Flags.DDPF_FOURCC) #pixel format flags
        self.dwFourCC = DWORD(0X30315844)       #(FOURCC code)    
        self.dwRGBBitCount = DWORD(0)           #how many bits per pixel. Valid when dwFlags includes DDPF_RGB, DDPF_LUMINANCE, or DDPF_YUV.
        self.dwRBitMask = DWORD(0X00000000)     #mask for red bit       Red (or lumiannce or Y) mask for reading color data. For instance, given the A8R8G8B8 format, the red mask would be 0x00ff0000.
        self.dwGBitMask = DWORD(0X00000000)     #mask for green bits    Green (or U) mask for reading color data. For instance, given the A8R8G8B8 format, the green mask would be 0x0000ff00.    
        self.dwBBitMask = DWORD(0X00000000)     #mask for blue bits     Blue (or V) mask for reading color data. For instance, given the A8R8G8B8 format, the blue mask would be 0x000000ff.
        self.dwABitMask = DWORD(0X00000000)     #mask for alpha channel Alpha mask for reading alpha data. dwFlags must include DDPF_ALPHAPIXELS or DDPF_ALPHA. For instance, given the A8R8G8B8 format, the alpha mask would be 0xff000000.

def writeDDS(file, magicNumber, header, header10, data):
    """
    Writes the binary file
    
    :param file: filename and path of target file
    :param magicNumber: constant number for DDS file
    :param header: regular DDS header
    :param header10: DXT10 header 
    :param data: customized data
    """
    
    fd_out = open(file,'wb')    #write, binary
    
    entry = struct.pack("@I",magicNumber.v)
    # print("field: {}, value: {}, entry: {}".format("magic Number",magicNumber.v,entry))
    fd_out.write(entry)
    #loop over header fields
    headerFields = vars(header)
    for field, value in headerFields.items():
        if field == 'ddspf':        
            for field, value in vars(value).items():  #DDS_PIXELFORMAT
                entry = struct.pack("@I",value.v)
                # print("field: {}, value: {}, entry: {}".format(field,value.v,entry))
                fd_out.write(entry)
        elif field == 'dwReserved1':
            for item in value:
                entry = struct.pack("@I",item.v)
                # print("field: {}, value: {}, entry: {}".format(field,item.v, entry))
                fd_out.write(entry)
        else:
            entry = struct.pack("@I",value.v)
            # print("field: {}, value: {}, entry: {}".format(field,value.v, entry))
            fd_out.write(entry)
        
    #loop over header10 fields
    header10Fields = vars(header10)
    for field, value in header10Fields.items():
        entry = struct.pack("@I",value.v)
        # print("field: {}, value: {}, entry: {}".format(field,value.v, entry))
        fd_out.write(entry)
    #loop over data
    # print("entries: {}".format(len(data)))
    for dataWord in data:
        # print("data: {}, dataWord16: {}".format(dataWord,FLOAT16(dataWord).v))
        entry = struct.pack("@e",FLOAT16(dataWord).v)
        fd_out.write(entry)
    fd_out.flush()
    fd_out.close()

def configureHeader(header,header10,height,width,numMipMaps, formatName, textureType, arraySize, typeName, channels):
    """ 
    Configure the DDS_HEADER
    
    It is expected that the DX10 header is used    
    :param header: default header
    :param header10: default DXT10 header
    :param height: the height of the surface
    :param width: the width of the surface
    :param numMipMaps: number of mip maps, expected 0
    :param formatName: name of theformat, expected "UNKNOWN"
    :param textureType: type of the texture
    :param arraySize: array size for the DXT10 header
    :param typeName: name of type of the data, expected "TYPE_SIGNED_HALF"
    :param channels: 1 OR 2 OR 4
    """

    usesDX10 = False
    if textureType == 'TEX_2D_ARRAY' or (typeName == 'TYPE_UNSIGNED_BYTE' and channels <= 2) or formatName == 'FORMAT_BC6' or formatName == 'FORMAT_BC6S' or formatName == 'FORMAT_BC7':
        usesDX10 = True
        if textureType == 'TEX_2D_ARRAY' and arraySize <= 1:
            return False
    
    
    header.dwSize = DWORD(124)
    header.dwHeight = DWORD(height)
    header.dwWidth = DWORD(width)
    header.dwCaps = DWORD(Flags.DDSCAPS_TEXTURE)
    header.dwReserved1[0] = DWORD(GS_DDS_HEADER_EXT_MAGIC_TAG)
    header.dwReserved1[2] = DWORD(DDS_EXTENDED_FLAGS.DDS_EXTENDED_ALLOW_RAW)
    if numMipMaps > 0:
        header.dwCaps = DWORD(header.dwCaps | Flags.DDSCAPS_MIPMAP)
    header.dwMipMapCount = DWORD(numMipMaps + 1)
    header.dwFlags = DWORD(Flags.DDSD_PIXELFORMAT | Flags.DDSD_WIDTH | Flags.DDSD_HEIGHT | Flags.DDSD_CAPS | Flags.DDSD_MIPMAPCOUNT)
    if textureType == 'TEX_CUBE':
        header.dwCaps = DWORD(header.dwCaps | Flags.DDSCAPS_COMPLEX)
        header.dwCaps2 = DWORD(Flags.DDSCAPS2_CUBEMAP|Flags.DDSCUBEMAP_ALL_FACES)
    if usesDX10:
        header.ddspf.dwFlags = DWORD(Flags.DDPF_FOURCC)
        header.ddspf.dwFourCC = DWORD(DDSPixelFormats.DDS_DX10)
        header10.arraySize = DWORD(arraySize)
        if formatName == 'FORMAT_BC6':
            header10.dxgiFormat = UINT(DDSDxgiFormat.DDS_DXGI_FORMAT_BC6H_UF16)
        elif formatName == 'FORMAT_BC6S':
            header10.dxgiFormat = UINT(DDSDxgiFormat.DDS_DXGI_FORMAT_BC6H_SF16)
        elif formatName == 'FORMAT_BC7':
            header10.dxgiFormat = UINT(DDSDxgiFormat.DDS_DXGI_FORMAT_BC7_UNORM)
        elif typeName == 'TYPE_SIGNED_FLOAT':
            if channels == 1:
                header10.dxgiFormat = UINT(DDSDxgiFormat.DDS_DXGI_FORMAT_R32_FLOAT)
            elif channels == 2:
                header10.dxgiFormat = UINT(DDSDxgiFormat.DDS_DXGI_FORMAT_R32G32_FLOAT)
            elif channels == 4:
                header10.dxgiFormat = UINT(DDSDxgiFormat.DDS_DXGI_FORMAT_R32G32B32A32_FLOAT)
            else:
                return False
        elif typeName == 'TYPE_SIGNED_HALF':
            if channels == 1:
                header10.dxgiFormat = UINT(DDSDxgiFormat.DDS_DXGI_FORMAT_R16_FLOAT)
            elif channels == 2:
                header10.dxgiFormat = UINT(DDSDxgiFormat.DDS_DXGI_FORMAT_R16G16_FLOAT)
            elif channels == 4:
                header10.dxgiFormat = UINT(DDSDxgiFormat.DDS_DXGI_FORMAT_R16G16B16A16_FLOAT)
            else:
                return False
        elif typeName == 'TYPE_UNSIGNED_BYTE':
            if channels == 1:
                header10.dxgiFormat = UINT(DDSDxgiFormat.DDS_DXGI_FORMAT_R8_UNORM)
            elif channels == 2:
                header10.dxgiFormat = UINT(DDSDxgiFormat.DDS_DXGI_FORMAT_R8G8_UNORM)
            elif channels == 4:
                header10.dxgiFormat = UINT(DDSDxgiFormat.DDS_DXGI_FORMAT_R8G8B8A8_UNORM)
            else:
                return False
        else:
            return False
            
        header10.miscFlag = UINT(0)
        header10.miscFlags2 = UINT(0)
        header10.resourceDimension = UINT(DDSRescourceDimensions.DDS_RESOURCE_DIMENSION_TEXTURE2D)
        
    else: #no DX10 
        pass    #no implementation
            
    return True
        
def writeCustomDDS(path, width, height, channels, arraySize, data):
    """
    The function writes a dds file from the given parameters
    
    :param str path: the filepath for the new dds file
    :param int width: the width of the surface
    :param int height: the height of the surface
    :param int channels: 1 OR 2 OR 4
    :param int arraySize: 
    :param list data: customized data
    
    """
    # print("writeCustomDDS: path: {}, width: {}, height: {}, channels: {}, arraySize: {}".format(path,width, height, channels, arraySize))
    #build setup
    magicNumber = DWORD(0X20534444)    #magic number
    header = DDS_HEADER()           #size is 124 bytes
    header10 = DDS_HEADER_DXT10()
    #parameter
    if arraySize > 1:
        textureType = 'TEX_2D_ARRAY'
    else:
        textureType = 'TEX_2D'    
    typeName = 'TYPE_SIGNED_HALF'
    numMipMaps = 0
    formatName = 'UNKNOWN'
    
    if configureHeader(header,header10,height,width,numMipMaps,formatName,textureType,arraySize,typeName,channels):
        writeDDS(path,magicNumber,header,header10,data)
    else:
        print("header configuration failed")

if __name__ == "__main__":
    """ Test function """
    
    bdata = []
    for i in range(2160):
            bdata.append(DWORD(0X6FC2003C))     
    writeCustomDDS("C:\\Users\\dds_file.dds",30,12,4,3,bdata)
        