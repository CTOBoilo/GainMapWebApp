"""
Image reading and processing pipeline for the Gain Map JPEG tool.

This module handles:
- Loading HDR and SDR source images into linear float32 numpy arrays
- Resizing and sharpening for web output
- Computing the ISO 21496-1 gain map JPEG
- Post-processing metadata (EXIF, XMP Container, CCV luminance)

Supported inputs:
- HDR: Linear 32-bit float TIFF (P3 gamut)
- SDR: 16-bit TIFF in sRGB, Display P3, Adobe RGB, or ProPhoto RGB
"""

import math
import os
import shutil
import subprocess

import numpy as np
import tifffile

SUPPORTED_SDR_COLORSPACES = {"srgb", "display_p3", "adobe_rgb", "prophoto_rgb"}

# ITU-R BT.2408 reference white for SDR content.
# Used to convert between linear-light ratios and absolute luminance (nits).
SDR_WHITE_NITS = 203.0


# ───────────────────────────────────────────────────────
# Image reading
# ───────────────────────────────────────────────────────

def readHdrSource(filePath):
    """Read an HDR source image (linear 32-bit float TIFF) into a linear float32 array.

    Args:
        filePath: Path to the HDR TIFF on disk.

    Returns:
        A numpy array of shape (height, width, 3), dtype float32, in linear light.
        Values can exceed 1.0 — that's the HDR headroom.

    Raises:
        ValueError: If the file extension is not a TIFF.
    """
    ext = os.path.splitext(filePath)[1].lower()

    if ext in (".tif", ".tiff"):
        return _readHdrTiff(filePath)
    else:
        raise ValueError(f"Unsupported HDR file format: {ext}. Must be a TIFF.")


def readSdrSource(filePath, colorSpace="srgb"):
    """Read an SDR source image (16-bit TIFF) and return both linear and gamma-encoded versions.

    We return TWO versions:
    - Linear: gamma removed, for the gain map ratio computation
    - Gamma-encoded: the original values, for the JPEG baseline

    Why both? If we linearize and then re-apply gamma (round-trip), small
    precision errors accumulate and cause a slight tonal shift. By keeping
    the original gamma-encoded values for the JPEG baseline, the SDR
    fallback looks exactly like the original TIFF.

    Args:
        filePath: Path to the 16-bit SDR TIFF on disk.
        colorSpace: One of: "srgb", "display_p3", "adobe_rgb", "prophoto_rgb".

    Returns:
        A tuple of (sdrLinear, sdrGamma):
        - sdrLinear: float32 array (H, W, 3), linear light [0.0, 1.0]
        - sdrGamma: uint8 array (H, W, 3), gamma-encoded [0, 255]

    Raises:
        ValueError: If the file is not a TIFF or color space is unsupported.
    """
    ext = os.path.splitext(filePath)[1].lower()
    if ext not in (".tif", ".tiff"):
        raise ValueError(f"SDR source must be a TIFF. Got: {ext}")

    if colorSpace not in SUPPORTED_SDR_COLORSPACES:
        raise ValueError(
            f"Unsupported color space: {colorSpace}. "
            f"Must be one of: {', '.join(SUPPORTED_SDR_COLORSPACES)}"
        )

    return _readSdrTiff(filePath, colorSpace)


def _readHdrTiff(filePath):
    """Read a 32-bit float HDR TIFF using tifffile."""
    imgData = tifffile.imread(filePath)
    imgData = _ensureRgb(imgData)

    if imgData.dtype == np.float32:
        return imgData
    elif imgData.dtype == np.float64:
        return imgData.astype(np.float32)
    elif imgData.dtype == np.uint16:
        return imgData.astype(np.float32) / 65535.0
    elif imgData.dtype == np.uint8:
        return imgData.astype(np.float32) / 255.0
    else:
        raise ValueError(
            f"Unexpected TIFF dtype: {imgData.dtype}. "
            f"Expected float32, float64, uint16, or uint8."
        )


