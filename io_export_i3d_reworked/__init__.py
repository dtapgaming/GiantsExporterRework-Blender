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

bl_info = {
    "name": "GIANTS I3D Exporter REWORKED",
    "author": "GIANTS Software | Dtap Gaming",
    "blender": (4, 3, 0),
    "version": ( 10, 0, 16 ),
    "location": "GIANTS I3D",
    "description": "GIANTS Utilities and Exporter Reworked for Blender 4.3+",
    "warning": "Designed for Blender 4.3 and above.",
    "wiki_url": "http://gdn.giants-software.com",
    "tracker_url": "https://discord.gg/NazY3trnnm",
    "category": "Game Engine",}

global DCC_PLATFORM
DCC_PLATFORM = "blender"

if "bpy" in locals():
    import importlib
    importlib.reload(i3d_ui)
    importlib.reload(dcc)
    importlib.reload(i3d_export)
    importlib.reload(i3d_globals)
    try:
        importlib.reload(updateChecker)
    except Exception:
        pass
else:
    from . import i3d_ui
    from . import dcc
    from . import i3d_export
    from . import i3d_globals
    from .helpers import updateChecker
import bpy
from .dcc.dccBlender import getFormattedNodeName


class I3D_MT_Menu( bpy.types.Menu ):
    """  GUI element in bottom left corner to open the GIANTS I3D Exporter """

    bl_label = "GIANTS I3D"
    bl_idname = "I3D_MT_Menu"

    def draw( self, context ):
        """pop up menu when clicked"""

        layout = self.layout
        layout.label( text = "v {0}".format(bl_info["version"]) )
        layout.operator( "i3d.menuexport" )

def draw_I3D_Menu( self, context ):
    """ Draw I3D Menu """

    self.layout.menu( I3D_MT_Menu.bl_idname )

def update_xml_config_id(self, context):
    if self.I3D_XMLconfigBool:
        self.I3D_XMLconfigID = getFormattedNodeName(self.name)
    else:
        self.I3D_XMLconfigID = ''

#-------------------------------------------------------------------------------
#   Register
#-------------------------------------------------------------------------------
def register():
    # TODO(jdellsperger): Why are these properties defined so radically diferent than all the
    # others? As far as I can tell, those are also "per node" properties and could be defined
    # in the same way as all the others...
    bpy.types.Object.I3D_XMLconfigBool = bpy.props.BoolProperty(default=False,
                                                                update=update_xml_config_id)
    bpy.types.Object.I3D_XMLconfigID = bpy.props.StringProperty(default='')
    bpy.types.EditBone.I3D_XMLconfigBool = bpy.props.BoolProperty(default=False,
                                                                  update=update_xml_config_id)
    bpy.types.EditBone.I3D_XMLconfigID = bpy.props.StringProperty(default='')
    i3d_globals.register()
    i3d_ui.register()
    updateChecker.register()
    bpy.utils.register_class( I3D_MT_Menu )
    bpy.types.STATUSBAR_HT_header.prepend(draw_I3D_Menu)


def unregister():
    bpy.types.STATUSBAR_HT_header.remove(draw_I3D_Menu)
    bpy.utils.unregister_class( I3D_MT_Menu )
    i3d_ui.unregister()
    updateChecker.unregister()
    i3d_globals.unregister()
    del bpy.types.Object.I3D_XMLconfigBool
    del bpy.types.Object.I3D_XMLconfigID
    del bpy.types.EditBone.I3D_XMLconfigBool
    del bpy.types.EditBone.I3D_XMLconfigID

if __name__ == "__main__":
    register()
