""" This util module contains the extra code needed to access the active object of a blender file.
The ctypes part is necessary to properly list selected hidden objects from the outliner """

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

import bpy, bmesh
from ctypes import c_int, c_float, c_void_p, c_short, \
    c_char, c_char_p, c_uint, POINTER, Structure
import re


root = None
version_ctypes_interface = bpy.app.version[:2]


def idcode(id):
    return sum(j << 8 * i for i, j in enumerate(id.encode()))

ID_OB = idcode("OB")  # bpy.types.Object
ID_LAYERCOLL = 0

"""
selected hidden object C wrapper as workaround for missing API
https://github.com/K-410/blender-scripts/blob/master/2.8/toggle_hide.py
"""
def listbase(ctype=None):
    ptr = POINTER(ctype)
    name = getattr(ctype, "__name__", "Generic")
    fields = {"_fields_": (("first", ptr), ("last", ptr))}
    return type(f"ListBase_{name}", (Structure,), fields)

def fproperty(funcs, property=property):
    return property(*funcs())

def _dyn_entry(name, ctyp, predicate):
    """Insert a Structure._fields_ entry based on predicate. Making it
    easier to add version-specific changes."""
    if predicate:
        return (name, ctyp),
    return ()

class View2D(Structure):
    """ source/blender/makesdna/DNA_view2d_types.h """

    _fields_ = (
        ("tot", c_float * 4),
        ("cur", c_float * 4),
        ("vert", c_int * 4),
        ("hor", c_int * 4),
        ("mask", c_int * 4),
        ("min", c_float * 2),
        ("max", c_float * 2),
        ("minzoom", c_float),
        ("maxzoom", c_float),
        ("scroll", c_short),
        ("scroll_ui", c_short),
        ("keeptot", c_short),
        ("keepzoom", c_short),
        ("keepofs", c_short),
        ("flag", c_short),
        ("align", c_short),
        ("winx", c_short),
        ("winy", c_short),
        ("oldwinx", c_short),
        ("oldwiny", c_short),
        ("around", c_short),
        *_dyn_entry("tab_offset", POINTER(c_float), version_ctypes_interface == (2, 83)),
        *_dyn_entry("tab_num", c_int, version_ctypes_interface == (2, 83)),
        *_dyn_entry("tab_cur", c_int, version_ctypes_interface == (2, 83)),
        ("alpha_vert", c_char),
        ("alpha_hor", c_char),
        *_dyn_entry("_pad", c_char * 6, version_ctypes_interface == (2, 83)),
        ("sms", c_void_p),
        ("smooth_timer", c_void_p),
    )

class TreeStoreElem(Structure):
    _fields_ = (
        ("type", c_short),
        ("nr", c_short),
        ("flag", c_short))

class TreeElement(Structure):
    _object = None
    _treeid = None
    _root = None

    @fproperty
    def select():
        """Get/set the selection of a tree element."""
        def getter(self):
            return bool(self.store_elem.contents.flag & 2)
        def setter(self, state):
            if state:
                self.store_elem.contents.flag |= 2
            else:
                self.store_elem.contents.flag &= ~2
        return getter, setter

    @fproperty
    def expand():
        """Get/set the expansion of a tree element."""
        def getter(self):
            return not bool(self.tseflag & 1)
        def setter(self, state):
            if state:
                self.store_elem.contents.flag &= ~1
            else:
                self.store_elem.contents.flag |= 1
        return getter, setter

    @property
    def treeid(self):
        """Internal use. """
        if self._treeid is None:
            self._treeid = hash(
                tuple((t.name.decode(), t.idcode) for t in self._resolve()))
        return self._treeid

    def _resolve(self):
        """Tree element path, internal."""
        link = [self]
        parent = self.parent
        while parent:
            link.append(parent.contents)
            parent = parent.contents.parent
        return tuple(reversed(link))

    def as_object(self, root):
        """Return the bpy.types.Object or LayerCollection instance"""
        if self._object is None:
            objs = bpy.context.view_layer.objects

            for t in subtrees_get(root):
                if t.treeid == self.treeid:
                    name = t.name.decode()

                    if t.idcode == ID_LAYERCOLL:
                        lc = bpy.context.view_layer.layer_collection
                        for p in [t.name.decode() for t in self._resolve()][1:]:
                            lc = lc.children[p]
                        self._object = lc
                        break

                    elif t.idcode == ID_OB:
                        self._object = objs[name]
                        break

        return self._object

    @classmethod
    def from_outliner(cls, so):
        return SpaceOutliner.from_address(so.as_pointer()).tree.first

TreeElement._fields_ = (
    ("next", POINTER(TreeElement)),
    ("prev", POINTER(TreeElement)),
    ("parent", POINTER(TreeElement)),
    *_dyn_entry("type", c_void_p, version_ctypes_interface > (2, 91)),
    ("subtree", listbase(TreeElement)),
    ("xs", c_int),
    ("ys", c_int),
    ("store_elem", POINTER(TreeStoreElem)),
    ("flag", c_short),
    ("index", c_short),
    ("idcode", c_short),
    ("xend", c_short),
    ("name", c_char_p),
    ("directdata", c_void_p),
    ("rnaptr", c_void_p * 3))

