import bpy
import os
import textwrap
import subprocess
import hashlib

class ChangeLogOperator(bpy.types.Operator):
    bl_idname = "object.change_log_operator"
    bl_label = "GIANTS I3D Exporter  - Change Log"

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
    return os.path.join(script_directory, "ChangeLog.txt")

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
    try:
        with open(getShownChangeLogFileName(), 'r') as file:
            file_content = file.read()
        return file_content
    except IOError:
        return []

def readChangeLog():
    try:
        text_file_path = getChangeLogFilename()
        with open(text_file_path, 'r') as file:
            return file.read()
    except IOError:
        return ""

def getHasChangedAnythingSinceLastView():
    file_content = readChangeLog()
    if not file_content:
        return False
    lines = file_content.splitlines()
    oldHashes = loadOldHashes()
    for line_number, line in enumerate(lines, start=1):
        # Create an MD5 hash object
        md5_hash = hashlib.md5()
        # Update the hash object with the string
        md5_hash.update(line.encode('utf-8'))
        # Get the hexadecimal representation of the hash
        md5_hex = md5_hash.hexdigest()

        if (md5_hex not in oldHashes):
            return True
    return False

def register():
    bpy.utils.register_class(ChangeLogOperator)
    bpy.utils.register_class(OpenChangeLogOperator)
def unregister():
    bpy.utils.unregister_class(ChangeLogOperator)
    bpy.utils.unregister_class(OpenChangeLogOperator)
