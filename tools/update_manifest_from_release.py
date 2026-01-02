import json
import os
import re
from datetime import datetime, timezone

# This script is executed by the GitHub Action after checking out `main` into the folder `main_branch/`.
# We intentionally write ONLY the manifest located in main_branch.
MANIFEST_PATH = "main_branch/i3dexport_latest.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_event() -> dict:
    p = os.environ.get("GITHUB_EVENT_PATH")
    if not p or not os.path.exists(p):
        raise RuntimeError("GITHUB_EVENT_PATH not found.")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def load_manifest() -> dict:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(m: dict) -> None:
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2)
        f.write("\n")


def detect_channel(tag: str, prerelease: bool) -> str:
    t = (tag or "").lower()
    if "alpha" in t:
        return "alpha"
    if "beta" in t:
        return "beta"
    # If the GitHub Release is marked prerelease but tag doesn't say alpha/beta, treat it as beta.
    if prerelease:
        return "beta"
    return "stable"


def parse_version(tag: str) -> list[int]:
    """Extract x.y.z (major.minor.patch) from a release tag.

    Examples:
      - '10.0.18' -> [10, 0, 18]
      - '10.0.17.2ALPHA' -> [10, 0, 17]

    Build numbers (the optional 4th numeric component) are handled separately
    by `parse_build(...)` because Blender add-ons only expose a 3-int
    `bl_info['version']` tuple.
    """

    m = re.search(r"(\d+)\.(\d+)\.(\d+)", tag or "")
    if not m:
        raise RuntimeError(f"Tag '{tag}' missing x.y.z version.")
    return [int(m.group(1)), int(m.group(2)), int(m.group(3))]


def parse_build(tag: str) -> int:
    """Extract optional build number from a release tag.

    Examples:
      - '10.0.18' -> 0
      - '10.0.17.2ALPHA' -> 2
      - '10.0.17.12BETA' -> 12

    This matches the 4th numeric component when present (after the third dot).
    """

    tag = tag or ""

    # Preferred: 10.0.17.2ALPHA / 10.0.17.2BETA / 10.0.17.2
    m = re.search(r"\d+\.\d+\.\d+\.(\d+)", tag)
    if m:
        return int(m.group(1))

    # Legacy: 10.0.12.ALPHA2 / 10.0.12.BETA3
    m = re.search(r"(?:ALPHA|BETA)(\d+)", tag, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))

    return 0


def _extract_manifest_message(release_body: str) -> str | None:
    """Optional override: users can put a single-line message in the Release body.

    Example:
      manifest_message: Stable update available (hotfix).

    If not present, we preserve the existing manifest message.
    """
    if not release_body:
        return None
    for line in release_body.splitlines():
        s = line.strip()
        if s.lower().startswith("manifest_message:"):
            return s.split(":", 1)[1].strip() or None
    return None


