"""VOLT-Icon-Set: eigene Icons für Kanäle, Ränge, Produkte und Module.

Raster 24×24, Linien 2 px, eckige Enden (VOLT ist kantig). Jedes Icon hat
Hauptlinien in der Textfarbe (Ivory) und genau einen Akzent in Amber.
Rechteckige Formen bekommen oben rechts den VOLT-Schnitt.

Arten:  m  = Hauptlinie   mf = Hauptfläche
        a  = Akzentlinie  af = Akzentfläche
        d  = Warnlinie    df = Warnfläche (nur für „nicht schreiben“)
"""
import math

RING = ("M95.68 48.63L88.42 57.22L84.84 68.43L66.45 85.89L43.14 85.59L39.3 84.51L31.98 90.75L39.14 92.87L68.3 92.64L70.03 91.9L89.21 73.88L94.75 61.29L95.7 55.86Z"
        "M4.3 48.16L4.67 58.75L7.49 67.96L12.62 76.3L21.28 85.08L25.35 78.62L15.11 67.64L11.6 57.47Z"
        "M34.29 24.02L15.04 40.95L14.65 56.64L21.42 66.07L21.54 39.15Z"
        "M80.22 16L76.11 21.99L84.15 30.19L86.85 42.16L77.54 51.93L77.49 69.7L83.69 58.38L95.17 44.42L91.29 27.18L88.54 23.67Z"
        "M66.87 10.57L60.12 9.07L40.64 8.61L27.52 14.27L17.58 20.28L21.77 21.82L6.1 37.3L4.78 43.5L10.42 50.75L11.23 40.35L34.82 16.74L43.6 15.05L53.77 15.12L60.4 16.32Z")
BOLT = "M84.89 2L24.82 54.52L46.88 54.01L33.13 74.69L16.31 98L80.57 42.55L56.28 43.24Z"

SHIELD = "M12 2.5L20 5.5V11.5C20 16.2 16.6 19.6 12 21.5C7.4 19.6 4 16.2 4 11.5V5.5Z"
CUTBOX = "M3 4H17L21 8V20H3Z"          # Rechteck mit VOLT-Schnitt


def gear(cx=12, cy=12, r_out=9.8, r_in=7.3, teeth=8, w=0.2):
    pts = []
    for i in range(teeth):
        a = i * math.tau / teeth
        for da, r in ((-w * 1.35, r_in), (-w * 0.75, r_out), (w * 0.75, r_out), (w * 1.35, r_in)):
            pts.append((cx + r * math.cos(a + da), cy + r * math.sin(a + da)))
    return "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + "Z"


def star(cx=12, cy=12.4, R=9.6, r=4.2):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = R if i % 2 == 0 else r
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + "Z"


def qmark(x, y, s=1.0):
    """Fragezeichen: Bogen + Punkt, linke obere Ecke bei (x, y), ca. 4×7.5 groß."""
    p = (f"M{x:.2f} {y + 1.6 * s:.2f}C{x:.2f} {y - .4 * s:.2f} {x + 4 * s:.2f} {y - .4 * s:.2f} {x + 4 * s:.2f} {y + 1.8 * s:.2f}"
         f"C{x + 4 * s:.2f} {y + 3.4 * s:.2f} {x + 2 * s:.2f} {y + 3.4 * s:.2f} {x + 2 * s:.2f} {y + 5 * s:.2f}")
    return [("a", f'<path d="{p}"/>'), ("af", f'<rect x="{x + 1.1 * s:.2f}" y="{y + 6.2 * s:.2f}" width="{1.8 * s:.2f}" height="{1.8 * s:.2f}"/>')]


# Gruppe, Name, Anzeigename, Elemente
ICONS = {}


def icon(group, key, label, *els):
    ICONS[key] = {"group": group, "label": label, "els": list(els)}


# ---------- Marke ----------
icon("marke", "volt", "VOLT-Logo",
     ("mf", f'<path transform="translate(.6 .6) scale(.228)" d="{RING}"/>'),
     ("af", f'<path transform="translate(.6 .6) scale(.228)" d="{BOLT}"/>'))

