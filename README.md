# Meno — Air Canvas

Meno tracks a coloured object in a webcam feed and draws a stroke along the
path it takes, turning any sufficiently saturated object into a brush. Input is
the camera only; no mouse or touchscreen is used while drawing.

Implemented with Python, OpenCV, NumPy and PySide6. It uses classical computer
vision. colour thresholding and contour analysis — with no machine-learning
model and no training data.

<!-- Add a demo GIF here once recorded, e.g.:
![Demo](docs/demo.gif)
-->

---

## Features

- **Colour tracking** — segments the pen object in HSV space and follows the
  centroid of the largest matching blob.
- **Live HSV tuning** — six sliders adjust the colour thresholds while the
  application runs, for different objects and lighting conditions.
- **Named presets** — threshold sets can be saved and recalled, so the sliders
  do not have to be retuned each session.
- **On-screen toolbar** — holding the pen over the strip at the top of the
  frame switches colour or clears the canvas.
- **Editable HUD** — the toolbar is defined by a JSON file. Buttons can be
  moved and resized by dragging, or edited by hand in
  `%APPDATA%\Meno\hud.json`.
- **Pen-up detection** — moving the object out of frame ends the current
  stroke, so separate strokes are not joined by a connecting line.
- **Three synchronised views** — the live feed with the drawing overlaid, the
  paint canvas alone, and the binary mask used for threshold tuning.
