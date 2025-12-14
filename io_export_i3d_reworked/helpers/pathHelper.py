import bpy


def getGamePath():
    addon = bpy.context.preferences.addons.get("io_export_i3d_reworked")
    if addon and hasattr(addon, "preferences") and getattr(addon.preferences, "game_install_path", ""):
        return addon.preferences.game_install_path
    return ""
