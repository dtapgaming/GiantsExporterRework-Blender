# io_export_i3d_reworked/i3d_vehicle_light_tool.py
# Vehicle Light Setup Tool + Testing Light System (isolated, surgical)
#
# Goals:
# - Emission color is driven by Vertex Color (GIANTS-style).
# - Emission strength is driven by our test system (modal timer) and/or "Make My Light".
# - Writes required custom material properties for exporter: customShader, customShaderVariation, shadingRate
# - Optional: writes customParameter_lightTypeBitMask for turn signals (20480) as requested.
#
# IMPORTANT: This module is intentionally self-contained to avoid breaking other addon features.

import bpy
import bmesh
import time

_UI_VALIDATION_CACHE = {'key': None, 't': 0.0, 'data': None}
_UI_VALIDATION_TTL = 0.5  # seconds

import math
import os
import struct
import shutil
import subprocess
import csv
import webbrowser
import html as _html
def _write_dds_uncompressed_rgba8(filepath, width, height, pixels_rgba):
    """Write an uncompressed 32bpp DDS (A8R8G8B8) as a fallback when Blender can't save DDS.

    pixels_rgba is a flat float list (RGBA, 0..1) of length width*height*4.
    The DDS will be written as BGRA byte order per pixel (little-endian A8R8G8B8 masks).
    """
    import struct

    # DDS constants
    DDSD_CAPS = 0x1
    DDSD_HEIGHT = 0x2
    DDSD_WIDTH = 0x4
    DDSD_PITCH = 0x8
    DDSD_PIXELFORMAT = 0x1000

    DDPF_ALPHAPIXELS = 0x1
    DDPF_RGB = 0x40

    DDSCAPS_TEXTURE = 0x1000

    dwSize = 124
    ddspf_size = 32

    dwFlags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PITCH | DDSD_PIXELFORMAT
    dwPitchOrLinearSize = width * 4

    # Pixel format (A8R8G8B8 masks)
    ddspf_flags = DDPF_RGB | DDPF_ALPHAPIXELS
    ddspf_fourCC = 0
    ddspf_RGBBitCount = 32
    ddspf_RBitMask = 0x00FF0000
    ddspf_GBitMask = 0x0000FF00
    ddspf_BBitMask = 0x000000FF
    ddspf_ABitMask = 0xFF000000

    dwCaps = DDSCAPS_TEXTURE

    header = bytearray()
    header += b"DDS "
    header += struct.pack("<I", dwSize)
    header += struct.pack("<I", dwFlags)
    header += struct.pack("<I", height)
    header += struct.pack("<I", width)
    header += struct.pack("<I", dwPitchOrLinearSize)
    header += struct.pack("<I", 0)  # dwDepth
    header += struct.pack("<I", 0)  # dwMipMapCount
    header += struct.pack("<11I", *([0] * 11))  # dwReserved1

    # DDS_PIXELFORMAT
    header += struct.pack("<I", ddspf_size)
    header += struct.pack("<I", ddspf_flags)
    header += struct.pack("<I", ddspf_fourCC)
    header += struct.pack("<I", ddspf_RGBBitCount)
    header += struct.pack("<I", ddspf_RBitMask)
    header += struct.pack("<I", ddspf_GBitMask)
    header += struct.pack("<I", ddspf_BBitMask)
    header += struct.pack("<I", ddspf_ABitMask)

    header += struct.pack("<I", dwCaps)
    header += struct.pack("<I", 0)  # dwCaps2
    header += struct.pack("<I", 0)  # dwCaps3
    header += struct.pack("<I", 0)  # dwCaps4
    header += struct.pack("<I", 0)  # dwReserved2

    # Pixel data: BGRA bytes
    data = bytearray(width * height * 4)

    def _b(v):
        if v <= 0.0:
            return 0
        if v >= 1.0:
            return 255
        return int(v * 255.0 + 0.5)

    di = 0
    for i in range(0, len(pixels_rgba), 4):
        r = pixels_rgba[i]
        g = pixels_rgba[i + 1]
        b = pixels_rgba[i + 2]
        a = pixels_rgba[i + 3]
        data[di] = _b(b)
        data[di + 1] = _b(g)
        data[di + 2] = _b(r)
        data[di + 3] = _b(a)
        di += 4

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(header)
        f.write(data)

    return True

import os
import struct
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

# ----------------------------
# Constants / IDs (surgical)
# ----------------------------

NODE_PREFIX = "I3D_LightPreview"
NODE_ATTR = f"{NODE_PREFIX}_Attr"
NODE_EMIT = f"{NODE_PREFIX}_Emission"
NODE_VAL  = f"{NODE_PREFIX}_Strength"
NODE_ADD  = f"{NODE_PREFIX}_Add"
NODE_OUT  = "Material Output"

# Roles stored on materials so test buttons know what to affect
ROLE_ITEMS = [
    ("NONE", "None", ""),
    ("LOWBEAM", "Headlight LowBeams", ""),
    ("HIGHBEAM", "High Beams", ""),
    ("LEFT_SIGNAL", "Left Turn Signal", ""),
    ("RIGHT_SIGNAL", "Right Turn Signal", ""),
    ("WORK_REAR", "Worklight Rear", ""),
    ("BEACON", "Beacon Light", ""),
    ("DRL", "Daytime Running Lights", ""),
]

LIGHT_TYPE_TO_DEFAULT_VCOL = {
    # Legacy role keys (older builds)
    "LOWBEAM":      (1.0, 1.0, 1.0, 1.0),
    "HIGHBEAM":     (1.0, 1.0, 1.0, 1.0),
    "LEFT_SIGNAL":  (1.0, 0.55, 0.0, 1.0),  # amber
    "RIGHT_SIGNAL": (1.0, 0.55, 0.0, 1.0),  # amber
    "WORK_REAR":    (1.0, 1.0, 1.0, 1.0),
    "BEACON":       (1.0, 0.55, 0.0, 1.0),  # amber (common)
    "DRL":          (1.0, 0.75, 0.35, 1.0), # warm-ish white/amberish DRL

    # Current Light Type preset IDs (GIANTS UDIM atlas)
    "0_DEFAULT_LIGHT":               (1.0, 1.0, 1.0, 1.0),
    "1_DEFAULT_LIGHT_HIGHBEAM":      (1.0, 1.0, 1.0, 1.0),
    "2_HIGHBEAM":                    (1.0, 1.0, 1.0, 1.0),
    "3_BOTTOM_LIGHT":                (1.0, 1.0, 1.0, 1.0),
    "4_TOP_LIGHT":                   (1.0, 1.0, 1.0, 1.0),

    # Amber lights
    "5_DRL":                         (1.0, 0.55, 0.0, 1.0),
    "6_TURN_LEFT":                   (1.0, 0.55, 0.0, 1.0),
    "7_TURN_RIGHT":                  (1.0, 0.55, 0.0, 1.0),
    "16_BEACON":                     (1.0, 0.55, 0.0, 1.0),

    # Red rear lights
    "8_BACK_LIGHT":                  (1.0, 0.0, 0.0, 1.0),
    "9_BRAKE_LIGHT":                 (1.0, 0.0, 0.0, 1.0),
    "10_BACK_BRAKE":                 (1.0, 0.0, 0.0, 1.0),

    # White lights
    "11_REVERSE":                    (1.0, 1.0, 1.0, 1.0),
    "12_WORK_FRONT":                 (1.0, 1.0, 1.0, 1.0),
    "13_WORK_BACK":                  (1.0, 1.0, 1.0, 1.0),
    "14_WORK_ADD1":                  (1.0, 1.0, 1.0, 1.0),
    "15_WORK_ADD2":                  (1.0, 1.0, 1.0, 1.0),
}



# ----------------------------
# UV Presets (Dropdown 2)
# ----------------------------
# These map UVs into UDIM tiles for UVMap1. Secondary UV map is always normalized to (0,0) tile.
UV_PRESET_ITEMS = [
    ("0_DEFAULT_LIGHT", "Default Light", ""),
    ("1_DEFAULT_LIGHT_HIGHBEAM", "Default Light & HighBeam", ""),
    ("2_HIGHBEAM", "HighBeam", ""),
    ("3_BOTTOM_LIGHT", "Bottom Light", ""),
    ("4_TOP_LIGHT", "Top Light", ""),
    ("5_DRL", "Daytime Running Light", ""),
    ("6_TURN_LEFT", "Turn Light Left", ""),
    ("7_TURN_RIGHT", "Turn Light Right", ""),
    ("8_BACK_LIGHT", "Back Light", ""),
    ("9_BRAKE_LIGHT", "Brake Light", ""),
    ("10_BACK_BRAKE", "Back & Brake Light", ""),
    ("11_REVERSE", "Reverse Light", ""),
    ("12_WORK_FRONT", "Work Light Front", ""),
    ("13_WORK_BACK", "Work Light Back", ""),
    ("14_WORK_ADD1", "Work Light Additional", ""),
    ("15_WORK_ADD2", "Work Light Additional 2", ""),
    ("16_BEACON", "Beacon Light", ""),
]

UV_PRESET_TO_TILE = {
    "0_DEFAULT_LIGHT": (0, 0),
    "1_DEFAULT_LIGHT_HIGHBEAM": (1, 0),
    "2_HIGHBEAM": (2, 0),
    "3_BOTTOM_LIGHT": (3, 0),
    "4_TOP_LIGHT": (4, 0),
    "5_DRL": (5, 0),
    "6_TURN_LEFT": (6, 0),
    "7_TURN_RIGHT": (7, 0),
    "8_BACK_LIGHT": (0, 1),
    "9_BRAKE_LIGHT": (1, 1),
    "10_BACK_BRAKE": (2, 1),
    "11_REVERSE": (3, 1),
    "12_WORK_FRONT": (4, 1),
    "13_WORK_BACK": (5, 1),
    "14_WORK_ADD1": (6, 1),
    "15_WORK_ADD2": (7, 1),
    "16_BEACON": (0, 0),
}



# ----------------------------
# MultiFunction Light: Material Table
# ----------------------------

MF_EXCLUDE_ID = "EXCLUDE"
MF_EXCLUDE_LABEL = "This material will not be part of the static Light System"
MF_LIGHTTYPE_ITEMS = [(MF_EXCLUDE_ID, MF_EXCLUDE_LABEL, "")] + UV_PRESET_ITEMS
SECONDARY_UV_NAME = "UVMap2"

def _get_view3d_uv_override(context, obj: bpy.types.Object):
    """Build a robust VIEW_3D override for UV operators like uv.smart_project."""
    window = getattr(context, "window", None)
    screen = getattr(context, "screen", None) or (window.screen if window else None)

    if not screen:
        return {"scene": context.scene, "active_object": obj, "object": obj, "edit_object": obj}

    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        region = None
        for r in area.regions:
            if r.type == "WINDOW":
                region = r
                break
        if not region:
            continue

        space = area.spaces.active if area.spaces else None
        region_data = getattr(space, "region_3d", None) if space else None

        override = {
            "window": window,
            "screen": screen,
            "area": area,
            "region": region,
            "scene": context.scene,
            "active_object": obj,
            "object": obj,
            "edit_object": obj,
            "selected_objects": [obj],
        }
        # Some Blender builds poll space_data/region_data for UV ops.
        if space is not None:
            override["space_data"] = space
        if region_data is not None:
            override["region_data"] = region_data
        return override

    return {"scene": context.scene, "active_object": obj, "object": obj, "edit_object": obj, "selected_objects": [obj]}


def _ensure_light_uv_layers(mesh: bpy.types.Mesh):
    """Ensure UV0 exists and UV1 is at index 1 and named SECONDARY_UV_NAME.
    Returns (uv0_name, uv1_name).

    Notes:
    - GIANTS staticLight expects UV0 (index 0) to stay in tile (0,0) (0..1).
    - The function/UDIM UV must be UV index 1 and named 'UVMap2'.
    - We also accept legacy name 'UVMap_LightSecondary' and rename it to 'UVMap2'.
    """
    if not mesh.uv_layers or len(mesh.uv_layers) == 0:
        mesh.uv_layers.new(name="UVMap")
    if len(mesh.uv_layers) == 0:
        raise RuntimeError("Failed to create UV0 layer")

    layers = mesh.uv_layers

    # If a legacy secondary UV exists, rename it to UVMap2
    legacy = layers.get("UVMap_LightSecondary")
    uv2 = layers.get(SECONDARY_UV_NAME)

    if uv2 is None and legacy is not None:
        try:
            legacy.name = SECONDARY_UV_NAME
            uv2 = legacy
        except Exception:
            uv2 = legacy

    # Ensure a secondary UV exists
    if uv2 is None:
        try:
            layers.new(name=SECONDARY_UV_NAME)
        except Exception:
            # fallback: create any second layer then rename later
            layers.new(name="UVMap.001")
        uv2 = layers.get(SECONDARY_UV_NAME) or layers[-1]

    # Ensure secondary UV is at index 1 (UV1)
    try:
        idx = list(layers).index(uv2)
        if idx != 1:
            layers.move(idx, 1)
            uv2 = layers[1]
    except Exception:
        # If move isn't available in this Blender build, we still enforce name.
        uv2 = layers[1] if len(layers) > 1 else uv2

    # Force layer at index 1 to have the exact expected name.
    try:
        uv1 = layers[1]
        if uv1.name != SECONDARY_UV_NAME:
            existing = layers.get(SECONDARY_UV_NAME)
            if existing and existing != uv1:
                try:
                    existing.name = SECONDARY_UV_NAME + "_OLD"
                except Exception:
                    pass
            uv1.name = SECONDARY_UV_NAME
    except Exception:
        pass

    return layers[0].name, layers[1].name


def _run_smart_uv_project_locked(context, obj: bpy.types.Object):
    """Run Blender's Smart UV Project with the user's locked settings."""
    override = _get_view3d_uv_override(context, obj)

    ts = getattr(context.scene, "tool_settings", None)
    prev_sync = None
    if ts is not None and hasattr(ts, "use_uv_select_sync"):
        prev_sync = ts.use_uv_select_sync
        ts.use_uv_select_sync = True

    # NOTE:
    # Blender's Smart UV Project operator expects angle_limit in **radians**.
    # The UI displays degrees, so we must convert the user's locked 66°.
    angle_rad = math.radians(66.0)

    kw_sets = [
        dict(
            angle_limit=angle_rad,
            margin_method="SCALED",
            rotation_method="AXIS_ALIGNED_VERTICAL",
            island_margin=0.14,
            area_weight=0.0,
            correct_aspect=True,
            scale_to_bounds=False,
        ),
        dict(
            angle_limit=angle_rad,
            margin_method="SCALED",
            rotation_method="AXIS_ALIGNED",
            island_margin=0.14,
            area_weight=0.0,
            correct_aspect=True,
            scale_to_bounds=False,
        ),
        # Minimum safe fallback (still Smart UV Project)
        dict(angle_limit=angle_rad, island_margin=0.14),
    ]

    try:
        with context.temp_override(**override):
            try:
                bpy.ops.mesh.select_mode(type="FACE")
            except Exception:
                pass

            for kws in kw_sets:
                try:
                    res = bpy.ops.uv.smart_project(**kws)
                    if isinstance(res, set) and "FINISHED" in res:
                        return True
                except TypeError:
                    continue
                except RuntimeError:
                    continue

            return False
    finally:
        if ts is not None and prev_sync is not None:
            ts.use_uv_select_sync = prev_sync


def _apply_light_uv_setup(context, obj: bpy.types.Object, preset_id: str):
    """
    GIANTS expectation for staticLight:

      - UV0 (first UV layer / index 0) MUST remain in tile (0,0) and inside 0..1.
        LightIntensity reads UV0.

      - UV1 (second UV layer / index 1, named UVMap2) is the one moved into the UDIM
        "function tiles" based on the light type.

    Behavior:
      - EDIT mode: unwrap selected faces (filtered to active material slot). If none selected, unwrap active slot faces.
      - OBJECT mode: unwrap active material slot faces.
      - Unwrap method: Smart UV Project ONLY (locked settings).
      - No UV wrapping / no manual UV math.
    """
    if not context:
        context = bpy.context
    if not obj or obj.type != "MESH":
        return False

    mesh = obj.data
    slot_index = getattr(obj, "active_material_index", 0)
    tile_x, tile_y = UV_PRESET_TO_TILE.get(preset_id, (0, 0))

    uv0_name, uv1_name = _ensure_light_uv_layers(mesh)

    view_layer = context.view_layer
    prev_active = view_layer.objects.active
    prev_selected = [o for o in view_layer.objects if o.select_get()]
    prev_mode = obj.mode

    # For restoring face selection in EDIT mode
    face_sel_restore = None

    try:
        # Ensure only obj is active/selected for ops
        for o in prev_selected:
            o.select_set(False)
        obj.select_set(True)
        view_layer.objects.active = obj

        # Enter edit mode
        if obj.mode != "EDIT":
            bpy.ops.object.mode_set(mode="EDIT")

        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()

        # Determine target faces:
        selected_faces = [f for f in bm.faces if f.select and f.material_index == slot_index]

        if prev_mode == "EDIT" and selected_faces:
            # Respect user's current selection (but filter by active material slot)
            target_face_indices = [f.index for f in selected_faces]
        else:
            # OBJECT mode OR EDIT mode with no selection: operate on all faces in active material slot
            target_face_indices = [f.index for f in bm.faces if f.material_index == slot_index]

        if not target_face_indices:
            return False

        # Save selection state (EDIT mode only) so we can restore it
        face_sel_restore = {f.index: f.select for f in bm.faces}

        # Select only target faces for the operator
        for f in bm.faces:
            f.select_set(False)
        for fi in target_face_indices:
            bm.faces[fi].select_set(True)
        bm.select_flush(True)
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        # Ensure UV0 is the active UV map before unwrap
        try:
            mesh.uv_layers.active_index = 0
            mesh.uv_layers.active = mesh.uv_layers[0]
        except Exception:
            pass

        if not _run_smart_uv_project_locked(context, obj):
            raise RuntimeError("Smart UV Project failed (operator did not finish)")

        # Apply UV1 UDIM shift using UV0 as the source, only for target faces
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        uv0_layer = bm.loops.layers.uv.get(uv0_name)
        uv1_layer = bm.loops.layers.uv.get(uv1_name)
        if not uv0_layer or not uv1_layer:
            raise RuntimeError("Missing UV layers after Smart UV Project")

        target_set = set(target_face_indices)
        for f in bm.faces:
            if f.index not in target_set:
                continue
            for loop in f.loops:
                uv0 = loop[uv0_layer].uv
                u = uv0.x + tile_x
                v = uv0.y + tile_y
                # Clamp inside UDIM tile to avoid boundary float issues (u==tile+1 can spill into next tile in GIANTS)
                eps = 1e-6
                if u < tile_x: u = tile_x
                if v < tile_y: v = tile_y
                if u > tile_x + 1.0 - eps: u = tile_x + 1.0 - eps
                if v > tile_y + 1.0 - eps: v = tile_y + 1.0 - eps
                loop[uv1_layer].uv = (u, v)

        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        # Keep UV0 active for user sanity
        try:
            mesh.uv_layers.active_index = 0
            mesh.uv_layers.active = mesh.uv_layers[0]
        except Exception:
            pass

        # Return count of faces affected (for debug)
        return len(target_face_indices)

    finally:
        # Restore face selection in EDIT mode if we changed it
        try:
            if obj.mode == "EDIT" and face_sel_restore is not None:
                bm = bmesh.from_edit_mesh(mesh)
                bm.faces.ensure_lookup_table()
                for f in bm.faces:
                    sel = face_sel_restore.get(f.index, False)
                    f.select_set(bool(sel))
                bm.select_flush(True)
                bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        except Exception:
            pass

        # Restore object mode
        try:
            if prev_mode != "EDIT":
                bpy.ops.object.mode_set(mode=prev_mode)
        except Exception:
            pass

        # Restore object selection/active
        try:
            for o in view_layer.objects:
                o.select_set(False)
            for o in prev_selected:
                o.select_set(True)
            view_layer.objects.active = prev_active
        except Exception:
            pass
    # OBJECT mode: operate on a temporary bmesh
    bm = bmesh.new()
    bm.from_mesh(mesh)
    _process_bmesh(bm, is_edit_mesh=False)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return True



# The exporter-required material custom properties you specified
REQUIRED_CUSTOM_SHADER = "$data/shaders/vehicleShader.xml"
REQUIRED_VARIATION = "staticLight"
REQUIRED_SHADING_RATE = "1x1"

TURN_SIGNAL_LIGHTTYPE_BITMASK = 20480.0  # as you instructed

def _is_power_of_two(x: int) -> bool:
    try:
        x = int(x)
    except Exception:
        return False
    return x > 0 and (x & (x - 1)) == 0


def _next_power_of_two(x: int, min_value: int = 1, max_value: int = 4096) -> int:
    """Return the next power-of-two >= x, clamped to [min_value, max_value]."""
    try:
        x = int(x)
    except Exception:
        x = min_value
    x = max(min_value, x)
    p = 1
    while p < x:
        p <<= 1
    return int(min(max_value, p))


def _read_dds_dimensions(filepath: str):
    """Return (width, height) for a DDS file, or None if not a DDS/invalid."""
    try:
        with open(filepath, "rb") as f:
            magic = f.read(4)
            if magic != b"DDS ":
                return None
            header = f.read(124)
            if len(header) < 124:
                return None
            # DDS_HEADER: dwHeight at offset 8, dwWidth at offset 12
            height = struct.unpack_from("<I", header, 8)[0]
            width = struct.unpack_from("<I", header, 12)[0]
            return int(width), int(height)
    except Exception:
        return None



