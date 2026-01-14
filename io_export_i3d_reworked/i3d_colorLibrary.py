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
import re
import zlib
import time
import shutil
import hashlib
import tempfile
import zipfile
import urllib.request
import urllib.parse
import urllib.error
import ssl
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

import bpy
import bpy.utils.previews
from bpy_extras.io_utils import ExportHelper, ImportHelper

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

# Runtime-only storage for temporary preview original states (avoid polluting Material custom properties).
# Keyed by material pointer for the current Blender session only.
_I3D_PREVIEW_ORIG_METHODS: Dict[int, Dict[str, str]] = {}

# -----------------------------------------------------------------------------
# Decal thumbnail previews (My Color Library UIList)
# -----------------------------------------------------------------------------

_I3D_CL_DECAL_PREVIEWS = None  # bpy.utils.previews.ImagePreviewCollection

def _cl_decal_previews_get():
    """Get (or create) the preview collection for decal thumbnails."""
    global _I3D_CL_DECAL_PREVIEWS
    try:
        if _I3D_CL_DECAL_PREVIEWS is None:
            _I3D_CL_DECAL_PREVIEWS = bpy.utils.previews.new()
    except Exception:
        _I3D_CL_DECAL_PREVIEWS = None
    return _I3D_CL_DECAL_PREVIEWS


def _cl_decal_previews_free():
    """Free the preview collection to avoid leaks on addon reload/unregister."""
    global _I3D_CL_DECAL_PREVIEWS
    if _I3D_CL_DECAL_PREVIEWS is not None:
        try:
            bpy.utils.previews.remove(_I3D_CL_DECAL_PREVIEWS)
        except Exception:
            pass
    _I3D_CL_DECAL_PREVIEWS = None


def _cl_decal_icon_id(filepath: str) -> int:
    """Return an icon_id for the given decal image path, or 0 if unavailable."""
    if not filepath:
        return 0
    try:
        fp = bpy.path.abspath(str(filepath))
    except Exception:
        fp = str(filepath)
    try:
        fp = os.path.normpath(fp)
    except Exception:
        pass
    try:
        if not os.path.exists(fp):
            return 0
    except Exception:
        return 0

    pcoll = _cl_decal_previews_get()
    if pcoll is None:
        return 0

    key = fp  # unique per absolute file path
    try:
        if key not in pcoll:
            pcoll.load(key, fp, 'IMAGE')
        return int(pcoll[key].icon_id)
    except Exception:
        return 0


def _preview_key_for_material(mat: bpy.types.Material) -> int:
    try:
        return int(mat.as_pointer())
    except Exception:
        return int(id(mat))

def _store_preview_methods(mat: bpy.types.Material) -> None:
    if not mat:
        return
    key = _preview_key_for_material(mat)
    if key in _I3D_PREVIEW_ORIG_METHODS:
        return
    try:
        # Prefer legacy stored originals if present (older builds), otherwise use current values.
        bm = str(mat.get("i3d_preview_blend_method_orig", getattr(mat, "blend_method", "")))
        sm = str(mat.get("i3d_preview_shadow_method_orig", getattr(mat, "shadow_method", "")))
        _I3D_PREVIEW_ORIG_METHODS[key] = {
            "blend_method": bm,
            "shadow_method": sm,
        }
    except Exception:
        # Nothing critical; preview still works, we just won't restore methods.
        return

    # Cleanup legacy props so they don't show in Material custom properties.
    try:
        if "i3d_preview_blend_method_orig" in mat:
            del mat["i3d_preview_blend_method_orig"]
    except Exception:
        pass
    try:
        if "i3d_preview_shadow_method_orig" in mat:
            del mat["i3d_preview_shadow_method_orig"]
    except Exception:
        pass

def _restore_preview_methods(mat: bpy.types.Material) -> None:
    if not mat:
        return
    key = _preview_key_for_material(mat)
    state = _I3D_PREVIEW_ORIG_METHODS.pop(key, None)

    # Legacy fallback: older builds stored these in Material custom properties.
    legacy_bm = None
    legacy_sm = None
    try:
        if "i3d_preview_blend_method_orig" in mat:
            legacy_bm = str(mat.get("i3d_preview_blend_method_orig", ""))
        if "i3d_preview_shadow_method_orig" in mat:
            legacy_sm = str(mat.get("i3d_preview_shadow_method_orig", ""))
    except Exception:
        pass

    bm = None
    sm = None
    if state:
        try:
            bm = state.get("blend_method") or None
            sm = state.get("shadow_method") or None
        except Exception:
            bm = None
            sm = None
    if not bm and legacy_bm:
        bm = legacy_bm
    if not sm and legacy_sm:
        sm = legacy_sm

    try:
        if bm:
            mat.blend_method = bm
        if sm:
            mat.shadow_method = sm
    except Exception:
        pass

    # Cleanup legacy props so they don't show in Material custom properties.
    try:
        if "i3d_preview_blend_method_orig" in mat:
            del mat["i3d_preview_blend_method_orig"]
    except Exception:
        pass
    try:
        if "i3d_preview_shadow_method_orig" in mat:
            del mat["i3d_preview_shadow_method_orig"]
    except Exception:
        pass

def _store_path() -> Path:
    # Store in Blender user config so library survives add-on updates.
    base = bpy.utils.user_resource('CONFIG') or ""
    base_path = Path(base) if base else Path.home() / ".blender"
    d = base_path / _STORE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d / _STORE_FILENAME



# -----------------------------------------------------------------------------
# Optional: Bundle decal images when exporting/importing My Color Library
# -----------------------------------------------------------------------------

_MY_COLORS_BUNDLE_JSON_NAME = "my_color_library.json"
_MY_COLORS_BUNDLE_DECALS_DIRNAME = "decals"

def _store_dir() -> Path:
    """Return the persistent storage folder used by this add-on."""
    return _store_path().parent

def _decal_store_dir() -> Path:
    """Persistent decal asset folder (survives add-on updates)."""
    d = _store_dir() / _MY_COLORS_BUNDLE_DECALS_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d

def _make_unique_dest_path(dest_dir: Path, filename: str) -> Path:
    """Return a unique path in dest_dir based on filename (adds _2, _3, ...)."""
    base = Path(filename).stem
    ext = Path(filename).suffix
    candidate = dest_dir / f"{base}{ext}"
    i = 2
    while candidate.exists():
        candidate = dest_dir / f"{base}_{i}{ext}"
        i += 1
    return candidate

_DECAL_CACHE_INDEX_FILENAME = "decal_cache_index.json"

def _decal_cache_index_path() -> Path:
    return _decal_store_dir() / _DECAL_CACHE_INDEX_FILENAME

def _load_decal_cache_index() -> Dict[str, str]:
    try:
        p = _decal_cache_index_path()
        if not p.exists():
            return {}
        raw = p.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _save_decal_cache_index(idx: Dict[str, str]) -> None:
    try:
        p = _decal_cache_index_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(idx, indent=2), encoding="utf-8")
    except Exception:
        pass

def _sha1_file(p: Path) -> str:
    try:
        h = hashlib.sha1()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _copy_decal_to_store(src: Path) -> str:
    """Copy src image to the persistent decal store and return the new absolute filepath.

    Dedupe behavior:
    - If an identical file (by SHA1) already exists in the decal store, reuse it instead of writing duplicates (_2, _3, ...).
    """
    try:
        src = Path(src)
        if not src.exists() or not src.is_file():
            return ""
        dest_dir = _decal_store_dir()

        file_hash = _sha1_file(src)
        idx = _load_decal_cache_index()

        if file_hash:
            existing_name = idx.get(file_hash, "")
            if existing_name:
                existing_path = (dest_dir / existing_name)
                if existing_path.exists():
                    return str(existing_path)

        ext = src.suffix
        stem = src.stem
        tag = (file_hash[:8] if file_hash else str(int(time.time())))
        dest = dest_dir / f"{stem}_{tag}{ext}"

        if dest.exists():
            dest = _make_unique_dest_path(dest_dir, src.name)

        shutil.copy2(str(src), str(dest))

        if file_hash:
            idx[file_hash] = dest.name
            _save_decal_cache_index(idx)

        return str(dest)
    except Exception:
        return ""

def _resolve_decal_path_for_import(decal_path: str, *, base_dir: Path) -> str:
    """Resolve a decal path from JSON to an absolute path, if possible."""
    try:
        dp = str(decal_path or "").strip()
        if not dp:
            return ""
        # Blender relative paths (//)
        if dp.startswith("//"):
            ap = Path(bpy.path.abspath(dp))
            if ap.exists():
                return str(ap)
        # Relative path inside a bundle (e.g. decals/foo.png)
        p = Path(dp)
        if not p.is_absolute():
            ap = (base_dir / p).resolve()
            if ap.exists():
                return str(ap)
        # Absolute path as-is
        if p.is_absolute() and p.exists():
            return str(p)
        return dp
    except Exception:
        return str(decal_path or "")

def _import_postprocess_decal_paths(data: Any, *, base_dir: Path, copy_assets_to_store: bool) -> Any:
    """Resolve decal_image_path entries and optionally copy images into the persistent store."""
    if not isinstance(data, list):
        return data
    for row in data:
        if not isinstance(row, dict):
            continue
        dp = str(row.get("decal_image_path", "") or "").strip()
        if not dp:
            continue

        resolved = _resolve_decal_path_for_import(dp, base_dir=base_dir)

        # If resolved points to a real file and we want persistence, copy it into the decal store.
        try:
            rp = Path(resolved)
            if copy_assets_to_store and rp.exists() and rp.is_file():
                stored = _copy_decal_to_store(rp)
                if stored:
                    row["decal_image_path"] = stored
                else:
                    row["decal_image_path"] = resolved
            else:
                row["decal_image_path"] = resolved
        except Exception:
            row["decal_image_path"] = resolved

    return data

def save_my_colors_bundle_to_zip(zip_path: Path) -> bool:
    """Export My Color Library as a ZIP: JSON + copied decal images for sharing."""
    scene = bpy.context.scene
    if not scene:
        return False

    try:
        payload = _serialize_my(scene)

        # Build mapping of absolute decal paths -> bundle relative paths.
        bundle_decals: Dict[str, str] = {}
        bundle_files: Dict[str, bytes] = {}

        for row in payload:
            dp = str(row.get("decal_image_path", "") or "").strip()
            if not dp:
                continue

            # Resolve Blender // paths to absolute.
            resolved = dp
            if dp.startswith("//"):
                resolved = bpy.path.abspath(dp)

            src = Path(resolved)
            if (not src.is_absolute()) or (not src.exists()):
                # If the path isn't valid, keep it as-is (user may still want the reference).
                continue

            src_key = str(src.resolve())
            if src_key in bundle_decals:
                row["decal_image_path"] = bundle_decals[src_key]
                continue

            rel_name = src.name
            # Ensure unique name within the bundle
            rel_path = f"{_MY_COLORS_BUNDLE_DECALS_DIRNAME}/{rel_name}"
            i = 2
            while rel_path in bundle_files:
                rel_name = f"{src.stem}_{i}{src.suffix}"
                rel_path = f"{_MY_COLORS_BUNDLE_DECALS_DIRNAME}/{rel_name}"
                i += 1

            try:
                data_bytes = src.read_bytes()
            except Exception:
                continue

            bundle_decals[src_key] = rel_path
            bundle_files[rel_path] = data_bytes
            row["decal_image_path"] = rel_path  # Store relative path inside the bundle.

        zip_path = Path(zip_path)
        zip_path.parent.mkdir(parents=True, exist_ok=True)

        # Write zip
        with zipfile.ZipFile(str(zip_path), "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(_MY_COLORS_BUNDLE_JSON_NAME, json.dumps(payload, indent=2))
            for rel_path, data_bytes in bundle_files.items():
                zf.writestr(rel_path, data_bytes)

        return True
    except Exception:
        return False

def load_my_colors_from_zip(
    zip_path: Path,
    *,
    replace: bool,
    ignore_duplicate_color_material: bool = False,
) -> int:
    """Import My Color Library from a ZIP bundle (JSON + decal images)."""
    try:
        zip_path = Path(zip_path)
        if not zip_path.exists():
            return 0

        with zipfile.ZipFile(str(zip_path), "r") as zf:
            # Find JSON manifest
            json_name = _MY_COLORS_BUNDLE_JSON_NAME
            if json_name not in zf.namelist():
                # Fallback: first .json in the zip
                candidates = [n for n in zf.namelist() if n.lower().endswith(".json")]
                if not candidates:
                    return 0
                json_name = candidates[0]

            raw = zf.read(json_name).decode("utf-8", errors="replace")
            data = json.loads(raw) if raw.strip() else []

            # Extract decals to a temp dir, then copy into persistent store
            with tempfile.TemporaryDirectory(prefix="i3d_cl_import_") as td:
                temp_dir = Path(td)

                # Extract everything (small zips), then resolve relative decal paths.
                zf.extractall(str(temp_dir))

                # Resolve and copy decals into persistent store
                data = _import_postprocess_decal_paths(
                    data,
                    base_dir=temp_dir,
                    copy_assets_to_store=True
                )

        scene = bpy.context.scene
        if not scene:
            return 0
        return _apply_my(
            scene,
            data,
            replace=replace,
            ignore_duplicate_color_material=ignore_duplicate_color_material,
        )
    except Exception:
        return 0


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
    try:
        if (not _FORCE_COLOR_SUSPEND) and bool(getattr(self, "xml_color_locked", False)):
            _enforce_forced_color_on_item(self)
    except Exception:
        pass
    schedule_save()


_MY_NAME_UPDATE_GUARD = False

def _on_my_name_update(self, context):
    """Enforce unique names (across ALL libraries) when user edits My Library item names."""
    global _MY_NAME_UPDATE_GUARD

    # Prevent recursion when we assign self.name inside this update callback.
    if _MY_NAME_UPDATE_GUARD:
        schedule_save()
        return

    scene = getattr(context, "scene", None)
    if scene is None:
        schedule_save()
        return

    desired = (getattr(self, "name", "") or "").strip() or "New Color"
    desired = desired[:80]
    unique = _ensure_unique_my_library_name(scene, desired, exclude_my_item=self)

    if unique != getattr(self, "name", ""):
        _MY_NAME_UPDATE_GUARD = True
        try:
            self.name = unique
        finally:
            _MY_NAME_UPDATE_GUARD = False

    schedule_save()



# -----------------------------------------------------------------------------
# XML export selection state (cross-library)
# -----------------------------------------------------------------------------

_XML_SYNC_SUSPEND = False


def _xml_format_trim3(x: float) -> str:
    try:
        s = f"{float(x):.3f}"
        s = s.rstrip("0").rstrip(".")
        return s if s else "0"
    except Exception:
        return "0"


def _xml_key_for_my(item):
    nm = (getattr(item, "name", "") or "").strip()
    # Snap to stable 8-bit sRGB for consistent keys.
    cs = _giants_srgb_text(getattr(item, "color", (1.0, 1.0, 1.0)))
    return f"MY|{nm}|{cs}"


def _xml_key_for_giants(item):
    brand = (getattr(item, "brand", "") or "").strip()
    nm = (getattr(item, "name", "") or "").strip()
    cs = (getattr(item, "colorScale", "") or "").strip() or _giants_srgb_text(getattr(item, "color", (1.0, 1.0, 1.0)))
    return f"GIANTS|{brand}|{nm}|{cs}"


def _xml_key_for_popular(item):
    brand = (getattr(item, "brand", "") or "").strip()
    nm = (getattr(item, "name", "") or "").strip()
    cs = (getattr(item, "colorScale", "") or "").strip() or _giants_srgb_text(getattr(item, "color", (1.0, 1.0, 1.0)))
    return f"POPULAR|{brand}|{nm}|{cs}"


def _xml_find_selected(scene, key: str) -> int:
    try:
        for i, it in enumerate(scene.i3d_cl_xml_selected_colors):
            if (it.key or "") == key:
                return i
    except Exception:
        pass
    return -1




def _xml_material_template_from_item(item) -> str:
    """Return the export string value for the item's Material Type dropdown."""
    try:
        enum_id = getattr(item, "xml_material_template", "NONE") or "NONE"
        return (_mt_value_from_enum_id(enum_id) or "").strip()
    except Exception:
        return ""


def _mtpl_forces_color_change(template_name: str) -> bool:
    """True if selecting this Material Type would force a swatch color change (locked templates).

    Used to block those templates in the POPULAR library so presets never get overridden.
    """
    s = (str(template_name or "").strip().lower())
    if not s or s in {"none", "null", "0"}:
        return False

    # wood1/wood2 are tintable in GE (do not force)
    if s in {"wood1", "wood2"}:
        return False

    # Glass is tintable (do not force)
    if "glass" in s or "window" in s:
        return False

    # If template declares a colorScale, selecting it forces that color.
    try:
        if _mtpl_colorscale_rgb(template_name) is not None:
            return True
    except Exception:
        pass

    # Common fixed-color variants.
    if "black" in s:
        return True
    if ("grey" in s) or ("gray" in s) or ("graphite" in s):
        return True
    if "white" in s:
        return True

    # Fixed wood species (non-tintable).
    if any(k in s for k in ("cedar", "oak", "pine", "spruce", "walnut", "cherry", "mahogany", "teak", "birch", "maple")):
        return True

    return False
def _xml_add_selected(scene, *, key: str, name: str, color, source: str, brand: str = "", materialTemplate: str = "") -> None:
    if not key:
        return
    if _xml_find_selected(scene, key) >= 0:
        return
    try:
        it = scene.i3d_cl_xml_selected_colors.add()
        it.key = key
        it.name = name
        it.source = source
        it.brand = brand
        it.materialTemplate = (materialTemplate or "").strip()
        it.color = _norm_color(color)
    except Exception:
        pass


def _xml_get_selected_material_template(scene, key: str) -> str:
    idx = _xml_find_selected(scene, key)
    if idx < 0:
        return ""
    try:
        return str(scene.i3d_cl_xml_selected_colors[idx].materialTemplate or "").strip()
    except Exception:
        return ""


def _xml_set_selected_material_template(scene, key: str, materialTemplate: str) -> None:
    idx = _xml_find_selected(scene, key)
    if idx < 0:
        return
    try:
        scene.i3d_cl_xml_selected_colors[idx].materialTemplate = (materialTemplate or "").strip()
    except Exception:
        pass


def _xml_remove_selected(scene, key: str) -> None:
    idx = _xml_find_selected(scene, key)
    if idx < 0:
        return
    try:
        scene.i3d_cl_xml_selected_colors.remove(idx)
    except Exception:
        pass


def _xml_sync_from_toggle(scene, *, src: str, item, selected: bool) -> None:
    global _XML_SYNC_SUSPEND
    if _XML_SYNC_SUSPEND:
        return

    if src == "MY":
        key = _xml_key_for_my(item)
        brand = ""
    elif src == "GIANTS":
        key = _xml_key_for_giants(item)
        brand = (getattr(item, "brand", "") or "").strip()
    else:
        key = _xml_key_for_popular(item)
        brand = (getattr(item, "brand", "") or "").strip()

    nm = (getattr(item, "name", "") or "").strip()
    col = getattr(item, "color", (1.0, 1.0, 1.0))

    if selected:
        _xml_add_selected(scene, key=key, name=nm, color=col, source=src, brand=brand, materialTemplate=_xml_material_template_from_item(item) if src in {"MY","POPULAR"} else "")
    else:
        _xml_remove_selected(scene, key)


class I3D_CL_XMLSelectedColorItem(bpy.types.PropertyGroup):
    key: bpy.props.StringProperty(name="Key", default="")
    name: bpy.props.StringProperty(name="Name", default="")
    source: bpy.props.StringProperty(name="Source", default="")
    brand: bpy.props.StringProperty(name="Brand", default="")
    materialTemplate: bpy.props.StringProperty(name="Material Template", default="")
    color: bpy.props.FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        size=3,
        default=(1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
    )


def _on_xml_selected_my(self, context):
    try:
        _xml_sync_from_toggle(context.scene, src="MY", item=self, selected=bool(getattr(self, "xml_selected", False)))
    except Exception:
        pass


def _on_xml_selected_giants(self, context):
    try:
        _xml_sync_from_toggle(context.scene, src="GIANTS", item=self, selected=bool(getattr(self, "xml_selected", False)))
    except Exception:
        pass


def _on_xml_selected_popular(self, context):
    try:
        _xml_sync_from_toggle(context.scene, src="POPULAR", item=self, selected=bool(getattr(self, "xml_selected", False)))
    except Exception:
        pass

def _on_xml_material_template_my(self, context):
    global _XML_SYNC_SUSPEND
    if _XML_SYNC_SUSPEND:
        return
    try:
        key = _xml_key_for_my(self)
        _xml_set_selected_material_template(context.scene, key, _xml_material_template_from_item(self))
    except Exception:
        pass

    try:
        _enforce_forced_color_on_item(self)
    except Exception:
        pass

    schedule_save()


def _on_xml_material_template_popular(self, context):
    global _XML_SYNC_SUSPEND
    if _XML_SYNC_SUSPEND:
        return
    # POPULAR library: do not allow Material Types that force a swatch color change.
    try:
        mt = _xml_material_template_from_item(self)
        if _mtpl_forces_color_change(mt):
            _XML_SYNC_SUSPEND = True
            try:
                self.xml_material_template = "NONE"
                if hasattr(self, "xml_color_locked"):
                    self.xml_color_locked = False
            finally:
                _XML_SYNC_SUSPEND = False
            try:
                key = _xml_key_for_popular(self)
                _xml_set_selected_material_template(context.scene, key, "")
            except Exception:
                pass
            schedule_save()
            return
    except Exception:
        pass
    try:
        key = _xml_key_for_popular(self)
        _xml_set_selected_material_template(context.scene, key, _xml_material_template_from_item(self))
    except Exception:
        pass

    try:
        _enforce_forced_color_on_item(self)
    except Exception:
        pass

    schedule_save()



def _xml_any_color_selected(scene) -> bool:
    try:
        return len(scene.i3d_cl_xml_selected_colors) > 0
    except Exception:
        return False


# -----------------------------------------------------------------------------
# XML Mode: Material Type (materialTemplateName) dropdown support
# -----------------------------------------------------------------------------
#
# DTAP request:
# - The dropdown list must be parsed from:
#     $data/shared/detailLibrary/materialTemplates.xml
# - The dropdown values are the <template name="..."> names from that file.
# - We also keep a small "extra" set to preserve imported/legacy values that
#   might not exist in the user's current FS install (so enum values don't break).

_MTPL_XML_MATERIAL_TEMPLATES_PATH = "$data/shared/detailLibrary/materialTemplates.xml"

_MTPL_CACHE_PATH: str = ""
_MTPL_CACHE_MTIME: float = -1.0
_MTPL_CACHE_NAMES: List[str] = []
_MTPL_CACHE_BY_NAME: Dict[str, Dict[str, str]] = {}
_MTPL_CACHE_LOWER_TO_NAME: Dict[str, str] = {}

# -----------------------------------------------------------------------------
# Material Template Apply Overrides (used by Apply TEMP/PERM flows)
# -----------------------------------------------------------------------------
# NOTE: These are intentionally global so we can avoid signature churn in existing
# Apply operators (Blender add-on stability).
_MTPL_OVERRIDE_DETAIL_DIFFUSE_MODE: str = ""  # "", "SKIP", "ROUGHNESS", "ALBEDO", "ALBEDO_TINT", "DECAL"
_MTPL_OVERRIDE_DECAL_IMAGE_PATH: str = ""
_MTPL_OVERRIDE_DECAL_PERSIST: bool = False
_MTPL_OVERRIDE_APPLY_ALPHA: Optional[bool] = None  # None = auto, True/False = force
_MTPL_OVERRIDE_FORCED_TINT: Optional[Tuple[float, float, float]] = None

def _mtpl_clear_overrides() -> None:
    global _MTPL_OVERRIDE_DETAIL_DIFFUSE_MODE, _MTPL_OVERRIDE_DECAL_IMAGE_PATH, _MTPL_OVERRIDE_DECAL_PERSIST
    global _MTPL_OVERRIDE_APPLY_ALPHA, _MTPL_OVERRIDE_FORCED_TINT
    _MTPL_OVERRIDE_DETAIL_DIFFUSE_MODE = ""
    _MTPL_OVERRIDE_DECAL_IMAGE_PATH = ""
    _MTPL_OVERRIDE_DECAL_PERSIST = False
    _MTPL_OVERRIDE_APPLY_ALPHA = None
    _MTPL_OVERRIDE_FORCED_TINT = None

from contextlib import contextmanager

@contextmanager
def _mtpl_apply_overrides(*,
    detail_diffuse_mode: str = "",
    decal_image_path: str = "",
    decal_persist: bool = False,
    apply_alpha: Optional[bool] = None,
    forced_tint: Optional[Tuple[float, float, float]] = None,
):
    global _MTPL_OVERRIDE_DETAIL_DIFFUSE_MODE, _MTPL_OVERRIDE_DECAL_IMAGE_PATH, _MTPL_OVERRIDE_DECAL_PERSIST
    global _MTPL_OVERRIDE_APPLY_ALPHA, _MTPL_OVERRIDE_FORCED_TINT
    _prev = (
        _MTPL_OVERRIDE_DETAIL_DIFFUSE_MODE,
        _MTPL_OVERRIDE_DECAL_IMAGE_PATH,
        _MTPL_OVERRIDE_DECAL_PERSIST,
        _MTPL_OVERRIDE_APPLY_ALPHA,
        _MTPL_OVERRIDE_FORCED_TINT,
    )
    try:
        if detail_diffuse_mode is not None:
            _MTPL_OVERRIDE_DETAIL_DIFFUSE_MODE = str(detail_diffuse_mode or "")
        if decal_image_path is not None:
            _MTPL_OVERRIDE_DECAL_IMAGE_PATH = str(decal_image_path or "")
        _MTPL_OVERRIDE_DECAL_PERSIST = bool(decal_persist)
        _MTPL_OVERRIDE_APPLY_ALPHA = apply_alpha
        _MTPL_OVERRIDE_FORCED_TINT = forced_tint
        yield
    finally:
        (
            _MTPL_OVERRIDE_DETAIL_DIFFUSE_MODE,
            _MTPL_OVERRIDE_DECAL_IMAGE_PATH,
            _MTPL_OVERRIDE_DECAL_PERSIST,
            _MTPL_OVERRIDE_APPLY_ALPHA,
            _MTPL_OVERRIDE_FORCED_TINT,
        ) = _prev


_MTPL_LAST_ERROR: str = ""

_MTPL_STAT_THROTTLE_S: float = 0.75
_MTPL_LAST_STAT_CHECK: float = 0.0

_MTPL_EXTRA_NAMES: Set[str] = set()


def _mtpl_resolve_path() -> str:
    game_path = getGamePath()
    return resolveGiantsPath(_MTPL_XML_MATERIAL_TEMPLATES_PATH, game_path)


def _prefer_dds(filepath: str) -> str:
    # GIANTS usually ships PNG references but prefers DDS at runtime.
    # DTAP note: GIANTS auto-assumes all .png end in .dds.
    p = (filepath or "").strip()
    if not p:
        return p
    root, ext = os.path.splitext(p)
    if ext.lower() == ".png":
        dds = root + ".dds"
        try:
            if os.path.isfile(dds):
                return dds
        except Exception:
            pass
    return p


def ensure_material_templates_cache(*, force: bool = False) -> bool:
    """Parse and cache $data/shared/detailLibrary/materialTemplates.xml.

    Returns True when cache is ready; False when file missing or parse failed.
    """
    global _MTPL_CACHE_PATH, _MTPL_CACHE_MTIME, _MTPL_CACHE_NAMES, _MTPL_CACHE_BY_NAME, _MTPL_CACHE_LOWER_TO_NAME, _MTPL_LAST_ERROR

    global _MTPL_LAST_STAT_CHECK
    now = time.time()
    if (not force) and _MTPL_LAST_STAT_CHECK and (now - _MTPL_LAST_STAT_CHECK) < _MTPL_STAT_THROTTLE_S:
        return bool(_MTPL_CACHE_NAMES)
    _MTPL_LAST_STAT_CHECK = now

    xml_path = _mtpl_resolve_path()
    if not xml_path:
        _MTPL_LAST_ERROR = "Game Install Path not set (cannot resolve $data path)."
        _MTPL_CACHE_PATH = ""
        _MTPL_CACHE_MTIME = -1.0
        _MTPL_CACHE_NAMES = []
        _MTPL_CACHE_BY_NAME = {}
        _MTPL_CACHE_LOWER_TO_NAME = {}
        return False

    if not os.path.isfile(xml_path):
        _MTPL_LAST_ERROR = f"Missing file: {xml_path}"
        _MTPL_CACHE_PATH = xml_path
        _MTPL_CACHE_MTIME = -1.0
        _MTPL_CACHE_NAMES = []
        _MTPL_CACHE_BY_NAME = {}
        _MTPL_CACHE_LOWER_TO_NAME = {}
        return False

    try:
        mtime = os.path.getmtime(xml_path)
    except Exception:
        mtime = -1.0

    if (not force) and _MTPL_CACHE_PATH == xml_path and _MTPL_CACHE_MTIME == mtime and _MTPL_CACHE_NAMES:
        return True

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        names: List[str] = []
        by_name: Dict[str, Dict[str, str]] = {}
        lower_map: Dict[str, str] = {}

        for el in root.iter():
            if (str(el.tag).split("}")[-1] != "template"):
                continue
            nm = (el.attrib.get("name") or "").strip()
            if not nm:
                continue

            # Store useful detail map attributes for preview injection.
            # Support both attribute-style (<template detailDiffuse="..."/>) and child-style
            # (<template><detailDiffuse>...</detailDiffuse></template>).
            detail_diffuse = (el.attrib.get("detailDiffuse") or "").strip()
            detail_specular = (el.attrib.get("detailSpecular") or "").strip()
            detail_normal = (el.attrib.get("detailNormal") or "").strip()
            if not detail_diffuse:
                detail_diffuse = (el.findtext("detailDiffuse") or "").strip()
            if not detail_specular:
                detail_specular = (el.findtext("detailSpecular") or "").strip()
            if not detail_normal:
                detail_normal = (el.findtext("detailNormal") or "").strip()

            category = (el.attrib.get("category") or "").strip()
            title = (el.attrib.get("title") or "").strip()
            icon_filename = (el.attrib.get("iconFilename") or "").strip()
            color_scale = (el.attrib.get("colorScale") or "").strip()
            if not category:
                category = (el.findtext("category") or "").strip()
            if not title:
                title = (el.findtext("title") or "").strip()
            if not icon_filename:
                icon_filename = (el.findtext("iconFilename") or "").strip()
            if not color_scale:
                color_scale = (el.findtext("colorScale") or "").strip()

            game_path = getGamePath()
            # Resolve $data paths if present.
            if detail_diffuse:
                detail_diffuse = _prefer_dds(resolveGiantsPath(detail_diffuse, game_path))
            if detail_specular:
                detail_specular = _prefer_dds(resolveGiantsPath(detail_specular, game_path))
            if detail_normal:
                detail_normal = _prefer_dds(resolveGiantsPath(detail_normal, game_path))

            
            smoothness_scale = (el.attrib.get("smoothnessScale") or "").strip()
            metalness_scale = (el.attrib.get("metalnessScale") or "").strip()
            clearcoat_intensity = (el.attrib.get("clearCoatIntensity") or "").strip()
            clearcoat_smoothness = (el.attrib.get("clearCoatSmoothness") or "").strip()
            porosity = (el.attrib.get("porosity") or "").strip()
            if not smoothness_scale:
                smoothness_scale = (el.findtext("smoothnessScale") or "").strip()
            if not metalness_scale:
                metalness_scale = (el.findtext("metalnessScale") or "").strip()
            if not clearcoat_intensity:
                clearcoat_intensity = (el.findtext("clearCoatIntensity") or "").strip()
            if not clearcoat_smoothness:
                clearcoat_smoothness = (el.findtext("clearCoatSmoothness") or "").strip()
            if not porosity:
                porosity = (el.findtext("porosity") or "").strip()

            by_name[nm] = {
                "name": nm,
                "category": category,
                "title": title,
                "iconFilename": icon_filename,
                "colorScale": color_scale,
                "detailDiffuse": detail_diffuse,
                "detailSpecular": detail_specular,
                "detailNormal": detail_normal,
                "smoothnessScale": smoothness_scale,
                "metalnessScale": metalness_scale,
                "clearCoatIntensity": clearcoat_intensity,
                "clearCoatSmoothness": clearcoat_smoothness,
                "porosity": porosity,
            }
            names.append(nm)
            lower_map[nm.lower()] = nm

        names = sorted(set(names), key=lambda s: s.lower())

        _MTPL_CACHE_PATH = xml_path
        _MTPL_CACHE_MTIME = mtime
        _MTPL_CACHE_NAMES = names
        _MTPL_CACHE_BY_NAME = by_name
        _MTPL_CACHE_LOWER_TO_NAME = lower_map
        _MTPL_LAST_ERROR = ""
        return True

    except Exception as e:
        _MTPL_LAST_ERROR = f"Failed to parse materialTemplates.xml: {e}"
        _MTPL_CACHE_PATH = xml_path
        _MTPL_CACHE_MTIME = mtime
        _MTPL_CACHE_NAMES = []
        _MTPL_CACHE_BY_NAME = {}
        _MTPL_CACHE_LOWER_TO_NAME = {}
        return False


def _mtpl_canonical_name(name: str) -> str:
    if not name:
        return ""
    ensure_material_templates_cache(force=False)
    s = str(name).strip()
    if not s:
        return ""
    if s in _MTPL_CACHE_BY_NAME:
        return s
    low = s.lower()
    if low in _MTPL_CACHE_LOWER_TO_NAME:
        return _MTPL_CACHE_LOWER_TO_NAME[low]
    return s


# -----------------------------------------------------------------------------
# Material Template: forced color + permanent block helpers (DTAP)
# -----------------------------------------------------------------------------

_WARNING_PERM_BLOCKED_TEXT = "the Material Type Selected does not allow Applying as Permanent to Material for Export"

_FORCE_COLOR_SUSPEND = False


def _mtpl_colorscale_rgb(template_name: str) -> Optional[Tuple[float, float, float]]:
    """Return (r,g,b) from materialTemplates.xml colorScale for template_name, or None."""
    try:
        ensure_material_templates_cache(force=False)
        nm = _mtpl_canonical_name(template_name)
        info = _MTPL_CACHE_BY_NAME.get(nm) or _MTPL_CACHE_BY_NAME.get(template_name) or {}
        cs = str(info.get("colorScale", "") or "").strip()
        if not cs:
            return None
        parts = cs.split()
        if len(parts) < 3:
            return None
        r = _clamp01(_safe_float(parts[0], 0.0))
        g = _clamp01(_safe_float(parts[1], 0.0))
        b = _clamp01(_safe_float(parts[2], 0.0))
        return (r, g, b)
    except Exception:
        return None



def _mtpl_blocks_permanent(template_name: str) -> bool:
    """True if template cannot be applied as Permanent material.

    Rule of thumb:
    - If it requires vehicleShader math (alpha, reflector, forced colorScale-based metals), block.
    - Decals are explicitly allowed (DTAP request).
    """
    s = str(template_name or "").strip().lower()
    if not s or s in {"none", "null"}:
        return False

    # Explicitly allow decals permanent (DTAP request).
    if "decal" in s:
        return False

    # Vehicle shader required: glass alpha / IOR / tint, reflector, etc.
    if "glass" in s:
        return True
    if "reflector" in s:
        return True

    # Color-in-name metals that rely on colorScale + shared diffuse/spec (vehicle shader multiplies)
    # If a template declares a colorScale and also looks like a "scratched/brushed" metal, block permanent.
    if any(k in s for k in ("scratched", "brushed", "polished")):
        try:
            if _mtpl_colorscale_rgb(template_name) is not None:
                return True
        except Exception:
            pass

    return False


def _enforce_forced_color_on_item(item) -> None:
    """Apply any forced swatch behavior based on selected Material Type.

    Rules:
    - If template declares a colorScale: force that color and lock swatch (EXCEPT wood1/wood2).
    - Glass templates: do NOT lock swatch (tintable). Transparency is previewed via injected alpha.
    - Fixed-color variants without colorScale (e.g. *Black/*Gray/*Graphite): lock swatch.
    - Fixed wood species (cedar/oak/etc): lock swatch.

    NOTE: This only affects the UI swatch + the color written into Principled defaults;
    the preview node injector decides how detailDiffuse is routed.
    """
    global _FORCE_COLOR_SUSPEND
    if _FORCE_COLOR_SUSPEND:
        return

    # Resolve selected materialTemplate name
    try:
        mt_raw = _xml_material_template_from_item(item)
    except Exception:
        mt_raw = ""

    mt = _mtpl_canonical_name(mt_raw)
    s = (mt or "").lower().strip()

    # wood1/wood2 are tintable in Giants Editor; never swatch-lock them.
    if s in {"wood1", "wood2"}:
        if hasattr(item, "xml_color_locked"):
            item.xml_color_locked = False
        return
    # Forced via colorScale (reflectors, some scratched metals, etc.)
    rgb = None
    try:
        rgb = _mtpl_colorscale_rgb(mt)
    except Exception:
        rgb = None

    if rgb:
        if hasattr(item, "xml_color_locked"):
            item.xml_color_locked = True
        _FORCE_COLOR_SUSPEND = True
        try:
            item.color = rgb
        finally:
            _FORCE_COLOR_SUSPEND = False
        return

    # Fixed-color variants WITHOUT colorScale (common in detailLibrary)
    fixed_color = None
    if "black" in s:
        fixed_color = (0.0, 0.0, 0.0)
    elif "grey" in s or "gray" in s or "graphite" in s:
        fixed_color = (0.2, 0.2, 0.2)
    elif "white" in s:
        fixed_color = (1.0, 1.0, 1.0)

    fixed_wood = any(k in s for k in ("cedar", "oak", "pine", "spruce", "walnut", "cherry", "mahogany", "teak", "birch", "maple"))

    if fixed_color is not None or fixed_wood:
        if hasattr(item, "xml_color_locked"):
            item.xml_color_locked = True
        if fixed_color is not None:
            _FORCE_COLOR_SUSPEND = True
            try:
                item.color = fixed_color
            finally:
                _FORCE_COLOR_SUSPEND = False
        return

    # Default: unlocked
    if hasattr(item, "xml_color_locked"):
        item.xml_color_locked = False




def _mtpl_is_decal(template_name: str) -> bool:
    return "decal" in (str(template_name or "").lower())

def _mtpl_is_glass(template_name: str) -> bool:
    return "glass" in (str(template_name or "").lower())

def _mtpl_is_reflector(template_name: str) -> bool:
    return "reflector" in (str(template_name or "").lower())

def _mtpl_requires_refraction_map(template_name: str) -> bool:
    s = (str(template_name or "").lower())
    if not s:
        return False
    # Reflectors are handled by mirror shader reflection maps, not refraction maps.
    if "reflector" in s:
        return False
    # Obvious glass/window templates.
    if "glass" in s or "window" in s:
        return True
    # GIANTS vehicleShader metal/clearcoat templates that also expect a refractionMap toggle.
    if any(k in s for k in ("chrome", "silver", "gold", "palladium", "bronze")):
        return True
    return False

def _mtpl_name_uses_alpha(template_name: str) -> bool:
    s = (str(template_name or "").lower())
    if "alpha" in s or "cutout" in s or "mask" in s:
        return True
    if "decal" in s or "glass" in s or "window" in s:
        return True
    return False

def _mtpl_detail_normal_is_flat(template_name: str) -> bool:
    try:
        ensure_material_templates_cache(force=False)
        nm = _mtpl_canonical_name(template_name)
        info = _MTPL_CACHE_BY_NAME.get(nm) or {}
        dn = str(info.get("detailNormal","") or "").lower()
        return ("flat_normal" in os.path.basename(dn)) or ("flatnormal" in os.path.basename(dn))
    except Exception:
        return False

def _mtpl_detail_diffuse_is_clear(template_name: str) -> bool:
    try:
        ensure_material_templates_cache(force=False)
        nm = _mtpl_canonical_name(template_name)
        info = _MTPL_CACHE_BY_NAME.get(nm) or {}
        dd = str(info.get("detailDiffuse","") or "").lower()
        base = os.path.basename(dd)
        # heuristics: clear_diffuse or clear.dds in detailLibrary
        return ("clear" in base and "diffuse" in base) or (base.startswith("clear") and base.endswith(".dds"))
    except Exception:
        return False

def _mtpl_needs_detail_prompt(template_name: str) -> bool:
    """True if template likely needs detailDiffuse to look right (flat normal + non-clear diffuse)."""
    if not template_name:
        return False
    s = str(template_name).lower()
    if _mtpl_blocks_permanent(template_name):
        return False
    if _mtpl_is_decal(template_name):
        return False
    # if colorScale exists, we treat as forced color (no prompt)
    try:
        if _mtpl_colorscale_rgb(template_name) is not None:
            return False
    except Exception:
        pass
    # flat normal usually means diffuse/spec carry the 'look'
    if _mtpl_detail_normal_is_flat(template_name) and (not _mtpl_detail_diffuse_is_clear(template_name)):
        return True
    # keyword-based fallback
    if any(k in s for k in ("carbon", "pattern", "granite", "leather", "fabric", "wood", "tread", "powdercoat", "powder_coat", "calibrated", "noise", "scratched", "brushed")):
        return True
    return False



# Enum id mapping (Blender enum values must be <= 63 chars).
_MT_VALUE_TO_ENUM_ID: Dict[str, str] = {}
_MT_ENUM_ID_TO_VALUE: Dict[str, str] = {}

_MT_ITEMS_EXTRA_VERSION: int = 0
_MT_ITEMS_CACHE_DEFAULT: Dict[str, Any] = {"sig": None, "items": None}
_MT_ITEMS_CACHE_POPULAR: Dict[str, Any] = {"sig": None, "items": None}

def _mt_safe_enum_id(v: str) -> str:
    # Deterministic short id via crc32
    s = str(v or "")
    crc = zlib.crc32(s.encode("utf-8")) & 0xFFFFFFFF
    return f"MT_{crc:08X}"

def _mt_register_value(v: str) -> str:
    v = str(v or "").strip()
    if not v:
        return "NONE"
    if v.lower() in {"none", "null", "0"}:
        return "NONE"

    v = _mtpl_canonical_name(v)

    if v not in _MT_VALUE_TO_ENUM_ID:
        eid = _mt_safe_enum_id(v)
        # Keep stable even if collision occurs (very unlikely).
        while eid in _MT_ENUM_ID_TO_VALUE and _MT_ENUM_ID_TO_VALUE[eid] != v:
            eid = eid + "_X"
        _MT_VALUE_TO_ENUM_ID[v] = eid
        _MT_ENUM_ID_TO_VALUE[eid] = v

    # Preserve values not present in the current FS install so the enum doesn't break.
    if v and v not in _MTPL_CACHE_NAMES:
        global _MT_ITEMS_EXTRA_VERSION
        if v not in _MTPL_EXTRA_NAMES:
            _MTPL_EXTRA_NAMES.add(v)
            _MT_ITEMS_EXTRA_VERSION += 1

    return _MT_VALUE_TO_ENUM_ID[v]

def _mt_value_from_enum_id(eid: str) -> str:
    if not eid or eid == "NONE":
        return ""
    return _MT_ENUM_ID_TO_VALUE.get(eid, "")

def _mt_items(self, context):
    # Items callback for EnumProperty.
    ensure_material_templates_cache(force=False)

    is_popular = False
    try:
        is_popular = (getattr(self.__class__, '__name__', '') == 'I3D_CL_PopularColorItem')
    except Exception:
        is_popular = False

    sig = (_MTPL_CACHE_PATH, _MTPL_CACHE_MTIME, _MT_ITEMS_EXTRA_VERSION, 'POPULAR' if is_popular else 'DEFAULT')
    cache = _MT_ITEMS_CACHE_POPULAR if is_popular else _MT_ITEMS_CACHE_DEFAULT

    try:
        if cache.get("sig") == sig and cache.get("items"):
            return cache["items"]
    except Exception:
        pass

    values: List[str] = []
    values.extend(_MTPL_CACHE_NAMES or [])
    if _MTPL_EXTRA_NAMES:
        # Put extras at end, stable sort.
        for v in sorted(_MTPL_EXTRA_NAMES, key=lambda s: s.lower()):
            if v not in values:
                values.append(v)

    items = [("NONE", "None", "Do not set materialTemplateName")]
    for v in values:
        # POPULAR library: hide any Material Types that would force a swatch color change (and Decal).
        if is_popular:
            try:
                if _mtpl_forces_color_change(v) or _mtpl_is_decal(v):
                    continue
            except Exception:
                pass
        eid = _mt_register_value(v)
        items.append((eid, v, ""))

    cache["sig"] = sig
    cache["items"] = items
    return items



class I3D_CL_ColorItem(bpy.types.PropertyGroup):

    xml_selected: bpy.props.BoolProperty(
        name='Select',
        default=False,
        update=_on_xml_selected_my,
    )
    xml_material_template: bpy.props.EnumProperty(
        name="Material Type",
        description="Optional materialTemplateName to export when using XML mode",
        items=_mt_items,
        default=0,
        update=_on_xml_material_template_my,
    )
    xml_color_locked: bpy.props.BoolProperty(
        name="Color Locked",
        description="Internal: Material Type forces this color and locks the swatch",
        default=False,
        options={'HIDDEN'},
    )
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

    decal_image_path: bpy.props.StringProperty(
        name="Decal Image Path",
        description="For Decal Material Types: image file path used for Base Color/Alpha when applying decals from My Color Library.",
        default="",
        subtype='FILE_PATH',
        options={'HIDDEN'},
    )


def _serialize_my(scene: bpy.types.Scene) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in scene.i3d_cl_my_colors:
        out.append({
            "name": (c.name or "").strip()[:80],
            "color": list(_norm_color(c.color)),
            "xml_material_template": _mt_value_from_enum_id(getattr(c, "xml_material_template", "NONE")),
            "decal_image_path": str(getattr(c, "decal_image_path", "") or ""),
        })
    return out


def _apply_my(
    scene: bpy.types.Scene,
    data: Any,
    *,
    replace: bool,
    ignore_duplicate_color_material: bool = False,
) -> int:
    if not isinstance(data, list):
        return 0

    def _combo_key(mt_value: str, rgb, decal_path: str = ""):
        """Key used for duplicate detection during import.

        For most materials we compare (Material Type + RGB). For decals we
        also include the decal image filename so different decals don't get
        skipped just because they share the same color/material.
        """
        mt_norm = (mt_value or "").strip().lower()
        rgb_norm = _norm_color(rgb)
        rgb_key = tuple(int(round(c * 255.0)) for c in rgb_norm)
        if mt_norm == "decal":
            base = os.path.basename(decal_path or "").lower()
            return (mt_norm, rgb_key, base)
        return (mt_norm, rgb_key)

    existing_names = set()
    if not replace:
        for c in scene.i3d_cl_my_colors:
            existing_names.add((c.name or "").strip().lower())

    existing_combos = set()
    if ignore_duplicate_color_material and not replace:
        for c in scene.i3d_cl_my_colors:
            try:
                mt_existing = _mt_value_from_enum_id(getattr(c, "xml_material_template", "NONE"))
            except Exception:
                mt_existing = ""
            try:
                rgb_existing = tuple(getattr(c, "color", (0.0, 0.0, 0.0)))
            except Exception:
                rgb_existing = (0.0, 0.0, 0.0)
            decal_existing = ""
            try:
                decal_existing = str(getattr(c, "decal_image_path", "") or "")
            except Exception:
                pass
            existing_combos.add(_combo_key(mt_existing, rgb_existing, decal_existing))

    count = 0
    if replace:
        scene.i3d_cl_my_colors.clear()

    for row in data:
        if not isinstance(row, dict):
            continue
        nm = str(row.get("name", "")).strip() or "Color"
        col = _norm_color(row.get("color"))
        mt_val = str(row.get("xml_material_template", "") or "").strip()
        decal_path = str(row.get("decal_image_path", "") or "")

        if ignore_duplicate_color_material:
            combo = _combo_key(mt_val, col, decal_path)
            if combo in existing_combos:
                continue
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
        try:
            item.xml_material_template = _mt_register_value(mt_val)
        except Exception:
            item.xml_material_template = "NONE"
        try:
            item.decal_image_path = decal_path
        except Exception:
            pass

        if ignore_duplicate_color_material:
            existing_combos.add(combo)
        existing_names.add(key)
        count += 1

    if count:
        scene.i3d_cl_my_index = min(scene.i3d_cl_my_index, max(0, len(scene.i3d_cl_my_colors) - 1))
        schedule_save()

    return count


def load_my_colors_from_path(
    path: Path,
    *,
    replace: bool,
    ignore_duplicate_color_material: bool = False,
) -> int:
    try:
        if not path.exists():
            return 0
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else []
    except Exception:
        return 0

    # If decal_image_path values are relative (e.g. "decals/foo.png"), try to resolve them
    # relative to the JSON file's folder. Optionally copy found images into the persistent
    # decal store so the library keeps working even if the import folder is moved/deleted.
    try:
        base_dir = path.parent
        # Copy assets only when the JSON contains relative decal paths.
        copy_assets = False
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict):
                    dp = str(row.get("decal_image_path", "") or "")
                    if dp and (not Path(dp).is_absolute()) and (not dp.startswith("//")):
                        copy_assets = True
                        break
        data = _import_postprocess_decal_paths(data, base_dir=base_dir, copy_assets_to_store=copy_assets)
    except Exception:
        pass

    scene = bpy.context.scene
    if not scene:
        return 0
    return _apply_my(
        scene,
        data,
        replace=replace,
        ignore_duplicate_color_material=ignore_duplicate_color_material,
    )


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

