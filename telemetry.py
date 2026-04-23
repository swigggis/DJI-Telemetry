import sys
import re
import math
import json
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QSlider, QLabel,
                             QFileDialog, QGridLayout, QGroupBox, QCheckBox,
                             QComboBox, QProgressDialog, QSizePolicy, QFrame,
                             QMenu, QMessageBox)
from PyQt6.QtCore import Qt, QTimer, QUrl, QThread, pyqtSignal, QPointF, QRectF, QSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QBrush, QPolygonF, QLinearGradient, QActionGroup
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

        function loadPath(points, minS, maxS, label, unitLabel){
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
          document.getElementById('leg-min').innerText=minS.toFixed(1)+' '+unitLabel;
          document.getElementById('leg-max').innerText=maxS.toFixed(1)+' '+unitLabel;
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

        var _rawPoints=[], _minS=0, _maxS=1, _label='', _unitLabel='m/s';

        function loadFullPath(points,minS,maxS,label,unitLabel,smooth){
          _rawPoints=points; _minS=minS; _maxS=maxS; _label=label; _unitLabel=unitLabel;
          loadPath(smoothPath(points,smooth),minS,maxS,label,unitLabel);
        }

        function updateSmooth(smooth){
          loadPath(smoothPath(_rawPoints,smooth),_minS,_maxS,_label,_unitLabel);
        }

        function updateLegendUnit(unitLabel){
          _unitLabel = unitLabel;
          loadPath(smoothPath(_rawPoints,0),_minS,_maxS,_label,_unitLabel);
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

    def load_full_path(self, telemetry, speed_mode, smooth=0, unit="m/s"):
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
        self._js(f"loadFullPath({json.dumps(points)},{mn},{mx},'{label}','{unit}',{smooth});")

    def update_smooth(self, smooth):
        self._js(f"updateSmooth({smooth});")

    def update_legend_unit(self, unit):
        self._js(f"updateLegendUnit('{unit}');")

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

        # Settings
        self.settings = QSettings("DJITelemetryViewer", "Settings")
        self.lang = self.settings.value("language", "en")
        self.units = self.settings.value("units", "metric")   # 'metric' or 'imperial'
        self.theme = self.settings.value("theme", "dark")     # 'dark' or 'light'

        self.sub_timer = QTimer()
        self.sub_timer.timeout.connect(self._update_telemetry)

        # Translation strings
        self.strings = {}
        self._init_strings()

        # References for dynamic updates
        self.height_name_lbl = None
        self.height_unit_lbl = None
        self.hspeed_name_lbl = None
        self.hspeed_unit_lbl = None
        self.vspeed_name_lbl = None
        self.vspeed_unit_lbl = None
        self.gps_alt_unit = "m"
        self.distance_unit = "m"

        self._setup_ui()
        self.apply_theme()
        self.apply_language()
        self.apply_units()

    def _init_strings(self):
        self.strings = {
            'en': {
                'window_title': 'DJI MINI 4K – Telemetry Viewer',
                'primary_flight': 'Primary Flight Data',
                'height': 'Height',
                'horiz_speed': 'Horiz. Speed',
                'vert_speed': 'Vert. Speed',
                'heading': 'Heading',
                'camera_gps': 'Camera & GPS',
                'aperture': 'Aperture',
                'shutter': 'Shutter',
                'iso': 'ISO',
                'ev': 'EV',
                'zoom': 'D.Zoom',
                'gps_lat': 'GPS Lat',
                'gps_lon': 'GPS Lon',
                'gps_alt': 'GPS Alt',
                'distance': 'Distance',
                'show_path': 'Show flight path',
                'color_by': 'Color by:',
                'horizontal_speed': 'Horizontal Speed',
                'vertical_speed': 'Vertical Speed',
                'path_smoothing': 'Path smoothing:',
                'file_menu': 'File',
                'open_video': 'Open Video…',
                'quit': 'Quit',
                'options_menu': 'Options',
                'language_menu': 'Language',
                'english': 'English',
                'german': 'German',
                'french': 'French',
                'units_menu': 'Units',
                'metric': 'Metric (m, m/s)',
                'imperial': 'Imperial (ft, mph)',
                'theme_menu': 'Theme',
                'dark': 'Dark',
                'light': 'Light',
                'no_video': 'No video loaded',
                'ffmpeg_error': '❌ FFmpeg not found!',
                'extracting': 'Extracting telemetry…',
                'building_path': 'Building flight path…',
                'ok': 'OK',
                'wait_title': 'Please wait',
                'speed_unit_ms': 'm/s',
                'speed_unit_mph': 'mph',
                'height_unit_m': 'm',
                'height_unit_ft': 'ft',
                'play': 'Play',
                'pause': 'Pause',
                'stop': 'Stop',
            },
            'de': {
                'window_title': 'DJI MINI 4K – Telemetrie-Viewer',
                'primary_flight': 'Primäre Flugdaten',
                'height': 'Höhe',
                'horiz_speed': 'Horiz. Geschw.',
                'vert_speed': 'Vert. Geschw.',
                'heading': 'Kurs',
                'camera_gps': 'Kamera & GPS',
                'aperture': 'Blende',
                'shutter': 'Verschluss',
                'iso': 'ISO',
                'ev': 'EV',
                'zoom': 'D.Zoom',
                'gps_lat': 'GPS Breite',
                'gps_lon': 'GPS Länge',
                'gps_alt': 'GPS Höhe',
                'distance': 'Entfernung',
                'show_path': 'Flugpfad anzeigen',
                'color_by': 'Färben nach:',
                'horizontal_speed': 'Horizontale Geschw.',
                'vertical_speed': 'Vertikale Geschw.',
                'path_smoothing': 'Pfadglättung:',
                'file_menu': 'Datei',
                'open_video': 'Video öffnen…',
                'quit': 'Beenden',
                'options_menu': 'Optionen',
                'language_menu': 'Sprache',
                'english': 'Englisch',
                'german': 'Deutsch',
                'french': 'Französisch',
                'units_menu': 'Einheiten',
                'metric': 'Metrisch (m, m/s)',
                'imperial': 'Imperial (ft, mph)',
                'theme_menu': 'Erscheinungsbild',
                'dark': 'Dunkel',
                'light': 'Hell',
                'no_video': 'Kein Video geladen',
                'ffmpeg_error': '❌ FFmpeg nicht gefunden!',
                'extracting': 'Extrahiere Telemetrie…',
                'building_path': 'Erstelle Flugpfad…',
                'ok': 'OK',
                'wait_title': 'Bitte warten',
                'speed_unit_ms': 'm/s',
                'speed_unit_mph': 'mph',
                'height_unit_m': 'm',
                'height_unit_ft': 'ft',
                'play': 'Abspielen',
                'pause': 'Pause',
                'stop': 'Stopp',
            },
            'fr': {
                'window_title': 'DJI MINI 4K – Visualisateur de télémétrie',
                'primary_flight': 'Données de vol principales',
                'height': 'Altitude',
                'horiz_speed': 'Vitesse horiz.',
                'vert_speed': 'Vitesse vert.',
                'heading': 'Cap',
                'camera_gps': 'Caméra & GPS',
                'aperture': 'Ouverture',
                'shutter': 'Vitesse',
                'iso': 'ISO',
                'ev': 'EV',
                'zoom': 'Z. num.',
                'gps_lat': 'Lat. GPS',
                'gps_lon': 'Long. GPS',
                'gps_alt': 'Alt. GPS',
                'distance': 'Distance',
                'show_path': 'Afficher trajectoire',
                'color_by': 'Couleur par :',
                'horizontal_speed': 'Vitesse horizontale',
                'vertical_speed': 'Vitesse verticale',
                'path_smoothing': 'Lissage trajectoire :',
                'file_menu': 'Fichier',
                'open_video': 'Ouvrir vidéo…',
                'quit': 'Quitter',
                'options_menu': 'Options',
                'language_menu': 'Langue',
                'english': 'Anglais',
                'german': 'Allemand',
                'french': 'Français',
                'units_menu': 'Unités',
                'metric': 'Métrique (m, m/s)',
                'imperial': 'Impérial (ft, mph)',
                'theme_menu': 'Thème',
                'dark': 'Sombre',
                'light': 'Clair',
                'no_video': 'Aucune vidéo chargée',
                'ffmpeg_error': '❌ FFmpeg introuvable !',
                'extracting': 'Extraction de la télémétrie…',
                'building_path': 'Construction de la trajectoire…',
                'ok': 'OK',
                'wait_title': 'Veuillez patienter',
                'speed_unit_ms': 'm/s',
                'speed_unit_mph': 'mph',
                'height_unit_m': 'm',
                'height_unit_ft': 'pi',
                'play': 'Lecture',
                'pause': 'Pause',
                'stop': 'Arrêt',
            }
        }

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
        self.big_group = QGroupBox()
        self.big_group.setStyleSheet("QGroupBox{font-weight:bold;font-size:13px;}")
        big_v = QVBoxLayout(self.big_group)
        big_v.setSpacing(4)

        self.lbl_height  = self._big_label("--")
        self.lbl_hspeed  = self._big_label("--")
        self.lbl_vspeed  = self._big_label("--")

        self.height_layout, self.height_name_lbl, self.height_unit_lbl = self._labeled_big("", self.lbl_height, "")
        self.hspeed_layout, self.hspeed_name_lbl, self.hspeed_unit_lbl = self._labeled_big("", self.lbl_hspeed, "")
        self.vspeed_layout, self.vspeed_name_lbl, self.vspeed_unit_lbl = self._labeled_big("", self.lbl_vspeed, "")

        big_v.addLayout(self.height_layout)
        big_v.addLayout(self.hspeed_layout)
        big_v.addLayout(self.vspeed_layout)

        # ── Compass ─────────────────────────────
        self.compass_group = QGroupBox()
        self.compass_group.setStyleSheet("QGroupBox{font-weight:bold;font-size:13px;}")
        compass_v = QVBoxLayout(self.compass_group)
        self.compass = CompassWidget()
        compass_v.addWidget(self.compass, alignment=Qt.AlignmentFlag.AlignCenter)

        # ── Secondary telemetry grid ─────────────
        self.sec_group = QGroupBox()
        grid = QGridLayout(self.sec_group)
        grid.setSpacing(4)

        self.sec_labels = {}
        fields = [
            ("aperture",    "f_stop",       ""),
            ("shutter",     "shutter_speed",""),
            ("iso",         "iso",          ""),
            ("ev",          "ev",           ""),
            ("zoom",        "digital_zoom", ""),
            ("gps_lat",     "gps_lat",      "°"),
            ("gps_lon",     "gps_lon",      "°"),
            ("gps_alt",     "gps_alt",      ""),
            ("distance",    "distance",     ""),
        ]
        r = c = 0
        self.sec_name_labels = {}
        for name_key, key, unit in fields:
            nl = QLabel()
            nl.setStyleSheet("font-size:11px;")
            vl = QLabel("--")
            vl.setStyleSheet("color:#0066cc;font-size:12px;font-weight:bold;")
            grid.addWidget(nl, r, c*2)
            grid.addWidget(vl, r, c*2+1)
            self.sec_labels[key] = (vl, unit)
            self.sec_name_labels[name_key] = nl
            c += 1
            if c >= 3:
                c = 0
                r += 1

        outer_h.addWidget(self.big_group,    stretch=0)
        outer_h.addWidget(self.compass_group,stretch=0)
        outer_h.addWidget(self.sec_group,    stretch=1)
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
        return row, name_lbl, unit_lbl

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
        self.buttons = {}
        for label_id, cb in [
            ("skip_back_10", lambda: self._skip(-10000)),
            ("skip_back_1",  lambda: self._skip(-1000)),
            ("play",         self._play_pause),
            ("stop",         self._stop),
            ("skip_forward_1", lambda: self._skip(1000)),
            ("skip_forward_10", lambda: self._skip(10000)),
        ]:
            b = QPushButton()
            b.setMinimumHeight(34)
            if label_id == "play":
                self.play_btn = b
            b.clicked.connect(cb)
            btn_row.addWidget(b)
            self.buttons[label_id] = b
        layout.addLayout(btn_row)

        # Volume + status
        bot = QHBoxLayout()
        self.vol_label = QLabel("🔊")
        bot.addWidget(self.vol_label)
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(50)
        self.vol_slider.setMaximumWidth(130)
        self.vol_slider.valueChanged.connect(lambda v: self.audio_output.setVolume(v/100))
        bot.addWidget(self.vol_slider)
        bot.addStretch()
        self.status_lbl = QLabel()
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

        self.path_cb = QCheckBox()
        self.path_cb.setChecked(True)
        self.path_cb.stateChanged.connect(
            lambda s: self.map_widget.set_path_visible(s == Qt.CheckState.CheckState.Checked.value))
        row1.addWidget(self.path_cb)

        self.color_label = QLabel()
        row1.addWidget(self.color_label)

        self.speed_combo = QComboBox()
        self.speed_combo.addItem("Horizontal Speed", "horizontal")
        self.speed_combo.addItem("Vertical Speed",   "vertical")
        self.speed_combo.currentIndexChanged.connect(self._change_speed_mode)
        row1.addWidget(self.speed_combo)
        row1.addStretch()
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.smooth_label = QLabel()
        row2.addWidget(self.smooth_label)
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
        mb = self.menuBar()
        self.file_menu = mb.addMenu("")
        self.file_menu.addAction("", self._open_file)
        self.file_menu.addSeparator()
        self.file_menu.addAction("", self.close)

        self.options_menu = mb.addMenu("")

        # Language submenu
        self.language_menu = self.options_menu.addMenu("")
        self.lang_group = QActionGroup(self)
        for lang_code, lang_name in [("en", "English"), ("de", "German"), ("fr", "French")]:
            action = self.language_menu.addAction(lang_name)
            action.setCheckable(True)
            action.setData(lang_code)
            if self.lang == lang_code:
                action.setChecked(True)
            action.triggered.connect(self._change_language)
            self.lang_group.addAction(action)

        # Units submenu
        self.units_menu = self.options_menu.addMenu("")
        self.units_group = QActionGroup(self)
        for unit_key, unit_name in [("metric", "Metric (m, m/s)"), ("imperial", "Imperial (ft, mph)")]:
            action = self.units_menu.addAction(unit_name)
            action.setCheckable(True)
            action.setData(unit_key)
            if self.units == unit_key:
                action.setChecked(True)
            action.triggered.connect(self._change_units)
            self.units_group.addAction(action)

        # Theme submenu
        self.theme_menu = self.options_menu.addMenu("")
        self.theme_group = QActionGroup(self)
        for theme_key, theme_name in [("dark", "Dark"), ("light", "Light")]:
            action = self.theme_menu.addAction(theme_name)
            action.setCheckable(True)
            action.setData(theme_key)
            if self.theme == theme_key:
                action.setChecked(True)
            action.triggered.connect(self._change_theme)
            self.theme_group.addAction(action)

    # ── Settings methods ───────────────────────
    def _change_language(self):
        action = self.sender()
        if action:
            self.lang = action.data()
            self.settings.setValue("language", self.lang)
            self.apply_language()

    def _change_units(self):
        action = self.sender()
        if action:
            self.units = action.data()
            self.settings.setValue("units", self.units)
            self.apply_units()

    def _change_theme(self):
        action = self.sender()
        if action:
            self.theme = action.data()
            self.settings.setValue("theme", self.theme)
            self.apply_theme()

    def apply_language(self):
        s = self.strings[self.lang]
        self.setWindowTitle(s['window_title'])
        self.big_group.setTitle(s['primary_flight'])
        self.compass_group.setTitle(s['heading'])
        self.sec_group.setTitle(s['camera_gps'])

        # Update big readout labels
        self.height_name_lbl.setText(s['height'])
        self.hspeed_name_lbl.setText(s['horiz_speed'])
        self.vspeed_name_lbl.setText(s['vert_speed'])

        # Update secondary field names
        name_map = {
            'aperture': s['aperture'], 'shutter': s['shutter'], 'iso': s['iso'],
            'ev': s['ev'], 'zoom': s['zoom'], 'gps_lat': s['gps_lat'],
            'gps_lon': s['gps_lon'], 'gps_alt': s['gps_alt'], 'distance': s['distance']
        }
        for key, label in name_map.items():
            if key in self.sec_name_labels:
                self.sec_name_labels[key].setText(f"<b>{label}:</b>")

        # Map controls
        self.path_cb.setText(s['show_path'])
        self.color_label.setText(s['color_by'])
        self.smooth_label.setText(s['path_smoothing'])

        # Combo items
        self.speed_combo.setItemText(0, s['horizontal_speed'])
        self.speed_combo.setItemText(1, s['vertical_speed'])

        # Menu
        self.file_menu.setTitle(s['file_menu'])
        self.file_menu.actions()[0].setText(s['open_video'])
        self.file_menu.actions()[2].setText(s['quit'])
        self.options_menu.setTitle(s['options_menu'])
        self.language_menu.setTitle(s['language_menu'])
        self.units_menu.setTitle(s['units_menu'])
        self.theme_menu.setTitle(s['theme_menu'])

        # Units and theme menu texts
        for action in self.units_menu.actions():
            if action.data() == "metric":
                action.setText(s['metric'])
            elif action.data() == "imperial":
                action.setText(s['imperial'])
        for action in self.theme_menu.actions():
            if action.data() == "dark":
                action.setText(s['dark'])
            elif action.data() == "light":
                action.setText(s['light'])

        # Buttons
        self.buttons["skip_back_10"].setText("⏪ -10s")
        self.buttons["skip_back_1"].setText("⏮ -1s")
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setText("⏸ " + s.get('pause', 'Pause'))
        else:
            self.play_btn.setText("▶ " + s.get('play', 'Play'))
        self.buttons["stop"].setText("⏹ " + s.get('stop', 'Stop'))
        self.buttons["skip_forward_1"].setText("⏭ +1s")
        self.buttons["skip_forward_10"].setText("⏩ +10s")

        # Status
        if not self.telemetry_data:
            self.status_lbl.setText(s['no_video'])

    def apply_units(self):
        s = self.strings[self.lang]
        if self.units == "metric":
            self.height_unit_lbl.setText(s['height_unit_m'])
            self.hspeed_unit_lbl.setText(s['speed_unit_ms'])
            self.vspeed_unit_lbl.setText(s['speed_unit_ms'])
            self.gps_alt_unit = s['height_unit_m']
            self.distance_unit = s['height_unit_m']
        else:  # imperial
            self.height_unit_lbl.setText(s['height_unit_ft'])
            self.hspeed_unit_lbl.setText(s['speed_unit_mph'])
            self.vspeed_unit_lbl.setText(s['speed_unit_mph'])
            self.gps_alt_unit = s['height_unit_ft']
            self.distance_unit = s['height_unit_ft']

        # Update map legend unit
        self._update_map_unit()
        # Force telemetry refresh to show converted values
        self._update_telemetry()

    def _update_map_unit(self):
        unit_txt = self.strings[self.lang]['speed_unit_ms'] if self.units == "metric" else self.strings[self.lang]['speed_unit_mph']
        self.map_widget.update_legend_unit(unit_txt)

    def apply_theme(self):
        if self.theme == "dark":
            dark_style = """
            QMainWindow { background-color: #1e1e2e; }
            QWidget { background-color: #1e1e2e; color: #e0e0e0; }
            QGroupBox { border: 1px solid #3a3a4a; border-radius: 5px; margin-top: 10px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; }
            QPushButton { background-color: #2d2d3a; border: 1px solid #5a5a70; border-radius: 4px; padding: 5px; color: #ffffff; }
            QPushButton:hover { background-color: #3d3d4e; }
            QSlider::groove:horizontal { height: 6px; background: #3a3a4a; border-radius: 3px; }
            QSlider::handle:horizontal { background: #00aaff; width: 14px; margin: -4px 0; border-radius: 7px; }
            QLabel { color: #e0e0e0; }
            QComboBox { background-color: #2d2d3a; border: 1px solid #5a5a70; border-radius: 3px; padding: 2px; }
            QCheckBox { color: #e0e0e0; }
            """
            QApplication.instance().setStyleSheet(dark_style)
        else:
            light_style = """
            QMainWindow { background-color: #f0f0f0; }
            QWidget { background-color: #f0f0f0; color: #202020; }
            QGroupBox { border: 1px solid #b0b0b0; border-radius: 5px; margin-top: 10px; font-weight: bold; background-color: #ffffff; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; }
            QPushButton { background-color: #e0e0e0; border: 1px solid #a0a0a0; border-radius: 4px; padding: 5px; color: #202020; }
            QPushButton:hover { background-color: #d0d0d0; }
            QSlider::groove:horizontal { height: 6px; background: #c0c0c0; border-radius: 3px; }
            QSlider::handle:horizontal { background: #0077aa; width: 14px; margin: -4px 0; border-radius: 7px; }
            QLabel { color: #202020; }
            QComboBox { background-color: #ffffff; border: 1px solid #a0a0a0; border-radius: 3px; padding: 2px; }
            QCheckBox { color: #202020; }
            """
            QApplication.instance().setStyleSheet(light_style)

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
            self, self.strings[self.lang]['open_video'], "", "Video Files (*.mp4 *.mov *.avi)")
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
            self.status_lbl.setText(self.strings[self.lang]['ffmpeg_error'])
            return

        self._prog = QProgressDialog(self.strings[self.lang]['extracting'], None, 0, 0, self)
        self._prog.setWindowTitle(self.strings[self.lang]['wait_title'])
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
        self._prog.setLabelText(self.strings[self.lang]['building_path'])
        self.subtitles      = subtitles
        self.telemetry_data = TelemetryParser.parse_all(subtitles)

        if self.telemetry_data:
            self._update_map_unit()
            self.map_widget.load_full_path(
                self.telemetry_data, self.speed_mode, self.smooth_value,
                self.strings[self.lang]['speed_unit_ms'] if self.units == "metric" else self.strings[self.lang]['speed_unit_mph'])
            self.sub_timer.start(100)

        self._prog.close()
        self.status_lbl.setText(f"✓ {len(self.telemetry_data)} telemetry points")

    # ── Map controls ───────────────────────────
    def _change_speed_mode(self):
        self.speed_mode = self.speed_combo.currentData()
        if self.telemetry_data:
            unit = self.strings[self.lang]['speed_unit_ms'] if self.units == "metric" else self.strings[self.lang]['speed_unit_mph']
            self.map_widget.load_full_path(
                self.telemetry_data, self.speed_mode, self.smooth_value, unit)

    def _change_smooth(self, val):
        self.smooth_value = val
        self.smooth_lbl.setText(str(val))
        if self.telemetry_data:
            self.map_widget.update_smooth(val)

    # ── Telemetry update with unit conversion ──
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

        # Apply unit conversions
        h  = found.get('height', 0) or 0
        hs = found.get('h_speed', 0) or 0
        vs = found.get('v_speed', 0) or 0
        gps_alt = found.get('gps_alt', None)
        dist = found.get('distance', None)

        if self.units == "imperial":
            h  = h * 3.28084          # meters to feet
            hs = hs * 2.23694         # m/s to mph
            vs = vs * 2.23694
            if gps_alt is not None:
                gps_alt = gps_alt * 3.28084
            if dist is not None:
                dist = dist * 3.28084

        self.lbl_height.setText(f"{h:.1f}")
        self.lbl_hspeed.setText(f"{hs:.2f}")
        self.lbl_vspeed.setText(f"{vs:.2f}")

        # Secondary grid (some fields don't need conversion)
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
            if key == 'gps_alt' and gps_alt is not None:
                v = gps_alt
                unit = " " + self.gps_alt_unit
            elif key == 'distance' and dist is not None:
                v = dist
                unit = " " + self.distance_unit
            if v is not None:
                lbl.setText(fmt[key](v) + unit)
            else:
                lbl.setText("--")

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
        s = self.strings[self.lang]
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            self.play_btn.setText("▶ " + s.get('play', 'Play'))
        else:
            self.media_player.play()
            self.play_btn.setText("⏸ " + s.get('pause', 'Pause'))

    def _stop(self):
        self.media_player.stop()
        self.play_btn.setText("▶ " + self.strings[self.lang].get('play', 'Play'))

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