# ---------- Kanäle ----------
icon("kanal", "regeln", "Regeln",
     ("m", '<path d="M5 3H15L19 7V21H5Z"/>'),
     ("a", '<path d="M8 8H12"/>'),
     ("m", '<path d="M8 12H16M8 16H16"/>'))
icon("kanal", "willkommen", "Willkommen",
     ("m", '<path d="M14 3H20V21H14"/>'),
     ("a", '<path d="M3 12H14M10 8L14 12L10 16"/>'))
icon("kanal", "verify", "Verifizieren",
     ("m", f'<path d="{SHIELD}"/>'),
     ("a", '<path d="M8 12L11 15L16.5 9"/>'))
icon("kanal", "stop", "Nicht schreiben",
     ("m", '<path d="M8 2.5H16L21.5 8V16L16 21.5H8L2.5 16V8Z"/>'),
     ("d", '<path d="M7.5 12H16.5" stroke-width="2.6"/>'))
icon("kanal", "ankuendigung", "Ankündigungen",
     ("m", '<path d="M3 9.5H7L16 4.5V19.5L7 14.5H3Z"/>'),
     ("m", '<path d="M7 14.5L9 20.5H11.5"/>'),
     ("a", '<path d="M19.5 9A4.2 4.2 0 0 1 19.5 15"/>'))
icon("kanal", "status", "Server-Status",
     ("m", f'<path d="{CUTBOX}"/>'),
     ("a", '<path d="M6 13.5H8.5L10.5 9.5L13 17L15 12.5H18"/>'))
icon("kanal", "uptime", "Uptime",
     ("mf", '<path d="M3 16h3.2v5H3zM8.3 12h3.2v9H8.3zM13.6 8h3.2v13h-3.2z"/>'),
     ("af", '<path d="M18.9 3h3.2v18h-3.2z"/>'))
icon("kanal", "website", "Website",
     ("m", '<circle cx="12" cy="12" r="9"/>'),
     ("m", '<path d="M12 3C8.2 7.5 8.2 16.5 12 21C15.8 16.5 15.8 7.5 12 3Z"/>'),
     ("a", '<path d="M3.5 12H20.5"/>'))
icon("kanal", "bewertung", "Bewertungen",
     ("af", f'<path d="{star()}"/>'))
icon("kanal", "faq", "FAQ",
     ("m", '<path d="M3 3.5H17L21 7.5V16H10.5L6 20.5V16H3Z"/>'),
     *qmark(10, 6.3, .95))
icon("kanal", "portfolio", "Portfolio",
     ("m", '<path d="M3 5H21V19H3Z"/>'),
     ("m", '<path d="M3 17L9 11L13 15L16 12L21 17"/>'),
     ("af", '<circle cx="16.5" cy="8.6" r="1.7"/>'))
icon("kanal", "produkte", "Produkte",
     ("af", '<path d="M12 2.5L20.5 7L12 11.5L3.5 7Z"/>'),
     ("m", '<path d="M12 2.5L20.5 7V17L12 21.5L3.5 17V7Z"/>'),
     ("m", '<path d="M3.5 7L12 11.5L20.5 7M12 11.5V21.5"/>'))
icon("kanal", "bestellen", "Bestellen",
     ("m", '<path d="M2 4H5L7.5 15H18.5L20.5 7.5H6"/>'),
     ("af", '<circle cx="9" cy="19.2" r="1.8"/><circle cx="17" cy="19.2" r="1.8"/>'))
icon("kanal", "ticket", "Tickets",
     ("m", '<path d="M3 6H21V10A2 2 0 0 0 21 14V18H3V14A2 2 0 0 0 3 10Z"/>'),
     ("af", '<path d="M8.6 6h2.2v12H8.6z"/>'))