_GIANTS_STAT_THROTTLE_S: float = 0.75
_GIANTS_LAST_STAT_CHECK: float = 0.0

_GIANTS_BRAND_ITEMS_CACHE_SIG = None
_GIANTS_BRAND_ITEMS_CACHE: List[Tuple[str, str, str]] = []

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
    """Parse and cache $data/shared/brandMaterialTemplates.xml (GIANTS brands/colors).

    Note: Material Type dropdowns are no longer sourced from this file; see
    ensure_material_templates_cache() for materialTemplates.xml parsing.
    """
    global _GIANTS_CACHE_PATH, _GIANTS_CACHE_MTIME, _GIANTS_CACHE_BRANDS, _GIANTS_CACHE_BRAND_LIST, _GIANTS_LAST_ERROR

    global _GIANTS_LAST_STAT_CHECK
    now = time.time()
    if (not force) and _GIANTS_LAST_STAT_CHECK and (now - _GIANTS_LAST_STAT_CHECK) < _GIANTS_STAT_THROTTLE_S:
        return bool(_GIANTS_CACHE_BRANDS)
    _GIANTS_LAST_STAT_CHECK = now

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


        brand_list: List[str] = []



        # Support both FS formats:
        #  A) <brand name=...><color .../></brand>
        #  B) <template brand=... colorScale=.../> (brandMaterialTemplates.xml in newer games)

        brand_els = root.findall("brand") or root.findall(".//brand")
        if brand_els:
            for brand_el in brand_els:
                brand_name = (brand_el.attrib.get("name") or "").strip()
                if not brand_name:
                    continue

                brand_list.append(brand_name)

                rows: List[Dict[str, Any]] = []
                for color_el in brand_el.findall("color"):
                    nm = (color_el.attrib.get("name") or "").strip()
                    r = float(color_el.attrib.get("r", "1.0") or 1.0)
                    g = float(color_el.attrib.get("g", "1.0") or 1.0)
                    b = float(color_el.attrib.get("b", "1.0") or 1.0)
                    pt = (color_el.attrib.get("parentTemplate") or "").strip()

                    rows.append({
                        "name": nm,
                        "brand": brand_name,
                        "rgb": (r, g, b),
                        "parentTemplate": pt,
                        "colorScale": "",
                        "title": "",
                    })

                brands[brand_name] = rows
        else:
            # Template-style brandMaterialTemplates.xml
            tpl_els = root.findall("template") or root.findall(".//template")

            def _parse_colorscale(cs: str):
                if not cs:
                    return None
                parts = cs.replace(',', ' ').split()
                if len(parts) < 3:
                    return None
                try:
                    r, g, b = float(parts[0]), float(parts[1]), float(parts[2])
                    return (r, g, b)
                except Exception:
                    return None

            def _canon_brand(brand_value: str, template_name: str) -> str:
                b = (brand_value or "").strip()
                if b.lower() in {"none", "null"}:
                    b = ""
                if b.lower() == "other":
                    return "Other"
                if b:
                    return b.upper()

                tn = (template_name or "").strip()
                up = tn.upper()
                for pfx in ("RIM_", "GENERIC_", "SHARED_"):
                    if up.startswith(pfx):
                        return "Other"
                if "_" in tn:
                    guess = tn.split("_", 1)[0].strip()
                    if guess:
                        return guess.upper()
                return "Other"

            for tpl in tpl_els:
                raw_name = (tpl.attrib.get("name") or "").strip()
                brand_name = _canon_brand((tpl.attrib.get("brand") or ""), raw_name)

                nm = (raw_name or "").strip()
                pt = (tpl.attrib.get("parentTemplate") or "").strip()
                if not pt:
                    pt = (root.attrib.get("parentTemplateDefault") or "").strip()
                cs = (tpl.attrib.get("colorScale") or "").strip()
                rgb = _parse_colorscale(cs)

                brand_list.append(brand_name)
                rows = brands.setdefault(brand_name, [])
                rows.append({
                    "name": nm,
                    "brand": brand_name,
                    "rgb": rgb,
                    "parentTemplate": pt,
                    "colorScale": cs,
                    "title": "",  # NOTE: Do not use localized title in the Color Library

                })

            # Sort each brand's rows by name for stable UI
            for _b, _rows in brands.items():
                try:
                    _rows.sort(key=lambda r: (r.get("name") or "").lower())
                except Exception:
                    pass

        brand_list = sorted(set(brand_list), key=lambda s: s.lower())
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

    global _GIANTS_BRAND_ITEMS_CACHE_SIG, _GIANTS_BRAND_ITEMS_CACHE
    sig = (_GIANTS_CACHE_PATH, _GIANTS_CACHE_MTIME, len(_GIANTS_CACHE_BRAND_LIST))

    try:
        if _GIANTS_BRAND_ITEMS_CACHE_SIG == sig and _GIANTS_BRAND_ITEMS_CACHE:
            return _GIANTS_BRAND_ITEMS_CACHE
    except Exception:
        pass

    items: List[Tuple[str, str, str]] = []
    for b in _GIANTS_CACHE_BRAND_LIST:
        if b == "Other":
            items.append(("OTHER", "Other", "Templates with no brand attribute"))
        else:
            items.append((b, b, ""))

    if not items:
        items = [("OTHER", "Other", "")]

    _GIANTS_BRAND_ITEMS_CACHE_SIG = sig
    _GIANTS_BRAND_ITEMS_CACHE = items
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
    parentTemplate: bpy.props.StringProperty(name="ParentTemplate", default="")
    xml_selected: bpy.props.BoolProperty(name="Select", default=False, update=_on_xml_selected_giants)


def rebuild_giants_visible(scene: bpy.types.Scene, *, force: bool = False) -> None:
    scene.i3d_cl_giants_colors.clear()
    scene.i3d_cl_giants_index = 0

    if not ensure_giants_cache(force=force):
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
        it.parentTemplate = r.get("parentTemplate", "")
        rgb = r.get("rgb")
        if rgb:
            it.color = rgb

        # Restore XML selection state
        global _XML_SYNC_SUSPEND
        _XML_SYNC_SUSPEND = True
        try:
            it.xml_selected = (_xml_find_selected(scene, _xml_key_for_giants(it)) >= 0)
        except Exception:
            pass
        _XML_SYNC_SUSPEND = False

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

# ---------------------------------------------------------------------------
# Deferred UI rebuild helpers (Blender 4+/5+ disallow writing to ID data in draw)
# ---------------------------------------------------------------------------
_DEFERRED_REBUILD_QUEUE = set()  # {(scene_name, which)}
_DEFERRED_REBUILD_TIMER_RUNNING = False

def _deferred_request_rebuild(scene, which: str) -> None:
    """Request a visible-list rebuild outside of UI draw context.

    Blender 4+/5+ can raise: 'Writing to ID classes in this context is not allowed'
    if we modify Scene collections during a panel's draw(). We therefore queue
    rebuilds to run on a timer callback.
    """
    global _DEFERRED_REBUILD_TIMER_RUNNING
    try:
        scene_name = scene.name if scene else None
        if not scene_name:
            return
        _DEFERRED_REBUILD_QUEUE.add((scene_name, which))
        if not _DEFERRED_REBUILD_TIMER_RUNNING:
            _DEFERRED_REBUILD_TIMER_RUNNING = True
            bpy.app.timers.register(_deferred_rebuild_timer, first_interval=0.0)
    except Exception:
        # Never let UI draw explode because a queue couldn't be scheduled.
        return

def _deferred_rebuild_timer():
    """Timer callback to process queued rebuilds."""
    global _DEFERRED_REBUILD_TIMER_RUNNING

    try:
        if not _DEFERRED_REBUILD_QUEUE:
            _DEFERRED_REBUILD_TIMER_RUNNING = False
            return None

        pending = list(_DEFERRED_REBUILD_QUEUE)
        _DEFERRED_REBUILD_QUEUE.clear()

        for scene_name, which in pending:
            scene = bpy.data.scenes.get(scene_name)
            if scene is None:
                continue

            try:
                if which == "GIANTS":
                    ensure_giants_cache(force=False)
                    rebuild_giants_visible(scene)
                elif which == "POPULAR":
                    ensure_popular_cache(force=False)
                    rebuild_popular_visible(scene)
            except Exception as e:
                print(f"[I3D Color Library] deferred rebuild failed ({which}): {e}")

        # If more rebuilds were queued while we processed, run again shortly.
        if _DEFERRED_REBUILD_QUEUE:
            return 0.1

        _DEFERRED_REBUILD_TIMER_RUNNING = False
        return None

    except Exception:
        _DEFERRED_REBUILD_TIMER_RUNNING = False
        return None
_POPULAR_CACHE_BRANDS: Dict[str, List[Dict[str, Any]]] = {}
_POPULAR_CACHE_BRAND_LIST: List[str] = []
_POPULAR_LAST_ERROR: str = ""

_POPULAR_STAT_THROTTLE_S: float = 0.75
_POPULAR_LAST_STAT_CHECK: float = 0.0

_POPULAR_BRAND_ITEMS_CACHE_SIG = None
_POPULAR_BRAND_ITEMS_CACHE: List[Tuple[str, str, str]] = []


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

    global _POPULAR_LAST_STAT_CHECK
    now = time.time()
    if (not force) and _POPULAR_LAST_STAT_CHECK and (now - _POPULAR_LAST_STAT_CHECK) < _POPULAR_STAT_THROTTLE_S:
        return bool(_POPULAR_CACHE_BRANDS)
    _POPULAR_LAST_STAT_CHECK = now

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
        parent_templates: Set[str] = set()

        for el in root.iter():
            # Expecting <template .../>
            if (str(el.tag).split("}")[-1] != "template"):
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

    global _POPULAR_BRAND_ITEMS_CACHE_SIG, _POPULAR_BRAND_ITEMS_CACHE
    sig = (_POPULAR_CACHE_PATH, _POPULAR_CACHE_MTIME, len(_POPULAR_CACHE_BRAND_LIST))

    try:
        if _POPULAR_BRAND_ITEMS_CACHE_SIG == sig and _POPULAR_BRAND_ITEMS_CACHE:
            return _POPULAR_BRAND_ITEMS_CACHE
    except Exception:
        pass

    items: List[Tuple[str, str, str]] = []
    for b in _POPULAR_CACHE_BRAND_LIST:
        if b == "Other":
            items.append(("OTHER", "Other", "Templates with no brand attribute"))
        else:
            items.append((b, b, ""))

    if not items:
        items = [("OTHER", "Other", "")]

    _POPULAR_BRAND_ITEMS_CACHE_SIG = sig
    _POPULAR_BRAND_ITEMS_CACHE = items
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
    xml_material_template: bpy.props.EnumProperty(
        name="Material Type",
        description="Optional materialTemplateName to export when using XML mode",
        items=_mt_items,
        default=0,
        update=_on_xml_material_template_popular,
    )
    xml_color_locked: bpy.props.BoolProperty(
        name="Color Locked",
        description="Internal: Material Type forces this color and locks the swatch",
        default=False,
        options={'HIDDEN'},
    )
    xml_selected: bpy.props.BoolProperty(name="Select", default=False, update=_on_xml_selected_popular)


def rebuild_popular_visible(scene: bpy.types.Scene, *, force: bool = False) -> None:
    scene.i3d_cl_popular_colors.clear()
    scene.i3d_cl_popular_index = 0

    if not ensure_popular_cache(force=force):
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

        # Restore XML selection state
        global _XML_SYNC_SUSPEND
        _XML_SYNC_SUSPEND = True
        try:
            sel_idx = _xml_find_selected(scene, _xml_key_for_popular(it))
            it.xml_selected = (sel_idx >= 0)
            if sel_idx >= 0:
                mt = (scene.i3d_cl_xml_selected_colors[sel_idx].materialTemplate or "").strip()
                # POPULAR library presets must never use forced-color templates (they override swatch).
                if mt and (not _mtpl_forces_color_change(mt)):
                    it.xml_material_template = _mt_register_value(mt)
                else:
                    it.xml_material_template = "NONE"
        except Exception:
            pass
        _XML_SYNC_SUSPEND = False

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




def _normalize_color_name_key(name: str) -> str:
    """Normalize a color name for cross-library comparisons.

    Treats the following as equivalent:
        - GENERIC_CABLEMOUNT_GREEN2
        - Generic Cablemount Green 2
        - $l10n_ui_colorGenericCablemountGreen2
    """
    s = (name or "").strip()
    if not s:
        return ""
    if s.startswith("$"):
        s = s[1:]
    # Strip common L10N prefixes for name-equivalence comparisons
    s = re.sub(r"(?i)^l10n_ui_color", "", s)
    # Remove whitespace/underscores/punctuation so CONSTANT_CASE and display forms match
    s = re.sub(r"[^0-9A-Za-z]+", "", s)
    return s.casefold()


def _all_library_existing_name_key_set(scene, *, exclude_my_item=None) -> set:
    """Return a normalized set of existing names across ALL libraries.

    This checks:
      - My Color Library (Scene collection), excluding exclude_my_item if provided
      - GIANTS cache (all brands)
      - POPULAR cache (all brands)
      - Visible GIANTS/POPULAR scene lists as a fallback
    """
    keys = set()

    # My Library
    try:
        for it in scene.i3d_cl_my_colors:
            if exclude_my_item is not None and it == exclude_my_item:
                continue
            k = _normalize_color_name_key(getattr(it, "name", "") or "")
            if k:
                keys.add(k)
    except Exception:
        pass

    # GIANTS cache (all brands)
    try:
        ensure_giants_cache(force=False)
    except Exception:
        pass
    try:
        for rows in (_GIANTS_CACHE_BRANDS or {}).values():
            for r in (rows or []):
                k = _normalize_color_name_key((r or {}).get("name", "") or "")
                if k:
                    keys.add(k)
    except Exception:
        pass

    # POPULAR cache (all brands)
    try:
        ensure_popular_cache(force=False)
    except Exception:
        pass
    try:
        for rows in (_POPULAR_CACHE_BRANDS or {}).values():
            for r in (rows or []):
                k = _normalize_color_name_key((r or {}).get("name", "") or "")
                if k:
                    keys.add(k)
    except Exception:
        pass

    # Visible lists (fallback only)
    try:
        for it in getattr(scene, "i3d_cl_giants_colors", []):
            k = _normalize_color_name_key(getattr(it, "name", "") or "")
            if k:
                keys.add(k)
    except Exception:
        pass
    try:
        for it in getattr(scene, "i3d_cl_popular_colors", []):
            k = _normalize_color_name_key(getattr(it, "name", "") or "")
            if k:
                keys.add(k)
    except Exception:
        pass

    return keys