def _extract_notes_from_release_body(release_body: str) -> list[str]:
    """Extract patch notes (short list) from the GitHub Release body.

    Supported formats:
    1) Explicit block:
         manifest_notes:
         - Fix: ...
         - New: ...

    2) Heading blocks:
         Patch Notes:
         - ...
       or
         Change Log:
         - ...
       (Now also supports plain non-bulleted lines under these headings.)

    3) Otherwise: collects bullet/numbered lines from anywhere in the body.

    Returns a list of strings (no bullet prefix). Empty list if nothing usable.
    """
    if not release_body:
        return []

    lines = release_body.splitlines()

    # 1) Explicit block: manifest_notes:
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("manifest_notes:"):
            notes: list[str] = []
            for j in range(i + 1, len(lines)):
                s = lines[j].strip()
                if not s:
                    if notes:
                        break
                    continue

                m = re.match(r"^[-*]\s+(.*)$", s)
                if m:
                    notes.append(m.group(1).strip())
                    continue

                m = re.match(r"^\d+\.\s+(.*)$", s)
                if m:
                    notes.append(m.group(1).strip())
                    continue

                # Stop when we hit something that isn't part of the list.
                if notes:
                    break
            return [n for n in notes if n][:25]

    # 1b) Heading blocks: "Patch Notes:" and/or "Change Log:"
    def _extract_items_after_heading(start_index: int) -> list[str]:
        notes: list[str] = []
        for j in range(start_index + 1, len(lines)):
            s = lines[j].strip()

            if not s:
                if notes:
                    break
                continue

            # Stop if we hit another heading block.
            if re.match(r"^(manifest_notes|patch\s+notes|change\s+log)\s*:", s, re.IGNORECASE):
                if notes:
                    break
                continue

            m = re.match(r"^[-*]\s+(.*)$", s)
            if m:
                notes.append(m.group(1).strip())
                continue

            m = re.match(r"^\d+\.\s+(.*)$", s)
            if m:
                notes.append(m.group(1).strip())
                continue

            # NEW: accept plain text lines under the heading
            notes.append(s)

        return notes

    collected: list[str] = []

    for i, line in enumerate(lines):
        s = line.strip()
        if re.match(r"^patch\s+notes\s*:", s, re.IGNORECASE):
            collected.extend(_extract_items_after_heading(i))
        elif re.match(r"^change\s+log\s*:", s, re.IGNORECASE):
            collected.extend(_extract_items_after_heading(i))

    # De-dupe while preserving order
    if collected:
        seen: set[str] = set()
        out: list[str] = []
        for n in collected:
            if n and n not in seen:
                out.append(n)
                seen.add(n)
        if out:
            return out[:25]

    # 2) Fallback: gather bullet/numbered items from the entire release body.
    notes: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue

        m = re.match(r"^[-*]\s+(.*)$", s)
        if m:
            notes.append(m.group(1).strip())
            continue

        m = re.match(r"^\d+\.\s+(.*)$", s)
        if m:
            notes.append(m.group(1).strip())
            continue

    # Keep it short in the manifest.
    notes = [n for n in notes if n]
    return notes[:25]


def main() -> None:
    event = load_event()
    release = event.get("release") or {}

    tag = release.get("tag_name") or ""
    prerelease = bool(release.get("prerelease", False))
    html_url = release.get("html_url") or ""
    body = release.get("body") or ""

    channel = detect_channel(tag, prerelease)
    version = parse_version(tag)
    build = parse_build(tag)

    # We always upload the asset to the Release with this exact name.
    download_url = (
        "https://github.com/dtapgaming/GiantsExporterRework-Blender/releases/download/"
        f"{tag}/io_export_i3d_reworked.zip"
    )

    manifest = load_manifest()
    manifest["schema"] = 1
    manifest["generated_utc"] = utc_now()

    manifest.setdefault("channels", {})
    manifest["channels"].setdefault(channel, {})
    ch = manifest["channels"][channel]

    # --- Preserve fields unless we have new authoritative values ---
    existing_message = ch.get("message")
    existing_notes = ch.get("notes")

    # Update version and links for THIS channel.
    #
    # NOTE: We keep the numeric core version (x.y.z) in `version` to remain
    # compatible with older in-Blender updaters that assume `version` has 3
    # integers. If a 4th-digit build number is present in the tag
    # (e.g. 10.0.17.2ALPHA), we also write it to `build`.
    ch["version"] = version
    if build > 0:
        ch["build"] = build
    else:
        # If the previous manifest had a build number, drop it for tags that
        # don't carry a 4th digit.
        ch.pop("build", None)
    ch.setdefault("min_blender", [4, 0, 0])

    ch.setdefault("download", {})
    # Preserve existing secondary if present.
    secondary = ch["download"].get("secondary")
    ch["download"]["primary"] = download_url
    if secondary is not None:
        ch["download"]["secondary"] = secondary

    # Always point to the published release page for notes_url.
    if html_url:
        ch["notes_url"] = html_url

    # Message: only overwrite if release body explicitly provides one.
    override_message = _extract_manifest_message(body)
    if override_message:
        ch["message"] = override_message
    else:
        # Keep existing if set, otherwise provide a default.
        ch["message"] = existing_message or f"{channel.capitalize()} build available."

    # Notes: use extracted notes if found; otherwise preserve existing notes.
    extracted_notes = _extract_notes_from_release_body(body)
    if extracted_notes:
        ch["notes"] = extracted_notes
    else:
        # Keep what was already in the manifest (if any).
        if existing_notes is not None:
            ch["notes"] = existing_notes

    save_manifest(manifest)
    print(f"Updated manifest channel={channel} version={version} notes_count={len(ch.get('notes') or [])}")


if __name__ == "__main__":
    main()