icon("kanal", "team", "Team",
     ("a", '<circle cx="17" cy="7.5" r="2.6"/>'),
     ("a", '<path d="M17.5 12.6C19.9 12.9 21.5 14.8 21.5 18"/>'),
     ("m", '<circle cx="9" cy="8" r="3.4"/>'),
     ("m", '<path d="M2.5 20C2.5 15.6 5.2 13.6 9 13.6C12.8 13.6 15.5 15.6 15.5 20"/>'))
icon("kanal", "aufgaben", "Aufgaben",
     ("a", '<path d="M3 6.5L5 8.5L8.5 4.5M3 12L5 14L8.5 10"/>'),
     ("m", '<path d="M11.5 6.5H21M11.5 12H21M11.5 18.5H21"/>'),
     ("m", '<path d="M3.5 16.5H7.5V20.5H3.5Z"/>'))
icon("kanal", "logs", "Logs",
     ("m", f'<path d="{CUTBOX}"/>'),
     ("a", '<path d="M6.5 10L9.5 13L6.5 16"/>'),
     ("m", '<path d="M11.5 16.5H17"/>'))
icon("kanal", "archiv", "Archiv",
     ("m", '<path d="M3 4H21V8.5H3Z"/>'),
     ("m", '<path d="M4.5 8.5V20H19.5V8.5"/>'),
     ("a", '<path d="M9.5 12.5H14.5"/>'))
icon("kanal", "schutz", "Schutz",
     ("m", f'<path d="{SHIELD}"/>'),
     ("af", '<path d="M13.4 5.6L7.9 13.2H11.3L10.1 18.4L16.1 10.6H12.6Z"/>'))
icon("kanal", "schloss", "Admin",
     ("m", '<path d="M4.5 10H19.5V21H4.5Z"/>'),
     ("m", '<path d="M8 10V7A4 4 0 0 1 16 7V10"/>'),
     ("af", '<path d="M11 13.5h2v4h-2z"/>'))
icon("kanal", "tuer", "Beitritte",
     ("m", '<path d="M4 3H14V21H4Z"/>'),
     ("af", '<circle cx="11" cy="12.5" r="1.2"/>'),
     ("a", '<path d="M15.5 12H21.5M19 9.5L21.5 12L19 14.5"/>'))
icon("kanal", "chat", "Chat",
     ("m", '<path d="M3 4H17L21 8V16H10L5.5 20.5V16H3Z"/>'),
     ("a", '<path d="M7 10H16"/>'),
     ("m", '<path d="M7 13H13"/>'))

# ---------- Ränge ----------
icon("rang", "owner", "Owner",
     ("af", '<path d="M3 18L4 6.5L9 11.5L12 4.5L15 11.5L20 6.5L21 18Z"/>'),
     ("m", '<path d="M4 21H20"/>'))
icon("rang", "admin", "Admin",
     ("a", '<path d="M4.5 9L12 3.5L19.5 9"/>'),
     ("m", '<path d="M4.5 14.5L12 9L19.5 14.5M4.5 20L12 14.5L19.5 20"/>'))
icon("rang", "support", "Support",
     ("m", '<path d="M4.5 14V12A7.5 7.5 0 0 1 19.5 12V14"/>'),
     ("mf", '<path d="M3 13h4v6.5H3zM17 13h4v6.5h-4z"/>'),
     ("a", '<path d="M19 19.5C19 21 17.8 21.5 15.5 21.5H13"/>'))
icon("rang", "kunde", "Kunde",
     ("m", '<path d="M3 7.5H21V20H3Z"/>'),
     ("m", '<path d="M9 7.5V4.5H15V7.5"/>'),
     ("a", '<path d="M3 12.5H21"/>'),
     ("af", '<path d="M10.5 11h3v3h-3z"/>'))
icon("rang", "user", "User",
     ("a", '<circle cx="12" cy="8" r="4"/>'),
     ("m", '<path d="M4 21C4 15.8 7.4 13.8 12 13.8C16.6 13.8 20 15.8 20 21"/>'))