def _read_dds_info(filepath: str):
    """Return dict with DDS info: width, height, mipmaps (optional), dxgiFormat (optional).
    This is best-effort and will return None on invalid DDS.
    """
    try:
        with open(filepath, "rb") as f:
            magic = f.read(4)
            if magic != b"DDS ":
                return None
            header = f.read(124)
            if len(header) < 124:
                return None
            height = struct.unpack_from("<I", header, 8)[0]
            width = struct.unpack_from("<I", header, 12)[0]
            mipmaps = struct.unpack_from("<I", header, 24)[0]  # dwMipMapCount
            # Pixel format fourCC at offset 80 (DDS_PIXELFORMAT.dwFourCC)
            fourcc = struct.unpack_from("<I", header, 84)[0]
            fourcc_bytes = struct.pack("<I", fourcc)
            fourcc_str = fourcc_bytes.decode("latin-1", errors="ignore")
            info = {"width": int(width), "height": int(height), "mipmaps": int(mipmaps), "fourcc": fourcc_str}
            # DX10 header follows if fourCC == 'DX10'
            if fourcc_str == "DX10":
                dx10 = f.read(20)
                if len(dx10) == 20:
                    dxgi_format = struct.unpack_from("<I", dx10, 0)[0]
                    info["dxgiFormat"] = int(dxgi_format)
            return info
    except Exception:
        return None


def _find_texconv_executable():
    """Find texconv executable (prefer bundled addon bin/texconv.exe)."""
    # 1) Prefer a bundled texconv shipped with the addon (Windows only).
    try:
        here = os.path.dirname(__file__)  # .../io_export_i3d_reworked/tools
        addon_root = os.path.abspath(os.path.join(here, os.pardir))  # .../io_export_i3d_reworked
        bundled = os.path.join(addon_root, "bin", "texconv.exe")
        if os.path.isfile(bundled):
            return bundled
    except Exception:
        pass

    # 2) Fall back to PATH
    for name in ("texconv.exe", "texconv"):
        try:
            p = shutil.which(name)
            if p:
                return p
        except Exception:
            continue
    return None


def _texconv_dxt5_with_mips(texconv_path: str, png_in: str, out_dir: str):
    """Run texconv to generate legacy DXT5 DDS with full mip chain into out_dir (avoids DX10 header)."""
    cmd = [
        texconv_path,
        "-f", "DXT5",
        "-m", "0",          # full mip chain
        "-o", out_dir,
        "-y",               # overwrite
        png_in,
    ]
    # Windows: avoid opening a console window if possible
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    res = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags)
    return res.returncode, (res.stdout or ""), (res.stderr or "")


def _safe_filename_base(name: str) -> str:
    """Return a filesystem-safe base filename (no extension)."""
    if not name:
        return "LightIntensity"
    s = str(name)
    # Replace characters that commonly break paths on Windows and in mod zips
    for ch in ['<', '>', ':', '"', '/', '\\', '|', '?', '*']:
        s = s.replace(ch, '_')
    s = s.strip().replace(' ', '_')
    # Collapse repeated underscores
    while '__' in s:
        s = s.replace('__', '_')
    return s or "LightIntensity"


def _get_i3d_export_base_dir(context, fallback_dir: str = None) -> str:
    """Return the directory we should treat as the .i3d export base for relative texture paths."""
    try:
        scene = getattr(context, "scene", None)
        ex = getattr(scene, "I3D_UIexportSettings", None) if scene else None

        # If exporter uses the .blend file name/location, use blend directory (if saved)
        if ex and bool(getattr(ex, "i3D_exportUseSoftwareFileName", False)):
            if bpy.data.filepath:
                return os.path.dirname(bpy.data.filepath)

        # Explicit export file location
        if ex:
            loc = str(getattr(ex, "i3D_exportFileLocation", "") or "").strip()
            if loc:
                abs_loc = bpy.path.abspath(loc)
                if abs_loc and os.path.isdir(abs_loc):
                    return abs_loc
                if abs_loc:
                    return os.path.dirname(abs_loc)
    except Exception:
        pass

    return str(fallback_dir) if fallback_dir else None


def _make_export_safe_texture_path(context, abs_dds_path: str, fallback_dir: str = None) -> str:
    """Create a portable, forward-slash relative path for customTexture_lightsIntensity."""
    if not abs_dds_path:
        return ""
    abs_dds_path = os.path.normpath(str(abs_dds_path))
    base_dir = _get_i3d_export_base_dir(context, fallback_dir) or fallback_dir

    # Last resort: basename only
    if not base_dir:
        return os.path.basename(abs_dds_path).replace("\\", "/")

    try:
        rel = os.path.relpath(abs_dds_path, start=base_dir)
    except Exception:
        rel = os.path.basename(abs_dds_path)

    rel = rel.replace("\\", "/")

    # If it escapes the base dir or still looks absolute (drive letter), fall back to basename
    if rel.startswith("..") or ":" in rel:
        rel = os.path.basename(abs_dds_path)

    return rel.replace("\\", "/")


def _resolve_intensity_path(context, tex_value: str):
    """Best-effort resolve customTexture_lightsIntensity to an on-disk file path.
    Supports:
      - absolute paths (C:/... or /...).
      - Blender-relative paths starting with '//' (relative to the .blend directory).
      - relative paths resolved against the .blend directory.
      - relative paths resolved against the LightIntensity Output Folder (li_out_dir) and its parent.
    """
    if not tex_value:
        return None

    tex_str = str(tex_value).strip()

    # Blender-relative paths start with '//' and must be resolved against the .blend file.
    # If we don't do this, Windows can misinterpret '//' as a UNC path.
    try:
        if tex_str.startswith("//"):
            abs_p = bpy.path.abspath(tex_str)
            if abs_p:
                tex_str = abs_p
    except Exception:
        pass

    # Normalize slashes + collapse ./ and ../
    tex_norm = tex_str.replace("\\", "/")

    # If still starts with '//' (e.g. unsaved blend or abspath failed), strip it so we don't treat it as UNC.
    if tex_norm.startswith("//"):
        tex_norm = tex_norm[2:]

    tex_os = os.path.normpath(tex_norm)

    # If absolute, use directly
    try:
        if os.path.isabs(tex_os) or (len(tex_os) > 2 and tex_os[1] == ":" and tex_os[2] in ("\\", "/")):
            return tex_os
    except Exception:
        pass

    candidates = []

    # 1) blend directory
    try:
        blend_path = bpy.data.filepath or ""
        if blend_path:
            blend_dir = os.path.dirname(blend_path)
            candidates.append(os.path.join(blend_dir, tex_os))
    except Exception:
        pass

    # 2) output dir (and its parent)
    try:
        props = getattr(context.scene, "i3d_light_tool", None) if context and getattr(context, "scene", None) else None
        out_dir = getattr(props, "li_out_dir", "") if props else ""
        if out_dir:
            out_dir = bpy.path.abspath(out_dir)
            # direct join
            candidates.append(os.path.join(out_dir, tex_os))
            # join by basename
            candidates.append(os.path.join(out_dir, os.path.basename(tex_os)))
            # parent join (helps when tex_value includes folder name like LightSystem/merged.dds)
            parent = os.path.dirname(out_dir)
            if parent:
                candidates.append(os.path.join(parent, tex_os))
    except Exception:
        pass

    # 3) i3d export directory (portable mod path)
    try:
        base_dir = _get_i3d_export_base_dir(context, None)
        if base_dir:
            candidates.append(os.path.join(base_dir, tex_os))
            candidates.append(os.path.join(base_dir, os.path.basename(tex_os)))
    except Exception:
        pass

    for c in candidates:
        try:
            if c and os.path.exists(c):
                return c
        except Exception:
            continue
    return None

    # Normalize slashes for current OS
    tex_norm = tex_value.replace("\\", "/").replace("\\", "/")
    tex_norm = tex_norm.replace("\\", "/")
    tex_norm = tex_norm.replace("\\", "/")
    tex_norm = tex_norm.replace("\\", "/")
    # Use os.path for actual existence checks
    tex_os = os.path.normpath(tex_norm)

    # If absolute, use directly
    try:
        if os.path.isabs(tex_os) or (len(tex_os) > 2 and tex_os[1] == ":" and tex_os[2] in ("\\", "/")):
            return tex_os
    except Exception:
        pass

    candidates = []

    # 1) blend directory
    try:
        blend_path = bpy.data.filepath or ""
        if blend_path:
            blend_dir = os.path.dirname(blend_path)
            candidates.append(os.path.join(blend_dir, tex_os))
    except Exception:
        pass

    # 2) output dir (and its parent)
    try:
        props = getattr(context.scene, "i3d_light_tool", None) if context and getattr(context, "scene", None) else None
        out_dir = getattr(props, "li_out_dir", "") if props else ""
        if out_dir:
            out_dir = bpy.path.abspath(out_dir)
            # direct join
            candidates.append(os.path.join(out_dir, tex_os))
            # join by basename
            candidates.append(os.path.join(out_dir, os.path.basename(tex_os)))
            # parent join (helps when tex_value includes folder name like LightSystem/merged.dds)
            parent = os.path.dirname(os.path.normpath(out_dir))
            candidates.append(os.path.join(parent, tex_os))
    except Exception:
        pass


    # 3) i3d export directory (portable mod path)
    try:
        base_dir = _get_i3d_export_base_dir(context, None)
        if base_dir:
            candidates.append(os.path.join(base_dir, tex_os))
            candidates.append(os.path.join(base_dir, os.path.basename(tex_os)))
    except Exception:
        pass

    for c in candidates:
        try:
            if c and os.path.exists(c):
                return c
        except Exception:
            continue
    return None




def _normalize_blender_path(p: str) -> str:
    """Normalize a Blender/OS path while preserving Blender-relative '//' prefix."""
    if not p:
        return ""
    s = str(p)
    try:
        if s.startswith("//"):
            tail = s[2:]
            tail_norm = os.path.normpath(tail).replace("\\", "/")
            return "//" + tail_norm
        return os.path.normpath(s).replace("\\", "/")
    except Exception:
        return s


def _find_emission_image_path(mat) -> str:
    """Return the image filepath feeding the material's Emission input (if any).

    We intentionally keep this lightweight and only follow the active output surface shader graph.
    """
    try:
        if not mat or not getattr(mat, "use_nodes", False) or not getattr(mat, "node_tree", None):
            return ""
        nt = mat.node_tree
        nodes = nt.nodes

        # Active output first
        out = None
        for n in nodes:
            if n.type == "OUTPUT_MATERIAL" and getattr(n, "is_active_output", False):
                out = n
                break
        if out is None:
            for n in nodes:
                if n.type == "OUTPUT_MATERIAL":
                    out = n
                    break
        if out is None or "Surface" not in out.inputs or not out.inputs["Surface"].is_linked:
            return ""

        def trace_image_from_socket(sock, depth=0, visited=None):
            if visited is None:
                visited = set()
            if not sock or not getattr(sock, "is_linked", False) or depth > 16:
                return None
            for link in sock.links:
                n = link.from_node
                if n is None or n in visited:
                    continue
                visited.add(n)
                if getattr(n, "type", "") == "TEX_IMAGE":
                    img = getattr(n, "image", None)
                    if img:
                        return img
                # Walk upstream through inputs (handles mixrgb/math/etc)
                for in_s in getattr(n, "inputs", []):
                    img = trace_image_from_socket(in_s, depth + 1, visited)
                    if img:
                        return img
            return None

        def collect_emission_sockets(shader_node, out_list, depth=0, visited=None):
            if visited is None:
                visited = set()
            if shader_node is None or shader_node in visited or depth > 16:
                return
            visited.add(shader_node)

            t = getattr(shader_node, "type", "")
            if t == "BSDF_PRINCIPLED":
                for nm in ("Emission Color", "Emission"):
                    if nm in shader_node.inputs:
                        out_list.append(shader_node.inputs[nm])
            elif t == "EMISSION":
                if "Color" in shader_node.inputs:
                    out_list.append(shader_node.inputs["Color"])

            # Recurse through shader inputs (Mix Shader / Add Shader / Group)
            for in_s in getattr(shader_node, "inputs", []):
                if getattr(in_s, "is_linked", False):
                    try:
                        src = in_s.links[0].from_node
                    except Exception:
                        src = None
                    if src is not None:
                        collect_emission_sockets(src, out_list, depth + 1, visited)

        # Start from surface shader feeding the active output
        surface_shader = out.inputs["Surface"].links[0].from_node
        cand_sockets = []
        collect_emission_sockets(surface_shader, cand_sockets)

        for s in cand_sockets:
            img = trace_image_from_socket(s)
            if img:
                fp = getattr(img, "filepath", "") or getattr(img, "filepath_raw", "") or ""
                return _normalize_blender_path(fp)
        return ""
    except Exception:
        return ""


def _apply_uvmap2_udim_shift_only(context, obj: bpy.types.Object, preset_id: str, slot_index: int):
    """
    Shift UVMap2 (secondary UV) into the UDIM function tile for the given preset,
    using UV0 as the source, WITHOUT unwrapping and WITHOUT writing UV0.

    Only affects faces that use the given material slot index.
    Creates UVMap2 if missing (via _ensure_light_uv_layers).
    Returns number of faces affected.
    """
    if not obj or obj.type != "MESH":
        return 0

    mesh = obj.data
    tile_x, tile_y = UV_PRESET_TO_TILE.get(preset_id, (0, 0))

    view_layer = context.view_layer
    prev_active = view_layer.objects.active
    prev_selected = [o for o in view_layer.objects if o.select_get()]
    prev_mode = obj.mode

    # For restoring face selection if we change it
    face_sel_restore = None

    try:
        # Ensure only obj is active/selected for ops
        for o in prev_selected:
            o.select_set(False)
        obj.select_set(True)
        view_layer.objects.active = obj

        # Ensure UV layers exist and UVMap2 is UV1
        uv0_name, uv1_name = _ensure_light_uv_layers(mesh)

        # Enter edit mode
        if obj.mode != "EDIT":
            bpy.ops.object.mode_set(mode="EDIT")

        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()

        # Preserve current selection (if any)
        try:
            face_sel_restore = {f.index: bool(f.select) for f in bm.faces}
        except Exception:
            face_sel_restore = None

        # Target faces: selected faces of slot if any, else all faces of slot
        selected_faces = [f for f in bm.faces if f.select and f.material_index == slot_index]
        if prev_mode == "EDIT" and selected_faces:
            target_faces = selected_faces
        else:
            target_faces = [f for f in bm.faces if f.material_index == slot_index]

        if not target_faces:
            return 0

        uv0_layer = bm.loops.layers.uv.get(uv0_name)
        uv1_layer = bm.loops.layers.uv.get(uv1_name)
        if not uv0_layer or not uv1_layer:
            return 0

        eps = 1e-6
        for f in target_faces:
            for loop in f.loops:
                uv0 = loop[uv0_layer].uv
                u = uv0.x + tile_x
                v = uv0.y + tile_y
                # Clamp inside tile to avoid boundary float issues
                if u < tile_x: u = tile_x
                if v < tile_y: v = tile_y
                if u > tile_x + 1.0 - eps: u = tile_x + 1.0 - eps
                if v > tile_y + 1.0 - eps: v = tile_y + 1.0 - eps
                loop[uv1_layer].uv = (u, v)

        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        return len(target_faces)

    finally:
        # Restore selection
        try:
            if face_sel_restore is not None:
                bm = bmesh.from_edit_mesh(mesh)
                bm.faces.ensure_lookup_table()
                for f in bm.faces:
                    f.select_set(bool(face_sel_restore.get(f.index, False)))
                bm.select_flush(True)
                bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        except Exception:
            pass

        # Restore object mode
        try:
            if prev_mode != "EDIT":
                bpy.ops.object.mode_set(mode=prev_mode)
        except Exception:
            pass

        # Restore selection/active objects
        try:
            for o in view_layer.objects:
                o.select_set(False)
            for o in prev_selected:
                o.select_set(True)
            view_layer.objects.active = prev_active
        except Exception:
            pass


def _apply_light_uv_setup_to_material_slot(obj: bpy.types.Object, slot_index: int, preset_id: str):
    """
    Force UV setup for ALL faces that use the given material slot index.
    This is a repair/failsafe tool so users don't end up with partial faces in the wrong UDIM tile.
    """
    if not obj or obj.type != "MESH":
        return False

    mesh = obj.data
    tile_x, tile_y = UV_PRESET_TO_TILE.get(preset_id, (0, 0))

    # Ensure at least one UV layer exists for UV0
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")

    uv0_name = mesh.uv_layers[0].name

    # Ensure secondary UV exists
    if SECONDARY_UV_NAME not in mesh.uv_layers:
        mesh.uv_layers.new(name=SECONDARY_UV_NAME)

    def _process_bmesh(bm, is_edit_mesh: bool):
        uv_layer0 = bm.loops.layers.uv.get(uv0_name)
        if uv_layer0 is None:
            uv_layer0 = bm.loops.layers.uv.new(uv0_name)

        uv_layer2 = bm.loops.layers.uv.get(SECONDARY_UV_NAME)
        if uv_layer2 is None:
            uv_layer2 = bm.loops.layers.uv.new(SECONDARY_UV_NAME)

        faces = [f for f in bm.faces if f.material_index == slot_index]
        if not faces:
            u = base_u + tile_x
            v = base_v + tile_y
            # Clamp inside UDIM tile to avoid boundary float issues (u==tile+1 can spill into next tile in GIANTS)
            eps = 1e-6
            if u < tile_x: u = tile_x
            if v < tile_y: v = tile_y
            if u > tile_x + 1.0 - eps: u = tile_x + 1.0 - eps
            if v > tile_y + 1.0 - eps: v = tile_y + 1.0 - eps
            loop[uv_layer2].uv = (u, v)

        for f in faces:
            for loop in f.loops:
                uv0 = loop[uv_layer0].uv
                base_u = uv0.x - math.floor(uv0.x)
                base_v = uv0.y - math.floor(uv0.y)
                loop[uv_layer0].uv = (base_u, base_v)
                loop[uv_layer2].uv = (base_u + tile_x, base_v + tile_y)

        if is_edit_mesh:
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        return True

    if obj.mode == "EDIT":
        bm = bmesh.from_edit_mesh(mesh)
        return _process_bmesh(bm, is_edit_mesh=True)

    bm = bmesh.new()
    bm.from_mesh(mesh)
    ok = _process_bmesh(bm, is_edit_mesh=False)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return ok


# ----------------------------
# Helpers: Vertex Color Access
# ----------------------------

def _get_active_vcol_name(obj: bpy.types.Object) -> str:
    """Return active color attribute name, fallback to 'Col'."""
    if not obj or obj.type != "MESH":
        return "Col"

    mesh = obj.data
    # Blender 3.2+ color_attributes
    if hasattr(mesh, "color_attributes") and mesh.color_attributes:
        # Try active
        active = getattr(mesh.color_attributes, "active", None)
        if active and getattr(active, "name", ""):
            return active.name
        # Fallback first
        if mesh.color_attributes[0].name:
            return mesh.color_attributes[0].name
    # Legacy vertex_colors
    if hasattr(mesh, "vertex_colors") and mesh.vertex_colors:
        return mesh.vertex_colors.active.name if mesh.vertex_colors.active else mesh.vertex_colors[0].name

    return "Col"


def _ensure_color_attribute(mesh: bpy.types.Mesh, name="Col"):
    """Ensure a CORNER color attribute exists and return it."""
    # Blender 3.2+
    if hasattr(mesh, "color_attributes"):
        if name in mesh.color_attributes:
            return mesh.color_attributes[name]
        # BYTE_COLOR is fine for vertex paint style usage
        try:
            attr = mesh.color_attributes.new(name=name, type="BYTE_COLOR", domain="CORNER")
        except TypeError:
            # Older variants might not support BYTE_COLOR; fallback
            attr = mesh.color_attributes.new(name=name, type="FLOAT_COLOR", domain="CORNER")
        # Make active if possible
        try:
            mesh.color_attributes.active = attr
        except Exception:
            pass
        return attr

    # Legacy
    if hasattr(mesh, "vertex_colors"):
        if name in mesh.vertex_colors:
            return mesh.vertex_colors[name]
        vcol = mesh.vertex_colors.new(name=name)
        mesh.vertex_colors.active = vcol
        return vcol

    return None


def _paint_selected_faces_vertex_color(obj: bpy.types.Object, rgba):
    """
    Paint selected faces (or all faces if none selected) in the active vertex color attribute.
    Works without switching modes; respects polygon selection state.
    """
    if not obj or obj.type != "MESH":
        return False

    mesh = obj.data

    # Ensure some color attr exists
    vcol_name = _get_active_vcol_name(obj)
    attr = _ensure_color_attribute(mesh, vcol_name)
    if not attr:
        # Create default
        attr = _ensure_color_attribute(mesh, "Col")
        vcol_name = "Col"
        if not attr:
            return False

    # Determine selected polygons (object-mode selection is stored on polygons)
    selected_polys = [p for p in mesh.polygons if p.select]
    if not selected_polys:
        selected_polys = list(mesh.polygons)

    # CORNER domain: paint loops
    if hasattr(mesh, "color_attributes"):
        # mesh.color_attributes data supports .color
        for p in selected_polys:
            for li in p.loop_indices:
                try:
                    attr.data[li].color = rgba
                except Exception:
                    # Some builds use .color_srgb etc; best-effort
                    try:
                        attr.data[li].color = (rgba[0], rgba[1], rgba[2], rgba[3])
                    except Exception:
                        pass
        mesh.update()
        return True

    # Legacy vertex_colors (also per-loop)
    if hasattr(mesh, "vertex_colors"):
        vcol = mesh.vertex_colors.get(vcol_name)
        if not vcol:
            vcol = mesh.vertex_colors.new(name=vcol_name)
        for p in selected_polys:
            for li in p.loop_indices:
                vcol.data[li].color = (rgba[0], rgba[1], rgba[2], rgba[3])
        mesh.update()
        return True

    return False


# ----------------------------
# Helpers: Node Injection (Vertex Color -> Emission Color)
# ----------------------------

def _find_node(nodes, name):
    for n in nodes:
        if n.name == name:
            return n
    return None


