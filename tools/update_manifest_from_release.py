import json, os, re
from datetime import datetime, timezone

MANIFEST_PATH = "main_branch/i3dexport_latest.json"

def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def load_event():
    p = os.environ.get("GITHUB_EVENT_PATH")
    if not p or not os.path.exists(p):
        raise RuntimeError("GITHUB_EVENT_PATH not found.")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def load_manifest():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_manifest(m):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2)
        f.write("\n")

def detect_channel(tag: str, prerelease: bool) -> str:
    t = (tag or "").lower()
    if "alpha" in t:
        return "alpha"
    if "beta" in t:
        return "beta"
    if prerelease:
        return "beta"
    return "stable"

def parse_version(tag: str):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", tag or "")
    if not m:
        raise RuntimeError(f"Tag '{tag}' missing x.y.z version.")
    return [int(m.group(1)), int(m.group(2)), int(m.group(3))]

def main():
    event = load_event()
    release = event.get("release") or {}
    tag = release.get("tag_name") or ""
    prerelease = bool(release.get("prerelease", False))
    html_url = release.get("html_url") or ""

    channel = detect_channel(tag, prerelease)
    version = parse_version(tag)

    download_url = f"https://github.com/dtapgaming/GiantsExporterRework-Blender/releases/download/{tag}/io_export_i3d_reworked.zip"

    manifest = load_manifest()
    manifest["schema"] = 1
    manifest["generated_utc"] = utc_now()
    manifest.setdefault("channels", {})
    manifest["channels"].setdefault(channel, {})
    ch = manifest["channels"][channel]

    ch["version"] = version
    ch.setdefault("min_blender", [4, 0, 0])
    ch.setdefault("download", {})
    ch["download"]["primary"] = download_url
    ch.setdefault("notes_url", html_url)
    ch["notes_url"] = html_url
    ch["message"] = f"A New {channel.capitalize()} Build Update Is Available."

    save_manifest(manifest)
    print(f"Updated manifest channel={channel} version={version}")

if __name__ == "__main__":
    main()
