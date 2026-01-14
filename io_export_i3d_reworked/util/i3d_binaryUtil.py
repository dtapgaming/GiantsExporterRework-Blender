import subprocess
import os


def _find_i3d_converter_exe() -> str:
    """Locate GIANTS' i3dConverter.exe.

    We ship i3dConverter.exe with this add-on in util/i3dConverter.exe.

    Fallback search (if missing):
      1) this add-on's util folder
      2) the GIANTS official exporter add-on (io_export_i3d) util folder

    Returns an absolute path, or "" if not found.
    """

    # 1) Legacy/local location (older installs)
    local = os.path.join(os.path.dirname(__file__), "i3dConverter.exe")
    if os.path.isfile(local):
        return local

    roots = []

    # 2) Add-on paths from addon_utils (preferred)
    try:
        import addon_utils  # type: ignore
        for base in getattr(addon_utils, "paths", lambda: [])() or []:
            if base:
                roots.append(os.path.join(base, "io_export_i3d"))
    except Exception:
        pass

    # 3) Common Blender add-ons directories
    try:
        import bpy  # type: ignore
        for base in [
            bpy.utils.user_resource('SCRIPTS', "addons"),
            bpy.utils.system_resource('SCRIPTS', "addons"),
        ]:
            if base:
                roots.append(os.path.join(base, "io_export_i3d"))
    except Exception:
        pass

    for root in roots:
        exe = os.path.join(root, "util", "i3dConverter.exe")
        if os.path.isfile(exe):
            return exe

    return ""

def create_binary_from_exe(file, gamePath):
    app_path = _find_i3d_converter_exe()
    if not app_path:
        return "i3dConverter.exe not found. Ensure util/i3dConverter.exe exists (reinstall the add-on), or install GIANTS official exporter add-on (io_export_i3d) which also provides util/i3dConverter.exe."
    input_params = ['-in', file, "-out", file]
    if(gamePath):
        input_params += ["-gamePath", gamePath]

    # out, err = subprocess.Popen([app_path]+input_params, stdout=subprocess.PIPE).communicate(b"input data that is passed to subprocess' stdin")
    out, err = subprocess.Popen([app_path]+input_params, stdout=subprocess.PIPE).communicate()
    out = out.decode("utf-8")
    out = out.splitlines()
    # print (out)   
    return out[-1:]

if(__name__=='__main__'):
    create_binary_from_exe()