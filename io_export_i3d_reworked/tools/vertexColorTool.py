
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
import bmesh
import math
from ..dcc import dccBlender as dcc

COLOR_DICT = {
    'RED' : [0.65,0.055,0.074,1.0],
    'ORANGE': [0.569,0.286,0.161,1.0],
    'WHITE': [0.3,0.3,0.3,1.0]
}

class I3D_PT_vertexColor( bpy.types.Panel ):
    """ GUI Panel for the GIANTS I3D TOOLS visible in the 3D Viewport """
    
    bl_idname       = "TOOLS_PT_VertexColor"
    bl_label        = "GIANTS Vertex Color Tool"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GIANTS I3D Exporter"

    # keep name of the active color_layer 
    # and use it in different places 
    c_activeColorLayerName = None
    # selected vertex index 
    c_activeVertexIndex = None
    c_activeRGBA = None
    
    def __getActive_ColorLayerName_VertexIndex_RGBA(self,context):
        """ Update function to display active vertex index """
        m_colorLayerName  = '???'
        m_activeVertexIndex  = '???'
        m_activeRGBA = '???'
        I3D_PT_vertexColor.c_activeColorLayerName = None
        I3D_PT_vertexColor.c_activeVertexIndex = None
        I3D_PT_vertexColor.c_activeRGBA = None
        try:
            m_activeColor = bpy.context.active_object.data.color_attributes.active_color
            if (m_activeColor):
                m_colorLayerName = m_activeColor.name
                I3D_PT_vertexColor.c_activeColorLayerName = m_colorLayerName
        except:
            pass
            #print("Can't get bpy.context.active_object.data.color_attributes.active_color")
        try:
            '''
                https://docs.blender.org/api/current/bmesh.html
                you need create instance of this mesh in the memory 
                and then you can access the data 
                otherwise direct access is not always reliable
            '''
            # lest use dynamically constructed bmesh
            if ('EDIT_MESH' == bpy.context.mode):
                # create in edit mode this way
                # otherwise do not work correctly
                m_bm = bmesh.from_edit_mesh(bpy.context.active_object.data)
            else:
                m_bm = bmesh.new()
                m_bm.from_mesh(bpy.context.active_object.data)
            # blender do not have list of selected vertices
            # blender only keep state of the vertex in the mesh in vertex.select 
            # so we need iterate over all verts
            m_selected_verts = [v for v in m_bm.verts if v.select]
            # check if we selected anything
            if (len(m_selected_verts)>0):
                m_activeVertexIndex = m_selected_verts[0].index
                I3D_PT_vertexColor.c_activeVertexIndex = m_activeVertexIndex
                # check if color layer exists
                if ( I3D_PT_vertexColor.c_activeColorLayerName ):
                    m_color = getColorByVertIndex( m_bm, I3D_PT_vertexColor.c_activeColorLayerName, m_activeVertexIndex )
                    # check if we get anything
                    if ( m_color ):
                        I3D_PT_vertexColor.c_activeRGBA = m_color
                        m_activeRGBA = "{} {} {} {}".format(round(m_color[0],3),round(m_color[1],3),round(m_color[2],3),round(m_color[3],3))
        except:
            pass
            #print("Can't make bmesh")
        return m_colorLayerName, m_activeVertexIndex, m_activeRGBA

    def draw(self, context):
        layout = self.layout
        # ------------------
        row = layout.row()
        row.operator('tools.vertexcolorview',text = 'Toggle Vertex Color Mode')
        # ------------------
        box = layout.box()
        row = box.row()
        split = row.split(factor=0.4)
        col = split.column()
        col.label( text = " Color Layer : " )
        col.label( text = " Vertex Index : " )
        col.label( text = " RGBA : " )
        split = split.split()
        col = split.column()
        m_colorLayerName, m_activeVertexIndex, m_activeRGBA = self.__getActive_ColorLayerName_VertexIndex_RGBA(context)
        col.label( text = "{}".format( m_colorLayerName ) )
        col.label( text = "{}".format( m_activeVertexIndex) )
        col.label( text = "{}".format( m_activeRGBA ) )
        row = box.row()
        row.prop(context.scene.TOOLS_UIVertexColor,'activeVertexIndex')
        row = box.row()
        split = row.split(factor=0.6)
        col = split.column()
        col.prop(context.scene.TOOLS_UIVertexColor,'colorR')
        col.prop(context.scene.TOOLS_UIVertexColor,'colorG')
        col.prop(context.scene.TOOLS_UIVertexColor,'colorB')
        col.prop(context.scene.TOOLS_UIVertexColor,'colorA')
        split = split.split()
        col = split.column()
        col.operator("tools.vertexcoloradjust",text="Get R").state = 1
        col.operator("tools.vertexcoloradjust",text="Get G").state = 2
        col.operator("tools.vertexcoloradjust",text="Get B").state = 3
        col.operator("tools.vertexcoloradjust",text="Get A").state = 4
        split = split.split()
        col = split.column()
        col.operator("tools.vertexcoloradjust",text="Set R").state = 6
        col.operator("tools.vertexcoloradjust",text="Set G").state = 7
        col.operator("tools.vertexcoloradjust",text="Set B").state = 8
        col.operator("tools.vertexcoloradjust",text="Set A").state = 9
        row = box.row()
        row.operator("tools.vertexcoloradjust",text="Get RGBA").state = 0
        row.operator("tools.vertexcoloradjust",text="Set RGBA").state = 5
        # ------------------
        row = layout.row()
        row.prop(context.scene.TOOLS_UIVertexColor,'colorEnum', expand=True)
        row = layout.row()
        row.operator("tools.vertexcolorpopupactionbutton",text="Color Mesh").state = 0
        row.operator("tools.vertexcolorpopupactionbutton",text="Color Selected Faces").state = 1
        row.operator("tools.vertexcolorpopupactionbutton",text="Color Selected Vertices").state = 2