def _readSdrTiff(filePath, colorSpace):
    """Read a 16-bit SDR TIFF and return both linear and gamma-encoded versions."""
    imgData = tifffile.imread(filePath)
    imgData = _ensureRgb(imgData)

    if imgData.dtype == np.uint16:
        sdrData = imgData.astype(np.float32) / 65535.0
    elif imgData.dtype == np.uint8:
        sdrData = imgData.astype(np.float32) / 255.0
    elif imgData.dtype in (np.float32, np.float64):
        sdrData = imgData.astype(np.float32)
    else:
        raise ValueError(
            f"Unexpected SDR TIFF dtype: {imgData.dtype}. "
            f"Expected uint16, uint8, float32, or float64."
        )

    sdrGamma = np.clip(sdrData * 255.0, 0, 255).astype(np.uint8)
    sdrLinear = _linearize(sdrData, colorSpace)

    return sdrLinear, sdrGamma


# ───────────────────────────────────────────────────────
# Linearization (pure numpy — no colour-science dependency)
# ───────────────────────────────────────────────────────

def _linearize(data, colorSpace):
    """Remove the gamma/transfer curve from pixel data to get linear light.

    Each color space encodes brightness differently. This function applies
    the correct inverse transfer function (EOTF) using pure numpy math.

    The sRGB EOTF is piece-wise:
      - For values <= 0.04045:  linear = value / 12.92
      - For values >  0.04045:  linear = ((value + 0.055) / 1.055) ^ 2.4

    Display P3 uses the same sRGB transfer curve (only the color primaries differ).
    Adobe RGB uses gamma 2.19921875. ProPhoto RGB uses gamma 1.8.
    """
    if colorSpace in ("srgb", "display_p3"):
        low = data / 12.92
        high = np.power((np.clip(data, 0.0, None) + 0.055) / 1.055, 2.4)
        return np.where(data <= 0.04045, low, high).astype(np.float32)

    elif colorSpace == "adobe_rgb":
        return np.power(np.clip(data, 0.0, None), 2.19921875).astype(np.float32)

    elif colorSpace == "prophoto_rgb":
        return np.power(np.clip(data, 0.0, None), 1.8).astype(np.float32)

    else:
        raise ValueError(f"Unknown color space for linearization: {colorSpace}")


# ───────────────────────────────────────────────────────
# Resize and sharpen
# ───────────────────────────────────────────────────────

def sharpenBaseline(gainmapData, amount=100):
    """Apply output sharpening to the baseline in gainmapData (in place).

    Downscaling softens images, so output sharpening compensates for
    that lost detail. This is standard practice for web/social publishing.

    Uses Pillow's UnsharpMask with:
    - radius=0.8 (small kernel — fine detail, not halos)
    - percent=amount (strength, typically 50-200 for web output)
    - threshold=0 (sharpen all pixels, not just high-contrast edges)

    Args:
        gainmapData: The dict from computeGainMap (baseline is uint8).
        amount: Sharpening strength as a percentage (0-500).

    Returns:
        The same gainmapData dict with sharpened baseline.
    """
    from PIL import Image, ImageFilter

    img = Image.fromarray(gainmapData["baseline"])
    img = img.filter(ImageFilter.UnsharpMask(radius=0.8, percent=amount, threshold=0))
    gainmapData["baseline"] = np.array(img)
    return gainmapData


# ───────────────────────────────────────────────────────
# Gain map creation
# ───────────────────────────────────────────────────────

def _loadIccProfile():
    """Load the Image P3 ICC profile bytes from the bundled .icc file."""
    iccPath = os.path.join(os.path.dirname(__file__), "icc", "imageP3.icc")
    with open(iccPath, "rb") as f:
        return f.read()