icon("rang", "bot", "Bot",
     ("m", '<path d="M4.5 8H19.5V20H4.5Z"/>'),
     ("m", '<path d="M12 8V4.8M2 12V16M22 12V16"/>'),
     ("af", '<circle cx="12" cy="3.3" r="1.5"/>'),
     ("af", '<path d="M8 12.2h2.6v2.6H8zM13.4 12.2H16v2.6h-2.6z"/>'))
icon("rang", "unverifiziert", "Unverifiziert",
     ("m", '<circle cx="9.5" cy="8" r="3.6"/>'),
     ("m", '<path d="M2.5 21C2.5 16.3 5.4 14.3 9.5 14.3C13.6 14.3 16.5 16.3 16.5 21"/>'),
     *qmark(17.2, 3.2, .9))

# ---------- Produkte ----------
icon("produkt", "familie", "Familien-Dashboard",
     ("m", '<path d="M3 11L12 3.5L21 11V21H3Z"/>'),
     ("af", '<path d="M10 14.5h4V21h-4z"/>'))
icon("produkt", "fussball", "Fussball-Manager",
     ("m", '<circle cx="12" cy="12" r="9"/>'),
     ("af", '<path d="M12 8.2L15.6 10.8L14.2 15H9.8L8.4 10.8Z"/>'),
     ("m", '<path d="M12 8.2V3.2M15.6 10.8L20.4 9.3M14.2 15L17.2 19.2M9.8 15L6.8 19.2M8.4 10.8L3.6 9.3"/>'))
icon("produkt", "routen", "Routen Manager",
     ("m", '<path d="M5.5 17C5.5 12 18.5 15.5 18.5 10"/>'),
     ("af", '<circle cx="5.5" cy="19" r="2.4"/>'),
     ("m", '<path d="M18.5 2.5A3.3 3.3 0 0 1 21.8 5.8C21.8 8.3 18.5 11.5 18.5 11.5C18.5 11.5 15.2 8.3 15.2 5.8A3.3 3.3 0 0 1 18.5 2.5Z"/>'))

# ---------- Module (VOLT Bot) ----------
icon("modul", "allgemein", "Allgemein",
     ("m", f'<path d="{gear()}"/>'),
     ("af", '<circle cx="12" cy="12" r="2.8"/>'))
icon("modul", "rollen", "Rollen",
     ("m", '<path d="M3 3.5H11.5L20.5 12.5L12.5 20.5L3.5 11.5Z"/>'),
     ("af", '<circle cx="7.6" cy="7.6" r="1.7"/>'))
icon("modul", "moderation", "Moderation",
     ("m", '<path d="M7.2 7.7L11.7 3.2L17.7 9.2L13.2 13.7Z"/>'),
     ("m", '<path d="M9.8 11.3L3.5 17.6" stroke-width="2.6"/>'),
     ("a", '<path d="M11 21H21"/>'))
icon("modul", "automod", "AutoMod",
     ("m", f'<path d="{SHIELD}"/>'),
     ("a", '<path d="M8 9H16M9.5 12.5H14.5M11 16H13"/>'))
icon("modul", "level", "Level-System",
     ("mf", '<path d="M3.5 17h3v4h-3zM9.5 14h3v7h-3zM15.5 11h3v10h-3z"/>'),
     ("a", '<path d="M3 11.5L8.5 6.5L11.5 9.5L19.5 2.5M15 2.5H19.5V7"/>'))
icon("modul", "aufstellung", "Aufstellung",
     ("m", '<path d="M5 4.5H19V21H5Z"/>'),
     ("mf", '<path d="M8.5 2.5h7v4h-7z"/>'),
     ("a", '<path d="M8 11.5L10.2 13.7L14 9.8"/>'),
     ("m", '<path d="M8 17.5H16"/>'))
icon("modul", "streams", "Streams",
     ("m", '<path d="M2.5 4.5H21.5V16.5H2.5Z"/>'),
     ("m", '<path d="M12 16.5V20.5M8 20.5H16"/>'),
     ("af", '<path d="M10 7.5L15.5 10.5L10 13.5Z"/>'))
