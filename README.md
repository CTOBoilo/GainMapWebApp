# Gain Map JPEG Tool

A simple web app that turns your HDR and SDR exports into a single **ISO 21496-1 gain map JPEG** — one file that looks great on regular screens and lights up on HDR-capable displays (iPhone 12+, recent MacBooks, iPads, Chrome on HDR monitors, etc.).

Inspired by [WebSharpPro](https://gregbenzphotography.com/photography-tutorials/websharppro-hdr-jpegs/) by **Greg Benz** — this is an open, self-hosted alternative for photographers who work outside the Lightroom Classic ecosystem.

> **For photographers, by a photographer.** No Lightroom plugin required. No cloud. Runs entirely on your own computer.

---

## What you get

- Drag & drop one HDR TIFF + one SDR TIFF → get a gain map JPEG
- **Batch mode** — drop a bunch of HDR/SDR pairs, get a ZIP back
- Live proofing preview before you download
- Optional resize, sharpening, EXIF preservation, and HDR metadata
- Works at full resolution (100MP+ Hasselblad files tested)

---

## Quick start

You need a Mac or Windows PC. Total install time: about 5 minutes.

### Step 1 — Install the prerequisites (one-time)

You need two things on your system before the app will run:

**1. Python 3.11 or newer** — the language the app is written in.
- **macOS:** `brew install python@3.12` in Terminal, or [download the installer](https://www.python.org/downloads/).
- **Windows:** Download from [python.org](https://www.python.org/downloads/). **When installing, check the box "Add Python to PATH".**

**2. exiftool** — handles photo metadata.
- **macOS:** `brew install exiftool` in Terminal.
- **Windows:** Download the Windows executable from [exiftool.org](https://exiftool.org/), rename `exiftool(-k).exe` to `exiftool.exe`, and place it in `C:\Windows` (or anywhere on your `PATH`).

### Step 2 — Download the app

Click the green **Code** button at the top of this page → **Download ZIP**. Unzip it wherever you like (Desktop, Documents, etc.).

If you prefer Git:

```bash
git clone https://github.com/CTOBoilo/GainMapWebApp.git
```

### Step 3 — Run the setup script

Open the unzipped folder.

- **macOS:** Open Terminal in this folder (right-click in Finder → New Terminal at Folder) and run:
  ```bash
  ./setup.sh
  ```
- **Windows:** Double-click `setup.bat`.

The script will check your Python install, create a self-contained Python environment, and install all required libraries. Takes about a minute.

### Step 4 — Start the app

- **macOS:** `./run.sh` in Terminal
- **Windows:** Double-click `run.bat`

Then open your browser at **http://127.0.0.1:5000** (or **5001** if AirPlay is using 5000 on Mac).

To stop the app, press `Ctrl+C` in the terminal window (or just close it).

---

## How to use it

### Single mode

1. Drag your HDR TIFF into the **HDR Source** drop zone.
2. Drag your SDR TIFF into the **SDR Source** drop zone.
3. Pick the SDR color space (sRGB, Display P3, Adobe RGB, or ProPhoto RGB) — must match what you exported from your editor.
4. Open **Options** if you want to resize, sharpen, or tweak metadata.
5. Click **Create Gain Map JPEG**.
6. Review the proofing page (SDR baseline + gain map + final output).
7. Hit **Download**.

### Batch mode

Click the **Batch** toggle at the top.

Name your files with `_hdr` and `_sdr` suffixes so the app can pair them automatically. Example:

```
sunset_001_hdr.tif    pairs with    sunset_001_sdr.tif
beach_002_hdr.tif     pairs with    beach_002_sdr.tif
portrait_003_hdr.tif  pairs with    portrait_003_sdr.tif
```

Drop all HDR files into the HDR drop zone, all SDR files into the SDR drop zone, pick your options, hit submit. You'll get a live progress page and a single ZIP with all the gain map JPEGs when done.

---

## File requirements

| Input | Format | Notes |
|-------|--------|-------|
| **HDR** | Linear 32-bit float TIFF | Display P3 gamut. Values > 1.0 represent HDR highlights. |
| **SDR** | 16-bit TIFF | Tone-mapped. Color space: sRGB, Display P3, Adobe RGB, or ProPhoto RGB. |

**Both files must have identical pixel dimensions.** Export both at the same resolution from your editor (Lightroom, Capture One, Photoshop, etc.).

There's no upload size limit — full-resolution 100MP+ TIFFs are fine. Each pair takes about 25 seconds to process on a modern Mac.

---

## Workflow tip — exporting from Lightroom Classic

1. Edit your image with Lightroom's HDR controls enabled.
2. Export **two versions** with the same filename stem:
   - **HDR**: 32-bit float, linear, P3 gamut → `sunset_001_hdr.tif`
   - **SDR**: 16-bit, tone-mapped, sRGB / P3 / Adobe RGB → `sunset_001_sdr.tif`
3. Same pixel dimensions for both.
4. Drop them into the app.

---

## Output

A standard `.jpg` file that:

- **Looks correct on every device** — non-HDR screens just see the SDR baseline.
- **Lights up on HDR displays** — iPhone 12 and newer, iPad Pro, M-series MacBooks, recent Samsung phones, HDR-capable browsers (Chrome, Safari).
- **Preserves your EXIF** — camera, lens, exposure, GPS — all carried over.
- **Embedded Image P3 ICC profile** for accurate color.

Drop the JPEG into Apple Photos, Instagram, your website, or anywhere that accepts JPEG. HDR-capable viewers will show the full dynamic range automatically.

---

## Options reference

| Option | What it does | Default |
|--------|-------------|---------|
| **JPEG Quality** | Quality for both baseline and gain map (1–100) | 95 |
| **Resize output** | Downscale to a target long edge before saving | Off |
| **Long edge (px)** | Target length of the longest side when resizing | 2160 |
| **Sharpen amount** | Output sharpening to recover detail lost to downscaling (0–500) | 100 |
| **Preserve EXIF** | Copy camera/lens/GPS metadata from SDR source | On |
| **XMP Directory Item Semantic** | Label Primary + GainMap inside the JPEG container | On |
| **CCV luminance metadata** | Write actual luminance values (nits) for HDR viewers | On |

---

## Troubleshooting

**"Access denied" or 403 error when opening http://127.0.0.1:5000**
macOS AirPlay Receiver claims port 5000. The app automatically retries on 5001 — just try **http://127.0.0.1:5001**. You can also disable AirPlay Receiver in System Settings → General → AirDrop & Handoff.

**"exiftool not found" error during processing**
exiftool isn't installed or isn't on your `PATH`. Re-check Step 1.

**The app says "Python is not installed" but I installed it**
On Windows, you probably forgot to check "Add Python to PATH" during install. Re-run the Python installer and tick that box.

**HDR JPEG shows banding in skies**
This is a known limitation of 8-bit gain map storage. The app already minimizes this by computing the gain map at full resolution before any downscale. If banding is still bothering you, export your HDR at full resolution and skip the resize option.

**Browser doesn't show HDR**
Your display has to be HDR-capable and the viewer has to support gain map JPEGs. Confirmed working: iPhone 12+, iPad Pro, M-series MacBooks (in Apple Photos and Safari), Chrome on HDR monitors. Confirmed *not* working: Firefox (as of early 2026), older Windows 10 PCs.

---

## Updating to a new version

When a new version is released, either:

- Re-download the ZIP from GitHub and re-run `setup.sh` / `setup.bat`, **or**
- If you cloned with git: `git pull` then re-run setup.

Your settings are stateless (nothing is stored between runs), so updates are safe.

---

## Privacy & data

Everything runs **locally on your computer**. No file ever leaves your machine. No analytics, no telemetry, no accounts. The app processes your files and discards them immediately after you download the result.

---

## For developers

- **Stack:** Python 3.12, Flask, NumPy, Pillow, [hdr-conversion](https://github.com/Jackchou00/hdr-conversion), exiftool
- **Architecture:** see [app.py](app.py) for routes, [processing.py](processing.py) for the image pipeline
- **PEP8 with camelCase variables.** Yes, we know — see the project rules.

Run in development mode:

```bash
source venv/bin/activate
python app.py
```

To bind to your local network (for iPad access over WiFi), edit the bottom of `app.py`:

```python
app.run(host="0.0.0.0", debug=False, port=port)
```

For production internal hosting, run behind **gunicorn** + **nginx**.

---

## Credits

- **Greg Benz** — [WebSharpPro](https://gregbenzphotography.com/photography-tutorials/websharppro-hdr-jpegs/) and the HDR JPEG workflow that inspired this project. His tutorials are essential reading for anyone working with gain map JPEGs.
- [hdr-conversion](https://github.com/Jackchou00/hdr-conversion) — the underlying ISO 21496-1 reader/writer
- [exiftool](https://exiftool.org/) — Phil Harvey's metadata Swiss army knife

---

## License

MIT — do whatever you want with it.
