
* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * 
****IMPORTANT: DOWNLOAD NOTES**** 
* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * 
DO NOT DOWNLOAD FROM HERE ⤵️

<img width="604" height="111" alt="image" src="https://github.com/user-attachments/assets/50efcc9c-4248-47a9-99a9-af22115e1c42" />



Instead Download from here ⤵️

<img width="422" height="573" alt="image" src="https://github.com/user-attachments/assets/b52d8fb3-3d66-46ef-a3a6-3a6fc966cd0d" />


or it wont work!!!

**Designed for Blender 4.3 and above. May not work in full on earlier versions but can be installed on 4.0+.


* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * 
****IMPORTANT: INSTALLATION AND SETUP NOTES**** 
* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * 

Installation - drag the Zip and drop it into blenders Viewport. You may be prompted to disable conflicting addons (there are 2) to use this addon you MUST disable both if you have them (they are built into this addon so you wont be missing them they are just included).


Now that the addon is installed open your side panel (Shortcut N) then click on the Giants I3D Exporter REWORKED tab
 
<img width="280" height="815" alt="image" src="https://github.com/user-attachments/assets/14c23bff-7f51-4c6c-8fc3-5354966b1892" />

 then click 
 
<img width="230" height="29" alt="image" src="https://github.com/user-attachments/assets/d5223f58-0857-4f6a-b677-a0cc41ab028a" />

 you will get a Pop-Up 

<img width="1059" height="603" alt="image" src="https://github.com/user-attachments/assets/51a544dd-f2e3-49bb-b4c2-977d5f41c188" />

set your game installation path at the bottom

<img width="681" height="86" alt="image" src="https://github.com/user-attachments/assets/9bb67335-a3de-4e87-8a0a-c18c90a53d81" />

IF you have not granted internet access to Blender itself and you want to get the updates to this addon without having to go to gitHub, then select Enable Online Access button (this ONLY shows if the enable Update Checks (Internet) box is checked)

<img width="1061" height="942" alt="image" src="https://github.com/user-attachments/assets/fa98ad13-eed8-4a38-b944-87887d5ee6e6" />

then close this window and all of the warnings will go away
 
<img width="297" height="642" alt="image" src="https://github.com/user-attachments/assets/77e267a2-3894-48cd-ae06-ebd74514a31a" />





* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * 
****UPDATE LOGIC**** 
* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * 

an update that gets pushed for this update will alert you if its availible when you start a blender session as long as you have Internet access enabled in Blender and the enable Update Checks (Internet) box is checked in your User Preferences in this same location you can choose what build you would like to opt into (STABLE/BETA/ALPHA).

this is an example of what an update prompt looks like on startup

<img width="645" height="613" alt="image" src="https://github.com/user-attachments/assets/31ceb917-64bf-478a-ad92-d2236560792a" />

Be sure to pay special attention to this section:

<img width="578" height="169" alt="image" src="https://github.com/user-attachments/assets/d5d63165-fbfd-4a7f-bc96-2efb7435ef3c" />

once you click Update either move your mouse up and down till the prompt changes or goes away or click out of it right away and watch the bottom left corner of blender 

<img width="701" height="282" alt="image" src="https://github.com/user-attachments/assets/9c163c2c-18a3-4308-aeba-40d151c1c511" />

just to the right of this GIANTS I3D quick access about menu it will show "downloading update" and "update complete" (it happens really fast)

if you get this popup after moving your mouse around after the update like mentioned above

<img width="1214" height="476" alt="image" src="https://github.com/user-attachments/assets/813308de-7c34-4287-862a-375be779819c" />

you can just click out of it this is a Minor Bug Im working on resolving but im getting stuck on fixing because it happens as the installation is happening of the new version.


* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * 
****OTHER INFO**** 
* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * 
Please Note: I haven't tested everything like splines tools, joint creation, array creation, and more complex things as I shouldn't have changed anything that broke those (in theory) let me know if there is issues with them.

Bug reports can be on this GitHub OR in your user prefferences you can select 



* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * 
****CHANGE LOGS**** 
* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * 

V 10.0.17.63 (14.01.2026) Build: BETA TESTING (opt in in user Preferences)
------------------
- Unsaved .blend safety for “Export Object Data Texture” If the blend isn’t saved, it now prompts the user to choose where to save curveArray.dds (instead of writing to a dangerous/odd default).
- Vehicle Light Tool validation + selection
  - Validation now updates mesh/UV data so Object Mode doesn’t miss UV-out-of-tile errors.
- Shader Setup: crash when no material assigned
- Shader Setup material selection sync
- Implemented proper bidirectional sync:
  - Picking a material in Blender’s Material Properties updates the add-on.
  - Picking a material in the add-on updates Blender’s active material slot.
- Object Data Texture export reliability (DDS overwrite/selection logic)
  - Export now targets the correct root based on current selection/parent chain.
  - De-dupes by output filepath so a stale object can’t overwrite a good DDS with a width=0 DDS.
  - Adds guards to refuse writing DDS if computed width/height are invalid + adds debug print of which object actually exported.
