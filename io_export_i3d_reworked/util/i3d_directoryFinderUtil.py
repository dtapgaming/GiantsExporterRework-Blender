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

import errno
import os
import platform
import re

if platform.system() == "Windows":
    import winreg

def isWindows():
    """ Check if current platform is Windows"""

    return platform.system() == "Windows"


def _is_valid_fs25_install(path):
    """Validate a candidate FS25 install path by checking for vehicleShader.xml."""
    if not path:
        return False
    try:
        shader_xml = os.path.join(path, "data", "shaders", "vehicleShader.xml")
        return os.path.isdir(path) and os.path.isfile(shader_xml)
    except Exception:
        return False

def _get_steam_path_windows():
    """Try to locate Steam install path (Windows)."""
    try:
        # Prefer user-level SteamPath
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam_path = winreg.QueryValueEx(key, "SteamPath")[0]
            if steam_path and os.path.isdir(steam_path):
                return steam_path
    except Exception:
        pass

    # Common default install location
    try:
        pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        candidate = os.path.join(pf86, "Steam")
        if os.path.isdir(candidate):
            return candidate
    except Exception:
        pass

    return ""

def _parse_steam_libraryfolders_vdf(vdf_path):
    """Parse steamapps/libraryfolders.vdf and return a list of library root paths."""
    libs = []
    if not vdf_path or not os.path.isfile(vdf_path):
        return libs
    try:
        with open(vdf_path, "r", encoding="utf-8", errors="ignore") as f:
            data = f.read()
        # New/old VDF formats both contain lines: "path" "X:\SteamLibrary"
        for m in re.finditer(r'\"path\"\s*\"([^\"]+)\"', data):
            p = m.group(1).replace('\\\\', '\\')
            if p and os.path.isdir(p) and p not in libs:
                libs.append(p)
    except Exception:
        pass
    return libs

def _find_fs25_path_steam():
    """Steam fallback: scan steam library folders for Farming Simulator 25."""
    if platform.system() != "Windows":
        return ""
    steam_path = _get_steam_path_windows()
    if not steam_path:
        return ""
    vdf_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")

    libraries = [steam_path]
    libraries += _parse_steam_libraryfolders_vdf(vdf_path)

    for lib in libraries:
        candidate = os.path.join(lib, "steamapps", "common", "Farming Simulator 25")
        if _is_valid_fs25_install(candidate):
            return candidate

    return ""
def findFS19Path():
    """ Top level function to find the installation path of the FS19"""

    if platform.system() == "Windows":
        return _findFS19PathWindows()
    else:
        print("only supported on Windows")
        return ""

def _findFS19PathWindows():
    """ Returns the installation Path of the FS19 installation on Windows """

    path = ""
    proc_arch = os.environ['PROCESSOR_ARCHITECTURE'].lower()
    if 'PROCESSOR_ARCHITEW6432' in os.environ:
        proc_arch64 = os.environ['PROCESSOR_ARCHITEW6432'].lower()
        if proc_arch == 'x86' and not proc_arch64:
            arch_keys = {0}
        elif proc_arch == 'x86' or proc_arch == 'amd64':
            arch_keys = {winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY}
        else:
            raise Exception("Unhandled arch: %s" % proc_arch)
    else:
        if proc_arch == 'x86' or proc_arch == 'amd64':
            arch_keys = {winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY}
        else:
            raise Exception("Unhandled arch: %s" % proc_arch)

    for arch_key in arch_keys:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0, winreg.KEY_READ | arch_key)
        for i in range(0, winreg.QueryInfoKey(key)[0]):     #iterate over all subkeys
            skey_name = winreg.EnumKey(key, i)
            skey = winreg.OpenKey(key, skey_name)
            try:
                if("Farming Simulator" in winreg.QueryValueEx(skey, 'DisplayName')[0]):
                    path = winreg.QueryValueEx(skey, 'InstallLocation')[0]
            except OSError as e:
                if e.errno == errno.ENOENT:
                    # DisplayName doesn't exist in this skey
                    pass
            finally:
                skey.Close()
    return path

def findFS22Path():
    """ Top level function to find the installation path of the FS22"""

    if platform.system() == "Windows":
        return _findFS22PathWindows()
    else:
        print("only supported on Windows")
        return ""

def _findFS22PathWindows():
    """Returns the installation path of Farming Simulator on Windows.

    - Prefers Farming Simulator 25 (this addon targets FS25).
    - Falls back to FS22 if found.
    - Includes Steam library scanning fallback (libraryfolders.vdf) for FS25 installs.

    Validation: candidate path must contain data/shaders/vehicleShader.xml
    """

    # 1) Try registry uninstall entries (works for some non-Steam installs)
    def _registry_scan():
        try:
            proc_arch = os.environ.get('PROCESSOR_ARCHITECTURE', '').lower()
            arch_keys = set()

            if 'PROCESSOR_ARCHITEW6432' in os.environ:
                proc_arch64 = os.environ.get('PROCESSOR_ARCHITEW6432', '').lower()
                if proc_arch == 'x86' and not proc_arch64:
                    arch_keys = {0}
                elif proc_arch == 'x86' or proc_arch == 'amd64':
                    arch_keys = {winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY}
                else:
                    arch_keys = {0}
            else:
                if proc_arch == 'x86' or proc_arch == 'amd64':
                    arch_keys = {winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY}
                else:
                    arch_keys = {0}

            # Prefer FS25, then FS22
            candidates_fs25 = []
            candidates_fs22 = []

            for arch_key in arch_keys:
                try:
                    key = winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE,
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                        0,
                        winreg.KEY_READ | arch_key,
                    )
                except OSError:
                    continue

                try:
                    for i in range(0, winreg.QueryInfoKey(key)[0]):
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            skey = winreg.OpenKey(key, subkey_name)
                        except OSError:
                            continue

                        try:
                            dn = ""
                            try:
                                dn = winreg.QueryValueEx(skey, 'DisplayName')[0] or ""
                            except OSError:
                                dn = ""

                            if not dn:
                                continue

                            install = ""
                            try:
                                install = winreg.QueryValueEx(skey, 'InstallLocation')[0] or ""
                            except OSError:
                                install = ""

                            if not install:
                                continue

                            if "Farming Simulator 25" in dn and _is_valid_fs25_install(install):
                                candidates_fs25.append(install)
                            elif "Farming Simulator 22" in dn and _is_valid_fs25_install(install):
                                candidates_fs22.append(install)
                        finally:
                            try:
                                skey.Close()
                            except Exception:
                                pass
                finally:
                    try:
                        key.Close()
                    except Exception:
                        pass

            if candidates_fs25:
                return candidates_fs25[0]
            if candidates_fs22:
                return candidates_fs22[0]
        except Exception:
            pass
        return ""

    path = _registry_scan()
    if path:
        return path

    # 2) Steam fallback for FS25
    steam_path = _find_fs25_path_steam()
    if steam_path:
        return steam_path

    return ""
