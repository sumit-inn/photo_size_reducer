# Orbit File Studio

This folder contains:
- `index.html` — responsive, browser-based compressor and converter
- `smart_compressor.py` — recursive Python batch compressor
- `requirements.txt` — Python dependencies
- `input/` — place files here for the Python script
- `output/` — generated outputs and log go here

## Web app
Open `index.html` in Chrome or Edge, or use VS Code Live Server. Processing happens in your browser; files are not uploaded. PDF, ZIP, and TIFF helpers load from a CDN only when needed, so those features require an internet connection. Video uses native browser decoding and recording, so it does not download a large video engine.

The app has Compress, Convert, History, and Settings pages. It supports JPG/JPEG, PNG, WebP, GIF, BMP, TIFF, PDF, MP4, MOV, WebM, and MKV inputs. Image output can be WebP, JPEG, or PNG; PDF output is PDF; video output can be MP4 or WebM when supported by the browser. GIF conversion uses only the first frame. Image decoding and available video codecs vary by browser, and unreadable or unsupported files show an error instead of being silently skipped.

## Python desktop script (Windows / VS Code)
Install Python 3.10+ and run:

```powershell
py -m pip install -r requirements.txt
py smart_compressor.py
```

Put JPG/JPEG, PNG, WebP, GIF, BMP, TIFF, PDF, MP4, MOV, WebM, and MKV files in `input/`. Outputs are saved under `output/`, preserving subfolders and using `_compressed` filenames. GIF inputs are converted from their first frame.

Options:

```powershell
py smart_compressor.py --quality 90
py smart_compressor.py --input "D:\MyFiles" --output "D:\Compressed" --quality 80
py smart_compressor.py --image-format jpg --video-format webm
```

Quality must be from 10 to 95. Image formats are `webp`, `jpg`, and `png`; video formats are `mp4` and `webm`. Video processing requires FFmpeg installed and available on `PATH`. Original files are not overwritten. Errors are logged to `output/compressor.log`.

## Notes
- WebP and JPEG image conversion are lossy; PNG is optimized losslessly. JPEG output composites transparency onto white.
- PDF processing is structural optimization, not guaranteed deep image recompression or a smaller output.
- Video output is transcoded and may take a long time. Browser video processing depends on native codecs available in that browser.
- Always check output files before using them as replacements for originals.