icon("modul", "social", "Social Media",
     ("m", '<path d="M7 2.5H17V21.5H7Z"/>'),
     ("m", '<path d="M11 18.5H13"/>'),
     ("af", '<path d="M12 14.2C9 11.8 8.2 10.6 8.2 9.4C8.2 8.1 9.2 7.2 10.3 7.2C11.1 7.2 11.7 7.6 12 8.2C12.3 7.6 12.9 7.2 13.7 7.2C14.8 7.2 15.8 8.1 15.8 9.4C15.8 10.6 15 11.8 12 14.2Z"/>'))
icon("modul", "umfragen", "Umfragen",
     ("m", '<path d="M4 5.5H13M4 18.5H10" stroke-width="3"/>'),
     ("a", '<path d="M4 12H20" stroke-width="3"/>'))
icon("modul", "giveaways", "Giveaways",
     ("m", '<path d="M4.5 11H19.5V21H4.5Z"/>'),
     ("m", '<path d="M3 7H21V11H3Z"/>'),
     ("a", '<path d="M12 7V21M12 7C10.2 3 6.2 3.8 8.4 7M12 7C13.8 3 17.8 3.8 15.6 7"/>'))
icon("modul", "geburtstage", "Geburtstage",
     ("m", '<path d="M4 12.5H20V21H4Z"/>'),
     ("m", '<path d="M4 16.5H20M8 12.5V9.5M12 12.5V9.5M16 12.5V9.5"/>'),
     ("af", '<ellipse cx="8" cy="6.5" rx="1.1" ry="1.7"/><ellipse cx="12" cy="6.5" rx="1.1" ry="1.7"/><ellipse cx="16" cy="6.5" rx="1.1" ry="1.7"/>'))
icon("modul", "tempvoice", "Temp-Voice",
     ("m", '<path d="M3 9H7L12 5V19L7 15H3Z"/>'),
     ("a", '<path d="M18 8.5V15.5M14.5 12H21.5"/>'))
icon("modul", "statistik", "Statistik",
     ("m", '<path d="M3 3V21H21"/>'),
     ("a", '<path d="M6.5 16L10.5 11L14 14L20 6.5"/>'))
icon("modul", "embeds", "Embed-Builder",
     ("af", '<path d="M3 4h2.4v16H3z"/>'),
     ("m", '<path d="M5.4 4H21V20H5.4"/>'),
     ("m", '<path d="M8.5 9H17M8.5 12.5H18M8.5 16H14"/>'))
icon("modul", "befehle", "Eigene Befehle",
     ("m", f'<path d="{CUTBOX}"/>'),
     ("a", '<path d="M14 7.5L10 17" stroke-width="2.4"/>'))
icon("modul", "erinnerungen", "Erinnerungen",
     ("m", '<circle cx="12" cy="13" r="7.8"/>'),
     ("m", '<path d="M3 6.5L6.5 3M21 6.5L17.5 3M6.5 21L8 19.3M17.5 21L16 19.3"/>'),
     ("a", '<path d="M12 8.5V13L15.2 15.2"/>'))
icon("modul", "statkanaele", "Statistik-Kanäle",
     ("m", '<path d="M9.5 3L7 21M16.5 3L14 21M4 8.5H19M3 15.5H18"/>'),
     ("af", '<circle cx="20.2" cy="4.2" r="2.2"/>'))

icon("modul", "autoban", "Autoban-Falle",
     ("m", '<path d="M8 2.5H16L21.5 8V16L16 21.5H8L2.5 16V8Z"/>'),
     ("af", '<path d="M13.6 5.4L7.6 13.4H11.3L10.1 18.6L16.5 10.4H12.7Z"/>'))

# ---------- Allgemeine Symbole (Knöpfe, Status, Listen) ----------
HEART = ("M12 20.5C5 15.5 2.5 12.2 2.5 8.7C2.5 6 4.6 3.8 7.2 3.8C9.2 3.8 11 5 12 6.8"
         "C13 5 14.8 3.8 16.8 3.8C19.4 3.8 21.5 6 21.5 8.7C21.5 12.2 19 15.5 12 20.5Z")
