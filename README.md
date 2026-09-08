# Meno

Meno tracks a coloured object through a webcam and uses its path to draw.
It uses Python, OpenCV, NumPy and PySide6.

## Run

Requires Python 3.10 or newer and a webcam. From the project directory:

```powershell
pip install .
python main.py
```

## Controls

Choose a camera index and click **Open camera**. Indices 0 through 4 are
available. Camera 0 opens at startup. Use the same button to reconnect after
a camera is disconnected.

The live feed stays on the left. **Canvas** and **Mask** show or hide the
previews on the right. Their positions are fixed.

Enable **Mask** and adjust the six HSV values until the object is the only
white shape. Hue ranges from 0 to 180. Saturation and value range from 0 to
255. The initial range detects blue objects. Settings reset when the app closes.

Move the object below the toolbar to draw. Hold it over a colour box to
select that drawing colour, or over **CLEAR** to erase the canvas. Move the
object out of view to end a stroke.

**Clear** also erases the canvas. **Save canvas** exports the drawing as PNG
or JPEG. The shortcuts are Ctrl+L and Ctrl+S.

The toolbar layout, palette, brush width, camera resolution and exposure
use fixed defaults. There are no movable panels, toolbar editor or saved
presets.

## Processing

The capture worker reads camera frames and sends them to the window.
The window passes each frame to `AirCanvas.process()`.

OpenCV mirrors the frame, converts BGR to HSV and thresholds the colour
range. Erosion, morphological opening and dilation remove noise. The
centroid of the largest contour supplies the pen position.

Positions inside the toolbar select a colour or clear the canvas. Positions
below it extend a stroke. Losing the object ends the stroke. New segments
are drawn into a persistent ink layer and copied onto the live frame.

The window displays the processed frame, canvas and binary mask. Qt draws
the toolbar over the live view using the same geometry as the pen hit detection.
The toolbar is absent from exported drawings.

## Files

* `meno/vision.py`: OpenCV processing and stroke storage.
* `meno/camera.py`: Camera access and fixed capture defaults.
* `meno/capture.py`: Camera worker and frame delivery.
* `meno/hud.py`: Toolbar geometry and palette used by the processing code.
* `meno/ui/window.py`: Fixed layout, controls and frame handling.
* `meno/ui/video_view.py`: Image display and toolbar painting.
* `meno/config.py`: Bundled asset paths.
* `meno/assets/themes/default.json`: Fixed toolbar definition.
* `meno/__main__.py`: Application setup.

## Windows build

Install the build tool and run the build script:

```powershell
pip install pyinstaller
.\build.ps1
```

The script uses `meno.spec` to produce `dist\Meno\Meno.exe` with its runtime
files. Keep the entire `dist\Meno` directory together when distributing it.
If Inno Setup is installed, the script also builds an installer using
`installer/meno.iss`.

## Limitations

Only one object is tracked. A larger object within the same colour range
can take over tracking. Crossing a toolbar button triggers it immediately.
Camera drivers may ignore the requested resolution or exposure.

## License

[MIT](LICENSE).
