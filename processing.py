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

def resizeArrays(hdrLinear, sdrLinear, sdrGamma, longEdge):
    """Resize all three arrays so the longest side equals longEdge pixels.

    If the image is already smaller than longEdge, returns unchanged arrays.
    Uses LANCZOS resampling (high-quality downscale filter).

    Args:
        hdrLinear: float32 (H, W, 3) — linear HDR
        sdrLinear: float32 (H, W, 3) — linear SDR
        sdrGamma: uint8 (H, W, 3) — gamma-encoded SDR
        longEdge: Target size for the longest dimension in pixels.

    Returns:
        Tuple of (hdrLinear, sdrLinear, sdrGamma) — resized.
    """
    from PIL import Image

    h, w = hdrLinear.shape[:2]
    currentLong = max(h, w)

    if currentLong <= longEdge:
        return hdrLinear, sdrLinear, sdrGamma

    scale = longEdge / currentLong
    newW = int(w * scale)
    newH = int(h * scale)

    sdrGammaImg = Image.fromarray(sdrGamma)
    sdrGamma = np.array(sdrGammaImg.resize((newW, newH), Image.LANCZOS))

    hdrLinear = _resizeFloat32(hdrLinear, newW, newH)
    sdrLinear = _resizeFloat32(sdrLinear, newW, newH)

    return hdrLinear, sdrLinear, sdrGamma


def _resizeFloat32(arr, newW, newH):
    """Resize a float32 (H, W, 3) array using Pillow's LANCZOS filter.

    Pillow doesn't support float32 RGB directly, so we resize each
    channel independently using 'F' mode (32-bit float grayscale).
    """
    from PIL import Image

    channels = []
    for c in range(arr.shape[2]):
        ch = Image.fromarray(arr[:, :, c], mode="F")
        ch = ch.resize((newW, newH), Image.LANCZOS)
        channels.append(np.array(ch))
    return np.stack(channels, axis=-1)


def sharpenImage(sdrGamma, amount=100):
    """Apply output sharpening to the SDR baseline (uint8 RGB array).

    Downscaling softens images, so output sharpening compensates for
    that lost detail. This is standard practice for web/social publishing.

    Uses Pillow's UnsharpMask with:
    - radius=0.8 (small kernel — fine detail, not halos)
    - percent=amount (strength, typically 50-200 for web output)
    - threshold=0 (sharpen all pixels, not just high-contrast edges)

    Args:
        sdrGamma: uint8 array (H, W, 3)
        amount: Sharpening strength as a percentage (0-500).

    Returns:
        Sharpened uint8 array (H, W, 3).
    """
    from PIL import Image, ImageFilter

    img = Image.fromarray(sdrGamma)
    img = img.filter(ImageFilter.UnsharpMask(radius=0.8, percent=amount, threshold=0))
    return np.array(img)


# ───────────────────────────────────────────────────────
# Gain map creation
# ───────────────────────────────────────────────────────

def createGainMapJpeg(hdrLinear, sdrLinear, sdrGamma, outputPath, jpegQuality=95):
    """Create an ISO 21496-1 gain map JPEG from HDR and SDR arrays.

    Args:
        hdrLinear: float32 (H, W, 3), linear light, values can exceed 1.0.
        sdrLinear: float32 (H, W, 3), linear light, values in [0.0, 1.0].
        sdrGamma: uint8 (H, W, 3), original gamma-encoded SDR.
        outputPath: Where to write the output JPEG.
        jpegQuality: JPEG quality for both baseline and gain map (1-100).

    Returns:
        The gainmapData dict (for preview generation and metadata extraction).

    Raises:
        ValueError: If the images have different dimensions.
    """
    import hdrconv.convert as convert
    import hdrconv.io as io
    from hdrconv.core import HDRImage

    if hdrLinear.shape[:2] != sdrLinear.shape[:2]:
        raise ValueError(
            f"HDR and SDR images must have the same dimensions. "
            f"HDR: {hdrLinear.shape[:2]}, SDR: {sdrLinear.shape[:2]}"
        )

    iccPath = os.path.join(os.path.dirname(__file__), "icc", "imageP3.icc")
    with open(iccPath, "rb") as f:
        p3IccProfile = f.read()

    hdrImage = HDRImage(
        data=hdrLinear,
        transfer_function="linear",
        color_space="p3",
    )

    gainmapData = convert.hdr_to_gainmap(
        hdrImage,
        baseline=sdrLinear,
        icc_profile=p3IccProfile,
        gamma=1.0,
    )

    # Replace the library's re-encoded baseline with our original
    # gamma-encoded SDR values to avoid round-trip precision loss.
    gainmapData["baseline"] = sdrGamma

    io.write_21496(
        gainmapData,
        outputPath,
        baseline_quality=jpegQuality,
        gainmap_quality=jpegQuality,
    )

    return gainmapData


# ───────────────────────────────────────────────────────
# Post-processing metadata (via exiftool)
# ───────────────────────────────────────────────────────