- Custom Track Setup axis lock behavior
  - Stops the generated setup from needing manual Y-axis dragging to re-align with rollers.
- Track Array Tools tutorial link updated to GamerDesigns New Tutorial using this tool in its Alpha Build State.

V 10.0.17.61 (14.01.2026) Build: ALPHA TESTING (opt in in user Preferences)
------------------
- Added a new Vehicle Light Setup Tool (Static Light workflow):
  - In-Blender light creation, generates UV maps, paints vertex colors, generates a LightIntensity map (emission), and can create multifunction Light Types (must set your materials and assign the proper faces).
  - In-Blender validation to catch common setup issues before export / Giants Editor.
  - Supports testing & validation of manually built lights (requires UV maps + shader/staticLight minimum to be setup for manual built light detection to work).
- Track Array Tools:
  - Import Basic Oval Track Setup System (template import).
  - Generate Custom Track Setup System From Guides:
    - Generates the template-style curve and armature: "2. EDIT me" + "3. EXPORT me".
    - Builds the 100-bone chain (Bone, Bone.002 ... Bone.100) and applies the matching Spline IK constraint.
    - Curve generation is centered on the world origin axis without forcing the Z (height) axis.
  - Credits: "Created by DtapGaming and RMC Gamer Designs".
- Shader Setup / Simulator:
  - Material Type simulation behavior improved so visuals ignore UV map scaling correctly and act like Giants treats them.
- Export reliability:
  - Sanitizes '&' in object/material names during export to prevent broken .i3d files.
- Tools stability (Blender 5):
  - Fixed Motion Path and Vertex Color panels failing to draw due to missing Scene properties / operators.
- Updater quality-of-life:
  - "Skip this version" is now respected after using "Refresh Addon After Update".
  - "Undo Skip Version" restored in the bottom mini menu.

V 10.0.17.13 (08.01.2026) Build: ALPHA TESTING (opt in in user Preferences)
------------------
- My Color Library JSON sharing improvements for Decals:
  - Export now supports an optional ZIP bundle: JSON + copies of all decal images used by your saved library.
  - Import supports ZIP bundles and will copy decal images into your persistent add-on storage so decals keep working across sessions.
  - JSON import will also resolve relative decal paths (e.g. decals/yourImage.png) when importing from a shared folder.

V 10.0.17.12 (07.01.2026) Build: ALPHA TESTING (opt in in user Preferences)
------------------
- Updated Color Library How-To PDFs (Material Mode + XML Mode) with new UI screenshots, corrected callouts, and updated explanations. The How-To buttons open these PDFs from the /docs folder.
- My Color Library improvements:
  - Added "Sort by Selected Material" button (material icon) next to the Search / Sort A-Z / Reverse controls.
  - Fixed Name Column width slider behavior for My Color Library rows.
  - JSON Export/Import fixed (Blender 5): operators now use the correct file-browser helpers, so picking .json paths works reliably again.
- Decal workflow improvements (My Color Library):
  - Decal image path is now remembered per saved entry (persists across new Blender sessions and is included in JSON Export/Import).
  - Added a "Change Image" icon button (appears after the decal is set) to re-pick the decal image and re-save the path.
  - Decal entries show a small thumbnail preview in the swatch column; click it to open a larger preview popup.
  - Fixed "Clear all temporary material shader Nodes" so it removes preview nodes but does NOT unhook the decal image from Principled Base Color/Alpha.
- L10N / XML exports:
  - L10N export now generates a single appended bundle file containing both EN + DE blocks (l10nBundle).
  - Improved German translation fallback / no-op detection (reduces cases where English comes back unchanged with minor punctuation edits).
- Stability/UI fixes:
  - Fixed Blender 5 enable crash caused by a stray UI draw call at import time (NameError: box not defined).

V 10.0.17.11 (10.12.2025) Build: ALPHA TESTING (opt in in user Preferences)
------------------
- Added "Refresh Addon After Update" button in the main panel header to disable + re-enable the add-on (timed), purge sys.modules entries for io_export_i3d_reworked, and force a full UI redraw so drag-and-drop updates can be applied without restarting Blender.
- Added Modders Edge Tools & Cleanup utilities into the add-on (credit: RMC|GamerDesigns).
- Added "Material Tools" collapsible in the Material tab containing:
  - Replace Material A -> B
  - Material Cleanup
  (credit: RMC|GamerDesigns)
- Reorganized Material tab UI:
  - Added main "Shader Setup" collapsible for shader configuration UI
  - Refraction Map collapsible is now nested inside "Shader Setup"
  - Color Library sits below Refraction Map and above "Material Tools"
