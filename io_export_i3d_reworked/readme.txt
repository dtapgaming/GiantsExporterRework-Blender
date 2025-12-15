GIANTS Blender i3d exporter plugins
================================

Blender Addon Support:
----------------------
https://docs.blender.org/manual/en/latest/editors/preferences/addons.html#rd-party-add-ons


Change log
----------
10.0.13 (15.12.2024)
------------------

New: Built-in Update Checker (Stable/Beta/Alpha) 
New: Prompts user at start up if there is an update available 
New: allows user to set build type in user preferences (Stable/Beta/Alpha) 
New: Logic to force (Beta/Alpha) channel Swapping because the version# between these will always be the same and update logic wouldn't allow swapping because version# was identical
New: Manual update added to user pref menu 
New: Activate online access (for all of blender) added to GUI if user has it disabled but enables updates in the User pref settings for this addon 
*** *** *** Fixed: Shader Import Button *** *** *** 
Tweak: Automatic Game-Relative Export Path Handling rework to handle shader export better
Tweak: Delta → Vertex Color Tool Integration tools panel overhaul (now collapsible and in layout is better) 
Tweak: MAJOR overhaul to the conflict detection and user prompt system now disables both addons at once if active to prevent needing to restart blender twice 

V 10.0.12 (10.12.2025)
------------------
Renamed Folder and Installer from io_export_i3d_10_0_11 to io_export_i3d_reworked
Added prompt that warns user that the official "Giants" exporter is active and both can not be active concurrently - ability to disable Giants Version and enable this one with single button
Added a warning prompt on install, that Blender needs to start a new session for addon to work - quit, save and quit, and cancel button for responses
Added a warning prompt on disable Giants Official exporter, that Blender needs to start a new session for addon to work - quit, save and quit, and cancel button for responses
Added a check on every start of a new blender session to ensure user did not re-enable Giants Official exporter while this exporter is active - Only one may be active at a time.
Full rebuild to the UV Mapping tool (previously named Vehicle Array Tool) Now Rebuilt and Optimized for Farming Simulator 25 No longer has FS22 Material properties
Added a "Snow Heap Mode" - REQUIRED to be enabled if doing Snow Heap Exporting (Roof Snow that Piles Up)
Built the Delta Vertex Color Tool Into this build - Original by Fuxna & Redphoenix
major Overhaul to Delta Vertex Color Tool to allow it to work on Newer and Older Blenders
Added prompt that warns user if the "Delta Vertex Color Tool" is active and both can not be active concurrently - ability to disable Fuxna & Redphoenix version and enable this one with single button
Added a "Delta Vertex Info tab" in the Tools tab of the Giants Panel with Links to Youtube Videos and credits to Fuxna & Redphoenix and a button to show new users where to find the Data Tab
Panel renamed to Giants I3D Exporter REWORKED

V 10.0.11 (8.12.2025) Build: ALPHA1
------------------
- Updated reworked version for Farming Simulator 25 By DTAPGAMING 

- Moved Game Installation Path browser into Preference addon menu - (this allows for a persistent game install location so you no longer have to select your install location every time you launch blender)
- Reworked GUI to better fit new persistent game install location features - If you set the wrong folder just go into Blender > Edit > Preferences > Add-ons > Giants I3D Exporter Tools Reworked> at the bottom is your install Location!
- Reworked Logic to allow all built-in tools to work with new persistent game install location - Just click the magnifying glass for shaders in material tab once you set the game install path it will work from then on out! 
- Added Emission Nullifier Option (no longer need to drag the slider of emissions to black or deal with annoyances in Giants Editor if you forgot)
- Removed the "Game relative" and "Relative" path options from export Tab and built real logic into back end, no longer needs a users input to properly route file paths.


10.0.0 (21.11.2024) - GIANTS OFFICIAL (Current release)
------------------
-Initial version for Farming Simulator 25