def _ensure_light_preview_nodes(mat: bpy.types.Material, obj_for_vcol: bpy.types.Object):
    """
    Adds a minimal emission add-on chain:
      (existing shader) + Emission(color=VertexColor, strength=Value) -> Material Output
    This is isolated and only created when user uses light tools.
    """
    if not mat:
        return None

    mat.use_nodes = True
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links

    out = None
    for n in nodes:
        if n.type == "OUTPUT_MATERIAL":
            out = n
            break
    if not out:
        out = nodes.new("ShaderNodeOutputMaterial")
        out.location = (400, 0)

    # Determine existing surface connection (if any)
    existing_link = None
    if out.inputs.get("Surface") and out.inputs["Surface"].is_linked:
        existing_link = out.inputs["Surface"].links[0]
        # If the output is already fed by our Add node, treat input[0] of that node as the "real base shader".
        from_node = existing_link.from_node
        if from_node and from_node.name == NODE_ADD:
            base_socket = None
            try:
                if from_node.inputs[0].is_linked:
                    base_socket = from_node.inputs[0].links[0].from_socket
            except Exception:
                base_socket = None
            existing_shader_socket = base_socket
        else:
            existing_shader_socket = existing_link.from_socket
    else:
        existing_shader_socket = None

    # Reuse if already created
    n_attr = _find_node(nodes, NODE_ATTR)
    n_emit = _find_node(nodes, NODE_EMIT)
    n_val  = _find_node(nodes, NODE_VAL)
    n_add  = _find_node(nodes, NODE_ADD)

    if not n_attr:
        n_attr = nodes.new("ShaderNodeAttribute")
        n_attr.name = NODE_ATTR
        n_attr.label = "I3D VertexColor (GIANTS)"
        n_attr.location = (-600, -200)

    if not n_emit:
        n_emit = nodes.new("ShaderNodeEmission")
        n_emit.name = NODE_EMIT
        n_emit.label = "I3D Emission"
        n_emit.location = (-200, -200)

    if not n_val:
        n_val = nodes.new("ShaderNodeValue")
        n_val.name = NODE_VAL
        n_val.label = "I3D Emission Strength"
        n_val.location = (-600, -420)
        # default OFF
        n_val.outputs[0].default_value = 0.0

    if not n_add:
        n_add = nodes.new("ShaderNodeAddShader")
        n_add.name = NODE_ADD
        n_add.label = "I3D Add Emission"
        n_add.location = (120, -50)

    # Set attribute name to active vcol
    vcol_name = _get_active_vcol_name(obj_for_vcol)
    try:
        n_attr.attribute_name = vcol_name
    except Exception:
        # Fallback
        n_attr.attribute_name = "Col"

    # Clear our links only (avoid nuking others)
    def _safe_unlink(to_socket):
        if to_socket and to_socket.is_linked:
            for lk in list(to_socket.links):
                links.remove(lk)

    # Ensure links: VertexColor -> Emission Color; Value -> Strength
    # Remove only our target links if already present
    _safe_unlink(n_emit.inputs.get("Color"))
    _safe_unlink(n_emit.inputs.get("Strength"))

    links.new(n_attr.outputs.get("Color"), n_emit.inputs.get("Color"))
    links.new(n_val.outputs.get("Value"), n_emit.inputs.get("Strength"))

    # Build chain:
    # If existing shader exists, add emission to it
    # else emission only
    _safe_unlink(n_add.inputs[0])
    _safe_unlink(n_add.inputs[1])
    _safe_unlink(out.inputs.get("Surface"))

    if existing_shader_socket:
        # keep the existing shader
        links.new(existing_shader_socket, n_add.inputs[0])
        links.new(n_emit.outputs.get("Emission"), n_add.inputs[1])
        links.new(n_add.outputs.get("Shader"), out.inputs.get("Surface"))
    else:
        # no existing shader connected
        links.new(n_emit.outputs.get("Emission"), out.inputs.get("Surface"))

    mat["i3d_light_preview_enabled"] = True
    return n_val


def _set_preview_emission_strength(mat: bpy.types.Material, strength: float):
    """Fast emission strength setter.
    Uses node lookup by name (fast) to avoid scanning nodes every tick.
    """
    if not mat or not mat.use_nodes or not mat.node_tree:
        return
    node = mat.node_tree.nodes.get(NODE_VAL)
    if node and node.type == "VALUE":
        node.outputs[0].default_value = max(0.0, float(strength))


# ----------------------------
# Helpers: Material Custom Properties (Exporter)
# ----------------------------

def _write_required_exporter_props(mat: bpy.types.Material):
    if not mat:
        return
    mat["customShader"] = REQUIRED_CUSTOM_SHADER
    mat["customShaderVariation"] = REQUIRED_VARIATION
    mat["shadingRate"] = REQUIRED_SHADING_RATE


def _write_turn_signal_bitmask(mat: bpy.types.Material):
    # You requested: customParameter_lightTypeBitMask = "20480.0 0.0 0.0 0.0"
    # The exporter writes CustomParameter values as strings, so we store this as a string.
    if not mat:
        return
    mat["customParameter_lightTypeBitMask"] = f"{float(TURN_SIGNAL_LIGHTTYPE_BITMASK):.1f} 0.0 0.0 0.0"


# ----------------------------
# Helpers: Validation / Failsafe (GE-style)
# ----------------------------

TEST_MODE_TO_ALLOWED_LIGHT_IDS = {
    # Headlights
    "DEFAULT": {"0_DEFAULT_LIGHT", "1_DEFAULT_LIGHT_HIGHBEAM", "3_BOTTOM_LIGHT", "4_TOP_LIGHT"},
    "HIGHBEAM": {"1_DEFAULT_LIGHT_HIGHBEAM", "2_HIGHBEAM"},

    # Turn signals / hazards
    "LEFT_SIGNAL": {"6_TURN_LEFT"},
    "RIGHT_SIGNAL": {"7_TURN_RIGHT"},
    "HAZARDS": {"6_TURN_LEFT", "7_TURN_RIGHT"},

    # Rear lights
    "BACK": {"8_BACK_LIGHT", "10_BACK_BRAKE"},
    "BRAKE": {"9_BRAKE_LIGHT", "10_BACK_BRAKE"},
    "REVERSE": {"11_REVERSE"},

    # Work lights
    "WORK_FRONT": {"12_WORK_FRONT"},
    "WORK_BACK": {"13_WORK_BACK"},
    "WORK_ADD1": {"14_WORK_ADD1"},
    "WORK_ADD2": {"15_WORK_ADD2"},
    "WORK_ALL": {"12_WORK_FRONT", "13_WORK_BACK", "14_WORK_ADD1", "15_WORK_ADD2"},

    # Other
    "DRL": {"5_DRL"},
    "BEACON": {"16_BEACON"},
    "TOP": {"4_TOP_LIGHT"},
    "BOTTOM": {"3_BOTTOM_LIGHT"},
}

# Brightness simulation (preview-only)
# DTAP request: make it easier to see differences between dimmer defaults/back lights
# and brighter brake/highbeam tests.
TEST_MODE_INTENSITY_MULT = {
    "DEFAULT": 0.08,
    "BACK": 0.12,
    "BRAKE": 0.65,
    "HIGHBEAM": 1.00,
}

def _parse_multi_modes(modes_csv: str):
    if not modes_csv:
        return []
    parts = [p.strip() for p in modes_csv.split(",")]
    return [p for p in parts if p]


def _multi_allowed_ids_and_mult(context):
    """Returns (modes_set, allowed_ids_set, mult_by_light_id_dict)."""
    props = context.scene.i3d_light_tool
    modes = set(_parse_multi_modes(props.test_multi_modes))

    allowed = set()
    mult_by_id = {}

    for mode in modes:
        ids = TEST_MODE_TO_ALLOWED_LIGHT_IDS.get(mode, set())
        allowed |= set(ids)
        mult = float(TEST_MODE_INTENSITY_MULT.get(mode, 1.0))
        for lid in ids:
            prev = float(mult_by_id.get(lid, 0.0))
            if mult > prev:
                mult_by_id[lid] = mult

    return modes, allowed, mult_by_id




def _compute_test_scope_signature(context, scope: str):
    """Lightweight signature to detect scope changes without expensive scanning."""
    try:
        if scope == "SELECTED":
            names = tuple(sorted([o.name_full for o in context.selected_objects if o and o.type == "MESH"]))
            return ("SELECTED", names)
        if scope == "ACTIVE":
            ao = context.view_layer.objects.active
            return ("ACTIVE", ao.name_full if ao else "")
        if scope == "VIEW_LAYER":
            # Don't hash every object name; counts + active name is enough.
            ao = context.view_layer.objects.active
            return ("VIEW_LAYER", len(context.view_layer.objects), ao.name_full if ao else "")
        if scope == "SCENE":
            ao = context.view_layer.objects.active
            return ("SCENE", len(context.scene.objects), ao.name_full if ao else "")
    except Exception:
        pass
    return (scope,)


def _get_test_scope_objects(context, scope: str):
    if scope == "SELECTED":
        return [o for o in context.selected_objects if o is not None]
    if scope == "SCENE":
        return [o for o in context.scene.objects if o is not None]
    # Default: VIEW_LAYER (visible to the user)
    return [o for o in context.view_layer.objects if o is not None]


# ----------------------------
# Testing Runtime Cache (perf)
# ----------------------------
_TEST_RUNTIME = {
    "targets": [],           # list of dicts (obj_name, slot_index, mat_name, light_id, wants_on, ok, obj_ref, mat_ref)
    "targets_by_light_id": {},  # light_id => list[dict] (built on rebuild for fast filtering)
    "last_revalidate": 0.0,
    "modal_active": False,   # True while the Light Test modal timer is running
    "timer": None,           # WindowManager timer handle (robust start/stop)
    "gen": 0,                # Generation counter to invalidate old modal instances

    # Signature of the currently running test (used to avoid rebuilding targets every tick)
    "active_sig": None,      # tuple(mode, scope, multi_csv)

    # Fast-path change detection
    "last_blink_on": None,
    "last_beacon_on": None,
    "last_base_intensity": None,

    # Cached results from last rebuild
    "last_mode": "",
    "last_scope": "",
    "last_multi_csv": "",

    # Cache of emission strengths we've already applied
    "last_strengths": {},    # key: material name => last_strength
}


def _clear_test_runtime():
    _TEST_RUNTIME["targets"].clear()
    _TEST_RUNTIME["targets_by_light_id"] = {}
    _TEST_RUNTIME["last_strengths"].clear()
    _TEST_RUNTIME["last_revalidate"] = 0.0
    _TEST_RUNTIME["last_mode"] = ""
    _TEST_RUNTIME["last_scope"] = ""
    _TEST_RUNTIME["last_multi_csv"] = ""
    _TEST_RUNTIME["active_sig"] = None
    _TEST_RUNTIME["last_blink_on"] = None
    _TEST_RUNTIME["last_beacon_on"] = None
    _TEST_RUNTIME["last_base_intensity"] = None



def _test_modal_is_alive() -> bool:
    try:
        return bool(_TEST_RUNTIME.get("modal_active")) and (_TEST_RUNTIME.get("timer") is not None)
    except Exception:
        return False


def _stop_test_modal_runner(context):
    """Hard-stop the modal runner (robust against rapid toggle spam).
    - Removes the active WM timer if present.
    - Marks modal as inactive so a new runner can start immediately.
    - Bumps generation so any lingering modal instances self-cancel on the next event.
    """
    try:
        _TEST_RUNTIME["gen"] = int(_TEST_RUNTIME.get("gen", 0)) + 1
    except Exception:
        _TEST_RUNTIME["gen"] = 1

    timer = _TEST_RUNTIME.get("timer")
    if timer is not None:
        try:
            context.window_manager.event_timer_remove(timer)
        except Exception:
            pass

    _TEST_RUNTIME["timer"] = None
    _TEST_RUNTIME["modal_active"] = False
    _TEST_RUNTIME["active_sig"] = None


def _ensure_test_modal_runner(context):
    """Ensure the light-test modal runner is active (single instance)."""
    if not _test_modal_is_alive():
        try:
            bpy.ops.i3d.light_test_modal("INVOKE_DEFAULT")
        except Exception:
            pass

def _rebuild_test_targets(context, mode: str, scope: str):
    """Rebuild cached targets and (optionally) revalidate them.
    This is intentionally done infrequently to avoid lag while a modal timer is running.
    """
    multi_modes = set()
    mult_by_id = {}
    if mode == "MULTI":
        multi_modes, allowed_ids, mult_by_id = _multi_allowed_ids_and_mult(context)
    else:
        allowed_ids = TEST_MODE_TO_ALLOWED_LIGHT_IDS.get(mode, set())
    targets = []
    targets_by_light_id = {}
    objects = _get_test_scope_objects(context, scope)

    for obj in objects:
        if not obj or obj.type != "MESH":
            continue

        # If editing, sync once during rebuild (safe + prevents UV data crashes)
        try:
            if obj.mode == "EDIT":
                obj.update_from_editmode()
        except Exception:
            pass

        for slot_index, slot in enumerate(obj.material_slots):
            mat = slot.material
            if not mat:
                continue

            light_id = _resolve_light_id_from_material(mat)
            if light_id in {"", "NONE"}:
                continue

            wants_on = (light_id in allowed_ids)
            ok = True
            if wants_on:
                ok, _errors = _validate_light_setup(context, obj, slot_index, mat, light_id)

            # Ensure preview nodes once (cheap on re-run, expensive on first run)
            try:
                if not mat.get("i3d_light_preview_enabled"):
                    _ensure_light_preview_nodes(mat, obj)
            except Exception:
                pass

            tinfo = {
                "obj_name": obj.name,
                "slot_index": slot_index,
                "mat_name": mat.name,
                "light_id": light_id,
                "wants_on": wants_on,
                "ok": ok,
                # direct refs (perf): avoid bpy.data lookups in modal
                "obj_ref": obj,
                "mat_ref": mat,
            }
            targets.append(tinfo)
            targets_by_light_id.setdefault(light_id, []).append(tinfo)

    _TEST_RUNTIME["targets"] = targets
    _TEST_RUNTIME["targets_by_light_id"] = targets_by_light_id
    _TEST_RUNTIME["last_mode"] = mode
    _TEST_RUNTIME["last_scope"] = scope

def _resolve_light_id_from_material(mat: bpy.types.Material) -> str:
    """
    Reads the stored light identifier from the material.

    Supports:
    - Current: mat["i3d_light_type"] = "6_TURN_LEFT" etc.
    - Legacy: mat["i3d_light_role"] = "LEFT_SIGNAL" etc.
    """
    if not mat:
        return ""

    light_id = mat.get("i3d_light_type") or mat.get("i3d_light_role") or ""
    legacy_map = {
        "LOWBEAM": "0_DEFAULT_LIGHT",
        "HIGHBEAM": "2_HIGHBEAM",
        "LEFT_SIGNAL": "6_TURN_LEFT",
        "RIGHT_SIGNAL": "7_TURN_RIGHT",
        "WORK_REAR": "13_WORK_BACK",
        "BEACON": "16_BEACON",
        "DRL": "5_DRL",
    }
    return legacy_map.get(light_id, light_id)


def _get_beacon_preview_mode_from_material(mat: bpy.types.Material) -> str:
    """Return the per-material beacon preview mode.

    - BLINKING: emission is gated by the beacon blink phase.
    - ROTATING: solid emission; object rotation is handled by the beacon rotation preview.

    Backward compatible: if the material has no property, defaults to BLINKING.
    """
    if not mat:
        return "BLINKING"

    # Preferred: real EnumProperty on bpy.types.Material
    try:
        v = getattr(mat, "i3d_beacon_preview_mode", None)
        if isinstance(v, str) and v in {"BLINKING", "ROTATING"}:
            return v
    except Exception:
        pass

    # Fallback: custom property (in case an older build stored it that way)
    try:
        v2 = mat.get("i3d_beacon_preview_mode")
        if isinstance(v2, str) and v2 in {"BLINKING", "ROTATING"}:
            return v2
    except Exception:
        pass

    return "BLINKING"


def _expected_tile_for_light_id(light_id: str):
    return UV_PRESET_TO_TILE.get(light_id)


def _bitmask_is_turn_signal(bitmask) -> bool:
    """Accepts string OR float-array IDProperty for turn-signal bitmask."""
    if bitmask is None:
        return False

    # Exporter wants string; allow either for backwards compatibility.
    if isinstance(bitmask, str):
        # Accept "20480.0 0.0 0.0 0.0" (spaces/commas)
        parts = bitmask.replace(",", " ").split()
        if not parts:
            return False
        try:
            return float(parts[0]) == float(TURN_SIGNAL_LIGHTTYPE_BITMASK)
        except Exception:
            return False

    # IDPropertyArray / list / tuple
    try:
        if len(bitmask) >= 1 and float(bitmask[0]) == float(TURN_SIGNAL_LIGHTTYPE_BITMASK):
            return True
    except Exception:
        pass
    return False


def _iter_slot_polys(mesh: bpy.types.Mesh, slot_index: int):
    for p in mesh.polygons:
        if p.material_index == slot_index:
            yield p


def _slot_uv_tiles(mesh: bpy.types.Mesh, slot_index: int, uv_layer_name: str):
    """Return a set of (tile_x, tile_y) used by this material slot in the given UV layer."""
    tiles = set()
    uv_layer = mesh.uv_layers.get(uv_layer_name)
    if not uv_layer:
        return tiles

    data = uv_layer.data
    if not data or len(data) == 0:
        return tiles

    for p in _iter_slot_polys(mesh, slot_index):
        for li in p.loop_indices:
            if li >= len(data):
                continue
            uv = data[li].uv
            tiles.add((math.floor(uv.x), math.floor(uv.y)))
    return tiles


def _slot_uv_all_in_tile(mesh: bpy.types.Mesh, slot_index: int, uv_layer_name: str, tile_xy, eps: float = 1e-6):
    """
    Strict check:
      Return True only if ALL UVs for ALL polys using this material slot are fully inside the expected UDIM tile.
    """
    uv_layer = mesh.uv_layers.get(uv_layer_name)
    if not uv_layer:
        return False

    data = uv_layer.data
    if not data or len(data) == 0:
        return False

    tx, ty = tile_xy
    u_min = tx - eps
    u_max = tx + 1.0 + eps
    v_min = ty - eps
    v_max = ty + 1.0 + eps

    any_loops = False
    for p in _iter_slot_polys(mesh, slot_index):
        for li in p.loop_indices:
            if li >= len(data):
                return False
            any_loops = True
            uv = data[li].uv
            if uv.x < u_min or uv.x > u_max or uv.y < v_min or uv.y > v_max:
                return False
    return any_loops


def _slot_secondary_uv_ok(mesh: bpy.types.Mesh, slot_index: int, uv_layer_name: str, eps: float = 1e-6):
    """
    Strict check:
      Secondary UV must be normalized to tile (0,0) => 0..1 UV range.
    """
    uv_layer = mesh.uv_layers.get(uv_layer_name)
    if not uv_layer:
        return False

    data = uv_layer.data
    if not data or len(data) == 0:
        return False

    any_loops = False
    for p in _iter_slot_polys(mesh, slot_index):
        for li in p.loop_indices:
            if li >= len(data):
                return False
            any_loops = True
            uv = data[li].uv
            if uv.x < -eps or uv.x > 1.0 + eps or uv.y < -eps or uv.y > 1.0 + eps:
                return False
    return any_loops


def _validate_light_setup(context, obj: bpy.types.Object, slot_index: int, mat: bpy.types.Material, light_id: str):
    """Failsafe validation so Blender tests reflect what will actually work in GIANTS Editor.

    GIANTS staticLight UV expectation:
      - UV0 (index 0) stays in tile (0,0) within 0..1 (LightIntensity reads this).
      - UV1 (index 1) is 'UVMap2' and must be moved into the expected UDIM function tile for the light type.

    Returns:
      (ok: bool, errors: list[str])
    """
    errors = []

    if not obj or obj.type != "MESH" or not mat:
        return False, ["No mesh/material"]

    mesh = obj.data

    # Keep mesh data in sync for validation (UV edits can live only in the edit-mesh until flushed)
    try:
        obj.update_from_editmode()
    except Exception:
        pass
    try:
        mesh.update()
    except Exception:
        pass

    # Required exporter props
    if mat.get("customShader") != REQUIRED_CUSTOM_SHADER:
        errors.append('Missing/incorrect customShader ($data/shaders/vehicleShader.xml)')
    if mat.get("customShaderVariation") != REQUIRED_VARIATION:
        errors.append("Missing/incorrect customShaderVariation (staticLight)")
    if mat.get("shadingRate") != REQUIRED_SHADING_RATE:
        errors.append("Missing/incorrect shadingRate (1x1)")

    # LightIntensity custom texture
    tex_val = mat.get("customTexture_lightsIntensity")
    if not tex_val:
        errors.append(f"Missing customTexture_lightsIntensity on '{mat.name}' (LightIntensity.dds required)")
    else:
        
        # LightIntensity path portability is not required during authoring/testing (export will break on other PCs)# Best-effort file existence + power-of-two check (supports relative paths)
        tex_str = str(tex_val).strip()
        if tex_str.startswith("$data/"):
            # Base game reference (GIANTS). Skip on-disk validation here.
            pass
        else:
            found_path = _resolve_intensity_path(context, tex_val)
            if not found_path or not os.path.exists(found_path):
                errors.append(f"customTexture_lightsIntensity file not found: '{tex_val}' (resolved: '{found_path or 'N/A'}')")
            else:
                info = _read_dds_info(found_path)
                if info:
                    w, h = info.get('width'), info.get('height')
                    if not _is_power_of_two(w) or not _is_power_of_two(h):
                        errors.append(f"LightIntensity DDS must be power-of-two (found {w}x{h})")

    # Turn signal bitmask required in GE for correct behavior
    if light_id in {"6_TURN_LEFT", "7_TURN_RIGHT"}:
        bitmask = mat.get("customParameter_lightTypeBitMask")
        if not _bitmask_is_turn_signal(bitmask):
            errors.append('Missing/incorrect customParameter_lightTypeBitMask ("20480.0 0.0 0.0 0.0")')

    # UV layers must exist
    if not mesh.uv_layers or len(mesh.uv_layers) == 0:
        errors.append("UV0 missing (no UV layers exist)")
        return False, errors

    uv0_name = mesh.uv_layers[0].name

    # UV0 must be inside tile (0,0)
    if not _slot_uv_all_in_tile(mesh, slot_index, uv0_name, (0, 0), eps=1e-5):
        errors.append("UV0 not fully inside tile (0,0) (0..1 required for LightIntensity)")

    # UV1 must be UVMap2 at index 1 and inside expected function tile
    expected_tile = _expected_tile_for_light_id(light_id)
    if expected_tile is None:
        errors.append("Unknown light type (no expected UDIM tile mapping)")
    else:
        if len(mesh.uv_layers) < 2:
            errors.append("UV1 missing (need second UV layer 'UVMap2')")
        else:
            uv1 = mesh.uv_layers[1]
            if uv1.name != SECONDARY_UV_NAME:
                errors.append(f"UV1 must be '{SECONDARY_UV_NAME}' at index 1 (found '{uv1.name}')")
            # Validate expected tile on UVMap2 regardless of name mismatch (best effort)
            uv1_name = uv1.name
            if not _slot_uv_all_in_tile(mesh, slot_index, uv1_name, expected_tile, eps=1e-5):
                errors.append(f"UV1 ({uv1_name}) not fully inside required UDIM tile {expected_tile}")

    return (len(errors) == 0), errors