def copyExifMetadata(sourceTiffPath, outputJpegPath):
    """Copy EXIF, IPTC, and key XMP metadata from the source TIFF to the output JPEG.

    Copies camera info, editorial metadata, and Lightroom/Photoshop XMP.
    Does NOT touch ICC profiles, MPF structure, or gain map XMP — those
    are already set correctly by the gain map writer.
    """
    subprocess.run(
        [
            "exiftool",
            "-TagsFromFile", sourceTiffPath,
            "-EXIF:all",
            "-IPTC:all",
            "-XMP-xmp:all",
            "-XMP-aux:all",
            "-XMP-exifEX:all",
            "-XMP-photoshop:all",
            "-XMP-xmpRights:all",
            "-XMP-dc:all",
            "-XMP-xmpMM:all",
            "-overwrite_original",
            outputJpegPath,
        ],
        check=True,
        capture_output=True,
    )


def writeContainerXmp(outputJpegPath):
    """Write XMP Directory Item Semantic metadata.

    Labels the two images inside the MPF JPEG container:
    - Image 1: Primary (the SDR baseline)
    - Image 2: GainMap (the HDR gain map)

    This helps HDR-aware viewers (Apple Photos, Chrome, etc.) identify
    which image is the baseline and which is the gain map, without
    relying solely on the binary ISO 21496-1 metadata.

    Uses the Google Container XMP namespace (XMP-GContainer), which
    is the de facto standard for multi-image JPEG containers.
    """
    subprocess.run(
        [
            "exiftool",
            "-struct",
            "-XMP-GContainer:ContainerDirectory="
            "[{DirectoryItemSemantic=Primary,DirectoryItemMime=image/jpeg},"
            "{DirectoryItemSemantic=GainMap,DirectoryItemMime=image/jpeg}]",
            "-overwrite_original",
            outputJpegPath,
        ],
        check=True,
        capture_output=True,
    )


def writeCcvMetadata(gainmapMetadata, hdrLinear, outputJpegPath):
    """Write Color Volume (CCV) metadata in the XMP-hdr namespace.

    Computes actual luminance values in nits from the HDR linear data
    and writes them alongside Display P3 color primaries and D65 white
    point — matching the format that WebSharpPro and Apple HDR viewers expect.

    Also writes gain map parameters in the XMP-hdrgm namespace for
    compatibility with viewers that read XMP instead of the binary
    ISO 21496-1 metadata.

    Args:
        gainmapMetadata: The metadata dict from gainmapData["metadata"].
        hdrLinear: The original HDR linear array (for luminance computation).
        outputJpegPath: Path to the output JPEG to write metadata into.
    """
    # Compute luminance in nits from linear-light HDR data.
    # ITU-R BT.709 luminance weights (same for P3 and sRGB).
    lumWeights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    luminanceMap = np.dot(hdrLinear, lumWeights)

    maxNits = float(np.max(luminanceMap)) * SDR_WHITE_NITS
    avgNits = float(np.mean(luminanceMap)) * SDR_WHITE_NITS
    minNits = float(np.min(np.clip(luminanceMap, 1e-6, None))) * SDR_WHITE_NITS

    # Display P3 primaries (CIE xy) and D65 white point
    p3Primaries = "0.6800,0.3200,0.2650,0.6900,0.1500,0.0600"
    d65White = "0.3127,0.3290"

    # XMP-hdr: CCV metadata (luminance + color volume)
    ccvArgs = [
        f"-XMP-hdr:CCVMaxLuminanceNits={maxNits:.6f}",
        f"-XMP-hdr:CCVMinLuminanceNits={minNits:.6f}",
        f"-XMP-hdr:CCVAvgLuminanceNits={avgNits:.6f}",
        f"-XMP-hdr:CCVPrimariesXY={p3Primaries}",
        f"-XMP-hdr:CCVWhiteXY={d65White}",
        "-XMP-hdr:SceneReferred=False",
    ]

    # XMP-hdrgm: gain map parameters (mirrors binary ISO metadata)
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

    hdrgmArgs = [
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

    subprocess.run(
        ["exiftool"] + ccvArgs + hdrgmArgs + ["-overwrite_original", outputJpegPath],
        check=True,
        capture_output=True,
    )


# ───────────────────────────────────────────────────────
# Preview generation
# ───────────────────────────────────────────────────────

def savePreviewImages(sdrGamma, gainmapData, outputPath, previewDir):
    """Save preview images for the proofing page.

    Generates three files in previewDir:
    - sdr_preview.jpg: The SDR baseline (what non-HDR displays see)
    - gainmap_preview.jpg: The RGB gain map visualization
    - output_preview.jpg: A copy of the final gain map JPEG

    All previews are resized to max 1600px long edge for fast loading.
    """
    from PIL import Image

    maxPreviewEdge = 1600

    def _saveResizedJpeg(arr, path):
        img = Image.fromarray(arr)
        w, h = img.size
        scale = min(maxPreviewEdge / max(w, h), 1.0)
        if scale < 1.0:
            newW = int(w * scale)
            newH = int(h * scale)
            img = img.resize((newW, newH), Image.LANCZOS)
        img.save(path, "JPEG", quality=85)

    _saveResizedJpeg(sdrGamma, os.path.join(previewDir, "sdr_preview.jpg"))

    gainmapArr = gainmapData["gainmap"]
    _saveResizedJpeg(gainmapArr, os.path.join(previewDir, "gainmap_preview.jpg"))

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