def _ensure_unique_my_library_name(scene, desired_name: str, *, exclude_my_item=None) -> str:
    """Ensure the desired name does not duplicate any existing name in ANY library.

    If it exists, suffix with an incrementing number.

    Naming style:
        - Underscore/constant-style names keep a compact suffix:
              GENERIC_CABLEMOUNT_GREEN -> GENERIC_CABLEMOUNT_GREEN2 -> GENERIC_CABLEMOUNT_GREEN3 ...
        - Normal names use a space before the number:
              Red -> Red 2 -> Red 3 ...
              Red 2 -> Red 3 ...
    """
    desired = (desired_name or "").strip() or "New Color"
    desired = desired[:80]
    existing = _all_library_existing_name_key_set(scene, exclude_my_item=exclude_my_item)

    if _normalize_color_name_key(desired) not in existing:
        return desired

    # Decide suffix style: underscore or CONSTANT_CASE names get compact numeric suffix.
    use_compact = ("_" in desired) or bool(re.fullmatch(r"[A-Z0-9_]+", desired))

    # Split trailing digits (with or without whitespace).
    m = re.match(r"^(.*?)(?:\s+)?(\d+)$", desired)
    if m:
        base = (m.group(1) or "").strip() or "New Color"
        try:
            num = int(m.group(2)) + 1
        except Exception:
            num = 2
    else:
        base = desired
        num = 2

    while True:
        cand = f"{base}{num}" if use_compact else f"{base} {num}"
        if _normalize_color_name_key(cand) not in existing:
            return cand
        num += 1




class I3D_CL_OT_MyAdd(bpy.types.Operator):
    bl_idname = "i3d.cl_my_add"
    bl_label = "Add Color"
    bl_description = "Adds a new color entry to My Color Library."
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        unique_name = _ensure_unique_my_library_name(scene, "New Color")
        item = scene.i3d_cl_my_colors.add()
        item.name = unique_name
        item.color = (1.0, 1.0, 1.0)
        scene.i3d_cl_my_index = len(scene.i3d_cl_my_colors) - 1
        schedule_save()
        return {'FINISHED'}


class I3D_CL_OT_MyRemove(bpy.types.Operator):
    bl_idname = "i3d.cl_my_remove"
    bl_label = "Remove Color"
    bl_description = "Removes the selected color entry from My Color Library."
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_my_index
        if 0 <= idx < len(scene.i3d_cl_my_colors):
            scene.i3d_cl_my_colors.remove(idx)
            scene.i3d_cl_my_index = min(idx, max(0, len(scene.i3d_cl_my_colors) - 1))
            schedule_save()
        return {'FINISHED'}



class I3D_CL_OT_MySortBySelectedMaterial(bpy.types.Operator):
    bl_idname = "i3d.cl_my_sort_by_selected_material"
    bl_label = "Sort by Selected Material"
    bl_description = "Sorts My Color Library by the Material Type of the currently selected color (matching items move to the top)."
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        col = scene.i3d_cl_my_colors

        if len(col) < 2:
            self.report({'INFO'}, "Nothing to sort")
            return {'CANCELLED'}

        idx = int(getattr(scene, "i3d_cl_my_index", -1))
        if not (0 <= idx < len(col)):
            self.report({'WARNING'}, "No color selected")
            return {'CANCELLED'}

        active_item = col[idx]
        active_ptr = active_item.as_pointer()
        target_mt = _xml_material_template_from_item(active_item) or ""

        items = list(col)

        if not target_mt:
            # No material selected -> just sort by Name (keep the active row on top).
            def _key(it):
                ptr = it.as_pointer()
                nm = (it.name or "").lower()
                return (0 if ptr == active_ptr else 1, nm)
        else:
            def _key(it):
                ptr = it.as_pointer()
                mt = _xml_material_template_from_item(it) or ""
                nm = (it.name or "").lower()
                return (
                    0 if ptr == active_ptr else (1 if mt == target_mt else 2),
                    mt.lower(),
                    nm,
                )

        desired = sorted(items, key=_key)
        desired_ptrs = [it.as_pointer() for it in desired]
        current_ptrs = [it.as_pointer() for it in col]

        # Reorder using CollectionProperty.move (keeps the same PropertyGroup instances).
        for i, ptr in enumerate(desired_ptrs):
            try:
                j = current_ptrs.index(ptr)
            except ValueError:
                continue
            if j != i:
                col.move(j, i)
                moved = current_ptrs.pop(j)
                current_ptrs.insert(i, moved)

        # Restore active index (same row as before sorting).
        try:
            scene.i3d_cl_my_index = current_ptrs.index(active_ptr)
        except Exception:
            scene.i3d_cl_my_index = min(max(0, idx), max(0, len(col) - 1))

        schedule_save()

        if target_mt:
            self.report({'INFO'}, f"Sorted by Material Type: {target_mt}")
        else:
            self.report({'INFO'}, "Sorted by Name (selected material is None)")

        return {'FINISHED'}

