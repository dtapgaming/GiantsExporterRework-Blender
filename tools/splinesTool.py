
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
from ..dcc import dccBlender as dcc

class I3D_PT_splines( bpy.types.Panel ):
    """ GUI Panel for the GIANTS I3D TOOLS visible in the 3D Viewport """
    
    bl_idname       = "TOOLS_PT_Splines"
    bl_label        = "GIANTS Splines Tool"
    bl_space_type   = 'VIEW_3D'
    bl_region_type  = 'UI'
    bl_category     = "GIANTS I3D Exporter"
    
    def __getSplineLength(self,context):
        """ Update function to display active spline  length """
        m_length  = '???'
        try:
            m_obj = bpy.context.active_object
            if ( m_obj ):
                if ( 'CURVE' == m_obj.type ):
                    m_length = m_obj.data.splines.active.calc_length()
        except:
            pass
        return m_length

    def draw(self, context):
        layout = self.layout
        # ------------------
        box = layout.box()
        row = box.row()
        split = row.split(factor=0.4)
        col = split.column()
        col.label( text = " Spline Length : " )
        split = split.split()
        col = split.column()
        m_length = self.__getSplineLength(context)
        col.label( text = "{}".format( m_length ) )

class I3D_OT_splineToolPopUp(bpy.types.Operator):
    
    bl_label = "Splines Tool"
    bl_idname = "i3d.splinetoolpopup"
    state : bpy.props.IntProperty(name = "State", default = 0)
    
    def execute(self, context):
        if self.state == 0:
            try:
                bpy.utils.register_class(I3D_PT_splines)
                self.state = 1
            except:
                return {'CANCELLED'}
        elif self.state == 1:
            try:
                bpy.utils.unregister_class(I3D_PT_splines)
                self.state = 0
            except:
                return {'CANCELLED'}
        return {'FINISHED'}
   
def register():
    """ Register UI elements """
    
    bpy.utils.register_class(I3D_OT_splineToolPopUp)
    
def unregister():
    """ Unregister UI elements """ 
    
    bpy.utils.unregister_class(I3D_OT_splineToolPopUp)
    

