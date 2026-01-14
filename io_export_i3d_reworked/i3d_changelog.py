import bpy
import os
import textwrap
import subprocess
import hashlib
import time

# ---------------------------------------------------------------------------
# UI performance cache
#
# getHasChangedAnythingSinceLastView() is called from the main panel draw.
# Scrolling the sidebar triggers frequent redraws. Without caching, the
# function re-reads the changelog and re-hashes its contents on every draw,
# which can make the entire sidebar feel laggy.
#
# We cache the result and only recompute when either:
#  - the readme.txt changelog file changes, or
#  - the "shown hashes" file changes (user viewed the changelog), or
#  - a small time window has passed (for safety).
# ---------------------------------------------------------------------------

_I3D_CHANGELOG_CACHE = {
    "key": None,          # (readme_mtime, shown_mtime, readme_size)
    "value": False,       # cached bool
    "last_check": 0.0,    # time.time()
}

_I3D_CHANGELOG_MIN_RECHECK_SECONDS = 1.0


def _safe_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except Exception:
        return 0.0


def _safe_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except Exception:
        return 0

class ChangeLogOperator(bpy.types.Operator):
    bl_idname = "object.change_log_operator"
    bl_label = "GIANTS I3D Exporter  - Change Log"
    bl_description = "GIANTS I3D Exporter  - Change Log: exports using the current settings."

    myLines = []
    # there fit 150 characters in 800 pixels
    numMaxCharsPerLine = 150
    numMaxPixelsPerLine = 800

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        file_content = readChangeLog()
        lines = file_content.splitlines()
        newHashes = []
        oldHashes = loadOldHashes()
        self.myLines = []

        lineWidth = 20
        for line_number, line in enumerate(lines, start=1):
            isNew = False
            # Create an MD5 hash object
            md5_hash = hashlib.md5()
            # Update the hash object with the string
            md5_hash.update(line.encode('utf-8'))
            # Get the hexadecimal representation of the hash
            md5_hex = md5_hash.hexdigest()

            if (md5_hex not in oldHashes):
                isNew = True
            newHashes.append(md5_hex)

            # show only the first 30 lines
            if line_number > 30:
                continue

            # get reasonable dialog width
            lineWidth = max(len(line), lineWidth)
            wrapp = textwrap.TextWrapper(width=self.numMaxCharsPerLine)
            wList = wrapp.wrap(text=line)
            for text in wList:
                self.myLines.append((text, isNew))

        saveNewHashes(newHashes)
        lineWidth = min(self.numMaxPixelsPerLine, lineWidth*(self.numMaxPixelsPerLine/self.numMaxCharsPerLine))
        return context.window_manager.invoke_props_dialog(self, width=int(lineWidth))

    def draw(self, context):
        layout = self.layout
        for item in self.myLines:
            row = layout.row(align = True)
            row.alignment = 'EXPAND'
            row.alert = item[1]
            row.label(text=item[0])

        layout.operator("cl.open_changelog_operator", text="View complete Change Log...")

class OpenChangeLogOperator(bpy.types.Operator):
    bl_idname = "cl.open_changelog_operator"
    bl_label = "Operator Callback"
    bl_description = "Operator Callback: opens the related window or resource."

    def execute(self, context):
        try:
            fileName = getChangeLogFilename()
            # Open the file with the default application
            subprocess.Popen(['start', '', fileName], shell=True)
        except Exception as e:
            self.report({'ERROR'}, f"Error opening file: {e}")
        return {'FINISHED'}

def getChangeLogFilename():
    # Get the directory of the script file
    script_directory = os.path.dirname(__file__)

    # Construct the path to the text file
    return os.path.join(script_directory, "readme.txt")

def getShownChangeLogFileName():
    # Get the user's AppData directory path
    appdata_dir = os.getenv('APPDATA')
    if not appdata_dir:
        raise RuntimeError("Could not find AppData directory")
    appdata_dir += "\\Giants"
    if not os.path.exists(appdata_dir):
        os.makedirs(appdata_dir)
    return os.path.join(appdata_dir, "GiantsBlenderExporter.properties")

def saveNewHashes(content):
    with open(getShownChangeLogFileName(), 'w') as file:
        for fileHash in content:
            file.write(fileHash + "\n")

def loadOldHashes():
    """Return a set of previously-seen line hashes."""
    try:
        with open(getShownChangeLogFileName(), 'r') as file:
            file_content = file.read()
        # Store as a set for fast membership checks.
        return {h.strip() for h in file_content.splitlines() if h.strip()}
    except IOError:
        return set()

def readChangeLog():
    try:
        text_file_path = getChangeLogFilename()
        with open(text_file_path, 'r') as file:
            return file.read()
    except IOError:
        return ""

def getHasChangedAnythingSinceLastView():
    """Cheap check used by the UI draw to decide whether to auto-show changelog.

    IMPORTANT: This function is called *very often* during panel redraw (scrolling),
    so it must avoid file IO and hashing unless something actually changed.
    """

    # Build cache key from both the changelog file and the "shown hashes" file.
    now = time.time()
    try:
        readme_path = getChangeLogFilename()
        shown_path = getShownChangeLogFileName()
    except Exception:
        # If we can't resolve paths, fail closed (no popup spam).
        return False

    key = (
        _safe_mtime(readme_path), _safe_size(readme_path),
        _safe_mtime(shown_path),  _safe_size(shown_path),
    )

    cached_key = _I3D_CHANGELOG_CACHE.get("key")
    if cached_key == key and (now - _I3D_CHANGELOG_CACHE.get("last_check", 0.0)) < _I3D_CHANGELOG_MIN_RECHECK_SECONDS:
        return bool(_I3D_CHANGELOG_CACHE.get("value", False))

    # If nothing changed, just return cached value.
    if cached_key == key:
        _I3D_CHANGELOG_CACHE["last_check"] = now
        return bool(_I3D_CHANGELOG_CACHE.get("value", False))

    # Recompute only when key changes.
    file_content = readChangeLog()
    if not file_content:
        _I3D_CHANGELOG_CACHE.update({"key": key, "value": False, "last_check": now})
        return False

    lines = file_content.splitlines()
    old_hashes = loadOldHashes()
    changed = False
    for line in lines:
        md5_hex = hashlib.md5(line.encode('utf-8')).hexdigest()
        if md5_hex not in old_hashes:
            changed = True
            break

    _I3D_CHANGELOG_CACHE.update({"key": key, "value": changed, "last_check": now})
    return changed

def register():
    bpy.utils.register_class(ChangeLogOperator)
    bpy.utils.register_class(OpenChangeLogOperator)
def unregister():
    bpy.utils.unregister_class(ChangeLogOperator)
    bpy.utils.unregister_class(OpenChangeLogOperator)
