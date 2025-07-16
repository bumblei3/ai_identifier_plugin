# Konstanten und Listen für AI Music Identifier Plugin

VALID_GENRES = [
    "Pop", "Rock", "Hip-Hop", "Jazz", "Classical", "Electronic", "Folk", "Blues", "Reggae", "Country", "Metal", "Soul", "Funk", "R&B", "Punk", "Disco", "Techno", "House", "Trance", "Ambient", "Dubstep", "Drum and Bass", "Gospel", "Latin", "Ska", "World", "K-Pop", "J-Pop", "Soundtrack", "Children's", "Comedy", "Spoken Word"
]
VALID_MOODS = [
    "fröhlich", "melancholisch", "energetisch", "ruhig", "aggressiv", "romantisch", "düster", "entspannt", "traurig", "heiter", "episch", "nostalgisch", "spirituell", "verspielt", "dramatisch", "träumerisch", "aufregend", "friedlich", "leidenschaftlich"
]
GENRE_HIERARCHY = {
    "Rock": {
        "Alternative Rock": ["Grunge", "Indie Rock", "Post-Rock", "Shoegaze"],
        "Classic Rock": ["Hard Rock", "Progressive Rock", "Psychedelic Rock"],
        "Metal": ["Heavy Metal", "Death Metal", "Black Metal", "Thrash Metal", "Power Metal"],
        "Punk": ["Punk Rock", "Hardcore Punk", "Pop Punk", "Post-Punk"],
        "Folk Rock": ["Country Rock", "Celtic Rock"]
    },
    "Electronic": {
        "Techno": ["Minimal Techno", "Detroit Techno", "Acid Techno"],
        "House": ["Deep House", "Progressive House", "Tech House", "Acid House"],
        "Trance": ["Progressive Trance", "Uplifting Trance", "Goa Trance"],
        "Ambient": ["Dark Ambient", "Space Ambient", "Drone"],
        "Drum and Bass": ["Liquid DnB", "Neurofunk", "Jungle"],
        "Dubstep": ["Brostep", "Melodic Dubstep", "UK Dubstep"]
    },
    "Pop": {
        "Synthpop": ["Electropop", "Futurepop"],
        "Indie Pop": ["Dream Pop", "Chamber Pop"],
        "K-Pop": ["K-Pop", "J-Pop"],
        "Pop Rock": ["Power Pop", "Soft Rock"]
    },
    "Hip-Hop": {
        "Rap": ["Gangsta Rap", "Conscious Rap", "Trap", "Drill"],
        "R&B": ["Contemporary R&B", "Neo-Soul", "Alternative R&B"]
    },
    "Jazz": {
        "Smooth Jazz": ["Fusion", "Acid Jazz"],
        "Traditional Jazz": ["Dixieland", "Swing", "Bebop"],
        "Modern Jazz": ["Free Jazz", "Avant-Garde Jazz"]
    },
    "Classical": {
        "Orchestral": ["Symphony", "Concerto", "Opera"],
        "Chamber Music": ["String Quartet", "Piano Trio"],
        "Contemporary Classical": ["Minimalism", "Serialism"]
    }
}

# Globale Thread-Limits und weitere technische Konstanten
_MAX_KI_THREADS = 2
_ACOUSTID_MAX_PARALLEL = 2
_CHUNK_SIZE = 20
_DEBUG_LOGGING_KEY = "aiid_debug_logging" 