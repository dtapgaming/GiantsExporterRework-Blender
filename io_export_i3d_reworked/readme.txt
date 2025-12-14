GIANTS Blender i3d exporter plugins
================================

Blender Addon Support:
----------------------
https://docs.blender.org/manual/en/latest/editors/preferences/addons.html#rd-party-add-ons


Change log
----------

10.0.0 (21.11.2024)
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