# ----------------------------
# Scene Properties (collapse + testing)
# ----------------------------





def _get_active_validation_cached(context, obj, slot_index, mat, light_id):
    """Cache expensive validation work to keep UI responsive."""
    try:
        now = time.time()
        key = (
            int(getattr(obj, "as_pointer", lambda: 0)()),
            int(getattr(obj.data, "as_pointer", lambda: 0)()) if getattr(obj, "data", None) else 0,
            int(slot_index),
            int(getattr(mat, "as_pointer", lambda: 0)()),
            str(light_id or ""),
            int(len(getattr(obj.data, "polygons", []))) if getattr(obj, "data", None) else 0,
            int(len(getattr(obj.data, "uv_layers", []))) if getattr(obj, "data", None) else 0,
        )
    except Exception:
        now = time.time()
        key = (obj.name, slot_index, getattr(mat, "name", ""), str(light_id or ""))

    if (_UI_VALIDATION_CACHE.get('key') == key) and (now - float(_UI_VALIDATION_CACHE.get('t') or 0.0) < _UI_VALIDATION_TTL):
        data = _UI_VALIDATION_CACHE.get('data')
        if data is not None:
            return data

    # Recompute
    mesh = obj.data
    uv0_name = mesh.uv_layers[0].name if mesh.uv_layers else "<missing>"
    expected_tile = _expected_tile_for_light_id(light_id)

    uv0_tiles = set()
    uv1_tiles = set()
    uv1_name = "<missing>"
    if mesh.uv_layers:
        uv0_tiles = _slot_uv_tiles(mesh, slot_index, uv0_name)
        if len(mesh.uv_layers) > 1:
            uv1_name = mesh.uv_layers[1].name
            uv1_tiles = _slot_uv_tiles(mesh, slot_index, uv1_name)

    ok, errors = _validate_light_setup(context, obj, slot_index, mat, light_id)
    bitmask = mat.get('customParameter_lightTypeBitMask')

    data = (uv0_name, expected_tile, uv0_tiles, uv1_name, uv1_tiles, bitmask, ok, errors)
    _UI_VALIDATION_CACHE['key'] = key
    _UI_VALIDATION_CACHE['t'] = now
    _UI_VALIDATION_CACHE['data'] = data
    return data



def _build_active_failsafe_report(context) -> str:
    """Return a full multi-line GIANTS failsafe report for the active object/material."""
    try:
        obj = getattr(context, "active_object", None)
        if not obj or obj.type != "MESH" or not getattr(obj, "active_material", None):
            return "Select a mesh + its light material to see validation.\n"

        mat = obj.active_material
        slot_index = int(getattr(obj, "active_material_index", 0))
        light_id = _resolve_light_id_from_material(mat) or "<missing>"

        uv0_name, expected_tile, uv0_tiles, uv1_name, uv1_tiles, bitmask, ok, errors = _get_active_validation_cached(
            context, obj, slot_index, mat, light_id
        )

        lines = []
        lines.append("GIANTS Failsafe Report")
        lines.append("=====================")
        lines.append(f"Object: {obj.name}")
        lines.append(f"Material: {mat.name}")
        lines.append(f"Slot Index: {slot_index}")
        lines.append(f"Light Type: {light_id}")
        lines.append("")
        lines.append(f"Expected UDIM (UV1): {expected_tile}")
        lines.append(f"UV0 Layer (LightIntensity): {uv0_name}")
        lines.append(f"UV0 Tiles Found: {sorted(list(uv0_tiles))}")
        lines.append(f"UV1 Layer (Function Tile): {uv1_name}")
        lines.append(f"UV1 Tiles Found: {sorted(list(uv1_tiles))}")
        lines.append(f"BitMask: {bitmask}")
        lines.append("")

        tex_val = mat.get("customTexture_lightsIntensity")
        lines.append(f"customTexture_lightsIntensity (raw): {repr(tex_val)}")
        if tex_val:
            tex_str = str(tex_val).strip()
            if tex_str.startswith("$data/"):
                lines.append("customTexture_lightsIntensity is a base-game $data reference (on-disk check skipped).")
            else:
                resolved = _resolve_intensity_path(context, tex_val)
                lines.append(f"customTexture_lightsIntensity resolved: {repr(resolved)}")
                try:
                    exists = bool(resolved) and os.path.exists(resolved)
                except Exception:
                    exists = False
                lines.append(f"Resolved exists: {exists}")
        em_path = _find_emission_image_path(mat)
        if em_path:
            lines.append(f"Emission texture detected (node): {repr(em_path)}")
            lines.append("WARNING: If there is a texture plugged into the emissive shader node it will have to be deleted inside of GE before testing the lights inside of Giants Editor or in game.")

        lines.append("")

        lines.append("Validation: PASS" if ok else "Validation: FAIL")
        if errors:
            lines.append("Errors:")
            for e in errors:
                lines.append(f" - {e}")

        lines.append("")
        lines.append(f"Blend File: {bpy.data.filepath or '<unsaved>'}")
        try:
            props = getattr(context.scene, "i3d_light_tool", None) if context and getattr(context, "scene", None) else None
            out_dir = getattr(props, "li_out_dir", "") if props else ""
            lines.append(f"LightIntensity Output Folder (li_out_dir): {repr(out_dir)}")
        except Exception:
            pass
        try:
            lines.append(f"I3D Export Base Dir: {repr(_get_i3d_export_base_dir(context, None))}")
        except Exception:
            pass

        return "\n".join(lines) + "\n"
    except Exception as e:
        return f"Failed to build report: {e}\n"


class I3D_CL_OT_LightShowFailsafeReport(bpy.types.Operator):
    bl_idname = "i3d.light_show_failsafe_report"
    bl_label = "GIANTS Failsafe Report"
    bl_description = 'Show a diagnostic report for the active light setup (failsafe/validation).'
    bl_options = {"REGISTER"}

    report_text: StringProperty(name="Report", default="", options={"SKIP_SAVE"})

    def invoke(self, context, event):
        self.report_text = _build_active_failsafe_report(context)
        return context.window_manager.invoke_props_dialog(self, width=900)

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.operator("i3d.light_copy_failsafe_report", text="Copy to Clipboard", icon="COPYDOWN")
        layout.separator()

        box = layout.box()
        txt = self.report_text or ""
        for ln in txt.splitlines():
            if not ln.strip():
                box.separator()
            else:
                box.label(text=ln)

    def execute(self, context):
        return {"FINISHED"}


class I3D_CL_OT_LightCopyFailsafeReport(bpy.types.Operator):
    bl_idname = "i3d.light_copy_failsafe_report"
    bl_label = "Copy GIANTS Failsafe Report"
    bl_description = 'Copy the active light failsafe/validation report to the clipboard.'
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            context.window_manager.clipboard = _build_active_failsafe_report(context)
        except Exception:
            pass
        return {"FINISHED"}

# ----------------------------
# Report helpers (Inspect Scene)
# ----------------------------

def _staticlight_variation_ok(mat: bpy.types.Material) -> (bool, str):
    """Gate for Inspect Scene: return (ok, reason). Only checks customShaderVariation (fast)."""
    if not mat:
        return False, "No material"
    try:
        var = mat.get("customShaderVariation", "")
    except Exception:
        var = ""
    if not isinstance(var, str) or not var.strip():
        return False, "customShaderVariation missing"
    v = var.strip().lower()
    allowed = {"staticlight", "staticlight_vertex", "staticlight_vertex_slide"}
    # Accept common casing variants like staticLight_Vertex
    if v in allowed:
        return True, f"customShaderVariation='{var}'"
    return False, f"customShaderVariation='{var}' (not staticLight)"


def _inspect_report_dir() -> str:
    """Return a stable report directory under Blender CONFIG."""
    base = bpy.utils.user_resource('CONFIG')
    if not base:
        base = os.path.expanduser("~")
    out_dir = os.path.join(base, "io_export_i3d_reworked", "reports")
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:
        pass
    return out_dir


def _write_inspect_report_files(rows: list) -> (str, str):
    """Write CSV + HTML to report dir. Returns (csv_path, html_path)."""
    out_dir = _inspect_report_dir()
    ts = time.strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(out_dir, f"inspect_scene_report_{ts}.csv")
    html_path = os.path.join(out_dir, f"inspect_scene_report_{ts}.html")

    headers = [
        "Mesh",
        "Material",
        "SlotIndex",
        "IsLightPass",
        "EligibleStaticLightVariation",
        "InferredLightId",
        "UVMap2TilesFound",
        "Reason",
        "Actions",
        "Warnings",
    ]

    # CSV
    try:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(headers)
            for r in rows:
                w.writerow([
                    r.get("mesh", ""),
                    r.get("material", ""),
                    r.get("slot", ""),
                    r.get("pass", ""),
                    r.get("eligible", ""),
                    r.get("inferred", ""),
                    r.get("tiles", ""),
                    r.get("reason", ""),
                    r.get("actions", ""),
                    r.get("warnings", ""),
                ])
    except Exception:
        pass

    # HTML table (opens in browser like a spreadsheet)
    try:
        def esc(x):
            return _html.escape(str(x) if x is not None else "")
        css = """
        <style>
        body{font-family:system-ui,Segoe UI,Arial,sans-serif;background:#111;color:#eee;margin:16px;}
        table{border-collapse:collapse;width:100%;}
        th,td{border:1px solid #333;padding:6px 8px;font-size:13px;vertical-align:top;}
        th{background:#222;}
        tr:nth-child(even){background:#151515;}
        .pass{color:#7CFC00;font-weight:700;}
        .fail{color:#FF6A6A;font-weight:700;}
        </style>
        """
        html_rows = []
        html_rows.append("<tr>" + "".join(f"<th>{esc(h)}</th>" for h in headers) + "</tr>")
        for r in rows:
            is_pass = bool(r.get("pass", False))
            cls = "pass" if is_pass else "fail"
            html_rows.append("<tr>" + "".join([
                f"<td>{esc(r.get('mesh',''))}</td>",
                f"<td>{esc(r.get('material',''))}</td>",
                f"<td>{esc(r.get('slot',''))}</td>",
                f"<td class='{cls}'>{'PASS' if is_pass else 'FAIL'}</td>",
                f"<td>{esc(r.get('eligible',''))}</td>",
                f"<td>{esc(r.get('inferred',''))}</td>",
                f"<td>{esc(r.get('tiles',''))}</td>",
                f"<td>{esc(r.get('reason',''))}</td>",
                f"<td>{esc(r.get('actions',''))}</td>",
                f"<td>{esc(r.get('warnings',''))}</td>",
            ]) + "</tr>")
        html_doc = "<html><head><meta charset='utf-8'><title>Inspect Scene Report</title>" + css + "</head><body>"
        html_doc += f"<h2>Inspect Scene Report</h2><p>Generated: {esc(ts)}</p>"
        html_doc += "<table>" + "\n".join(html_rows) + "</table></body></html>"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_doc)
    except Exception:
        pass

    return csv_path, html_path


def _build_inspect_report_text(rows: list) -> str:
    """Human-readable multiline report for popup + clipboard."""
    out = []
    for r in rows:
        out.append(f"Mesh: {r.get('mesh','')}")
        out.append(f"  Material: {r.get('material','')}")
        out.append(f"  Is Light?: {'PASS' if r.get('pass') else 'FAIL'}")
        if r.get("eligible"):
            out.append(f"  Eligible: {r.get('eligible')}")
        if r.get("inferred"):
            out.append(f"  Inferred: {r.get('inferred')}")
        if r.get("tiles"):
            out.append(f"  UVMap2 Tiles: {r.get('tiles')}")
        if r.get("reason"):
            out.append(f"  Reason: {r.get('reason')}")
        if r.get("actions"):
            out.append(f"  Actions: {r.get('actions')}")
        if r.get("warnings"):
            out.append(f"  Warnings: {r.get('warnings')}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# ----------------------------
# Failsafe helper: select offending faces
# ----------------------------

class I3D_CL_OT_LightSelectOffendingFaces(bpy.types.Operator):
    bl_idname = "i3d.light_select_offending_faces"
    bl_label = "Select Offending Faces"
    bl_description = 'Select faces/materials that failed validation for the active light setup.'
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = getattr(context, "active_object", None)
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "No active mesh object.")
            return {"CANCELLED"}

        mesh = obj.data
        slot_index = getattr(obj, "active_material_index", 0)
        mat = obj.active_material

        light_id = _resolve_light_id_from_material(mat) or ""
        expected_tile = UV_PRESET_TO_TILE.get(light_id)
        if not expected_tile:
            self.report({"ERROR"}, "Active material has no valid i3d_light_type (cannot infer expected UVMap2 tile).")
            return {"CANCELLED"}

        # UV0 and UVMap2
        uv0_name = mesh.uv_layers[0].name if mesh.uv_layers else "UVMap"
        uv2_name = "UVMap2"
        if mesh.uv_layers.get("UVMap2"):
            uv2_name = "UVMap2"
        elif len(mesh.uv_layers) >= 2:
            uv2_name = mesh.uv_layers[1].name

        # Enter edit mode
        prev_mode = obj.mode
        try:
            if obj.mode != "EDIT":
                bpy.ops.object.mode_set(mode="EDIT")
        except Exception:
            pass

        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()

        uv0_layer = bm.loops.layers.uv.get(uv0_name)
        uv2_layer = bm.loops.layers.uv.get(uv2_name)
        if not uv0_layer or not uv2_layer:
            self.report({"ERROR"}, "Missing UV layers required for selection.")
            return {"CANCELLED"}

        tx, ty = expected_tile
        eps = 1e-6
        u0_min, u0_max = -eps, 1.0 + eps
        v0_min, v0_max = -eps, 1.0 + eps

        u2_min, u2_max = tx - eps, tx + 1.0 + eps
        v2_min, v2_max = ty - eps, ty + 1.0 + eps

        # Clear selection then select offending
        for f in bm.faces:
            f.select_set(False)

        bad = 0
        for f in bm.faces:
            if f.material_index != slot_index:
                continue
            bad_face = False
            for loop in f.loops:
                uv0 = loop[uv0_layer].uv
                uv2 = loop[uv2_layer].uv
                if (uv0.x < u0_min or uv0.x > u0_max or uv0.y < v0_min or uv0.y > v0_max):
                    bad_face = True
                    break
                if (uv2.x < u2_min or uv2.x > u2_max or uv2.y < v2_min or uv2.y > v2_max):
                    bad_face = True
                    break
            if bad_face:
                f.select_set(True)
                bad += 1

        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        if bad == 0:
            self.report({"INFO"}, "No offending faces found for the active material slot.")
        else:
            self.report({"WARNING"}, f"Selected {bad} offending faces in active material slot.")

        # Keep user in Edit Mode so the selection is visible.

        return {"FINISHED"}


# ----------------------------
# Inspect Report UI operators
# ----------------------------

class I3D_CL_OT_LightShowInspectReport(bpy.types.Operator):
    bl_idname = "i3d.light_show_inspect_report"
    bl_label = "Inspect Scene Report"
    bl_description = 'Show the scene inspection report for manually built static lights.'
    bl_options = {"REGISTER"}

    report_text: bpy.props.StringProperty(name="Report", default="", options={"SKIP_SAVE"})

    def invoke(self, context, event):
        props = getattr(context.scene, "i3d_light_tool", None)
        self.report_text = getattr(props, "inspect_last_report", "") if props else ""
        return context.window_manager.invoke_props_dialog(self, width=980)

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        # Order B: View Report as Spreadsheet, then Copy
        row.operator("i3d.light_open_inspect_report", text="View Report as Spreadsheet", icon="WORLD")
        row.operator("i3d.light_copy_inspect_report", text="Copy to Clipboard", icon="COPYDOWN")
        layout.separator()
        box = layout.box()
        txt = self.report_text or ""
        for ln in txt.splitlines():
            if not ln.strip():
                box.separator()
            else:
                box.label(text=ln)

    def execute(self, context):
        return {"FINISHED"}


class I3D_CL_OT_LightCopyInspectReport(bpy.types.Operator):
    bl_idname = "i3d.light_copy_inspect_report"
    bl_label = "Copy Inspect Report"
    bl_description = 'Copy the scene inspection report to the clipboard.'

    def execute(self, context):
        props = getattr(context.scene, "i3d_light_tool", None)
        txt = getattr(props, "inspect_last_report", "") if props else ""
        try:
            context.window_manager.clipboard = txt or ""
        except Exception:
            pass
        self.report({"INFO"}, "Inspect report copied to clipboard.")
        return {"FINISHED"}


class I3D_CL_OT_LightOpenInspectReport(bpy.types.Operator):
    bl_idname = "i3d.light_open_inspect_report"
    bl_label = "Open Inspect Report (Spreadsheet)"
    bl_description = 'Open the scene inspection report file in your default text editor.'

    def execute(self, context):
        props = getattr(context.scene, "i3d_light_tool", None)
        html_path = getattr(props, "inspect_last_report_html", "") if props else ""
        if not html_path:
            self.report({"ERROR"}, "No HTML report found. Run Inspect Scene first.")
            return {"CANCELLED"}
        try:
            if os.path.exists(html_path):
                webbrowser.open("file://" + os.path.abspath(html_path))
                self.report({"INFO"}, "Opened inspect report in browser.")
                return {"FINISHED"}
        except Exception:
            pass
        self.report({"ERROR"}, "Failed to open inspect report.")
        return {"CANCELLED"}
def _on_light_role_changed(self, context):
    """Keep the active material's stored i3d_light_type in sync with the dropdown.
    This prevents confusing test results if the user changes the dropdown but doesn't click 'Make My Light' yet.
    Does NOT move UVs or paint vertex colors (those still require 'Make My Light').
    """
    try:
        if not getattr(self, "auto_sync_light_type", True):
            return
        obj = context.active_object
        if not obj or obj.type != "MESH":
            return
        mat = obj.active_material
        if not mat:
            return
        mat["i3d_light_type"] = self.light_role
        mat["i3d_light_role"] = self.light_role

        # Ensure required exporter props exist (safe, doesn't affect other tools)
        _write_required_exporter_props(mat)

        # Ensure turn-signal bitmask if needed
        if self.light_role in {"6_TURN_LEFT", "7_TURN_RIGHT"}:
            _write_turn_signal_bitmask(mat)
    except Exception:
        # Never break UI due to sync
        return

# ----------------------------
# MultiFunction Light: UI + Data
# ----------------------------

def _mf_on_light_type_changed(self, context):
    """Auto-fill the row color from the selected light type unless the user enabled custom color."""
    try:
        if getattr(self, "use_custom_color", False):
            return
        rgba = LIGHT_TYPE_TO_DEFAULT_VCOL.get(getattr(self, "light_type", ""), (1.0, 1.0, 1.0, 1.0))
        # Ensure 4-tuple
        self.color = (float(rgba[0]), float(rgba[1]), float(rgba[2]), float(rgba[3]))
    except Exception:
        return


class I3D_MF_MaterialRow(bpy.types.PropertyGroup):
    material: PointerProperty(type=bpy.types.Material)
    light_type: EnumProperty(
        name="Light Type",
        items=MF_LIGHTTYPE_ITEMS,
        default=MF_EXCLUDE_ID,
        update=_mf_on_light_type_changed,
    )
    use_custom_color: BoolProperty(
        name="Custom Color",
        default=False,
        description="If enabled, the row color will not auto-sync when changing Light Type.",
    )
    color: FloatVectorProperty(
        name="Light Color",
        subtype="COLOR",
        size=4,
        min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
    )


