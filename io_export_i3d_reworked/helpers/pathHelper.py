import bpy
import os


try:
    from ..util import i3d_directoryFinderUtil as dirf
except Exception:
    dirf = None


def _strip_wrapping_quotes(p):
    if p is None:
        return ""
    s = str(p).strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        s = s[1:-1].strip()
    return s

def _get_addon_prefs_addon():
    """Return the Addon entry from bpy.context.preferences.addons for this addon.

    Supports both classic add-on installs (key == 'io_export_i3d_reworked') and
    Blender extension installs where the key may be namespaced (e.g. 'bl_ext.user_default.io_export_i3d_reworked').
    """
    prefs = getattr(bpy.context, "preferences", None)
    if prefs is None:
        return None

    # Classic add-on key
    addon = prefs.addons.get("io_export_i3d_reworked")
    if addon is not None:
        return addon

    # Extension installs may namespace the module name
    try:
        for key in prefs.addons.keys():
            if key.endswith("io_export_i3d_reworked"):
                addon = prefs.addons.get(key)
                if addon is not None:
                    return addon
    except Exception:
        pass

    return None


def getGamePath():
    addon = _get_addon_prefs_addon()
    if addon and hasattr(addon, "preferences"):
        game_path = _strip_wrapping_quotes(getattr(addon.preferences, "game_install_path", ""))
        if game_path:
            return game_path
    return ""
def resolveGiantsPath(path, game_install_path=None):
    """Resolve GIANTS-style paths that begin with '$' against the FS install path.

    Examples:
      '$data/shared/...':   <FS PATH>/data/shared/...
      '$dataS/...':         <FS PATH>/dataS/...
      '$something/...':     <FS PATH>/something/...

    Handles paths where the stored FS path was accidentally set to the 'data' folder already
    by avoiding duplicate 'data' or 'dataS' segments.
    """
    if not path or "$" not in path:
        return path

    game_path = game_install_path if game_install_path is not None else getGamePath()
    game_path = _strip_wrapping_quotes(game_path)
    if not game_path:
        # If user didn't set the install path, try auto-detection on Windows.
        if dirf is not None:
            try:
                if dirf.isWindows():
                    game_path = _strip_wrapping_quotes(dirf.findFS22Path())
            except Exception:
                game_path = ""
    if not game_path:
        return ""

    # Expand Blender's path formatting (supports '//' etc.)
    try:
        game_path = bpy.path.abspath(game_path)
        game_path = _strip_wrapping_quotes(game_path)
    except Exception:
        pass

    game_path = str(game_path).strip().rstrip("/\\")
    if not game_path:
        return ""

    # Only support the common '$...' form
    if path.startswith("$"):
        rel = path[1:].lstrip("/\\")
        # Normalize separators in rel
        rel = rel.replace("/", os.sep).replace("\\", os.sep)

        # Avoid duplicate 'data' / 'dataS' if user pointed at the data folder
        first_segment = rel.split(os.sep, 1)[0] if rel else ""
        base = os.path.basename(game_path).lower()
        if first_segment and base == first_segment.lower():
            game_path = os.path.dirname(game_path)

        return os.path.normpath(os.path.join(game_path, rel))

    # Fallback: replace any '$' with '<game_path>/'
    return os.path.normpath(path.replace("$", game_path + os.sep))