class TOOLS_UIVertexColor( bpy.types.PropertyGroup ):   

    activeVertexIndex    : bpy.props.IntProperty( name = "Active Vertex Index", default = 0, min = 0 )
    colorR : bpy.props.FloatProperty ( name = "R", default = 1.0 , min = 0.0, max = 1.0, precision = 3 )
    colorG : bpy.props.FloatProperty ( name = "G", default = 1.0 , min = 0.0, max = 1.0, precision = 3 )
    colorB : bpy.props.FloatProperty ( name = "B", default = 1.0 , min = 0.0, max = 1.0, precision = 3 )
    colorA : bpy.props.FloatProperty ( name = "A", default = 1.0 , min = 0.0, max = 1.0, precision = 3 )
    colorEnum  : bpy.props.EnumProperty ( items = [("RED", "Red", str(COLOR_DICT['RED'])),("ORANGE","Orange", str(COLOR_DICT['ORANGE'])),("WHITE","White", str(COLOR_DICT['WHITE']))], name = "Color Enum")
    previous_mode : bpy.props.StringProperty (name="previous Mode",default = 'MATERIAL')#bpy.context.space_data.shading.color_type == 'VERTEX')

    @classmethod
    def register( cls ):
        bpy.types.Scene.TOOLS_UIVertexColor = bpy.props.PointerProperty(
            name = "Tools UI Vertex Color",
            type =  cls,
            description = "Tools UI Vertex Color"
        )
    @classmethod
    def unregister( cls ):
        if bpy.context.scene.get( 'TOOLS_UIVertexColor' ):  del bpy.context.scene[ 'TOOLS_UIVertexColor' ]
        try:    del bpy.types.Scene.TOOLS_UIVertexColor
        except: pass
        
