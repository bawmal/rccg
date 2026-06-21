#!/usr/bin/env python3
"""
RCCG COM Bible-lite — Local Web Server
Serves the web UI + WebSocket for live transcription, manual lookup, and quote search.
Run:  python3 serve.py
Open:  http://localhost:8080
"""
import asyncio, json, os, re, signal, sqlite3, subprocess, sys, threading
from http.server import HTTPServer, SimpleHTTPRequestHandler

try:
    import websockets
except ImportError:
    print("Installing websockets...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets", "--quiet"])
    import websockets

DB_PATH   = os.path.join(os.path.dirname(__file__), "data", "rhema.db")
MODEL     = os.path.join(os.path.dirname(__file__), "models", "ggml-base.en.bin")
WEB_DIR   = os.path.join(os.path.dirname(__file__), "web-ui")
HTTP_PORT = 8080
WS_PORT   = 8765

active_translation = "KJV"
broadcast_clients  = set()

# ─── SQLite helpers ──────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_translations(conn):
    try:
        rows = conn.execute(
            "SELECT id, abbreviation, title FROM translations WHERE is_downloaded=1 ORDER BY id"
        ).fetchall()
        return [{"abbr": r["abbreviation"], "title": r["title"]} for r in rows]
    except Exception as e:
        print(f"get_translations error: {e}")
        return [{"abbr": "KJV", "title": "King James Version"}]

def get_translation_id(conn, abbr):
    row = conn.execute("SELECT id FROM translations WHERE abbreviation=?", (abbr,)).fetchone()
    return row["id"] if row else 1

def _book_name_variants(book):
    """Generate possible DB name variants for a canonical book name."""
    variants = [book]
    # "1 Samuel" -> "I Samuel", "2 Kings" -> "II Kings", "3 John" -> "III John"
    if book.startswith("1 "):
        variants.append("I " + book[2:])
    elif book.startswith("2 "):
        variants.append("II " + book[2:])
    elif book.startswith("3 "):
        variants.append("III " + book[2:])
    # "Revelation" -> "Revelation of John"
    if book == "Revelation":
        variants.append("Revelation of John")
    return variants

def lookup_verse(conn, book, chapter, verse, translation):
    tid = get_translation_id(conn, translation)
    variants = _book_name_variants(book)
    try:
        for bname in variants:
            row = conn.execute(
                "SELECT * FROM verses WHERE book_name=? AND chapter=? AND verse=? AND translation_id=? LIMIT 1",
                (bname, chapter, verse, tid)
            ).fetchone()
            if row:
                return {
                    "book_name": row["book_name"],
                    "chapter":   row["chapter"],
                    "verse":     row["verse"],
                    "text":      row["text"],
                    "reference": f"{row['book_name']} {row['chapter']}:{row['verse']}",
                    "translation": translation,
                }
        # Fallback: case-insensitive LIKE match
        for bname in variants:
            row = conn.execute(
                "SELECT * FROM verses WHERE LOWER(book_name) LIKE LOWER(?) AND chapter=? AND verse=? AND translation_id=? LIMIT 1",
                (bname + "%", chapter, verse, tid)
            ).fetchone()
            if row:
                return {
                    "book_name": row["book_name"],
                    "chapter":   row["chapter"],
                    "verse":     row["verse"],
                    "text":      row["text"],
                    "reference": f"{row['book_name']} {row['chapter']}:{row['verse']}",
                    "translation": translation,
                }
    except Exception as e:
        print(f"lookup error: {e}")
    return None