def computeGainMap(hdrLinear, sdrLinear, sdrGamma):
    """Compute the ISO 21496-1 gain map at full resolution.

    Reimplements the gain map math from hdr-conversion directly,
    skipping the library's expensive colour.eotf_inverse() call on
    the baseline (which we discard anyway). On a 100 MP image this
    saves ~40 seconds.

    Args:
        hdrLinear: float32 (H, W, 3), linear light, values can exceed 1.0.
        sdrLinear: float32 (H, W, 3), linear light, values in [0.0, 1.0].
        sdrGamma: uint8 (H, W, 3), original gamma-encoded SDR.

    Returns:
        A GainmapImage-compatible dict with baseline, gainmap, metadata,
        and ICC profile bytes.

    Raises:
        ValueError: If the images have different dimensions.
    """
    if hdrLinear.shape[:2] != sdrLinear.shape[:2]:
        raise ValueError(
            f"HDR and SDR images must have the same dimensions. "
            f"HDR: {hdrLinear.shape[:2]}, SDR: {sdrLinear.shape[:2]}"
        )

    p3IccProfile = _loadIccProfile()

    offset = np.float32(1.0 / 64.0)

    # HDR headroom: how many stops above SDR white the brightest pixel reaches
    altHeadroom = float(np.log2(np.maximum(hdrLinear.max(), 1.001)))

    # Per-pixel ratio between HDR and SDR in linear light.
    # Offset prevents division by zero in dark regions.
    ratio = (hdrLinear + offset) / (sdrLinear + offset)
    np.clip(ratio, 1e-6, None, out=ratio)

    # Log2 of ratio — the gain map lives in log space
    gainmapLog = np.log2(ratio)
    del ratio

    # Per-channel min/max for normalization
    gmMin = np.min(gainmapLog, axis=(0, 1))  # shape (3,)
    gmMax = np.max(gainmapLog, axis=(0, 1))  # shape (3,)

    # Normalize each channel to [0, 1] — vectorized, no per-channel loop
    diffs = gmMax - gmMin
    diffs = np.where(diffs == 0, 1.0, diffs)
    gainmapLog -= gmMin
    gainmapLog /= diffs
    np.clip(gainmapLog, 0, 1, out=gainmapLog)

    gainmapUint8 = (gainmapLog * 255).astype(np.uint8)
    del gainmapLog

    return {
        "baseline": sdrGamma,
        "gainmap": gainmapUint8,
        "metadata": {
            "minimum_version": 0,
            "writer_version": 0,
            "baseline_hdr_headroom": 0.0,
            "alternate_hdr_headroom": altHeadroom,
            "is_multichannel": True,
            "use_base_colour_space": True,
            "gainmap_min": tuple(gmMin.tolist()),
            "gainmap_max": tuple(gmMax.tolist()),
            "gainmap_gamma": (1.0, 1.0, 1.0),
            "baseline_offset": (float(offset), float(offset), float(offset)),
            "alternate_offset": (float(offset), float(offset), float(offset)),
        },
        "baseline_icc": p3IccProfile,
        "gainmap_icc": p3IccProfile,
    }


def resizeOutput(gainmapData, longEdge):
    """Resize the baseline and gain map arrays after gain map computation.

    Metadata (GainMapMin/Max/Gamma etc.) stays from the full-res
    computation — only the pixel arrays get downscaled.

    Args:
        gainmapData: The dict returned by computeGainMap.
        longEdge: Target size for the longest dimension in pixels.

    Returns:
        The same gainmapData dict with resized arrays (modified in place).
    """
    from PIL import Image

    baseline = gainmapData["baseline"]
    gainmap = gainmapData["gainmap"]

    h, w = baseline.shape[:2]
    currentLong = max(h, w)

    if currentLong <= longEdge:
        return gainmapData

    scale = longEdge / currentLong
    newW = int(w * scale)
    newH = int(h * scale)

    baselineImg = Image.fromarray(baseline)
    gainmapData["baseline"] = np.array(
        baselineImg.resize((newW, newH), Image.LANCZOS)
    )

    gainmapImg = Image.fromarray(gainmap)
    gainmapData["gainmap"] = np.array(
        gainmapImg.resize((newW, newH), Image.LANCZOS)
    )

    return gainmapData