- Color Library improvements (credit baseline/idea: RMC|GamerDesigns; expanded/customized for REWORKED):
  - 3 tabs: My Color Library / Giants Library / Popular Color Library
  - Giants Library parses $data/shared/brandMaterialTemplates.xml (brand dropdown + color list)
  - Popular Color Library parses an XML shipped with the add-on (popular tractor/vehicle/platform palettes)
  - Selected panel shows GIANTS (sRGB), RGB (0-255), HEX, and copy buttons (Copy GIANTS (sRGB), Copy RGB, Copy HEX, Copy colorScale)
  - Added "Set Emission (Black)" button in Selected section
  - Import/Export sharing applies ONLY to My Color Library (Giants/Popular are not exportable)
  - User Preferences: Color Library list Name Column slider


V 10.0.17.10 (10.12.2025) Build: ALPHA TESTING (opt in in user Preferences)
------------------
- Added a Color Library Tool (credit for the baseline and Idea goes to RMC|GamerDesigns) but has been improved upon and now has 3 tabs of Libraries (User created/Giants Brands/Popular Color Library {colors are based off of hex colors from public documents so its possible some popular ones could be wrong but more likely they just dont look right in blenders lighting} )

V 10.0.17.9 (10.12.2025) Build: BETA TESTING (opt in in user Preferences)
------------------
- Added 4th Digit Build Number (Testing) build numbers
- Fixed Blender 5 panel draw issues (no more restart required after install/update).
- Removed all “Quit Blender” / restart-required logic from the add-on.
- Fixed shader Load behavior and material dropdown syncing when selecting meshes (including old .blend files).
- Added automatic conversion of legacy absolute customShader paths to portable $data/shaders (now allows Handing blend files off to co-modders without having to deal with fixing materials)
- Improved update/rollback behavior: update checks now default ON and user update settings persist across reinstall/rollback.
- Added a one-click button to enable Blender Allow Online Access when update checks are enabled but Blenders online internet access isnt.

V 10.0.16 (10.12.2025) Build: STABLE RELEASE
------------------
- Fixed Issue where error could occur if user selected the actual full collection in scene graph
- Fixed drawing issue for the material Template tool (assign vehicle shader materials preassigned from Giants)

V 10.0.15 (10.12.2025) Build: STABLE RELEASE
------------------
- Renamed Folder and Installer from io_export_i3d_10_0_11 to io_export_i3d_reworked
- Added prompt that warns user that the official "Giants" exporter is active and both can not be active concurrently - ability to disable Giants Version and enable this one with single button
- Added a warning prompt on install, that Blender needs to start a new session for addon to work - quit, save and quit, and cancel button for responses
- Added a warning prompt on disable Giants Official exporter, that Blender needs to start a new session for addon to work - quit, save and quit, and cancel button for responses
- Added a check on every start of a new blender session to ensure user did not re-enable Giants Official exporter while this exporter is active - Only one may be active at a time.
- Full rebuild to the UV Mapping tool (previously named Vehicle Array Tool) Now Rebuilt and Optimized for Farming Simulator 25 No longer has FS22 Material properties
- Added a "Snow Heap Mode" - REQUIRED to be enabled if doing Snow Heap Exporting (Roof Snow that Piles Up)
- Built the Delta Vertex Color Tool Into this build - Original by Fuxna & Redphoenix
- major Overhaul to Delta Vertex Color Tool to allow it to work on Newer and Older Blenders
- Added prompt that warns user if the "Delta Vertex Color Tool" is active and both can not be active concurrently - ability to disable Fuxna & Redphoenix version and enable this one with single button
- Added a "Delta Vertex Info tab" in the Tools tab of the Giants Panel with Links to Youtube Videos and credits to Fuxna & Redphoenix and a button to show new users where to find the Data Tab
- Panel renamed to Giants I3D Exporter REWORKED
- 

V 10.0.14 (8.12.2025) Build: ALPHA0 NOT STABLE
------------------
- Updated reworked version for Farming Simulator 25 By DTAPGAMING 

- Moved Game Installation Path browser into Preference addon menu - (this allows for a persistent game install location so you no longer have to select your install location every time you launch blender)
- Reworked GUI to better fit new persistent game install location features - If you set the wrong folder just go into Blender > Edit > Preferences > Add-ons > Giants I3D Exporter Tools Reworked> at the bottom is your install Location!
- Reworked Logic to allow all built-in tools to work with new persistent game install location - Just click the magnifying glass for shaders in material tab once you set the game install path it will work from then on out! 
<img width="458" height="241" alt="image" src="https://github.com/user-attachments/assets/131d6c50-f2b5-42f6-a3ca-59e0e2ba7ea7" />

You will need the game install location set to use the Material Templates as well 
<img width="458" height="241" alt="image" src="https://github.com/user-attachments/assets/e2e60ae8-67b6-4b54-80f7-a1ab20f899ae" />

- Added Emission Nullifier Option (no longer need to drag the slider of emissions to black or deal with annoyances in Giants Editor if you forgot) 
<img width="436" height="120" alt="image" src="https://github.com/user-attachments/assets/ea55136b-bdc4-4ec8-b56a-3a5471a01124" />

- Removed the "Game relative" and "Relative" path options from export Tab and built real logic into back end, no longer needs a users input to properly route file paths.