class I3D_UL_MF_Materials(bpy.types.UIList):
    """Per-material MultiFunction configuration list."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)

        mat = getattr(item, "material", None)
        mat_name = mat.name if mat else "<missing material>"
        row.label(text=mat_name, icon="MATERIAL")

        row.prop(item, "light_type", text="")
        sub = row.row(align=True)
        sub.prop(item, "use_custom_color", text="", icon="LOCKED" if getattr(item, "use_custom_color", False) else "UNLOCKED")
        sub.prop(item, "color", text="")


class I3D_LightToolProps(bpy.types.PropertyGroup):
    show_light_setup: BoolProperty(
        name="Vehicle Light Setup Tool",
        default=False,
        description="Show/Hide Vehicle Light Setup Tool",
    )

    show_light_testing: BoolProperty(
        name="Testing Light System",
        default=False,
        description="Show/Hide Testing Light System",
    )

    multi_function_light: EnumProperty(
        name="Multi Function Light?",
        items=[("NO", "No", ""), ("YES", "Yes", "")],
        default="NO",
    )

    # MultiFunction configuration
    mf_commit_scope: EnumProperty(
        name="Commit Scope",
        items=[
            ("SELECTED", "Selected Meshes", ""),
            ("ACTIVE", "Active Mesh Only", ""),
        ],
        default="SELECTED",
        description="Which meshes are affected by 'Commit and make MultiFunction Light'",
    )


    # UV workflow controls (Build48)
    do_not_unwrap_uvs: BoolProperty(
        name="Do Not Unwrap UVs",
        default=False,
        description="If enabled: NEVER run Smart UV Project (unwrap). UVMap2 will be created if missing and shifted to the selected light UDIM tile(s).",
    )

    pack_existing_uvs: BoolProperty(
        name="Pack existing UVs (no unwrap)",
        default=False,
        description="Only when Do Not Unwrap UVs is enabled: pack existing UV0 islands (move/rotate/scale only) so they fit in one 0..1 tile.",
    )

    pack_island_bleed: FloatProperty(
        name="Bleed Between Islands",
        default=0.06,
        min=0.0,
        max=0.50,
        description="Spacing between islands when packing existing UVs (NOT the border margin).",
    )

    paint_vertex_colors: BoolProperty(
        name="Paint Vertex Colors",
        default=True,
        description="If disabled, this tool will not touch vertex colors.",
    )


    mf_items: CollectionProperty(type=I3D_MF_MaterialRow)
    mf_active_index: IntProperty(default=0)

    auto_sync_light_type: BoolProperty(
        name="Auto-Sync Light Type",
        description="Automatically sync the Light Type dropdown into the active material's i3d_light_type metadata (tests use this). Does not move UVs or paint.",
        default=True,
    )

    light_role: EnumProperty(
        name="Light Type",
        items=UV_PRESET_ITEMS,
        default="0_DEFAULT_LIGHT",
        update=_on_light_role_changed,
        description="Light type (also controls the UV UDIM tile used for UV0 / UVMap1)",
    )

    beacon_mode: EnumProperty(
        name="Beacon Type",
        items=[("BLINKING", "Blinking", ""), ("ROTATING", "Rotating", "")],
        default="BLINKING",
    )

    override_color: EnumProperty(
        name="Override Normal Color?",
        items=[("NO", "No", ""), ("YES", "Yes", "")],
        default="NO",
    )

    override_rgba: FloatVectorProperty(
        name="Light Color",
        subtype="COLOR",
        size=4,
        min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
    )

    # Testing controls
    test_intensity: FloatProperty(
        name="Test Intensity",
        default=25.0,
        min=0.0,
        max=250.0,
        description="Emission strength used for preview tests",
    )

    blinker_hz: FloatProperty(
        name="Blink Rate (Hz)",
        default=1.0,
        min=0.1,
        max=10.0,
        description="Turn signal / hazard blink frequency",
    )

    beacon_speed: FloatProperty(
        name="Beacon Speed",
        default=1.0,
        min=0.1,
        max=10.0,
        description="Blinking beacon speed (higher = faster)",
    )

    beacon_rpm: FloatProperty(
        name="Beacon RPM",
        default=200.0,
        min=1.0,
        max=2000.0,
        description="Rotating beacon RPM (preview only)",
    )


    # Testing performance controls (reduces lag while testing)
    revalidate_interval: FloatProperty(
        name="Revalidate Interval (sec)",
        default=1.0,
        min=0.10,
        max=10.0,
        description="How often the test system re-checks UVs/material props. Higher = less lag",
    )

    # LightIntensity atlas export (staticLight requirement)
    li_tile_res: IntProperty(
        name="Tile Resolution",
        default=256,
        min=32,
        max=2048,
        description="Max resolution for LightIntensity generation. Output will be a best-fit power-of-two rectangle.",
    )

    li_mode: EnumProperty(
        name="Output Mode",
        items=[
            ("COLOR", "Vertex Color", "Write vertex color into the atlas"),
            ("LUMA", "Luminance (grayscale)", "Write grayscale intensity into RGB"),
        ],
        default="COLOR",
    )

    li_out_dir: StringProperty(
        name="Output Folder",
        subtype="DIR_PATH",
        default="",
        description="Folder to save LightIntensity output (DDS required, PNG optional)",
    )

    li_filename: StringProperty(
        name="Filename",
        default="",
        description="Optional: output base filename (no extension). Leave blank to auto-name.",
    )


    li_save_png: BoolProperty(
        name="Save PNG (debug)",
        default=True,
        description="Also save a PNG copy for debugging. A DDS is always generated for export.",
    )
    test_scope: EnumProperty(
        name="Test Scope",
        items=[
            ("VIEW_LAYER", "Visible Scene", "Affect all visible objects in the current view layer"),
            ("SCENE", "All Scene", "Affect all objects in the scene (including hidden)"),
            ("SELECTED", "Selected Only", "Only affect currently selected objects"),
        ],
        default="VIEW_LAYER",
        description="Which objects are affected by the Testing Light System",
    )

    test_running: BoolProperty(default=False)
    test_mode: StringProperty(default="")  # e.g. "LEFT_SIGNAL"

    test_multi_enable: BoolProperty(
        name="Multi-toggle Tests",
        default=False,
        description="Allow multiple light tests at once (combine modes).",
    )
    # Comma-separated list of active test mode keys (e.g. DEFAULT,HIGHBEAM,LEFT_SIGNAL)
    test_multi_modes: StringProperty(default="")


# ----------------------------
# Operators
# ----------------------------


    inspect_utilities_open: BoolProperty(
        name="Inspect Scene for Manually Built Lights",
        default=True,
        description="Show/hide the Inspect Scene utilities section",
    )

    inspect_dry_run: BoolProperty(
        name="Scan and list but don't implement",
        default=False,
        description="Inspect Scene: build the report but do not write/modify any material properties",
    )

    inspect_last_report: StringProperty(
        name="Last Inspect Report",
        default="",
        options={"SKIP_SAVE"},
    )

    inspect_last_report_csv: StringProperty(
        name="Last Inspect Report CSV",
        default="",
    )

    inspect_last_report_html: StringProperty(
        name="Last Inspect Report HTML",
        default="",
    )

class I3D_MF_OT_RefreshMaterials(bpy.types.Operator):
    bl_idname = "i3d.mf_refresh_materials"
    bl_label = "Refresh Materials"
    bl_description = 'Refresh the material list used by the MultiFunction Light setup UI.'
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.i3d_light_tool

        def _scope_objects():
            if props.mf_commit_scope == "ACTIVE":
                o = context.active_object
                return [o] if o and o.type == "MESH" else []
            return [o for o in context.selected_objects if o and o.type == "MESH"]

        objs = _scope_objects()
        if not objs:
            self.report({"ERROR"}, "No mesh objects found for the chosen Commit Scope.")
            return {"CANCELLED"}

        mats = []
        seen = set()
        for obj in objs:
            for slot in obj.material_slots:
                mat = slot.material
                if not mat:
                    continue
                # Use ID pointer for uniqueness
                key = mat.as_pointer()
                if key in seen:
                    continue
                seen.add(key)
                mats.append(mat)

        # Preserve existing settings
        old = {}
        for it in props.mf_items:
            mat = getattr(it, "material", None)
            if not mat:
                continue
            old[mat.as_pointer()] = {
                "light_type": getattr(it, "light_type", MF_EXCLUDE_ID),
                "use_custom_color": bool(getattr(it, "use_custom_color", False)),
                "color": tuple(getattr(it, "color", (1.0, 1.0, 1.0, 1.0))),
            }

        props.mf_items.clear()

        for mat in mats:
            it = props.mf_items.add()
            it.material = mat

            prev = old.get(mat.as_pointer())
            if prev:
                it.use_custom_color = bool(prev.get("use_custom_color", False))
                try:
                    it.light_type = prev.get("light_type", MF_EXCLUDE_ID)
                except Exception:
                    it.light_type = MF_EXCLUDE_ID
                try:
                    it.color = prev.get("color", (1.0, 1.0, 1.0, 1.0))
                except Exception:
                    pass
            else:
                it.light_type = MF_EXCLUDE_ID
                it.use_custom_color = False
                it.color = (1.0, 1.0, 1.0, 1.0)

        props.mf_active_index = min(max(0, props.mf_active_index), max(0, len(props.mf_items) - 1))

        self.report({"INFO"}, f"MultiFunction material list refreshed: {len(props.mf_items)} material(s).")
        return {"FINISHED"}


def _run_smart_uv_project_multifunction(context, obj: bpy.types.Object):
    """Smart UV Project for MultiFunction commit (island margin 0.06)."""
    override = _get_view3d_uv_override(context, obj)

    ts = getattr(context.scene, "tool_settings", None)
    prev_sync = None
    if ts is not None and hasattr(ts, "use_uv_select_sync"):
        prev_sync = ts.use_uv_select_sync
        ts.use_uv_select_sync = True

    angle_rad = math.radians(66.0)

    kw_sets = [
        dict(
            angle_limit=angle_rad,
            margin_method="SCALED",
            rotation_method="AXIS_ALIGNED_VERTICAL",
            island_margin=0.06,
            area_weight=0.0,
            correct_aspect=True,
            scale_to_bounds=False,
        ),
        dict(
            angle_limit=angle_rad,
            margin_method="SCALED",
            rotation_method="AXIS_ALIGNED",
            island_margin=0.06,
            area_weight=0.0,
            correct_aspect=True,
            scale_to_bounds=False,
        ),
        dict(angle_limit=angle_rad, island_margin=0.06),
    ]

    try:
        with context.temp_override(**override):
            try:
                bpy.ops.mesh.select_mode(type="FACE")
            except Exception:
                pass

            for kws in kw_sets:
                try:
                    res = bpy.ops.uv.smart_project(**kws)
                    if isinstance(res, set) and "FINISHED" in res:
                        return True
                except Exception:
                    continue
            return False
    finally:
        if ts is not None and prev_sync is not None:
            ts.use_uv_select_sync = prev_sync


def _get_image_editor_uv_override(context, obj: bpy.types.Object):
    window = getattr(context, "window", None)
    screen = getattr(context, "screen", None) or (window.screen if window else None)

    if not screen:
        return _get_view3d_uv_override(context, obj)

    for area in screen.areas:
        if area.type not in {"IMAGE_EDITOR", "UV"}:
            continue
        region = None
        for r in area.regions:
            if r.type == "WINDOW":
                region = r
                break
        if not region:
            continue
        space = area.spaces.active if area.spaces else None
        override = {
            "window": window,
            "screen": screen,
            "area": area,
            "region": region,
            "scene": context.scene,
            "active_object": obj,
            "object": obj,
            "edit_object": obj,
            "selected_objects": [o for o in context.selected_objects if o and o.type == "MESH"],
        }
        if space is not None:
            override["space_data"] = space
        return override

    return _get_view3d_uv_override(context, obj)


def _run_pack_islands_multifunction(context, obj: bpy.types.Object, margin=0.14):
    """Pack islands after unwrap. Attempts IMAGE_EDITOR override first, then VIEW_3D."""
    overrides = [
        _get_image_editor_uv_override(context, obj),
        _get_view3d_uv_override(context, obj),
    ]
    for ov in overrides:
        try:
            with context.temp_override(**ov):
                res = bpy.ops.uv.pack_islands(margin=float(margin))
                if isinstance(res, set) and "FINISHED" in res:
                    return True
        except Exception:
            continue
    # Last attempt: no override
    try:
        res = bpy.ops.uv.pack_islands(margin=float(margin))
        if isinstance(res, set) and "FINISHED" in res:
            return True
    except Exception:
        pass
    return False


def _mesh_has_secondary_uv(mesh: bpy.types.Mesh) -> bool:
    """True if the mesh already has a secondary UV layer (UVMap2 / index 1).
    IMPORTANT: In Do Not Unwrap mode we must NOT create or rename UV layers.
    """
    try:
        if mesh is None or not getattr(mesh, "uv_layers", None):
            return False
        # Prefer explicit UVMap2 naming, but accept any 2nd UV layer (index 1).
        if mesh.uv_layers.get("UVMap2") is not None:
            return True
        return len(mesh.uv_layers) >= 2
    except Exception:
        return False


def _mesh_has_uv0(mesh: bpy.types.Mesh) -> bool:
    try:
        return bool(mesh and getattr(mesh, "uv_layers", None) and len(mesh.uv_layers) >= 1)
    except Exception:
        return False


def _fit_selected_uv0_to_border_in_editmode(objs, border=0.14):
    """Scale/translate selected UV0 loops so the selection fits inside [border..1-border] (U and V).
    - Only touches selected faces/loops.
    - Works in single-object OR multi-object edit mode.
    - Uses a UNIFORM scale and centers within the available area.
    """
    if not objs:
        return False

    target_min = float(border)
    target_max = 1.0 - float(border)
    avail = max(1e-9, (target_max - target_min))

    # Gather global bounds across all selected UVs
    min_u, min_v = 1e9, 1e9
    max_u, max_v = -1e9, -1e9
    any_uv = False

    for obj in objs:
        if not obj or obj.type != "MESH":
            continue
        mesh = obj.data
        if not _mesh_has_uv0(mesh):
            continue

        try:
            uv0_name = mesh.uv_layers[0].name
        except Exception:
            continue

        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.get(uv0_name)
        if not uv_layer:
            continue

        for f in bm.faces:
            if not f.select:
                continue
            for loop in f.loops:
                uv = loop[uv_layer].uv
                u = float(uv.x)
                v = float(uv.y)
                min_u = min(min_u, u)
                min_v = min(min_v, v)
                max_u = max(max_u, u)
                max_v = max(max_v, v)
                any_uv = True

    if not any_uv or max_u < min_u or max_v < min_v:
        return False

    du = max(1e-9, (max_u - min_u))
    dv = max(1e-9, (max_v - min_v))

    # Uniform scale so both axes fit within the available area
    s = min(avail / du, avail / dv)

    new_du = du * s
    new_dv = dv * s

    # Center within the border box
    off_u = target_min + (avail - new_du) * 0.5
    off_v = target_min + (avail - new_dv) * 0.5

    eps = 1e-6

    # Apply transform only to selected UVs
    for obj in objs:
        if not obj or obj.type != "MESH":
            continue
        mesh = obj.data
        if not _mesh_has_uv0(mesh):
            continue

        try:
            uv0_name = mesh.uv_layers[0].name
        except Exception:
            continue

        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.get(uv0_name)
        if not uv_layer:
            continue

        for f in bm.faces:
            if not f.select:
                continue
            for loop in f.loops:
                uv = loop[uv_layer].uv
                u = (float(uv.x) - min_u) * s + off_u
                v = (float(uv.y) - min_v) * s + off_v
                # Clamp to stay strictly inside the border area
                u = max(target_min, min(target_max - eps, u))
                v = max(target_min, min(target_max - eps, v))
                loop[uv_layer].uv = (u, v)

        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

    return True


def _pack_existing_uv0_for_active_slot(context, obj: bpy.types.Object, slot_index: int, bleed_margin: float, border=0.14):
    """Do Not Unwrap mode helper:
    - Select faces in active material slot only
    - Pack existing UV0 islands (no unwrap) using bleed_margin BETWEEN islands
    - Fit packed UVs inside [border..1-border]
    """
    if not obj or obj.type != "MESH":
        return False
    mesh = obj.data
    if not _mesh_has_uv0(mesh):
        return False

    view_layer = context.view_layer
    prev_active = view_layer.objects.active
    prev_selected = [o for o in view_layer.objects if o.select_get()]
    prev_mode = obj.mode

    face_sel_restore = None

    try:
        # Make obj active/selected for ops
        for o in prev_selected:
            o.select_set(False)
        obj.select_set(True)
        view_layer.objects.active = obj

        if obj.mode != "EDIT":
            bpy.ops.object.mode_set(mode="EDIT")

        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()

        # Save selection
        face_sel_restore = {f.index: f.select for f in bm.faces}

        # Select only slot faces
        for f in bm.faces:
            f.select_set(f.material_index == int(slot_index))
        bm.select_flush(True)
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        # Ensure UV0 active
        try:
            mesh.uv_layers.active_index = 0
            mesh.uv_layers.active = mesh.uv_layers[0]
        except Exception:
            pass

        # Pack existing islands (no unwrap)
        if not _run_pack_islands_multifunction(context, obj, margin=float(bleed_margin)):
            return False

        # Fit inside border
        if not _fit_selected_uv0_to_border_in_editmode([obj], border=float(border)):
            return False

        return True

    finally:
        # Restore face selection
        try:
            if obj.mode == "EDIT" and face_sel_restore is not None:
                bm = bmesh.from_edit_mesh(mesh)
                bm.faces.ensure_lookup_table()
                for f in bm.faces:
                    f.select_set(bool(face_sel_restore.get(f.index, False)))
                bm.select_flush(True)
                bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        except Exception:
            pass

        # Restore mode
        try:
            if prev_mode != "EDIT":
                bpy.ops.object.mode_set(mode=prev_mode)
        except Exception:
            pass

        # Restore selection/active
        try:
            for o in view_layer.objects:
                o.select_set(False)
            for o in prev_selected:
                o.select_set(True)
            view_layer.objects.active = prev_active
        except Exception:
            pass


def _paint_faces_by_material(obj: bpy.types.Object, mat_to_rgba: dict):
    """Paint all faces by their assigned material (full material coverage)."""
    if not obj or obj.type != "MESH":
        return False
    mesh = obj.data
    if not mat_to_rgba:
        return False

    # Ensure active color attribute exists
    vcol_name = _get_active_vcol_name(obj)
    attr = _ensure_color_attribute(mesh, vcol_name)
    if not attr:
        attr = _ensure_color_attribute(mesh, "Col")
        if not attr:
            return False

    # Build slot->rgba map for this object
    slot_rgba = {}
    for si, slot in enumerate(obj.material_slots):
        mat = slot.material
        if not mat:
            continue
        if mat in mat_to_rgba:
            slot_rgba[si] = mat_to_rgba[mat]

    if not slot_rgba:
        return False

    # Paint loops
    if hasattr(mesh, "color_attributes"):
        for poly in mesh.polygons:
            rgba = slot_rgba.get(poly.material_index)
            if rgba is None:
                continue
            for li in poly.loop_indices:
                try:
                    attr.data[li].color = rgba
                except Exception:
                    pass
        mesh.update()
        return True

    if hasattr(mesh, "vertex_colors"):
        vcol = mesh.vertex_colors.get(attr.name) if hasattr(attr, "name") else mesh.vertex_colors.active
        if not vcol:
            vcol = mesh.vertex_colors.new(name=vcol_name)
        for poly in mesh.polygons:
            rgba = slot_rgba.get(poly.material_index)
            if rgba is None:
                continue
            for li in poly.loop_indices:
                vcol.data[li].color = rgba
        mesh.update()
        return True

    return False


class I3D_MF_OT_CommitMultiFunction(bpy.types.Operator):
    bl_idname = "i3d.mf_commit_multifunction"
    bl_label = "Commit and make MultiFunction Light"
    bl_description = 'Commit the MultiFunction Light setup (paint faces/vertex colors based on the material table).'
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.i3d_light_tool

        # Build included materials map
        included = {}
        for row in props.mf_items:
            mat = getattr(row, "material", None)
            lt = getattr(row, "light_type", MF_EXCLUDE_ID)
            if not mat or lt == MF_EXCLUDE_ID:
                continue
            rgba = tuple(getattr(row, "color", (1.0, 1.0, 1.0, 1.0)))
            included[mat] = {"light_type": lt, "color": rgba}

        if not included:
            self.report({"ERROR"}, "No included materials. Set at least one material Light Type (not excluded).")
            return {"CANCELLED"}

        # Determine objects by scope
        if props.mf_commit_scope == "ACTIVE":
            objs = [context.active_object] if context.active_object and context.active_object.type == "MESH" else []
        else:
            objs = [o for o in context.selected_objects if o and o.type == "MESH"]

        if not objs:
            self.report({"ERROR"}, "No mesh objects found for the chosen Commit Scope.")
            return {"CANCELLED"}


        # Skip meshes that have ZERO included light materials (prevents UVMap2 bloat on excluded-only meshes)
        objs_with_included = []
        for o in objs:
            try:
                if any((slot.material in included) for slot in o.material_slots):
                    objs_with_included.append(o)
            except Exception:
                continue
        objs = objs_with_included
        if not objs:
            self.report({"ERROR"}, "No chosen meshes contain included light materials (all were excluded).")
            return {"CANCELLED"}

        view_layer = context.view_layer
        prev_active = view_layer.objects.active
        prev_selected = [o for o in view_layer.objects if o.select_get()]
        prev_mode = objs[0].mode if objs else "OBJECT"

        try:
            # Select scope objects
            for o in prev_selected:
                o.select_set(False)
            for o in objs:
                o.select_set(True)
            view_layer.objects.active = objs[0]
            # UV workflow (Build48)
            if getattr(props, "do_not_unwrap_uvs", False):
                # Do Not Unwrap: NEVER Smart UV unwrap. UVMap2 will be created if missing and shifted to UDIM function tiles.
                # Ensure UV layers exist and UVMap2 is UV1 (create if missing)
                for o in objs:
                    try:
                        if o and o.type == "MESH":
                            _ensure_light_uv_layers(o.data)
                    except Exception:
                        pass

                # Enter multi-object Edit mode (needed to write UVMap2)
                if view_layer.objects.active and view_layer.objects.active.mode != "EDIT":
                    bpy.ops.object.mode_set(mode="EDIT")

                if getattr(props, "pack_existing_uvs", False):
                    # Pack existing UV0 islands (no unwrap) for INCLUDED faces only.
                    for o in objs:
                        if not _mesh_has_uv0(o.data):
                            self.report({"ERROR"}, f"Pack existing UVs is enabled, but '{o.name}' has no UV0 layer.")
                            return {"CANCELLED"}

                    # Select included faces per object
                    for obj in objs:
                        view_layer.objects.active = obj
                        mesh = obj.data

                        bm = bmesh.from_edit_mesh(mesh)
                        bm.faces.ensure_lookup_table()

                        included_slots = set()
                        for si, slot in enumerate(obj.material_slots):
                            mat = slot.material
                            if mat in included:
                                included_slots.add(si)

                        for f in bm.faces:
                            f.select_set(f.material_index in included_slots)

                        bm.select_flush(True)
                        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

                        # Ensure UV0 is active before pack
                        try:
                            mesh.uv_layers.active_index = 0
                            mesh.uv_layers.active = mesh.uv_layers[0]
                        except Exception:
                            pass

                    # Pack across all selected faces (attempts global pack in multi-edit mode)
                    view_layer.objects.active = objs[0]
                    if not _run_pack_islands_multifunction(context, objs[0], margin=float(props.pack_island_bleed)):
                        self.report({"WARNING"}, "Pack existing UVs failed (UVs may overlap).")

                    # Fit inside fixed border (0.14 from tile edge)
                    if not _fit_selected_uv0_to_border_in_editmode(objs, border=0.14):
                        self.report({"WARNING"}, "Border-fit failed (UVs may still be close to edge).")

                # Apply UVMap2 UDIM shift per-material (per face) for INCLUDED faces only
                for obj in objs:
                    view_layer.objects.active = obj
                    mesh = obj.data
                    bm = bmesh.from_edit_mesh(mesh)
                    bm.faces.ensure_lookup_table()

                    uv0_name, uv1_name = _ensure_light_uv_layers(mesh)
                    uv0_layer = bm.loops.layers.uv.get(uv0_name)
                    uv1_layer = bm.loops.layers.uv.get(uv1_name)
                    if not uv0_layer or not uv1_layer:
                        continue

                    slot_tile = {}
                    for si, slot in enumerate(obj.material_slots):
                        mat = slot.material
                        if mat in included:
                            lt = included[mat]["light_type"]
                            slot_tile[si] = UV_PRESET_TO_TILE.get(lt, (0, 0))

                    eps = 1e-6
                    for f in bm.faces:
                        tile = slot_tile.get(f.material_index)
                        if tile is None:
                            continue
                        tx, ty = tile
                        for loop in f.loops:
                            uv0 = loop[uv0_layer].uv
                            u = uv0.x + tx
                            v = uv0.y + ty
                            # Clamp inside tile to avoid boundary float issues
                            if u < tx: u = tx
                            if v < ty: v = ty
                            if u > tx + 1.0 - eps: u = tx + 1.0 - eps
                            if v > ty + 1.0 - eps: v = ty + 1.0 - eps
                            loop[uv1_layer].uv = (u, v)

                    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

                # Exit edit mode back to object mode
                bpy.ops.object.mode_set(mode="OBJECT")

            else:
                # Ensure UV layers exist and are named correctly BEFORE entering Edit Mode
                for o in objs:
                    try:
                        if o and o.type == "MESH":
                            _ensure_light_uv_layers(o.data)
                    except Exception:
                        pass

                # Enter multi-object Edit mode
                if view_layer.objects.active and view_layer.objects.active.mode != "EDIT":
                    bpy.ops.object.mode_set(mode="EDIT")

                # Select included faces and unwrap per object
                total_faces = 0
                for obj in objs:
                    view_layer.objects.active = obj
                    mesh = obj.data

                    # Ensure UV layers exist + UVMap2 is UV1
                    try:
                        _ensure_light_uv_layers(mesh)
                    except Exception:
                        pass

                    bm = bmesh.from_edit_mesh(mesh)
                    bm.faces.ensure_lookup_table()

                    # Determine which material slot indices are included
                    included_slots = set()
                    for si, slot in enumerate(obj.material_slots):
                        mat = slot.material
                        if mat in included:
                            included_slots.add(si)

                    if not included_slots:
                        # Nothing to do on this mesh (no included materials). Ensure nothing is selected.
                        for f in bm.faces:
                            f.select_set(False)
                        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
                        continue

                    # Select faces for included materials only
                    for f in bm.faces:
                        f.select_set(f.material_index in included_slots)
                    bm.select_flush(True)
                    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

                    # Count faces for report
                    total_faces += sum(1 for f in bm.faces if f.select)

                    # Ensure UV0 is active before unwrap
                    try:
                        mesh.uv_layers.active_index = 0
                        mesh.uv_layers.active = mesh.uv_layers[0]
                    except Exception:
                        pass

                    if not _run_smart_uv_project_multifunction(context, obj):
                        self.report({"ERROR"}, f"Smart UV Project failed on '{obj.name}'.")
                        return {"CANCELLED"}

                # Pack across all selected faces (attempts global pack in multi-edit mode)
                view_layer.objects.active = objs[0]
                if not _run_pack_islands_multifunction(context, objs[0], margin=0.14):
                    self.report({"WARNING"}, "Pack Islands failed (UVs unwrapped but may overlap).")

                # Apply UVMap2 UDIM shift per-material (per face)
                for obj in objs:
                    view_layer.objects.active = obj
                    mesh = obj.data
                    bm = bmesh.from_edit_mesh(mesh)
                    bm.faces.ensure_lookup_table()

                    uv0_name, uv1_name = _ensure_light_uv_layers(mesh)
                    uv0_layer = bm.loops.layers.uv.get(uv0_name)
                    uv1_layer = bm.loops.layers.uv.get(uv1_name)
                    if not uv0_layer or not uv1_layer:
                        continue

                    slot_tile = {}
                    for si, slot in enumerate(obj.material_slots):
                        mat = slot.material
                        if mat in included:
                            lt = included[mat]["light_type"]
                            slot_tile[si] = UV_PRESET_TO_TILE.get(lt, (0, 0))

                    for f in bm.faces:
                        tile = slot_tile.get(f.material_index)
                        if tile is None:
                            continue
                        tx, ty = tile
                        for loop in f.loops:
                            uv0 = loop[uv0_layer].uv
                            u = uv0.x + tx
                            v = uv0.y + ty
                            # Clamp inside tile to avoid boundary float issues
                            eps = 1e-6
                            if u < tx: u = tx
                            if v < ty: v = ty
                            if u > tx + 1.0 - eps: u = tx + 1.0 - eps
                            if v > ty + 1.0 - eps: v = ty + 1.0 - eps
                            loop[uv1_layer].uv = (u, v)

                    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

                # Exit edit mode back to object mode
                bpy.ops.object.mode_set(mode="OBJECT")

        finally:
            # Restore selection/active
            try:
                for o in view_layer.objects:
                    o.select_set(False)
                for o in prev_selected:
                    o.select_set(True)
                view_layer.objects.active = prev_active
            except Exception:
                pass

            # Best-effort restore previous mode
            try:
                if prev_active and prev_active.mode != prev_mode:
                    bpy.ops.object.mode_set(mode=prev_mode)
            except Exception:
                pass

        # Apply exporter props + material metadata + vertex colors
        for mat, cfg in included.items():
            _write_required_exporter_props(mat)
            mat["i3d_light_type"] = cfg["light_type"]
            mat["i3d_light_role"] = cfg["light_type"]
            # MultiFunction does NOT support rotating-beacon preview (it would rotate the whole mesh).
            if cfg.get("light_type") == "16_BEACON":
                try:
                    if hasattr(mat, "i3d_beacon_preview_mode"):
                        mat.i3d_beacon_preview_mode = "BLINKING"
                    else:
                        mat["i3d_beacon_preview_mode"] = "BLINKING"
                except Exception:
                    pass
            if cfg["light_type"] in {"6_TURN_LEFT", "7_TURN_RIGHT"}:
                _write_turn_signal_bitmask(mat)

        mat_to_rgba = {m: cfg["color"] for m, cfg in included.items()}
        for obj in objs:
            if getattr(props, "paint_vertex_colors", True):
                _paint_faces_by_material(obj, mat_to_rgba)
            # Ensure preview nodes for included materials on this object (cheap if already created)
            for slot in obj.material_slots:
                mat = slot.material
                if mat and mat in included:
                    try:
                        _ensure_light_preview_nodes(mat, obj)
                    except Exception:
                        pass

        self.report({"INFO"}, f"Committed MultiFunction: {len(included)} material(s) across {len(objs)} mesh(es).")
        return {"FINISHED"}


class I3D_CL_OT_MakeMyLight(bpy.types.Operator):
    bl_idname = "i3d.light_make_my_light"
    bl_label = "Make My Light"
    bl_description = 'Build the Static Light setup for the selected meshes (UVs, vertex colors, LightIntensity, and required properties).'
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.i3d_light_tool

        if props.multi_function_light == "YES":
            self.report({"WARNING"}, "Multifunction lights must be set up manually (UV/UDIM + VertexColor segmentation).")
            return {"CANCELLED"}

        obj = context.active_object
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh object first.")
            return {"CANCELLED"}

        mat = obj.active_material
        if not mat:
            self.report({"ERROR"}, "Active object has no active material.")
            return {"CANCELLED"}


        # UV workflow
        slot_index = obj.active_material_index

        if props.do_not_unwrap_uvs:
            # Do Not Unwrap: NEVER Smart UV unwrap. UVMap2 will be created if missing and shifted to the selected UDIM tile.
            try:
                _ensure_light_uv_layers(obj.data)
            except Exception as e:
                self.report({"ERROR"}, f"Failed to ensure UV layers: {e}")
                return {"CANCELLED"}

            if props.pack_existing_uvs:
                if not _mesh_has_uv0(obj.data):
                    self.report({"ERROR"}, "Pack existing UVs is enabled, but this mesh has no UV0 layer.")
                    return {"CANCELLED"}
                ok_pack = _pack_existing_uv0_for_active_slot(
                    context, obj, slot_index, float(props.pack_island_bleed), border=0.14
                )
                if not ok_pack:
                    self.report({"ERROR"}, "Pack existing UVs failed (no unwrap). Ensure the active material slot has faces and UV0 data.")
                    return {"CANCELLED"}
                self.report({"INFO"}, "Packed existing UV0 islands for the active material slot (no unwrap).")
            # else: read-only UVs (no changes)

            # Shift UVMap2 into the selected UDIM function tile for the active material slot (no unwrap)
            try:
                face_count = _apply_uvmap2_udim_shift_only(context, obj, props.light_role, slot_index)
                if face_count:
                    self.report({"INFO"}, f"UVMap2 UDIM shift applied (no unwrap) for {face_count} face(s) (UVMap2={UV_PRESET_TO_TILE.get(props.light_role)}).")
                else:
                    self.report({"WARNING"}, "UVMap2 shift: no target faces found for active material slot.")
            except Exception as e:
                self.report({"WARNING"}, f"UVMap2 shift failed (no unwrap): {e}")
        else:
            # Apply UV preset (GIANTS expectation: UV0 in 0..1; UVMap2 shifted to UDIM function tile)
            try:
                face_count = _apply_light_uv_setup(context, obj, props.light_role)
                if face_count:
                    self.report({"INFO"}, f"Smart UV Project applied to {face_count} face(s) (UV0=0..1, UVMap2={UV_PRESET_TO_TILE.get(props.light_role)}).")
                else:
                    self.report({"WARNING"}, "UV setup: no target faces found for active material slot.")
            except Exception as e:
                self.report({"WARNING"}, f"UV setup failed: {e}")

        # 1) Write exporter properties (always)
        _write_required_exporter_props(mat)

        # 2) Store light type for testing buttons
        mat["i3d_light_type"] = props.light_role
        mat["i3d_light_role"] = props.light_role

        # 3) If turn signals, write bitmask
        if props.light_role in {"6_TURN_LEFT", "7_TURN_RIGHT", "LEFT_SIGNAL", "RIGHT_SIGNAL"}:
            _write_turn_signal_bitmask(mat)

        # 4) Paint vertex color (optional)
        if getattr(props, "paint_vertex_colors", True):
            if props.override_color == "YES":
                rgba = props.override_rgba
            else:
                rgba = LIGHT_TYPE_TO_DEFAULT_VCOL.get(props.light_role, (1.0, 1.0, 1.0, 1.0))

            # Do Not Unwrap mode must not touch non-included materials/faces:
            # paint ONLY the active material's faces (full material coverage).
            if getattr(props, "do_not_unwrap_uvs", False):
                _paint_faces_by_material(obj, {mat: rgba})
            else:
                _paint_selected_faces_vertex_color(obj, rgba)

        # 5) Ensure preview nodes (vertex color drives emission color)
        _ensure_light_preview_nodes(mat, obj)

        self.report({"INFO"}, "Light setup applied (shader props + vertex color + preview nodes).")
        return {"FINISHED"}


class I3D_CL_OT_ApplyLightColor(bpy.types.Operator):
    bl_idname = "i3d.light_apply_color"
    bl_label = "Apply Light Color (Vertex Paint)"
    bl_description = 'Apply the selected light color to the active light setup preview/vertex color.'
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.i3d_light_tool
        obj = context.active_object
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh object first.")
            return {"CANCELLED"}

        rgba = props.override_rgba
        ok = _paint_selected_faces_vertex_color(obj, rgba)
        if not ok:
            self.report({"ERROR"}, "Could not paint vertex color.")
            return {"CANCELLED"}

        # update preview nodes attr name
        mat = obj.active_material
        if mat:
            _ensure_light_preview_nodes(mat, obj)

        self.report({"INFO"}, "Vertex color applied.")
        return {"FINISHED"}



class I3D_CL_OT_LightFixActiveSlotUVs(bpy.types.Operator):
    bl_idname = "i3d.light_fix_active_slot_uvs"
    bl_label = "Fix Active Slot UVs (Match UDIM)"
    bl_description = 'Fix/validate UV setup for the active light material slot (UV0 + UVMap2 requirements).'
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh object first.")
            return {"CANCELLED"}

        mat = obj.active_material
        if not mat:
            self.report({"ERROR"}, "Active object has no active material.")
            return {"CANCELLED"}

        slot_index = obj.active_material_index
        light_id = _resolve_light_id_from_material(mat) or ""

        if light_id not in UV_PRESET_TO_TILE:
            self.report({"ERROR"}, "Active material has no valid i3d_light_type / light preset (run Make My Light).")
            return {"CANCELLED"}

        ok = _apply_light_uv_setup_to_material_slot(obj, slot_index, light_id)
        if not ok:
            self.report({"ERROR"}, "No faces found for the active material slot (nothing to fix).")
            return {"CANCELLED"}

        self.report({"INFO"}, f"UVs fixed: all faces in slot moved to UDIM {UV_PRESET_TO_TILE.get(light_id)} and secondary UV normalized.")
        return {"FINISHED"}




class I3D_CL_OT_InspectSceneForManualLights(bpy.types.Operator):
    bl_idname = "i3d.light_inspect_scene_manual_lights"
    bl_label = "Inspect Scene for Manually Built Lights"
    bl_description = 'Inspect the scene for manually built static lights and report setup issues.'
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = getattr(context, "scene", None)
        if scene is None:
            self.report({"ERROR"}, "No scene found.")
            return {"CANCELLED"}

        props = getattr(scene, "i3d_light_tool", None)
        dry_run = bool(getattr(props, "inspect_dry_run", False)) if props else False

        # Invert mapping: tile -> [light_ids]
        tile_to_ids = {}
        for lid, tile in (UV_PRESET_TO_TILE or {}).items():
            try:
                tile_to_ids.setdefault((int(tile[0]), int(tile[1])), []).append(str(lid))
            except Exception:
                continue

        rows = []
        scanned_slots = 0
        pass_count = 0
        fail_count = 0
        wrote_count = 0
        warn_count = 0

        def _choose_uv2_layer(mesh: bpy.types.Mesh):
            # Prefer explicit UVMap2
            try:
                if mesh.uv_layers.get("UVMap2"):
                    return mesh.uv_layers.get("UVMap2")
            except Exception:
                pass
            # Heuristic: prefer a layer that actually uses UDIM coords (any uv outside 0..1)
            try:
                layers = list(mesh.uv_layers)
            except Exception:
                layers = []
            if len(layers) < 2:
                return None
            eps = 1e-6
            best = None
            best_score = -1
            for lyr in layers[1:]:
                try:
                    data = lyr.data
                    n = len(data)
                except Exception:
                    continue
                if n <= 0:
                    continue
                step = max(1, n // 128)
                score = 0
                for k in range(0, min(n, step * 128), step):
                    try:
                        uv = data[k].uv
                        if (uv.x < -eps) or (uv.x > 1.0 + eps) or (uv.y < -eps) or (uv.y > 1.0 + eps):
                            score += 1
                    except Exception:
                        continue
                if score > best_score:
                    best_score = score
                    best = lyr
            return best if best is not None else layers[1]

        def _tiles_for_slot(mesh: bpy.types.Mesh, uv_layer: bpy.types.MeshUVLoopLayer, slot_index: int):
            tiles = set()
            any_loops = False
            data = uv_layer.data if uv_layer else None
            if not data:
                return tiles, False
            for p in _iter_slot_polys(mesh, slot_index):
                for li in p.loop_indices:
                    if li >= len(data):
                        continue
                    any_loops = True
                    uv = data[li].uv
                    tiles.add((int(math.floor(uv.x)), int(math.floor(uv.y))))
            return tiles, any_loops

        for obj in scene.objects:
            if not obj or obj.type != "MESH":
                continue
            mesh = obj.data
            if not mesh or not getattr(obj, "material_slots", None):
                continue

            uv2_layer = _choose_uv2_layer(mesh)

            for si, slot in enumerate(obj.material_slots):
                mat = slot.material
                if mat is None:
                    continue

                scanned_slots += 1
                ok_var, var_reason = _staticlight_variation_ok(mat)
                if not ok_var:
                    rows.append({
                        "mesh": obj.name,
                        "material": mat.name if mat else "",
                        "slot": si,
                        "pass": False,
                        "eligible": "",
                        "inferred": "",
                        "tiles": "",
                        "reason": var_reason,
                        "actions": "SKIPPED (not a staticLight material)",
                        "warnings": "",
                    })
                    fail_count += 1
                    continue

                # Must have a UV2 to infer from UDIM tiles
                if uv2_layer is None:
                    rows.append({
                        "mesh": obj.name,
                        "material": mat.name,
                        "slot": si,
                        "pass": False,
                        "eligible": var_reason,
                        "inferred": "",
                        "tiles": "",
                        "reason": "UVMap2/secondary UV layer not found",
                        "actions": "",
                        "warnings": "",
                    })
                    fail_count += 1
                    continue

                tiles, any_loops = _tiles_for_slot(mesh, uv2_layer, si)
                tiles_str = ", ".join([f"({t[0]},{t[1]})" for t in sorted(list(tiles))]) if tiles else ""
                if not any_loops:
                    rows.append({
                        "mesh": obj.name,
                        "material": mat.name,
                        "slot": si,
                        "pass": False,
                        "eligible": var_reason,
                        "inferred": "",
                        "tiles": tiles_str,
                        "reason": "No faces found in this material slot",
                        "actions": "",
                        "warnings": "",
                    })
                    fail_count += 1
                    continue

                inferred = ""
                reason = ""
                warnings = ""
                actions = []

                if len(tiles) != 1:
                    reason = f"UVMap2 spans multiple UDIM tiles: {tiles_str}"
                    inferred = ""
                    is_pass = False
                else:
                    tile = next(iter(tiles))
                    ids = tile_to_ids.get(tile, [])
                    if not ids:
                        reason = f"UVMap2 tile {tile} not recognized as a light UDIM tile"
                        is_pass = False
                    elif len(ids) > 1:
                        reason = f"Ambiguous UDIM tile {tile} maps to multiple light IDs: {ids}"
                        is_pass = False
                    else:
                        inferred = ids[0]
                        reason = f"Inferred from UVMap2 tile {tile}"
                        is_pass = True

                # PASS is strictly: eligible + inferred light tile successfully
                if is_pass:
                    pass_count += 1
                else:
                    fail_count += 1

                # Apply / plan changes
                if is_pass:
                    # Never overwrite i3d_light_type; warn on mismatch
                    existing = _resolve_light_id_from_material(mat) or ""
                    if existing and existing != inferred:
                        warnings = f"Existing i3d_light_type='{existing}' differs from inferred '{inferred}' (not overwritten)"
                        warn_count += 1

                    if not dry_run:
                        changed = False
                        if "customShader" not in mat:
                            mat["customShader"] = REQUIRED_CUSTOM_SHADER
                            actions.append("SET customShader")
                            changed = True
                        # Do NOT add customShaderVariation if missing; eligibility guarantees it exists.
                        if "shadingRate" not in mat:
                            mat["shadingRate"] = REQUIRED_SHADING_RATE
                            actions.append("SET shadingRate")
                            changed = True

                        if "i3d_light_type" not in mat and "i3d_light_role" not in mat:
                            # Only set if missing
                            mat["i3d_light_type"] = inferred
                            mat["i3d_light_role"] = inferred
                            actions.append(f"SET i3d_light_type/i3d_light_role='{inferred}'")
                            changed = True
                        else:
                            if "i3d_light_type" not in mat:
                                mat["i3d_light_type"] = inferred
                                actions.append(f"SET i3d_light_type='{inferred}'")
                                changed = True
                            if "i3d_light_role" not in mat:
                                mat["i3d_light_role"] = inferred
                                actions.append(f"SET i3d_light_role='{inferred}'")
                                changed = True

                        if inferred in {"6_TURN_LEFT", "7_TURN_RIGHT"}:
                            if "customParameter_lightTypeBitMask" not in mat:
                                _write_turn_signal_bitmask(mat)
                                actions.append("SET turn-signal bitmask (20480)")
                                changed = True

                        em_path = _find_emission_image_path(mat)
                        if em_path and not mat.get("customTexture_lightsIntensity"):
                            mat["customTexture_lightsIntensity"] = em_path
                            actions.append("SET customTexture_lightsIntensity from Emission image")
                            changed = True

                        if changed:
                            wrote_count += 1
                    else:
                        # Dry run: list what would be changed
                        if "customShader" not in mat:
                            actions.append("WOULD SET customShader")
                        if "shadingRate" not in mat:
                            actions.append("WOULD SET shadingRate")
                        if "i3d_light_type" not in mat:
                            actions.append(f"WOULD SET i3d_light_type='{inferred}'")
                        if "i3d_light_role" not in mat:
                            actions.append(f"WOULD SET i3d_light_role='{inferred}'")
                        if inferred in {"6_TURN_LEFT", "7_TURN_RIGHT"} and "customParameter_lightTypeBitMask" not in mat:
                            actions.append("WOULD SET turn-signal bitmask (20480)")
                        em_path = _find_emission_image_path(mat)
                        if em_path and not mat.get("customTexture_lightsIntensity"):
                            actions.append("WOULD SET customTexture_lightsIntensity from Emission image")


                rows.append({
                    "mesh": obj.name,
                    "material": mat.name,
                    "slot": si,
                    "pass": bool(is_pass),
                    "eligible": var_reason,
                    "inferred": inferred,
                    "tiles": tiles_str,
                    "reason": reason,
                    "actions": "; ".join(actions),
                    "warnings": warnings,
                })

        # Save report to props
        if props is not None:
            props.inspect_last_report = _build_inspect_report_text(rows)
            csv_path, html_path = _write_inspect_report_files(rows)
            props.inspect_last_report_csv = csv_path
            props.inspect_last_report_html = html_path

        msg = f"Inspect Scene done: slots={scanned_slots}, PASS={pass_count}, FAIL={fail_count}, wrote={wrote_count}, warnings={warn_count}"
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class I3D_CL_OT_GenerateLightIntensityPNG(bpy.types.Operator):
    bl_idname = "i3d.light_generate_intensity_png"
    bl_label = "Generate LightIntensity (PNG)"
    bl_description = 'Generate the LightIntensity (emission) image for the current light setup.'
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.i3d_light_tool

        # Targets: selected meshes if any, else active mesh
        targets = []
        try:
            targets = [o for o in (context.selected_objects or []) if o and o.type == "MESH"]
        except Exception:
            targets = []
        if not targets:
            aobj = context.active_object
            if aobj and aobj.type == "MESH":
                targets = [aobj]
        if not targets:
            self.report({"ERROR"}, "Select a mesh object first.")
            return {"CANCELLED"}

        # Determine which material slots are part of the light system on each object
        light_slots_by_obj = {}
        light_id_by_obj_slot = {}
        affected_mats = set()
        for tobj in targets:
            slots = set()
            for si, slot in enumerate(getattr(tobj, "material_slots", []) or []):
                mat = slot.material
                if not mat:
                    continue
                light_id = _resolve_light_id_from_material(mat) or ""
                if not light_id:
                    continue
                slots.add(si)
                light_id_by_obj_slot[(tobj.name, si)] = light_id
                affected_mats.add(mat)
            if slots:
                light_slots_by_obj[tobj.name] = slots

        if not light_slots_by_obj:
            self.report({"ERROR"}, "No light materials found (run Make My Light / MultiFunction Commit first).")
            return {"CANCELLED"}

        # Best pixel usage: normalize UV0 bounds for light faces into 0..1, then generate a best-fit power-of-two rectangle.
        # IMPORTANT: this only touches faces assigned to light materials (materials with i3d_light_type).
        min_u, min_v = 1e9, 1e9
        max_u, max_v = -1e9, -1e9

        # Sync edit mode data (read-only: do NOT create/modify UV layers)
        for tobj in targets:
            try:
                if tobj.mode == "EDIT":
                    tobj.update_from_editmode()
            except Exception:
                pass

        # First pass: compute UV0 bounds over all light faces across the targets
        for tobj in targets:
            slots = light_slots_by_obj.get(tobj.name)
            if not slots:
                continue
            mesh = tobj.data
            if not mesh.uv_layers or not mesh.uv_layers[0] or not mesh.uv_layers[0].data:
                continue
            uv0 = mesh.uv_layers[0].data
            for poly in mesh.polygons:
                if poly.material_index not in slots:
                    continue
                for li in poly.loop_indices:
                    uv = uv0[li].uv
                    min_u = min(min_u, float(uv.x))
                    min_v = min(min_v, float(uv.y))
                    max_u = max(max_u, float(uv.x))
                    max_v = max(max_v, float(uv.y))

        if max_u < min_u or max_v < min_v:
            self.report({"ERROR"}, "Could not compute UV0 bounds (no UV data on light faces).")
            return {"CANCELLED"}

        du = max(1e-9, (max_u - min_u))
        dv = max(1e-9, (max_v - min_v))

        # Decide output dimensions (best-fit POT rectangle). Larger UV extent uses full Tile Resolution.
        tile_res = int(props.li_tile_res)
        max_extent = max(du, dv)
        target_w = int(round(tile_res * (du / max_extent)))
        target_h = int(round(tile_res * (dv / max_extent)))
        width = _next_power_of_two(target_w, min_value=32, max_value=2048)
        height = _next_power_of_two(target_h, min_value=32, max_value=2048)
        # IMPORTANT: UVs are treated as read-only here.
        # We normalize UV0 bounds in-memory during rasterization and DO NOT write UVs back to the mesh.

        # Allocate pixel buffer RGBA
        pixels = [0.0] * (width * height * 4)

        def _edge(ax, ay, bx, by, cx, cy):
            return (cx - ax) * (by - ay) - (cy - ay) * (bx - ax)

        def _write_pixel(ix, iy, r, g, b, a=1.0):
            if ix < 0 or iy < 0 or ix >= width or iy >= height:
                return
            idx = (iy * width + ix) * 4
            pixels[idx + 0] = r
            pixels[idx + 1] = g
            pixels[idx + 2] = b
            pixels[idx + 3] = a

        # Rasterize each triangle using UV0 into the output buffer
        for tobj in targets:
            slots = light_slots_by_obj.get(tobj.name)
            if not slots:
                continue
            mesh = tobj.data
            if not mesh.uv_layers or not mesh.uv_layers[0] or not mesh.uv_layers[0].data:
                continue

            # Vertex color accessor (CORNER domain)
            vcol_name = _get_active_vcol_name(tobj)
            col_data = None
            if hasattr(mesh, "color_attributes") and vcol_name in mesh.color_attributes:
                attr = mesh.color_attributes[vcol_name]
                if getattr(attr, "domain", "") == "CORNER":
                    col_data = attr.data
            elif hasattr(mesh, "vertex_colors") and getattr(mesh, "vertex_colors", None):
                vcol = mesh.vertex_colors.get(vcol_name) or mesh.vertex_colors.active or (mesh.vertex_colors[0] if mesh.vertex_colors else None)
                col_data = vcol.data if vcol else None

            if not col_data:
                continue

            uv_data = mesh.uv_layers[0].data
            uv_len = len(uv_data)
            col_len = len(col_data)

            mesh.calc_loop_triangles()
            for tri in mesh.loop_triangles:
                if getattr(tri, "material_index", None) not in slots:
                    continue
                li0, li1, li2 = tri.loops
                if li0 >= uv_len or li1 >= uv_len or li2 >= uv_len:
                    continue
                if li0 >= col_len or li1 >= col_len or li2 >= col_len:
                    continue

                uv_a = uv_data[li0].uv
                uv_b = uv_data[li1].uv
                uv_c = uv_data[li2].uv

                # Map UV0 bounds to pixel coordinates (read-only; in-memory normalization)
                nax = (float(uv_a.x) - min_u) / du
                nay = (float(uv_a.y) - min_v) / dv
                nbx = (float(uv_b.x) - min_u) / du
                nby = (float(uv_b.y) - min_v) / dv
                ncx = (float(uv_c.x) - min_u) / du
                ncy = (float(uv_c.y) - min_v) / dv

                # Clamp inside 0..1 (avoid u==1.0 mapping outside texture)
                nax = max(0.0, min(0.999999, nax))
                nay = max(0.0, min(0.999999, nay))
                nbx = max(0.0, min(0.999999, nbx))
                nby = max(0.0, min(0.999999, nby))
                ncx = max(0.0, min(0.999999, ncx))
                ncy = max(0.0, min(0.999999, ncy))

                ax = nax * (width - 1)
                ay = nay * (height - 1)
                bx = nbx * (width - 1)
                by = nby * (height - 1)
                cx = ncx * (width - 1)
                cy = ncy * (height - 1)

                min_x = int(max(0, math.floor(min(ax, bx, cx))))
                max_x = int(min(width - 1, math.ceil(max(ax, bx, cx))))
                min_y = int(max(0, math.floor(min(ay, by, cy))))
                max_y = int(min(height - 1, math.ceil(max(ay, by, cy))))

                area = _edge(ax, ay, bx, by, cx, cy)
                if abs(area) < 1e-12:
                    continue

                col_a = col_data[li0].color
                col_b = col_data[li1].color
                col_c = col_data[li2].color

                for iy in range(min_y, max_y + 1):
                    for ix in range(min_x, max_x + 1):
                        px = ix + 0.5
                        py = iy + 0.5
                        w0 = _edge(bx, by, cx, cy, px, py)
                        w1 = _edge(cx, cy, ax, ay, px, py)
                        w2 = _edge(ax, ay, bx, by, px, py)

                        if (w0 >= 0 and w1 >= 0 and w2 >= 0) or (w0 <= 0 and w1 <= 0 and w2 <= 0):
                            w0 /= area
                            w1 /= area
                            w2 /= area

                            r = (col_a[0] * w0) + (col_b[0] * w1) + (col_c[0] * w2)
                            g = (col_a[1] * w0) + (col_b[1] * w1) + (col_c[1] * w2)
                            b = (col_a[2] * w0) + (col_b[2] * w1) + (col_c[2] * w2)

                            if props.li_mode == "LUMA":
                                l = max(0.0, min(1.0, (0.2126 * r + 0.7152 * g + 0.0722 * b)))
                                r = g = b = l

                            r = max(0.0, min(1.0, r))
                            g = max(0.0, min(1.0, g))
                            b = max(0.0, min(1.0, b))
                            _write_pixel(ix, iy, r, g, b, 1.0)

        # Create / update Blender image datablock
        img_name = "I3D_LightIntensity"
        img = bpy.data.images.get(img_name)
        if img and (img.size[0] != width or img.size[1] != height):
            try:
                bpy.data.images.remove(img)
            except Exception:
                pass
            img = None
        if img is None:
            img = bpy.data.images.new(img_name, width=width, height=height, alpha=True, float_buffer=False)
        img.pixels = pixels

        # Save to disk (DDS for export + optional PNG for debugging)
        out_dir = (props.li_out_dir or "").strip()
        if not out_dir:
            out_dir = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.path.expanduser("~")

        # Filename auto behavior:
        # - MultiFunction: default to 'merged'
        # - Normal mode: default to active material name (or object name)
        raw_name = (props.li_filename or "").strip()
        if raw_name:
            base_name = os.path.splitext(raw_name)[0]
        else:
            if props.multi_function_light == "YES":
                base_name = "merged"
            else:
                aobj = context.active_object
                if aobj and aobj.type == "MESH" and aobj.active_material:
                    base_name = _safe_filename_base(aobj.active_material.name)
                elif aobj:
                    base_name = _safe_filename_base(aobj.name)
                else:
                    base_name = "LightIntensity"

        base_name = _safe_filename_base(base_name)
        png_out_path = os.path.join(out_dir, base_name + ".png")
        dds_out_path = os.path.join(out_dir, base_name + ".dds")

        # DDS is REQUIRED for the staticLight shader workflow
        dds_saved = False
        dds_err = None
        
        # DDS is REQUIRED for the staticLight system.
        # Preferred output: DXT5 with full mip chain (texconv, avoids DX10 header GIANTS rejects for LightIntensity).
        # We generate a PNG source for conversion (and optionally keep it as debug output).
        texconv_path = _find_texconv_executable()
        used_texconv = False

        # Always save a PNG source for conversion
        try:
            img.filepath_raw = png_out_path
            img.file_format = "PNG"
            img.save()
        except Exception as e:
            self.report({"ERROR"}, f"Failed to save LightIntensity PNG source for DDS conversion: {e}")
            return {"CANCELLED"}

        if texconv_path:
            try:
                code, out_s, err_s = _texconv_dxt5_with_mips(texconv_path, png_out_path, out_dir)
                if code != 0:
                    self.report({"WARNING"}, f"texconv failed (code {code}); falling back to Blender DDS save. {err_s or out_s}")
                else:
                    # texconv outputs <basename>.DDS by default
                    produced = os.path.join(out_dir, base_name + ".DDS")
                    if not os.path.exists(produced):
                        produced = os.path.join(out_dir, base_name + ".dds")
                    if os.path.exists(produced):
                        # Ensure expected lowercase .dds path exists
                        if produced.lower() != dds_out_path.lower():
                            try:
                                if os.path.exists(dds_out_path):
                                    os.remove(dds_out_path)
                            except Exception:
                                pass
                            try:
                                os.replace(produced, dds_out_path)
                            except Exception:
                                # If rename fails, just use produced path
                                dds_out_path = produced
                        used_texconv = True
            except Exception as e:
                self.report({"WARNING"}, f"texconv exception; falling back to Blender DDS save: {e}")

        if not used_texconv:
            # Fallback: Blender DDS save (may not be BC7 / mipmapped)
            try:
                img.filepath_raw = dds_out_path
                img.file_format = "DDS"
                img.save()
            except Exception as e:
                self.report({"ERROR"}, f"Failed to save LightIntensity DDS (fallback): {e}")
                return {"CANCELLED"}
        
        # PNG is optional (debugging / review). We always save it as a conversion source above.
        # If the user doesn't want to keep it, remove it now.
        if not getattr(props, "li_save_png", True):
            try:
                if os.path.exists(png_out_path):
                    os.remove(png_out_path)
            except Exception:
                pass

        
        # Write customTexture_lightsIntensity (portable relative path with forward slashes)
        try:
            portable_tex = _make_export_safe_texture_path(context, dds_out_path, out_dir)
            if portable_tex:
                for m in affected_mats:
                    try:
                        m["customTexture_lightsIntensity"] = portable_tex
                    except Exception:
                        pass
        except Exception:
            pass

# Successful generation
        return {"FINISHED"}


# -----------------------------------------------------------------------------
# Restored: Light testing system + UI draw helpers + register/unregister
# (Build 19 hotfix – previous build accidentally truncated this module)
# -----------------------------------------------------------------------------

class I3D_CL_OT_LightTestStart(bpy.types.Operator):
    bl_idname = "i3d.light_test_start"
    bl_label = "Start Light Test"
    bl_description = 'Start the in-Blender static light test/simulation for the selected light setup.'
    bl_options = {"REGISTER"}

    mode: StringProperty()

    def execute(self, context):
        props = context.scene.i3d_light_tool
        props.test_mode = self.mode
        props.test_running = True

        _clear_test_runtime()

        # Start modal if not already
        _ensure_test_modal_runner(context)
        return {"FINISHED"}


class I3D_CL_OT_LightTestToggle(bpy.types.Operator):
    bl_idname = "i3d.light_test_toggle"
    bl_label = "Toggle Light Test"
    bl_description = 'Toggle the selected light test state (on/off) while the test is running.'
    bl_options = {"REGISTER"}

    mode: StringProperty()

    def execute(self, context):
        props = context.scene.i3d_light_tool

        modes = set(_parse_multi_modes(props.test_multi_modes))
        if self.mode in modes:
            modes.remove(self.mode)
        else:
            modes.add(self.mode)

        props.test_multi_modes = ",".join(sorted(modes))

        # If nothing is selected, stop and clear
        if not modes:
            bpy.ops.i3d.light_test_stop()
            return {"FINISHED"}

        # Ensure modal runner is active in MULTI mode
        props.test_mode = "MULTI"
        props.test_running = True
        _clear_test_runtime()
        _ensure_test_modal_runner(context)
        return {"FINISHED"}


class I3D_CL_OT_LightTestClearMulti(bpy.types.Operator):
    bl_idname = "i3d.light_test_clear_multi"
    bl_label = "Clear Multi Tests"
    bl_description = 'Clear MultiFunction test states back to defaults.'
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.i3d_light_tool
        props.test_multi_modes = ""
        bpy.ops.i3d.light_test_stop()
        return {"FINISHED"}


class I3D_CL_OT_LightTestStop(bpy.types.Operator):
    bl_idname = "i3d.light_test_stop"
    bl_label = "Stop Light Tests"
    bl_description = 'Stop the in-Blender static light test/simulation.'
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.i3d_light_tool
        props.test_running = False
        props.test_mode = ""

        _clear_test_runtime()

        # turn off emission on all affected objects (scope-based, not selection-based)
        objects = _get_test_scope_objects(context, props.test_scope)
        for obj in objects:
            if not obj or obj.type != "MESH":
                continue
            for slot in obj.material_slots:
                mat = slot.material
                if not mat:
                    continue
                if mat.get("i3d_light_preview_enabled") or _resolve_light_id_from_material(mat):
                    _set_preview_emission_strength(mat, 0.0)
        # Robust stop: ensure the modal runner is fully stopped so rapid on/off cannot wedge the test system.
        _stop_test_modal_runner(context)


        self.report({"INFO"}, "Light tests stopped.")
        return {"FINISHED"}


class I3D_CL_OT_LightTestModal(bpy.types.Operator):
    bl_idname = "i3d.light_test_modal"
    bl_label = "Vehicle Light Test Runner"
    bl_description = 'Internal: modal driver used for the in-Blender static light test/simulation.'

    _timer = None
    _t0 = 0.0

    def invoke(self, context, event):
        props = context.scene.i3d_light_tool

        # Prevent duplicate timers/handlers when toggling quickly (MULTI mode on/off).
        if not _TEST_RUNTIME.get("modal_active"):
            self._t0 = time.perf_counter()
            self._timer = context.window_manager.event_timer_add(
                0.20 if props.test_mode == "MULTI" else 0.10,
                window=context.window,
            )
            context.window_manager.modal_handler_add(self)
            _TEST_RUNTIME["modal_active"] = True
            try:
                _rebuild_test_targets(context, props.test_mode, props.test_scope)
                _TEST_RUNTIME["last_revalidate"] = time.perf_counter()
            except Exception:
                pass

        return {"RUNNING_MODAL"}

    def cancel(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        _TEST_RUNTIME["modal_active"] = False

    def modal(self, context, event):
        props = context.scene.i3d_light_tool

        # MULTI mode: if no toggles are active, stop immediately.
        if props.test_mode == "MULTI" and not (props.test_multi_modes or "").strip():
            props.test_running = False
            props.test_mode = ""
            self.cancel(context)
            return {"CANCELLED"}

        # If stopped, remove timer and ensure emission off
        if not props.test_running or not props.test_mode:
            self.cancel(context)
            return {"CANCELLED"}

        if event.type != "TIMER":
            return {"PASS_THROUGH"}

        t = time.perf_counter() - self._t0
        mode = props.test_mode

        # Backward compatibility (older UI label)
        if mode == "LOWBEAM":
            mode = "DEFAULT"

        # Multi-toggle runtime selection (MULTI uses stored CSV list)
        multi_modes = set()
        mult_by_id = {}
        if mode == "MULTI":
            multi_modes, allowed_ids, mult_by_id = _multi_allowed_ids_and_mult(context)
        else:
            allowed_ids = TEST_MODE_TO_ALLOWED_LIGHT_IDS.get(mode, set())


        # Preview brightness simulation
        base_intensity = float(props.test_intensity)
        # In MULTI mode, per-light intensity multiplier is computed per material slot.
        intensity = base_intensity * float(TEST_MODE_INTENSITY_MULT.get(mode, 1.0))

        # Compute blink state(s)
        blink_on = True
        if mode in {"LEFT_SIGNAL", "RIGHT_SIGNAL", "HAZARDS"} or (mode == "MULTI" and (multi_modes & {"LEFT_SIGNAL", "RIGHT_SIGNAL", "HAZARDS"})):
            hz = max(0.1, props.blinker_hz)
            blink_on = (int(t * hz * 2.0) % 2) == 0
        beacon_active = (mode == "BEACON") or (mode == "MULTI" and ("BEACON" in multi_modes))


        # Beacon blink phase (only affects materials whose Beacon Preview Mode is BLINKING)
        beacon_on = True
        if beacon_active:
            speed = max(0.1, props.beacon_speed)
            period = 1.2 / speed
            phase = t % period
            beacon_on = (phase <= 0.12) or (0.22 <= phase <= 0.34)

        # Rebuild / revalidate cache (avoid heavy work every timer tick)
        now = time.perf_counter()
        force_full_apply = False

        # Rebuild immediately when toggles change (MULTI) or scope/mode changes
        multi_csv = props.test_multi_modes if mode == "MULTI" else ""
        scope_sig = _compute_test_scope_signature(context, props.test_scope)
        sig = (mode, props.test_scope, multi_csv, scope_sig)
        if sig != _TEST_RUNTIME.get("active_sig"):
            try:
                _rebuild_test_targets(context, mode, props.test_scope)
                _TEST_RUNTIME["active_sig"] = sig
                _TEST_RUNTIME["last_revalidate"] = now
                _TEST_RUNTIME["last_multi_csv"] = multi_csv
                _TEST_RUNTIME["last_blink_on"] = None
                _TEST_RUNTIME["last_beacon_on"] = None
                _TEST_RUNTIME["last_base_intensity"] = None
                force_full_apply = True
            except Exception:
                pass
        else:
            if mode != "MULTI":
                # Periodic revalidate (user-controlled)
                if (now - _TEST_RUNTIME.get("last_revalidate", 0.0)) >= max(0.10, float(props.revalidate_interval)):
                    try:
                        _rebuild_test_targets(context, mode, props.test_scope)
                        _TEST_RUNTIME["last_revalidate"] = now
                        force_full_apply = True
                    except Exception:
                        pass

        # If the user changes the intensity slider while running, re-apply once.
        intensity_changed = (_TEST_RUNTIME.get("last_base_intensity") is None) or (abs(float(_TEST_RUNTIME.get("last_base_intensity") or 0.0) - float(base_intensity)) > 1e-9)
        if intensity_changed:
            _TEST_RUNTIME["last_base_intensity"] = float(base_intensity)
            force_full_apply = True

        blink_changed = (_TEST_RUNTIME.get("last_blink_on") is None) or (blink_on != _TEST_RUNTIME.get("last_blink_on"))
        beacon_changed = (_TEST_RUNTIME.get("last_beacon_on") is None) or (beacon_on != _TEST_RUNTIME.get("last_beacon_on"))
        if blink_changed:
            _TEST_RUNTIME["last_blink_on"] = blink_on
        if beacon_changed:
            _TEST_RUNTIME["last_beacon_on"] = beacon_on

        # allowed_ids computed earlier (MULTI unions toggled test modes)
        # Rotating beacon preview: rotate only the objects whose beacon material is set to ROTATING.
        # NOTE: Rotating beacons are SOLID (not flashing). The rotation itself is the preview.
        # MultiFunction mode intentionally does NOT support rotating-beacon preview (would rotate the whole mesh).
        if beacon_active and ("16_BEACON" in allowed_ids):
            try:
                # PERF: rotate beacons using real dt (avoids heavy depsgraph churn from constant step)
                now2 = time.perf_counter()
                dt = float(now2 - float(_TEST_RUNTIME.get("last_rotate_t", now2)))
                _TEST_RUNTIME["last_rotate_t"] = now2
                dt = max(0.0, min(dt, 0.25))
                rpm = max(1.0, props.beacon_rpm)
                rps = rpm / 60.0
                rotated = set()
                for tinfo in _TEST_RUNTIME.get("targets", []):
                    if tinfo.get("light_id") != "16_BEACON":
                        continue
                    mat = tinfo.get("mat_ref") or bpy.data.materials.get(tinfo.get("mat_name", ""))
                    if _get_beacon_preview_mode_from_material(mat) != "ROTATING":
                        continue
                    if not bool(tinfo.get("ok", False)):
                        continue
                    obj = tinfo.get("obj_ref") or bpy.data.objects.get(tinfo.get("obj_name", ""))
                    if not obj or obj.type != "MESH":
                        continue
                    if obj.name in rotated:
                        continue
                    # Match the timer step (0.10 sec)
                    obj.rotation_euler.z += (2.0 * math.pi * rps) * dt
                    rotated.add(obj.name)
            except Exception:
                pass

        # Apply emission only when needed (perf). For steady lights this runs once on mode/toggle change,
        # and for blinking lights it only updates on blink edge changes.
        signal_active = (mode in {"LEFT_SIGNAL", "RIGHT_SIGNAL", "HAZARDS"}) or (
            mode == "MULTI" and bool(multi_modes & {"LEFT_SIGNAL", "RIGHT_SIGNAL", "HAZARDS"})
        )

        ids_to_process = None
        if not force_full_apply:
            ids = set()
            if signal_active and blink_changed:
                ids.update({"6_TURN_LEFT", "7_TURN_RIGHT"})
            if beacon_active and beacon_changed:
                ids.add("16_BEACON")

            # Nothing to update this tick
            if not ids:
                return {"PASS_THROUGH"}

            ids_to_process = ids

        # Use fast light_id index built during rebuild to avoid scanning the full target list.
        if ids_to_process is None:
            targets_iter = _TEST_RUNTIME.get("targets", [])
        else:
            t_by = _TEST_RUNTIME.get("targets_by_light_id", {}) or {}
            targets_iter = []
            for lid in ids_to_process:
                targets_iter.extend(t_by.get(lid, []))

        # PERF: Emission is a MATERIAL-level property (node default_value).
        # Many objects/slots may reference the same material. Update each material once.
        mat_state = {}  # mat_name -> {"mat": mat, "all_ok": bool, "strength": float}

        for tinfo in targets_iter:
            mat = tinfo.get("mat_ref")
            if not mat:
                mat = bpy.data.materials.get(tinfo.get("mat_name", ""))
            if not mat:
                continue

            light_id = tinfo.get("light_id", "")
            if not light_id:
                continue

            wants_on = (light_id in allowed_ids)
            ok = bool(tinfo.get("ok", False))
            on = wants_on and ok

            # Apply animation flags
            if signal_active and light_id in {"6_TURN_LEFT", "7_TURN_RIGHT"}:
                on = on and blink_on
            if beacon_active and light_id == "16_BEACON":
                bmode = _get_beacon_preview_mode_from_material(mat)
                if bmode == "BLINKING":
                    on = on and beacon_on
                # ROTATING = solid (no flashing)

            # Per-target intensity (MULTI uses per-light multiplier)
            if mode == "MULTI":
                strength = (float(base_intensity) * float(mult_by_id.get(light_id, 1.0))) if on else 0.0
            else:
                strength = float(intensity) if on else 0.0

            st = mat_state.get(mat.name)
            if st is None:
                mat_state[mat.name] = {"mat": mat, "all_ok": ok, "strength": float(strength)}
            else:
                st["all_ok"] = bool(st["all_ok"]) and ok
                if float(strength) > float(st["strength"]):
                    st["strength"] = float(strength)

        # Apply updates only when value actually changes.
        for mat_name, st in mat_state.items():
            mat = st["mat"]
            # If any usage of this material is invalid, force it OFF (safer).
            strength = float(st["strength"]) if bool(st["all_ok"]) else 0.0

            last = _TEST_RUNTIME["last_strengths"].get(mat_name)
            if last is None or abs(float(last) - strength) > 1e-9:
                _set_preview_emission_strength(mat, strength)
                _TEST_RUNTIME["last_strengths"][mat_name] = strength

        return {"PASS_THROUGH"}


# ----------------------------
# UI draw helper (call from your Materials tab draw)
# ----------------------------

def draw_vehicle_light_setup_tool(layout, context):
    props = context.scene.i3d_light_tool

    # Collapsible: Vehicle Light Setup Tool
    box = layout.box()
    row = box.row()
    row.prop(props, "show_light_setup", text="Vehicle Light Setup Tool", emboss=True, icon="LIGHT")

    if props.show_light_setup:
        col = box.column(align=True)

        col.prop(props, "multi_function_light", text="Multi Function Light?")
        if props.multi_function_light == "YES":
            info = col.box()
            info.label(text="You are in multifunction light design mode.", icon="INFO")
            info.label(text="Create a different material for each light type and assign faces to it.")
            if getattr(props, "do_not_unwrap_uvs", False):
                info.label(text="Commit will NOT unwrap UVs and will NOT move UVMap2 (manual UVs required).", icon="INFO")
            else:
                info.label(text="Commit will Smart UV unwrap UV0 (0..1), pack, then move UVMap2 into UDIM tiles.")
            info.separator()
            info.label(text="Excluded materials are untouched.", icon="CHECKMARK")

            opt = col.box()
            opt.label(text="UV Workflow Options", icon="UV")
            opt.prop(props, "do_not_unwrap_uvs", text="Do Not Unwrap UVs")
            if props.do_not_unwrap_uvs:
                opt.label(text="UVMap2 must already exist on each mesh.", icon="INFO")
                opt.prop(props, "pack_existing_uvs", text="Pack existing UVs (no unwrap)")
                if props.pack_existing_uvs:
                    opt.prop(props, "pack_island_bleed", text="Bleed Between Islands")
                    opt.label(text="Textures must be recompiled to match new UV layout.", icon="ERROR")
            opt.prop(props, "paint_vertex_colors", text="Paint Vertex Colors")

            row = col.row(align=True)
            row.prop(props, "mf_commit_scope", text="Commit Scope")
            row.operator("i3d.mf_refresh_materials", text="Refresh Materials", icon="FILE_REFRESH")

            col.template_list("I3D_UL_MF_Materials", "", props, "mf_items", props, "mf_active_index", rows=8)

            col.separator()
            col.operator("i3d.mf_commit_multifunction", icon="CHECKMARK")

            # LightIntensity helper (required by staticLight shader variation)
            li_box = col.box()
            li_box.label(text="LightIntensity Map (Emissive) (Required for Static Lights)", icon="IMAGE")
            li_box.prop(props, "li_tile_res")
            li_box.prop(props, "li_mode")
            li_box.prop(props, "li_out_dir")
            rowf = li_box.row(align=True)
            rowf.prop(props, "li_filename", text="Filename (optional)")
            if not (props.li_filename or "").strip():
                li_box.label(text="Auto: merged", icon="INFO")
            li_box.operator("i3d.light_generate_intensity_png", icon="FILE_IMAGE")
        else:
            col.prop(props, "light_role", text="Light Type")
            col.prop(props, "auto_sync_light_type")

            uvbox = col.box()
            uvbox.label(text="UV Workflow Options", icon="UV")
            uvbox.prop(props, "do_not_unwrap_uvs", text="Do Not Unwrap UVs")
            if props.do_not_unwrap_uvs:
                uvbox.label(text="UVMap2 will be created if missing.", icon="INFO")
                uvbox.prop(props, "pack_existing_uvs", text="Pack existing UVs (no unwrap)")
                if props.pack_existing_uvs:
                    uvbox.prop(props, "pack_island_bleed", text="Bleed Between Islands")
                    uvbox.label(text="Textures must be recompiled to match new UV layout.", icon="ERROR")

            col.prop(props, "paint_vertex_colors", text="Paint Vertex Colors")

            # Per-material beacon preview mode (must be set before testing; persists on the material)
            try:
                aobj = context.active_object
                amat = aobj.active_material if aobj and aobj.type == "MESH" else None
            except Exception:
                amat = None

            try:
                active_is_beacon = (props.light_role in {"16_BEACON", "BEACON"}) or (
                    bool(amat) and (_resolve_light_id_from_material(amat) in {"16_BEACON", "BEACON"})
                )
            except Exception:
                active_is_beacon = (props.light_role in {"16_BEACON", "BEACON"})

            if active_is_beacon:
                if amat is not None and hasattr(amat, "i3d_beacon_preview_mode"):
                    col.prop(amat, "i3d_beacon_preview_mode", text="Beacon Preview")
                else:
                    col.label(text="Select a beacon material to set Beacon Preview Mode.", icon="INFO")

            col.separator()
            if getattr(props, "paint_vertex_colors", True):
                col.prop(props, "override_color", text="Override Normal Color?")
                if props.override_color == "YES":
                    col.prop(props, "override_rgba", text="")
                    col.operator("i3d.light_apply_color", icon="BRUSH_DATA")
            else:
                col.label(text="Vertex colors will not be modified.", icon="INFO")

            col.separator()
            col.operator("i3d.light_make_my_light", icon="CHECKMARK")

            # LightIntensity helper (required by staticLight shader variation)
            li_box = col.box()
            li_box.label(text="LightIntensity Map (Emissive) (Required for Static Lights)", icon="IMAGE")
            li_box.prop(props, "li_tile_res")
            li_box.prop(props, "li_mode")
            li_box.prop(props, "li_out_dir")
            rowf = li_box.row(align=True)
            rowf.prop(props, "li_filename", text="Filename (optional)")
            if not (props.li_filename or "").strip():
                auto_name = "LightIntensity"
                try:
                    aobj = context.active_object
                    if aobj and aobj.type == "MESH" and aobj.active_material:
                        auto_name = _safe_filename_base(aobj.active_material.name)
                    elif aobj:
                        auto_name = _safe_filename_base(aobj.name)
                except Exception:
                    pass
                li_box.label(text=f"Auto: {auto_name}", icon="INFO")
            li_box.operator("i3d.light_generate_intensity_png", icon="FILE_IMAGE")

        # Inspect Scene for Manually Built Lights (on-demand; no polling)
        util_box = box.box()
        header = util_box.row()
        header.prop(props, "inspect_utilities_open", text="Inspect Scene for Manually Built Lights", icon=("TRIA_DOWN" if props.inspect_utilities_open else "TRIA_RIGHT"), emboss=False)
        if props.inspect_utilities_open:
            colu = util_box.column(align=True)
            colu.operator("i3d.light_inspect_scene_manual_lights", icon="VIEWZOOM")
            colu.prop(props, "inspect_dry_run", text="Scan and list but don't implement")
        
            row_rep = colu.row(align=True)
            row_rep.operator("i3d.light_show_inspect_report", text="View Report", icon="TEXT")
            row_rep.operator("i3d.light_open_inspect_report", text="View Report as Spreadsheet", icon="WORLD")
            row_rep.operator("i3d.light_copy_inspect_report", text="", icon="COPYDOWN")
        
            colu.label(text="One-time scan: checks customShaderVariation + UVMap2 UDIM; writes only missing props (unless dry-run).", icon="INFO")

        # Collapsible subfolder: Testing Light System
        sub = box.box()
        r2 = sub.row()
        r2.prop(props, "show_light_testing", text="Testing Light System", emboss=True, icon="PLAY")

        if props.show_light_testing:
            col2 = sub.column(align=True)
            col2.prop(props, "test_intensity")
            col2.prop(props, "test_scope")
            col2.prop(props, "revalidate_interval")
            col2.separator()

            # Scope warning (common confusion: "nothing selected" + Selected Only scope)
            if props.test_scope == "SELECTED" and not context.selected_objects:
                col2.label(text="Test Scope is 'Selected Only' but nothing is selected.", icon="ERROR")
                col2.label(text="Switch Test Scope to 'Visible Scene' to test without selecting meshes.", icon="INFO")

            # Active slot validation (GE-style failsafe readout)
            status = col2.box()
            status.label(text="Active Light Status (GIANTS Failsafe)", icon="INFO")

            obj = context.active_object
            if not obj or obj.type != "MESH" or not obj.active_material:
                status.label(text="Select a mesh + its light material to see validation.", icon="ERROR")
            else:
                mat = obj.active_material
                slot_index = obj.active_material_index
                light_id = _resolve_light_id_from_material(mat)

                if not light_id:
                    status.label(text="Active material has no i3d_light_type (run 'Make My Light').", icon="ERROR")
                else:
                    mesh = obj.data
                    uv0_name, expected_tile, uv0_tiles, uv1_name, uv1_tiles, bitmask, ok, errors = _get_active_validation_cached(context, obj, slot_index, mat, light_id)

                    status.label(text=f"Light Type: {light_id}")
                    status.label(text=f"Expected UDIM (UV1): {expected_tile}")
                    status.label(text=f"UV0 Layer (LightIntensity): {uv0_name}")
                    em_path = _find_emission_image_path(mat)
                    if em_path:
                        status.label(text="WARNING: Emission texture detected in shader nodes.", icon="ERROR")
                        status.label(text="Delete emissive texture in GE before GE/in-game light testing.", icon="INFO")

                    status.label(text=f"UV0 Tiles Found: {sorted(list(uv0_tiles))}")
                    if len(mesh.uv_layers) > 1:
                        status.label(text=f"UV1 Layer (Function Tile): {uv1_name}")
                        status.label(text=f"UV1 Tiles Found: {sorted(list(uv1_tiles))}")
                    status.label(text=f"BitMask: {bitmask}")

                    if ok:
                        status.label(text="PASS: This material slot should work in GIANTS Editor.", icon="CHECKMARK")
                    else:
                        status.label(text="FAIL: Fix these issues for GIANTS Editor:", icon="ERROR")
                        for e in errors:
                            status.label(text=e, icon="ERROR")
                        row_fail = status.row(align=True)
                        row_fail.operator("i3d.light_show_failsafe_report", text="See Full Report", icon="TEXT")
                        row_fail.operator("i3d.light_copy_failsafe_report", text="", icon="COPYDOWN")
                        row_fail.operator("i3d.light_select_offending_faces", text="Select Offending Faces", icon="RESTRICT_SELECT_OFF")
                        status.operator("i3d.light_fix_active_slot_uvs", icon="WRENCH")


            # blink sliders
            col2.prop(props, "blinker_hz")
            col2.separator()

            # Beacon controls
            col2.label(text="Beacon Controls")
            col2.prop(props, "beacon_speed", text="Blink Speed")
            col2.prop(props, "beacon_rpm", text="Rotation RPM")
            col2.label(text="Beacon preview mode is set per material in Vehicle Light Setup Tool.", icon="INFO")

            col2.separator()
            row_mt = col2.row(align=True)
            row_mt.prop(props, "test_multi_enable", text="Multi-toggle Tests")
            if props.test_multi_enable:
                row_mt.label(text="May cause lag — more lights toggled means more lag", icon="ERROR")

            if props.test_multi_enable:
                active_modes = set([p for p in (props.test_multi_modes or "").split(",") if p])

                rowt = col2.row(align=True)
                rowt.operator("i3d.light_test_stop", text="Stop Tests", icon="CANCEL")
                rowt.operator("i3d.light_test_clear_multi", text="Clear Toggles", icon="X")

                grid = col2.grid_flow(columns=2, align=True)

                op = grid.operator("i3d.light_test_toggle", text="Default Lights", depress=("DEFAULT" in active_modes))
                op.mode = "DEFAULT"
                op = grid.operator("i3d.light_test_toggle", text="High Beams", depress=("HIGHBEAM" in active_modes))
                op.mode = "HIGHBEAM"

                op = grid.operator("i3d.light_test_toggle", text="Left Signal", depress=("LEFT_SIGNAL" in active_modes))
                op.mode = "LEFT_SIGNAL"
                op = grid.operator("i3d.light_test_toggle", text="Right Signal", depress=("RIGHT_SIGNAL" in active_modes))
                op.mode = "RIGHT_SIGNAL"
                # Hazards button hidden in Multi-toggle mode (use Left + Right together)

                op = grid.operator("i3d.light_test_toggle", text="Back Lights", depress=("BACK" in active_modes))
                op.mode = "BACK"
                op = grid.operator("i3d.light_test_toggle", text="Brake Lights", depress=("BRAKE" in active_modes))
                op.mode = "BRAKE"

                op = grid.operator("i3d.light_test_toggle", text="Reverse Light", depress=("REVERSE" in active_modes))
                op.mode = "REVERSE"

                op = grid.operator("i3d.light_test_toggle", text="Worklight Front", depress=("WORK_FRONT" in active_modes))
                op.mode = "WORK_FRONT"
                op = grid.operator("i3d.light_test_toggle", text="Worklight Rear", depress=("WORK_BACK" in active_modes))
                op.mode = "WORK_BACK"

                op = grid.operator("i3d.light_test_toggle", text="Work Light Add 1", depress=("WORK_ADD1" in active_modes))
                op.mode = "WORK_ADD1"
                op = grid.operator("i3d.light_test_toggle", text="Work Light Add 2", depress=("WORK_ADD2" in active_modes))
                op.mode = "WORK_ADD2"

                op = grid.operator("i3d.light_test_toggle", text="Beacon Lights", depress=("BEACON" in active_modes))
                op.mode = "BEACON"
                op = grid.operator("i3d.light_test_toggle", text="DRL", depress=("DRL" in active_modes))
                op.mode = "DRL"
            else:
                rowt = col2.row(align=True)
                rowt.operator("i3d.light_test_stop", text="Stop Tests", icon="CANCEL")

                grid = col2.grid_flow(columns=2, align=True)

                op = grid.operator("i3d.light_test_start", text="Test Default Lights")
                op.mode = "DEFAULT"
                op = grid.operator("i3d.light_test_start", text="Test High Beams")
                op.mode = "HIGHBEAM"

                op = grid.operator("i3d.light_test_start", text="Test Left Signal")
                op.mode = "LEFT_SIGNAL"
                op = grid.operator("i3d.light_test_start", text="Test Right Signal")
                op.mode = "RIGHT_SIGNAL"

                op = grid.operator("i3d.light_test_start", text="Test Hazards")
                op.mode = "HAZARDS"

                op = grid.operator("i3d.light_test_start", text="Test Back Lights")
                op.mode = "BACK"
                op = grid.operator("i3d.light_test_start", text="Test Brake Lights")
                op.mode = "BRAKE"

                op = grid.operator("i3d.light_test_start", text="Test Reverse Light")
                op.mode = "REVERSE"

                op = grid.operator("i3d.light_test_start", text="Test Worklight Front")
                op.mode = "WORK_FRONT"
                op = grid.operator("i3d.light_test_start", text="Test Worklight Rear")
                op.mode = "WORK_BACK"

                op = grid.operator("i3d.light_test_start", text="Test Work Light Additional")
                op.mode = "WORK_ADD1"
                op = grid.operator("i3d.light_test_start", text="Test Work Light Additional 2")
                op.mode = "WORK_ADD2"

                op = grid.operator("i3d.light_test_start", text="Test Beacon Lights")
                op.mode = "BEACON"
                op = grid.operator("i3d.light_test_start", text="Test DRL")
                op.mode = "DRL"
            col2.separator()


# ----------------------------
# Register
# ----------------------------

CLASSES = (
    I3D_MF_MaterialRow,
    I3D_UL_MF_Materials,
    I3D_MF_OT_RefreshMaterials,
    I3D_MF_OT_CommitMultiFunction,
    I3D_LightToolProps,
    I3D_CL_OT_MakeMyLight,
    I3D_CL_OT_ApplyLightColor,
    I3D_CL_OT_LightFixActiveSlotUVs,
    I3D_CL_OT_LightShowFailsafeReport,
    I3D_CL_OT_LightCopyFailsafeReport,
    I3D_CL_OT_LightSelectOffendingFaces,
    I3D_CL_OT_LightShowInspectReport,
    I3D_CL_OT_LightCopyInspectReport,
    I3D_CL_OT_LightOpenInspectReport,
    I3D_CL_OT_InspectSceneForManualLights,
    I3D_CL_OT_GenerateLightIntensityPNG,
    I3D_CL_OT_LightTestStart,
    I3D_CL_OT_LightTestStop,
    I3D_CL_OT_LightTestToggle,
    I3D_CL_OT_LightTestClearMulti,
    I3D_CL_OT_LightTestModal,
)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)

    # Per-material beacon preview mode (supports mixed blinking+rotating beacons)
    try:
        bpy.types.Material.i3d_beacon_preview_mode = EnumProperty(
            name="Beacon Preview Mode",
            items=[
                ("BLINKING", "Blinking", "Blinking beacon (emission toggles on/off)"),
                ("ROTATING", "Rotating (Solid)", "Rotating beacon preview (solid emission; object rotates)"),
            ],
            default="BLINKING",
        )
    except Exception:
        pass

    bpy.types.Scene.i3d_light_tool = PointerProperty(type=I3D_LightToolProps)


def unregister():
    if hasattr(bpy.types.Scene, "i3d_light_tool"):
        del bpy.types.Scene.i3d_light_tool

    try:
        if hasattr(bpy.types.Material, "i3d_beacon_preview_mode"):
            del bpy.types.Material.i3d_beacon_preview_mode
    except Exception:
        pass

    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