class TOOLS_OT_vertexColorAdjust(bpy.types.Operator):
    
    bl_label = "Vertex Color Adjust"
    bl_idname = "tools.vertexcoloradjust"
    bl_options = {'UNDO'}
    state : bpy.props.IntProperty( name = "State", default = 0 )
    
    def execute(self, context):
        m_getStates = [0,1,2,3,4]
        m_setStates = [5,6,7,8,9]
        # ----------------------
        if self.state in m_getStates:
            m_activeVertexIndex = 0
            m_color = None
            # if anything slected 
            try:
                if ('EDIT_MESH' == bpy.context.mode):
                    m_bm = bmesh.from_edit_mesh(bpy.context.active_object.data)
                else:
                    m_bm = bmesh.new()
                    m_bm.from_mesh(bpy.context.active_object.data)
                m_selected_verts = [v for v in m_bm.verts if v.select]
                if (len(m_selected_verts)>0):
                    m_activeVertexIndex = m_selected_verts[0].index
                    if ( I3D_PT_vertexColor.c_activeColorLayerName ):
                        m_color = getColorByVertIndex( m_bm, I3D_PT_vertexColor.c_activeColorLayerName, m_activeVertexIndex )
                #print('vtx index: {}'.format(m_activeVertexIndex))
                #print('vtx color: {}'.format(m_color))
            except:
                pass
            bpy.context.scene.TOOLS_UIVertexColor.activeVertexIndex = m_activeVertexIndex
            if   0 == self.state:
                if (m_color):
                    bpy.context.scene.TOOLS_UIVertexColor.colorR = round( m_color[0], 3 )
                    bpy.context.scene.TOOLS_UIVertexColor.colorG = round( m_color[1], 3 )
                    bpy.context.scene.TOOLS_UIVertexColor.colorB = round( m_color[2], 3 )
                    bpy.context.scene.TOOLS_UIVertexColor.colorA = round( m_color[3], 3 )
                else:
                    return {'CANCELLED'}
            elif 1 == self.state:
                if (m_color):
                    bpy.context.scene.TOOLS_UIVertexColor.colorR = round( m_color[0], 3 )
                else:
                    return {'CANCELLED'}
            elif 2 == self.state:
                if (m_color):
                    bpy.context.scene.TOOLS_UIVertexColor.colorG = round( m_color[1], 3 )
                else:
                    return {'CANCELLED'}
            elif 3 == self.state:
                if (m_color):
                    bpy.context.scene.TOOLS_UIVertexColor.colorB = round( m_color[2], 3 )
                else:
                    return {'CANCELLED'}
            elif 4 == self.state:
                if (m_color):
                    bpy.context.scene.TOOLS_UIVertexColor.colorA = round( m_color[3], 3 )
                else:
                    return {'CANCELLED'}
            else:
                return {'CANCELLED'}
        # ----------------------
        if self.state in m_setStates:
            m_oldmode = bpy.context.active_object.mode
            m_obj = bpy.context.active_object
            if (m_obj):
                # set to Edit mode 
                bpy.ops.object.mode_set(mode='EDIT')
                m_bm = bmesh.from_edit_mesh(m_obj.data)
                m_selectedVerts = [v for v in m_bm.verts if v.select]
                # check active Color Layer
                if ( I3D_PT_vertexColor.c_activeColorLayerName ):
                    m_color = ( bpy.context.scene.TOOLS_UIVertexColor.colorR, 
                                bpy.context.scene.TOOLS_UIVertexColor.colorG, 
                                bpy.context.scene.TOOLS_UIVertexColor.colorB, 
                                bpy.context.scene.TOOLS_UIVertexColor.colorA )
                    if   5 == self.state:
                        setColorByVertIndex( m_bm, I3D_PT_vertexColor.c_activeColorLayerName, m_selectedVerts, m_color )
                    elif 6 == self.state:
                        setColorByVertIndex( m_bm, I3D_PT_vertexColor.c_activeColorLayerName, m_selectedVerts, m_color, m_mode = 'r' )
                    elif 7 == self.state:
                        setColorByVertIndex( m_bm, I3D_PT_vertexColor.c_activeColorLayerName, m_selectedVerts, m_color, m_mode = 'g' )
                    elif 8 == self.state:
                        setColorByVertIndex( m_bm, I3D_PT_vertexColor.c_activeColorLayerName, m_selectedVerts, m_color, m_mode = 'b' )
                    elif 9 == self.state:
                        setColorByVertIndex( m_bm, I3D_PT_vertexColor.c_activeColorLayerName, m_selectedVerts, m_color, m_mode = 'a' )
                    # need to refresh
                    bpy.ops.object.mode_set(mode='OBJECT')
                # set back other mode
            bpy.ops.object.mode_set(mode=m_oldmode)
        return {'FINISHED'}

def getColorByVertIndex( m_bm, m_layer_name, m_index ):
    # 'POINT' color stored in vertices 
    m_color_layer = None
    # byte color
    if m_layer_name in m_bm.verts.layers.color.keys(): 
        # load BMLayerItem 
        m_color_layer = m_bm.verts.layers.color[ m_layer_name ]
    # float color
    if m_layer_name in m_bm.verts.layers.float_color.keys():
        m_color_layer = m_bm.verts.layers.float_color[ m_layer_name ]
    if (m_color_layer):
        # iterate over all vertices
        for m_vert in m_bm.verts:
            if (m_index == m_vert.index):
                # get the color and convert to tuple
                m_color = m_vert[m_color_layer][:]
                return m_color
    # 'CORNER' color stored in loops 
    if m_layer_name in m_bm.loops.layers.float_color.keys():
        m_color_layer = m_bm.loops.layers.float_color[ m_layer_name ]
    if m_layer_name in m_bm.loops.layers.color.keys():
        m_color_layer = m_bm.loops.layers.color[ m_layer_name ]
    if (m_color_layer):
        # iterate over all face loops
        for m_face in m_bm.faces:
            for m_loop in m_face.loops:
                if (m_index == m_loop.vert.index):
                    # get the color and convert to tuple
                    m_color = m_loop[m_color_layer][:]
                    return m_color
    return None