icon("ui", "plus", "Hinzufügen",
     ("m", '<path d="M12 3.5V20.5"/>'),
     ("a", '<path d="M3.5 12H20.5"/>'))
icon("ui", "check", "Erledigt",
     ("m", f'<path d="{CUTBOX}"/>'),
     ("a", '<path d="M7 12.5L10.5 16L17 8.5" stroke-width="2.4"/>'))
icon("ui", "kreuz", "Fehler / Abgelehnt",
     ("m", f'<path d="{CUTBOX}"/>'),
     ("d", '<path d="M8 8.5L16 16.5M16 8.5L8 16.5" stroke-width="2.4"/>'))
icon("ui", "warnung", "Achtung",
     ("m", '<path d="M12 3L22 20.5H2Z"/>'),
     ("a", '<path d="M12 9V14"/>'),
     ("af", '<path d="M11 16.2h2v2h-2z"/>'))
icon("ui", "uhr", "Zeit",
     ("m", '<circle cx="12" cy="12" r="9"/>'),
     ("a", '<path d="M12 6.5V12L15.8 14.6"/>'))
icon("ui", "kalender", "Termine",
     ("m", '<path d="M3 5H21V21H3Z"/>'),
     ("m", '<path d="M3 10H21M8 2.5V7M16 2.5V7"/>'),
     ("af", '<path d="M13.5 13.5h4v4h-4z"/>'))
icon("ui", "kasse", "Kasse / Geld",
     ("m", '<path d="M2.5 6H18L21.5 9.5V18H2.5Z"/>'),
     ("a", '<circle cx="12" cy="12" r="3"/>'),
     ("m", '<path d="M6 9.5V14.5"/>'))
icon("ui", "stift", "Bearbeiten",
     ("m", '<path d="M4 20L4.8 15.8L15.4 5.2L18.8 8.6L8.2 19.2Z"/>'),
     ("m", '<path d="M13.2 7.4L16.6 10.8"/>'),
     ("a", '<path d="M13 21H21"/>'))
icon("ui", "loeschen", "Löschen",
     ("m", '<path d="M5.5 7H18.5L17.3 21H6.7Z"/>'),
     ("m", '<path d="M3 7H21M9 7V3.5H15V7"/>'),
     ("a", '<path d="M10 11V17M14 11V17"/>'))
icon("ui", "export", "Senden / Export",
     ("m", '<path d="M4 13.5V20.5H20V13.5"/>'),
     ("a", '<path d="M12 15.5V3.5M7.5 8L12 3.5L16.5 8"/>'))
icon("ui", "import", "Empfangen / Import",
     ("m", '<path d="M4 13.5V20.5H20V13.5"/>'),
     ("a", '<path d="M12 3.5V15.5M7.5 11L12 15.5L16.5 11"/>'))
icon("ui", "suche", "Suche",
     ("m", '<circle cx="10.5" cy="10.5" r="6.5"/>'),
     ("a", '<path d="M15.3 15.3L21 21" stroke-width="2.6"/>'))
icon("ui", "schluessel", "Zugang",
     ("m", '<circle cx="8" cy="15.5" r="4.5"/>'),
     ("a", '<path d="M11.2 12.3L20 3.5M16.6 6.9L19.2 9.5M14 9.5L16.2 11.7"/>'))
icon("ui", "handy", "Handy",
     ("m", '<path d="M6.5 2.5H17.5V21.5H6.5Z"/>'),
     ("a", '<path d="M10.5 18.3H13.5"/>'))
icon("ui", "pokal", "Pokal",
     ("m", '<path d="M7 3.5H17V9.5A5 5 0 0 1 7 9.5Z"/>'),
     ("m", '<path d="M7 5.5H3.5V7.5A3.5 3.5 0 0 0 7.3 11M17 5.5H20.5V7.5A3.5 3.5 0 0 1 16.7 11M12 14.5V18"/>'),
     ("a", '<path d="M7.5 20.5H16.5"/>'))
