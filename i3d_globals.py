#-------------------------------------------------------------------------------
#   Global variables and methods
#-------------------------------------------------------------------------------
import time
from .util import logUtil

g_meshCache = {}

#-------------------------------------------------------------------------------
#   Debugging Profiling
#-------------------------------------------------------------------------------
g_logPerformance = True
g_logPerformanceStartTime = None

def I3DLogPerformanceInit():
    """ inits start time """
    global g_logPerformanceStartTime
    g_logPerformanceStartTime = time.time()

def I3DLogPerformance(text):
    """ Prints time elapsed """
    global g_logPerformanceStartTime
    if g_logPerformanceStartTime is not None:
        time_now = time.time()
        #dcc.UIShowError('time elapsed {0:.2f} seconds at '.format(time_now - g_logPerformanceStartTime) + text)
        logUtil.ActionLog.addMessage('time elapsed {0:.2f} seconds at '.format(time_now - g_logPerformanceStartTime) + text, messageType = 'ERROR')

import bpy

import bpy

class I3DExporterAddonPreferences(bpy.types.AddonPreferences):
    """Addon preferences for GIANTS I3D Exporter.
    Stores the global Farming Simulator installation directory."""
    bl_idname = "io_export_i3d_10_0_11"

    game_install_path: bpy.props.StringProperty(
        name="FS25 Game Path",
        description="Path to the Farming Simulator 25 game folder",
        default="",
        subtype='DIR_PATH',
    )

    def draw(self, context):
        layout = self.layout

        layout.label(text="Farming Simulator 25 Game Path")

        # =========================
        # Highlight in RED if empty
        # =========================
        if not self.game_install_path:
            box = layout.box()
            box.alert = True  # red warning style box
            col = box.column()
            col.label(text="⚠  Farming Simulator 25 Directory is EMPTY  ⚠", icon='ERROR')
            col.prop(self, "game_install_path", text="")
        else:
            # Normal field (not red)
            layout.prop(self, "game_install_path")



def register():
    bpy.utils.register_class(I3DExporterAddonPreferences)

def unregister():
    bpy.utils.unregister_class(I3DExporterAddonPreferences)


# to profile with internal tools
# import cProfile, pstats, io
# from pstats import SortKey
#     pr = cProfile.Profile()
#     pr.enable()
#     # execute code to profile
#     pr.disable()
#     s = io.StringIO()
#     sortby = SortKey.CUMULATIVE
#     ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
#     ps.print_stats()
#     dcc.UIShowError(s.getvalue())

# how to load and use a c++ library
# # install msgpack
# import ensurepip
# ensurepip.bootstrap()

# import subprocess
# import sys

# try:
#     #subprocess.check_call([bpy.app.binary_path_python, "-m", "ensurepip", "--user"])
#     subprocess.check_call([sys.executable, "-m", "ensurepip", "--user"])
# except subprocess.CalledProcessError as e:
#     pass

# try:
#     #subprocess.check_call([bpy.app.binary_path_python, "-m", "pip", "install", "msgpack"])
#     subprocess.check_call([sys.executable, "-m", "pip", "install", "msgpack"])
# except subprocess.CalledProcessError as e:
#     pass

#import sys
#sys.path.append("c:/users/nicolas wrobel/appdata/roaming/python/python310/site-packages")
