import os
import shutil
import tempfile
import time
import uuid

from flask import Flask, render_template, request, send_file, redirect, url_for, abort

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

    import io
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    try:
        app.run(debug=True, port=port)
    except OSError:
        print(f"Port {port} is busy (macOS AirPlay often uses 5000). Trying {port + 1}.")
        app.run(debug=True, port=port + 1)