def writeGainMapJpeg(gainmapData, outputPath, jpegQuality=95):
    """Write the gain map data to an ISO 21496-1 JPEG file.

    Args:
        gainmapData: The dict from computeGainMap (possibly resized).
        outputPath: Where to write the output JPEG.
        jpegQuality: JPEG quality for both baseline and gain map (1-100).
    """
    import hdrconv.io as io

    io.write_21496(
        gainmapData,
        outputPath,
        baseline_quality=jpegQuality,
        gainmap_quality=jpegQuality,
    )


# ───────────────────────────────────────────────────────
# Post-processing metadata (via exiftool)
# ───────────────────────────────────────────────────────

def writeAllMetadata(
    outputJpegPath,
    sourceTiffPath=None,
    enableExif=False,
    enableXmpDir=False,
    enableCcv=False,
    gainmapMetadata=None,
    hdrLinear=None,
):
    """Write all post-processing metadata in a single exiftool call.

    Combines ICC re-embedding, EXIF copy, XMP container labels, and CCV
    luminance data into one invocation. Each full-res JPEG read+write
    cycle is expensive, so batching saves significant time.

    The ICC profile re-embed and ColorSpace=Uncalibrated always run.
    Everything else is controlled by the boolean flags.
    """
    iccPath = os.path.join(os.path.dirname(__file__), "icc", "imageP3.icc")

    args = ["exiftool"]

    # --- EXIF/IPTC/XMP copy from source TIFF ---
    if enableExif and sourceTiffPath:
        args += [
            "-TagsFromFile", sourceTiffPath,
            "-EXIF:all",
            "--EXIF:ColorSpace",
            "-IPTC:all",
            "-XMP-xmp:all",
            "-XMP-aux:all",
            "-XMP-exifEX:all",
            "-XMP-photoshop:all",
            "-XMP-xmpRights:all",
            "-XMP-dc:all",
            "-XMP-xmpMM:all",
            "--ICC_Profile:all",
        ]

    # --- XMP Container Directory (Primary + GainMap labels) ---
    if enableXmpDir:
        args += [
            "-struct",
            "-XMP-GContainer:ContainerDirectory="
            "[{DirectoryItemSemantic=Primary,DirectoryItemMime=image/jpeg},"
            "{DirectoryItemSemantic=GainMap,DirectoryItemMime=image/jpeg}]",
        ]

    # --- CCV luminance + XMP-hdrgm gain map parameters ---
    if enableCcv and gainmapMetadata is not None and hdrLinear is not None:
        lumWeights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        luminanceMap = np.dot(hdrLinear, lumWeights)

        maxNits = float(np.max(luminanceMap)) * SDR_WHITE_NITS
        avgNits = float(np.mean(luminanceMap)) * SDR_WHITE_NITS
        minNits = float(np.min(np.clip(luminanceMap, 1e-6, None))) * SDR_WHITE_NITS

        p3Primaries = "0.6800,0.3200,0.2650,0.6900,0.1500,0.0600"
        d65White = "0.3127,0.3290"

        args += [
            f"-XMP-hdr:CCVMaxLuminanceNits={maxNits:.6f}",
            f"-XMP-hdr:CCVMinLuminanceNits={minNits:.6f}",
            f"-XMP-hdr:CCVAvgLuminanceNits={avgNits:.6f}",
            f"-XMP-hdr:CCVPrimariesXY={p3Primaries}",
            f"-XMP-hdr:CCVWhiteXY={d65White}",
            "-XMP-hdr:SceneReferred=False",
        ]

        hdrCapacityMax = math.log2(
            max(gainmapMetadata.get("alternate_hdr_headroom", 1.0), 1.001)
        )
        hdrCapacityMin = math.log2(
            max(gainmapMetadata.get("baseline_hdr_headroom", 1.0), 1.001)
        )
        gmMin = gainmapMetadata.get("gainmap_min", (0.0, 0.0, 0.0))
        gmMax = gainmapMetadata.get("gainmap_max", (1.0, 1.0, 1.0))
        gmGamma = gainmapMetadata.get("gainmap_gamma", (1.0, 1.0, 1.0))
        offsetSdr = gainmapMetadata.get("baseline_offset", (0.0, 0.0, 0.0))
        offsetHdr = gainmapMetadata.get("alternate_offset", (0.0, 0.0, 0.0))

        args += [
            f"-XMP-hdrgm:HDRCapacityMax={hdrCapacityMax:.6f}",
            f"-XMP-hdrgm:HDRCapacityMin={hdrCapacityMin:.6f}",
            f"-XMP-hdrgm:GainMapMax={sum(gmMax) / 3.0:.6f}",
            f"-XMP-hdrgm:GainMapMin={sum(gmMin) / 3.0:.6f}",
            f"-XMP-hdrgm:Gamma={sum(gmGamma) / 3.0:.6f}",
            f"-XMP-hdrgm:OffsetSDR={sum(offsetSdr) / 3.0:.6f}",
            f"-XMP-hdrgm:OffsetHDR={sum(offsetHdr) / 3.0:.6f}",
            "-XMP-hdrgm:BaseRenditionIsHDR=False",
            "-XMP-hdrgm:Version=1.0",
        ]

    # --- ICC profile re-embed + ColorSpace (always runs last) ---
    args += [
        f"-icc_profile<={iccPath}",
        "-EXIF:ColorSpace=Uncalibrated",
        "-overwrite_original",
        outputJpegPath,
    ]

    subprocess.run(args, check=True, capture_output=True)


