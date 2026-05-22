from flask import Flask, render_template_string
import sqlite3

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Гид по Анапе – карта</title>
    <meta charset="utf-8" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
</head>
<body>
    <div id="map" style="height: 100vh;"></div>
    <script>
        var map = L.map('map').setView([44.895, 37.31], 12);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap'
        }).addTo(map);
        var markers = {{ markers | safe }};
        markers.forEach(function(m) {
            L.marker([m.lat, m.lon]).addTo(map)
             .bindPopup("<b>" + m.name + "</b><br>" + m.desc + "<br><i>" + m.route + "</i>");
        });
    </script>
</body>
</html>
"""

def get_all_locations():
    # Импортируем маршруты из main.py (или скопируем структуру)
    ROUTES = {
        "kids": { "name": "Анапа с детьми", "locations": [ {"name": "Парк 30-летия Победы", "lat": 44.8941, "lon": 37.3135, "description": "Аттракционы"}, {"name": "Дельфинарий", "lat": 44.8790, "lon": 37.2935, "description": "Шоу"}, {"name": "Аквапарк", "lat": 44.8840, "lon": 37.2975, "description": "Горки"}, {"name": "Белая шляпа", "lat": 44.8921, "lon": 37.3150, "description": "Фото"}, {"name": "Центральный пляж", "lat": 44.8905, "lon": 37.3127, "description": "Песок"}] },
        "adult": { "name": "Анапа взрослая", "locations": [ {"name": "Русские ворота", "lat": 44.8955, "lon": 37.3198, "description": "Крепость"}, {"name": "Музей", "lat": 44.8961, "lon": 37.3167, "description": "История"}, {"name": "Беседка", "lat": 44.8917, "lon": 37.3082, "description": "Вид"}, {"name": "Винодельня", "lat": 44.870, "lon": 37.350, "description": "Вино"}, {"name": "Маяк", "lat": 44.8869, "lon": 37.2990, "description": "Маяк"}] },
        "car": { "name": "На машине", "locations": [ {"name": "Кипарисовое озеро", "lat": 44.910, "lon": 37.350, "description": "Озеро"}, {"name": "Сукко", "lat": 44.790, "lon": 37.370, "description": "Долина"}, {"name": "Утриш", "lat": 44.750, "lon": 37.380, "description": "Заповедник"}, {"name": "Варваровка", "lat": 44.840, "lon": 37.370, "description": "Виноградники"}, {"name": "Благовещенская", "lat": 44.960, "lon": 37.280, "description": "Коса"}] },
        "walk": { "name": "Пешеходная", "locations": [ {"name": "Русские ворота", "lat": 44.8955, "lon": 37.3198, "description": "Старт"}, {"name": "Храм Онуфрия", "lat": 44.8977, "lon": 37.3174, "description": "Храм"}, {"name": "Сквер Гудовича", "lat": 44.8959, "lon": 37.3148, "description": "Сквер"}, {"name": "Фонтан", "lat": 44.8936, "lon": 37.3170, "description": "Набережная"}, {"name": "Отдыхающий", "lat": 44.8933, "lon": 37.3162, "description": "Скульптура"}] }
    }
    markers = []
    for route_id, route in ROUTES.items():
        for loc in route["locations"]:
            markers.append({
                "lat": loc["lat"],
                "lon": loc["lon"],
                "name": loc["name"],
                "desc": loc.get("description", ""),
                "route": route["name"]
            })
    return markers

@app.route("/")
def index():
    markers = get_all_locations()
    return render_template_string(HTML_TEMPLATE, markers=markers)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