9.1.0 (04.10.2023)
------------------
-Fixed a bug with the cpu mesh setting where the flag was read from the UI instead of from the objects
-Increased the precision of floating point settings to six decimal positions
-Added support for double sided shape flag
-Added support for the receive and cast shadows flags
-Added support for the rendered in viewports flag
-Fixed Vertex Colors export (supported Blender versions >= 3.2)
-Added features to Vertex Color Tool (supported Blender versions >= 3.2)
-Fixed Material Attributes (Custommap and CustomParameter are only written if different to the default values in i3d file. new i3dConverter.exe)
-Fixed moving UV despite use_uv_select_sync is set (in Vehicle material array tool)
-Added weighted normal modifier support
-Fixed Xml values are only written if they are different to the default value
-Performance increased (less string comparisons)
-Fixed crash when undoing Object Data from Curve
-Visibility of nodes are using the eye button in blender scenegraph
-Fixed export with "joints" set
-Added export of reflectionmap when in blender a material surface with BSDF is used
-Fixed rotation calculation. sin(180) is 0 not 1e-10
-Fixed custom bounding volume calculation
-Added bone constraint "Child Of" support to move the bone to corresponding parent in scenegraph


9.0.1 (26.11.2021)
------------------
-Renamed Shader tab to Material tab
-Added newest shader parameters to Material tab
-Reworked display of shader parameters
-Reworked Predefines, now shows last selected and if it was modified or not
-Reworked selection logic
-Added "Auto Assign" checkbox, for automated load and save of attributes
-Added bumpDepth export parameter from normal map shader node
-Many minor changes and bugfixes
-Added blender version "3.0"
-Material/Shader path can use $data/shader notation
-Fixed Collision mask
-Cast Shadows/Receive Shadows are now selected when using predefined settings 

9.0.1 (22.07.2021)
------------------
-Support for LTS 2.83 and LTS 2.93
-Bugfix: Hidden objects have now same behaviour like non hidden objects
-Added Vertex Color Tool
-Added align Y-axis Tool
-Added vehicle array Tool
-Added binary export as default option
-Added dedicated bit mask editor
-minor changes and bugfixes

9.0.1 (03.09.2020)
------------------
-Added custom material color array support for vehicleShader.xml
-Added Motion Path Tool
-Added Motion Path from Object Tool

9.0.0 (04.06.2020)
------------------
- FS22 Update
    -Added sharp Edge support without modifier
    -Added Merge Children
    -Added multiple material support for Merge Groups and Merge Children
    -Added uvDensity calculation
    -Added .DDS file export

    -Reworked path handling 
    -Reworked handling of blender default shaders
    -Reworked the user feedback output, now visible in the Info View

-GUI update
    -Relocated Export Game Relative Path
    -Added Merge Children GUI elements(only available for empty objects)
    -Added Export DDS GUI elements, this includes dimensions, type, filepath and children shapes)
    -Added "Set Game Shader Path" button to the shader tab, automatically fills in the Game Shader path
    -Added Load Shader Button

8.1.0 (14.05.2020)
------------------
- Blender 2.82 version
- GUI changes: 
    -Removed "File > Export" option, export options only available in the "3D Viewport"
    -Real time Index Path and Node Name display with xml update export checkbox
    -Updated Export Options
    -Added "Game Location" for game relative path export
    -Added "XML config. Files" for multiple XML file selection
    -Updated "Output File" behavior according to selected options
    -Added Predefined option for the Attributes similar to the Maya exporter
    -Updated Attribute options
    -Added "Shader"-Tab similar to the Maya exporter, to select shader settings from existing Shader xml files.

- I3DExporter changes:
    -Added Animation support
    -Added Skinning support
    -Added Merge Group support
    -Added file path support options: Absolute path, Relative to *.i3d file path, Relative to Game Installation path
    -Added XML Update support
    -Added Predefined Attribute options
    -Added option to use existing Shader options
    -Removed Axis Orientation "Keep Axis" option

7.1.0 (06.12.2017)
------------------
- Added Blender 2.79 support



