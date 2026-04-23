import sys
import re
import math
import json
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QSlider, QLabel,
                             QFileDialog, QGridLayout, QGroupBox, QCheckBox,
                             QComboBox, QProgressDialog, QSizePolicy, QFrame)
from PyQt6.QtCore import Qt, QTimer, QUrl, QThread, pyqtSignal, QPointF, QRectF
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QBrush, QPolygonF, QLinearGradient
import subprocess
import tempfile
import os


# ─────────────────────────────────────────────
#  Background Thread: Subtitle Extraction
# ─────────────────────────────────────────────
class SubtitleExtractorThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(list)
    error    = pyqtSignal(str)

    def __init__(self, video_path, ffmpeg_path):
        super().__init__()
        self.video_path  = video_path
        self.ffmpeg_path = ffmpeg_path

    def run(self):
        try:
            self.progress.emit("Extracting subtitles…")
            temp_srt = os.path.join(tempfile.gettempdir(), 'dji_subs.srt')

            subprocess.run(
                [self.ffmpeg_path, '-y', '-i', self.video_path, '-map', '0:2', temp_srt],
                capture_output=True, text=True, timeout=60
            )

            if not os.path.exists(temp_srt) or os.path.getsize(temp_srt) == 0:
                self.error.emit("SRT file could not be created!")
                return

            self.progress.emit("Parsing telemetry…")
            subtitles = self._parse_srt(temp_srt)
            self.progress.emit(f"{len(subtitles)} subtitles loaded")
            self.finished.emit(subtitles)

        except Exception as e:
            self.error.emit(str(e))

    def _parse_srt(self, filepath):
        subtitles = []
        content   = None
        for enc in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
            try:
                with open(filepath, 'r', encoding=enc) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue
        if not content:
            return subtitles

        for block in re.split(r'\n\n+', content.strip()):
            lines = block.strip().split('\n')
            if len(lines) >= 3 and '-->' in lines[1]:
                try:
                    s, e = lines[1].split('-->')
                    subtitles.append({
                        'start': self._to_ms(s),
                        'end':   self._to_ms(e),
                        'text':  '\n'.join(lines[2:])
                    })
                except Exception:
                    pass
        return subtitles

    @staticmethod
    def _to_ms(t):
        t = t.strip().replace('.', ',')
        h, m, s = t.split(':')
        s, ms = s.split(',')
        return int(h)*3600000 + int(m)*60000 + int(s)*1000 + int(ms)


# ─────────────────────────────────────────────
#  Telemetry Parser
# ─────────────────────────────────────────────
class TelemetryParser:
    @staticmethod
    def parse(text):
        def f(pattern, t=text):
            m = re.search(pattern, t)
            return m.group(1) if m else None

        lat = lon = alt = None
        gps = re.search(r'GPS\s*\(([\d.]+),\s*([\d.]+),\s*([\d.]+)\)', text)
        if gps:
            lon = float(gps.group(1))
            lat = float(gps.group(2))
            alt = float(gps.group(3))

        return {
            'f_stop':        f(r'F/([\d.]+)'),
            'shutter_speed': f(r'SS\s+([\d.]+)'),
            'iso':           f(r'ISO\s+(\d+)'),
            'ev':            f(r'EV\s+([-\d.]+)'),
            'digital_zoom':  f(r'DZOOM\s+([\d.]+)'),
            'gps_lat':       lat,
            'gps_lon':       lon,
            'gps_alt':       alt,
            'distance':      float(f(r'D\s+([\d.]+)m') or 0) or None,
            'height':        float(f(r'H\s+([\d.]+)m')  or 0) or None,
            'h_speed':       float(f(r'H\.S\s+([-\d.]+)m/s') or 0),
            'v_speed':       float(f(r'V\.S\s*([-\d.]+)m/s') or 0),
        }

    @staticmethod
    def parse_all(subtitles):
        result = []
        for sub in subtitles:
            d = TelemetryParser.parse(sub['text'])
            d['time_ms'] = sub['start']
            result.append(d)
        return result


