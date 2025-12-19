* * * *If you want Updates without having to come to this page: __**Activate the Update checker**__ in the user preferences when you set your game path!


*****IMPORTANT: 
DO NOT DOWNLOAD FROM HERE <img width="604" height="111" alt="image" src="https://github.com/user-attachments/assets/50efcc9c-4248-47a9-99a9-af22115e1c42" />

Instead Download from here <img width="393" height="463" alt="image" src="https://github.com/user-attachments/assets/db06d9ab-8703-4640-a9b9-9d27270f1a4c" />


or it wont work!!!

**Designed for Blender 4.3 and above. May not work in full on earlier versions but can be installed on 4.0+.

Installation - drag the Zip and drop it into blenders Viewport. You may be prompted to disable conflicting addons (there are 2) to use this addon you MUST disable both if you have them (they are built into this addon so you wont be missing them they are just included).
Deactivate the first one if needed you will then be prompted to quit blender, your choice to save and quit or just quit. relaunch blender with your Icon on the desktop, If you are then prompted to deactivate the second one do so and then quit once more.
(if none of the conflicting mods were active you will still need to quit blender at least once with its corresponding pop up to fully activate this addon)

Now that the addon is installed open your side panel (Shortcut N) then click on the Giants I3D Exporter REWORKED tab
 
<img width="280" height="815" alt="image" src="https://github.com/user-attachments/assets/14c23bff-7f51-4c6c-8fc3-5354966b1892" />

 then click 
 
<img width="230" height="29" alt="image" src="https://github.com/user-attachments/assets/d5223f58-0857-4f6a-b677-a0cc41ab028a" />

 you will get a Pop-Up 

<img width="860" height="634" alt="image" src="https://github.com/user-attachments/assets/e9c09505-f756-40e2-82a2-d14ae7f97cfd" />

set your game installation path at the bottom

<img width="681" height="86" alt="image" src="https://github.com/user-attachments/assets/9bb67335-a3de-4e87-8a0a-c18c90a53d81" />

then close this window and all of the warnings will go away
 
<img width="297" height="642" alt="image" src="https://github.com/user-attachments/assets/77e267a2-3894-48cd-ae06-ebd74514a31a" />



Change log
----------
10.0.14 (16.12.2025)
-----------------
-Fixed Backend issue caused by "forced (Beta/Alpha) channel Swapping", removed this feature, You can still select the channel you wish to use but each channel will now have a different version Number instead.

10.0.13 (15.12.2025)
-----------------
- New: Built-in Update Checker (Stable/Beta/Alpha)
- New: Prompts user at start up if there is an update available
- New: allows user to set build type in user preferences (Stable/Beta/Alpha)
- New: Logic to force (Beta/Alpha) channel Swapping because the version# between these will always be the same and update logic wouldn't allow swapping because version# was identical
- New: Manual update added to user pref menu
- New: Activate online access (for all of blender) added to GUI if user has it disabled but enables updates in the User pref settings for this addon
- Fixed: Shader LOAD Button - Now reloads all values of the previously applied custom attributes
- Tweak: Automatic Game-Relative Export Path Handling rework to handle shader export better
- Tweak: Delta → Vertex Color Tool Integration tools panel overhaul (now collapsible and in layout is better)
- Tweak: MAJOR overhaul to the conflict detection and user prompt system now disables both addons at once if active to prevent needing to restart blender twice


V 10.0.12 (10.12.2025)
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

V 10.0.11 (8.12.2025)
------------------
- Updated reworked version for Farming Simulator 25 By DTAPGAMING 

- Moved Game Installation Path browser into Preference addon menu - (this allows for a persistent game install location so you no longer have to select your install location every time you launch blender)
- Reworked GUI to better fit new persistent game install location features - If you set the wrong folder just go into Blender > Edit > Preferences > Add-ons > Giants I3D Exporter Tools Reworked> at the bottom is your install Location!
- Reworked Logic to allow all built-in tools to work with new persistent game install location - Just click the magnifying glass for shaders in material tab once you set the game install path it will work from then on out! 
You will need the game install location set to use the Material Templates as well 
- Added Emission Nullifier Option (no longer need to drag the slider of emissions to black or deal with annoyances in Giants Editor if you forgot) 
<img width="436" height="120" alt="image" src="https://github.com/user-attachments/assets/ea55136b-bdc4-4ec8-b56a-3a5471a01124" />

- Removed the "Game relative" and "Relative" path options from export Tab and built real logic into back end, no longer needs a users input to properly route file paths.


Please Note: This is an Alpha Build so there will probably be bugs and maybe even some base features that broke I pre-alpha tested a lot of the features but I haven't tested everything like vertex painting and more complex things as I should have changed anything that broke those (in theory)
