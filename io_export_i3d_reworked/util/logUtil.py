
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

class ActionLog:
    """ Structures the Info View Output displayed in blender """
    
    header = [({'INFO'}, "----------Action Log----------")]
    message = [] # example format: [({'INFO'},"test")]

    @classmethod
    def addMessage(cls,message,messageType = 'INFO'):
        """
        Add a message to the Action Log

        :param cls: ActionLog class
        :param message: message to display in the Info View 
        :param messageType: Describes the priority and format from the output: {'DEBUG', 'INFO', 'OPERATOR', 'PROPERTY', 'WARNING', 'ERROR', 
        'ERROR_INVALID_INPUT', 'ERROR_INVALID_CONTEXT', 'ERROR_OUT_OF_MEMORY'}, preferrably use INFO, WARNING
        """
        try:
            cls.message.append(({messageType},str(message)))
        except:
            cls.message.append(({messageType},"could not log message"))
    @classmethod
    def reset(cls):
        """ Resets the output buffer """
        
        cls.message = []

# bpy.app.debug_wm = True
# bpy.context.area.ui_type = 'INFO'