# ─────────────────────────────────────────────
#  Compass Widget
# ─────────────────────────────────────────────
class CompassWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._heading = 0.0
        self.setMinimumSize(120, 120)
        self.setMaximumSize(160, 160)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_heading(self, degrees):
        self._heading = degrees % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h   = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r      = min(w, h) / 2 - 6

        # ── Background circle ──
        painter.setBrush(QBrush(QColor(30, 30, 50)))
        painter.setPen(QPen(QColor(80, 80, 120), 2))
        painter.drawEllipse(QRectF(cx - r, cy - r, r*2, r*2))

        # ── Tick marks ──
        painter.setPen(QPen(QColor(120, 120, 160), 1))
        for i in range(36):
            angle = math.radians(i * 10)
            inner = r - (6 if i % 9 == 0 else 3)
            x1 = cx + inner * math.sin(angle)
            y1 = cy - inner * math.cos(angle)
            x2 = cx + r     * math.sin(angle)
            y2 = cy - r     * math.cos(angle)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        # ── Cardinal labels ──
        font = QFont("Arial", 7, QFont.Weight.Bold)
        painter.setFont(font)
        for label, angle in [("N", 0), ("E", 90), ("S", 180), ("W", 270)]:
            rad = math.radians(angle)
            lx  = cx + (r - 14) * math.sin(rad) - 5
            ly  = cy - (r - 14) * math.cos(rad) + 5
            color = QColor(255, 80, 80) if label == "N" else QColor(200, 200, 220)
            painter.setPen(QPen(color))
            painter.drawText(int(lx), int(ly), label)

        # ── Needle (rotated by heading) ──
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self._heading)

        needle_len = r * 0.65

        # North tip (red)
        north = QPolygonF([
            QPointF(0, -needle_len),
            QPointF(-6, 0),
            QPointF(6, 0),
        ])
        painter.setBrush(QBrush(QColor(220, 60, 60)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(north)

        # South tip (white)
        south = QPolygonF([
            QPointF(0, needle_len * 0.6),
            QPointF(-6, 0),
            QPointF(6, 0),
        ])
        painter.setBrush(QBrush(QColor(220, 220, 240)))
        painter.drawPolygon(south)

        # Center cap
        painter.setBrush(QBrush(QColor(60, 60, 80)))
        painter.setPen(QPen(QColor(150, 150, 180), 1))
        painter.drawEllipse(QRectF(-5, -5, 10, 10))

        painter.restore()

        # ── Heading text ──
        painter.setPen(QPen(QColor(200, 200, 220)))
        font2 = QFont("Arial", 8, QFont.Weight.Bold)
        painter.setFont(font2)
        painter.drawText(
            QRectF(0, cy + r - 18, w, 18),
            Qt.AlignmentFlag.AlignHCenter,
            f"{self._heading:.1f}°"
        )


# ─────────────────────────────────────────────
#  Map Widget (Leaflet + CartoDB)
# ─────────────────────────────────────────────
class MapWidget(QWebEngineView):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(400, 300)
        self._ready   = False
        self._pending = []
        self.loadFinished.connect(self._on_ready)
        self._init_map()

    def _on_ready(self, ok):
        self._ready = True
        for js in self._pending:
            self.page().runJavaScript(js)
        self._pending.clear()

    def _js(self, code):
        if self._ready:
            self.page().runJavaScript(code)
        else:
            self._pending.append(code)

    def _init_map(self):
        html = r"""
        <!DOCTYPE html><html><head>
        <meta charset="utf-8">
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>
          body{margin:0;padding:0;background:#1a1a2e}
          #map{height:100vh;width:100%}
          #legend{
            position:absolute;bottom:30px;right:10px;z-index:1000;
            background:rgba(0,0,0,.78);padding:10px 14px;border-radius:8px;
            color:#fff;font:12px Arial;min-width:150px;display:none;
          }
          #legend-bar{
            height:12px;border-radius:4px;margin:6px 0 4px;
            background:linear-gradient(to right,#00cc44,#ffcc00,#ff2200);
          }
          #legend-labels{display:flex;justify-content:space-between;font-size:11px;color:#ccc}
        </style>
        </head><body>
        <div id="map"></div>
        <div id="legend">
          <div id="leg-title">Speed</div>
          <div id="legend-bar"></div>
          <div id="legend-labels">
            <span id="leg-min">0 m/s</span>
            <span id="leg-max">? m/s</span>
          </div>
        </div>
        <script>
        var map = L.map('map').setView([52.6014,10.0860],15);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',{
          attribution:'© OpenStreetMap © CARTO',subdomains:'abcd',maxZoom:20
        }).addTo(map);

        var droneIcon = L.divIcon({
          html:'<div style="background:#007bff;border:2px solid white;border-radius:50%;width:14px;height:14px;box-shadow:0 0 6px rgba(0,120,255,.8)"></div>',
          iconSize:[14,14],iconAnchor:[7,7],className:''
        });
        var marker = L.marker([52.6014,10.0860],{icon:droneIcon}).addTo(map);

        var segments=[], pathVisible=true;

        function speedColor(t){
          var r,g,b=0;
          if(t<0.5){r=Math.round(255*t*2);g=204;}
          else{r=255;g=Math.round(204*(1-(t-0.5)*2));}
          return 'rgb('+r+','+g+','+b+')';
        }

        function loadPath(points, minS, maxS, label){
          segments.forEach(function(s){map.removeLayer(s);});
          segments=[];
          if(points.length<2) return;
          for(var i=0;i<points.length-1;i++){
            var p=points[i], q=points[i+1];
            var t=(maxS>minS)?(p.speed-minS)/(maxS-minS):0;
            var seg=L.polyline([[p.lat,p.lon],[q.lat,q.lon]],{
              color:speedColor(Math.max(0,Math.min(1,t))),weight:4,opacity:.9
            });
            if(pathVisible) seg.addTo(map);
            segments.push(seg);
          }
          var ll=points.map(function(p){return[p.lat,p.lon];});
          map.fitBounds(L.latLngBounds(ll).pad(0.1));
          document.getElementById('legend').style.display='block';
          document.getElementById('leg-title').innerText=label;
          document.getElementById('leg-min').innerText=minS.toFixed(1)+' m/s';
          document.getElementById('leg-max').innerText=maxS.toFixed(1)+' m/s';
        }

        function smoothPath(points, factor){
          if(factor<=0||points.length<3) return points;
          var out=points.slice();
          for(var iter=0;iter<factor;iter++){
            var tmp=out.slice();
            for(var i=1;i<tmp.length-1;i++){
              tmp[i]={
                lat:(out[i-1].lat+out[i].lat*2+out[i+1].lat)/4,
                lon:(out[i-1].lon+out[i].lon*2+out[i+1].lon)/4,
                speed:out[i].speed
              };
            }
            out=tmp;
          }
          return out;
        }

        var _rawPoints=[], _minS=0, _maxS=1, _label='';

        function loadFullPath(points,minS,maxS,label,smooth){
          _rawPoints=points; _minS=minS; _maxS=maxS; _label=label;
          loadPath(smoothPath(points,smooth),minS,maxS,label);
        }

        function updateSmooth(smooth){
          loadPath(smoothPath(_rawPoints,smooth),_minS,_maxS,_label);
        }

        function updatePosition(lat,lon){marker.setLatLng([lat,lon]);}

        function setPathVisible(v){
          pathVisible=v;
          segments.forEach(function(s){v?s.addTo(map):map.removeLayer(s);});
        }

        function clearAll(){
          segments.forEach(function(s){map.removeLayer(s);});
          segments=[];
          document.getElementById('legend').style.display='none';
        }
        </script>
        </body></html>
        """
        self._ready = False
        self.setHtml(html)

    def load_full_path(self, telemetry, speed_mode, smooth=0):
        points, speeds = [], []
        for t in telemetry:
            lat, lon = t.get('gps_lat'), t.get('gps_lon')
            spd = abs(t.get('v_speed', 0)) if speed_mode == 'vertical' else t.get('h_speed', 0)
            if lat and lon:
                points.append({'lat': lat, 'lon': lon, 'speed': spd})
                speeds.append(spd)
        if not points:
            return
        mn, mx = min(speeds), max(speeds)
        label  = "Vertical Speed" if speed_mode == 'vertical' else "Horizontal Speed"
        self._js(f"loadFullPath({json.dumps(points)},{mn},{mx},'{label}',{smooth});")

    def update_smooth(self, smooth):
        self._js(f"updateSmooth({smooth});")

    def update_position(self, lat, lon):
        self._js(f"updatePosition({lat},{lon});")

    def set_path_visible(self, v):
        self._js(f"setPathVisible({'true' if v else 'false'});")

    def clear_all(self):
        self._js("clearAll();")


# ─────────────────────────────────────────────
#  Main Window
# ─────────────────────────────────────────────
class DJITelemetryViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DJI MINI 4K – Telemetry Viewer")
        self.setGeometry(100, 100, 1560, 900)

        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)

        self.video_widget = QVideoWidget()
        self.media_player.setVideoOutput(self.video_widget)

        self.subtitles      = []
        self.telemetry_data = []
        self.speed_mode     = 'horizontal'
        self.smooth_value   = 0

        self.sub_timer = QTimer()
        self.sub_timer.timeout.connect(self._update_telemetry)

        self._setup_ui()

    # ── UI Construction ────────────────────────
    def _setup_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root_h = QHBoxLayout(root)
        root_h.setSpacing(8)
        root_h.setContentsMargins(8, 8, 8, 8)

        # Left column
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(self.video_widget, stretch=4)
        left.addWidget(self._build_telemetry_panel())
        left.addLayout(self._build_controls())

        # Right column
        right = QVBoxLayout()
        right.setSpacing(6)
        self.map_widget = MapWidget()
        right.addWidget(self.map_widget, stretch=1)
        right.addLayout(self._build_map_controls())

        root_h.addLayout(left,  stretch=2)
        root_h.addLayout(right, stretch=1)

        self._build_menu()

    def _build_telemetry_panel(self):
        outer = QWidget()
        outer_h = QHBoxLayout(outer)
        outer_h.setContentsMargins(0, 0, 0, 0)
        outer_h.setSpacing(8)

        # ── Big readouts (Height + Speeds) ──────
        big_group = QGroupBox("Primary Flight Data")
        big_group.setStyleSheet("QGroupBox{font-weight:bold;font-size:13px;}")
        big_v = QVBoxLayout(big_group)
        big_v.setSpacing(4)

        self.lbl_height  = self._big_label("--")
        self.lbl_hspeed  = self._big_label("--")
        self.lbl_vspeed  = self._big_label("--")

        big_v.addLayout(self._labeled_big("Height",          self.lbl_height,  "m"))
        big_v.addLayout(self._labeled_big("Horiz. Speed",    self.lbl_hspeed,  "m/s"))
        big_v.addLayout(self._labeled_big("Vert. Speed",     self.lbl_vspeed,  "m/s"))

        # ── Compass ─────────────────────────────
        compass_group = QGroupBox("Heading")
        compass_group.setStyleSheet("QGroupBox{font-weight:bold;font-size:13px;}")
        compass_v = QVBoxLayout(compass_group)
        self.compass = CompassWidget()
        compass_v.addWidget(self.compass, alignment=Qt.AlignmentFlag.AlignCenter)

        # ── Secondary telemetry grid ─────────────
        sec_group = QGroupBox("Camera & GPS")
        sec_group.setStyleSheet("QGroupBox{font-weight:bold;font-size:13px;}")
        grid = QGridLayout(sec_group)
        grid.setSpacing(4)

        self.sec_labels = {}
        fields = [
            ("Aperture",    "f_stop",       ""),
            ("Shutter",     "shutter_speed",""),
            ("ISO",         "iso",          ""),
            ("EV",          "ev",           ""),
            ("D.Zoom",      "digital_zoom", ""),
            ("GPS Lat",     "gps_lat",      "°"),
            ("GPS Lon",     "gps_lon",      "°"),
            ("GPS Alt",     "gps_alt",      " m"),
            ("Distance",    "distance",     " m"),
        ]
        r = c = 0
        for name, key, unit in fields:
            nl = QLabel(f"<b>{name}:</b>")
            nl.setStyleSheet("font-size:11px;")
            vl = QLabel("--")
            vl.setStyleSheet("color:#0066cc;font-size:12px;font-weight:bold;")
            grid.addWidget(nl, r, c*2)
            grid.addWidget(vl, r, c*2+1)
            self.sec_labels[key] = (vl, unit)
            c += 1
            if c >= 3:
                c = 0
                r += 1

        outer_h.addWidget(big_group,    stretch=0)
        outer_h.addWidget(compass_group,stretch=0)
        outer_h.addWidget(sec_group,    stretch=1)
        return outer

    def _big_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color:#00aaff;font-size:28px;font-weight:bold;"
            "font-family:monospace;letter-spacing:1px;"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return lbl

    def _labeled_big(self, name, val_lbl, unit):
        row = QHBoxLayout()
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("font-size:12px;color:#aaaaaa;")
        unit_lbl = QLabel(unit)
        unit_lbl.setStyleSheet("font-size:14px;color:#888888;")
        row.addWidget(name_lbl)
        row.addStretch()
        row.addWidget(val_lbl)
        row.addWidget(unit_lbl)
        return row

    def _build_controls(self):
        layout = QVBoxLayout()

        # Seek slider
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderMoved.connect(self._set_position)
        layout.addWidget(self.seek_slider)

        # Time
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.time_label)

        # Buttons
        btn_row = QHBoxLayout()
        for label, cb in [
            ("⏪ -10s",  lambda: self._skip(-10000)),
            ("⏮ -1s",   lambda: self._skip(-1000)),
            ("▶ Play",   self._play_pause),
            ("⏹ Stop",   self._stop),
            ("⏭ +1s",   lambda: self._skip(1000)),
            ("⏩ +10s",  lambda: self._skip(10000)),
        ]:
            b = QPushButton(label)
            b.setMinimumHeight(34)
            if label == "▶ Play":
                self.play_btn = b
            b.clicked.connect(cb)
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        # Volume + status
        bot = QHBoxLayout()
        bot.addWidget(QLabel("🔊"))
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(50)
        self.vol_slider.setMaximumWidth(130)
        self.vol_slider.valueChanged.connect(lambda v: self.audio_output.setVolume(v/100))
        bot.addWidget(self.vol_slider)
        bot.addStretch()
        self.status_lbl = QLabel("No video loaded")
        self.status_lbl.setStyleSheet("color:gray;font-size:11px;")
        bot.addWidget(self.status_lbl)
        layout.addLayout(bot)

        self.media_player.positionChanged.connect(self._position_changed)
        self.media_player.durationChanged.connect(self._duration_changed)
        return layout

    def _build_map_controls(self):
        layout = QVBoxLayout()
        layout.setSpacing(4)

        row1 = QHBoxLayout()

        self.path_cb = QCheckBox("Show flight path")
        self.path_cb.setChecked(True)
        self.path_cb.stateChanged.connect(
            lambda s: self.map_widget.set_path_visible(s == Qt.CheckState.Checked.value))
        row1.addWidget(self.path_cb)

        row1.addWidget(QLabel("Color by:"))
        self.speed_combo = QComboBox()
        self.speed_combo.addItem("Horizontal Speed", "horizontal")
        self.speed_combo.addItem("Vertical Speed",   "vertical")
        self.speed_combo.currentIndexChanged.connect(self._change_speed_mode)
        row1.addWidget(self.speed_combo)
        row1.addStretch()
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Path smoothing:"))
        self.smooth_slider = QSlider(Qt.Orientation.Horizontal)
        self.smooth_slider.setRange(0, 50)
        self.smooth_slider.setValue(0)
        self.smooth_slider.setTickInterval(5)
        self.smooth_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.smooth_slider.valueChanged.connect(self._change_smooth)
        row2.addWidget(self.smooth_slider)
        self.smooth_lbl = QLabel("0")
        self.smooth_lbl.setMinimumWidth(24)
        row2.addWidget(self.smooth_lbl)
        layout.addLayout(row2)

        return layout

    def _build_menu(self):
        mb   = self.menuBar()
        fmnu = mb.addMenu("File")
        fmnu.addAction("Open Video…", self._open_file)
        fmnu.addSeparator()
        fmnu.addAction("Quit", self.close)

    # ── File Opening ───────────────────────────
    def _find_ffmpeg(self):
        for p in ['ffmpeg', 'ffmpeg.exe',
                  r'C:\ffmpeg\bin\ffmpeg.exe', r'C:\ffmpeg\ffmpeg.exe']:
            try:
                r = subprocess.run([p, '-version'], capture_output=True, timeout=5)
                if r.returncode == 0:
                    return p
            except Exception:
                pass
        return None

    def _open_file(self):
        fn, _ = QFileDialog.getOpenFileName(
            self, "Open DJI Video", "", "Video Files (*.mp4 *.mov *.avi)")
        if not fn:
            return

        self.media_player.setSource(QUrl.fromLocalFile(fn))
        # Show first frame
        self.media_player.play()
        QTimer.singleShot(150, lambda: self.media_player.pause())
        QTimer.singleShot(160, lambda: self.media_player.setPosition(0))

        self.map_widget.clear_all()
        self.subtitles      = []
        self.telemetry_data = []

        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            self.status_lbl.setText("❌ FFmpeg not found!")
            return

        self._prog = QProgressDialog("Extracting telemetry…", None, 0, 0, self)
        self._prog.setWindowTitle("Please wait")
        self._prog.setWindowModality(Qt.WindowModality.WindowModal)
        self._prog.setCancelButton(None)
        self._prog.show()

        self._extractor = SubtitleExtractorThread(fn, ffmpeg)
        self._extractor.progress.connect(self._on_progress)
        self._extractor.finished.connect(self._on_extracted)
        self._extractor.error.connect(self._on_error)
        self._extractor.start()

    def _on_progress(self, msg):
        self.status_lbl.setText(msg)
        if hasattr(self, '_prog'):
            self._prog.setLabelText(msg)

    def _on_error(self, msg):
        self.status_lbl.setText(f"❌ {msg}")
        if hasattr(self, '_prog'):
            self._prog.close()

    def _on_extracted(self, subtitles):
        self._prog.setLabelText("Building flight path…")
        self.subtitles      = subtitles
        self.telemetry_data = TelemetryParser.parse_all(subtitles)

        if self.telemetry_data:
            self.map_widget.load_full_path(
                self.telemetry_data, self.speed_mode, self.smooth_value)
            self.sub_timer.start(100)

        self._prog.close()
        self.status_lbl.setText(f"✓ {len(self.telemetry_data)} telemetry points")

    # ── Map controls ───────────────────────────
    def _change_speed_mode(self):
        self.speed_mode = self.speed_combo.currentData()
        if self.telemetry_data:
            self.map_widget.load_full_path(
                self.telemetry_data, self.speed_mode, self.smooth_value)

    def _change_smooth(self, val):
        self.smooth_value = val
        self.smooth_lbl.setText(str(val))
        if self.telemetry_data:
            self.map_widget.update_smooth(val)

    # ── Telemetry update ───────────────────────
    def _update_telemetry(self):
        pos = self.media_player.position()
        td  = self.telemetry_data
        if not td:
            return

        # Binary search
        lo, hi, found = 0, len(td)-1, None
        while lo <= hi:
            mid = (lo+hi)//2
            if td[mid]['time_ms'] <= pos:
                found = td[mid]
                lo = mid+1
            else:
                hi = mid-1

        if not found:
            return

        # Big readouts
        h  = found.get('height',  0) or 0
        hs = found.get('h_speed', 0) or 0
        vs = found.get('v_speed', 0) or 0
        self.lbl_height.setText(f"{h:.1f}")
        self.lbl_hspeed.setText(f"{hs:.2f}")
        self.lbl_vspeed.setText(f"{vs:.2f}")

        # Secondary grid
        fmt = {
            'f_stop':        lambda v: str(v),
            'shutter_speed': lambda v: str(v),
            'iso':           lambda v: str(v),
            'ev':            lambda v: str(v),
            'digital_zoom':  lambda v: str(v),
            'gps_lat':       lambda v: f"{v:.6f}",
            'gps_lon':       lambda v: f"{v:.6f}",
            'gps_alt':       lambda v: f"{v:.1f}",
            'distance':      lambda v: f"{v:.1f}",
        }
        for key, (lbl, unit) in self.sec_labels.items():
            v = found.get(key)
            lbl.setText((fmt[key](v) + unit) if v is not None else "--")

        # Map position
        lat, lon = found.get('gps_lat'), found.get('gps_lon')
        if lat and lon:
            self.map_widget.update_position(lat, lon)

        # Heading from GPS
        self._update_heading(pos, found)

    def _update_heading(self, pos_ms, current):
        """Calculate heading from consecutive GPS points"""
        td  = self.telemetry_data
        idx = next((i for i, t in enumerate(td) if t['time_ms'] == current['time_ms']), None)
        if idx is None or idx == 0:
            return

        prev = td[idx-1]
        lat1, lon1 = prev.get('gps_lat'),    prev.get('gps_lon')
        lat2, lon2 = current.get('gps_lat'), current.get('gps_lon')

        if not all([lat1, lon1, lat2, lon2]):
            return
        if abs(lat2-lat1) < 1e-7 and abs(lon2-lon1) < 1e-7:
            return

        # Bearing calculation
        dlon  = math.radians(lon2 - lon1)
        rlat1 = math.radians(lat1)
        rlat2 = math.radians(lat2)
        x = math.sin(dlon) * math.cos(rlat2)
        y = (math.cos(rlat1)*math.sin(rlat2) -
             math.sin(rlat1)*math.cos(rlat2)*math.cos(dlon))
        bearing = (math.degrees(math.atan2(x, y)) + 360) % 360
        self.compass.set_heading(bearing)

    # ── Playback controls ──────────────────────
    def _play_pause(self):
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            self.play_btn.setText("▶ Play")
        else:
            self.media_player.play()
            self.play_btn.setText("⏸ Pause")

    def _stop(self):
        self.media_player.stop()
        self.play_btn.setText("▶ Play")

    def _skip(self, ms):
        self.media_player.setPosition(max(0, self.media_player.position()+ms))

    def _set_position(self, pos):
        self.media_player.setPosition(pos)

    def _position_changed(self, pos):
        self.seek_slider.setValue(pos)
        dur = self.media_player.duration()
        self.time_label.setText(f"{self._fmt(pos)} / {self._fmt(dur)}")

    def _duration_changed(self, dur):
        self.seek_slider.setRange(0, dur)

    @staticmethod
    def _fmt(ms):
        s = ms // 1000
        return f"{s//60:02d}:{s%60:02d}"


# ─────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = DJITelemetryViewer()
    win.show()
    sys.exit(app.exec())