def search_quote(conn, text, translation, limit=5):
    """Simple word-overlap search."""
    words = set(re.findall(r'\w+', text.lower()))
    if not words:
        return []
    # Build WHERE with LIKE for each significant word (skip tiny words)
    sig = [w for w in words if len(w) > 2][:6]
    if not sig:
        sig = list(words)[:3]
    tid = get_translation_id(conn, translation)
    conditions = " AND ".join([f"LOWER(text) LIKE ?" for _ in sig])
    params = [f"%{w}%" for w in sig]
    params.append(tid)
    try:
        rows = conn.execute(
            f"SELECT * FROM verses WHERE {conditions} AND translation_id=? LIMIT ?",
            params + [limit * 3]
        ).fetchall()
    except Exception as e:
        print(f"search error: {e}")
        return []
    # Score by word overlap
    results = []
    for row in rows:
        txt_words = set(re.findall(r'\w+', row["text"].lower()))
        overlap = len(words & txt_words)
        score = overlap / max(len(words), 1)
        results.append({
            "book_name": row["book_name"],
            "chapter":   row["chapter"],
            "verse":     row["verse"],
            "text":      row["text"],
            "reference": f"{row['book_name']} {row['chapter']}:{row['verse']}",
            "translation": translation,
            "score":     round(score, 3),
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]

# ─── HTTP server ─────────────────────────────────────────────────────────────

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB_DIR, **kw)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.path = "/index-web.html"
        super().do_GET()

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, fmt, *a):
        pass  # silence HTTP logs

def run_http():
    srv = HTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    srv.serve_forever()

# ─── WebSocket server ────────────────────────────────────────────────────────

async def broadcast(msg_str):
    global broadcast_clients
    gone = set()
    for ws in broadcast_clients:
        try:
            await ws.send(msg_str)
        except:
            gone.add(ws)
    broadcast_clients -= gone

async def handle_client(ws):
    global active_translation, broadcast_clients
    broadcast_clients.add(ws)
    conn = get_db()
    print(f"[WS] client connected ({len(broadcast_clients)} total)")
    try:
        # Send init
        trans = get_translations(conn)
        await ws.send(json.dumps({
            "type": "init",
            "translation": active_translation,
            "translations": trans,
        }))

        async for raw in ws:
            try:
                msg = json.loads(raw)
            except:
                continue
            action = msg.get("action", "")

            if action == "set_translation":
                t = msg.get("translation", "").upper()
                if t:
                    active_translation = t
                    await broadcast(json.dumps({"type": "translation_change", "translation": t}))

            elif action in ("lookup", "select_candidate"):
                raw_book = msg.get("book_name", "")
                ch   = msg.get("chapter")
                vs   = msg.get("verse")
                if raw_book and ch is not None and vs is not None:
                    book = resolve_book_name(raw_book) or raw_book
                    v = lookup_verse(conn, book, int(ch), int(vs), active_translation)
                    if v:
                        v["type"]       = "verse_detected"
                        v["source"]     = "manual"
                        v["confidence"] = 1.0
                        await broadcast(json.dumps(v))
                    else:
                        print(f"[WS] verse not found: {book} {ch}:{vs}")

            elif action == "search_quote":
                text  = msg.get("text", "")
                limit = msg.get("limit", 5)
                results = search_quote(conn, text, active_translation, limit)
                if results:
                    top = results[0]
                    if top["score"] >= 0.6:
                        top["type"]       = "verse_detected"
                        top["source"]     = "quote"
                        top["confidence"] = top["score"]
                        await broadcast(json.dumps(top))
                    else:
                        await broadcast(json.dumps({"type": "candidates", "candidates": results}))

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[WS] error: {e}")
    finally:
        broadcast_clients.discard(ws)
        conn.close()
        print(f"[WS] client disconnected ({len(broadcast_clients)} total)")

# ─── Whisper transcription ───────────────────────────────────────────────────