class SpaceOutliner(Structure):
    """ source/blender/makesdna/DNA_space_types.h """

    _fields_ = (
        ("next", c_void_p),
        ("prev", c_void_p),
        ("regionbase", listbase()),
        ("spacetype", c_char),
        ("link_flag", c_char),
        ("pad0", c_char * 6),
        ("v2d", View2D),
        ("tree", listbase(TreeElement)),
        # ... (cont)
    )
    @classmethod
    def get_tree(cls, so: bpy.types.SpaceOutliner) -> TreeElement:
        return cls.from_address(so.as_pointer()).tree.first

class ID(Structure):
    """ source/blender/makesdna/DNA_ID.h """

    _fields_ = (
        ("next", c_void_p),
        ("prev", c_void_p),
        ("newid", c_void_p),
        ("lib", c_void_p),
        *_dyn_entry("asset_data", c_void_p, version_ctypes_interface > (2, 83)),
        ("name", c_char * 66),
        ("flag", c_short),
        ("tag", c_int),
        ("us", c_int),
        ("icon_id", c_int),
        ("recalc", c_int),
        ("recalc_up_to_undo_push", c_int),
        ("recalc_after_undo_push", c_int),
        ("session_uuid", c_uint),
        ("properties", c_void_p),
        ("override_library", c_void_p),
        ("orig_id", c_void_p),
        ("py_instance", c_void_p),
        *_dyn_entry("_pad1", c_void_p, version_ctypes_interface > (2, 83))
    )

class wmWindowManager(Structure):
    """ source/blender/makesdna/DNA_windowmanager_types.h """
    _fields_ = (
        ("id", ID),
        ("windrawable", c_void_p),
        ("winactive", c_void_p),
        ("windows", listbase()),
        ("initialized", c_short),
        ("file_saved", c_short),
        ("op_undo_depth", c_short),
        ("outliner_sync_select_dirty", c_short),
        # ... (cont)
    )

def subtrees_get(tree):
    """Given a tree, retrieve all its sub tree elements."""
    trees = []
    pool = [tree]
    while pool:
        t = pool.pop().contents
        trees.append(t)
        child = t.subtree.first
        while child:
            pool.append(child)
            child = child.contents.next
    return trees[1:]

def get_outliner_selected_nodes():
    """ Returns all hidden objects selected in the outliner for Blender 2.83 LTS"""

    _so = None
    for win in bpy.context.window_manager.windows:
        for ar in win.screen.areas:
            if ar.type == 'OUTLINER':
                _so = ar.spaces.active
    if _so is None:
        print('so is None')
        return
    root = TreeElement.from_outliner(_so)
    # wmstruct = wmWindowManager.from_address(bpy.context.window_manager.as_pointer())
    # Track processed objects to prevent those that appear in multiple
    # collections from being processed again.
    walked = set()
    types = {ID_OB, ID_LAYERCOLL}
    try:
        for tree in subtrees_get(root):
            if tree.select and tree.idcode in types:
                obj = tree.as_object(root)
                if obj in walked:
                    continue
                walked.add(obj)
    except ValueError as e:
        pass
        #print(e)
    except KeyError as e:
        pass
        #print(e)
    root = None
    return list(walked)

def atoi(text):
    return int(text) if text.isdigit() else text

def natural_keys(text):
    '''
    alist.sort(key=natural_keys) sorts in human order
    http://nedbatchelder.com/blog/200712/human_sorting.html
    (See Toothy's implementation in the comments)
    '''
    return [ atoi(c) for c in re.split(r'(\d+)', text) ]

def getSelectedNodes():
    """ Returns a list of all bpy.context.selected_objects names. """

    iterItems = get_outliner_selected_nodes()
    if iterItems is None or len(iterItems) == 0:
        iterItems = bpy.context.selected_objects
    nameList = [o.name for o in iterItems]
    nameList.sort(key=natural_keys)
    return nameList

def getActiveObjectName(previous):
    """
    previous: name of the previous object
    """

    #nativ_activeObjName = context.active_object.name    #necessary?
    nodes = getSelectedNodes()
    if len(nodes)>0:
        activeObjName = getSelectedNodes()[0]
    else:
        return (previous, False)
    hasChanged = True
    if previous == activeObjName:
        hasChanged = False
    return (activeObjName,hasChanged)


def getSelectedObjects(context):
    # get active object from outliner context
    # this also includes hidden objects like collision etc
    selected_items = []
    for area in context.screen.areas:
        if area.type == 'OUTLINER':
            try:
                context_override = {}
                context_override['area'] = area
                context_override['region'] = [region for region in area.regions if region.type == 'WINDOW'][0]

                with bpy.context.temp_override(**context_override):
                    selected_items.extend(context.selected_ids)
            except Exception as e:
                print(f"An exception occurred: {e}")
    if not selected_items:
        selected_items.extend(context.selected_objects)

    return selected_items