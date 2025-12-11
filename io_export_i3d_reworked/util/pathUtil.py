import os


class Error(Exception):
    """Base class for exceptions in this module."""
    pass


class InputError(Error):
    """Exception raised for errors in the input.

    Attributes:
        expression -- input expression in which the error occurred
        message -- explanation of the error
    """
    def __init__(self, expression, message):
        self.expression = expression
        self.message = message


def resolvePath(fullPath, referenceDirectory=None, targetDirectory=None):
    """
    Resolve a file or directory path.

    This version is tuned for the GIANTS FS25 Blender exporter and fixes the
    specific issue where an absolute Windows shader path like:

        C:\\Program Files (x86)\\Steam\\SteamApps\\common\\Farming Simulator 25\\data\\shaders\\placeableShader.xml

    would get turned into a broken path such as:

        C:/Users/Program Files (x86)/Steam/SteamApps/common/Farming Simulator 25/data/shaders/placeableShader.xml

    Behavior:
      - If referenceDirectory is given and fullPath is relative, it is joined.
      - If targetDirectory is given and the path is absolute, we **keep it
        absolute** instead of forcing it relative. This is the key fix.
      - Otherwise, we fall back to normal absolute/relative resolution.
    """

    if fullPath is None or fullPath == "":
        raise InputError("fullPath", "No path given")

    # Normalize slashes early
    fullPath = fullPath.replace("\\", os.sep).replace("/", os.sep)

    # ----------------------------------------------------------------------
    # Step 1: Build an absolute path using referenceDirectory if provided
    # ----------------------------------------------------------------------
    if referenceDirectory:
        referenceDirectory = referenceDirectory.replace("\\", os.sep).replace("/", os.sep)
        if not os.path.isabs(fullPath):
            absPath = os.path.normpath(os.path.join(referenceDirectory, fullPath))
        else:
            absPath = os.path.normpath(fullPath)
    else:
        # No referenceDirectory: interpret fullPath as absolute or relative
        absPath = os.path.abspath(fullPath)

    # ----------------------------------------------------------------------
    # Step 2: Handle targetDirectory (this is where the bug used to show up)
    # ----------------------------------------------------------------------
    if targetDirectory:
        targetDirectory = targetDirectory.replace("\\", os.sep).replace("/", os.sep)
        targetDirectory = os.path.abspath(targetDirectory)

        # 🔴 PATCH:
        # If absPath is already an absolute Windows path, do NOT try to make
        # it relative to targetDirectory. Just return the absolute path with
        # normalized separators.
        if os.path.isabs(absPath):
            return absPath.replace("\\", os.sep).replace("/", os.sep)

        # Fallback: if for some reason absPath is still not absolute, attempt
        # a relative path (this should be rare in this exporter).
        try:
            relPath = os.path.relpath(absPath, targetDirectory)
        except Exception:
            relPath = absPath

        return relPath.replace("\\", os.sep).replace("/", os.sep)

    # ----------------------------------------------------------------------
    # Step 3: No targetDirectory → just return absolute path
    # ----------------------------------------------------------------------
    return absPath.replace("\\", os.sep).replace("/", os.sep)


def getCanonicalPath(base, relative):
    """Return an absolute path for `relative` based on `base`."""
    if base is None:
        raise InputError("base", "base path is None")
    if relative is None:
        raise InputError("relative", "relative path is None")
    return os.path.abspath(os.path.join(base, relative))


def getPathWithoutFile(path):
    """Return the directory portion of a path (without the file name)."""
    path_norm = path.replace("\\", "/")
    try:
        last_sep = path_norm.rindex("/")
    except ValueError:
        raise InputError(path, "no / in path")
    return path_norm[:last_sep]


def makeRelativePath(fileLocation, targetPath):
    """
    Make a relative path for targetPath from fileLocation.

    This is a generic helper and is not heavily used in the FS25 exporter,
    but it is kept here for compatibility with older scripts.
    """

    fileLocation = fileLocation.replace("\\", "/")
    targetPath = targetPath.replace("\\", "/")

    # Different drive letters on Windows → cannot be made relative safely
    if (
        len(fileLocation) > 2 and len(targetPath) > 2 and
        fileLocation[1] == ":" and targetPath[1] == ":" and
        fileLocation[0].lower() != targetPath[0].lower()
    ):
        return targetPath

    try:
        commonPrefix = os.path.commonprefix([fileLocation, targetPath])
    except Exception as e:
        raise InputError(
            fileLocation + " | " + targetPath,
            "commonprefix() error: " + str(e)
        )

    fileRest = fileLocation[len(commonPrefix):].strip("/")
    targetRest = targetPath[len(commonPrefix):].strip("/")

    relativePath = ""
    if fileRest:
        for _ in fileRest.split("/"):
            relativePath += "../"

    if targetRest:
        relativePath += targetRest

    return relativePath


if __name__ == "__main__":
    print("pathUtil test")
    try:
        print("returned:", resolvePath("../shaders/vehicleShader.xml", None, None))
    except Exception as e:
        print("Error:", e)