# Canonical book names in order
CANONICAL_BOOKS = [
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy",
    "Joshua", "Judges", "Ruth", "1 Samuel", "2 Samuel",
    "1 Kings", "2 Kings", "1 Chronicles", "2 Chronicles",
    "Ezra", "Nehemiah", "Esther", "Job", "Psalms", "Proverbs",
    "Ecclesiastes", "Song of Solomon", "Isaiah", "Jeremiah",
    "Lamentations", "Ezekiel", "Daniel", "Hosea", "Joel", "Amos",
    "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah",
    "Haggai", "Zechariah", "Malachi",
    "Matthew", "Mark", "Luke", "John", "Acts", "Romans",
    "1 Corinthians", "2 Corinthians", "Galatians", "Ephesians",
    "Philippians", "Colossians", "1 Thessalonians", "2 Thessalonians",
    "1 Timothy", "2 Timothy", "Titus", "Philemon", "Hebrews",
    "James", "1 Peter", "2 Peter", "1 John", "2 John", "3 John",
    "Jude", "Revelation",
]

BOOK_ALIASES = {
    # Full names (lowercase)
    "genesis": "Genesis", "exodus": "Exodus", "leviticus": "Leviticus",
    "numbers": "Numbers", "deuteronomy": "Deuteronomy",
    "joshua": "Joshua", "judges": "Judges", "ruth": "Ruth",
    "1 samuel": "1 Samuel", "2 samuel": "2 Samuel",
    "1 kings": "1 Kings", "2 kings": "2 Kings",
    "1 chronicles": "1 Chronicles", "2 chronicles": "2 Chronicles",
    "ezra": "Ezra", "nehemiah": "Nehemiah", "esther": "Esther",
    "job": "Job", "psalms": "Psalms", "proverbs": "Proverbs",
    "ecclesiastes": "Ecclesiastes", "song of solomon": "Song of Solomon",
    "isaiah": "Isaiah", "jeremiah": "Jeremiah", "lamentations": "Lamentations",
    "ezekiel": "Ezekiel", "daniel": "Daniel",
    "hosea": "Hosea", "joel": "Joel", "amos": "Amos",
    "obadiah": "Obadiah", "jonah": "Jonah", "micah": "Micah",
    "nahum": "Nahum", "habakkuk": "Habakkuk", "zephaniah": "Zephaniah",
    "haggai": "Haggai", "zechariah": "Zechariah", "malachi": "Malachi",
    "matthew": "Matthew", "mark": "Mark", "luke": "Luke", "john": "John",
    "acts": "Acts", "romans": "Romans",
    "1 corinthians": "1 Corinthians", "2 corinthians": "2 Corinthians",
    "galatians": "Galatians", "ephesians": "Ephesians",
    "philippians": "Philippians", "colossians": "Colossians",
    "1 thessalonians": "1 Thessalonians", "2 thessalonians": "2 Thessalonians",
    "1 timothy": "1 Timothy", "2 timothy": "2 Timothy",
    "titus": "Titus", "philemon": "Philemon", "hebrews": "Hebrews",
    "james": "James", "1 peter": "1 Peter", "2 peter": "2 Peter",
    "1 john": "1 John", "2 john": "2 John", "3 john": "3 John",
    "jude": "Jude", "revelation": "Revelation",
    # Common abbreviations
    "gen": "Genesis", "ge": "Genesis",
    "exo": "Exodus", "exod": "Exodus", "ex": "Exodus",
    "lev": "Leviticus", "le": "Leviticus",
    "num": "Numbers", "nu": "Numbers", "nm": "Numbers",
    "deut": "Deuteronomy", "deu": "Deuteronomy", "dt": "Deuteronomy",
    "josh": "Joshua", "jos": "Joshua",
    "judg": "Judges", "jdg": "Judges", "jg": "Judges",
    "ru": "Ruth", "rth": "Ruth",
    "1sam": "1 Samuel", "1sa": "1 Samuel", "2sam": "2 Samuel", "2sa": "2 Samuel",
    "1ki": "1 Kings", "1kgs": "1 Kings", "2ki": "2 Kings", "2kgs": "2 Kings",
    "1chr": "1 Chronicles", "1ch": "1 Chronicles", "2chr": "2 Chronicles", "2ch": "2 Chronicles",
    "neh": "Nehemiah", "ne": "Nehemiah",
    "est": "Esther", "esth": "Esther",
    "jb": "Job",
    "ps": "Psalms", "psalm": "Psalms", "psa": "Psalms", "pss": "Psalms",
    "prov": "Proverbs", "pro": "Proverbs", "pr": "Proverbs",
    "eccl": "Ecclesiastes", "ecc": "Ecclesiastes", "ec": "Ecclesiastes",
    "sol": "Song of Solomon", "song": "Song of Solomon", "sos": "Song of Solomon", "ss": "Song of Solomon",
    "isa": "Isaiah", "is": "Isaiah",
    "jer": "Jeremiah", "je": "Jeremiah",
    "lam": "Lamentations", "la": "Lamentations",
    "ezek": "Ezekiel", "eze": "Ezekiel", "ez": "Ezekiel",
    "dan": "Daniel", "da": "Daniel", "dn": "Daniel",
    "hos": "Hosea", "ho": "Hosea",
    "joe": "Joel", "jl": "Joel",
    "am": "Amos",
    "ob": "Obadiah", "oba": "Obadiah",
    "jon": "Jonah", "jnh": "Jonah",
    "mic": "Micah", "mi": "Micah",
    "nah": "Nahum", "na": "Nahum",
    "hab": "Habakkuk", "hb": "Habakkuk",
    "zeph": "Zephaniah", "zep": "Zephaniah",
    "hag": "Haggai", "hg": "Haggai",
    "zech": "Zechariah", "zec": "Zechariah",
    "mal": "Malachi",
    "matt": "Matthew", "mat": "Matthew", "mt": "Matthew",
    "mk": "Mark", "mr": "Mark",
    "lk": "Luke", "lu": "Luke",
    "jn": "John", "joh": "John",
    "ac": "Acts", "act": "Acts",
    "rom": "Romans", "ro": "Romans",
    "1cor": "1 Corinthians", "1co": "1 Corinthians", "2cor": "2 Corinthians", "2co": "2 Corinthians",
    "gal": "Galatians", "ga": "Galatians",
    "eph": "Ephesians", "ep": "Ephesians",
    "phil": "Philippians", "php": "Philippians",
    "col": "Colossians", "co": "Colossians",
    "1thess": "1 Thessalonians", "1th": "1 Thessalonians", "2thess": "2 Thessalonians", "2th": "2 Thessalonians",
    "1tim": "1 Timothy", "1ti": "1 Timothy", "2tim": "2 Timothy", "2ti": "2 Timothy",
    "tit": "Titus", "ti": "Titus",
    "phm": "Philemon", "philem": "Philemon",
    "heb": "Hebrews", "he": "Hebrews",
    "jas": "James", "jm": "James",
    "1pet": "1 Peter", "1pe": "1 Peter", "1pt": "1 Peter",
    "2pet": "2 Peter", "2pe": "2 Peter", "2pt": "2 Peter",
    "1jn": "1 John", "1jo": "1 John", "2jn": "2 John", "2jo": "2 John", "3jn": "3 John", "3jo": "3 John",
    "jud": "Jude",
    "rev": "Revelation", "re": "Revelation",
}