- **Exposure control** — locks the camera exposure, which raises the frame rate
  in low light and keeps colours constant. See
  [Camera and frame rate](#camera-and-frame-rate).
- **Canvas export** — saves the artwork as PNG or JPEG, without the toolbar.

---

## How it works

Each frame runs through the same pipeline:

| # | Stage | What happens |
|---|-------|--------------|
| 1 | **Capture** | A worker thread reads a frame from the webcam and passes it to the GUI thread by signal. Capture is off the GUI thread because `cap.read()` blocks. |
| 2 | **Mirror** | The frame is flipped horizontally, so moving the object right moves the pointer right. |
| 3 | **Colour segmentation** | BGR is converted to HSV and thresholded with `inRange()`. HSV separates hue from brightness, which makes thresholding more tolerant of lighting changes than raw BGR. |
| 4 | **Noise removal** | Erode → morphological open → dilate with a 5×5 kernel. Speckles are removed; the target blob keeps its original size. |
| 5 | **Blob tracking** | `findContours()` with `RETR_EXTERNAL`, then the largest contour by area. Image moments (`m10/m00`, `m01/m00`) give its centroid, which is the pen tip for this frame. |
| 6 | **Interpret** | A tip inside the toolbar band is a button press (clear, or select a colour); below it, the point extends the stroke in progress. |
| 7 | **Render** | The new segment is drawn once into a persistent ink layer, which is then composited onto the frame in a single masked copy. |

### Stroke storage

Points are stored as one `deque` per stroke, grouped into one list per palette
colour. `maxlen` bounds the memory a long session can use: old points fall off
the tail. When the pen leaves the frame a fresh deque is appended to each list,
which is what prevents two separate strokes from being joined by one straight
line.

Strokes are also kept as pixels, in an ink layer plus a mask marking where ink
exists. Each segment is drawn into that layer once, when it is made. Replaying
every stored point onto every frame instead would cost O(points drawn so far)
per frame, so per-frame cost would grow for the duration of the session.

---

## Quick start

**Requirements:** Python 3.10+ and a webcam.

```bash
# 1. Clone
git clone https://github.com/klaywork2005/meno.git
cd meno

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python main.py
```

`python -m meno` is equivalent. After `pip install -e .` the `meno` command is
also available.

One window opens, containing the live feed, the paint canvas, the mask and the
control panel. The last three are dock widgets and can be hidden from the
**View** menu; their visibility is remembered between sessions.

---

## Using it

### 1. Tune the colour first

Hold the object in front of the camera and watch the **Mask** view. Adjust the
six sliders until the object is the only solid white shape in it:

- **Hue** — the target colour (0–180 in OpenCV, half the usual 0–360°). Set the
  lower and upper pair to bracket the object's hue.
- **Saturation** — colour intensity. Raise the lower bound to reject greys and
  skin tones.
- **Value** — brightness. Raise the lower bound to reject shadows.

The shipped presets cover blue, green, red and yellow objects under indoor
light. **Save as...** stores the current values under a name.

### 2. Draw

| Action | How |
|--------|-----|
| Draw | Move the object anywhere below the toolbar strip |
| Change colour | Hold the object over the blue / green / red / yellow box |
| Clear the canvas | Hold the object over the **CLEAR** box, or press <kbd>Ctrl</kbd>+<kbd>L</kbd> |
| End a stroke | Move the object out of frame, or out of the colour range |
| Save the drawing | <kbd>Ctrl</kbd>+<kbd>S</kbd> |
| Edit the toolbar | <kbd>Ctrl</kbd>+<kbd>E</kbd>, then drag a button to move it or its edge to resize it |
| Quit | <kbd>Ctrl</kbd>+<kbd>Q</kbd> |

---

## Project structure

```
meno/
├── main.py                 # Entry point shim; also the PyInstaller entry script
├── meno/
│   ├── __main__.py         # QApplication setup and crash handler
│   ├── camera.py           # Device open, configure and enumerate
│   ├── capture.py          # Capture worker thread
│   ├── vision.py           # The per-frame pipeline (AirCanvas)
│   ├── hud.py              # Toolbar layout model, loaded from JSON
│   ├── config.py           # File locations and persisted settings
│   ├── ui/
│   │   ├── window.py       # Main window: docks, menus, controls
│   │   └── video_view.py   # Frame display widget and HUD painting/editing
│   └── assets/themes/      # Bundled default HUD layout
├── tools/make_icon.py      # Generates meno/assets/meno.ico
├── meno.spec               # PyInstaller build configuration
├── installer/meno.iss      # Inno Setup installer script
├── build.ps1               # Builds the executable and the installer
├── pyproject.toml
├── requirements.txt
├── LICENSE                 # MIT
└── README.md
```

The dependency direction is one-way: `ui/` imports from `vision.py`, `hud.py`,
`camera.py` and `config.py`, and none of those import from `ui/`. `AirCanvas`
performs no I/O and holds no Qt references, so the front end can be replaced
without changing the pipeline.

---

## Design notes

- **HSV rather than BGR.** In BGR, all three channels carry brightness, so a
  lighting change moves the numeric definition of a colour. HSV isolates
  brightness in the `value` channel, so a hue range remains valid across a
  wider set of conditions.
- **Largest contour.** Other objects sharing the target colour are usually
  smaller or further away. The failure mode is graceful: a larger object of
  that colour makes the pointer jump, and tightening the saturation bound
  corrects it.
- **Moments rather than the bounding-box centre.** The centroid is stable under
  rotation and partial occlusion; a bounding box shifts as the silhouette
  changes shape.
- **One stroke list per colour.** Rendering is a straightforward loop over
  colour, stroke and point, and clearing is a single reset rather than a
  filtered delete.
- **Fractional HUD coordinates.** Button positions are stored as fractions of
  the frame, so one layout is correct at any capture resolution and switching
  cameras cannot place a button off-screen.
- **Capture on a worker thread.** `cap.read()` blocks until the camera produces
  a frame. Calling it on the GUI thread leaves that thread unable to repaint or
  handle input for most of each frame interval.

---

## Building a Windows .exe and installer

Two stages. `build.ps1` runs both:

```powershell
.\build.ps1                  # exe + installer
.\build.ps1 -SkipInstaller   # exe only
.\build.ps1 -Clean           # delete build/ and dist/ first
```

### Stage 1 — the executable (PyInstaller)

`pyinstaller meno.spec` produces **`dist\Meno\`**: `Meno.exe` plus an
`_internal` directory containing Qt, OpenCV and a private copy of Python. That
directory is a complete application and runs on a machine with no Python
installed. Approximately 183 MB.

The configuration is in [`meno.spec`](meno.spec). Four points determine whether
the build works:

- **The entry point is `main.py`, not `meno/__main__.py`.** PyInstaller
  executes the entry script as a top-level module, so a module using relative
  imports fails at startup with *"attempted relative import with no known
  parent package"*.
- **One directory, not `--onefile`.** A onefile executable unpacks the whole
  bundle to a temporary directory on every launch, which delays startup and is
  a common antivirus heuristic trigger.
- **Assets are bundled to `assets/`**, matching where `config.asset_path()`
  resolves under `sys._MEIPASS`. Both must be changed together.
- **Unused Qt modules, OpenCV's ffmpeg and Qt's software OpenGL are excluded**,
  which removes about 50 MB that is unreachable from this application.

### Stage 2 — the installer (Inno Setup)

Inno Setup is a separate download:

```powershell
winget install JRSoftware.InnoSetup
```

`build.ps1` locates `ISCC.exe` and compiles
[`installer/meno.iss`](installer/meno.iss) into
**`dist\installer\Meno-0.1.0-Setup.exe`**, a Windows installer with a Start
menu entry, an optional desktop icon and an uninstaller. If Inno Setup is
absent the script completes stage 1 and reports what is missing.

The installer requests no administrator rights by default and can install into
the user's own profile; a per-machine install into Program Files is selectable
on the first page.

### Releasing a new version

The version appears in three files and must be changed in all of them:
`pyproject.toml`, `installer/version_info.txt` and the `AppVersion` line in
`installer/meno.iss`. `AppId` must not change: it is how Windows recognises an
existing installation and upgrades it in place.

### SmartScreen

The output is unsigned, so the first run produces a *"Windows protected your
PC"* dialog requiring *More info → Run anyway*. This requires a code-signing
certificate to remove; no build setting affects it.

---

## Camera and frame rate

The status bar shows the measured frame rate. A rate well below 30 is usually
caused by **auto-exposure**: in low light a webcam lengthens its integration
time to brighten the image, and a frame held open for 1/12 s can only be
delivered twelve times a second. No software setting can retrieve frames the
camera has not captured.

The **Lock exposure** checkbox in the control panel pins the exposure. It is
enabled by default. On a typical webcam in an average room it is the difference
between roughly 13 fps and 30 fps. The adjacent slider trades brightness
against frame rate; disabling the checkbox restores automatic exposure.

A locked exposure also holds the colours constant, which the HSV thresholds
depend on.

---

## Known limitations & possible next steps

- Only one object is tracked at a time — the largest blob wins.
- Hover-to-click has no dwell timer, so moving the pen across the toolbar on
  the way elsewhere can trigger a button.
- Switching cameras takes one to two seconds, during which no frames arrive.
- Exposure control is implemented for DirectShow and V4L2 property semantics;
  other backends may ignore it.
- Possible extensions: adjustable brush thickness, an undo stack, loading saved
  artwork, and replacing colour tracking with a hand-landmark model such as
  MediaPipe.

---

## License

Released under the [MIT License](LICENSE).