def setColorByVertIndex( m_bm, m_layer_name, m_selectedVerts, m_color, m_mode = 'rgba' ):
    # set colors can be performed only with bmesh.from_edit_mesh
    # which can be created only in Edit mode
    # 'POINT' color stored in vertices 
    m_color_layer = None
    # byte color
    if m_layer_name in m_bm.verts.layers.color.keys(): 
        # load BMLayerItem 
        m_color_layer = m_bm.verts.layers.color[ m_layer_name ]
    # float color
    if m_layer_name in m_bm.verts.layers.float_color.keys():
        m_color_layer = m_bm.verts.layers.float_color[ m_layer_name ]
    if (m_color_layer):
        # iterate over all vertices
        for m_vert in m_bm.verts:
            for m_selVtx in m_selectedVerts:
                if ( m_selVtx.index == m_vert.index ):
                    # set the color
                    if   'r' == m_mode:
                        m_vert[m_color_layer].x = m_color[0]
                    elif 'g' == m_mode:
                        m_vert[m_color_layer].y = m_color[1]
                    elif 'b' == m_mode:
                        m_vert[m_color_layer].z = m_color[2]
                    elif 'a' == m_mode:
                        m_vert[m_color_layer].w = m_color[3]
                    else:
                        m_vert[m_color_layer].x = m_color[0]
                        m_vert[m_color_layer].y = m_color[1]
                        m_vert[m_color_layer].z = m_color[2]
                        m_vert[m_color_layer].w = m_color[3]
        return True
    m_color_layer = None
    # 'CORNER' color stored in loops 
    if m_layer_name in m_bm.loops.layers.float_color.keys():
        m_color_layer = m_bm.loops.layers.float_color[ m_layer_name ]
    if m_layer_name in m_bm.loops.layers.color.keys():
        m_color_layer = m_bm.loops.layers.color[ m_layer_name ]
    if (m_color_layer):
        # iterate over all face loops
        for m_face in m_bm.faces:
            for m_loop in m_face.loops:
                for m_selVtx in m_selectedVerts:
                    if ( m_selVtx.index == m_loop.vert.index ):
                        # set the color
                        if   'r' == m_mode:
                            m_loop[m_color_layer].x = m_color[0]
                        elif 'g' == m_mode:
                            m_loop[m_color_layer].y = m_color[1]
                        elif 'b' == m_mode:
                            m_loop[m_color_layer].z = m_color[2]
                        elif 'a' == m_mode:
                            m_loop[m_color_layer].w = m_color[3]
                        else:
                            m_loop[m_color_layer].x = m_color[0]
                            m_loop[m_color_layer].y = m_color[1]
                            m_loop[m_color_layer].z = m_color[2]
                            m_loop[m_color_layer].w = m_color[3]
        return True
    return None

class I3D_OT_vertexColorPopUp(bpy.types.Operator):
    
    bl_label = "Vertex Color"
    bl_idname = "i3d.vertexcolorpopup"
    state : bpy.props.IntProperty(name = "State", default = 0)
    
    def execute(self, context):
        if self.state == 0:
            try:
                bpy.utils.register_class(I3D_PT_vertexColor)
                context.scene.TOOLS_UIVertexColor.previous_mode = bpy.context.space_data.shading.color_type
                if context.scene.TOOLS_UIVertexColor.previous_mode == 'VERTEX':
                    context.scene.TOOLS_UIVertexColor.previous_mode = 'MATERIAL'
                self.state = 1
            except:
                return {'CANCELLED'}
        elif self.state == 1:
            try:
                bpy.utils.unregister_class(I3D_PT_vertexColor)
                self.state = 0
            except:
                return {'CANCELLED'}
        return {'FINISHED'}