class I3D_CL_OT_MyExport(bpy.types.Operator, ExportHelper):
    bl_idname = "i3d.cl_my_export"
    bl_label = "Export Colors"
    bl_description = "Exports My Color Library to a JSON file. Optionally bundles decal images into a ZIP for sharing."
    bl_options = {'UNDO'}

    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json;*.zip", options={'HIDDEN'})

    bundle_decals: bpy.props.BoolProperty(
        name="Bundle decal images (ZIP)",
        description="If enabled, exports a ZIP containing the JSON plus copies of all decal images used by My Color Library.",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.alert = True
        row.prop(self, "bundle_decals")

    def invoke(self, context, event):
        # Suggest a default filename/location for the file browser.
        if not getattr(self, "filepath", ""):
            default_dir = bpy.path.abspath("//")
            if not default_dir or default_dir == "//":
                default_dir = os.path.expanduser("~")
            self.filepath = os.path.join(default_dir, "i3d_reworked_colors.json")
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        out_path = Path(self.filepath)

        if self.bundle_decals:
            if out_path.suffix.lower() != ".zip":
                out_path = out_path.with_suffix(".zip")
            ok = save_my_colors_bundle_to_zip(out_path)
            self.report({'INFO'} if ok else {'ERROR'}, "Exported ZIP bundle" if ok else "Export failed")
            return {'FINISHED'}

        # Default JSON-only export
        if out_path.suffix.lower() != ".json":
            out_path = out_path.with_suffix(".json")
        ok = save_my_colors_to_path(out_path)
        self.report({'INFO'} if ok else {'ERROR'}, "Exported colors" if ok else "Export failed")
        return {'FINISHED'}

class I3D_CL_OT_MyImport(bpy.types.Operator, ImportHelper):
    bl_idname = "i3d.cl_my_import"
    bl_label = "Import Colors"
    bl_description = "Imports a JSON file into My Color Library (duplicates are deduped when possible)."
    bl_options = {'UNDO'}

    filter_glob: bpy.props.StringProperty(default="*.json;*.zip", options={'HIDDEN'})

    replace_library: bpy.props.BoolProperty(
        name="Replace existing library",
        description="If enabled, replaces your current colors. If disabled, imports and adds to your existing list.",
        default=False,
    )

    ignore_duplicate_color_material: bpy.props.BoolProperty(
        name="Ignore duplicates (Color + Material Type)",
        description=(
            "If enabled, skips importing any entry that already exists in your current My Color Library "
            "with the same Color AND Material Type. (For decals, the image filename is also compared so "
            "different decals are not accidentally skipped.)"
        ),
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "replace_library")
        layout.prop(self, "ignore_duplicate_color_material")

    def execute(self, context):
        fp = Path(self.filepath)

        # ZIP bundle import (JSON + optional decal images folder).
        if fp.suffix.lower() == '.zip':
            n = load_my_colors_from_zip(
                fp,
                replace=self.replace_library,
                ignore_duplicate_color_material=self.ignore_duplicate_color_material,
            )
            if n:
                self.report({'INFO'}, f"Imported {n} colors (ZIP bundle)")
            else:
                self.report({'WARNING'}, 'No colors imported (ZIP may be empty or invalid)')
            return {'FINISHED'}

        # Default JSON import.
        n = load_my_colors_from_path(
            fp,
            replace=self.replace_library,
            ignore_duplicate_color_material=self.ignore_duplicate_color_material,
        )
        if n:
            self.report({'INFO'}, f"Imported {n} colors")
        else:
            self.report({'WARNING'}, 'No colors imported (file may be empty or invalid)')
        return {'FINISHED'}



def _collect_used_decal_store_files(scene: bpy.types.Scene) -> set:
    """Return absolute filepaths (as strings) inside the persistent decal store that are currently referenced."""
    used = set()
    try:
        store_dir = _decal_store_dir().resolve()
    except Exception:
        store_dir = _decal_store_dir()

    try:
        col = getattr(scene, "i3d_cl_my_colors", None)
        if col is None:
            return used
        for item in col:
            try:
                dp = str(getattr(item, "decal_image_path", "") or "").strip()
            except Exception:
                dp = ""
            if not dp:
                continue

            try:
                if dp.startswith("//"):
                    p = Path(bpy.path.abspath(dp))
                else:
                    p = Path(dp)
            except Exception:
                p = Path(dp)

            try:
                if not p.is_absolute():
                    parts = list(p.parts)
                    if parts and parts[0].lower() == _MY_COLORS_BUNDLE_DECALS_DIRNAME.lower():
                        p = store_dir / parts[-1]
                    else:
                        p = store_dir / p.name
            except Exception:
                pass

            try:
                rp = p.resolve()
            except Exception:
                rp = p

            try:
                if (store_dir == rp.parent) or (store_dir in rp.parents):
                    if rp.exists() and rp.is_file():
                        used.add(str(rp))
            except Exception:
                pass
    except Exception:
        pass

    return used


class I3D_CL_OT_MyClearUnusedDecals(bpy.types.Operator):
    bl_idname = "i3d.cl_my_clear_unused_decals"
    bl_label = "Clear Unused Cached Decals"
    bl_description = "Deletes decal images from the add-on cache folder that are not referenced by any entry in My Color Library."
    bl_options = {'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene = context.scene
        try:
            store_dir = _decal_store_dir()
        except Exception:
            self.report({'ERROR'}, "Could not resolve decal cache folder")
            return {'CANCELLED'}

        # Collect decals referenced by My Color Library (by filename within the store dir).
        used_names = set()
        try:
            for c in getattr(scene, "i3d_cl_my_colors", []):
                fp = str(getattr(c, "decal_image_path", "") or "").strip()
                if not fp:
                    continue
                try:
                    p = Path(fp)
                    name = p.name
                    if name and (store_dir / name).exists():
                        used_names.add(name.lower())
                        continue
                    # If the stored path points inside the store dir, include it too.
                    try:
                        rp = p.resolve()
                        if (rp.parent == store_dir) or (store_dir in rp.parents):
                            used_names.add(rp.name.lower())
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass

        # Helper: hash file contents (for dedupe).
        def _sha1_file(p: Path) -> str:
            h = hashlib.sha1()
            with p.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            return h.hexdigest()

        # Scan store dir for files.
        files = []
        try:
            for p in store_dir.iterdir():
                if not p.is_file():
                    continue
                if p.name == _DECAL_CACHE_INDEX_FILENAME:
                    continue
                files.append(p)
        except Exception:
            self.report({'ERROR'}, "Could not read decal cache folder")
            return {'CANCELLED'}

        # 1) Dedupe by content hash (update library refs to canonical file, then delete duplicates).
        duplicates_deleted = 0
        refs_updated = 0
        hash_groups = {}
        for p in files:
            try:
                hh = _sha1_file(p)
            except Exception:
                continue
            hash_groups.setdefault(hh, []).append(p)

        # Update references + delete duplicate files
        for hh, group in hash_groups.items():
            if len(group) <= 1:
                continue
            # Pick canonical: prefer a referenced filename; else first sorted name.
            group_sorted = sorted(group, key=lambda x: x.name.lower())
            canonical = None
            for p in group_sorted:
                if p.name.lower() in used_names:
                    canonical = p
                    break
            if canonical is None:
                canonical = group_sorted[0]
            canon_path = str((store_dir / canonical.name).resolve())
            # Redirect any library entries referencing duplicates to canonical
            try:
                for c in getattr(scene, "i3d_cl_my_colors", []):
                    fp = str(getattr(c, "decal_image_path", "") or "").strip()
                    if not fp:
                        continue
                    try:
                        nm = Path(fp).name.lower()
                    except Exception:
                        continue
                    if nm == canonical.name.lower():
                        continue
                    if nm in {p2.name.lower() for p2 in group_sorted[1:]}:
                        c.decal_image_path = canon_path
                        refs_updated += 1
                if refs_updated:
                    schedule_save()
            except Exception:
                pass
            # Refresh used names (canonical is used if any duplicate was used)
            if any(p.name.lower() in used_names for p in group_sorted):
                used_names.add(canonical.name.lower())
            # Delete other duplicates
            for p in group_sorted:
                if p.name.lower() == canonical.name.lower():
                    continue
                try:
                    p.unlink()
                    duplicates_deleted += 1
                except Exception:
                    pass

        # 2) Delete any unused files (not referenced by My Color Library).
        deleted_unused = 0
        kept = 0
        try:
            for p in store_dir.iterdir():
                if not p.is_file():
                    continue
                if p.name == _DECAL_CACHE_INDEX_FILENAME:
                    continue
                if p.name.lower() in used_names:
                    kept += 1
                    continue
                try:
                    p.unlink()
                    deleted_unused += 1
                except Exception:
                    pass
        except Exception:
            pass

        # 3) Clean/update decal cache index to reflect current files.
        try:
            idx = _load_decal_cache_index()
            changed = False
            for h, fname in list(idx.items()):
                if not (store_dir / fname).exists():
                    idx.pop(h, None)
                    changed = True
            if changed:
                _save_decal_cache_index(idx)
        except Exception:
            pass

        self.report({'INFO'}, f"Deleted {deleted_unused} unused decal(s), removed {duplicates_deleted} duplicate(s), updated {refs_updated} reference(s). Kept {kept}.")
        return {'FINISHED'}

class I3D_CL_OT_MyReload(bpy.types.Operator):
    bl_idname = "i3d.cl_my_reload"
    bl_label = "Reload Colors"
    bl_description = "Reloads My Color Library from disk and refreshes the list."

    def execute(self, context):
        load_my_colors()
        self.report({'INFO'}, "Reloaded colors")
        return {'FINISHED'}


def _get_active_material(context) -> Optional[bpy.types.Material]:
    obj = context.object
    mat = obj.active_material if obj else None
    return mat


def _material_get_basecolor_image_filepath(mat: bpy.types.Material) -> str:
    """Return filepath of the image node currently driving Principled Base Color (if any)."""
    if not mat or not getattr(mat, "use_nodes", False) or not getattr(mat, "node_tree", None):
        return ""
    nt = mat.node_tree
    nodes = nt.nodes
    # Prefer named Principled; fall back to first Principled.
    bsdf = nodes.get("Principled BSDF")
    if bsdf is None:
        for n in nodes:
            if getattr(n, "type", "") == 'BSDF_PRINCIPLED':
                bsdf = n
                break
    if bsdf is None:
        return ""
    inp = None
    try:
        inp = bsdf.inputs.get("Base Color")
    except Exception:
        inp = None
    if inp is None or not inp.is_linked:
        return ""
    try:
        lnk = inp.links[0]
        from_node = lnk.from_node
        if from_node and getattr(from_node, "type", "") == 'TEX_IMAGE':
            img = getattr(from_node, "image", None)
            if img:
                return str(getattr(img, "filepath", "") or "")
    except Exception:
        pass
    return ""

def _material_has_basecolor_image(mat: bpy.types.Material) -> bool:
    return bool(_material_get_basecolor_image_filepath(mat))


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


def _set_bsdf_input(bsdf: bpy.types.Node, name_variants, value) -> bool:
    """Set a Principled BSDF input by trying multiple possible socket names.

    Blender has renamed some Principled inputs across versions; we keep this tolerant.
    """
    try:
        v = float(value)
    except Exception:
        return False

    for nm in name_variants:
        sock = bsdf.inputs.get(nm) if hasattr(bsdf, "inputs") else None
        if sock is None:
            continue
        if hasattr(sock, "default_value"):
            try:
                sock.default_value = v
                return True
            except Exception:
                pass
    return False


def _find_principled_bsdf(mat: bpy.types.Material):
    if not mat or not getattr(mat, "use_nodes", False) or not getattr(mat, "node_tree", None):
        return None
    nodes = mat.node_tree.nodes
    # Prefer the default name when present.
    bsdf = nodes.get("Principled BSDF")
    if bsdf and getattr(bsdf, "type", "") == 'BSDF_PRINCIPLED':
        return bsdf
    # Fallback: first Principled node.
    for n in nodes:
        if getattr(n, "type", "") == 'BSDF_PRINCIPLED':
            return n
    return None


# --- Material preview presets (Blender viewport approximation) ---
# NOTE: GIANTS shaders won't match 1:1 in Blender, but this gives a much better "at a glance" preview.
_PREVIEW_PRESETS = {
    # Metals
    "CHROME": {
        "metallic": 1.0,
        "roughness": 0.02,
        "anisotropic": 0.0,
    },
    "POLISHED_METAL": {
        "metallic": 1.0,
        "roughness": 0.10,
        "anisotropic": 0.0,
    },
    "BRUSHED_METAL": {
        "metallic": 1.0,
        "roughness": 0.28,
        "anisotropic": 0.65,
    },
    "SCRATCHED_METAL": {
        "metallic": 1.0,
        "roughness": 0.35,
        "anisotropic": 0.25,
    },

    # Paint / plastics
    "GLOSS_PAINT": {
        "metallic": 0.0,
        "roughness": 0.14,
        "specular": 0.55,
        "coat_weight": 0.55,
        "coat_roughness": 0.03,
    },
    "SATIN_PAINT": {
        "metallic": 0.0,
        "roughness": 0.30,
        "specular": 0.50,
        "coat_weight": 0.35,
        "coat_roughness": 0.08,
    },
    "MATTE_PAINT": {
        "metallic": 0.0,
        "roughness": 0.70,
        "specular": 0.35,
        "coat_weight": 0.0,
    },
    "PLASTIC_GLOSS": {
        "metallic": 0.0,
        "roughness": 0.22,
        "specular": 0.50,
        "coat_weight": 0.0,
    },
    "PLASTIC_MATTE": {
        "metallic": 0.0,
        "roughness": 0.60,
        "specular": 0.35,
        "coat_weight": 0.0,
    },
    "RUBBER": {
        "metallic": 0.0,
        "roughness": 0.88,
        "specular": 0.20,
        "coat_weight": 0.0,
    },

    # Glass-ish
    "GLASS": {
        "metallic": 0.0,
        "roughness": 0.02,
        "ior": 1.45,
        "transmission": 1.0,
    },
}


def _guess_preview_preset_id(material_template_name: str):
    if not material_template_name:
        return None

    s = material_template_name.strip().lower()

    # Explicit / high-priority matches
    if "chrome" in s or "mirror" in s:
        return "CHROME"
    if "glass" in s or "window" in s:
        return "GLASS"
    if "rubber" in s or "tire" in s or "tyre" in s:
        return "RUBBER"

    # Common template naming patterns
    if "scratched" in s or "scratch" in s:
        return "SCRATCHED_METAL"
    if "brushed" in s:
        return "BRUSHED_METAL"

    # Calibrated / generic groups
    if "metal" in s or "metallic" in s:
        return "POLISHED_METAL"
    if "paint" in s or "coated" in s:
        if "matte" in s:
            return "MATTE_PAINT"
        if "satin" in s:
            return "SATIN_PAINT"
        return "GLOSS_PAINT"
    if "plastic" in s:
        if "matte" in s:
            return "PLASTIC_MATTE"
        return "PLASTIC_GLOSS"

    # Fallback keywords
    if "gloss" in s:
        return "GLOSS_PAINT"
    if "matte" in s:
        return "MATTE_PAINT"

    return None


def _is_preview_only_node(node) -> bool:
    try:
        if node is None:
            return False
        # ID properties
        try:
            if bool(node.get("i3d_preview_only", False)):
                return True
        except Exception:
            pass
        try:
            if bool(node["i3d_preview_only"]):
                return True
        except Exception:
            pass
        try:
            lab = getattr(node, "label", "") or ""
            if lab.startswith("I3D_PREVIEW_ONLY:"):
                return True
        except Exception:
            pass
    except Exception:
        pass
    return False



def _is_legacy_orphan_preview_node(node) -> bool:
    """Cleanup helper for broken preview builds that left behind untagged orphan nodes.

    We keep this intentionally narrow to avoid touching user-authored nodes.
    """
    try:
        if node is None:
            return False
        if _is_preview_only_node(node):
            return False
        # Only remove completely unlinked Math(Add) nodes with default 0.5/0.5 and no label.
        if getattr(node, "type", "") != 'MATH':
            return False
        try:
            if getattr(node, "operation", "") != 'ADD':
                return False
        except Exception:
            return False
        if (getattr(node, "label", "") or "").strip():
            return False
        # No links anywhere
        try:
            if any(s.is_linked for s in getattr(node, "inputs", [])):
                return False
            if any(s.is_linked for s in getattr(node, "outputs", [])):
                return False
        except Exception:
            pass
        # Default inputs of Blender's Math(Add) are typically 0.5 / 0.5
        try:
            a = float(node.inputs[0].default_value)
            b = float(node.inputs[1].default_value)
            if abs(a - 0.5) > 1e-6 or abs(b - 0.5) > 1e-6:
                return False
        except Exception:
            return False
        return True
    except Exception:
        return False


def _tag_preview_node(node, role: str, *, restore: Optional[Dict[str, Any]] = None) -> None:
    if node is None:
        return
    try:
        node["i3d_preview_only"] = True
    except Exception:
        pass
    try:
        node["i3d_preview_role"] = str(role or "")
    except Exception:
        pass
    try:
        node.label = f"I3D_PREVIEW_ONLY:{role}"
    except Exception:
        pass
    if restore is not None:
        try:
            node["i3d_preview_restore"] = json.dumps(restore)
        except Exception:
            pass


def _unlink_input_socket(node_tree: bpy.types.NodeTree, inp: bpy.types.NodeSocket) -> None:
    try:
        if inp and inp.is_linked:
            for l in list(inp.links):
                try:
                    node_tree.links.remove(l)
                except Exception:
                    pass
    except Exception:
        pass


def _load_image_safe(abs_path: str) -> Optional[bpy.types.Image]:
    p = (abs_path or "").strip()
    if not p:
        return None
    try:
        # check_existing keeps memory sane when applying repeatedly
        return bpy.data.images.load(p, check_existing=True)
    except Exception:
        return None


def _new_node_safe(node_tree: bpy.types.NodeTree, node_type: str):
    try:
        return node_tree.nodes.new(type=node_type)
    except Exception:
        return None


def _make_image_texture_node(node_tree: bpy.types.NodeTree, abs_path: str, *, non_color: bool, role: str, loc=(0, 0)):
    img = _load_image_safe(abs_path)
    if img is None:
        return None
    n = _new_node_safe(node_tree, "ShaderNodeTexImage")
    if n is None:
        return None
    n.image = img
    try:
        n.location = loc
    except Exception:
        pass
    try:
        if non_color:
            n.image.colorspace_settings.name = "Non-Color"
    except Exception:
        pass
    _tag_preview_node(n, role)
    return n


# Detail-map UV transform preview
# GIANTS vehicleShader uses a "custom" UV transform for detail textures (detailDiffuse/specular/normal).
# In Blender preview, users should NOT have to scale their UV islands just to make detail tiling look right.
# We approximate the shader's custom transform by applying a Mapping node on top of UV coordinates.
_DETAIL_PREVIEW_SCALE_DEFAULT = 1.0


def _ensure_detail_preview_uv_output(node_tree: bpy.types.NodeTree, *, scale: float = _DETAIL_PREVIEW_SCALE_DEFAULT, loc=(0, 0)):
    """Create and return a shared Vector output socket for detail textures (UV -> Mapping -> Vector).

    Returns an output socket suitable for connecting to Image Texture 'Vector' inputs.
    """
    if not node_tree:
        return None

    nt = node_tree
    nodes = nt.nodes
    links = nt.links

    tc = _new_node_safe(nt, "ShaderNodeTexCoord")
    mp = _new_node_safe(nt, "ShaderNodeMapping")
    if tc is None or mp is None:
        return None

    try:
        tc.location = (loc[0], loc[1])
        mp.location = (loc[0] + 200, loc[1])
    except Exception:
        pass

    # Default tiling (preview-only)
    # IMPORTANT: When using BOX projection, the Image Texture uses all 3 axes.
    # If Z scale remains 1.0 while X/Y are scaled, side projections will look
    # stretched/smeared. Keep XYZ uniform.
    try:
        if "Scale" in mp.inputs:
            s = float(scale)
            mp.inputs["Scale"].default_value = (s, s, s)
    except Exception:
        pass

    _tag_preview_node(tc, "DETAIL_UV_TEXCOORD")
    _tag_preview_node(mp, "DETAIL_UV_MAPPING")

    try:
        links.new(tc.outputs.get("Object"), mp.inputs.get("Vector"))
    except Exception:
        pass

    try:
        return mp.outputs.get("Vector")
    except Exception:
        return None



def _configure_detail_preview_teximage_node(tex: bpy.types.Node) -> None:
    """Configure a ShaderNodeTexImage to behave like a 'custom/detail' mapping preview.

    We want detail maps to be:
    - NOT dependent on UV island scale/packing changes
    - Applied consistently on all faces (not top-down planar projection)

    Approach:
    - Use BOX projection (tri-planar style) driven by Object coords from _ensure_detail_preview_uv_output.
    """
    if not tex:
        return
    try:
        tex.projection = 'BOX'
    except Exception:
        pass
    try:
        # Small blend to smooth edges between projections
        tex.projection_blend = 0.15
    except Exception:
        pass

def _apply_material_template_preview_maps(mat: bpy.types.Material, material_template_name: str) -> bool:
    """Inject preview detail maps (Diffuse / Specular / Normal) into the active material node tree.

    DTAP requirements:
    - Detail maps come from $data/shared/detailLibrary/materialTemplates.xml
      (detailDiffuse, detailSpecular, detailNormal).
    - Prefer .dds over .png when both exist.
    - Do NOT overwrite user textures: combine with existing links/values.
    - Tag all injected nodes so exporter can ignore them.
    - Preview is applied only via Apply-to-Material operators.
    """
    if not mat or not mat.use_nodes or not mat.node_tree:
        return False

    raw = str(material_template_name or "").strip()
    if not raw or raw.lower() in {"none", "null"}:
        # None => remove any active preview nodes for this material.
        try:
            _clear_preview_nodes_in_material(mat)
        except Exception:
            pass
        return True

    mt = _mtpl_canonical_name(raw)
    if not mt:
        return False

    if not ensure_material_templates_cache(force=False):
        return False

    entry = _MTPL_CACHE_BY_NAME.get(mt)
    if not entry:
        return False

    # Always clear previous preview nodes in this material to avoid stacking.
    try:
        _clear_preview_nodes_in_material(mat)
    except Exception:
        pass

    bsdf = _find_principled_bsdf(mat)
    if not bsdf:
        return False


    # Apply-time overrides (set by modal prompts / decal picker).
    dd_mode = str(_MTPL_OVERRIDE_DETAIL_DIFFUSE_MODE or "").upper().strip()
    decal_path_override = str(_MTPL_OVERRIDE_DECAL_IMAGE_PATH or "").strip()
    decal_persist_override = bool(_MTPL_OVERRIDE_DECAL_PERSIST)
    forced_tint_override = _MTPL_OVERRIDE_FORCED_TINT
    apply_alpha_override = _MTPL_OVERRIDE_APPLY_ALPHA

    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links

    bx, by = (0.0, 0.0)
    try:
        bx, by = bsdf.location
    except Exception:
        pass

    # Shared UV transform for detail textures (preview-only)
    detail_uv_out = _ensure_detail_preview_uv_output(nt, scale=_DETAIL_PREVIEW_SCALE_DEFAULT, loc=(bx - 860, by + 120))

    applied_any = False

    # Common sockets we may override (Base Color / Alpha).
    base_color_in = None
    alpha_in = None
    try:
        base_color_in = bsdf.inputs.get("Base Color")
    except Exception:
        base_color_in = None
    try:
        alpha_in = bsdf.inputs.get("Alpha")
    except Exception:
        alpha_in = None

    # AUTO routing rules when no explicit prompt override was chosen.
    # - wood1/wood2 are tintable (keep swatch) => keep detailDiffuse in Diffuse Roughness (Base Color stays swatch).
    # - fixed wood species (cedar/oak/etc) => put detailDiffuse straight into Base Color (no tint), lock swatch.
    # - fixed-color variants (black/grey/graphite) => put detailDiffuse straight into Base Color (no tint), lock swatch.
    if not dd_mode:
        sname = (mt or "").lower()
        if sname in {"wood1", "wood2"}:
            dd_mode = "ROUGHNESS"
        elif any(k in sname for k in ("cedar", "oak", "pine", "spruce", "walnut", "cherry", "mahogany", "teak", "birch", "maple")):
            dd_mode = "ALBEDO"
        elif any(k in sname for k in ("black", "grey", "gray", "graphite")):
            dd_mode = "ALBEDO"
        else:
            # If a template declares a colorScale and we weren't explicitly told otherwise,
            # using ALBEDO_TINT gives a closer preview for forced-color templates.
            try:
                cs = _mtpl_colorscale_rgb(mt)
            except Exception:
                cs = None
            if cs is not None:
                # Do NOT apply to tintable wood.
                if sname not in {"wood1", "wood2"}:
                    dd_mode = "ALBEDO_TINT"
                    if forced_tint_override is None:
                        forced_tint_override = cs

    # If decal template and Base Color already has an image, do NOT prompt again.
    # Instead, optionally wire alpha for preview and skip overriding Base Color.
    if _mtpl_is_decal(material_template_name) and (not decal_path_override) and base_color_in is not None:
        try:
            if base_color_in.is_linked and base_color_in.links:
                src_node = base_color_in.links[0].from_node
                src_sock = base_color_in.links[0].from_socket
                if src_node and src_node.type == 'TEX_IMAGE' and alpha_in is not None:
                    want_alpha = bool(apply_alpha_override) if apply_alpha_override is not None else True
                    if want_alpha:
                        # capture original alpha
                        a_linked = bool(alpha_in.is_linked)
                        a_from_node = ""
                        a_from_socket = ""
                        a_default = None
                        try:
                            a_default = float(alpha_in.default_value)
                        except Exception:
                            a_default = None
                        if a_linked:
                            try:
                                lnk = alpha_in.links[0]
                                a_from_node = getattr(lnk.from_node, "name", "")
                                a_from_socket = getattr(lnk.from_socket, "name", "")
                            except Exception:
                                pass
                        rr = _new_node_safe(nt, "ShaderNodeReroute")
                        if rr is not None:
                            try:
                                rr.location = (bx - 220, by + 260)
                            except Exception:
                                pass
                            _tag_preview_node(rr, "DECAL_ALPHA_REROUTE", restore={
                                "target_node": bsdf.name,
                                "target_socket": alpha_in.name,
                                "orig_linked": bool(a_linked),
                                "orig_from_node": a_from_node,
                                "orig_from_socket": a_from_socket,
                                "orig_default": a_default,
                            })
                            _unlink_input_socket(nt, alpha_in)
                            try:
                                links.new(src_node.outputs.get('Alpha'), rr.inputs[0])
                                links.new(rr.outputs[0], alpha_in)
                            except Exception:
                                pass
                            # set blend/shadow methods for decal preview
                            _store_preview_methods(mat)
                            try:
                                mat.blend_method = 'CLIP'
                                mat.shadow_method = 'HASHED'
                            except Exception:
                                pass
                            applied_any = True
        except Exception:
            pass

    # DECAL override: inject an explicit base color image and optional alpha preview.
    # This is used when the user selects a custom decal image from the file picker.
    if decal_path_override and base_color_in is not None:
        try:
            dp = decal_path_override
            if os.path.isfile(dp):
                # capture original Base Color wiring/default
                orig_linked = bool(base_color_in.is_linked)
                orig_from_node = ""
                orig_from_socket = ""
                orig_default = None
                try:
                    orig_default = tuple(base_color_in.default_value)
                except Exception:
                    orig_default = None
                if orig_linked and base_color_in.links:
                    try:
                        lnk = base_color_in.links[0]
                        orig_from_node = getattr(lnk.from_node, "name", "")
                        orig_from_socket = getattr(lnk.from_socket, "name", "")
                    except Exception:
                        pass

                img = nodes.new('ShaderNodeTexImage')
                try:
                    img.location = (bx - 420, by + 260)
                except Exception:
                    pass
                try:
                    img.image = bpy.data.images.load(dp, check_existing=True)
                except Exception:
                    img.image = None
                try:
                    img.extension = 'REPEAT'
                except Exception:
                    pass
                try:
                    img.interpolation = 'Linear'
                except Exception:
                    pass

                # Link color -> Base Color
                try:
                    if orig_linked and base_color_in.links:
                        try:
                            links.remove(base_color_in.links[0])
                        except Exception:
                            pass
                    links.new(img.outputs.get('Color'), base_color_in)
                except Exception:
                    pass

                _tag_preview_node(img, "DECAL_BASECOLOR", restore={
                    "target_node": bsdf.name,
                    "target_socket": base_color_in.name,
                    "orig_linked": bool(orig_linked),
                    "orig_from_node": orig_from_node,
                    "orig_from_socket": orig_from_socket,
                    "orig_default": orig_default,
                })
                # Mark persist if requested so Clear Preview does not delete it.
                if decal_persist_override:
                    try:
                        img["i3d_preview_persist"] = True
                    except Exception:
                        pass

                # Alpha preview
                want_alpha = bool(apply_alpha_override) if apply_alpha_override is not None else _mtpl_name_uses_alpha(material_template_name)
                if want_alpha and alpha_in is not None:
                    a_linked = bool(alpha_in.is_linked)
                    a_from_node = ""
                    a_from_socket = ""
                    a_default = None
                    try:
                        a_default = float(alpha_in.default_value)
                    except Exception:
                        a_default = None
                    if a_linked and alpha_in.links:
                        try:
                            lnk = alpha_in.links[0]
                            a_from_node = getattr(lnk.from_node, "name", "")
                            a_from_socket = getattr(lnk.from_socket, "name", "")
                        except Exception:
                            pass
                    try:
                        if a_linked and alpha_in.links:
                            try:
                                links.remove(alpha_in.links[0])
                            except Exception:
                                pass
                        links.new(img.outputs.get('Alpha'), alpha_in)
                    except Exception:
                        pass
                    _store_preview_methods(mat)
                    try:
                        if _mtpl_is_glass(material_template_name):
                            mat.blend_method = 'BLEND'
                            mat.shadow_method = 'HASHED'
                        else:
                            mat.blend_method = 'CLIP'
                            mat.shadow_method = 'HASHED'
                    except Exception:
                        pass
                    try:
                        img["i3d_preview_restore_alpha"] = json.dumps({
                            "target_node": bsdf.name,
                            "target_socket": alpha_in.name,
                            "orig_linked": bool(a_linked),
                            "orig_from_node": a_from_node,
                            "orig_from_socket": a_from_socket,
                            "orig_default": a_default,
                        })
                    except Exception:
                        pass
                applied_any = True
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # Glass transparency preview: in GIANTS this is handled by vehicleShader.
    # For Blender TEMP preview we simulate see-through by driving Principled Alpha
    # with a constant and switching material blend/shadow methods.
    # ---------------------------------------------------------------------
    if _mtpl_is_glass(material_template_name) and alpha_in is not None:
        want_alpha = bool(apply_alpha_override) if apply_alpha_override is not None else True
        if want_alpha:
            try:
                has_alpha_link = bool(alpha_in.is_linked)
            except Exception:
                has_alpha_link = False

            if not has_alpha_link:
                a_from_node = ""
                a_from_socket = ""
                a_default = None
                try:
                    a_default = float(alpha_in.default_value)
                except Exception:
                    a_default = None

                val = nodes.new("ShaderNodeValue")
                try:
                    val.location = (bx - 420, by + 520)
                except Exception:
                    pass
                try:
                    val.outputs[0].default_value = 0.25
                except Exception:
                    pass

                try:
                    links.new(val.outputs[0], alpha_in)
                except Exception:
                    pass

                _tag_preview_node(val, "GLASS_ALPHA_VALUE", restore={
                    "target_node": bsdf.name,
                    "target_socket": alpha_in.name,
                    "orig_linked": False,
                    "orig_from_node": a_from_node,
                    "orig_from_socket": a_from_socket,
                    "orig_default": a_default,
                })

                _store_preview_methods(mat)
                try:
                    mat.blend_method = "BLEND"
                    mat.shadow_method = "HASHED"
                except Exception:
                    pass

                applied_any = True

    def _entry_float(key: str, default: float) -> float:
        try:
            v = entry.get(key, "")
            return float(v) if str(v).strip() != "" else float(default)
        except Exception:
            return float(default)

    smooth_scale = max(0.0, _entry_float("smoothnessScale", 1.0))
    metal_scale = max(0.0, _entry_float("metalnessScale", 1.0))
    coat_intensity = _clamp01(_entry_float("clearCoatIntensity", 0.0))
    coat_smoothness = _clamp01(_entry_float("clearCoatSmoothness", 0.0))
    porosity = _clamp01(_entry_float("porosity", 0.0))

    sname = (mt or "").lower()
    # "Dry" heuristic: things that should not look glossy in Blender previews.
    is_dry = (
        ("fabric" in sname) or ("cloth" in sname) or ("carpet" in sname) or ("rubber" in sname) or
        ("matte" in sname) or ("matpaint" in sname) or
        (porosity >= 0.5) or
        (smooth_scale <= 0.25 and metal_scale <= 0.01)
    )

    def _connect_preview_value(input_names, value: float, role: str, loc=(0, 0)) -> bool:
        """Connect a preview-only Value node into a BSDF input, preserving/restoring the original."""
        inp = None
        for nm in input_names:
            try:
                inp = bsdf.inputs.get(nm)
            except Exception:
                inp = None
            if inp is not None:
                break
        if inp is None:
            return False

        orig_linked = bool(getattr(inp, "is_linked", False))
        orig_from_node = ""
        orig_from_socket = ""
        orig_default = None

        if orig_linked:
            try:
                lnk = inp.links[0]
                orig_from_node = lnk.from_node.name
                orig_from_socket = lnk.from_socket.name
            except Exception:
                orig_linked = False

        if not orig_linked:
            try:
                orig_default = float(inp.default_value)
            except Exception:
                orig_default = None

        valn = _new_node_safe(nt, "ShaderNodeValue")
        if valn is None:
            return False

        try:
            valn.location = loc
        except Exception:
            pass
        try:
            valn.outputs[0].default_value = float(value)
        except Exception:
            pass

        _tag_preview_node(valn, role, restore={
            "target_node": bsdf.name,
            "target_socket": inp.name,
            "orig_linked": bool(orig_linked),
            "orig_from_node": orig_from_node,
            "orig_from_socket": orig_from_socket,
            "orig_default": orig_default,
        })

        _unlink_input_socket(nt, inp)
        try:
            links.new(valn.outputs[0], inp)
            return True
        except Exception:
            return False

    # Apply coat scalars (if present) for non-dry templates.
    if not is_dry:
        if coat_intensity > 0.0:
            if _connect_preview_value(["Coat Weight", "Clearcoat", "Clearcoat Weight"], coat_intensity, "COAT_WEIGHT", loc=(bx - 320, by + 320)):
                applied_any = True
            # coat smoothness -> coat roughness
            coat_rough = _clamp01(1.0 - coat_smoothness)
            if _connect_preview_value(["Coat Roughness", "Clearcoat Roughness"], coat_rough, "COAT_ROUGHNESS", loc=(bx - 320, by + 280)):
                applied_any = True
    else:
        # Force specular/ior/coat down for dry templates (fabric/matte/rubber/etc).
        if _connect_preview_value(["Specular IOR Level", "Specular", "Specular Level", "Specular IOR"], 0.0, "SPECULAR_ZERO", loc=(bx - 320, by + 240)):
            applied_any = True
        if _connect_preview_value(["IOR"], 0.0, "IOR_ZERO", loc=(bx - 320, by + 200)):
            applied_any = True
        if _connect_preview_value(["Coat Weight", "Clearcoat", "Clearcoat Weight"], 0.0, "COAT_WEIGHT_ZERO", loc=(bx - 320, by + 160)):
            applied_any = True

    # ---------------------------------------------------------------------
    # Diffuse Roughness: plug detailDiffuse into Diffuse Roughness so Base Color remains user-selectable
    # ---------------------------------------------------------------------
    detail_diffuse = (entry.get("detailDiffuse") or "").strip()
    diffuse_rough_in = None
    for _nm in ("Diffuse Roughness", "Diffuse roughness", "DiffuseRoughness"):
        try:
            diffuse_rough_in = bsdf.inputs.get(_nm)
        except Exception:
            diffuse_rough_in = None
        if diffuse_rough_in is not None:
            break

    # Override: use detailDiffuse as the albedo (Base Color) instead of affecting Diffuse Roughness.
    # Used when user chooses "Prioritize Detail" for Permanent apply.
    if dd_mode in ("ALBEDO", "ALBEDO_TINT") and detail_diffuse and os.path.isfile(detail_diffuse) and base_color_in is not None:
        # Capture original Base Color wiring/default
        orig_linked = bool(base_color_in.is_linked)
        orig_from_node = ""
        orig_from_socket = ""
        orig_default = None
        try:
            orig_default = tuple(base_color_in.default_value)
        except Exception:
            orig_default = None
        if orig_linked:
            try:
                lnk = base_color_in.links[0]
                orig_from_node = getattr(lnk.from_node, "name", "")
                orig_from_socket = getattr(lnk.from_socket, "name", "")
            except Exception:
                pass

        img = nodes.new('ShaderNodeTexImage')
        try:
            img.location = (bx - 420, by + 340)
        except Exception:
            pass
        try:
            img.image = bpy.data.images.load(detail_diffuse, check_existing=True)
        except Exception:
            img.image = None
        try:
            img.extension = 'REPEAT'
        except Exception:
            pass
        try:
            _configure_detail_preview_teximage_node(img)
        except Exception:
            pass

        # Apply detail UV transform (preview-only)
        try:
            if detail_uv_out is not None and "Vector" in img.inputs:
                links.new(detail_uv_out, img.inputs["Vector"])
        except Exception:
            pass

        out_color = img.outputs.get('Color')
        last_out = out_color
        if dd_mode == "ALBEDO_TINT":
            # Multiply by forced tint if provided, else by current Base Color default.
            tint = forced_tint_override
            if tint is None:
                try:
                    tint = tuple(bsdf.inputs.get("Base Color").default_value)[:3]
                except Exception:
                    tint = None
            if tint is not None:
                rgb = nodes.new('ShaderNodeRGB')
                mul = nodes.new('ShaderNodeMixRGB')
                try:
                    rgb.location = (bx - 640, by + 340)
                    mul.location = (bx - 220, by + 340)
                except Exception:
                    pass
                try:
                    rgb.outputs[0].default_value = (float(tint[0]), float(tint[1]), float(tint[2]), 1.0)
                except Exception:
                    pass
                try:
                    mul.blend_type = 'MULTIPLY'
                    mul.inputs[0].default_value = 1.0
                except Exception:
                    pass
                try:
                    links.new(out_color, mul.inputs[1])
                    links.new(rgb.outputs[0], mul.inputs[2])
                    last_out = mul.outputs.get('Color')
                except Exception:
                    last_out = out_color
                _tag_preview_node(rgb, "ALBEDO_TINT_RGB")
                _tag_preview_node(mul, "ALBEDO_TINT_MULTIPLY")

        try:
            if orig_linked:
                try:
                    links.remove(base_color_in.links[0])
                except Exception:
                    pass
            links.new(last_out, base_color_in)
        except Exception:
            pass
        _tag_preview_node(img, "DETAIL_DIFFUSE_ALBEDO", restore={
            "target_node": bsdf.name,
            "target_socket": base_color_in.name,
            "orig_linked": bool(orig_linked),
            "orig_from_node": orig_from_node,
            "orig_from_socket": orig_from_socket,
            "orig_default": orig_default,
        })
        applied_any = True

    if dd_mode not in ("SKIP", "ALBEDO", "ALBEDO_TINT", "DECAL") and detail_diffuse and os.path.isfile(detail_diffuse) and diffuse_rough_in is not None:
        # Capture original
        orig_linked = bool(diffuse_rough_in.is_linked)
        orig_from_node = ""
        orig_from_socket = ""
        orig_default = None

        if orig_linked:
            try:
                lnk = diffuse_rough_in.links[0]
                orig_from_node = lnk.from_node.name
                orig_from_socket = lnk.from_socket.name
            except Exception:
                orig_linked = False

        if not orig_linked:
            try:
                orig_default = float(diffuse_rough_in.default_value)
            except Exception:
                orig_default = 0.0

        tex = _make_image_texture_node(nt, detail_diffuse, non_color=True, role="DETAIL_DIFFUSE", loc=(bx - 520, by + 140))
        if tex is not None:
            try:
                _configure_detail_preview_teximage_node(tex)
            except Exception:
                pass
            # Apply detail UV transform (preview-only)
            try:
                if detail_uv_out is not None and "Vector" in tex.inputs:
                    links.new(detail_uv_out, tex.inputs["Vector"])
            except Exception:
                pass
            bw = _new_node_safe(nt, "ShaderNodeRGBToBW")
            mul = _new_node_safe(nt, "ShaderNodeMath")
            if bw and mul:
                try:
                    bw.location = (bx - 320, by + 140)
                    mul.location = (bx - 120, by + 140)
                    mul.operation = 'MULTIPLY'
                except Exception:
                    pass

                _tag_preview_node(bw, "DIFFUSE_BW")
                _tag_preview_node(mul, "DIFFUSE_ROUGH_MULTIPLY", restore={
                    "target_node": bsdf.name,
                    "target_socket": diffuse_rough_in.name,
                    "orig_linked": bool(orig_linked),
                    "orig_from_node": orig_from_node,
                    "orig_from_socket": orig_from_socket,
                    "orig_default": orig_default,
                })

                _unlink_input_socket(nt, diffuse_rough_in)

                if orig_linked and orig_from_node and orig_from_socket:
                    try:
                        src_node = nodes.get(orig_from_node)
                        src_sock = src_node.outputs.get(orig_from_socket) if src_node else None
                        if src_sock:
                            bw_orig = _new_node_safe(nt, "ShaderNodeRGBToBW")
                            if bw_orig is not None:
                                try:
                                    bw_orig.location = (bx - 320, by + 20)
                                except Exception:
                                    pass
                                _tag_preview_node(bw_orig, "DIFFROUGH_ORIG_BW")
                                try:
                                    links.new(src_sock, bw_orig.inputs["Color"])
                                    links.new(bw_orig.outputs["Val"], mul.inputs[0])
                                except Exception:
                                    pass
                            else:
                                try:
                                    links.new(src_sock, mul.inputs[0])
                                except Exception:
                                    pass
                    except Exception:
                        pass
                else:
                    base_val = 1.0
                    try:
                        if orig_default is not None and float(orig_default) > 0.0:
                            base_val = float(orig_default)
                    except Exception:
                        base_val = 1.0
                    val = _new_node_safe(nt, "ShaderNodeValue")
                    if val is not None:
                        try:
                            val.location = (bx - 520, by + 20)
                            val.outputs[0].default_value = float(base_val)
                        except Exception:
                            pass
                        _tag_preview_node(val, "DIFFROUGH_ORIGINAL_VALUE")
                        try:
                            links.new(val.outputs[0], mul.inputs[0])
                        except Exception:
                            pass

                try:
                    links.new(tex.outputs["Color"], bw.inputs["Color"])
                    links.new(bw.outputs["Val"], mul.inputs[1])
                except Exception:
                    pass

                try:
                    links.new(mul.outputs["Value"], diffuse_rough_in)
                    applied_any = True
                except Exception:
                    pass

    # ---------------------------------------------------------------------
    # Specular: use detailSpecular channels per vehicleShader.xml
    #   detailSpecular.r - smoothness  => roughness = 1 - (smoothness * smoothnessScale)
    #   detailSpecular.b - metalness   => metallic = max(original, metalness * metalnessScale)
    # ---------------------------------------------------------------------
    detail_spec = (entry.get("detailSpecular") or "").strip()
    if detail_spec and os.path.isfile(detail_spec):
        rough_in = None
        metal_in = None
        try:
            rough_in = bsdf.inputs.get("Roughness")
        except Exception:
            rough_in = None
        try:
            metal_in = bsdf.inputs.get("Metallic")
        except Exception:
            metal_in = None

        tex = _make_image_texture_node(nt, detail_spec, non_color=True, role="DETAIL_SPECULAR", loc=(bx - 520, by - 220))
        if tex is not None:
            try:
                _configure_detail_preview_teximage_node(tex)
            except Exception:
                pass
            # Apply detail UV transform (preview-only)
            try:
                if detail_uv_out is not None and "Vector" in tex.inputs:
                    links.new(detail_uv_out, tex.inputs["Vector"])
            except Exception:
                pass
            sep = _new_node_safe(nt, "ShaderNodeSeparateRGB")
            if sep is not None:
                try:
                    sep.location = (bx - 320, by - 220)
                except Exception:
                    pass
                _tag_preview_node(sep, "SPEC_SEPARATE_RGB")
                try:
                    links.new(tex.outputs["Color"], sep.inputs["Image"])
                except Exception:
                    pass

            # -----------------------------
            # Roughness output
            # -----------------------------
            if rough_in is not None:
                orig_linked = bool(rough_in.is_linked)
                orig_from_node = ""
                orig_from_socket = ""
                orig_default = None

                if orig_linked:
                    try:
                        lnk = rough_in.links[0]
                        orig_from_node = lnk.from_node.name
                        orig_from_socket = lnk.from_socket.name
                    except Exception:
                        orig_linked = False

                if not orig_linked:
                    try:
                        orig_default = float(rough_in.default_value)
                    except Exception:
                        orig_default = 0.5

                # smooth_scaled = smoothness * smoothnessScale
                smooth_mul = _new_node_safe(nt, "ShaderNodeMath")
                inv_smooth = _new_node_safe(nt, "ShaderNodeMath")  # 1 - smooth_scaled
                mul = _new_node_safe(nt, "ShaderNodeMath")         # orig * (1 - smooth_scaled)

                if smooth_mul is not None and inv_smooth is not None and mul is not None:
                    try:
                        smooth_mul.operation = 'MULTIPLY'
                        smooth_mul.inputs[1].default_value = float(smooth_scale)
                        smooth_mul.location = (bx - 120, by - 180)
                    except Exception:
                        pass
                    _tag_preview_node(smooth_mul, "SMOOTHNESS_SCALE")

                    try:
                        inv_smooth.operation = 'SUBTRACT'
                        inv_smooth.inputs[0].default_value = 1.0
                        inv_smooth.location = (bx + 60, by - 220)
                    except Exception:
                        pass
                    _tag_preview_node(inv_smooth, "ROUGH_FROM_SMOOTHNESS")

                    try:
                        mul.operation = 'MULTIPLY'
                        mul.location = (bx + 240, by - 220)
                    except Exception:
                        pass
                    _tag_preview_node(mul, "ROUGHNESS_MULTIPLY")

                    _unlink_input_socket(nt, rough_in)

                    # Connect smoothness -> smooth_mul
                    try:
                        if sep is not None:
                            links.new(sep.outputs["R"], smooth_mul.inputs[0])
                        else:
                            bw = _new_node_safe(nt, "ShaderNodeRGBToBW")
                            if bw is not None:
                                try:
                                    bw.location = (bx - 320, by - 220)
                                except Exception:
                                    pass
                                _tag_preview_node(bw, "SPEC_BW_FALLBACK")
                                links.new(tex.outputs["Color"], bw.inputs["Color"])
                                links.new(bw.outputs["Val"], smooth_mul.inputs[0])
                    except Exception:
                        pass

                    # Original roughness source
                    if orig_linked and orig_from_node and orig_from_socket:
                        try:
                            src_node = nodes.get(orig_from_node)
                            src_sock = src_node.outputs.get(orig_from_socket) if src_node else None
                            if src_sock:
                                bw_orig = _new_node_safe(nt, "ShaderNodeRGBToBW")
                                if bw_orig is not None:
                                    try:
                                        bw_orig.location = (bx - 320, by - 320)
                                    except Exception:
                                        pass
                                    _tag_preview_node(bw_orig, "ROUGH_ORIG_BW")
                                    links.new(src_sock, bw_orig.inputs["Color"])
                                    links.new(bw_orig.outputs["Val"], mul.inputs[0])
                                else:
                                    links.new(src_sock, mul.inputs[0])
                        except Exception:
                            pass
                    else:
                        val = _new_node_safe(nt, "ShaderNodeValue")
                        if val is not None:
                            try:
                                val.location = (bx - 320, by - 320)
                                val.outputs[0].default_value = 1.0
                            except Exception:
                                pass
                            _tag_preview_node(val, "ROUGH_ORIG_VALUE")
                            try:
                                links.new(val.outputs[0], mul.inputs[0])
                            except Exception:
                                pass

                    # smooth_mul -> inv_smooth -> mul
                    try:
                        links.new(smooth_mul.outputs[0], inv_smooth.inputs[1])
                        links.new(inv_smooth.outputs[0], mul.inputs[1])
                    except Exception:
                        pass

                    # Porosity makes materials appear less glossy in GE; approximate by flooring roughness.
                    if porosity > 0.0:
                        rough_floor = _clamp01(porosity * 0.8)
                        mx = _new_node_safe(nt, "ShaderNodeMath")
                        if mx is not None:
                            try:
                                mx.operation = 'MAXIMUM'
                                mx.location = (bx + 420, by - 220)
                            except Exception:
                                pass
                            _tag_preview_node(mx, "ROUGHNESS_POROSITY_MAX", restore={
                                "target_node": bsdf.name,
                                "target_socket": "Roughness",
                                "orig_linked": bool(orig_linked),
                                "orig_from_node": orig_from_node,
                                "orig_from_socket": orig_from_socket,
                                "orig_default": orig_default,
                            })

                            valfloor = _new_node_safe(nt, "ShaderNodeValue")
                            if valfloor is not None:
                                try:
                                    valfloor.location = (bx + 240, by - 300)
                                    valfloor.outputs[0].default_value = float(rough_floor)
                                except Exception:
                                    pass
                                _tag_preview_node(valfloor, "ROUGHNESS_POROSITY_FLOOR")

                            try:
                                links.new(mul.outputs[0], mx.inputs[0])
                                if valfloor is not None:
                                    links.new(valfloor.outputs[0], mx.inputs[1])
                                else:
                                    mx.inputs[1].default_value = float(rough_floor)
                                links.new(mx.outputs[0], rough_in)
                                applied_any = True
                            except Exception:
                                pass
                        else:
                            # fallback: no porosity floor node
                            _tag_preview_node(mul, "ROUGHNESS_MULTIPLY", restore={
                                "target_node": bsdf.name,
                                "target_socket": "Roughness",
                                "orig_linked": bool(orig_linked),
                                "orig_from_node": orig_from_node,
                                "orig_from_socket": orig_from_socket,
                                "orig_default": orig_default,
                            })
                            try:
                                links.new(mul.outputs[0], rough_in)
                                applied_any = True
                            except Exception:
                                pass
                    else:
                        _tag_preview_node(mul, "ROUGHNESS_MULTIPLY", restore={
                            "target_node": bsdf.name,
                            "target_socket": "Roughness",
                            "orig_linked": bool(orig_linked),
                            "orig_from_node": orig_from_node,
                            "orig_from_socket": orig_from_socket,
                            "orig_default": orig_default,
                        })
                        try:
                            links.new(mul.outputs[0], rough_in)
                            applied_any = True
                        except Exception:
                            pass

            # -----------------------------
            # Metallic output
            # -----------------------------
            if metal_in is not None:
                orig_linked = bool(metal_in.is_linked)
                orig_from_node = ""
                orig_from_socket = ""
                orig_default = None

                if orig_linked:
                    try:
                        lnk = metal_in.links[0]
                        orig_from_node = lnk.from_node.name
                        orig_from_socket = lnk.from_socket.name
                    except Exception:
                        orig_linked = False

                if not orig_linked:
                    try:
                        orig_default = float(metal_in.default_value)
                    except Exception:
                        orig_default = 0.0

                # metal_scaled = metalness * metalnessScale
                metal_mul = _new_node_safe(nt, "ShaderNodeMath")
                mx = _new_node_safe(nt, "ShaderNodeMath")  # max(orig, metal_scaled)
                if metal_mul is not None and mx is not None:
                    try:
                        metal_mul.operation = 'MULTIPLY'
                        metal_mul.inputs[1].default_value = float(metal_scale)
                        metal_mul.location = (bx - 120, by - 340)
                    except Exception:
                        pass
                    _tag_preview_node(metal_mul, "METALNESS_SCALE")

                    try:
                        mx.operation = 'MAXIMUM'
                        mx.location = (bx + 60, by - 340)
                    except Exception:
                        pass
                    _tag_preview_node(mx, "METALLIC_MAX", restore={
                        "target_node": bsdf.name,
                        "target_socket": "Metallic",
                        "orig_linked": bool(orig_linked),
                        "orig_from_node": orig_from_node,
                        "orig_from_socket": orig_from_socket,
                        "orig_default": orig_default,
                    })

                    _unlink_input_socket(nt, metal_in)

                    # Original metallic source
                    if orig_linked and orig_from_node and orig_from_socket:
                        try:
                            src_node = nodes.get(orig_from_node)
                            src_sock = src_node.outputs.get(orig_from_socket) if src_node else None
                            if src_sock:
                                bw_orig = _new_node_safe(nt, "ShaderNodeRGBToBW")
                                if bw_orig is not None:
                                    try:
                                        bw_orig.location = (bx - 320, by - 420)
                                    except Exception:
                                        pass
                                    _tag_preview_node(bw_orig, "METALLIC_ORIG_BW")
                                    links.new(src_sock, bw_orig.inputs["Color"])
                                    links.new(bw_orig.outputs["Val"], mx.inputs[0])
                                else:
                                    links.new(src_sock, mx.inputs[0])
                        except Exception:
                            pass
                    else:
                        val = _new_node_safe(nt, "ShaderNodeValue")
                        if val is not None:
                            try:
                                val.location = (bx - 320, by - 420)
                                val.outputs[0].default_value = float(orig_default if orig_default is not None else 0.0)
                            except Exception:
                                pass
                            _tag_preview_node(val, "METALLIC_ORIG_VALUE")
                            try:
                                links.new(val.outputs[0], mx.inputs[0])
                            except Exception:
                                pass

                    # Metalness from specular blue channel (scaled)
                    try:
                        if sep is not None:
                            links.new(sep.outputs["B"], metal_mul.inputs[0])
                        else:
                            bw = _new_node_safe(nt, "ShaderNodeRGBToBW")
                            if bw is not None:
                                _tag_preview_node(bw, "SPEC_BW_FALLBACK_METAL")
                                links.new(tex.outputs["Color"], bw.inputs["Color"])
                                links.new(bw.outputs["Val"], metal_mul.inputs[0])
                    except Exception:
                        pass

                    try:
                        links.new(metal_mul.outputs[0], mx.inputs[1])
                    except Exception:
                        pass

                    try:
                        links.new(mx.outputs[0], metal_in)
                        applied_any = True
                    except Exception:
                        pass

    # ---------------------------------------------------------------------
    # Normal: combine user normal with detailNormal via Vector Add -> Normalize
    # ---------------------------------------------------------------------
    detail_norm = (entry.get("detailNormal") or "").strip()
    if detail_norm and os.path.isfile(detail_norm) and ("Normal" in bsdf.inputs):
        norm_in = bsdf.inputs["Normal"]
        orig_linked = bool(norm_in.is_linked)
        orig_from_node = ""
        orig_from_socket = ""

        if orig_linked:
            try:
                lnk = norm_in.links[0]
                orig_from_node = lnk.from_node.name
                orig_from_socket = lnk.from_socket.name
            except Exception:
                orig_linked = False

        tex = _make_image_texture_node(nt, detail_norm, non_color=True, role="DETAIL_NORMAL", loc=(bx - 520, by - 380))
        if tex is not None:
            try:
                _configure_detail_preview_teximage_node(tex)
            except Exception:
                pass
            # Apply detail UV transform (preview-only)
            try:
                if detail_uv_out is not None and "Vector" in tex.inputs:
                    links.new(detail_uv_out, tex.inputs["Vector"])
            except Exception:
                pass
            nmap = _new_node_safe(nt, "ShaderNodeNormalMap")
            if nmap is not None:
                try:
                    nmap.location = (bx - 320, by - 380)
                except Exception:
                    pass
                _tag_preview_node(nmap, "DETAIL_NORMALMAP")

                try:
                    links.new(tex.outputs["Color"], nmap.inputs["Color"])
                except Exception:
                    pass

                _unlink_input_socket(nt, norm_in)

                if orig_linked and orig_from_node and orig_from_socket:
                    add = _new_node_safe(nt, "ShaderNodeVectorMath")
                    norm = _new_node_safe(nt, "ShaderNodeVectorMath")
                    if add and norm:
                        try:
                            add.operation = 'ADD'
                            norm.operation = 'NORMALIZE'
                            add.location = (bx - 120, by - 380)
                            norm.location = (bx + 60, by - 380)
                        except Exception:
                            pass
                        _tag_preview_node(add, "NORMAL_ADD")
                        _tag_preview_node(norm, "NORMAL_NORMALIZE", restore={
                            "target_node": bsdf.name,
                            "target_socket": "Normal",
                            "orig_linked": True,
                            "orig_from_node": orig_from_node,
                            "orig_from_socket": orig_from_socket,
                        })

                        try:
                            src_node = nodes.get(orig_from_node)
                            src_sock = src_node.outputs.get(orig_from_socket) if src_node else None
                            if src_sock:
                                links.new(src_sock, add.inputs[0])
                        except Exception:
                            pass
                        try:
                            links.new(nmap.outputs["Normal"], add.inputs[1])
                            links.new(add.outputs["Vector"], norm.inputs[0])
                            links.new(norm.outputs["Vector"], norm_in)
                            applied_any = True
                        except Exception:
                            pass
                else:
                    try:
                        links.new(nmap.outputs["Normal"], norm_in)
                        _tag_preview_node(nmap, "DETAIL_NORMALMAP", restore={
                            "target_node": bsdf.name,
                            "target_socket": "Normal",
                            "orig_linked": False,
                            "orig_from_node": "",
                            "orig_from_socket": "",
                        })
                        applied_any = True
                    except Exception:
                        pass

    return applied_any
def _restore_from_preview_node(node_tree: bpy.types.NodeTree, nodes, restore_json: str, restoring_node=None) -> None:
    if not restore_json:
        return
    try:
        data = json.loads(restore_json)
    except Exception:
        return
    target_node = data.get("target_node") or ""
    target_socket = data.get("target_socket") or ""
    if not target_node or not target_socket:
        return
    bsdf = nodes.get(target_node)
    if bsdf is None:
        return
    inp = bsdf.inputs.get(target_socket)
    if inp is None:
        return

    # If this restore marker belongs to a preview node, only restore when the
    # target socket is currently driven by that same preview node. This prevents
    # stomping persistent hookups like the DECAL image that we intentionally keep.
    if restoring_node is not None:
        try:
            if getattr(inp, 'is_linked', False) and getattr(inp, 'links', None):
                if not any(getattr(lnk, 'from_node', None) == restoring_node for lnk in inp.links):
                    return
        except Exception:
            pass

    _unlink_input_socket(node_tree, inp)

    if data.get("orig_linked"):
        orig_from_node = data.get("orig_from_node") or ""
        orig_from_socket = data.get("orig_from_socket") or ""
        if orig_from_node and orig_from_socket:
            src = nodes.get(orig_from_node)
            out = src.outputs.get(orig_from_socket) if src else None
            if out is not None:
                try:
                    node_tree.links.new(out, inp)
                except Exception:
                    pass
    else:
        orig_default = data.get("orig_default", None)
        if orig_default is not None:
            try:
                inp.default_value = orig_default
            except Exception:
                pass


def _clear_preview_nodes_in_material(mat: bpy.types.Material) -> int:
    if not mat or not mat.use_nodes or not mat.node_tree:
        return 0
    nt = mat.node_tree
    nodes = nt.nodes

    # Restore material-level preview settings (alpha preview can change these).
    _restore_preview_methods(mat)

    # First restore original links/values from any restore markers.
    for n in list(nodes):
        if not _is_preview_only_node(n):
            continue
        # Persistent preview nodes (like a chosen DECAL image) must keep their current
        # hookups; do not run restore markers on them.
        try:
            if bool(n.get('i3d_preview_persist', False)):
                continue
        except Exception:
            pass
        try:
            rj = n.get("i3d_preview_restore", "")
        except Exception:
            try:
                rj = n["i3d_preview_restore"]
            except Exception:
                rj = ""
        if rj:
            _restore_from_preview_node(nt, nodes, rj, restoring_node=n)
        # Optional second restore marker (e.g., DECAL alpha hookup).
        try:
            ra = n.get("i3d_preview_restore_alpha", "")
        except Exception:
            ra = ""
        if ra:
            try:
                _restore_from_preview_node(nt, nodes, ra, restoring_node=n)
            except Exception:
                pass


    # Then remove all preview-tagged nodes.
    removed = 0
    for n in list(nodes):
        # Keep preview-persistent nodes (e.g. user-selected decal base image) even when clearing preview.
        if _is_preview_only_node(n):
            try:
                if bool(n.get("i3d_preview_persist", False)):
                    continue
            except Exception:
                pass
            try:
                nodes.remove(n)
                removed += 1
            except Exception:
                pass
            continue
        if _is_legacy_orphan_preview_node(n):
            try:
                nodes.remove(n)
                removed += 1
            except Exception:
                pass
    return removed


def _apply_preview_preset_to_material(mat: bpy.types.Material, material_template_name: str) -> str:
    """Back-compat wrapper.

    The old code applied scalar Principled presets based on guessed keywords.
    DTAP now wants real detail-map preview injection from materialTemplates.xml.

    Returns 'MAPS' if preview maps were injected, '' otherwise.
    """
    ok = False
    try:
        ok = _apply_material_template_preview_maps(mat, material_template_name)
    except Exception:
        ok = False
    return "MAPS" if ok else ""



def _get_item_material_template_value(item) -> str:
    """Best-effort extraction of the material template name from a color item."""
    if item is None:
        return ""

    # Enum (stored as enum id); use existing helpers if present in this module.
    if hasattr(item, "xml_material_template"):
        try:
            return _mt_value_from_enum_id(item.xml_material_template)  # type: ignore[name-defined]
        except Exception:
            try:
                return str(item.xml_material_template)
            except Exception:
                return ""

    # Raw string field (Giants library colors).
    for attr in ("parentTemplate", "parentTemplateValue", "materialTemplate", "materialTemplateName"):
        if hasattr(item, attr):
            try:
                v = getattr(item, attr)
                return str(v) if v else ""
            except Exception:
                pass

    return ""

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




def _reset_material_node_tree_to_principled(mat: bpy.types.Material) -> bool:
    """Hard reset material nodes to a simple Principled BSDF -> Material Output chain.

    Used by the permanent apply operator so the resulting node setup is 'hard-coded'
    and intentionally overwrites any existing shading nodes.
    """
    if not mat:
        return False
    try:
        mat.use_nodes = True
    except Exception:
        return False

    nt = getattr(mat, "node_tree", None)
    if nt is None:
        return False

    try:
        # Remove all links first
        try:
            for lnk in list(nt.links):
                try:
                    nt.links.remove(lnk)
                except Exception:
                    pass
        except Exception:
            pass

        # Remove all nodes
        try:
            for n in list(nt.nodes):
                try:
                    nt.nodes.remove(n)
                except Exception:
                    pass
        except Exception:
            pass

        out = _new_node_safe(nt, "ShaderNodeOutputMaterial")
        bsdf = _new_node_safe(nt, "ShaderNodeBsdfPrincipled")
        if out is None or bsdf is None:
            return False

        try:
            bsdf.location = (0, 0)
            out.location = (300, 0)
        except Exception:
            pass

        try:
            nt.links.new(bsdf.outputs.get("BSDF"), out.inputs.get("Surface"))
        except Exception:
            # Fallback for older Blender socket name differences
            try:
                nt.links.new(bsdf.outputs[0], out.inputs[0])
            except Exception:
                pass

        return True
    except Exception:
        return False


def _strip_all_preview_tags_in_material(mat: bpy.types.Material) -> int:
    """Remove i3d preview tagging from nodes so they won't be cleared/ignored."""
    if not mat or not mat.use_nodes or not mat.node_tree:
        return 0
    nt = mat.node_tree
    removed = 0
    for n in list(nt.nodes):
        try:
            # Remove known ID props used for preview-only nodes
            for k in ("i3d_preview_only", "i3d_preview_role", "i3d_preview_restore"):
                try:
                    if k in n:
                        del n[k]
                        removed += 1
                except Exception:
                    pass
        except Exception:
            pass
        try:
            lab = getattr(n, "label", "") or ""
            if lab.startswith("I3D_PREVIEW_ONLY:"):
                n.label = lab.replace("I3D_PREVIEW_ONLY:", "", 1)
        except Exception:
            pass
    return removed


def _apply_color_item_permanent_to_material(context, item) -> bool:
    """Permanent variant of Apply-to-Material:
    - Wipes node tree
    - Applies the same preview maps
    - Removes preview tags so nodes are kept for export
    """
    mat = _get_active_material(context)
    if not mat:
        return False

    if not _reset_material_node_tree_to_principled(mat):
        return False

    ok = True
    try:
        col = getattr(item, "color", None)
        if col is not None:
            ok = _apply_color_to_material(mat, tuple(_norm_color(col)))
    except Exception:
        ok = False

    try:
        mt_name = _get_item_material_template_value(item)
        _apply_preview_preset_to_material(mat, mt_name)
    except Exception:
        pass

    try:
        _strip_all_preview_tags_in_material(mat)
    except Exception:
        pass

    return bool(ok)


# -----------------------------------------------------------------------------
# GIANTS Export helpers (Vehicle Shader custom properties)
# -----------------------------------------------------------------------------

def _colorscale_text_for_item(item, src: str) -> str:
    """Return the colorScale string (3 floats) used by GIANTS templates."""
    rgb = _norm_color(getattr(item, "color", (1.0, 1.0, 1.0)))
    cs_attr = ""
    try:
        cs_attr = str(getattr(item, "colorScale", "") or "").strip()
    except Exception:
        cs_attr = ""
    if cs_attr and src in ('GIANTS', 'POPULAR'):
        return cs_attr
    r, g, b = _giants_srgb_triplet_from_color(rgb)
    return f"{r:.4f} {g:.4f} {b:.4f}"


def _clear_vehicle_shader_export_props(mat: bpy.types.Material) -> None:
    """Remove GIANTS Vehicle Shader export custom properties from a material.

    IMPORTANT: This is only called by the *Giants Export* apply button(s) so users can
    switch templates without leaving stale export properties behind.
    """
    if not mat:
        return
    try:
        for k in (
            "customParameterTemplate_brandColor_material",
            "customParameterTemplate_brandColor_brandColor",
            "customParameter_colorScale",
            "customShader",
            "shadingRate",
            "refractionMap",  # legacy/older builds or manual user edits
            "i3d_preview_blend_method_orig",   # legacy
            "i3d_preview_shadow_method_orig",  # legacy
        ):
            try:
                if k in mat:
                    del mat[k]
            except Exception:
                pass
    except Exception:
        pass



# Material templates where the swatch tint is ignored/overridden by detailDiffuse being pre-colored.
# (These should NOT write customParameter_colorScale.)
_NO_COLOR_SCALE_MATERIAL_TEMPLATES = {
    "rubberblack",
    "woodcedar",
    "woodoak",
    "leatherbrown",
}


def _set_vehicle_shader_export_props_material(
    mat: bpy.types.Material,
    *,
    material_template_value: str,
    color_scale_triplet: str,
) -> None:
    """Set export properties for *material-based* brandColor usage.

    Expected keys (when used):
      - customParameter_colorScale
      - customParameterTemplate_brandColor_material (ONLY if material_template_value is set and not 'NONE')
      - customShader
      - shadingRate
    """
    if not mat:
        return
    try:
        mtv = (material_template_value or "").strip()
        mtv_key = mtv.lower()

        # Some "one-off" templates ignore swatch tint (detailDiffuse is already colored).
        wants_colorscale = True
        if mtv and mtv.upper() != "NONE" and mtv_key in _NO_COLOR_SCALE_MATERIAL_TEMPLATES:
            wants_colorscale = False

        if wants_colorscale and color_scale_triplet:
            mat["customParameter_colorScale"] = str(color_scale_triplet)
        else:
            if "customParameter_colorScale" in mat:
                del mat["customParameter_colorScale"]

        if mtv and mtv.upper() != "NONE":
            mat["customParameterTemplate_brandColor_material"] = str(mtv)
        else:
            # DO NOT write the property at all if user selected None
            if "customParameterTemplate_brandColor_material" in mat:
                del mat["customParameterTemplate_brandColor_material"]

        mat["customShader"] = "$data/shaders/vehicleShader.xml"
        mat["shadingRate"] = "1x1"
    except Exception:
        pass


def _set_vehicle_shader_export_props_brandcolor(
    mat: bpy.types.Material,
    *,
    template_name: str,
) -> None:
    """Set export properties for *brandColor templateName* usage (GIANTS library).

    Expected keys:
      - customParameterTemplate_brandColor_brandColor
      - customShader
      - shadingRate
    """
    if not mat:
        return
    try:
        tn = (template_name or "").strip()
        if tn:
            mat["customParameterTemplate_brandColor_brandColor"] = str(tn)
        else:
            if "customParameterTemplate_brandColor_brandColor" in mat:
                del mat["customParameterTemplate_brandColor_brandColor"]

        mat["customShader"] = "$data/shaders/vehicleShader.xml"
        mat["shadingRate"] = "1x1"
    except Exception:
        pass


class I3D_CL_OT_ApplyMyToMaterial(bpy.types.Operator):
    bl_idname = "i3d.cl_my_apply_to_material"
    bl_label = "Apply Temporary preview to Material - No Giants Export"
    bl_description = 'Apply Temporary Preview To Material - "Use to preview what the color selection will look like once its in Giants Editor and in game this will be ignored during export and can be removed in bulk on export tab"'
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

        item = scene.i3d_cl_my_colors[idx]
        mt_name = _get_item_material_template_value(item)

        # Decal TEMP preview: ask for user base-color image if none exists.
        if _mtpl_is_decal(mt_name):
            # For decals, remember the chosen base image per My Color Library entry.
            stored_fp = str(getattr(item, "decal_image_path", "") or "").strip()
            if stored_fp and (not os.path.isfile(stored_fp)):
                stored_fp = ""

            base_fp = stored_fp or _material_get_basecolor_image_filepath(mat)
            if not base_fp:
                # First-time: ask user to pick an image; the picker will remember it on the item.
                return bpy.ops.i3d.cl_pick_decal_base_image('INVOKE_DEFAULT', src='MY', index=idx, is_permanent=False)

            # If we discovered the decal image from the material and the item doesn't have one yet, store it.
            try:
                if (not stored_fp) and base_fp:
                    item.decal_image_path = base_fp
                    schedule_save()
            except Exception:
                pass

            ok = _apply_color_to_material(mat, tuple(_norm_color(item.color)))
            try:
                with _mtpl_apply_overrides(
                    detail_diffuse_mode='DECAL',
                    decal_image_path=base_fp,
                    decal_persist=True,
                    apply_alpha=True,
                ):
                    _apply_preview_preset_to_material(mat, mt_name)
            except Exception:
                pass

            self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
            return {'FINISHED'} if ok else {'CANCELLED'}

        # Normal TEMP preview
        ok = _apply_color_to_material(mat, tuple(_norm_color(item.color)))
        if ok:
            _apply_preview_preset_to_material(mat, mt_name)

        self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
        return {'FINISHED'} if ok else {'CANCELLED'}






class I3D_CL_OT_ApplyMyToMaterialExport(bpy.types.Operator):
    bl_idname = "i3d.cl_my_apply_to_material_export"
    bl_label = "Apply Temporary preview to Material and apply material and shader for Giants Export"
    bl_description = "Apply Temporary Preview to the active Blender Material and set GIANTS Vehicle Shader export custom properties."
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

        item = scene.i3d_cl_my_colors[idx]
        mt_name = _xml_material_template_from_item(item)

        if _mtpl_is_decal(mt_name):
            stored_fp = str(getattr(item, "decal_image_path", "") or "").strip()
            if stored_fp and (not os.path.isfile(stored_fp)):
                stored_fp = ""

            base_fp = stored_fp or _material_get_basecolor_image_filepath(mat)
            if not base_fp:
                return bpy.ops.i3d.cl_pick_decal_base_image('INVOKE_DEFAULT', src='MY', index=idx, is_permanent=False, set_export_props=True)

            try:
                if (not stored_fp) and base_fp:
                    item.decal_image_path = base_fp
                    schedule_save()
            except Exception:
                pass

            ok = _apply_color_to_material(mat, tuple(item.color))
            try:
                with _mtpl_apply_overrides(
                    detail_diffuse_mode="DECAL",
                    decal_image_path=base_fp,
                    decal_persist=True,
                    apply_alpha=True,
                ):
                    _apply_preview_preset_to_material(mat, mt_name)
            except Exception:
                pass

            if ok:
                _clear_vehicle_shader_export_props(mat)
                _set_vehicle_shader_export_props_material(
                    mat,
                    material_template_value=_get_item_material_template_value(item),
                    color_scale_triplet=_colorscale_text_for_item(item, 'MY'),
                )

            self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
            return {'FINISHED'} if ok else {'CANCELLED'}

        ok = _apply_color_to_material(mat, tuple(item.color))
        if ok:
            _apply_preview_preset_to_material(mat, mt_name)
            _clear_vehicle_shader_export_props(mat)
            _set_vehicle_shader_export_props_material(
                mat,
                material_template_value=_get_item_material_template_value(item),
                color_scale_triplet=_colorscale_text_for_item(item, 'MY'),
            )

        self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
        return {'FINISHED'} if ok else {'CANCELLED'}

class I3D_CL_OT_ApplyMyToMaterialPermanent(bpy.types.Operator):
    bl_idname = "i3d.cl_my_apply_to_material_permanent"
    bl_label = "Apply permanently To Material using No Shader During Export - Not Suggested"
    bl_description = 'Apply Permanently To Material For Export - "use for meshes you do not wish to use a slot name with and allow color changing in game to undo this you must delete the material or manually delete in shading workspace"'
    bl_options = {'UNDO'}


    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_my_index
        if not (0 <= idx < len(scene.i3d_cl_my_colors)):
            self.report({'WARNING'}, "No color selected")
            return {'CANCELLED'}

        item = scene.i3d_cl_my_colors[idx]

        mat = _get_active_material(context)
        if not mat:
            self.report({'WARNING'}, "No active material found")
            return {'CANCELLED'}

        mt_name = _xml_material_template_from_item(item)

        if _mtpl_blocks_permanent(mt_name):
            self.report({'WARNING'}, "This Material Type requires the Vehicle Shader and cannot be applied as Permanent.")
            return {'CANCELLED'}

        # Decals: use the stored decal image for this My Color Library entry when available.
        if _mtpl_is_decal(mt_name):
            stored_fp = str(getattr(item, "decal_image_path", "") or "").strip()
            if stored_fp and (not os.path.isfile(stored_fp)):
                stored_fp = ""

            base_fp = stored_fp or _material_get_basecolor_image_filepath(mat)
            if not base_fp:
                return bpy.ops.i3d.cl_pick_decal_base_image('INVOKE_DEFAULT', src='MY', index=idx, is_permanent=True)

            try:
                if (not stored_fp) and base_fp:
                    item.decal_image_path = base_fp
                    schedule_save()
            except Exception:
                pass

            try:
                with _mtpl_apply_overrides(
                    detail_diffuse_mode="DECAL",
                    decal_image_path=base_fp,
                    decal_persist=False,
                    apply_alpha=True,
                ):
                    ok = _apply_color_item_permanent_to_material(context, item)
            except Exception:
                ok = False
        elif _mtpl_needs_detail_prompt(mt_name):
            return bpy.ops.i3d.cl_perm_apply_detail_prompt('INVOKE_DEFAULT', src='MY', index=idx)
        else:
            ok = _apply_color_item_permanent_to_material(context, item)

        self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
        return {'FINISHED'} if ok else {'CANCELLED'}

class I3D_CL_OT_ApplyMyToGiantsColorScale(bpy.types.Operator):
    bl_idname = "i3d.cl_my_apply_to_giants_colorscale"
    bl_label = "Apply Temporary preview to Material - No Giants Export"
    bl_description = "Applies the selected My Color Library entry as a temporary preview on the active material (GIANTS-style colorScale)."
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
    bl_description = "Copies the selected color value (HEX, RGB, or colorScale) to the clipboard."

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
    bl_description = "Reloads the GIANTS Color Library from the game files and refreshes the list."

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
    bl_description = "Reloads the Popular Color Library and refreshes the list."

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
    bl_label = "Apply Temporary preview to Material - No Giants Export"
    bl_description = 'Apply Temporary Preview To Material - "Use to preview what the color selection will look like once its in Giants Editor and in game this will be ignored during export and can be removed in bulk on export tab"'
    bl_options = {'UNDO'}
    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_giants_index
        if not (0 <= idx < len(scene.i3d_cl_giants_colors)):
            self.report({'WARNING'}, "No color selected")
            return {'CANCELLED'}

        mat = _get_active_material(context)
        if not mat:
            self.report({'WARNING'}, "No active material")
            return {'CANCELLED'}

        item = scene.i3d_cl_giants_colors[idx]
        mt_name = _get_item_material_template_value(item)

        if _mtpl_is_decal(mt_name):
            base_fp = _material_get_basecolor_image_filepath(mat)
            if not base_fp:
                return bpy.ops.i3d.cl_pick_decal_base_image('INVOKE_DEFAULT', src='GIANTS', index=idx, is_permanent=False)

            ok = _apply_color_to_material(mat, tuple(_norm_color(item.color)))
            try:
                with _mtpl_apply_overrides(detail_diffuse_mode='SKIP', apply_alpha=True):
                    _apply_preview_preset_to_material(mat, mt_name)
            except Exception:
                pass

            self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
            return {'FINISHED'} if ok else {'CANCELLED'}

        ok = _apply_color_to_material(mat, tuple(_norm_color(item.color)))
        if ok:
            _apply_preview_preset_to_material(mat, mt_name)

        self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
        return {'FINISHED'} if ok else {'CANCELLED'}






class I3D_CL_OT_ApplyGiantsToMaterialExport(bpy.types.Operator):
    bl_idname = "i3d.cl_giants_apply_to_material_export"
    bl_label = "Apply Temporary preview to Material and apply material and shader for Giants Export"
    bl_description = "Apply Temporary Preview to the active Blender Material and set GIANTS Vehicle Shader export custom properties."
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_giants_index
        if not (0 <= idx < len(scene.i3d_cl_giants_colors)):
            self.report({'WARNING'}, "No color selected")
            return {'CANCELLED'}

        mat = _get_active_material(context)
        if not mat:
            self.report({'WARNING'}, "No active material")
            return {'CANCELLED'}

        item = scene.i3d_cl_giants_colors[idx]
        mt_name = _get_item_material_template_value(item)

        if _mtpl_is_decal(mt_name):
            base_fp = _material_get_basecolor_image_filepath(mat)
            if not base_fp:
                return bpy.ops.i3d.cl_pick_decal_base_image('INVOKE_DEFAULT', src='GIANTS', index=idx, is_permanent=False, set_export_props=True)

            ok = _apply_color_to_material(mat, tuple(_norm_color(item.color)))
            try:
                with _mtpl_apply_overrides(detail_diffuse_mode='SKIP', apply_alpha=True):
                    _apply_preview_preset_to_material(mat, mt_name)
            except Exception:
                pass

            if ok:
                _clear_vehicle_shader_export_props(mat)
                _set_vehicle_shader_export_props_brandcolor(
                    mat,
                    template_name=getattr(item, "name", "") or "",
                )

            self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
            return {'FINISHED'} if ok else {'CANCELLED'}

        ok = _apply_color_to_material(mat, tuple(_norm_color(item.color)))
        if ok:
            _apply_preview_preset_to_material(mat, mt_name)
            _clear_vehicle_shader_export_props(mat)
            _set_vehicle_shader_export_props_brandcolor(
                mat,
                template_name=getattr(item, "name", "") or "",
            )

        self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
        return {'FINISHED'} if ok else {'CANCELLED'}

class I3D_CL_OT_ApplyGiantsToMaterialPermanent(bpy.types.Operator):
    bl_idname = "i3d.cl_giants_apply_to_material_permanent"
    bl_label = "Apply permanently To Material using No Shader During Export - Not Suggested"
    bl_description = 'Apply Permanently To Material For Export - "use for meshes you do not wish to use a slot name with and allow color changing in game to undo this you must delete the material or manually delete in shading workspace"'
    bl_options = {'UNDO'}


    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_giants_index
        if not (0 <= idx < len(scene.i3d_cl_giants_colors)):
            self.report({'WARNING'}, "No GIANTS color selected")
            return {'CANCELLED'}

        item = scene.i3d_cl_giants_colors[idx]

        mat = _get_active_material(context)
        if not mat:
            self.report({'WARNING'}, "No active material found")
            return {'CANCELLED'}

        mt_name = _xml_material_template_from_item(item)

        if _mtpl_blocks_permanent(mt_name):
            self.report({'WARNING'}, "This Material Type requires the Vehicle Shader and cannot be applied as Permanent.")
            return {'CANCELLED'}

        # Decals: use existing Base Color image if present, otherwise prompt to pick one.
        if _mtpl_is_decal(mt_name):
            base_fp = _material_get_basecolor_image_filepath(mat)
            if not base_fp:
                return bpy.ops.i3d.cl_pick_decal_base_image('INVOKE_DEFAULT', src='GIANTS', index=idx, is_permanent=True)
            try:
                with _mtpl_apply_overrides(
                    detail_diffuse_mode="DECAL",
                    decal_image_path=base_fp,
                    decal_persist=False,
                    apply_alpha=True,
                ):
                    ok = _apply_color_item_permanent_to_material(context, item)
            except Exception:
                ok = False
        elif _mtpl_needs_detail_prompt(mt_name):
            return bpy.ops.i3d.cl_perm_apply_detail_prompt('INVOKE_DEFAULT', src='GIANTS', index=idx)
        else:
            ok = _apply_color_item_permanent_to_material(context, item)

        self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
        return {'FINISHED'} if ok else {'CANCELLED'}

class I3D_CL_OT_ApplyGiantsToGiantsColorScale(bpy.types.Operator):
    bl_idname = "i3d.cl_giants_apply_to_giants_colorscale"
    bl_label = "Apply Temporary preview to Material - No Giants Export"
    bl_description = "Applies the selected GIANTS Library entry as a temporary preview on the active material (GIANTS-style colorScale)."
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
    bl_description = "Copies the selected GIANTS color into My Color Library."
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_giants_index
        if not (0 <= idx < len(scene.i3d_cl_giants_colors)):
            self.report({'WARNING'}, "No GIANTS color selected")
            return {'CANCELLED'}

        g = scene.i3d_cl_giants_colors[idx]
        unique_name = _ensure_unique_my_library_name(scene, g.name)
        it = scene.i3d_cl_my_colors.add()
        it.name = unique_name
        it.color = g.color
        scene.i3d_cl_my_index = len(scene.i3d_cl_my_colors) - 1
        schedule_save()
        self.report({'INFO'}, "Added to My Library")
        return {'FINISHED'}



class I3D_CL_OT_ApplyPopularToMaterial(bpy.types.Operator):
    bl_idname = "i3d.cl_popular_apply_to_material"
    bl_label = "Apply Temporary preview to Material - No Giants Export"
    bl_description = 'Apply Temporary Preview To Material - "Use to preview what the color selection will look like once its in Giants Editor and in game this will be ignored during export and can be removed in bulk on export tab"'
    bl_options = {'UNDO'}
    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_popular_index
        if not (0 <= idx < len(scene.i3d_cl_popular_colors)):
            self.report({'WARNING'}, "No color selected")
            return {'CANCELLED'}

        mat = _get_active_material(context)
        if not mat:
            self.report({'WARNING'}, "No active material")
            return {'CANCELLED'}

        item = scene.i3d_cl_popular_colors[idx]
        mt_name = _get_item_material_template_value(item)

        if _mtpl_is_decal(mt_name):
            base_fp = _material_get_basecolor_image_filepath(mat)
            if not base_fp:
                return bpy.ops.i3d.cl_pick_decal_base_image('INVOKE_DEFAULT', src='POPULAR', index=idx, is_permanent=False)

            ok = _apply_color_to_material(mat, tuple(_norm_color(item.color)))
            try:
                with _mtpl_apply_overrides(detail_diffuse_mode='SKIP', apply_alpha=True):
                    _apply_preview_preset_to_material(mat, mt_name)
            except Exception:
                pass

            self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
            return {'FINISHED'} if ok else {'CANCELLED'}

        ok = _apply_color_to_material(mat, tuple(_norm_color(item.color)))
        if ok:
            _apply_preview_preset_to_material(mat, mt_name)

        self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
        return {'FINISHED'} if ok else {'CANCELLED'}






class I3D_CL_OT_ApplyPopularToMaterialExport(bpy.types.Operator):
    bl_idname = "i3d.cl_popular_apply_to_material_export"
    bl_label = "Apply Temporary preview to Material and apply material and shader for Giants Export"
    bl_description = "Apply Temporary Preview to the active Blender Material and set GIANTS Vehicle Shader export custom properties."
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_popular_index
        if not (0 <= idx < len(scene.i3d_cl_popular_colors)):
            self.report({'WARNING'}, "No color selected")
            return {'CANCELLED'}

        mat = _get_active_material(context)
        if not mat:
            self.report({'WARNING'}, "No active material")
            return {'CANCELLED'}

        item = scene.i3d_cl_popular_colors[idx]
        mt_name = _get_item_material_template_value(item)

        if _mtpl_is_decal(mt_name):
            self.report({'WARNING'}, "Decal is not allowed in Popular Library")
            return {'CANCELLED'}

        ok = _apply_color_to_material(mat, tuple(_norm_color(item.color)))
        if ok:
            _apply_preview_preset_to_material(mat, mt_name)
            _clear_vehicle_shader_export_props(mat)
            _set_vehicle_shader_export_props_material(
                mat,
                material_template_value=_get_item_material_template_value(item),
                color_scale_triplet=_colorscale_text_for_item(item, 'POPULAR'),
            )

        self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
        return {'FINISHED'} if ok else {'CANCELLED'}

class I3D_CL_OT_ApplyPopularToMaterialPermanent(bpy.types.Operator):
    bl_idname = "i3d.cl_popular_apply_to_material_permanent"
    bl_label = "Apply permanently To Material using No Shader During Export - Not Suggested"
    bl_description = 'Apply Permanently To Material For Export - "use for meshes you do not wish to use a slot name with and allow color changing in game to undo this you must delete the material or manually delete in shading workspace"'
    bl_options = {'UNDO'}


    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_popular_index
        if not (0 <= idx < len(scene.i3d_cl_popular_colors)):
            self.report({'WARNING'}, "No Popular color selected")
            return {'CANCELLED'}

        item = scene.i3d_cl_popular_colors[idx]

        mat = _get_active_material(context)
        if not mat:
            self.report({'WARNING'}, "No active material found")
            return {'CANCELLED'}

        mt_name = _xml_material_template_from_item(item)

        if _mtpl_blocks_permanent(mt_name):
            self.report({'WARNING'}, "This Material Type requires the Vehicle Shader and cannot be applied as Permanent.")
            return {'CANCELLED'}

        # Decals: use existing Base Color image if present, otherwise prompt to pick one.
        if _mtpl_is_decal(mt_name):
            base_fp = _material_get_basecolor_image_filepath(mat)
            if not base_fp:
                return bpy.ops.i3d.cl_pick_decal_base_image('INVOKE_DEFAULT', src='POPULAR', index=idx, is_permanent=True)
            try:
                with _mtpl_apply_overrides(
                    detail_diffuse_mode="DECAL",
                    decal_image_path=base_fp,
                    decal_persist=False,
                    apply_alpha=True,
                ):
                    ok = _apply_color_item_permanent_to_material(context, item)
            except Exception:
                ok = False
        elif _mtpl_needs_detail_prompt(mt_name):
            return bpy.ops.i3d.cl_perm_apply_detail_prompt('INVOKE_DEFAULT', src='POPULAR', index=idx)
        else:
            ok = _apply_color_item_permanent_to_material(context, item)

        self.report({'INFO'} if ok else {'WARNING'}, "Applied" if ok else "Material could not be updated")
        return {'FINISHED'} if ok else {'CANCELLED'}

class I3D_CL_OT_ApplyPopularToGiantsColorScale(bpy.types.Operator):
    bl_idname = "i3d.cl_popular_apply_to_giants_colorscale"
    bl_label = "Apply Temporary preview to Material - No Giants Export"
    bl_description = "Applies the selected Popular Library entry as a temporary preview on the active material (GIANTS-style colorScale)."
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
    bl_description = "Copies the selected Popular color into My Color Library."
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        idx = scene.i3d_cl_popular_index
        if not (0 <= idx < len(scene.i3d_cl_popular_colors)):
            self.report({'WARNING'}, "No Popular color selected")
            return {'CANCELLED'}

        g = scene.i3d_cl_popular_colors[idx]
        unique_name = _ensure_unique_my_library_name(scene, g.name)
        it = scene.i3d_cl_my_colors.add()
        it.name = unique_name
        it.color = g.color
        scene.i3d_cl_my_index = len(scene.i3d_cl_my_colors) - 1
        schedule_save()
        self.report({'INFO'}, "Added to My Library")
        return {'FINISHED'}





class I3D_CL_OT_PickDecalBaseImage(bpy.types.Operator, ImportHelper):
    bl_idname = "i3d.cl_pick_decal_base_image"
    bl_label = "Select Decal Base Color Image"
    bl_description = "Pick an image file to use as the decal's Base Color (and optional alpha) for preview/permanent apply."
    bl_options = {'UNDO'}

    filename_ext = ""
    filter_glob: bpy.props.StringProperty(
        default="*.dds;*.png;*.tga;*.jpg;*.jpeg;*.tif;*.tiff",
        options={'HIDDEN'},
        maxlen=255,
    )

    src: bpy.props.EnumProperty(
        items=[('MY', 'My', ''), ('GIANTS', 'Giants', ''), ('POPULAR', 'Popular', '')],
        name="Source Library",
        default='MY',
    )
    index: bpy.props.IntProperty(name="Index", default=-1)

    set_export_props: bpy.props.BoolProperty(
        name="Set GIANTS Export Props",
        description="If enabled, also set Vehicle Shader export custom properties on the material.",
        default=False,
    )
    is_permanent: bpy.props.BoolProperty(name="Permanent", default=False)

    set_export_props: bpy.props.BoolProperty(
        name="Set GIANTS Export Props",
        description="If enabled, also set Vehicle Shader export custom properties on the material.",
        default=False,
    )

    def execute(self, context):
        mat = _get_active_material(context)
        if not mat:
            self.report({'WARNING'}, "No active material found")
            return {'CANCELLED'}

        # Resolve item from chosen library
        scene = context.scene
        item = None
        try:
            if self.src == 'MY':
                item = scene.i3d_cl_my_colors[self.index]
            elif self.src == 'GIANTS':
                item = scene.i3d_cl_giants_colors[self.index]
            else:
                item = scene.i3d_cl_popular_colors[self.index]
        except Exception:
            item = None

        if item is None:
            self.report({'WARNING'}, "Invalid item selection")
            return {'CANCELLED'}

        fp = str(getattr(self, "filepath", "") or "").strip()
        if not fp:
            self.report({'WARNING'}, "No file selected")
            return {'CANCELLED'}

        # Prefer .dds when the user picked a .png and a matching .dds exists.
        try:
            fp = _prefer_dds(fp)
        except Exception:
            pass

        # Remember the decal image path for My Color Library so it persists across sessions.
        if self.src == 'MY':
            try:
                item.decal_image_path = fp
            except Exception:
                pass

        # Apply with overrides: DECAL base color image + alpha
        try:
            with _mtpl_apply_overrides(
                detail_diffuse_mode="DECAL",
                decal_image_path=fp,
                decal_persist=(not self.is_permanent),
                apply_alpha=True,
            ):
                if self.is_permanent:
                    ok = _apply_color_item_permanent_to_material(context, item)
                else:
                    # Temporary preview apply: keep nodes preview-only + optionally persistent
                    mt_name = _xml_material_template_from_item(item)
                    _apply_color_to_material(mat, tuple(item.color))
                    _apply_preview_preset_to_material(mat, mt_name)
                    ok = True
        except Exception:
            ok = False

        if not ok:
            self.report({'WARNING'}, "Decal apply failed")
            return {'CANCELLED'}

        if self.set_export_props:
            mat = _get_active_material(context)
            if mat and item:
                _clear_vehicle_shader_export_props(mat)
                if self.src == 'GIANTS':
                    _set_vehicle_shader_export_props_brandcolor(
                        mat,
                        template_name=getattr(item, "name", "") or "",
                    )
                else:
                    _set_vehicle_shader_export_props_material(
                        mat,
                        material_template_value=_get_item_material_template_value(item),
                        color_scale_triplet=_colorscale_text_for_item(item, self.src),
                    )

        schedule_save()
        self.report({'INFO'}, "Decal image applied")
        return {'FINISHED'}



class I3D_CL_OT_ShowDecalPreview(bpy.types.Operator):
    bl_idname = "i3d.cl_show_decal_preview"
    bl_label = "Decal Preview"
    bl_description = "Show a larger preview of the decal image for this My Color Library entry"
    bl_options = {'INTERNAL'}

    index: bpy.props.IntProperty(name="Index", default=-1)

    def invoke(self, context, event):
        # Cache icon id for the popup session so draw() is cheap.
        self._icon_id = 0
        self._filepath = ""
        try:
            item = context.scene.i3d_cl_my_colors[self.index]
            self._filepath = str(getattr(item, "decal_image_path", "") or "")
            self._icon_id = _cl_decal_icon_id(self._filepath)
        except Exception:
            self._icon_id = 0
            self._filepath = ""

        # Wider popup so the preview is useful.
        return context.window_manager.invoke_popup(self, width=560)

    def draw(self, context):
        layout = self.layout
        if getattr(self, "_icon_id", 0):
            layout.template_icon(icon_value=int(self._icon_id), scale=12.0)
            if getattr(self, "_filepath", ""):
                layout.label(text=bpy.path.basename(str(self._filepath)))
        else:
            layout.label(text="Decal image preview not available.")
            if getattr(self, "_filepath", ""):
                layout.label(text=str(self._filepath))

    def execute(self, context):
        return {'FINISHED'}


class I3D_CL_OT_PermApplyDetailPrompt(bpy.types.Operator):
    bl_idname = "i3d.cl_perm_apply_detail_prompt"
    bl_label = "Permanent Apply Options"
    bl_description = "Choose how to apply detailDiffuse for Permanent materials (keep detail vs keep color)."
    bl_options = {'INTERNAL'}

    src: bpy.props.EnumProperty(
        items=[('MY', 'My', ''), ('GIANTS', 'Giants', ''), ('POPULAR', 'Popular', '')],
        name="Source Library",
        default='MY',
    )
    index: bpy.props.IntProperty(name="Index", default=-1)

    choice: bpy.props.EnumProperty(
        items=[
            ('KEEP_DETAIL', "Prioritize Detail (No Color)", ""),
            ('KEEP_COLOR', "Prioritize Color (May lack detail)", ""),
        ],
        name="Apply Mode",
        default='KEEP_DETAIL',
    )
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=820)

    def draw(self, context):
        layout = self.layout
        layout.label(text="This Material Type can not be permanently applied with Color and Detail at the same time using this tool,")
        layout.label(text="in order to have both in Giants Editor the vehicle shader is required.")
        layout.separator()
        layout.label(text="Choose how to apply it as a Permanent Blender Material for export.")
        layout.separator()
        layout.prop(self, "choice", expand=True)
        layout.separator()
        layout.label(text="Tip: For the Best Result in game, Apply as Temporary Preview and add the vehicle Shader")
        layout.label(text="using the shader setup folder above this color Library tool then apply the material type there.")
        layout.separator()
        layout.label(text="Tip: Temporary Preview + Vehicle Shader is the most accurate option.")
        layout.label(text="Close this window or press Cancel to abort.")

    def execute(self, context):
        scene = context.scene
        item = None
        try:
            if self.src == 'MY':
                item = scene.i3d_cl_my_colors[self.index]
            elif self.src == 'GIANTS':
                item = scene.i3d_cl_giants_colors[self.index]
            else:
                item = scene.i3d_cl_popular_colors[self.index]
        except Exception:
            item = None
        if item is None:
            self.report({'WARNING'}, "Invalid item selection")
            return {'CANCELLED'}
        mt_name = _xml_material_template_from_item(item)
        mode = 'SKIP' if self.choice == 'KEEP_COLOR' else 'ALBEDO'

        try:
            with _mtpl_apply_overrides(detail_diffuse_mode=mode):
                ok = _apply_color_item_permanent_to_material(context, item)
        except Exception:
            ok = False

        if not ok:
            self.report({'WARNING'}, "Permanent apply failed")
            return {'CANCELLED'}

        schedule_save()
        self.report({'INFO'}, "Applied Permanently")
        return {'FINISHED'}


class I3D_CL_OT_ClearPreviewMaterialNodes(bpy.types.Operator):
    bl_idname = "i3d.colorlib_clear_preview_material_nodes"
    bl_label = "Clear all temporary preview material shader Nodes"
    bl_description = "Remove all I3D_PREVIEW_ONLY nodes from all materials and restore original connections where possible."
    bl_options = {'UNDO'}

    def execute(self, context):
        mats_touched = 0
        nodes_removed = 0

        for mat in getattr(bpy.data, "materials", []):
            if not mat or not getattr(mat, "use_nodes", False) or not getattr(mat, "node_tree", None):
                continue
            try:
                removed = _clear_preview_nodes_in_material(mat)
            except Exception:
                removed = 0
            if removed:
                mats_touched += 1
                nodes_removed += int(removed)

        self.report({'INFO'}, f"Cleared preview nodes from {mats_touched} material(s) ({nodes_removed} node(s) removed)")
        return {'FINISHED'}



# -----------------------------------------------------------------------------
# UI Lists
# -----------------------------------------------------------------------------


class I3D_CL_UL_MyColors(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        prefs = _cl_get_prefs(context)

        is_xml = (getattr(context.scene, 'i3d_cl_output_mode', 'MATERIAL') == 'XML')
        is_decal = False
        has_decal_path = False
        try:
            is_decal = _mtpl_is_decal(_get_item_material_template_value(item))
            has_decal_path = bool(str(getattr(item, "decal_image_path", "") or "").strip())
        except Exception:
            is_decal = False
            has_decal_path = False

        # Use the same name-column splitter that the preferences slider controls.
        # (Slider: Preferences -> Add-ons -> Color Library UI -> "Color List: Name Column")
        name_ratio = float(getattr(prefs, 'colorlib_name_ratio', 0.78)) if prefs else 0.78
        try:
            name_ratio = max(0.40, min(0.90, float(name_ratio)))
        except Exception:
            name_ratio = 0.78

        if is_xml:
            row = layout.row(align=True)
            row.prop(item, "xml_selected", text="")

            split = row.split(factor=name_ratio, align=True)
            col_name = split.column(align=True)
            col_name.prop(item, "name", text="", emboss=False)

            right = split.row(align=True)

            # After first decal apply, show a Change Image button between Name and Material Type.
            # Icon-only keeps the row compact; tooltip explains the action.
            if is_decal and has_decal_path:
                op = right.operator("i3d.cl_pick_decal_base_image", text="", icon='IMAGE_DATA')
                op.src = 'MY'
                op.index = index
                op.is_permanent = False
                op.set_export_props = False

            right.prop(item, "xml_material_template", text="")
            chip = right.row(align=True)
            if is_decal and has_decal_path:
                icon_id = _cl_decal_icon_id(getattr(item, "decal_image_path", "") or "")
                if icon_id:
                    op = chip.operator("i3d.cl_show_decal_preview", text="", icon_value=icon_id, emboss=False)
                    op.index = index
                else:
                    chip.label(text="", icon='IMAGE_DATA')
            else:
                chip.prop(item, "color", text="")

        else:
            split = layout.split(factor=name_ratio, align=True)
            col_name = split.column(align=True)
            col_name.prop(item, "name", text="", emboss=False)

            right = split.row(align=True)

            if is_decal and has_decal_path:
                op = right.operator("i3d.cl_pick_decal_base_image", text="", icon='IMAGE_DATA')
                op.src = 'MY'
                op.index = index
                op.is_permanent = False
                op.set_export_props = False

            right.prop(item, "xml_material_template", text="")
            chip = right.row(align=True)
            if is_decal and has_decal_path:
                icon_id = _cl_decal_icon_id(getattr(item, "decal_image_path", "") or "")
                if icon_id:
                    op = chip.operator("i3d.cl_show_decal_preview", text="", icon_value=icon_id, emboss=False)
                    op.index = index
                else:
                    chip.label(text="", icon='IMAGE_DATA')
            else:
                chip.prop(item, "color", text="")
            # NOTE: My Color Library already shows the color preview swatch.
            # Do not also show the numeric color value in the list rows.


    def draw_filter(self, context, layout):
        # Keep the standard UIList filter controls (Search + Sort A-Z + Reverse),
        # and add a custom "Sort by Selected Material" button beside them.
        row = layout.row(align=True)
        row.prop(self, "filter_name", text="", icon='VIEWZOOM')
        row.prop(self, "use_filter_sort_alpha", text="", icon='SORTALPHA')
        row.prop(self, "use_filter_sort_reverse", text="", icon='ARROW_LEFTRIGHT')
        row.operator("i3d.cl_my_sort_by_selected_material", text="", icon='MATERIAL')



class I3D_CL_UL_GiantsColors(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        prefs = _cl_get_prefs(context)
        if getattr(context.scene, 'i3d_cl_output_mode', 'MATERIAL') == 'XML':
            row = layout.row(align=True)
            row.prop(item, "xml_selected", text="")
            split = row.split(factor=0.45)
            split.label(text=item.name)
            mid = split.split(factor=0.65)
            mid.label(text=(getattr(item, "parentTemplate", "") or ""))
            chip = mid.row(align=True)
            chip.enabled = False
            chip.prop(item, "color", text="")
        else:
            split = layout.split(factor=float(getattr(prefs, 'colorlib_name_ratio', 0.78)) if prefs else 0.78)
            split.label(text=item.name)
            mid = split.split(factor=0.65)
            mid.label(text=(getattr(item, "parentTemplate", "") or ""))
            chip = mid.row(align=True)
            chip.enabled = False
            chip.prop(item, "color", text="")



class I3D_CL_UL_PopularColors(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        prefs = _cl_get_prefs(context)
        if getattr(context.scene, 'i3d_cl_output_mode', 'MATERIAL') == 'XML':
            row = layout.row(align=True)
            row.prop(item, "xml_selected", text="")
            split = row.split(factor=0.45)
            split.label(text=item.name)
            right = split.split(factor=0.70)
            right.prop(item, "xml_material_template", text="")
            chip = right.row(align=True)
            chip.enabled = False
            chip.prop(item, "color", text="")
        else:
            split = layout.split(factor=float(getattr(prefs, 'colorlib_name_ratio', 0.60)) if prefs else 0.60)
            split.label(text=item.name)
            right = split.split(factor=0.70)
            right.prop(item, "xml_material_template", text="")
            chip = right.row(align=True)
            chip.enabled = False
            chip.prop(item, "color", text="")






class I3D_CL_OT_SetEmissionBlack(bpy.types.Operator):
    bl_idname = "i3d.cl_set_emission_black"
    bl_label = "Set Emission (Black)"
    bl_description = "Set Principled BSDF Emission Color to black (#000000FF) on the active material"
    bl_options = {'UNDO'}

    strength: bpy.props.FloatProperty(
        name="Strength",
        default=0.0,
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
# XML export helpers + operators
# -----------------------------------------------------------------------------

_XML_TAG_ORDER = [
    "rimColorConfiguration",
    "baseColorConfiguration",
    "designColorConfiguration",
    "designColor2Configuration",
    "designColor3Configuration",
    "designColor4Configuration",
    "designColor5Configuration",
    "designColor6Configuration",
    "designColor7Configuration",
    "designColor8Configuration",
    "designColor9Configuration",
    "designColor10Configuration",
    "designColor11Configuration",
    "designColor12Configuration",
    "designColor13Configuration",
    "designColor14Configuration",
    "designColor15Configuration",
    "designColor16Configuration",
    "wrappingColorConfiguration",
]


def _xml_tag_prop(tag: str) -> str:
    return f"i3d_cl_xml_tag_{tag}"


def _xml_title_prop(tag: str) -> str:
    return f"i3d_cl_xml_title_{tag}"


def _xml_material_prop(tag: str) -> str:
    return f"i3d_cl_xml_material_{tag}"


# useDefaultColors flag per wrapper tag
def _xml_defaultcolors_prop(tag: str) -> str:
    return f"i3d_cl_xml_useDefaultColors_{tag}"


def _xml_any_tag_selected(scene) -> bool:
    try:
        for t in _XML_TAG_ORDER:
            if bool(getattr(scene, _xml_tag_prop(t), False)):
                return True
    except Exception:
        pass
    return False


def _xml_selected_colors_as_list(scene):
    items = []
    try:
        items = list(scene.i3d_cl_xml_selected_colors)
    except Exception:
        items = []
    items.sort(key=lambda it: ((getattr(it, 'name', '') or '').lower()))
    return items



def _escape_attr(s: str) -> str:
    return (s or "").replace('"', "'")


def _xml_split_material_slots(raw: str) -> List[str]:
    parts = [p.strip() for p in (raw or "").split(",")]
    return [p for p in parts if p]


def _line_for_selected(tag: str, it) -> str:
    # GIANTS selections export as a compact materialTemplateName reference.
    if (getattr(it, "source", "") or "") == "GIANTS":
        tmpl = _escape_attr(getattr(it, "name", "") or "")
        return f'    <{tag} materialTemplateName="{tmpl}" price="0"/>'

    nm = _escape_attr(getattr(it, "name", "") or "")
    col = getattr(it, "color", (1.0, 1.0, 1.0))
    srgb = _giants_srgb_triplet_from_color(col)
    cstr = " ".join(_xml_format_trim3(v) for v in srgb)

    mt = _escape_attr(getattr(it, "materialTemplate", "") or "")
    if mt:
        return f'    <{tag} name="{nm}" color="{cstr}" materialTemplateName="{mt}" price="0" />'
    return f'    <{tag} name="{nm}" color="{cstr}" price="0" />'


def _xml_build_block(scene, tag: str, items):
    wrapper = tag + "s"
    title = getattr(scene, f"i3d_cl_xml_title_{tag}", "CHANGE ME")
    slot = getattr(scene, f"i3d_cl_xml_material_{tag}", "CHANGE ME")

    # Allow multiple slots separated by commas.
    slots = _xml_split_material_slots(slot)

    # Per-tag useDefaultColors flag
    use_default = bool(getattr(scene, _xml_defaultcolors_prop(tag), (tag == "rimColorConfiguration")))
    use_default_attr = "true" if use_default else "false"

    lines = []
    if tag == "rimColorConfiguration":
        lines.append(f'  <{wrapper} useDefaultColors="{use_default_attr}">')
        for it in items:
            lines.append(_line_for_selected(tag, it))
        lines.append(f"  </{wrapper}>")

    elif tag == "wrappingColorConfiguration":
        lines.append(f'  <{wrapper} useDefaultColors="{use_default_attr}" title="{_escape_attr(title)}">')
        for it in items:
            lines.append(_line_for_selected(tag, it))
        lines.append(f"  </{wrapper}>")

    else:
        lines.append(f'  <{wrapper} useDefaultColors="{use_default_attr}" title="{_escape_attr(title)}">')
        for it in items:
            lines.append(_line_for_selected(tag, it))
        for s in slots:
            lines.append(f'    <material materialSlotName="{_escape_attr(s)}"/>')
        lines.append(f"  </{wrapper}>")

    return "\n".join(lines)

class I3D_CL_OT_XMLSelectAllVisible(bpy.types.Operator):
    bl_idname = "i3d.cl_xml_select_all_visible"
    bl_label = "Select All Visible Colors"
    bl_description = "Selects all currently visible colors in the list (respects filters/search)."

    src: bpy.props.EnumProperty(
        items=[
            ('MY', 'My Color Library', ''),
            ('GIANTS', 'Giants Library', ''),
            ('POPULAR', 'Popular Color Library', ''),
        ],
        name="Source",
        default='MY',
    )

    def execute(self, context):
        scene = context.scene
        global _XML_SYNC_SUSPEND

        if self.src == 'MY':
            items = list(scene.i3d_cl_my_colors)
            key_fn = _xml_key_for_my
        elif self.src == 'GIANTS':
            items = list(scene.i3d_cl_giants_colors)
            key_fn = _xml_key_for_giants
        else:
            items = list(scene.i3d_cl_popular_colors)
            key_fn = _xml_key_for_popular

        _XML_SYNC_SUSPEND = True
        try:
            for it in items:
                it.xml_selected = True
        finally:
            _XML_SYNC_SUSPEND = False

        for it in items:
            try:
                key = key_fn(it)
                nm = (getattr(it, 'name', '') or '').strip()
                brand = (getattr(it, 'brand', '') or '').strip()
                col = getattr(it, 'color', (1.0, 1.0, 1.0))
                _xml_add_selected(scene, key=key, name=nm, color=col, source=self.src, brand=brand, materialTemplate=_xml_material_template_from_item(it) if self.src in {'MY','POPULAR'} else '')
            except Exception:
                pass

        self.report({'INFO'}, "Selected all visible colors")
        return {'FINISHED'}


class I3D_CL_OT_XMLClearSelectedColors(bpy.types.Operator):
    bl_idname = "i3d.cl_xml_clear_selected_colors"
    bl_label = "Clear Selected Colors"
    bl_description = "Clears all selected colors across libraries/categories."

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.alert = True
        col.label(text="WARNING: you are about to clear ALL selected Colors")
        col.label(text="from Every category in EVERY library. Are you sure?")

    def execute(self, context):
        scene = context.scene
        global _XML_SYNC_SUSPEND

        try:
            scene.i3d_cl_xml_selected_colors.clear()
        except Exception:
            pass

        _XML_SYNC_SUSPEND = True
        try:
            for it in scene.i3d_cl_my_colors:
                it.xml_selected = False
            for it in scene.i3d_cl_giants_colors:
                it.xml_selected = False
            for it in scene.i3d_cl_popular_colors:
                it.xml_selected = False
        finally:
            _XML_SYNC_SUSPEND = False

        self.report({'INFO'}, "Cleared selected colors")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=720)


class I3D_CL_OT_XMLSelectAllTags(bpy.types.Operator):
    bl_idname = "i3d.cl_xml_select_all_tags"
    bl_label = "Select All Tags"
    bl_description = "Selects all tags in the XML tag list."

    def execute(self, context):
        scene = context.scene
        show_more = bool(getattr(scene, "i3d_cl_xml_show_more_tags", False))

        shown_tags = [
            "rimColorConfiguration",
            "baseColorConfiguration",
            "designColorConfiguration",
            "designColor2Configuration",
            "designColor3Configuration",
            "designColor4Configuration",
        ]

        if show_more:
            shown_tags.extend([f"designColor{i}Configuration" for i in range(5, 17)])

        shown_tags.append("wrappingColorConfiguration")

        for t in shown_tags:
            try:
                setattr(scene, _xml_tag_prop(t), True)
            except Exception:
                pass

        self.report({'INFO'}, "Selected all shown tags")
        return {'FINISHED'}



class I3D_CL_OT_XMLShowMoreTags(bpy.types.Operator):
    bl_idname = "i3d.cl_xml_show_more_tags"
    bl_label = "Show More"
    bl_description = "Show designColor5Configuration through designColor16Configuration"

    def execute(self, context):
        context.scene.i3d_cl_xml_show_more_tags = True
        return {'FINISHED'}


class I3D_CL_OT_XMLShowLessTags(bpy.types.Operator):
    bl_idname = "i3d.cl_xml_show_less_tags"
    bl_label = "Show Less"
    bl_description = "Hide designColor5Configuration through designColor16Configuration (and uncheck them)"

    def _any_hidden_selected(self, scene):
        for i in range(5, 17):
            t = f"designColor{i}Configuration"
            try:
                if bool(getattr(scene, _xml_tag_prop(t), False)):
                    return True
            except Exception:
                pass
        return False

    def invoke(self, context, event):
        scene = context.scene
        if self._any_hidden_selected(scene):
            return context.window_manager.invoke_props_dialog(self, width=720)
        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        layout.label(text="This will hide designColor5Configuration - designColor16Configuration and uncheck any that are enabled.")

    def execute(self, context):
        scene = context.scene

        for i in range(5, 17):
            t = f"designColor{i}Configuration"
            try:
                setattr(scene, _xml_tag_prop(t), False)
            except Exception:
                pass

        scene.i3d_cl_xml_show_more_tags = False
        return {'FINISHED'}

class I3D_CL_OT_XMLClearSelectedTags(bpy.types.Operator):
    bl_idname = "i3d.cl_xml_clear_selected_tags"
    bl_label = "Clear Selected Tags"
    bl_description = "Clears all selected tags from the XML tag list."

    def execute(self, context):
        scene = context.scene
        for t in _XML_TAG_ORDER:
            try:
                setattr(scene, _xml_tag_prop(t), False)
            except Exception:
                pass

            # Reset useDefaultColors to its default per tag.
            try:
                # Default should be TRUE for all XML export tag wrappers.
                setattr(scene, _xml_defaultcolors_prop(t), True)
            except Exception:
                pass

            # Reset per-tag metadata to defaults too.
            try:
                setattr(scene, f"i3d_cl_xml_title_{t}", "CHANGE ME")
            except Exception:
                pass
            if t not in {"rimColorConfiguration", "wrappingColorConfiguration"}:
                try:
                    setattr(scene, f"i3d_cl_xml_material_{t}", "CHANGE ME")
                except Exception:
                    pass
        self.report({'INFO'}, "Cleared selected tags")
        return {'FINISHED'}




# -----------------------------------------------------------------------------
# L10N helpers for Color Library XML Export
# -----------------------------------------------------------------------------

_L10N_CONTRIBUTOR = "DTAPGAMING's Blender Exporter Reworked Tool"
_L10N_LANGUAGE_VERSION = "1.0.0.0"

_L10N_ONLINE_CACHE = {"checked": False, "ok": False, "ts": 0.0}

def i3d_cl_blender_online_access_enabled() -> bool:
    """Return Blender's user preference for allowing online access.

    Blender 4.x/5.x exposes this as: bpy.context.preferences.system.use_online_access
    """
    try:
        prefs = getattr(bpy.context, 'preferences', None)
        sys = getattr(prefs, 'system', None) if prefs else None
        val = getattr(sys, 'use_online_access', None) if sys else None
        if val is None:
            # If we can't read the preference, fail closed (treat as disabled).
            return False
        return bool(val)
    except Exception:
        # If we can't read the preference, fail closed (treat as disabled).
        return False


def i3d_cl_online_access_available(timeout_sec: float = 1.5, cache_seconds: float = 60.0) -> bool:
    """Best-effort check for outbound HTTPS access.

    NOTE:
        We keep this lightweight and cached because it can be called from UI draw().
    """
    # Respect Blender's "Allow Online Access" preference.
    if not i3d_cl_blender_online_access_enabled():
        return False
    try:
        now = time.time()
        if _L10N_ONLINE_CACHE.get("checked") and (now - float(_L10N_ONLINE_CACHE.get("ts") or 0.0)) < cache_seconds:
            return bool(_L10N_ONLINE_CACHE.get("ok"))

        urls = [
            "https://www.google.com/generate_204",
            "https://clients3.google.com/generate_204",
            "https://example.com/",
        ]

        ctx = ssl.create_default_context()
        ok = False
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Blender-I3D-Reworked/1.0"})
                with urllib.request.urlopen(req, timeout=timeout_sec, context=ctx) as resp:
                    # Any response is good enough to count as "online"
                    if resp.status in (200, 204):
                        ok = True
                        break
            except Exception:
                continue

        _L10N_ONLINE_CACHE["checked"] = True
        _L10N_ONLINE_CACHE["ok"] = ok
        _L10N_ONLINE_CACHE["ts"] = now
        return ok
    except Exception:
        return False


def _l10n_strip_outer_punct(token: str) -> Tuple[str, str, str]:
    if not token:
        return "", "", ""
    pre = ""
    suf = ""
    t = token

    while t and t[0] in "([{\"'":
        pre += t[0]
        t = t[1:]
    while t and t[-1] in ")]},.;:!?\"'":
        suf = t[-1] + suf
        t = t[:-1]

    return pre, t, suf


def _l10n_titlecase_token(token: str) -> str:
    pre, core, suf = _l10n_strip_outer_punct(token)
    if not core:
        return pre + suf

    # Keep acronyms (short ALL CAPS)
    if core.isupper() and len(core) <= 4:
        return pre + core + suf

    return pre + core[:1].upper() + core[1:].lower() + suf


def _l10n_words_from_raw(raw: str) -> List[str]:
    s = (raw or "").strip()
    if not s:
        return []

    # Normalize separators
    s = s.replace("_", " ").replace("-", " ")

    # Split camelHump: pinkChrome -> pink Chrome
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)
    s = re.sub(r"(?<=[A-Za-z])(?=[0-9])", " ", s)
    s = re.sub(r"(?<=[0-9])(?=[A-Za-z])", " ", s)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)

    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return []

    return [w for w in s.split(" ") if w]


def _l10n_display_from_raw(raw: str) -> str:
    words = _l10n_words_from_raw(raw)
    if not words:
        return ""
    return " ".join(_l10n_titlecase_token(w) for w in words).strip()


def _l10n_join_brand_and_name(brand_disp: str, name_disp: str) -> str:
    b = (brand_disp or '').strip()
    n = (name_disp or '').strip()
    if not b:
        return n
    if not n:
        return b

    # Avoid duplicated brand prefix, e.g. brand='Kick', name='Kick Green' => 'Kick Green'
    if n.casefold().startswith((b + ' ').casefold()):
        return n

    return f"{b} {n}"



def _l10n_dedupe_leading_brand(text: str, brand_disp: str) -> str:
    t = (text or '').strip()
    b = (brand_disp or '').strip()
    if not b or not t:
        return t

    b_cf = b.casefold()
    if t.casefold().startswith(b_cf + ' '):
        rest = t[len(b):].lstrip()
        if rest.casefold().startswith(b_cf + ' '):
            rest2 = rest[len(b):].lstrip()
            return f"{b} {rest2}".strip()

    return t



def _l10n_pascal_from_display(display: str) -> str:
    words = _l10n_words_from_raw(display)
    out = []
    for w in words:
        pre, core, suf = _l10n_strip_outer_punct(w)
        core = re.sub(r"[^0-9A-Za-z]+", "", core)
        if not core:
            continue
        if core.isupper() and len(core) <= 4:
            out.append(core)
        else:
            out.append(core[:1].upper() + core[1:])
    return "".join(out)



def _l10n_key_from_display(display: str) -> str:
    # Build an FS-style L10N key from a human display string.
    # Example: "Kick Green (Dark)" -> "l10n_ui_colorKickGreenDark"
    disp = (display or "").strip()
    if not disp:
        return ""
    return "l10n_ui_color" + _l10n_pascal_from_display(disp)

def _l10n_make_unique_key(base_key: str, used: Set[str]) -> str:
    if base_key not in used:
        used.add(base_key)
        return base_key
    i = 2
    while True:
        k = f"{base_key}_{i}"
        if k not in used:
            used.add(k)
            return k
        i += 1


# Basic offline EN->DE translation for common color words / qualifiers.
_DE_PHRASE_MAP = {
    "Dark Grey": "Dunkelgrau",
    "Dark Gray": "Dunkelgrau",
    "Light Grey": "Hellgrau",
    "Light Gray": "Hellgrau",
    "Medium Grey": "Mittelgrau",
    "Medium Gray": "Mittelgrau",
    "Dark Blue": "Dunkelblau",
    "Light Blue": "Hellblau",
    "Medium Blue": "Mittelblau",
}

_DE_WORD_MAP = {
    "Black": "Schwarz",
    "Gray": "Grau",
    "Grey": "Grau",
    "White": "Weiß",
    "Red": "Rot",
    "Blue": "Blau",
    "Green": "Grün",
    "Yellow": "Gelb",
    "Orange": "Orange",
    "Gold": "Gold",
    "Silver": "Silber",
    "Brown": "Braun",
    "Purple": "Lila",
    "Pink": "Rosa",
    "Chrome": "Chrom",
    "Matte": "Matt",
    "Gloss": "Glanz",
    "Glossy": "Glänzend",
    "Metal": "Metall",
    "Metallic": "Metallic",
    "Pearl": "Perl",
    "Persian": "Persisch",
    "Dark": "Dunkel",
    "Light": "Hell",
    "Medium": "Mittel",
    "Navy": "Marine",
    "Apple": "Apfel",
    "Candy": "Bonbon",
    "Coated": "Überzogen",
    "Coating": "Überzug",
    "Coat": "Überzug",
}


def _translate_en_to_de_offline(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return ""

    # Phrase replacements (case-sensitive first, then case-insensitive)
    for en, de in _DE_PHRASE_MAP.items():
        s = re.sub(rf"\b{re.escape(en)}\b", de, s)

    parts = []
    for tok in s.split(" "):
        pre, core, suf = _l10n_strip_outer_punct(tok)
        if not core:
            parts.append(tok)
            continue

        # Try phrase_map already applied; now translate word by word.
        core_tc = _l10n_titlecase_token(core)
        core_clean = re.sub(r"[^0-9A-Za-zÄÖÜäöüß]+", "", core_tc)
        repl = _DE_WORD_MAP.get(core_clean, None)
        if repl is None:
            # Keep original casing for unknown tokens
            repl = core_tc
        parts.append(pre + repl + suf)

    return " ".join(parts).strip()


def _translate_en_to_de_online_google(text: str, timeout_sec: float = 3.0) -> Optional[str]:
    """Attempt a free Google translate endpoint. May fail depending on network policies."""
    try:
        q = (text or "").strip()
        if not q:
            return ""
        url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=de&dt=t&q=" + urllib.parse.quote(q)
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": "Blender-I3D-Reworked/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_sec, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(raw)
        # data[0] is a list of [translated, original, ...]
        out = []
        for seg in (data[0] or []):
            if seg and isinstance(seg, list) and seg[0]:
                out.append(str(seg[0]))
        return "".join(out).strip() if out else None
    except Exception:
        return None


def _l10n_norm_for_compare(s: str) -> str:
    # Compare two strings while ignoring punctuation/case changes.
    return re.sub(r"[^0-9a-z]+", "", (s or "").lower())


def _l10n_translation_effectively_same(src: str, dst: str) -> bool:
    # Treat "no-op" translations (or tiny punctuation tweaks) as a miss, so we can fall back
    # to the offline word-map (which at least translates common color words like Red->Rot).
    return _l10n_norm_for_compare(src) == _l10n_norm_for_compare(dst)


def _translate_en_to_de(text: str, *, online_allowed: bool) -> str:
    # If online is allowed, try an online translator; fall back to offline mapping.
    if online_allowed:
        hit = _translate_en_to_de_online_google(text)
        if hit and not _l10n_translation_effectively_same(text, hit):
            return hit
    return _translate_en_to_de_offline(text)


def _brand_display_title(brand: str) -> str:
    b = (brand or "").strip()
    if not b:
        return ""
    # Keep hyphens as-is, title-case each part.
    parts = []
    for seg in b.split("-"):
        seg = seg.strip()
        if not seg:
            continue
        parts.append(seg[:1].upper() + seg[1:].lower() if not seg.isupper() else seg.title())
    return "-".join(parts)


_POPULAR_L10N_PRESETS: Dict[str, Dict[str, str]] = {}

# Reverse maps for Popular L10N presets (filled by ensure_popular_l10n_presets)
_POPULAR_L10N_KEY_TO_TEMPLATES: Dict[str, List[str]] = {}
_POPULAR_L10N_DISP_TO_TEMPLATES: Dict[str, List[str]] = {}

def _norm_popular_key(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("$"):
        s = s[1:]
    return s.lower()

def _norm_popular_disp(s: str) -> str:
    # Compact normalization for display strings: keep only alnum, lowercase.
    s = (s or "").strip()
    if s.startswith("$"):
        s = s[1:]
    return re.sub(r"[^0-9a-z]+", "", s.lower())

def _popular_templates_for_l10n_key(raw_key: str) -> List[str]:
    try:
        ensure_popular_l10n_presets(force=False)
    except Exception:
        return []
    nk = _norm_popular_key(raw_key)
    return list(_POPULAR_L10N_KEY_TO_TEMPLATES.get(nk, []))

def _popular_templates_for_display(raw_display: str) -> List[str]:
    try:
        ensure_popular_l10n_presets(force=False)
    except Exception:
        return []
    nd = _norm_popular_disp(raw_display)
    return list(_POPULAR_L10N_DISP_TO_TEMPLATES.get(nd, []))

def _popular_pick_template_by_color(candidates: List[str], rgb: Tuple[float, float, float], tol: float = 0.004) -> Optional[str]:
    # Choose the best matching Popular template by RGB colorScale.
    if not candidates:
        return None
    try:
        ensure_popular_cache(force=False)
    except Exception:
        return candidates[0] if candidates else None

    def _same(a, b) -> bool:
        return (abs(a[0] - b[0]) <= tol) and (abs(a[1] - b[1]) <= tol) and (abs(a[2] - b[2]) <= tol)

    # Prefer exact color matches.
    for tmpl in candidates:
        for rows in _POPULAR_CACHE_BRANDS.values():
            for r in rows:
                if (r.get("name") or "") == tmpl:
                    prgb = r.get("rgb", None)
                    if prgb and _same(prgb, rgb):
                        return tmpl

    # Fallback to the first candidate.
    return candidates[0] if candidates else None
def _popular_l10n_preset_path() -> Path:
    try:
        addon_dir = Path(__file__).resolve().parent
    except Exception:
        addon_dir = Path(".")
    return addon_dir / "data" / "popularColorLibrary_l10n_presets.xml"


def ensure_popular_l10n_presets(force: bool = False) -> None:
    global _POPULAR_L10N_PRESETS, _POPULAR_L10N_KEY_TO_TEMPLATES, _POPULAR_L10N_DISP_TO_TEMPLATES
    if _POPULAR_L10N_PRESETS and not force:
        return

    preset_path = _popular_l10n_preset_path()
    presets: Dict[str, Dict[str, str]] = {}

    if preset_path.is_file():
        try:
            tree = ET.parse(str(preset_path))
            root = tree.getroot()
            for e in root.findall("./entry"):
                tmpl = (e.attrib.get("template") or "").strip()
                if not tmpl:
                    continue

                key = (e.attrib.get("key") or "").strip()
                en = (e.attrib.get("en") or "").strip()
                de = (e.attrib.get("de") or "").strip()

                # Safety: older preset files could accidentally include duplicated leading brand
                # words like "Kick Kick Green". If so, clean it here so UI + exports are correct.
                def _dedupe_leading_word(s: str) -> str:
                    parts = (s or "").strip().split()
                    if len(parts) >= 2 and parts[0].casefold() == parts[1].casefold():
                        return " ".join(parts[1:])
                    return (s or "").strip()

                en = _dedupe_leading_word(en)
                de = _dedupe_leading_word(de)

                # If preset lacks a key, derive a stable one from the EN display text.
                if en and not key:
                    key = _l10n_key_from_display(en)

                presets[tmpl] = {
                    "key": key,
                    "en": en,
                    "de": de,
                }
        except Exception:
            presets = {}


    # Build reverse maps for stable lookups (key/display -> template)
    key_to: Dict[str, List[str]] = {}
    disp_to: Dict[str, List[str]] = {}
    try:
        for tmpl, pdata in presets.items():
            k = (pdata.get("key") or "").strip()
            if k:
                key_to.setdefault(_norm_popular_key(k), []).append(tmpl)

            en = (pdata.get("en") or "").strip()
            if en:
                disp_to.setdefault(_norm_popular_disp(en), []).append(tmpl)

            de = (pdata.get("de") or "").strip()
            if de:
                disp_to.setdefault(_norm_popular_disp(de), []).append(tmpl)
    except Exception:
        key_to = {}
        disp_to = {}

    _POPULAR_L10N_KEY_TO_TEMPLATES = key_to
    _POPULAR_L10N_DISP_TO_TEMPLATES = disp_to
    _POPULAR_L10N_PRESETS = presets


def _popular_preset_for_template(template_name: str) -> Optional[Dict[str, str]]:
    ensure_popular_l10n_presets(force=False)
    return _POPULAR_L10N_PRESETS.get((template_name or "").strip())


def _build_l10n_xml(entries: Dict[str, str]) -> str:
    lines = []
    lines.append("<l10n>")
    lines.append(f"    <translationContributors>{_escape_attr(_L10N_CONTRIBUTOR)}</translationContributors>")
    lines.append(f"    <languageVersion>{_escape_attr(_L10N_LANGUAGE_VERSION)}</languageVersion>")
    lines.append("    <texts>")
    for k in sorted(entries.keys()):
        v = entries[k]
        lines.append(f"        <text name=\"{_escape_attr(k)}\" text=\"{_escape_attr(v)}\"/>")
    lines.append("    </texts>")
    lines.append("</l10n>")
    return "\n".join(lines)

def _indent_block(text: str, spaces: int) -> str:
    pad = " " * max(0, int(spaces))
    return "\n".join((pad + ln) if ln.strip() else ln for ln in (text or "").splitlines())


def _build_l10n_bundle_xml(entries_en: Dict[str, str], entries_de: Optional[Dict[str, str]] = None) -> str:
    lines: List[str] = []
    lines.append("<l10nBundle>")
    lines.append("  <!-- English -->")
    lines.append(_indent_block(_build_l10n_xml(entries_en), 2))
    if entries_de:
        lines.append("")
        lines.append("  <!-- German -->")
        lines.append(_indent_block(_build_l10n_xml(entries_de), 2))
    lines.append("</l10nBundle>")
    return "\n".join(lines)


class I3D_CL_OT_XMLExportSelected(bpy.types.Operator, ExportHelper):
    bl_idname = "i3d.cl_xml_export_selected"
    bl_label = "Save as XML"
    bl_description = "Saves the selected colors/tags as an XML file (for sharing or backup)."

    filename_ext = ".xml"
    filter_glob: bpy.props.StringProperty(default="*.xml", options={'HIDDEN'})

    def invoke(self, context, event):
        # Suggest a default filename/location for the file browser.
        if not getattr(self, "filepath", ""):
            default_dir = bpy.path.abspath("//")
            if not default_dir or default_dir == "//":
                default_dir = os.path.expanduser("~")
            self.filepath = os.path.join(default_dir, "colorConfigurations.xml")
        return ExportHelper.invoke(self, context, event)
    def execute(self, context):
            scene = context.scene

            colors = _xml_selected_colors_as_list(scene)
            if not colors:
                self.report({'WARNING'}, "No colors selected")
                return {'CANCELLED'}

            tags = [t for t in _XML_TAG_ORDER if bool(getattr(scene, _xml_tag_prop(t), False))]
            if not tags:
                self.report({'WARNING'}, "No tags selected")
                return {'CANCELLED'}

            # Export settings (Export tab > Miscellaneous)
            settings = getattr(scene, "I3D_UIexportSettings", None)
            gen_l10n = bool(getattr(settings, "i3D_exportColorLibrariesGenerateL10N", False)) if settings else False
            gen_de = bool(getattr(settings, "i3D_exportColorLibrariesGermanL10N", False)) if settings else False
            gen_de = bool(gen_l10n and gen_de)

            online_ok = bool(i3d_cl_online_access_available()) if gen_de else False
            if gen_de and not online_ok:
                # UI should already force this off, but keep export robust.
                gen_de = False

            used_keys: Set[str] = set()
            l10n_en: Dict[str, str] = {}
            l10n_de: Dict[str, str] = {}

            def _register_l10n(base_key: str, text_en: str, text_de: Optional[str] = None) -> str:
                # IMPORTANT: Do NOT generate suffixed keys for repeated use of the same selected color.
                # Users select a color once, then reuse it across multiple exported tags; the L10N key
                # must remain stable and only appear once in the dictionaries.

                # Reuse an existing key when it already maps to the exact same EN text.
                if base_key in l10n_en and l10n_en.get(base_key, "") == text_en:
                    used_keys.add(base_key)
                    if gen_de and base_key not in l10n_de:
                        l10n_de[base_key] = (text_de or text_en)
                    return base_key

                # Use the base key if it's free; only suffix when there is a real collision
                # (same key, different EN text).
                if base_key in used_keys:
                    key = _l10n_make_unique_key(base_key, used_keys)
                else:
                    used_keys.add(base_key)
                    key = base_key

                l10n_en[key] = text_en
                if gen_de:
                    l10n_de[key] = (text_de or text_en)
                return key


            def _register_l10n_fixed(key: str, text_en: str, text_de: Optional[str] = None) -> str:
                # Register an existing (fixed) key without ever suffixing it.
                k = (key or "").strip()
                if not k:
                    base_key = "l10n_ui_color" + _l10n_pascal_from_display(text_en or "")
                    return _register_l10n(base_key, text_en, text_de)
            
                # If the key already exists, keep the existing EN text to avoid breaking references.
                if k in l10n_en:
                    used_keys.add(k)
                    if gen_de and k not in l10n_de:
                        l10n_de[k] = (text_de or l10n_en.get(k, "") or text_en)
                    return k
            
                used_keys.add(k)
                l10n_en[k] = (text_en or "")
                if gen_de:
                    l10n_de[k] = (text_de or text_en or "")
                return k

            def _maybe_l10n_title(title_raw: str) -> str:
                title_disp = (title_raw or "").strip()
                if not gen_l10n:
                    return _escape_attr(title_disp)
                if not title_disp or title_disp == "CHANGE ME":
                    return _escape_attr(title_disp)
                title_en = _l10n_display_from_raw(title_disp)
                base_key = "l10n_ui_colorConfigTitle" + _l10n_pascal_from_display(title_en)
                de_txt = _translate_en_to_de(title_en, online_allowed=online_ok) if gen_de else None
                key = _register_l10n(base_key, title_en, de_txt)
                return _escape_attr(f"${key}")

            def _line_for_selected_l10n(tag: str, it) -> str:
                src = (getattr(it, "source", "") or "").strip()

                # GIANTS library stays as-is (already covered by base-game dictionaries)
                if src == "GIANTS" or not gen_l10n:
                    return _line_for_selected(tag, it)

                # wrappingColorConfiguration cannot use GIANTS templates in-game; preserve existing skip behavior.
                if tag == "wrappingColorConfiguration" and src == "GIANTS":
                    return ""

                name_attr = (getattr(it, "name", "") or "").strip()
                brand_attr = (getattr(it, "brand", "") or "").strip()

                # English display text
                en_text = ""
                de_text = None
                if src == "POPULAR":
                    preset = _popular_preset_for_template(name_attr)
                    if not preset:
                        # name_attr might be an L10N key or display string (e.g. after a bad import) - try to resolve to a template.
                        cand = _popular_templates_for_l10n_key(name_attr) or _popular_templates_for_display(name_attr)
                        tmpl = _popular_pick_template_by_color(cand, _giants_srgb_triplet_from_color(getattr(it, "color", (1.0, 1.0, 1.0))))
                        if tmpl:
                            preset = _popular_preset_for_template(tmpl)
                    brand_for_display = brand_attr or (preset.get("brand") if preset else "") or ""
                    bdisp = _brand_display_title(brand_for_display)
                    if preset and preset.get("en"):
                        en_text = _l10n_dedupe_leading_brand((preset.get("en") or ""), bdisp)
                        if gen_de:
                            de_raw = preset.get("de") or None
                            de_text = _l10n_dedupe_leading_brand(de_raw, bdisp) if (de_raw and bdisp) else de_raw
                    else:
                        ndsp = _l10n_display_from_raw(name_attr)
                        en_text = _l10n_join_brand_and_name(bdisp, ndsp)

                    if not en_text:
                        en_text = _l10n_display_from_raw(name_attr)

                    if gen_de and not de_text:
                        de_text = _translate_en_to_de(en_text, online_allowed=online_ok)

                    # If this Popular entry has a fixed preset key, use it verbatim (do not rebuild keys from EN text).
                    if preset and preset.get("key"):
                        fixed_key = (preset.get("key") or "").strip()
                        if fixed_key:
                            key = _register_l10n_fixed(fixed_key, en_text, de_text)
                            export_name = f"${key}"

                            # Build tag line (same structure as _line_for_selected, but with L10N name)
                            col = getattr(it, "color", (1.0, 1.0, 1.0))
                            srgb = _giants_srgb_triplet_from_color(col)
                            cstr = " ".join(_xml_format_trim3(v) for v in srgb)

                            mt = _escape_attr(getattr(it, "materialTemplate", "") or "")
                            if mt:
                                return f'    <{tag} name="{_escape_attr(export_name)}" color="{cstr}" materialTemplateName="{mt}" price="0" />'
                            return f'    <{tag} name="{_escape_attr(export_name)}" color="{cstr}" price="0" />'

                else:
                    # MY library: user-supplied name (allow underscores / camelCase)
                    raw_nm = name_attr
                    de_text = ""

                    # If the user is already using an L10N key (e.g. "$l10n_ui_colorKICKBlack"),
                    # preserve the key and derive display text from the key suffix.
                    nm_no_dollar = raw_nm[1:] if raw_nm.startswith("$") else raw_nm
                    if nm_no_dollar.lower().startswith("l10n_"):
                        fixed_key = nm_no_dollar.strip()

                        disp_src = fixed_key
                        if disp_src.startswith("l10n_ui_colorConfigTitle"):
                            disp_src = disp_src[len("l10n_ui_colorConfigTitle"):]
                        elif disp_src.startswith("l10n_ui_color"):
                            disp_src = disp_src[len("l10n_ui_color"):]

                        en_text = _l10n_display_from_raw(disp_src) or disp_src

                        if gen_de:
                            de_text = _translate_en_to_de(en_text, online_allowed=online_ok)

                        key = _register_l10n_fixed(fixed_key, en_text, de_text)
                        export_name = f"${key}"

                        # Build tag line (same structure as _line_for_selected, but with L10N name)
                        col = getattr(it, "color", (1.0, 1.0, 1.0))
                        srgb = _giants_srgb_triplet_from_color(col)
                        cstr = " ".join(_xml_format_trim3(v) for v in srgb)

                        mt = _escape_attr(getattr(it, "materialTemplate", "") or "")
                        if mt:
                            return f'    <{tag} name="{_escape_attr(export_name)}" color="{cstr}" materialTemplateName="{mt}" price="0" />'
                        return f'    <{tag} name="{_escape_attr(export_name)}" color="{cstr}" price="0" />'

                    en_text = _l10n_display_from_raw(name_attr) or name_attr
                    if gen_de:
                        de_text = _translate_en_to_de(en_text, online_allowed=online_ok)


                # Safety net: if a MY color matches a Popular preset (key/display + color), force the preset key + translations.
                # This prevents "YouTube"/"TikTok" camel-case from generating mismatched keys like l10n_ui_colorYouTubeRed.
                if src == "MY":
                    cand = _popular_templates_for_l10n_key(name_attr)
                    if not cand:
                        cand = _popular_templates_for_display(en_text) or _popular_templates_for_display(name_attr)

                    tmpl = _popular_pick_template_by_color(cand, _giants_srgb_triplet_from_color(getattr(it, "color", (1.0, 1.0, 1.0))))
                    if tmpl:
                        pp = _popular_preset_for_template(tmpl)
                        fixed_key2 = (pp.get("key") or "").strip() if pp else ""
                        if fixed_key2:
                            pen = (pp.get("en") or en_text) if pp else en_text
                            pde = (pp.get("de") or de_text) if pp else de_text
                            key = _register_l10n_fixed(fixed_key2, pen, pde)
                            export_name = f"${key}"

                            col = getattr(it, "color", (1.0, 1.0, 1.0))
                            srgb = _giants_srgb_triplet_from_color(col)
                            cstr = " ".join(_xml_format_trim3(v) for v in srgb)

                            mt = _escape_attr(getattr(it, "materialTemplate", "") or "")
                            if mt:
                                return f'    <{tag} name="{_escape_attr(export_name)}" color="{cstr}" materialTemplateName="{mt}" price="0" />'
                            return f'    <{tag} name="{_escape_attr(export_name)}" color="{cstr}" price="0" />'

                base_key = "l10n_ui_color" + _l10n_pascal_from_display(en_text)
                key = _register_l10n(base_key, en_text, de_text)
                export_name = f"${key}"

                # Build tag line (same structure as _line_for_selected, but with L10N name)
                col = getattr(it, "color", (1.0, 1.0, 1.0))
                srgb = _giants_srgb_triplet_from_color(col)
                cstr = " ".join(_xml_format_trim3(v) for v in srgb)

                mt = _escape_attr(getattr(it, "materialTemplate", "") or "")
                if mt:
                    return f'    <{tag} name="{_escape_attr(export_name)}" color="{cstr}" materialTemplateName="{mt}" price="0" />'
                return f'    <{tag} name="{_escape_attr(export_name)}" color="{cstr}" price="0" />'

            blocks: List[str] = []
            for t in tags:
                wrapper = t + "s"
                title_raw = getattr(scene, f"i3d_cl_xml_title_{t}", "CHANGE ME")
                slot_raw = getattr(scene, f"i3d_cl_xml_material_{t}", "CHANGE ME")
                slots = _xml_split_material_slots(slot_raw)

                # Per-tag useDefaultColors flag
                use_default = bool(getattr(scene, _xml_defaultcolors_prop(t), (t == "rimColorConfiguration")))
                use_default_attr = "true" if use_default else "false"

                lines: List[str] = []
                if t == "rimColorConfiguration":
                    lines.append(f'  <{wrapper} useDefaultColors="{use_default_attr}">')
                    for it in colors:
                        ln = _line_for_selected_l10n(t, it)
                        if ln:
                            lines.append(ln)
                    lines.append(f"  </{wrapper}>")

                elif t == "wrappingColorConfiguration":
                    title_attr = _maybe_l10n_title(title_raw)
                    lines.append(f'  <{wrapper} useDefaultColors="{use_default_attr}" title="{title_attr}">')
                    for it in colors:
                        ln = _line_for_selected_l10n(t, it)
                        if ln:
                            lines.append(ln)
                    lines.append(f"  </{wrapper}>")

                else:
                    title_attr = _maybe_l10n_title(title_raw)
                    lines.append(f'  <{wrapper} useDefaultColors="{use_default_attr}" title="{title_attr}">')
                    for it in colors:
                        ln = _line_for_selected_l10n(t, it)
                        if ln:
                            lines.append(ln)
                    for s in slots:
                        lines.append(f'    <material materialSlotName="{_escape_attr(s)}"/>')
                    lines.append(f"  </{wrapper}>")

                blocks.append("\n".join(lines))

            body = "\n\n".join([b for b in blocks if b and b.strip()]).rstrip()

            # Always export a well-formed XML document with a single root element.
            text = '<?xml version="1.0" encoding="utf-8"?>\n'
            text += "<colorConfigurations>\n"
            if body:
                text += body + "\n"
            text += "</colorConfigurations>\n"

            try:
                with open(self.filepath, 'w', encoding='utf-8') as f:
                    f.write(text)
            except Exception as e:
                self.report({'ERROR'}, f"Failed to write: {e}")
                return {'CANCELLED'}

            # Write a single appended L10N file next to the exported XML (if enabled)
            # - <exportname>_l10n.xml  (EN + optional DE in the same file under <l10nBundle>)
            if gen_l10n and l10n_en:
                base = os.path.splitext(self.filepath)[0]
                l10n_path = base + "_l10n.xml"
                try:
                    with open(l10n_path, "w", encoding="utf-8") as f:
                        f.write('<?xml version="1.0" encoding="utf-8"?>\n')
                        f.write(_build_l10n_bundle_xml(l10n_en, l10n_de if (gen_de and l10n_de) else None) + "\n")
                except Exception as e:
                    self.report({'WARNING'}, f"L10N write failed: {e}")


            self.report({'INFO'}, f"Saved XML: {self.filepath}")
            return {'FINISHED'}
class I3D_CL_OT_XMLImportSelected(bpy.types.Operator):
    bl_idname = "i3d.cl_xml_import_selected"
    bl_label = "Import XML"
    bl_description = "Imports colors/tags from an XML file into the libraries (duplicates are deduped when possible)."

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        scene = context.scene
        xml_path = self.filepath

        if not xml_path or not os.path.isfile(xml_path):
            self.report({'ERROR'}, "XML file not found")
            return {'CANCELLED'}

        # Reset tags + per-tag metadata to defaults.
        for t in _XML_TAG_ORDER:
            try:
                setattr(scene, _xml_tag_prop(t), False)
            except Exception:
                pass
            try:
                setattr(scene, f"i3d_cl_xml_title_{t}", "CHANGE ME")
            except Exception:
                pass
            if t not in {"rimColorConfiguration", "wrappingColorConfiguration"}:
                try:
                    setattr(scene, f"i3d_cl_xml_material_{t}", "CHANGE ME")
                except Exception:
                    pass

        # Clear selected colors list + any My selections.
        try:
            bpy.ops.i3d.cl_xml_clear_selected_colors()
        except Exception:
            try:
                scene.i3d_cl_xml_selected_colors.clear()
            except Exception:
                pass

        global _XML_SYNC_SUSPEND
        _XML_SYNC_SUSPEND = True
        try:
            for it in scene.i3d_cl_my_colors:
                it.xml_selected = False
        finally:
            _XML_SYNC_SUSPEND = False

        # Helpers (import-side)
        def _parse_triplet(s: str) -> Optional[Tuple[float, float, float]]:
            try:
                parts = [p.strip() for p in (s or "").replace(",", " ").split() if p.strip()]
                if len(parts) < 3:
                    return None
                return (float(parts[0]), float(parts[1]), float(parts[2]))
            except Exception:
                return None

        def _rgb255(trip: Tuple[float, float, float]) -> Tuple[float, float, float]:
            # Normalize to 0..1 range if input looks like 0..255.
            mx = max(trip[0], trip[1], trip[2])
            if mx > 1.5:
                return (trip[0] / 255.0, trip[1] / 255.0, trip[2] / 255.0)
            return trip

        def _same_color(a: Tuple[float, float, float], b: Tuple[float, float, float], tol: float = 0.004) -> bool:
            return (abs(a[0] - b[0]) <= tol) and (abs(a[1] - b[1]) <= tol) and (abs(a[2] - b[2]) <= tol)

        # Parse XML
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
        except Exception as e:
            # Legacy fallback: older exports (or hand-edited files) may contain multiple
            # top-level wrapper elements without a single root, which ElementTree rejects
            # with "junk after document element".
            try:
                with open(xml_path, "r", encoding="utf-8", errors="ignore") as f:
                    raw = f.read()
                # Strip UTF-8 BOM, if any.
                raw = raw.lstrip("\ufeff")
                # Strip XML declaration if present (ElementTree disallows nested declarations).
                raw2 = re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", raw, flags=re.IGNORECASE)
                root = ET.fromstring(f"<colorConfigurations>\n{raw2}\n</colorConfigurations>")
            except Exception:
                self.report({'ERROR'}, f"Failed to parse XML: {e}")
                return {'CANCELLED'}


        want = []
        seen = set()

        # Collect wrapper tags, metadata, and color/template selections
        for wrapper in list(root):
            wtag = wrapper.tag or ""
            if not wtag.endswith("s"):
                continue

            tag = wtag[:-1]
            if tag not in _XML_TAG_ORDER:
                continue

            # Tag enabled
            try:
                setattr(scene, _xml_tag_prop(tag), True)
            except Exception:
                pass

            # Title
            if tag != "rimColorConfiguration":
                tval_raw = (wrapper.attrib.get("title") or "CHANGE ME").strip() or "CHANGE ME"
                tval = tval_raw
                try:
                    tval_no_dollar = tval_raw[1:] if tval_raw.startswith("$") else tval_raw
                    l10n_prefix = "l10n_ui_colorConfigTitle"
                    if tval_no_dollar.startswith(l10n_prefix):
                        tval = _l10n_display_from_raw(tval_no_dollar[len(l10n_prefix):])
                except Exception:
                    tval = tval_raw

                try:
                    setattr(scene, f"i3d_cl_xml_title_{tag}", tval)
                except Exception:
                    pass
            # Slot(s)
            if tag not in {"rimColorConfiguration", "wrappingColorConfiguration"}:
                slots = []
                for mel in wrapper.findall("material"):
                    sval = (mel.attrib.get("materialSlotName") or "").strip()
                    if sval and sval not in slots:
                        slots.append(sval)
                try:
                    setattr(scene, f"i3d_cl_xml_material_{tag}", ", ".join(slots) if slots else "CHANGE ME")
                except Exception:
                    pass

            # Color entries / template refs
            for child in list(wrapper):
                if child.tag != tag:
                    continue

                mt_name = (child.attrib.get("materialTemplateName") or "").strip()
                color_attr = (child.attrib.get("color") or "").strip()
                name_attr = (child.attrib.get("name") or "").strip()

                # New GIANTS-style export: no color, only materialTemplateName
                if not color_attr:
                    if mt_name:
                        k = ("REF", mt_name.lower())
                        if k not in seen:
                            seen.add(k)
                            want.append({
                                "kind": "REF",
                                "template": mt_name,
                            })
                    continue

                trip = _parse_triplet(color_attr)
                if not trip:
                    continue
                trip = _rgb255(trip)

                explicit_mt = bool(mt_name)
                k = ("COLOR", name_attr.lower(), round(trip[0], 4), round(trip[1], 4), round(trip[2], 4), mt_name)
                if k in seen:
                    continue
                seen.add(k)
                want.append({
                    "kind": "COLOR",
                    "name": name_attr,
                    "trip": trip,
                    "materialTemplate": mt_name,
                    "explicit_mt": explicit_mt,
                })

        if not want:
            self.report({'WARNING'}, "No supported color configurations found in XML")
            return {'FINISHED'}

        # Ensure caches
        ensure_popular_cache(force=False)
        ensure_giants_cache(force=False)

        # Flatten popular rows
        popular_rows: List[Dict[str, Any]] = []
        try:
            for brand, rows in _POPULAR_CACHE_BRANDS.items():
                for r in rows:
                    popular_rows.append({
                        "brand": brand,
                        "name": r.get("name", ""),
                        "rgb": r.get("rgb", (1.0, 1.0, 1.0)),
                        "colorScale": r.get("colorScale", ""),
                    })
        except Exception:
            popular_rows = []


        # Build a quick lookup for Popular rows by normalized name (strip leading '$', lower-case).
        def _norm_name(s: str) -> str:
            s = (s or '').strip()
            if s.startswith('$'):
                s = s[1:]
            return s.lower()

        popular_by_norm: Dict[str, Dict[str, Any]] = {}
        try:
            for r in popular_rows:
                key = _norm_name(r.get('name') or '')
                if key and key not in popular_by_norm:
                    popular_by_norm[key] = r
        except Exception:
            popular_by_norm = {}

        # Build mapping from Popular L10N keys -> template name(s)
        popular_l10n_to_templates: Dict[str, List[str]] = {}
        try:
            ensure_popular_l10n_presets(force=False)
            for tmpl, pdata in _POPULAR_L10N_PRESETS.items():
                k = (pdata.get("key") or "").strip()
                if not k:
                    continue
                nk = _norm_name(k)
                popular_l10n_to_templates.setdefault(nk, []).append(tmpl)
        except Exception:
            popular_l10n_to_templates = {}

        def _fix_l10n_key(raw: str) -> str:
            s = (raw or "").strip()
            if s.startswith("$"):
                s = s[1:].strip()
            low = s.lower()
            pref = "l10n_ui_color"
            dup = "l10nuicolor"
            if low.startswith(pref + dup):
                # Fix earlier export bug: l10n_ui_colorL10NUiColorX -> l10n_ui_colorX
                s = "l10n_ui_color" + s[len(pref) + len(dup):]
            return s

        def _popular_template_for_name(name: str, trip: Tuple[float, float, float]) -> str:
            nm = _fix_l10n_key(name)
            if not nm:
                return name

            # 1) If it's already a Popular template name, return canonical template name.
            row = popular_by_norm.get(_norm_name(nm))
            if row:
                return row.get("name") or nm

            # 2) L10N key -> template(s)
            if nm.lower().startswith("l10n_"):
                cands = popular_l10n_to_templates.get(_norm_name(nm), [])
                if cands:
                    # Prefer color-matched candidate.
                    for cand in cands:
                        pr = _find_popular(cand, trip)
                        if pr:
                            return pr.get("name") or cand
                    return cands[0]

            # 3) Display string (EN/DE) -> template(s)
            cands2 = _popular_templates_for_display(nm)
            if cands2:
                for cand in cands2:
                    pr = _find_popular(cand, trip)
                    if pr:
                        return pr.get("name") or cand
                return cands2[0]

            return nm
        giants_rows: List[Tuple[str, Dict[str, Any]]] = []
        giants_by_name: Dict[str, Tuple[str, Dict[str, Any]]] = {}
        try:
            for brand, rows in _GIANTS_CACHE_BRANDS.items():
                for r in rows:
                    giants_rows.append((brand, r))
                    nm = (r.get("name") or "").strip()
                    if nm:
                        giants_by_name.setdefault(nm.lower(), (brand, r))
        except Exception:
            giants_rows = []
            giants_by_name = {}

        def _find_popular(name: str, trip: Tuple[float, float, float]) -> Optional[Dict[str, Any]]:
            nkey = _norm_name(name)
            for r in popular_rows:
                if _norm_name(r.get('name') or '') != nkey:
                    continue
                rgb = r.get('rgb') or (1.0, 1.0, 1.0)
                if _same_color(rgb, trip):
                    return r
            return None

        def _find_giants_by_name_color(name: str, trip: Tuple[float, float, float]) -> Optional[Tuple[str, Dict[str, Any]]]:
            nl = (name or "").lower()
            for brand, r in giants_rows:
                if (r.get("name") or "").lower() != nl:
                    continue
                rgb = r.get("rgb") or (1.0, 1.0, 1.0)
                if _same_color(rgb, trip):
                    return (brand, r)
            return None

        imported = 0
        my_items_to_select = []

        # Apply selections
        for it in want:
            if it.get("kind") == "REF":
                tmpl = (it.get("template") or "").strip()
                if not tmpl:
                    continue
                hit = giants_by_name.get(tmpl.lower())
                if not hit:
                    continue
                brand, r = hit
                nm = (r.get("name") or "").strip() or tmpl
                rgb = r.get("rgb") or (1.0, 1.0, 1.0)
                cs = (r.get("colorScale") or "").strip() or _giants_srgb_text(rgb)
                key = f"GIANTS|{brand}|{nm}|{cs}"
                _xml_add_selected(scene, key=key, name=nm, color=rgb, source="GIANTS", brand=brand, materialTemplate="")
                imported += 1
                continue

            if it.get("kind") != "COLOR":
                continue

            nm = (it.get("name") or "").strip()
            trip = it.get("trip") or (1.0, 1.0, 1.0)
            mt = (it.get("materialTemplate") or "").strip()
            explicit_mt = bool(it.get("explicit_mt"))

            if explicit_mt:
                # If materialTemplateName was explicitly present, DO NOT match GIANTS palette.
                nm_pop = _popular_template_for_name(nm, trip) or nm
                pr = _find_popular(nm_pop, trip)
                if pr:
                    brand = pr.get("brand", "")
                    cs = (pr.get("colorScale") or "").strip() or _giants_srgb_text(pr.get("rgb") or trip)
                    key = f"POPULAR|{brand}|{nm_pop}|{cs}"
                    _xml_add_selected(scene, key=key, name=nm_pop, color=trip, source="POPULAR", brand=brand, materialTemplate=mt)
                    imported += 1
                    continue

                # Fall back to My
                raw_nm = nm
                disp_nm = nm
                try:
                    nm_no_dollar = raw_nm[1:] if raw_nm.startswith("$") else raw_nm
                    nm_no_dollar = _fix_l10n_key(nm_no_dollar)
                    if nm_no_dollar.startswith("l10n_ui_color"):
                        disp_nm = _l10n_display_from_raw(nm_no_dollar[len("l10n_ui_color"):])
                except Exception:
                    disp_nm = nm



                # If XML name is an L10N key that already exists in Popular library, do NOT import into My.
                # Instead, select the Popular entry directly (even if RGB differs slightly).
                try:
                    nm_no_dollar = raw_nm[1:] if raw_nm.startswith("$") else raw_nm
                    nm_no_dollar = _fix_l10n_key(nm_no_dollar)
                    tmpl = _popular_template_for_name(nm_no_dollar, trip)
                    pr_l10n = popular_by_norm.get(_norm_name(tmpl)) if tmpl else None
                except Exception:
                    pr_l10n = None
                    tmpl = ""

                if pr_l10n:
                    brand = pr_l10n.get("brand", "")
                    cs = (pr_l10n.get("colorScale") or "").strip() or _giants_srgb_text(pr_l10n.get("rgb") or trip)
                    key = f"POPULAR|{brand}|{tmpl}|{cs}"
                    _xml_add_selected(scene, key=key, name=tmpl, color=trip, source="POPULAR", brand=brand, materialTemplate=mt)
                    imported += 1
                    continue

                my_item = None

                # Match existing My Library entries robustly:
                # - exact string match (disp/raw)
                # - normalized display match (underscores/camelCase/number chunking)
                norm_disp = ""
                norm_raw = ""
                try:
                    norm_disp = (_l10n_display_from_raw(disp_nm) or disp_nm or "").casefold().strip()
                    norm_raw = (_l10n_display_from_raw(raw_nm) or raw_nm or "").casefold().strip()
                except Exception:
                    norm_disp = (disp_nm or "").casefold().strip()
                    norm_raw = (raw_nm or "").casefold().strip()

                for mi in scene.i3d_cl_my_colors:
                    if not _same_color(tuple(mi.color), trip):
                        continue

                    nm_existing = (getattr(mi, "name", "") or "").strip()
                    if nm_existing == disp_nm or nm_existing == raw_nm:
                        my_item = mi
                        break

                    try:
                        norm_existing = (_l10n_display_from_raw(nm_existing) or nm_existing or "").casefold().strip()
                    except Exception:
                        norm_existing = (nm_existing or "").casefold().strip()

                    if norm_existing and (norm_existing == norm_disp or norm_existing == norm_raw):
                        my_item = mi
                        break

                if my_item is None:
                    my_item = scene.i3d_cl_my_colors.add()
                    my_item.name = _ensure_unique_my_library_name(scene, disp_nm)
                    my_item.color = trip

                try:
                    my_item.xml_material_template = _mt_register_value(mt)
                except Exception:
                    my_item.xml_material_template = "NONE"

                my_items_to_select.append(my_item)
                key = _xml_key_for_my(my_item)
                _xml_add_selected(scene, key=key, name=nm, color=trip, source="MY", brand="", materialTemplate=mt)
                imported += 1
                continue

            # Legacy behavior: match POPULAR -> GIANTS -> MY
            nm_pop = _popular_template_for_name(nm, trip) or nm
            pr = _find_popular(nm_pop, trip)
            if pr:
                brand = pr.get("brand", "")
                cs = (pr.get("colorScale") or "").strip() or _giants_srgb_text(pr.get("rgb") or trip)
                key = f"POPULAR|{brand}|{nm_pop}|{cs}"
                _xml_add_selected(scene, key=key, name=nm_pop, color=trip, source="POPULAR", brand=brand, materialTemplate="")
                imported += 1
                continue

            gr = _find_giants_by_name_color(nm, trip)
            if gr:
                brand, r = gr
                cs = (r.get("colorScale") or "").strip() or _giants_srgb_text(r.get("rgb") or trip)
                key = f"GIANTS|{brand}|{nm}|{cs}"
                _xml_add_selected(scene, key=key, name=nm, color=trip, source="GIANTS", brand=brand, materialTemplate="")
                imported += 1
                continue

            # Fall back to My (do not auto-assign a material type for legacy XML)
            my_item = None
            for mi in scene.i3d_cl_my_colors:
                if mi.name == nm and _same_color(tuple(mi.color), trip):
                    my_item = mi
                    break
            if my_item is None:
                my_item = scene.i3d_cl_my_colors.add()
                my_item.name = nm
                my_item.color = trip

            my_items_to_select.append(my_item)
            key = _xml_key_for_my(my_item)
            _xml_add_selected(scene, key=key, name=nm, color=trip, source="MY", brand="", materialTemplate="")
            imported += 1

        # Apply My selections (and keep them in sync without firing updates)
        _XML_SYNC_SUSPEND = True
        try:
            for mi in my_items_to_select:
                mi.xml_selected = True
        finally:
            _XML_SYNC_SUSPEND = False

        rebuild_giants_visible(scene, force=True)
        rebuild_popular_visible(scene, force=True)
        schedule_save()

        self.report({'INFO'}, f"Imported {imported} selections from XML")
        return {'FINISHED'}


    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

# -----------------------------------------------------------------------------
# Drawing
# -----------------------------------------------------------------------------


def _draw_xml_mode_controls(box, scene: bpy.types.Scene, src: str):
    """Shared UI for XML mode (MY/GIANTS/POPULAR)."""

    box.separator()

    row = box.row(align=True)
    row.scale_y = 1.1
    op = row.operator("i3d.cl_xml_select_all_visible", text="Select all visible colors in list", icon='CHECKBOX_HLT')
    op.src = src

    # Keep this button close to Select-all, and only show if something is selected.
    if _xml_any_color_selected(scene):
        row.operator("i3d.cl_xml_clear_selected_colors", text="Clear selected colors", icon='TRASH')

    # Allow quick temporary preview to the active material even in XML mode (small button)
    _xml_preview_op = {
        'MY': 'i3d.cl_my_apply_to_material',
        'POPULAR': 'i3d.cl_popular_apply_to_material',
        'GIANTS': 'i3d.cl_giants_apply_to_material',
    }.get(src)
    if _xml_preview_op:
        rprev = box.row(align=True)
        rprev.scale_y = 0.85
        rprev.alert = True
        rprev.operator(_xml_preview_op, text="Apply Temporary preview to Material - No Giants Export")


    info = box.row()
    info.label(text=f"Selected Colors: {len(scene.i3d_cl_xml_selected_colors)}")


    tags = box.box()
    tags.label(text="XML Export Tags")

    # ---------------------------------------------------------------------
    # Table-style header + column splitter (keeps each row clean)
    # ---------------------------------------------------------------------
    def _xml_tags_table_columns(row_layout):
        """Return aligned columns for the XML Export Tags table.

        Column order:
            Export Tag | Default Colors | Title | Slot
        """

        # Keep header + rows aligned by using the same split ratios.
        # Make Export Tag column smaller to avoid dead space, and give
        # Default Colors column enough width so the header is not truncated.
        split = row_layout.split(factor=0.32, align=True)
        col_tag = split.column(align=True)
        col_rest = split.column(align=True)

        # Checkbox column for useDefaultColors.
        split2 = col_rest.split(factor=0.18, align=True)
        col_def = split2.column(align=True)
        col_rest2 = split2.column(align=True)

        # Title + Slot columns.
        split3 = col_rest2.split(factor=0.60, align=True)
        col_title = split3.column(align=True)
        col_slot = split3.column(align=True)

        return col_tag, col_def, col_title, col_slot

    hdr = tags.row(align=True)
    h_tag, h_def, h_title, h_slot = _xml_tags_table_columns(hdr)

    h_tag.label(text="Export Tag")
    h_def.label(text="Default")
    h_def.label(text="Colors")
    h_title.label(text="Title")
    h_slot.label(text="Slot")

    tags.separator()

    show_more = bool(getattr(scene, "i3d_cl_xml_show_more_tags", False))

    def _draw_tag_row(container, tag_name: str, *, standout: bool = False):
        prop_name = _xml_tag_prop(tag_name)
        enabled = bool(getattr(scene, prop_name, False))
        r = container.row(align=True)
        if standout:
            r.alert = True

        col_tag, col_def, col_title, col_slot = _xml_tags_table_columns(r)

        tag_cell = col_tag.row(align=True)
        tag_cell.prop(scene, prop_name, text="")
        tag_cell.label(text=tag_name)

        title_prop = _xml_title_prop(tag_name)
        if hasattr(scene, title_prop):
            col_title.enabled = enabled
            col_title.prop(scene, title_prop, text="")
        else:
            col_title.label(text="")

        slot_prop = _xml_material_prop(tag_name)
        if tag_name != "wrappingColorConfiguration" and hasattr(scene, slot_prop):
            col_slot.enabled = enabled
            col_slot.prop(scene, slot_prop, text="")
        else:
            col_slot.label(text="")

        col_def.enabled = enabled
        col_def.prop(scene, _xml_defaultcolors_prop(tag_name), text="")

    # Always shown (top)
    _draw_tag_row(tags, "rimColorConfiguration")

    visible_tags = [
        "baseColorConfiguration",
        "designColorConfiguration",
        "designColor2Configuration",
        "designColor3Configuration",
        "designColor4Configuration",
    ]

    if show_more:
        visible_tags.extend([f"designColor{i}Configuration" for i in range(5, 17)])

    for t in visible_tags:
        _draw_tag_row(tags, t)

    toggle_row = tags.row(align=True)
    if show_more:
        toggle_row.operator("i3d.cl_xml_show_less_tags", text="Show Less", icon='TRIA_UP')
    else:
        toggle_row.operator("i3d.cl_xml_show_more_tags", text="Show More", icon='TRIA_DOWN')

    # Always shown (bottom) and should stand out
    tip = tags.box()
    tip.alert = True

    _draw_tag_row(tip, "wrappingColorConfiguration", standout=True)
    tip.label(text="wrappingColorConfiguration is uncommon - easy to miss and is only needed for Bale Wrappers", icon='INFO')

    tags_row = box.row(align=True)

    tags_row.scale_y = 1.1
    tags_row.operator("i3d.cl_xml_select_all_tags", text="Select All Tags Shown", icon='CHECKMARK')

    if _xml_any_tag_selected(scene):
        tags_row2 = box.row(align=True)
        tags_row2.scale_y = 1.1
        tags_row2.operator("i3d.cl_xml_clear_selected_tags", text="Clear selected tags", icon='X')

    box.separator()

    io = box.column(align=True)
    io.scale_y = 1.05
    io.operator("i3d.cl_xml_import_selected", text="Import saved XML", icon='IMPORT')

    # L10N generation options (used by XML export)
    settings = scene.I3D_UIexportSettings

    try:
        l10n = box.column(align=True)
        l10n.scale_y = 1.0

        blender_online_ok = i3d_cl_blender_online_access_enabled()

        l10n_row = l10n.row(align=True)
        split = l10n_row.split(factor=0.55, align=True)

        split.prop(settings, "i3D_exportColorLibrariesGenerateL10N", text="Generate English L10N")

        german_wrap = split.row(align=True)
        if not blender_online_ok:
            german_wrap.enabled = False
        german_wrap.prop(settings, "i3D_exportColorLibrariesGermanL10N", text="Generate German L10N (Online)")

        if not blender_online_ok:
            warn = l10n.row(align=True)
            warn.alert = True
            warn.label(text="Enable Preferences -> System -> Allow Online Access To Generate German L10N Translations", icon='ERROR')

    except Exception as e:
        print("[I3D Color Library] L10N UI draw failed:", repr(e))
        err = box.row(align=True)
        err.alert = True
        err.label(text="L10N UI failed (see console)", icon='ERROR')


    save = box.column(align=True)
    save.scale_y = 1.25
    save.operator("i3d.cl_xml_export_selected", text="Save as an XML", icon='FILE_TICK')


    box.separator()
    howto_row = box.row(align=True)
    howto_row.scale_y = 1.05
    howto_row.operator("i3d.cl_open_howto_xml_mode", text="How To XML Mode", icon='QUESTION')

def draw_color_library(layout, context):
    scene = context.scene

    # NOTE: Caller provides the container layout (typically a collapsible box).
    # Do NOT create an extra outer box here; keep borders clean and avoid nesting.
    box = layout

    mode_row = box.row(align=True)
    mode_row.prop(scene, "i3d_cl_output_mode", expand=True)

    row = box.row(align=True)
    row.prop(scene, "i3d_cl_tab", expand=True)

    if scene.i3d_cl_tab == 'MY':
        header = box.row(align=True)
        header.operator("i3d.cl_my_add", icon='ADD', text="")
        header.operator("i3d.cl_my_remove", icon='REMOVE', text="")

        if scene.i3d_cl_output_mode == 'XML':
            hdr = box.row(align=True)
            hdr.label(text="")
            split = hdr.split(factor=0.50)
            split.label(text="Name")
            right = split.split(factor=0.70)
            right.label(text="Material Type")
            right.label(text="")

        box.template_list(
            "I3D_CL_UL_MyColors",
            "",
            scene,
            "i3d_cl_my_colors",
            scene,
            "i3d_cl_my_index",
            rows=7,
        )

        # -----------------------------
        # XML MODE controls
        # -----------------------------
        if scene.i3d_cl_output_mode == 'XML':
            _draw_xml_mode_controls(box, scene, 'MY')
            return

        idx = scene.i3d_cl_my_index
        if 0 <= idx < len(scene.i3d_cl_my_colors):
            item = scene.i3d_cl_my_colors[idx]
            sel = box.box()
            sel.label(text="Selected")

            sw = sel.row()
            sw.enabled = not bool(getattr(item, "xml_color_locked", False))
            sw.scale_y = 1.3
            sw.prop(item, "color", text="")

            sel.prop(item, "name", text="")

            if scene.i3d_cl_output_mode != 'XML':
                sel.prop(item, "xml_material_template", text="Material Type")

            sel.label(text=f"GIANTS (sRGB): {_srgb_label_text(item.color)}")
            R, G, B = _rgb255_triplet_from_color(item.color)
            sel.label(text=f"RGB: ({R}, {G}, {B})")
            sel.label(text=f"HEX: {_hex_text_from_color(item.color)}")

            tmp_row = sel.row()
            tmp_row.alert = True
            tmp_row.operator("i3d.cl_my_apply_to_material", text="Apply Temporary preview to Material - No Giants Export")

            tmp_row2 = sel.row()
            tmp_row2.alert = True
            tmp_row2.operator("i3d.cl_my_apply_to_material_export", text="Apply Temporary preview to Material and apply material and shader for Giants Export", icon='CHECKMARK')
            permrow = sel.row()
            permrow.alert = True
            _mt = _xml_material_template_from_item(item)
            _blocked = _mtpl_blocks_permanent(_mt)
            permrow.enabled = not _blocked
            permrow.operator("i3d.cl_my_apply_to_material_permanent", text=_WARNING_PERM_BLOCKED_TEXT if _blocked else "Apply permanently To Material using No Shader During Export - Not Suggested")

            copyhdr = sel.row()


            copyhdr.prop(scene, "i3d_cl_show_copy_values", text="Copy Color Values", icon='TRIA_DOWN' if scene.i3d_cl_show_copy_values else 'TRIA_RIGHT', emboss=False)


            if scene.i3d_cl_show_copy_values:


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


                            copyrow2.operator("i3d.cl_my_apply_to_giants_colorscale", text="Apply to GIANTS colorScale")


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
            text="Share & Import My Color Library with Friends",
            icon='TRIA_DOWN' if scene.i3d_cl_show_files else 'TRIA_RIGHT',
            icon_only=False,
            emboss=False,
        )
        if scene.i3d_cl_show_files:
            col = files.column(align=True)
            row = col.row(align=True)
            row.scale_y = 1.1
            row.operator("i3d.cl_my_export", text="Export", icon='EXPORT')
            row.operator("i3d.cl_my_import", text="Import", icon='IMPORT')
            col.operator("i3d.cl_my_reload", text="Reload Library", icon='FILE_REFRESH')
            col.separator()
            col.operator("i3d.cl_my_clear_unused_decals", text="Clear Unused Cached Decals", icon='TRASH')


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
            _deferred_request_rebuild(scene, "GIANTS")

        box.template_list(
            "I3D_CL_UL_GiantsColors",
            "",
            scene,
            "i3d_cl_giants_colors",
            scene,
            "i3d_cl_giants_index",
            rows=7,
        )

        # -----------------------------
        # XML MODE controls
        # -----------------------------
        if scene.i3d_cl_output_mode == 'XML':
            _draw_xml_mode_controls(box, scene, 'GIANTS')
            return

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

            if scene.i3d_cl_output_mode != 'XML':
                sel.prop(item, "xml_material_template", text="Material Type")

            sel.label(text=f"GIANTS (sRGB): {_srgb_label_text(item.color)}")
            R, G, B = _rgb255_triplet_from_color(item.color)
            sel.label(text=f"RGB: ({R}, {G}, {B})")
            sel.label(text=f"HEX: {_hex_text_from_color(item.color)}")

            if item.colorScale:
                sel.label(text=f"colorScale: {item.colorScale}")

            tmp_row = sel.row()
            tmp_row.alert = True
            tmp_row.operator("i3d.cl_giants_apply_to_material", text="Apply Temporary preview to Material - No Giants Export")

            tmp_row2 = sel.row()
            tmp_row2.alert = True
            tmp_row2.operator("i3d.cl_giants_apply_to_material_export", text="Apply Temporary preview to Material and apply material and shader for Giants Export", icon='CHECKMARK')
            addrow = sel.row()
            addrow.operator("i3d.cl_giants_add_to_my_library", text="Add to My Library")

            permrow = sel.row()
            permrow.alert = True
            _mt = _xml_material_template_from_item(item)
            _blocked = _mtpl_blocks_permanent(_mt)
            permrow.enabled = not _blocked
            permrow.operator("i3d.cl_giants_apply_to_material_permanent", text=_WARNING_PERM_BLOCKED_TEXT if _blocked else "Apply permanently To Material using No Shader During Export - Not Suggested")

            copyhdr = sel.row()


            copyhdr.prop(scene, "i3d_cl_show_copy_values", text="Copy Color Values", icon='TRIA_DOWN' if scene.i3d_cl_show_copy_values else 'TRIA_RIGHT', emboss=False)


            if scene.i3d_cl_show_copy_values:


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


                            copyrow2.operator("i3d.cl_giants_apply_to_giants_colorscale", text="Apply to GIANTS colorScale")


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
            _deferred_request_rebuild(scene, "POPULAR")

        if scene.i3d_cl_output_mode == 'XML':
            hdr = box.row(align=True)
            hdr.label(text="")
            split = hdr.split(factor=0.45)
            split.label(text="Name")
            right = split.split(factor=0.70)
            right.label(text="Material Type")
            right.label(text="")

        box.template_list(
            "I3D_CL_UL_PopularColors",
            "",
            scene,
            "i3d_cl_popular_colors",
            scene,
            "i3d_cl_popular_index",
            rows=7,
        )

        # -----------------------------
        # XML MODE controls
        # -----------------------------
        if scene.i3d_cl_output_mode == 'XML':
            _draw_xml_mode_controls(box, scene, 'POPULAR')
            return

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

            tmp_row = sel.row()
            tmp_row.alert = True
            tmp_row.operator("i3d.cl_popular_apply_to_material", text="Apply Temporary preview to Material - No Giants Export")

            tmp_row2 = sel.row()
            tmp_row2.alert = True
            tmp_row2.operator("i3d.cl_popular_apply_to_material_export", text="Apply Temporary preview to Material and apply material and shader for Giants Export", icon='CHECKMARK')
            addrow = sel.row()
            addrow.operator("i3d.cl_popular_add_to_my_library", text="Add to My Library")

            permrow = sel.row()
            permrow.alert = True
            _mt = _xml_material_template_from_item(item)
            _blocked = _mtpl_blocks_permanent(_mt)
            permrow.enabled = not _blocked
            permrow.operator("i3d.cl_popular_apply_to_material_permanent", text=_WARNING_PERM_BLOCKED_TEXT if _blocked else "Apply permanently To Material using No Shader During Export - Not Suggested")

            copyhdr = sel.row()


            copyhdr.prop(scene, "i3d_cl_show_copy_values", text="Copy Color Values", icon='TRIA_DOWN' if scene.i3d_cl_show_copy_values else 'TRIA_RIGHT', emboss=False)


            if scene.i3d_cl_show_copy_values:


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


                            copyrow2.operator("i3d.cl_popular_apply_to_giants_colorscale", text="Apply to GIANTS colorScale")


                            copyrow2.operator("i3d.cl_set_emission_black", text="Set Emission (Black)", icon='SHADING_RENDERED')
        else:
            box.label(text="No Popular color selected", icon='INFO')


    # How-To button (Material Mode)
    howto_row = box.row(align=True)
    howto_row.scale_y = 1.05
    howto_row.operator("i3d.cl_open_howto_material_mode", text="How To Material Mode", icon='QUESTION')

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




# ---------------------------------------------------------------------
# How-To (PDF) openers
# ---------------------------------------------------------------------

def _i3d_cl_open_pdf(filename: str, *, operator: bpy.types.Operator):
    """Open a bundled PDF in the user's default viewer/browser."""
    try:
        pdf_path = (Path(__file__).resolve().parent / "docs" / filename)
    except Exception:
        pdf_path = None

    if not pdf_path or not pdf_path.exists():
        operator.report({'ERROR'}, f"Missing how-to PDF: {filename}")
        return {'CANCELLED'}

    # Prefer url_open with file:// URI (works cross-platform).
    try:
        bpy.ops.wm.url_open(url=pdf_path.as_uri())
        return {'FINISHED'}
    except Exception:
        pass

    # Fallback: open path in OS file explorer (may not open the file directly on some OSes).
    try:
        bpy.ops.wm.path_open(filepath=str(pdf_path))
        return {'FINISHED'}
    except Exception as e:
        operator.report({'ERROR'}, f"Failed to open PDF: {e}")
        return {'CANCELLED'}


class I3D_CL_OT_OpenHowToMaterialMode(bpy.types.Operator):
    bl_idname = "i3d.cl_open_howto_material_mode"
    bl_label = "Open Material Mode How-To"
    bl_description = "Open the Material Mode Color Library tutorial (PDF)"

    def execute(self, context):
        return _i3d_cl_open_pdf("Color_Library_HowTo_Material_Mode.pdf", operator=self)


class I3D_CL_OT_OpenHowToXMLMode(bpy.types.Operator):
    bl_idname = "i3d.cl_open_howto_xml_mode"
    bl_label = "Open XML Mode How-To"
    bl_description = "Open the XML Mode Color Library tutorial (PDF)"

    def execute(self, context):
        return _i3d_cl_open_pdf("Color_Library_HowTo_XML_Mode.pdf", operator=self)


# -----------------------------------------------------------------------------
# Register
# -----------------------------------------------------------------------------


classes = (
    I3D_CL_ColorItem,
    I3D_CL_XMLSelectedColorItem,
    I3D_CL_GiantsColorItem,
    I3D_CL_PopularColorItem,
    I3D_CL_OT_MyAdd,
    I3D_CL_OT_MyRemove,
    I3D_CL_OT_MySortBySelectedMaterial,
    I3D_CL_OT_MyExport,
    I3D_CL_OT_MyImport,
    I3D_CL_OT_MyClearUnusedDecals,
    I3D_CL_OT_MyReload,
    I3D_CL_OT_ApplyMyToMaterial,
    I3D_CL_OT_ApplyMyToMaterialExport,
    I3D_CL_OT_ApplyMyToMaterialPermanent,
    I3D_CL_OT_ApplyMyToGiantsColorScale,
    I3D_CL_OT_CopySelected,
    I3D_CL_OT_GiantsRefresh,
    I3D_CL_OT_PopularRefresh,
    I3D_CL_OT_ClearPreviewMaterialNodes,
    I3D_CL_OT_ApplyGiantsToMaterial,
    I3D_CL_OT_ApplyGiantsToMaterialExport,
    I3D_CL_OT_ApplyGiantsToMaterialPermanent,
    I3D_CL_OT_ApplyGiantsToGiantsColorScale,
    I3D_CL_OT_AddGiantsToMyLibrary,
    I3D_CL_OT_ApplyPopularToMaterial,
    I3D_CL_OT_ApplyPopularToMaterialExport,
    I3D_CL_OT_ApplyPopularToMaterialPermanent,
    I3D_CL_OT_ApplyPopularToGiantsColorScale,
    I3D_CL_OT_AddPopularToMyLibrary,
    I3D_CL_OT_PickDecalBaseImage,
    I3D_CL_OT_ShowDecalPreview,
    I3D_CL_OT_PermApplyDetailPrompt,
    I3D_CL_OT_XMLSelectAllVisible,
    I3D_CL_OT_XMLClearSelectedColors,
    I3D_CL_OT_XMLSelectAllTags,
    I3D_CL_OT_XMLShowMoreTags,
    I3D_CL_OT_XMLShowLessTags,
    I3D_CL_OT_XMLClearSelectedTags,
    I3D_CL_OT_OpenHowToMaterialMode,
    I3D_CL_OT_OpenHowToXMLMode,
    I3D_CL_OT_XMLExportSelected,
    I3D_CL_OT_XMLImportSelected,
    I3D_CL_UL_MyColors,
    I3D_CL_UL_GiantsColors,
    I3D_CL_UL_PopularColors,
    I3D_CL_OT_SetEmissionBlack,
)


def register():
    try:
        _cl_decal_previews_free()
    except Exception:
        pass
    # Best-effort cleanup so reinstall/reload doesn't require restarting Blender.
    # (If a previous enable failed mid-register, Blender can keep some RNA classes alive.)
    try:
        # Remove Scene properties first (if they already exist).
        for _p in (
            "i3d_cl_tab",
            "i3d_cl_output_mode",
            "i3d_cl_xml_selected_colors",
            "i3d_cl_my_colors",
            "i3d_cl_my_index",
            "i3d_cl_giants_brand",
            "i3d_cl_giants_colors",
            "i3d_cl_giants_index",
            "i3d_cl_popular_brand",
            "i3d_cl_popular_colors",
            "i3d_cl_popular_index",
            "i3d_cl_show_files",
        "i3d_cl_show_copy_values",
            "i3d_cl_xml_show_more_tags",
        ):
            if hasattr(bpy.types.Scene, _p):
                try:
                    delattr(bpy.types.Scene, _p)
                except Exception:
                    pass



        # Per-tag XML Scene properties (selection, metadata, and useDefaultColors)
        try:
            for t in _XML_TAG_ORDER:
                for attr in (
                    _xml_tag_prop(t),
                    _xml_defaultcolors_prop(t),
                    _xml_title_prop(t),
                    _xml_material_prop(t),
                ):
                    if hasattr(bpy.types.Scene, attr):
                        try:
                            delattr(bpy.types.Scene, attr)
                        except Exception:
                            pass
        except Exception:
            pass
        # Unregister our classes if they already exist (reverse order).
        for _c in reversed(classes):
            _name = getattr(_c, "__name__", "")
            if not _name:
                continue
            _existing = getattr(bpy.types, _name, None)
            if _existing is None:
                continue
            try:
                bpy.utils.unregister_class(_existing)
            except Exception:
                pass
    except Exception:
        pass

    for c in classes:
        try:
            bpy.utils.register_class(c)
        except RuntimeError as e:
            if "already registered" in str(e):
                continue
            raise

    # Cleanup legacy preview IDProperties so they don't appear in Material custom properties.
    try:
        for _m in bpy.data.materials:
            try:
                if "i3d_preview_blend_method_orig" in _m:
                    del _m["i3d_preview_blend_method_orig"]
            except Exception:
                pass
            try:
                if "i3d_preview_shadow_method_orig" in _m:
                    del _m["i3d_preview_shadow_method_orig"]
            except Exception:
                pass
    except Exception:
        pass

    bpy.types.Scene.i3d_cl_tab = bpy.props.EnumProperty(
        items=[('MY', 'My Color Library', ''), ('GIANTS', 'Giants Library', ''), ('POPULAR', 'Popular Color Library', '')],
        name="Color Library Mode",
        default='MY',
    )


    bpy.types.Scene.i3d_cl_output_mode = bpy.props.EnumProperty(
        items=[('MATERIAL', 'Material Mode', ''), ('XML', 'XML Mode', '')],
        name='Mode',
        default='MATERIAL',
    )

    bpy.types.Scene.i3d_cl_xml_selected_colors = bpy.props.CollectionProperty(type=I3D_CL_XMLSelectedColorItem)
    bpy.types.Scene.i3d_cl_xml_show_more_tags = bpy.props.BoolProperty(
        name="Show More Tags",
        description="Show designColor5Configuration through designColor16Configuration in the XML Export Tags list",
        default=False,
    )


    # XML tag selection booleans
    for t in _XML_TAG_ORDER:
        setattr(
            bpy.types.Scene,
            _xml_tag_prop(t),
            bpy.props.BoolProperty(name=t, default=False),
        )



    # XML tag useDefaultColors booleans
    for t in _XML_TAG_ORDER:
        # Default should be TRUE for all XML export tag wrappers.
        default_val = True
        setattr(
            bpy.types.Scene,
            _xml_defaultcolors_prop(t),
            bpy.props.BoolProperty(
                name="Use Giants Default Colors",
                description="When on the in game color selection for this configuration will allow the default colors (mostly the shared generic colors like jetBlack johnDeereYellow johnDeereGreen navyBlue pink purple things like that total of 35 colors)",
                default=default_val,
            ),
        )
    # XML tag metadata (title / materialSlotName)
    for t in _XML_TAG_ORDER:
        if t == "rimColorConfiguration":
            continue
        setattr(
            bpy.types.Scene,
            _xml_title_prop(t),
            bpy.props.StringProperty(name=f"{t} title", default="CHANGE ME"),
        )
        setattr(
            bpy.types.Scene,
            _xml_material_prop(t),
            bpy.props.StringProperty(name=f"{t} materialSlotName", default="CHANGE ME"),
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

    bpy.types.Scene.i3d_cl_show_copy_values = bpy.props.BoolProperty(
        name="Copy Color Values",
        default=False,
        options={'SKIP_SAVE'},
    )

    bpy.types.Scene.i3d_cl_show_files = bpy.props.BoolProperty(
        name="Share & Import My Color Library with Friends",
        default=False,
        options={'SKIP_SAVE'},
    )

    _on_load_post(None)

    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    if _on_save_pre not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_on_save_pre)


def unregister():
    try:
        _cl_decal_previews_free()
    except Exception:
        pass
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
        "i3d_cl_show_copy_values",
        "i3d_cl_xml_show_more_tags",
    ):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)
    for t in _XML_TAG_ORDER:
        # Tag selection boolean
        attr = _xml_tag_prop(t)
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)

        # useDefaultColors boolean
        attr = _xml_defaultcolors_prop(t)
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)

        # Per-tag metadata (title / materialSlotName)
        if t != "rimColorConfiguration":
            attr = _xml_title_prop(t)
            if hasattr(bpy.types.Scene, attr):
                delattr(bpy.types.Scene, attr)
            attr = _xml_material_prop(t)
            if hasattr(bpy.types.Scene, attr):
                delattr(bpy.types.Scene, attr)

    try:
        del bpy.types.Scene.i3d_cl_xml_selected_colors
    except Exception:
        pass

    try:
        del bpy.types.Scene.i3d_cl_output_mode
    except Exception:
        pass


    for c in reversed(classes):
        try:
            bpy.utils.unregister_class(c)
        except RuntimeError as e:
            if "not registered" in str(e) or "missing bl_rna" in str(e):
                continue
            raise