def resolve_book_name(raw):
    """Resolve a book name/abbreviation to its canonical form."""
    key = raw.lower().strip()
    # Direct alias match
    if key in BOOK_ALIASES:
        return BOOK_ALIASES[key]
    # Prefix match against canonical names
    for canon in CANONICAL_BOOKS:
        if canon.lower().startswith(key):
            return canon
    # Prefix match without spaces (e.g. "1cor" -> "1 Corinthians")
    for canon in CANONICAL_BOOKS:
        if canon.lower().replace(' ', '').startswith(key.replace(' ', '')):
            return canon
    return None

def detect_verse_ref(text):
    """Detect a Bible verse reference from spoken or typed text."""
    t = text.lower().strip()
    # Normalize spoken words
    t = t.replace("chapter ", " ").replace("verse ", ":").replace(" verse ", ":")
    t = re.sub(r'\b(first|one)\b', '1', t)
    t = re.sub(r'\b(second|two)\b', '2', t)
    t = re.sub(r'\b(third|three)\b', '3', t)
    
    # Pattern 1: "Book Chapter:Verse" with space — e.g. "John 3:16", "1 Corinthians 13:4"
    m = re.search(r'((?:[123]\s)?[a-z]+(?:\s(?:of\s)?[a-z]+)?)\s+(\d+)[:\s](\d+)', t)
    # Pattern 2: "BookChapter:Verse" no space — e.g. "exo1:1", "gen1:1", "1cor13:4"
    if not m:
        m = re.search(r'((?:[123])?[a-z]+)(\d+)[:](\d+)', t)
    # Pattern 3: spoken "book chapter verse" — e.g. "genesis 1 1"
    if not m:
        m = re.search(r'((?:[123]\s)?[a-z]+(?:\s(?:of\s)?[a-z]+)?)\s+(\d+)\s+(\d+)', t)
    if not m:
        return None
    raw_book = m.group(1).strip()
    chapter  = int(m.group(2))
    verse    = int(m.group(3))
    book = resolve_book_name(raw_book)
    if not book:
        return None
    return book, chapter, verse