class TOOLS_OT_vertexColorView(bpy.types.Operator):
    
    bl_label = "Vertex Color Toggle"
    bl_idname = "tools.vertexcolorview"
    previous_mode = 'MATERIAL' #bpy.props.StringProperty(name='MATERIAL')
    
    def execute(self, context):
        # context.scene.TOOLS_UIVertexColor.hasVertexColorMode = not context.scene.TOOLS_UIVertexColor.hasVertexColorMode
        hasVertexColorMode = bpy.context.space_data.shading.color_type == 'VERTEX'
        if not hasVertexColorMode:
            context.scene.TOOLS_UIVertexColor.previous_mode = bpy.context.space_data.shading.color_type
            bpy.context.space_data.shading.color_type = 'VERTEX'
        else:
            bpy.context.space_data.shading.color_type =  context.scene.TOOLS_UIVertexColor.previous_mode 
        return {'FINISHED'}


class TOOLS_OT_vertexColorPopUpActionButton(bpy.types.Operator):
    
    bl_label = "Action Button"
    bl_idname = "tools.vertexcolorpopupactionbutton"
    state : bpy.props.IntProperty(name = "State", default=0)

    def execute(self,context):  
       
        # self.report({'INFO'},str(self.state))
        if self.state == 0:     #all
            for obj in context.selected_objects:
                if len(obj.data.vertex_colors) == 0:
                    obj.data.vertex_colors.new(name = 'Col')    #default name
                layer = obj.data.vertex_colors[0]
                for vert in layer.data:
                    vert.color = COLOR_DICT[context.scene.TOOLS_UIVertexColor.colorEnum]
        elif self.state == 1:   #faces
            mode = bpy.context.active_object.mode
            oldmode = mode
            obj = bpy.context.edit_object
            if obj is None:
                return {'CANCELLED'}
            if len(obj.data.vertex_colors) == 0:
                obj.data.vertex_colors.new(name = 'Col')    #default name
            if not obj:
                return {'CANCELLED'}
            mesh = obj.data
            bm = bmesh.from_edit_mesh(mesh)
            # list of selected faces
            selfaces = [f for f in bm.faces if f.select]
            if selfaces:
                for face in selfaces:
                    for  loop in face.loops:
                        loop[bm.loops.layers.color[0]] = COLOR_DICT[context.scene.TOOLS_UIVertexColor.colorEnum]
                bpy.ops.object.mode_set(mode='OBJECT')
                # bm.to_mesh(obj.data)
                bpy.ops.object.mode_set(mode=oldmode)
            else:
                return {'CANCELLED'}
                
        elif self.state == 2:   #vertices
            mode = bpy.context.active_object.mode
            oldmode = mode
            obj = bpy.context.edit_object
            if obj is None:
                return {'CANCELLED'}
            if len(obj.data.vertex_colors) == 0:
                obj.data.vertex_colors.new(name = 'Col')    #default name
            if not obj:
                return {'CANCELLED'}
            mesh = obj.data
            bm = bmesh.from_edit_mesh(mesh)
            # list of selected vertices
            selverts = [f for f in bm.verts if f.select]
            if selverts:
                for face in bm.faces:
                    for loop in face.loops:
                        if loop.vert in selverts:
                            loop[bm.loops.layers.color[0]] = COLOR_DICT[context.scene.TOOLS_UIVertexColor.colorEnum]
                bpy.ops.object.mode_set(mode='OBJECT')
                # bm.to_mesh(obj.data)
                bpy.ops.object.mode_set(mode=oldmode)
            else:
                return {'CANCELLED'}

        return {'FINISHED'}
   
def register():
    """ Register UI elements """
    
    bpy.utils.register_class(TOOLS_UIVertexColor)
    bpy.utils.register_class(I3D_OT_vertexColorPopUp)
    bpy.utils.register_class(TOOLS_OT_vertexColorPopUpActionButton)
    bpy.utils.register_class(TOOLS_OT_vertexColorView)
    bpy.utils.register_class(TOOLS_OT_vertexColorAdjust)

    
def unregister():
    """ Unregister UI elements """    
    
    bpy.utils.unregister_class(TOOLS_OT_vertexColorView)
    bpy.utils.unregister_class(TOOLS_OT_vertexColorPopUpActionButton)
    bpy.utils.unregister_class(I3D_OT_vertexColorPopUp)
    bpy.utils.unregister_class(TOOLS_OT_vertexColorAdjust)
    bpy.utils.unregister_class(TOOLS_UIVertexColor)
    