# ───────────────────────────────────────────────────────
# Preview generation
# ───────────────────────────────────────────────────────

def savePreviewImages(gainmapData, outputPath, previewDir):
    """Save preview images for the proofing page.

    Generates three files in previewDir:
    - sdr_preview.jpg: The SDR baseline with Image P3 ICC profile
    - gainmap_preview.jpg: The RGB gain map visualization
    - output_preview.jpg: A copy of the final gain map JPEG

    All previews are resized to max 1600px long edge for fast loading.
    The SDR preview embeds the same ICC profile as the output JPEG so
    the browser renders its colors accurately.
    """
    from PIL import Image

    p3IccProfile = _loadIccProfile()
    maxPreviewEdge = 1600

    def _saveResizedJpeg(arr, path, iccProfile=None):
        img = Image.fromarray(arr)
        w, h = img.size
        scale = min(maxPreviewEdge / max(w, h), 1.0)
        if scale < 1.0:
            newW = int(w * scale)
            newH = int(h * scale)
            img = img.resize((newW, newH), Image.LANCZOS)
        saveKwargs = {"quality": 85}
        if iccProfile:
            saveKwargs["icc_profile"] = iccProfile
        img.save(path, "JPEG", **saveKwargs)

    _saveResizedJpeg(
        gainmapData["baseline"],
        os.path.join(previewDir, "sdr_preview.jpg"),
        iccProfile=p3IccProfile,
    )

    _saveResizedJpeg(
        gainmapData["gainmap"],
        os.path.join(previewDir, "gainmap_preview.jpg"),
    )

    shutil.copy2(outputPath, os.path.join(previewDir, "output_preview.jpg"))


# ───────────────────────────────────────────────────────
# Utility
# ───────────────────────────────────────────────────────

def _ensureRgb(imgData):
    """Ensure image array is shape (height, width, 3) RGB."""
    if imgData.ndim == 2:
        imgData = np.stack([imgData, imgData, imgData], axis=-1)
    elif imgData.ndim == 3 and imgData.shape[2] == 4:
        imgData = imgData[:, :, :3]
    elif imgData.ndim == 3 and imgData.shape[2] == 3:
        pass
    else:
        raise ValueError(
            f"Unexpected image shape: {imgData.shape}. Expected (H, W, 3)."
        )
    return imgData
