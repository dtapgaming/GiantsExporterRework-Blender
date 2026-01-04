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

"""I3D Color Library

Implements a two-tab color library UI (My Color Library / Giants Library)
inside the "Material" tab (UI_settingsMode == 'shader') of the REWORKED exporter.

Requirements from DTAP:
 - My Color Library: user-managed list of colors with add/remove/import/export.
 - Giants Library: parse $data/shared/brandMaterialTemplates.xml via resolveGiantsPath,
   group templates by brand (missing brand -> Other), and list colors (name left, chip right).
 - Apply selected color to Blender material (Principled Base Color / diffuse fallback)
 - Apply selected color as GIANTS exporter custom property: material["customParameter_colorScale"].
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import bpy

from .helpers.pathHelper import getGamePath, resolveGiantsPath


def _cl_get_prefs(context):
    try:
        return context.preferences.addons['io_export_i3d_reworked'].preferences
    except Exception:
        return None



# -----------------------------------------------------------------------------
# Persistent storage for "My Color Library"
# -----------------------------------------------------------------------------

_STORE_DIRNAME = "io_export_i3d_reworked"
_STORE_FILENAME = "color_library.json"


def _store_path() -> Path:
    # Store in Blender user config so library survives add-on updates.
    base = bpy.utils.user_resource('CONFIG') or ""
    base_path = Path(base) if base else Path.home() / ".blender"
    d = base_path / _STORE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d / _STORE_FILENAME


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _norm_color(v: Any) -> List[float]:
    try:
        r = _clamp01(_safe_float(v[0], 0.0))
        g = _clamp01(_safe_float(v[1], 0.0))
        b = _clamp01(_safe_float(v[2], 0.0))
        return [r, g, b]
    except Exception:
        return [1.0, 1.0, 1.0]


def _giants_srgb_triplet_from_color(rgb: Any) -> Tuple[float, float, float]:
    """Return sRGB floats snapped to 8-bit/255 for stable GIANTS colorScale."""
    c = _norm_color(rgb)
    r = int(round(c[0] * 255)) / 255.0
    g = int(round(c[1] * 255)) / 255.0
    b = int(round(c[2] * 255)) / 255.0
    return r, g, b


def _giants_srgb_text(rgb: Any) -> str:
    r, g, b = _giants_srgb_triplet_from_color(rgb)
    return f"{r:.6f} {g:.6f} {b:.6f}"

def _rgb255_triplet_from_color(rgb: Any) -> Tuple[int, int, int]:
    r, g, b = _giants_srgb_triplet_from_color(rgb)
    return (int(round(r * 255.0)), int(round(g * 255.0)), int(round(b * 255.0)))


def _hex_text_from_color(rgb: Any) -> str:
    R, G, B = _rgb255_triplet_from_color(rgb)
    return f"#{R:02X}{G:02X}{B:02X}"


def _srgb_label_text(rgb: Any) -> str:
    r, g, b = _giants_srgb_triplet_from_color(rgb)
    return f"{r:.3f} {g:.3f} {b:.3f}"



# Debounced autosave
_SAVE_PENDING = False


def _do_save() -> None:
    global _SAVE_PENDING
    _SAVE_PENDING = False
    try:
        save_my_colors()
    except Exception:
        pass


def schedule_save() -> None:
    global _SAVE_PENDING
    if _SAVE_PENDING:
        return
    _SAVE_PENDING = True
    bpy.app.timers.register(_do_save, first_interval=0.25)


def _on_my_color_update(self, context):
    schedule_save()


def _on_my_name_update(self, context):
    schedule_save()


class I3D_CL_ColorItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name="Name", default="New Color", update=_on_my_name_update)
    color: bpy.props.FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        size=3,
        default=(1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
        update=_on_my_color_update,
    )


def _serialize_my(scene: bpy.types.Scene) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in scene.i3d_cl_my_colors:
        out.append({
            "name": (c.name or "").strip()[:80],
            "color": list(_norm_color(c.color)),
        })
    return out


def _apply_my(scene: bpy.types.Scene, data: Any, *, replace: bool) -> int:
    if not isinstance(data, list):
        return 0

    existing_names = set()
    if not replace:
        for c in scene.i3d_cl_my_colors:
            existing_names.add((c.name or "").strip().lower())

    count = 0
    if replace:
        scene.i3d_cl_my_colors.clear()

    for row in data:
        if not isinstance(row, dict):
            continue
        nm = str(row.get("name", "")).strip() or "Color"
        col = _norm_color(row.get("color"))
        key = nm.lower()
        if not replace and key in existing_names:
            base = nm
            i = 2
            while key in existing_names:
                nm = f"{base} {i}"
                key = nm.lower()
                i += 1

        item = scene.i3d_cl_my_colors.add()
        item.name = nm
        item.color = col
        existing_names.add(key)
        count += 1

    if count:
        scene.i3d_cl_my_index = min(scene.i3d_cl_my_index, max(0, len(scene.i3d_cl_my_colors) - 1))
        schedule_save()

    return count


def load_my_colors_from_path(path: Path, *, replace: bool) -> int:
    try:
        if not path.exists():
            return 0
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else []
    except Exception:
        return 0

    scene = bpy.context.scene
    if not scene:
        return 0
    return _apply_my(scene, data, replace=replace)


def save_my_colors_to_path(path: Path) -> bool:
    scene = bpy.context.scene
    if not scene:
        return False
    try:
        payload = _serialize_my(scene)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def load_my_colors() -> None:
    load_my_colors_from_path(_store_path(), replace=True)


def save_my_colors() -> None:
    save_my_colors_to_path(_store_path())


# -----------------------------------------------------------------------------
# GIANTS brandMaterialTemplates.xml parsing + caching
# -----------------------------------------------------------------------------

_GIANTS_XML_GIANTS_PATH = "$data/shared/brandMaterialTemplates.xml"

_GIANTS_CACHE_PATH: str = ""
_GIANTS_CACHE_MTIME: float = -1.0
_GIANTS_CACHE_BRANDS: Dict[str, List[Dict[str, Any]]] = {}
_GIANTS_CACHE_BRAND_LIST: List[str] = []
_GIANTS_LAST_ERROR: str = ""


def _parse_color_scale_triplet(text: str) -> Optional[Tuple[float, float, float]]:
    if not text:
        return None
    parts = str(text).strip().split()
    if len(parts) < 3:
        return None
    r = _clamp01(_safe_float(parts[0], 0.0))
    g = _clamp01(_safe_float(parts[1], 0.0))
    b = _clamp01(_safe_float(parts[2], 0.0))
    return (r, g, b)


def _giants_xml_resolve_path() -> str:
    game_path = getGamePath()
    resolved = resolveGiantsPath(_GIANTS_XML_GIANTS_PATH, game_path)
    return resolved


def ensure_giants_cache(*, force: bool = False) -> bool:
    """Parse and cache GIANTS brandMaterialTemplates.xml.

    Returns True when cache is ready; False when file missing or parse failed.
    """
    global _GIANTS_CACHE_PATH, _GIANTS_CACHE_MTIME, _GIANTS_CACHE_BRANDS, _GIANTS_CACHE_BRAND_LIST, _GIANTS_LAST_ERROR

    xml_path = _giants_xml_resolve_path()
    if not xml_path:
        _GIANTS_LAST_ERROR = "Game Install Path not set (cannot resolve $data path)."
        _GIANTS_CACHE_PATH = ""
        _GIANTS_CACHE_MTIME = -1.0
        _GIANTS_CACHE_BRANDS = {}
        _GIANTS_CACHE_BRAND_LIST = []
        return False

    if not os.path.isfile(xml_path):
        _GIANTS_LAST_ERROR = f"Missing file: {xml_path}"
        _GIANTS_CACHE_PATH = xml_path
        _GIANTS_CACHE_MTIME = -1.0
        _GIANTS_CACHE_BRANDS = {}
        _GIANTS_CACHE_BRAND_LIST = []
        return False

    try:
        mtime = os.path.getmtime(xml_path)
    except Exception:
        mtime = -1.0

    if (not force) and _GIANTS_CACHE_PATH == xml_path and _GIANTS_CACHE_MTIME == mtime and _GIANTS_CACHE_BRANDS:
        return True

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        brands: Dict[str, List[Dict[str, Any]]] = {}
        OTHER = "Other"

        for el in root.iter():
            # Expecting <template .../>
            if el.tag != "template":
                continue
            nm = (el.attrib.get("name") or "").strip()
            cs = (el.attrib.get("colorScale") or "").strip()
            trip = _parse_color_scale_triplet(cs)
            if (not nm) or (trip is None):
                continue
            brand = (el.attrib.get("brand") or "").strip()
            if not brand:
                brand = OTHER

            row = {
                "name": nm,
                "brand": brand,
                "colorScale": cs,
                "rgb": trip,
                "title": (el.attrib.get("title") or "").strip(),
            }

            brands.setdefault(brand, []).append(row)

        # Sort
        for b in brands.keys():
            brands[b].sort(key=lambda r: (r.get("name") or ""))
        brand_list = sorted([b for b in brands.keys() if b != OTHER])
        if OTHER in brands:
            brand_list.append(OTHER)

        _GIANTS_CACHE_PATH = xml_path
        _GIANTS_CACHE_MTIME = mtime
        _GIANTS_CACHE_BRANDS = brands
        _GIANTS_CACHE_BRAND_LIST = brand_list
        _GIANTS_LAST_ERROR = ""
        return True

    except Exception as e:
        _GIANTS_LAST_ERROR = f"Failed to parse brandMaterialTemplates.xml: {e}"
        _GIANTS_CACHE_PATH = xml_path
        _GIANTS_CACHE_MTIME = mtime
        _GIANTS_CACHE_BRANDS = {}
        _GIANTS_CACHE_BRAND_LIST = []
        return False


def _giants_brand_items(self, context):
    # Items callback for EnumProperty.
    ensure_giants_cache(force=False)
    items = []
    for b in _GIANTS_CACHE_BRAND_LIST:
        if b == "Other":
            items.append(("OTHER", "Other", "Templates with no brand attribute"))
        else:
            items.append((b, b, ""))
    if not items:
        items = [("OTHER", "Other", "")]
    return items


class I3D_CL_GiantsColorItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name="Name", default="")
    brand: bpy.props.StringProperty(name="Brand", default="")
    color: bpy.props.FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        size=3,
        default=(1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
    )
    colorScale: bpy.props.StringProperty(name="colorScale", default="")
    title: bpy.props.StringProperty(name="Title", default="")


def rebuild_giants_visible(scene: bpy.types.Scene) -> None:
    scene.i3d_cl_giants_colors.clear()
    scene.i3d_cl_giants_index = 0

    if not ensure_giants_cache(force=False):
        return

    brand_id = getattr(scene, "i3d_cl_giants_brand", "OTHER")
    brand_key = "Other" if brand_id == "OTHER" else brand_id

    rows = _GIANTS_CACHE_BRANDS.get(brand_key, [])
    for r in rows:
        it = scene.i3d_cl_giants_colors.add()
        it.name = r.get("name", "")
        it.brand = r.get("brand", "")
        it.colorScale = r.get("colorScale", "")
        it.title = r.get("title", "")
        rgb = r.get("rgb")
        if rgb:
            it.color = rgb

    if rows:
        scene.i3d_cl_giants_index = 0


def _on_brand_update(self, context):
    try:
        rebuild_giants_visible(context.scene)
    except Exception:
        pass



# -----------------------------------------------------------------------------
# POPULAR color library parsing + caching (shipped inside the addon)
# -----------------------------------------------------------------------------

_POPULAR_XML_RELATIVE_PATH = os.path.join("data", "popularBrandMaterialTemplates.xml")

_POPULAR_CACHE_PATH: str = ""
_POPULAR_CACHE_MTIME: float = -1.0
_POPULAR_CACHE_BRANDS: Dict[str, List[Dict[str, Any]]] = {}
_POPULAR_CACHE_BRAND_LIST: List[str] = []
_POPULAR_LAST_ERROR: str = ""


def _popular_xml_resolve_path() -> str:
    try:
        here = os.path.dirname(__file__)
        return os.path.join(here, _POPULAR_XML_RELATIVE_PATH)
    except Exception:
        return ""


def ensure_popular_cache(*, force: bool = False) -> bool:
    """Parse and cache the addon-shipped popularBrandMaterialTemplates.xml.

    Returns True when cache is ready; False when file missing or parse failed.
    """
    global _POPULAR_CACHE_PATH, _POPULAR_CACHE_MTIME, _POPULAR_CACHE_BRANDS, _POPULAR_CACHE_BRAND_LIST, _POPULAR_LAST_ERROR

    xml_path = _popular_xml_resolve_path()
    if not xml_path:
        _POPULAR_LAST_ERROR = "Cannot resolve addon data path."
        _POPULAR_CACHE_PATH = ""
        _POPULAR_CACHE_MTIME = -1.0
        _POPULAR_CACHE_BRANDS = {}
        _POPULAR_CACHE_BRAND_LIST = []
        return False

    if not os.path.isfile(xml_path):
        _POPULAR_LAST_ERROR = f"Missing file: {xml_path}"
        _POPULAR_CACHE_PATH = xml_path
        _POPULAR_CACHE_MTIME = -1.0
        _POPULAR_CACHE_BRANDS = {}
        _POPULAR_CACHE_BRAND_LIST = []
        return False

    try:
        mtime = os.path.getmtime(xml_path)
    except Exception:
        mtime = -1.0

    if (not force) and _POPULAR_CACHE_PATH == xml_path and _POPULAR_CACHE_MTIME == mtime and _POPULAR_CACHE_BRANDS:
        return True

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        brands: Dict[str, List[Dict[str, Any]]] = {}
        OTHER = "Other"

        for el in root.iter():
            # Expecting <template .../>
            if el.tag != "template":
                continue
            nm = (el.attrib.get("name") or "").strip()
            cs = (el.attrib.get("colorScale") or "").strip()
            trip = _parse_color_scale_triplet(cs)
            if (not nm) or (trip is None):
                continue
            brand = (el.attrib.get("brand") or "").strip()
            if not brand:
                brand = OTHER

            row = {
                "name": nm,
                "brand": brand,
                "colorScale": cs,
                "rgb": trip,
                "title": (el.attrib.get("title") or "").strip(),
            }

            brands.setdefault(brand, []).append(row)

        # Sort
        for b in brands.keys():
            brands[b].sort(key=lambda r: (r.get("name") or ""))
        brand_list = sorted([b for b in brands.keys() if b != OTHER])
        if OTHER in brands:
            brand_list.append(OTHER)

        _POPULAR_CACHE_PATH = xml_path
        _POPULAR_CACHE_MTIME = mtime
        _POPULAR_CACHE_BRANDS = brands
        _POPULAR_CACHE_BRAND_LIST = brand_list
        _POPULAR_LAST_ERROR = ""
        return True

    except Exception as e:
        _POPULAR_LAST_ERROR = f"Failed to parse popularBrandMaterialTemplates.xml: {e}"
        _POPULAR_CACHE_PATH = xml_path
        _POPULAR_CACHE_MTIME = mtime
        _POPULAR_CACHE_BRANDS = {}
        _POPULAR_CACHE_BRAND_LIST = []
        return False


def _popular_brand_items(self, context):
    # Items callback for EnumProperty.
    ensure_popular_cache(force=False)
    items = []
    for b in _POPULAR_CACHE_BRAND_LIST:
        if b == "Other":
            items.append(("OTHER", "Other", "Templates with no brand attribute"))
        else:
            items.append((b, b, ""))
    if not items:
        items = [("OTHER", "Other", "")]
    return items


class I3D_CL_PopularColorItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name="Name", default="")
    brand: bpy.props.StringProperty(name="Brand", default="")
    color: bpy.props.FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        size=3,
        default=(1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
    )
    colorScale: bpy.props.StringProperty(name="colorScale", default="")
    title: bpy.props.StringProperty(name="Title", default="")


def rebuild_popular_visible(scene: bpy.types.Scene) -> None:
    scene.i3d_cl_popular_colors.clear()
    scene.i3d_cl_popular_index = 0

    if not ensure_popular_cache(force=False):
        return

    brand_id = getattr(scene, "i3d_cl_popular_brand", "OTHER")
    brand_key = "Other" if brand_id == "OTHER" else brand_id

    rows = _POPULAR_CACHE_BRANDS.get(brand_key, [])
    for r in rows:
        it = scene.i3d_cl_popular_colors.add()
        it.name = r.get("name", "")
        it.brand = r.get("brand", "")
        it.colorScale = r.get("colorScale", "")
        it.title = r.get("title", "")
        rgb = r.get("rgb")
        if rgb:
            it.color = rgb

    if rows:
        scene.i3d_cl_popular_index = 0


def _on_popular_brand_update(self, context):
    try:
        rebuild_popular_visible(context.scene)
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Operators
# -----------------------------------------------------------------------------


class I3D_CL_OT_MyAdd(bpy.types.Operator):
    bl_idname = "i3d.cl_my_add"
    bl_label = "Add Color"
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        item = scene.i3d_cl_my_colors.add()
        item.name = "New Color"
        item.color = (1.0, 1.0, 1.0)
        scene.i3d_cl_my_index = len(scene.i3d_cl_my_colors) - 1
        schedule_save()
        return {'FINISHED'}


class I3D_CL_OT_MyRemove(bpy.types.Operator):
    bl_idname = "i3d.cl_my_remove"
    bl_label = "Remove Color"
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_my_index
        if 0 <= idx < len(scene.i3d_cl_my_colors):
            scene.i3d_cl_my_colors.remove(idx)
            scene.i3d_cl_my_index = min(idx, max(0, len(scene.i3d_cl_my_colors) - 1))
            schedule_save()
        return {'FINISHED'}


class I3D_CL_OT_MyExport(bpy.types.Operator):
    bl_idname = "i3d.cl_my_export"
    bl_label = "Export Colors"
    bl_options = {'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        ok = save_my_colors_to_path(Path(self.filepath))
        self.report({'INFO'} if ok else {'ERROR'}, "Exported colors" if ok else "Export failed")
        return {'FINISHED'}

    def invoke(self, context, event):
        self.filepath = "i3d_reworked_colors.json"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class I3D_CL_OT_MyImport(bpy.types.Operator):
    bl_idname = "i3d.cl_my_import"
    bl_label = "Import Colors"
    bl_options = {'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    replace_library: bpy.props.BoolProperty(
        name="Replace existing library",
        description="If enabled, replaces your current colors. If disabled, imports and adds to your existing list.",
        default=False,
    )

    def execute(self, context):
        n = load_my_colors_from_path(Path(self.filepath), replace=self.replace_library)
        if n:
            self.report({'INFO'}, f"Imported {n} colors")
        else:
            self.report({'WARNING'}, "No colors imported")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class I3D_CL_OT_MyReload(bpy.types.Operator):
    bl_idname = "i3d.cl_my_reload"
    bl_label = "Reload Colors"

    def execute(self, context):
        load_my_colors()
        self.report({'INFO'}, "Reloaded colors")
        return {'FINISHED'}


def _get_active_material(context) -> Optional[bpy.types.Material]:
    obj = context.object
    mat = obj.active_material if obj else None
    return mat


def _apply_color_to_material(mat: bpy.types.Material, col: Tuple[float, float, float]) -> bool:
    if not mat:
        return False
    # Prefer node-based materials
    if getattr(mat, "use_nodes", False) and getattr(mat, "node_tree", None):
        try:
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf and "Base Color" in bsdf.inputs:
                bsdf.inputs["Base Color"].default_value = (col[0], col[1], col[2], 1.0)
                return True
        except Exception:
            pass
    # Fallback
    try:
        mat.diffuse_color = (col[0], col[1], col[2], 1.0)
        return True
    except Exception:
        return False


def _apply_giants_colorscale(mat: bpy.types.Material, color_scale_triplet: str) -> bool:
    if not mat:
        return False
    cs = (color_scale_triplet or "").strip()
    if not cs:
        return False
    # Ensure 3 floats
    trip = _parse_color_scale_triplet(cs)
    if trip is None:
        return False
    mat["customParameter_colorScale"] = f"{trip[0]:.6f} {trip[1]:.6f} {trip[2]:.6f} 1.0"
    try:
        mat.update_tag()
    except Exception:
        pass
    try:
        if bpy.context.view_layer:
            bpy.context.view_layer.update()
    except Exception:
        pass
    return True


class I3D_CL_OT_ApplyMyToMaterial(bpy.types.Operator):
    bl_idname = "i3d.cl_my_apply_to_material"
    bl_label = "Apply to Material"
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_my_index
        if not (0 <= idx < len(scene.i3d_cl_my_colors)):
            self.report({'WARNING'}, "No color selected")
            return {'CANCELLED'}

        mat = _get_active_material(context)
        if not mat:
            self.report({'WARNING'}, "No active material")
            return {'CANCELLED'}

        col = scene.i3d_cl_my_colors[idx].color
        ok = _apply_color_to_material(mat, tuple(_norm_color(col)))
        self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
        return {'FINISHED'} if ok else {'CANCELLED'}


class I3D_CL_OT_ApplyMyToGiantsColorScale(bpy.types.Operator):
    bl_idname = "i3d.cl_my_apply_to_giants_colorscale"
    bl_label = "Apply to GIANTS colorScale"
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_my_index
        if not (0 <= idx < len(scene.i3d_cl_my_colors)):
            self.report({'WARNING'}, "No color selected")
            return {'CANCELLED'}

        mat = _get_active_material(context)
        if not mat:
            self.report({'WARNING'}, "No active material")
            return {'CANCELLED'}

        txt = _giants_srgb_text(scene.i3d_cl_my_colors[idx].color)
        ok = _apply_giants_colorscale(mat, txt)
        self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Could not set customParameter_colorScale")
        return {'FINISHED'} if ok else {'CANCELLED'}

class I3D_CL_OT_CopySelected(bpy.types.Operator):
    bl_idname = "i3d.cl_copy_selected"
    bl_label = "Copy Color Value"

    src: bpy.props.EnumProperty(
        items=[
            ('MY', 'My Color Library', ''),
            ('GIANTS', 'Giants Library', ''),
            ('POPULAR', 'Popular Color Library', ''),
        ],
        name="Source",
        default='MY',
    )

    kind: bpy.props.EnumProperty(
        items=[
            ('SRGB', 'GIANTS (sRGB)', ''),
            ('RGB', 'RGB (255)', ''),
            ('CSCALE', 'colorScale (XML)', ''),
            ('HEX', 'HEX', ''),
        ],
        name="Format",
        default='SRGB',
    )

    def execute(self, context):
        scene = context.scene

        item = None
        if self.src == 'MY':
            idx = scene.i3d_cl_my_index
            if 0 <= idx < len(scene.i3d_cl_my_colors):
                item = scene.i3d_cl_my_colors[idx]
        elif self.src == 'GIANTS':
            idx = scene.i3d_cl_giants_index
            if 0 <= idx < len(scene.i3d_cl_giants_colors):
                item = scene.i3d_cl_giants_colors[idx]
        else:
            idx = scene.i3d_cl_popular_index
            if 0 <= idx < len(scene.i3d_cl_popular_colors):
                item = scene.i3d_cl_popular_colors[idx]

        if not item:
            self.report({'WARNING'}, "No color selected")
            return {'CANCELLED'}

        rgb = _norm_color(getattr(item, "color", (1.0, 1.0, 1.0)))

        if self.kind == 'HEX':
            txt = _hex_text_from_color(rgb)
        elif self.kind == 'RGB':
            R, G, B = _rgb255_triplet_from_color(rgb)
            txt = f"{R}, {G}, {B}"
        elif self.kind == 'CSCALE':
            # XML expects 3 floats in [0..1] without alpha; preserve source XML when available.
            cs_attr = ""
            try:
                cs_attr = str(getattr(item, "colorScale", "") or "").strip()
            except Exception:
                cs_attr = ""
            if cs_attr and self.src in ('GIANTS', 'POPULAR'):
                txt = cs_attr
            else:
                r, g, b = _giants_srgb_triplet_from_color(rgb)
                txt = f"{r:.4f} {g:.4f} {b:.4f}"
        else:
            txt = _giants_srgb_text(rgb)

        try:
            context.window_manager.clipboard = txt
        except Exception:
            pass

        self.report({'INFO'}, "Copied")
        return {'FINISHED'}



class I3D_CL_OT_GiantsRefresh(bpy.types.Operator):
    bl_idname = "i3d.cl_giants_refresh"
    bl_label = "Refresh GIANTS Library"

    def execute(self, context):
        ensure_giants_cache(force=True)
        rebuild_giants_visible(context.scene)
        if _GIANTS_LAST_ERROR:
            self.report({'WARNING'}, _GIANTS_LAST_ERROR)
        else:
            self.report({'INFO'}, "GIANTS library refreshed")
        return {'FINISHED'}



class I3D_CL_OT_PopularRefresh(bpy.types.Operator):
    bl_idname = "i3d.cl_popular_refresh"
    bl_label = "Refresh Popular Library"

    def execute(self, context):
        ensure_popular_cache(force=True)
        rebuild_popular_visible(context.scene)
        if _POPULAR_LAST_ERROR:
            self.report({'WARNING'}, _POPULAR_LAST_ERROR)
        else:
            self.report({'INFO'}, "Popular library refreshed")
        return {'FINISHED'}



class I3D_CL_OT_ApplyGiantsToMaterial(bpy.types.Operator):
    bl_idname = "i3d.cl_giants_apply_to_material"
    bl_label = "Apply to Material"
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_giants_index
        if not (0 <= idx < len(scene.i3d_cl_giants_colors)):
            self.report({'WARNING'}, "No GIANTS color selected")
            return {'CANCELLED'}

        mat = _get_active_material(context)
        if not mat:
            self.report({'WARNING'}, "No active material")
            return {'CANCELLED'}

        col = scene.i3d_cl_giants_colors[idx].color
        ok = _apply_color_to_material(mat, tuple(_norm_color(col)))
        self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
        return {'FINISHED'} if ok else {'CANCELLED'}


class I3D_CL_OT_ApplyGiantsToGiantsColorScale(bpy.types.Operator):
    bl_idname = "i3d.cl_giants_apply_to_giants_colorscale"
    bl_label = "Apply to GIANTS colorScale"
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_giants_index
        if not (0 <= idx < len(scene.i3d_cl_giants_colors)):
            self.report({'WARNING'}, "No GIANTS color selected")
            return {'CANCELLED'}

        mat = _get_active_material(context)
        if not mat:
            self.report({'WARNING'}, "No active material")
            return {'CANCELLED'}

        cs = scene.i3d_cl_giants_colors[idx].colorScale
        ok = _apply_giants_colorscale(mat, cs)
        self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Could not set customParameter_colorScale")
        return {'FINISHED'} if ok else {'CANCELLED'}


class I3D_CL_OT_AddGiantsToMyLibrary(bpy.types.Operator):
    bl_idname = "i3d.cl_giants_add_to_my_library"
    bl_label = "Add to My Library"
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_giants_index
        if not (0 <= idx < len(scene.i3d_cl_giants_colors)):
            self.report({'WARNING'}, "No GIANTS color selected")
            return {'CANCELLED'}

        g = scene.i3d_cl_giants_colors[idx]
        it = scene.i3d_cl_my_colors.add()
        it.name = g.name
        it.color = g.color
        scene.i3d_cl_my_index = len(scene.i3d_cl_my_colors) - 1
        schedule_save()
        self.report({'INFO'}, "Added to My Library")
        return {'FINISHED'}



class I3D_CL_OT_ApplyPopularToMaterial(bpy.types.Operator):
    bl_idname = "i3d.cl_popular_apply_to_material"
    bl_label = "Apply to Material"
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_popular_index
        if not (0 <= idx < len(scene.i3d_cl_popular_colors)):
            self.report({'WARNING'}, "No Popular color selected")
            return {'CANCELLED'}

        mat = _get_active_material(context)
        if not mat:
            self.report({'WARNING'}, "No active material")
            return {'CANCELLED'}

        col = scene.i3d_cl_popular_colors[idx].color
        ok = _apply_color_to_material(mat, tuple(_norm_color(col)))
        self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
        return {'FINISHED'} if ok else {'CANCELLED'}


class I3D_CL_OT_ApplyPopularToGiantsColorScale(bpy.types.Operator):
    bl_idname = "i3d.cl_popular_apply_to_giants_colorscale"
    bl_label = "Apply to GIANTS colorScale"
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_popular_index
        if not (0 <= idx < len(scene.i3d_cl_popular_colors)):
            self.report({'WARNING'}, "No Popular color selected")
            return {'CANCELLED'}

        mat = _get_active_material(context)
        if not mat:
            self.report({'WARNING'}, "No active material")
            return {'CANCELLED'}

        cs = scene.i3d_cl_popular_colors[idx].colorScale
        ok = _apply_giants_colorscale(mat, cs)
        self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Could not set customParameter_colorScale")
        return {'FINISHED'} if ok else {'CANCELLED'}


class I3D_CL_OT_AddPopularToMyLibrary(bpy.types.Operator):
    bl_idname = "i3d.cl_popular_add_to_my_library"
    bl_label = "Add to My Library"
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_popular_index
        if not (0 <= idx < len(scene.i3d_cl_popular_colors)):
            self.report({'WARNING'}, "No Popular color selected")
            return {'CANCELLED'}

        g = scene.i3d_cl_popular_colors[idx]
        it = scene.i3d_cl_my_colors.add()
        it.name = g.name
        it.color = g.color
        scene.i3d_cl_my_index = len(scene.i3d_cl_my_colors) - 1
        schedule_save()
        self.report({'INFO'}, "Added to My Library")
        return {'FINISHED'}



# -----------------------------------------------------------------------------
# UI Lists
# -----------------------------------------------------------------------------


class I3D_CL_UL_MyColors(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        prefs = _cl_get_prefs(context)
        split = layout.split(factor=float(getattr(prefs, 'colorlib_name_ratio', 0.60)) if prefs else 0.60)
        split.prop(item, "name", text="", emboss=False)
        right = split.row(align=True)
        chip = right.row(align=True)
        chip.prop(item, "color", text="")
        # NOTE: My Color Library already shows the color preview swatch.
        # Do not also show the numeric color value in the list rows.


class I3D_CL_UL_GiantsColors(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        prefs = _cl_get_prefs(context)
        split = layout.split(factor=float(getattr(prefs, 'colorlib_name_ratio', 0.78)) if prefs else 0.78)
        split.label(text=item.name)
        chip = split.row(align=True)
        chip.prop(item, "color", text="")


class I3D_CL_UL_PopularColors(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        prefs = _cl_get_prefs(context)
        split = layout.split(factor=float(getattr(prefs, 'colorlib_name_ratio', 0.78)) if prefs else 0.78)
        split.label(text=item.name)
        chip = split.row(align=True)
        chip.prop(item, "color", text="")





class I3D_CL_OT_SetEmissionBlack(bpy.types.Operator):
    bl_idname = "i3d.cl_set_emission_black"
    bl_label = "Set Emission (Black)"
    bl_description = "Set Principled BSDF Emission Color to black (#000000FF) on the active material"
    bl_options = {'UNDO'}

    strength: bpy.props.FloatProperty(
        name="Strength",
        default=1.0,
        min=0.0,
        soft_max=50.0,
    )  # type: ignore

    def execute(self, context):
        obj = context.active_object
        if not obj:
            self.report({'WARNING'}, "No active object.")
            return {'CANCELLED'}

        mat = getattr(obj, "active_material", None)
        if not mat:
            self.report({'WARNING'}, "No active material.")
            return {'CANCELLED'}

        if not getattr(mat, "use_nodes", False) or not getattr(mat, "node_tree", None):
            self.report({'WARNING'}, "Material has no node tree.")
            return {'CANCELLED'}

        principled = None
        for n in mat.node_tree.nodes:
            if n.type == 'BSDF_PRINCIPLED':
                principled = n
                break

        if not principled:
            self.report({'WARNING'}, "No Principled BSDF node found.")
            return {'CANCELLED'}

        emis_col = principled.inputs.get("Emission Color") or principled.inputs.get("Emission")
        emis_str = principled.inputs.get("Emission Strength")

        if emis_col:
            emis_col.default_value = (0.0, 0.0, 0.0, 1.0)

        if emis_str:
            emis_str.default_value = float(self.strength)

        self.report({'INFO'}, f"Emission set to black on: {mat.name}")
        return {'FINISHED'}



# -----------------------------------------------------------------------------
# Drawing
# -----------------------------------------------------------------------------


def draw_color_library(layout, context):
    scene = context.scene

    # NOTE: Caller provides the container layout (typically a collapsible box).
    # Do NOT create an extra outer box here; keep borders clean and avoid nesting.
    box = layout

    row = box.row(align=True)
    row.prop(scene, "i3d_cl_tab", expand=True)

    if scene.i3d_cl_tab == 'MY':
        header = box.row(align=True)
        header.operator("i3d.cl_my_add", icon='ADD', text="")
        header.operator("i3d.cl_my_remove", icon='REMOVE', text="")

        box.template_list(
            "I3D_CL_UL_MyColors",
            "",
            scene,
            "i3d_cl_my_colors",
            scene,
            "i3d_cl_my_index",
            rows=7,
        )

        idx = scene.i3d_cl_my_index
        if 0 <= idx < len(scene.i3d_cl_my_colors):
            item = scene.i3d_cl_my_colors[idx]
            sel = box.box()
            sel.label(text="Selected")

            sw = sel.row()
            sw.scale_y = 1.3
            sw.prop(item, "color", text="")

            sel.prop(item, "name", text="")

            sel.label(text=f"GIANTS (sRGB): {_srgb_label_text(item.color)}")
            R, G, B = _rgb255_triplet_from_color(item.color)
            sel.label(text=f"RGB: ({R}, {G}, {B})")
            sel.label(text=f"HEX: {_hex_text_from_color(item.color)}")

            btns = sel.row(align=True)
            btns.operator("i3d.cl_my_apply_to_material", text="Apply to Material")
            btns.operator("i3d.cl_my_apply_to_giants_colorscale", text="Apply to GIANTS colorScale")

            copyrow = sel.row(align=True)
            op = copyrow.operator("i3d.cl_copy_selected", text="Copy GIANTS (sRGB)", icon='COPYDOWN')
            op.src = 'MY'
            op.kind = 'SRGB'
            op = copyrow.operator("i3d.cl_copy_selected", text="Copy RGB", icon='COPYDOWN')
            op.src = 'MY'
            op.kind = 'RGB'
            op = copyrow.operator("i3d.cl_copy_selected", text="Copy HEX", icon='COPYDOWN')
            op.src = 'MY'
            op.kind = 'HEX'
            copyrow2 = sel.row(align=True)
            op = copyrow2.operator("i3d.cl_copy_selected", text="Copy colorScale", icon='COPYDOWN')
            op.src = 'MY'
            op.kind = 'CSCALE'
            copyrow2.operator("i3d.cl_set_emission_black", text="Set Emission (Black)", icon='SHADING_RENDERED')
        else:
            box.label(text="No color selected", icon='INFO')

        # -------------------------------------------------
        # Share / Import / Export (My Library ONLY)
        # -------------------------------------------------
        files = box.box()
        r = files.row()
        r.prop(
            scene,
            "i3d_cl_show_files",
            text="Share & Import",
            icon='TRIA_DOWN' if scene.i3d_cl_show_files else 'TRIA_RIGHT',
            icon_only=False,
            emboss=False,
        )
        if scene.i3d_cl_show_files:
            col = files.column(align=True)
            row = col.row(align=True)
            row.scale_y = 1.1
            row.operator("i3d.cl_my_export", text="Export JSON", icon='EXPORT')
            row.operator("i3d.cl_my_import", text="Import JSON", icon='IMPORT')
            col.operator("i3d.cl_my_reload", text="Reload Library", icon='FILE_REFRESH')

    elif scene.i3d_cl_tab == 'GIANTS':
        # GIANTS
        ok = ensure_giants_cache(force=False)
        header = box.row(align=True)
        header.prop(scene, "i3d_cl_giants_brand", text="Brand")
        header.operator("i3d.cl_giants_refresh", icon='FILE_REFRESH', text="")

        if not ok:
            warn = box.box()
            warn.alert = True
            warn.label(text="GIANTS Library unavailable", icon='ERROR')
            if _GIANTS_LAST_ERROR:
                warn.label(text=_GIANTS_LAST_ERROR)
            warn.label(text="Set Game Install Path in add-on preferences.")
            return

        # Ensure list is populated at least once
        if len(scene.i3d_cl_giants_colors) == 0:
            rebuild_giants_visible(scene)

        box.template_list(
            "I3D_CL_UL_GiantsColors",
            "",
            scene,
            "i3d_cl_giants_colors",
            scene,
            "i3d_cl_giants_index",
            rows=7,
        )

        idx = scene.i3d_cl_giants_index
        if 0 <= idx < len(scene.i3d_cl_giants_colors):
            item = scene.i3d_cl_giants_colors[idx]
            sel = box.box()
            sel.label(text="Selected")

            sw = sel.row()
            sw.enabled = False
            sw.scale_y = 1.3
            sw.prop(item, "color", text="")

            sel.label(text=item.name)

            sel.label(text=f"GIANTS (sRGB): {_srgb_label_text(item.color)}")
            R, G, B = _rgb255_triplet_from_color(item.color)
            sel.label(text=f"RGB: ({R}, {G}, {B})")
            sel.label(text=f"HEX: {_hex_text_from_color(item.color)}")

            if item.colorScale:
                sel.label(text=f"colorScale: {item.colorScale}")

            btns = sel.row(align=True)
            btns.operator("i3d.cl_giants_apply_to_material", text="Apply to Material")
            btns.operator("i3d.cl_giants_apply_to_giants_colorscale", text="Apply to GIANTS colorScale")
            btns.operator("i3d.cl_giants_add_to_my_library", text="Add to My Library")

            copyrow = sel.row(align=True)
            op = copyrow.operator("i3d.cl_copy_selected", text="Copy GIANTS (sRGB)", icon='COPYDOWN')
            op.src = 'GIANTS'
            op.kind = 'SRGB'
            op = copyrow.operator("i3d.cl_copy_selected", text="Copy RGB", icon='COPYDOWN')
            op.src = 'GIANTS'
            op.kind = 'RGB'
            op = copyrow.operator("i3d.cl_copy_selected", text="Copy HEX", icon='COPYDOWN')
            op.src = 'GIANTS'
            op.kind = 'HEX'
            copyrow2 = sel.row(align=True)
            op = copyrow2.operator("i3d.cl_copy_selected", text="Copy colorScale", icon='COPYDOWN')
            op.src = 'GIANTS'
            op.kind = 'CSCALE'
            copyrow2.operator("i3d.cl_set_emission_black", text="Set Emission (Black)", icon='SHADING_RENDERED')
        else:
            box.label(text="No GIANTS color selected", icon='INFO')



    else:
        # POPULAR
        ok = ensure_popular_cache(force=False)
        header = box.row(align=True)
        header.prop(scene, "i3d_cl_popular_brand", text="Brand")
        header.operator("i3d.cl_popular_refresh", icon='FILE_REFRESH', text="")

        if not ok:
            warn = box.box()
            warn.alert = True
            warn.label(text="Popular Library unavailable", icon='ERROR')
            if _POPULAR_LAST_ERROR:
                warn.label(text=_POPULAR_LAST_ERROR)
            warn.label(text="The addon-shipped XML is missing or invalid.")
            return

        # Ensure list is populated at least once
        if len(scene.i3d_cl_popular_colors) == 0:
            rebuild_popular_visible(scene)

        box.template_list(
            "I3D_CL_UL_PopularColors",
            "",
            scene,
            "i3d_cl_popular_colors",
            scene,
            "i3d_cl_popular_index",
            rows=7,
        )

        idx = scene.i3d_cl_popular_index
        if 0 <= idx < len(scene.i3d_cl_popular_colors):
            item = scene.i3d_cl_popular_colors[idx]
            sel = box.box()
            sel.label(text="Selected")

            sw = sel.row()
            sw.enabled = False
            sw.scale_y = 1.3
            sw.prop(item, "color", text="")

            sel.label(text=item.name)

            sel.label(text=f"GIANTS (sRGB): {_srgb_label_text(item.color)}")
            R, G, B = _rgb255_triplet_from_color(item.color)
            sel.label(text=f"RGB: ({R}, {G}, {B})")
            sel.label(text=f"HEX: {_hex_text_from_color(item.color)}")

            if item.colorScale:
                sel.label(text=f"colorScale: {item.colorScale}")

            btns = sel.row(align=True)
            btns.operator("i3d.cl_popular_apply_to_material", text="Apply to Material")
            btns.operator("i3d.cl_popular_apply_to_giants_colorscale", text="Apply to GIANTS colorScale")
            btns.operator("i3d.cl_popular_add_to_my_library", text="Add to My Library")

            copyrow = sel.row(align=True)
            op = copyrow.operator("i3d.cl_copy_selected", text="Copy GIANTS (sRGB)", icon='COPYDOWN')
            op.src = 'POPULAR'
            op.kind = 'SRGB'
            op = copyrow.operator("i3d.cl_copy_selected", text="Copy RGB", icon='COPYDOWN')
            op.src = 'POPULAR'
            op.kind = 'RGB'
            op = copyrow.operator("i3d.cl_copy_selected", text="Copy HEX", icon='COPYDOWN')
            op.src = 'POPULAR'
            op.kind = 'HEX'
            copyrow2 = sel.row(align=True)
            op = copyrow2.operator("i3d.cl_copy_selected", text="Copy colorScale", icon='COPYDOWN')
            op.src = 'POPULAR'
            op.kind = 'CSCALE'
            copyrow2.operator("i3d.cl_set_emission_black", text="Set Emission (Black)", icon='SHADING_RENDERED')
        else:
            box.label(text="No Popular color selected", icon='INFO')


# -----------------------------------------------------------------------------
# Handlers
# -----------------------------------------------------------------------------


def _on_load_post(_dummy):
    try:
        load_my_colors()
    except Exception:
        pass


def _on_save_pre(_dummy):
    try:
        save_my_colors()
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Register
# -----------------------------------------------------------------------------


classes = (
    I3D_CL_ColorItem,
    I3D_CL_GiantsColorItem,
    I3D_CL_PopularColorItem,
    I3D_CL_OT_MyAdd,
    I3D_CL_OT_MyRemove,
    I3D_CL_OT_MyExport,
    I3D_CL_OT_MyImport,
    I3D_CL_OT_MyReload,
    I3D_CL_OT_ApplyMyToMaterial,
    I3D_CL_OT_ApplyMyToGiantsColorScale,
    I3D_CL_OT_CopySelected,
    I3D_CL_OT_GiantsRefresh,
    I3D_CL_OT_PopularRefresh,
    I3D_CL_OT_ApplyGiantsToMaterial,
    I3D_CL_OT_ApplyGiantsToGiantsColorScale,
    I3D_CL_OT_AddGiantsToMyLibrary,
    I3D_CL_OT_ApplyPopularToMaterial,
    I3D_CL_OT_ApplyPopularToGiantsColorScale,
    I3D_CL_OT_AddPopularToMyLibrary,
    I3D_CL_UL_MyColors,
    I3D_CL_UL_GiantsColors,
    I3D_CL_UL_PopularColors,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)

    bpy.types.Scene.i3d_cl_tab = bpy.props.EnumProperty(
        items=[('MY', 'My Color Library', ''), ('GIANTS', 'Giants Library', ''), ('POPULAR', 'Popular Color Library', '')],
        name="Color Library Mode",
        default='MY',
    )

    bpy.types.Scene.i3d_cl_my_colors = bpy.props.CollectionProperty(type=I3D_CL_ColorItem)
    bpy.types.Scene.i3d_cl_my_index = bpy.props.IntProperty(default=0)

    bpy.types.Scene.i3d_cl_giants_brand = bpy.props.EnumProperty(
        items=_giants_brand_items,
        name="Brand",
        update=_on_brand_update,
    )
    bpy.types.Scene.i3d_cl_giants_colors = bpy.props.CollectionProperty(type=I3D_CL_GiantsColorItem)
    bpy.types.Scene.i3d_cl_giants_index = bpy.props.IntProperty(default=0)


    bpy.types.Scene.i3d_cl_popular_brand = bpy.props.EnumProperty(
        items=_popular_brand_items,
        name="Brand",
        update=_on_popular_brand_update,
    )
    bpy.types.Scene.i3d_cl_popular_colors = bpy.props.CollectionProperty(type=I3D_CL_PopularColorItem)
    bpy.types.Scene.i3d_cl_popular_index = bpy.props.IntProperty(default=0)

    bpy.types.Scene.i3d_cl_show_files = bpy.props.BoolProperty(
        name="Share & Import",
        default=True,
    )

    _on_load_post(None)

    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    if _on_save_pre not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_on_save_pre)


def unregister():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if _on_save_pre in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(_on_save_pre)

    # Scene properties
    for attr in (
        "i3d_cl_tab",
        "i3d_cl_my_colors",
        "i3d_cl_my_index",
        "i3d_cl_giants_brand",
        "i3d_cl_giants_colors",
        "i3d_cl_giants_index",
        "i3d_cl_popular_brand",
        "i3d_cl_popular_colors",
        "i3d_cl_popular_index",
        "i3d_cl_show_files",
    ):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)

    for c in reversed(classes):
        bpy.utils.unregister_class(c)