icon("ui", "kamera", "Foto",
     ("m", '<path d="M2.5 7H7.5L9.5 4.5H14.5L16.5 7H21.5V19.5H2.5Z"/>'),
     ("a", '<circle cx="12" cy="13" r="3.5"/>'))
icon("ui", "live", "Live / Online",
     ("af", '<circle cx="12" cy="12" r="2.8"/>'),
     ("m", '<path d="M7.6 7.6A6.2 6.2 0 0 0 7.6 16.4M16.4 7.6A6.2 6.2 0 0 1 16.4 16.4'
            'M4.4 4.4A10.7 10.7 0 0 0 4.4 19.6M19.6 4.4A10.7 10.7 0 0 1 19.6 19.6"/>'))
icon("ui", "sync", "Aktualisieren",
     ("m", '<path d="M19.6 9.5A8 8 0 0 0 5.2 7.2M4.4 14.5A8 8 0 0 0 18.8 16.8"/>'),
     ("a", '<path d="M5 3V7.5H9.5M19 21V16.5H14.5"/>'))
icon("ui", "spende", "Spenden",
     ("m", f'<path d="{HEART}"/>'),
     ("af", '<path d="M13.2 7.6L9 12.8H11.9L10.8 16.8L15.2 11.3H12.3Z"/>'))
icon("ui", "link", "Öffnen",
     ("m", '<path d="M12 4H4V20H20V12"/>'),
     ("a", '<path d="M14.5 3.5H20.5V9.5M20.5 3.5L11 13"/>'))
icon("ui", "sprache", "Sprachen",
     ("m", '<path d="M2.5 4H13.5V14H8L4.5 17.5V14H2.5Z"/>'),
     ("a", '<path d="M15 9H21.5V18H19.5V21L16.5 18H11V16.5"/>'))

# Welche Icons ein Discord-Server zuerst bekommt (Emoji-Plätze sind begrenzt)
DISCORD_ORDER = (["volt"] + [k for k, v in ICONS.items() if v["group"] == "rang"]
                 + [k for k, v in ICONS.items() if v["group"] == "kanal"]
                 + [k for k, v in ICONS.items() if v["group"] == "produkt"]
                 + [k for k, v in ICONS.items() if v["group"] == "modul"]
                 + [k for k, v in ICONS.items() if v["group"] == "ui"])

COLORS = {"main": "#F2EFE8", "accent": "#FFB83F", "danger": "#FF4D5E"}


def _style(kind, sw):
    if kind == "m":
        return f'fill="none" stroke="currentColor" stroke-width="{sw}" stroke-linejoin="miter" stroke-linecap="butt"'
    if kind == "mf":
        return 'fill="currentColor" stroke="none"'
    if kind in ("a", "d"):
        var = "--vi-accent" if kind == "a" else "--vi-danger"
        col = COLORS["accent"] if kind == "a" else COLORS["danger"]
        return (f'fill="none" stroke="{col}" style="stroke:var({var},{col})" stroke-width="{sw}" '
                f'stroke-linejoin="miter" stroke-linecap="butt"')
    var = "--vi-accent" if kind == "af" else "--vi-danger"
    col = COLORS["accent"] if kind == "af" else COLORS["danger"]
    return f'fill="{col}" style="fill:var({var},{col})" stroke="none"'


def body(key, sw=2.0):
    """SVG-Inhalt eines Icons (ohne <svg>-Hülle)."""
    out = []
    for kind, el in ICONS[key]["els"]:
        st = _style(kind, sw)
        # eigene stroke-width im Element hat Vorrang (dann aber mit Faktor)
        if 'stroke-width="' in el:
            import re
            w = float(re.search(r'stroke-width="([\d.]+)"', el).group(1))
            el = re.sub(r'stroke-width="[\d.]+"', "", el)
            st = re.sub(r'stroke-width="[\d.]+"', f'stroke-width="{w * sw / 2:.2f}"', st)
        out.append(f'<g {st}>{el}</g>')
    return "".join(out)
