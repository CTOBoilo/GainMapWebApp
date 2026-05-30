import io
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile

from flask import Flask, render_template, request, send_file, redirect, url_for, abort, Response

from processing import (
    computeGainMap,
    readHdrSource,
    readSdrSource,
    resizeOutput,
    savePreviewImages,
    sharpenBaseline,
    writeAllMetadata,
    writeGainMapJpeg,
)

app = Flask(__name__)

app.config["MAX_CONTENT_LENGTH"] = None

ALLOWED_EXTENSIONS = {".tif", ".tiff"}

activeSessions = {}


def isAllowedFile(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/convert", methods=["POST"])
def convert():
    """Process uploaded files with user-selected options, then show proofing page."""

    # --- Validate files ---

    if "hdr_file" not in request.files or "sdr_file" not in request.files:
        return render_template(
            "index.html",
            message="Please select both an HDR and an SDR file.",
            messageType="error",
        )

    hdrFile = request.files["hdr_file"]
    sdrFile = request.files["sdr_file"]

    if hdrFile.filename == "" or sdrFile.filename == "":
        return render_template(
            "index.html",
            message="Please select both an HDR and an SDR file.",
            messageType="error",
        )

    if not isAllowedFile(hdrFile.filename):
        return render_template(
            "index.html",
            message=f"HDR file must be a TIFF. Got: {hdrFile.filename}",
            messageType="error",
        )

    if not isAllowedFile(sdrFile.filename):
        return render_template(
            "index.html",
            message=f"SDR file must be a TIFF. Got: {sdrFile.filename}",
            messageType="error",
        )

    # --- Read options from form ---

    sdrColorspace = request.form.get("sdr_colorspace", "srgb")
    validColorspaces = {"srgb", "display_p3", "adobe_rgb", "prophoto_rgb"}
    if sdrColorspace not in validColorspaces:
        return render_template(
            "index.html",
            message=f"Invalid color space: {sdrColorspace}",
            messageType="error",
        )

    jpegQuality = int(request.form.get("jpeg_quality", 95))
    jpegQuality = max(1, min(100, jpegQuality))

    enableResize = request.form.get("enable_resize") == "on"
    longEdge = int(request.form.get("long_edge", 2160))
    longEdge = max(100, min(20000, longEdge))

    sharpenAmount = int(request.form.get("sharpen_amount", 100))
    sharpenAmount = max(0, min(500, sharpenAmount))

    enableExif = request.form.get("enable_exif") == "on"
    enableXmpDir = request.form.get("enable_xmp_dir") == "on"
    enableCcv = request.form.get("enable_ccv") == "on"

    # --- Process ---

    tempDir = tempfile.mkdtemp(prefix="gainmap_")

    try:
        hdrPath = os.path.join(tempDir, hdrFile.filename)
        sdrPath = os.path.join(tempDir, sdrFile.filename)
        hdrFile.save(hdrPath)
        sdrFile.save(sdrPath)

        def _log(msg):
            import sys
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()

        t0 = time.time()

        hdrLinear = readHdrSource(hdrPath)
        sdrLinear, sdrGamma = readSdrSource(sdrPath, colorSpace=sdrColorspace)
        _log(f"  [timing] Read sources: {time.time() - t0:.1f}s")

        t1 = time.time()
        gainmapData = computeGainMap(hdrLinear, sdrLinear, sdrGamma)
        del sdrLinear, sdrGamma
        _log(f"  [timing] Compute gain map: {time.time() - t1:.1f}s")

        if enableResize:
            t2 = time.time()
            resizeOutput(gainmapData, longEdge)
            if sharpenAmount > 0:
                sharpenBaseline(gainmapData, amount=sharpenAmount)
            _log(f"  [timing] Resize + sharpen: {time.time() - t2:.1f}s")

        t3 = time.time()
        baseName = os.path.splitext(hdrFile.filename)[0]
        outputFilename = f"{baseName}_gainmap.jpg"
        outputPath = os.path.join(tempDir, outputFilename)
        writeGainMapJpeg(gainmapData, outputPath, jpegQuality=jpegQuality)
        _log(f"  [timing] Write JPEG: {time.time() - t3:.1f}s")

        t4 = time.time()
        writeAllMetadata(
            outputPath,
            sourceTiffPath=sdrPath,
            enableExif=enableExif,
            enableXmpDir=enableXmpDir,
            enableCcv=enableCcv,
            gainmapMetadata=gainmapData["metadata"],
            hdrLinear=hdrLinear,
        )
        del hdrLinear
        _log(f"  [timing] Metadata: {time.time() - t4:.1f}s")

        os.remove(hdrPath)
        os.remove(sdrPath)

        t5 = time.time()
        previewDir = os.path.join(tempDir, "previews")
        os.makedirs(previewDir)
        savePreviewImages(gainmapData, outputPath, previewDir)
        _log(f"  [timing] Previews: {time.time() - t5:.1f}s")
        _log(f"  [timing] TOTAL: {time.time() - t0:.1f}s")

        # Register session
        sessionId = uuid.uuid4().hex[:12]
        activeSessions[sessionId] = {
            "tempDir": tempDir,
            "outputFilename": outputFilename,
            "outputPath": outputPath,
        }

        return redirect(url_for("results", session_id=sessionId))

    except ValueError as e:
        shutil.rmtree(tempDir, ignore_errors=True)
        return render_template(
            "index.html",
            message=str(e),
            messageType="error",
        )
    except Exception as e:
        shutil.rmtree(tempDir, ignore_errors=True)
        return render_template(
            "index.html",
            message=f"Processing failed: {e}",
            messageType="error",
        )


@app.route("/results/<session_id>")
def results(session_id):
    if session_id not in activeSessions:
        return redirect(url_for("index"))

    session = activeSessions[session_id]
    return render_template(
        "results.html",
        sessionId=session_id,
        outputFilename=session["outputFilename"],
    )


@app.route("/preview/<session_id>/<image_type>")
def preview(session_id, image_type):
    if session_id not in activeSessions:
        abort(404)

    session = activeSessions[session_id]
    previewDir = os.path.join(session["tempDir"], "previews")

    fileMap = {
        "sdr": "sdr_preview.jpg",
        "gainmap": "gainmap_preview.jpg",
        "output": "output_preview.jpg",
    }

    if image_type not in fileMap:
        abort(404)

    filePath = os.path.join(previewDir, fileMap[image_type])
    if not os.path.exists(filePath):
        abort(404)

    return send_file(filePath, mimetype="image/jpeg")


@app.route("/download/<session_id>")
def download(session_id):
    if session_id not in activeSessions:
        abort(404)

    session = activeSessions[session_id]
    outputPath = session["outputPath"]
    outputFilename = session["outputFilename"]

    if not os.path.exists(outputPath):
        abort(404)

    with open(outputPath, "rb") as f:
        fileData = f.read()

    shutil.rmtree(session["tempDir"], ignore_errors=True)
    del activeSessions[session_id]

    return send_file(
        io.BytesIO(fileData),
        mimetype="image/jpeg",
        as_attachment=True,
        download_name=outputFilename,
    )


# ─────────────────────────────────────────────────────────
# Batch processing
# ─────────────────────────────────────────────────────────

def _stripSuffix(stem):
    """Remove _hdr or _sdr suffix (case-insensitive) to get the base name."""
    lower = stem.lower()
    if lower.endswith("_hdr"):
        return stem[:-4]
    if lower.endswith("_sdr"):
        return stem[:-4]
    return stem


def _matchPairs(hdrFiles, sdrFiles):
    """Match HDR and SDR files by base name after stripping _hdr/_sdr suffixes.

    Example: sunset_001_hdr.tif pairs with sunset_001_sdr.tif
    because both have the base name "sunset_001".

    Returns (matchedPairs, unmatchedHdr, unmatchedSdr) where matchedPairs
    is a list of (hdrFileObj, sdrFileObj, baseName) tuples.
    """
    hdrByBase = {}
    for f in hdrFiles:
        if f.filename and isAllowedFile(f.filename):
            stem = os.path.splitext(f.filename)[0]
            base = _stripSuffix(stem)
            hdrByBase[base] = f

    sdrByBase = {}
    for f in sdrFiles:
        if f.filename and isAllowedFile(f.filename):
            stem = os.path.splitext(f.filename)[0]
            base = _stripSuffix(stem)
            sdrByBase[base] = f

    matched = []
    for base in hdrByBase:
        if base in sdrByBase:
            matched.append((hdrByBase[base], sdrByBase[base], base))

    unmatchedHdr = set(hdrByBase) - set(sdrByBase)
    unmatchedSdr = set(sdrByBase) - set(hdrByBase)
    return matched, unmatchedHdr, unmatchedSdr


def _processBatch(sessionId, pairs, tempDir, options):
    """Background worker that processes each HDR/SDR pair sequentially.

    Updates activeSessions[sessionId]["progress"] after each pair so
    the status endpoint can report live progress.
    """
    import sys

    def _log(msg):
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()

    progress = activeSessions[sessionId]["progress"]
    outputDir = os.path.join(tempDir, "output")
    os.makedirs(outputDir, exist_ok=True)

    for i, (hdrPath, sdrPath, stem) in enumerate(pairs):
        progress["current"] = stem
        progress["completed"] = i

        try:
            t0 = time.time()
            _log(f"  [batch {i + 1}/{len(pairs)}] Processing: {stem}")

            hdrLinear = readHdrSource(hdrPath)
            sdrLinear, sdrGamma = readSdrSource(
                sdrPath, colorSpace=options["sdrColorspace"]
            )

            gainmapData = computeGainMap(hdrLinear, sdrLinear, sdrGamma)
            del sdrLinear, sdrGamma

            if options["enableResize"]:
                resizeOutput(gainmapData, options["longEdge"])
                if options["sharpenAmount"] > 0:
                    sharpenBaseline(gainmapData, amount=options["sharpenAmount"])

            outputFilename = f"{stem}_gainmap.jpg"
            outputPath = os.path.join(outputDir, outputFilename)
            writeGainMapJpeg(
                gainmapData, outputPath, jpegQuality=options["jpegQuality"]
            )

            writeAllMetadata(
                outputPath,
                sourceTiffPath=sdrPath,
                enableExif=options["enableExif"],
                enableXmpDir=options["enableXmpDir"],
                enableCcv=options["enableCcv"],
                gainmapMetadata=gainmapData["metadata"],
                hdrLinear=hdrLinear,
            )

            del hdrLinear, gainmapData

            _log(f"  [batch {i + 1}/{len(pairs)}] Done: {stem} ({time.time() - t0:.1f}s)")

        except Exception as e:
            _log(f"  [batch {i + 1}/{len(pairs)}] FAILED: {stem} — {e}")
            progress["errors"].append({"file": stem, "error": str(e)})

        # Clean up source TIFFs after each pair to free disk space
        for p in (hdrPath, sdrPath):
            if os.path.exists(p):
                os.remove(p)

    progress["completed"] = len(pairs)
    progress["current"] = None

    # Create ZIP of all outputs
    zipPath = os.path.join(tempDir, "gainmap_batch.zip")
    with zipfile.ZipFile(zipPath, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in sorted(os.listdir(outputDir)):
            fpath = os.path.join(outputDir, fname)
            zf.write(fpath, fname)

    progress["done"] = True
    activeSessions[sessionId]["zipPath"] = zipPath
    _log(f"  [batch] All done. ZIP at {zipPath}")


@app.route("/batch", methods=["POST"])
def batch():
    """Accept multiple HDR + SDR files, match by name, process in background."""

    hdrFiles = request.files.getlist("hdr_files")
    sdrFiles = request.files.getlist("sdr_files")

    if not hdrFiles or not sdrFiles:
        return render_template(
            "index.html",
            message="Please select HDR and SDR files for batch processing.",
            messageType="error",
        )

    matched, unmatchedHdr, unmatchedSdr = _matchPairs(hdrFiles, sdrFiles)

    if not matched:
        unHdr = ", ".join(sorted(unmatchedHdr)) if unmatchedHdr else "(none)"
        unSdr = ", ".join(sorted(unmatchedSdr)) if unmatchedSdr else "(none)"
        return render_template(
            "index.html",
            message=(
                f"No matching pairs found. HDR and SDR filenames must match. "
                f"Unmatched HDR: {unHdr}. Unmatched SDR: {unSdr}."
            ),
            messageType="error",
        )

    # Read shared options
    sdrColorspace = request.form.get("sdr_colorspace", "srgb")
    jpegQuality = max(1, min(100, int(request.form.get("jpeg_quality", 95))))
    enableResize = request.form.get("enable_resize") == "on"
    longEdge = max(100, min(20000, int(request.form.get("long_edge", 2160))))
    sharpenAmount = max(0, min(500, int(request.form.get("sharpen_amount", 100))))
    enableExif = request.form.get("enable_exif") == "on"
    enableXmpDir = request.form.get("enable_xmp_dir") == "on"
    enableCcv = request.form.get("enable_ccv") == "on"

    options = {
        "sdrColorspace": sdrColorspace,
        "jpegQuality": jpegQuality,
        "enableResize": enableResize,
        "longEdge": longEdge,
        "sharpenAmount": sharpenAmount,
        "enableExif": enableExif,
        "enableXmpDir": enableXmpDir,
        "enableCcv": enableCcv,
    }

    # Save all files to temp directory and build pairs list
    tempDir = tempfile.mkdtemp(prefix="gainmap_batch_")
    hdrDir = os.path.join(tempDir, "hdr")
    sdrDir = os.path.join(tempDir, "sdr")
    os.makedirs(hdrDir)
    os.makedirs(sdrDir)

    pairs = []
    for hdrFile, sdrFile, baseName in matched:
        hdrPath = os.path.join(hdrDir, hdrFile.filename)
        sdrPath = os.path.join(sdrDir, sdrFile.filename)
        hdrFile.save(hdrPath)
        sdrFile.save(sdrPath)
        pairs.append((hdrPath, sdrPath, baseName))

    # Register session with progress tracking
    sessionId = uuid.uuid4().hex[:12]
    activeSessions[sessionId] = {
        "tempDir": tempDir,
        "type": "batch",
        "progress": {
            "total": len(pairs),
            "completed": 0,
            "current": None,
            "errors": [],
            "done": False,
        },
        "unmatchedHdr": sorted(unmatchedHdr),
        "unmatchedSdr": sorted(unmatchedSdr),
        "zipPath": None,
    }

    # Start background processing thread
    thread = threading.Thread(
        target=_processBatch,
        args=(sessionId, pairs, tempDir, options),
        daemon=True,
    )
    thread.start()

    return redirect(url_for("batchResults", session_id=sessionId))


@app.route("/batch/results/<session_id>")
def batchResults(session_id):
    if session_id not in activeSessions:
        return redirect(url_for("index"))

    session = activeSessions[session_id]
    return render_template(
        "batch_results.html",
        sessionId=session_id,
        total=session["progress"]["total"],
        unmatchedHdr=session.get("unmatchedHdr", []),
        unmatchedSdr=session.get("unmatchedSdr", []),
    )


@app.route("/batch/status/<session_id>")
def batchStatus(session_id):
    if session_id not in activeSessions:
        return Response(
            json.dumps({"error": "Session not found"}),
            status=404,
            mimetype="application/json",
        )

    progress = activeSessions[session_id]["progress"]
    return Response(
        json.dumps(progress),
        mimetype="application/json",
    )


@app.route("/batch/download/<session_id>")
def batchDownload(session_id):
    if session_id not in activeSessions:
        abort(404)

    session = activeSessions[session_id]
    zipPath = session.get("zipPath")

    if not zipPath or not os.path.exists(zipPath):
        abort(404)

    with open(zipPath, "rb") as f:
        zipData = f.read()

    shutil.rmtree(session["tempDir"], ignore_errors=True)
    del activeSessions[session_id]

    return send_file(
        io.BytesIO(zipData),
        mimetype="application/zip",
        as_attachment=True,
        download_name="gainmap_batch.zip",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debugMode = os.environ.get("DEBUG", "1") == "1"
    try:
        app.run(host="0.0.0.0", debug=debugMode, port=port)
    except OSError:
        print(f"Port {port} is busy (macOS AirPlay often uses 5000). Trying {port + 1}.")
        app.run(host="0.0.0.0", debug=debugMode, port=port + 1)
