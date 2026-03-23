# Gain Map JPEG Tool

A web application for creating **ISO 21496-1 gain map JPEGs** from HDR and SDR source images. Outputs a single JPEG file that displays correctly on both standard (SDR) and HDR-capable displays — with the SDR version as the baseline and HDR headroom encoded in an embedded gain map.

Inspired by [WebSharpPro](https://gregbenzphotography.com/web-sharp-pro-panel) by **Greg Benz** — a Lightroom plugin for HDR gain map JPEGs. This tool is an open, self-hosted alternative for photographers who want flexibility outside the LR ecosystem.

---

## What It Does

1. **Accepts two TIFF inputs**
   - **HDR**: Linear 32-bit float TIFF (Display P3 gamut) — your high dynamic range source
   - **SDR**: 16-bit TIFF — your tone-mapped version (e.g. exported from Lightroom)

2. **Computes an RGB gain map** from the ratio of HDR to SDR in linear light, then writes a single ISO 21496-1 compliant JPEG containing:
   - The SDR image (what non-HDR displays show)
   - A per-channel gain map (how to reconstruct HDR on capable displays)

3. **Proofing page** — before download, you see side-by-side previews of the SDR baseline, gain map visualization, and final output.

4. **Optional processing**
   - Resize by long edge (e.g. 2160px for Instagram)
   - Output sharpening (compensates for downscale softness)
   - EXIF/IPTC/XMP preservation from your SDR source
   - XMP Container metadata (Primary + GainMap labels for HDR viewers)
   - CCV (Color Volume) luminance metadata in nits

---

## Supported Inputs

| Input | Format | Notes |
|-------|--------|-------|
| **HDR** | Linear 32-bit float TIFF | Display P3 gamut. Values > 1.0 represent HDR highlights. |
| **SDR** | 16-bit TIFF | Tone-mapped. Color space: sRGB, Display P3, Adobe RGB, or ProPhoto RGB — must match your export. |

HDR and SDR images **must have identical dimensions**. Export both at the same resolution from your editor.

---

## Requirements

- **Python 3.11+** (tested with 3.12)
- **exiftool** — system binary for metadata handling. Install separately:
  - macOS: `brew install exiftool`
  - Ubuntu/Debian: `apt install libimage-exiftool-perl`
  - Windows: [exiftool.org](https://exiftool.org/)

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/GainMapWebApp.git
cd GainMapWebApp
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Verify exiftool is installed

```bash
exiftool -ver
```

---

## Running the App

### Development (local)

```bash
source venv/bin/activate
python app.py
```

Opens at `http://127.0.0.1:5000`. Upload limit: 2 GB combined (HDR + SDR).

### Production (internal / LAN)

To serve on your network (e.g. for team access), bind to all interfaces:

```bash
python app.py
```

Then in `app.py`, change the last line to:

```python
app.run(host="0.0.0.0", debug=False)
```

For production use, run behind **gunicorn** (or similar) and **nginx** for:
- Request body size limits (nginx `client_max_body_size`)
- Reverse proxy and static file serving

---

## Workflow

### Typical Lightroom export pipeline

1. Edit your image in Lightroom Classic.
2. Export **two** versions:
   - **HDR TIFF**: 32-bit float, linear, P3 gamut (e.g. via a plug-in or HDR merge export).
   - **SDR TIFF**: 16-bit, tone-mapped, your preferred color space (sRGB, P3, Adobe RGB, ProPhoto).
3. Both at the same pixel dimensions (e.g. 11656×8742 or resized 2160×1620).

### In the app

1. Select HDR and SDR files (drag & drop supported).
2. Choose the SDR color space to match your export.
3. Open **Options** to adjust:
   - JPEG quality (default 95)
   - Resize (e.g. long edge 2160 for web)
   - Sharpening (when resizing)
   - Metadata toggles (EXIF, XMP Container, CCV)
4. Click **Create Gain Map JPEG**.
5. Review the proofing page, then **Download** the result.

---

## Output Format

The output is an **ISO 21496-1 gain map JPEG**:

- **Baseline image**: SDR fallback — displays on any device.
- **Gain map**: Encodes how to reconstruct HDR from the baseline.
- **Embedded ICC profile**: Display P3 (image P3).
- **Metadata**: EXIF (camera info), XMP Container (Primary/GainMap labels), XMP-hdr (CCV luminance nits), XMP-hdrgm (gain map parameters).

Supported by Apple Photos, Chrome, and other HDR-aware viewers.

---

## Project Structure

```
GainMapWebApp/
├── app.py              # Flask routes, file handling, session management
├── processing.py       # Image reading, gain map computation, metadata
├── requirements.txt    # Python dependencies
├── icc/
│   └── imageP3.icc     # Display P3 ICC profile (embedded in output)
├── static/
│   └── style.css       # UI styling
├── templates/
│   ├── index.html      # Upload form, options, drag & drop
│   └── results.html    # Proofing page
└── README.md
```

---

## Options Reference

| Option | Description | Default |
|--------|-------------|---------|
| **JPEG Quality** | Quality for baseline and gain map encoding (1–100) | 95 |
| **Resize output** | Downscale before encoding | Off |
| **Long edge (px)** | Target length of longest side when resizing | 2160 |
| **Sharpen amount** | Output sharpening strength when resizing (0–500) | 100 |
| **Preserve EXIF** | Copy camera/metadata from SDR source | On |
| **XMP Directory Item Semantic** | Label Primary + GainMap for viewers | On |
| **CCV luminance metadata** | Write min/max/avg nits + color volume to XMP | On |

---

## Technical Notes

- **Linear light**: HDR and SDR are converted to linear light before computing the gain map. The SDR gamma curve is removed using the correct EOTF for the selected color space (sRGB piece-wise, Adobe RGB γ2.2, ProPhoto γ1.8).
- **Baseline preservation**: The app keeps the original gamma-encoded SDR pixels for the JPEG baseline instead of linearizing and re-encoding. This avoids subtle tonal shifts from round-trip precision loss.
- **RGB gain maps**: Per-channel gain maps are used (not grayscale) for better color accuracy in highlights.
- **exiftool**: Used for EXIF copying and XMP metadata. The app calls the `exiftool` binary directly — it must be installed and on your `PATH`.

---

## License

[Add your license here]

---

## Acknowledgments

- **Greg Benz** — [WebSharpPro](https://gregbenzphotography.com/web-sharp-pro-panel) plugin and HDR JPEG workflow. His tutorials and plugin were the primary inspiration for this project.
- [hdr-conversion](https://github.com/nicholasduck/hdr-conversion) — ISO 21496-1 gain map computation and encoding
- [exiftool](https://exiftool.org/) — metadata handling
