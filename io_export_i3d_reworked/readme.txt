CHANGE LOGS

V 10.0.17.11 (10.12.2025) Build: ALPHA TESTING (opt in in user Preferences)
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

V 10.0.17.10 (10.12.2025) Build: BETA TESTING (opt in in user Preferences)
- Added a Color Library Tool (credit for the baseline and Idea goes to RMC|GamerDesigns) but has been improved upon and now has 3 tabs of Libraries (User created/Giants Brands/Popular Color Library {colors are based off of hex colors from public documents so its possible some popular ones could be wrong but more likely they just dont look right in blenders lighting} )

V 10.0.17.9 (10.12.2025) Build: BETA TESTING (opt in in user Preferences)
- Added 4th Digit Build Number (Testing) build numbers
- Fixed Blender 5 panel draw issues (no more restart required after install/update).
- Removed all “Quit Blender” / restart-required logic from the add-on.
- Fixed shader Load behavior and material dropdown syncing when selecting meshes (including old .blend files).
- Added automatic conversion of legacy absolute customShader paths to portable $data/shaders (now allows Handing blend files off to co-modders without having to deal with fixing materials)
- Improved update/rollback behavior: update checks now default ON and user update settings persist across reinstall/rollback.
- Added a one-click button to enable Blender Allow Online Access when update checks are enabled but Blenders online internet access isnt.

V 10.0.16 (10.12.2025) Build: STABLE RELEASE
- Fixed Issue where error could occur if user selected the actual full collection in scene graph
- Fixed drawing issue for the material Template tool (assign vehicle shader materials preassigned from Giants)

V 10.0.15 (10.12.2025) Build: STABLE RELEASE
- Renamed Folder and Installer from io_export_i3d_10_0_11 to io_export_i3d_reworked
- Added prompt that warns user that the official "Giants" exporter is active and both can not be active concurrently - ability to disable Giants Version and enable this one with single button
- Added a warning prompt on install, that Blender needs to start a new session for addon to work - quit, save and quit, and cancel button for responses
- Added a warning prompt on disable Giants Official exporter, that Blender needs to start a new session for addon to work - quit, save and quit, and cancel button for responses
- Added a check on every start of a new blender session to ensure user did not re-enable Giants Official exporter while this exporter is active - Only one may be active at a time.
- Full rebuild to the UV Mapping tool (previously named Vehicle Array Tool) Now Rebuilt and Optimized for Farming Simulator 25 No longer has FS22 Material properties
- Added a "Snow Heap Mode" - REQUIRED to be enabled if doing Snow Heap Exporting (Roof Snow that Piles Up)
- Built the Delta Vertex Color Tool Into this build - Original by Fuxna & Redphoenix
- Major Overhaul to Delta Vertex Color Tool to allow it to work on Newer and Older Blenders
- Added prompt that warns user if the "Delta Vertex Color Tool" is active and both can not be active concurrently - ability to disable Fuxna & Redphoenix version and enable this one with single button
- Added a "Delta Vertex Info tab" in the Tools tab of the Giants Panel with Links to Youtube Videos and credits to Fuxna & Redphoenix and a button to show new users where to find the Data Tab

V 10.0.14 (8.12.2025) Build: ALPHA0 NOT STABLE
- Updated reworked version for Farming Simulator 25 By DTAPGAMING
- Moved Game Installation Path browser into Preference addon menu - (this allows for a persistent game install location so you no longer have to select your install location every time you launch blender)
- Reworked GUI to better fit new persistent game install location features - If you set the wrong folder just go into Blender > Edit > Preferences > Add-ons > Giants I3D Exporter Tools Reworked> at the bottom is your install Location!
- Reworked Logic to allow all built-in tools to work with new persistent game install location - Just click the magnifying glass for shaders in material tab once you set the game install path it will work from then on out!
You will need the game install location set to use the Material Templates as well
- Added Emission Nullifier Option (no longer need to drag the slider of emissions to black or deal with annoyances in Giants Editor if you forgot)
- Removed the "Game relative" and "Relative" path options from export Tab and built real logic into back end, no longer needs a users input to properly route file paths.
