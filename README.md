# DJI MINI 4K Telemetry Viewer

A desktop application for viewing DJI MINI 4K drone footage with synchronized telemetry overlay, interactive map, and heading compass.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![PyQt6](https://img.shields.io/badge/PyQt6-6.x-green) ![License](https://img.shields.io/badge/License-MIT-yellow)

---

https://github.com/swigggis/DJI-Telemetry/blob/61b0cbc37b914c7000d239f3c113fff4f4631018/screenshot.png

## Features

- Video playback with full transport controls
- Real-time telemetry display (GPS, altitude, speed, camera settings)
- OpenStreetMap flight path with speed-based color gradient
- Path smoothing slider
- Heading compass calculated from GPS coordinates
- Background telemetry extraction

---

## Requirements

- Python 3.10 or newer
- FFmpeg

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/yourname/dji-telemetry-viewer.git
cd dji-telemetry-viewer
```

### 2. Install Python dependencies

```bash
pip install PyQt6 PyQt6-WebEngine
```

### 3. Install FFmpeg

#### Windows

1. Download the latest build from [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/) — choose `ffmpeg-release-essentials.zip`
2. Extract the archive, for example to `C:\ffmpeg`
3. Add FFmpeg to your system PATH — open PowerShell and run:

```powershell
[Environment]::SetEnvironmentVariable(
    "Path",
    [Environment]::GetEnvironmentVariable("Path", "User") + ";C:\ffmpeg\bin",
    "User"
)
```

4. Close and reopen PowerShell, then verify:

```powershell
ffmpeg -version
```

#### macOS

```bash
brew install ffmpeg
```

#### Linux (Debian / Ubuntu)

```bash
sudo apt update && sudo apt install ffmpeg
```

---

## Usage

```bash
python telemetry.py
```

1. Click **File → Open Video…** and select a DJI `.mp4` file
2. Telemetry is extracted automatically from the embedded subtitle track
3. The flight path is rendered on the map with a speed color gradient
4. Use the **Path smoothing** slider to reduce GPS noise on the map
5. Switch between **Horizontal** and **Vertical Speed** coloring via the dropdown

---

## Compatibility

Tested with footage from the **DJI MINI 4K**.  
The app expects telemetry embedded as `mov_text` subtitles in stream `0:2`.  
Other DJI models with the same subtitle format should work as well.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `FFmpeg not found` | Make sure `ffmpeg` is in your PATH (see installation above) |
| No telemetry shown | Run `ffprobe your_video.mp4` and check that a subtitle stream exists |
| Map tiles not loading | Check your internet connection |
| Black video window | Codec issue — ensure your PyQt6 installation is complete |

---

## License

MIT