async def whisper_loop():
    global active_translation
    if not os.path.exists(MODEL):
        print(f"[WHISPER] Model not found: {MODEL}")
        print(f"[WHISPER] Audio transcription disabled. Manual lookup still works.")
        return

    print("[WHISPER] Starting whisper-stream...")
    proc = await asyncio.create_subprocess_exec(
        "whisper-stream",
        "--model", MODEL,
        "--language", "en",
        "--step", "2000",
        "--length", "8000",
        "--keep", "200",
        "--threads", "4",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    print("[WHISPER] whisper-stream running")

    conn = get_db()
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            raw = line.decode("utf-8", errors="replace")
            cleaned = raw.replace("\x1b[2K", "").replace("\x1b[1G", "").replace("\x1b[0m", "").strip()
            if not cleaned or cleaned.startswith("[") or cleaned.startswith("whisper") or cleaned.startswith("ggml") or cleaned.startswith("main:"):
                continue

            ref = detect_verse_ref(cleaned)
            if ref:
                book, ch, vs = ref
                v = lookup_verse(conn, book, ch, vs, active_translation)
                if v:
                    v["type"]       = "verse_detected"
                    v["source"]     = "direct"
                    v["confidence"] = 1.0
                    print(f"[WHISPER] Detected: {v['reference']}")
                    await broadcast(json.dumps(v))
    except Exception as e:
        print(f"[WHISPER] error: {e}")
    finally:
        conn.close()
        proc.terminate()

# ─── Main ────────────────────────────────────────────────────────────────────

async def main():
    # Validate
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Bible database not found: {DB_PATH}")
        sys.exit(1)

    print("=" * 56)
    print("  RCCG COM Bible-lite — Local Web Server")
    print("=" * 56)
    print(f"  Database: {DB_PATH}")
    print(f"  Model:    {MODEL} {'(found)' if os.path.exists(MODEL) else '(NOT FOUND — audio disabled)'}")
    print(f"  Web UI:   http://localhost:{HTTP_PORT}")
    print(f"  WS:       ws://localhost:{WS_PORT}")
    print("=" * 56)

    # HTTP in background thread
    t = threading.Thread(target=run_http, daemon=True)
    t.start()
    print(f"[HTTP] Serving on http://localhost:{HTTP_PORT}")

    # WebSocket server
    async with websockets.serve(handle_client, "0.0.0.0", WS_PORT):
        print(f"[WS]   Listening on ws://localhost:{WS_PORT}")
        print()
        print(">>> Open http://localhost:8080 in your browser <<<")
        print()

        # Start whisper in parallel
        asyncio.create_task(whisper_loop())

        # Run forever
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
