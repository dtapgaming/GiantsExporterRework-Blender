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

if platform.system() == "Windows":
    import winreg

def isWindows():
    """ Check if current platform is Windows"""

    return platform.system() == "Windows"

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
    """ Returns the installation Path of the FS22 installation on Windows


    Currently there is no registry key, therefore the function is not working. (yet)
    """

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
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", 0, winreg.KEY_READ | arch_key)
        for i in range(0, winreg.QueryInfoKey(key)[0]):     #iterate over all subkeys
            skey_name = winreg.EnumKey(key, i)
            skey = winreg.OpenKey(key, skey_name)
            try:
                if("Farming Simulator 25" in winreg.QueryValueEx(skey, 'DisplayName')[0]):
                    path = winreg.QueryValueEx(skey, 'InstallLocation')[0]
            except OSError as e:
                if e.errno == errno.ENOENT:
                    # DisplayName doesn't exist in this skey
                    pass
            finally:
                skey.Close()
    return path