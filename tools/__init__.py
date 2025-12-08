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

import importlib

_MODULES = {
    '.motionPathTool': None, 
    '.motionPathObjectTool' : None,
    '.vehicleArrayTool.vehicleArrayTool' : None,
    '.vertexColorTool': None,
    '.splinesTool':None
}

for module in _MODULES.keys():
    try:
        _MODULES[module] = importlib.import_module(module,__name__)
        print("{} loaded".format(module))
    except ImportError as e:
        print("{} not available".format(module))
    # except Exception as e:
        # print(e)
        # print("something went wrong")



def registerTools():
    print("registerTools")
    for module in [v for v in _MODULES.values() if not(v is None)]:
        importlib.reload(module)
        try:
            module.register()
        except:
            print(f"Error: unable to register module {module}")
    
def unregisterTools():
    print("unregisterTools")
    for module in [v for v in _MODULES.values() if not(v is None)]:
        try:
            module.unregister()
        except:
            print(f"Error: unable to unregister module {module}")
 