#!/usr/bin/env python3
"""
RCCG COM Bible-lite — Local Web Server
Serves the web UI + WebSocket for live transcription, manual lookup, and quote search.
Run:  python3 serve.py
Open:  http://localhost:8080
"""
import asyncio, json, os, re, signal, sqlite3, subprocess, sys, threading, socket
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


def free_ports():
    """Kill any process listening on our HTTP/WebSocket ports before we bind."""
    system = sys.platform
    for port in (HTTP_PORT, WS_PORT):
        try:
            if system.startswith("win"):
                # Use netstat to find PIDs and taskkill them
                result = subprocess.run(
                    ["netstat", "-ano", "|", "findstr", f":{port}"],
                    capture_output=True, text=True, shell=True
                )
                seen_pids = set()
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        if pid.isdigit() and pid not in seen_pids:
                            seen_pids.add(pid)
                            try:
                                subprocess.run(["taskkill", "/F", "/PID", pid], check=False, capture_output=True)
                                print(f"[cleanup] killed process {pid} on port {port}")
                            except Exception as e:
                                print(f"[cleanup] taskkill failed for {pid}: {e}")
            else:
                # Unix: lsof -ti :port | xargs kill -9
                result = subprocess.run(
                    ["lsof", "-ti", f":{port}"],
                    capture_output=True, text=True
                )
                for pid in result.stdout.strip().split():
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                        print(f"[cleanup] killed process {pid} on port {port}")
                    except Exception as e:
                        print(f"[cleanup] kill failed for {pid}: {e}")
        except Exception as e:
            print(f"[cleanup] port {port}: {e}")


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

STOP_WORDS = {
    'the','a','an','and','or','but','in','on','at','to','for','of','with',
    'is','was','are','were','be','been','being','have','has','had','do','does',
    'did','will','would','could','should','may','might','shall','can',
    'i','he','she','it','we','they','you','me','him','her','us','them',
    'my','his','its','our','their','your','this','that','these','those',
    'not','no','nor','so','yet','both','either','neither','each',
    'than','then','when','where','who','which','what','how',
    'if','as','by','from','into','through','during','before','after',
    'above','below','up','down','out','off','over','under','again',
    'said','unto','thy','thee','thou','ye','hath','doth','shall',
}

def _sig_words(text):
    """Extract significant (non-stop) words from text."""
    words = re.findall(r'[a-z]+', text.lower())
    sig = [w for w in words if w not in STOP_WORDS and len(w) > 2]
    return sig if sig else words

def _ngrams(words, n):
    """Generate n-grams from a word list."""
    return [' '.join(words[i:i+n]) for i in range(len(words) - n + 1)]

def search_quote(conn, text, translation, limit=5):
    """
    Phrase-first quote search:
    1. Build SQL using distinctive 3-word phrases (trigrams) as LIKE filters — 
       this fetches verses containing the actual spoken phrases, not just words.
    2. Score fetched candidates by n-gram overlap.
    3. Return ranked list so presenter can choose.
    """
    t = text.lower().strip()
    all_words = re.findall(r'[a-z]+', t)
    if not all_words:
        return []
    all_words_set = set(all_words)
    sig = _sig_words(t)
    tid = get_translation_id(conn, translation)

    # ── Build SQL using PHRASE filters (trigrams + bigrams from full text) ──
    # This ensures "was the word" fetches John 1:1, not just Genesis
    phrase_filters = []
    # Trigrams first (most distinctive)
    for i in range(len(all_words) - 2):
        phrase_filters.append(' '.join(all_words[i:i+3]))
    # Bigrams as fallback
    if len(phrase_filters) < 3:
        for i in range(len(all_words) - 1):
            phrase_filters.append(' '.join(all_words[i:i+2]))
    # Deduplicate and take up to 12 filters
    seen_f = set()
    unique_filters = []
    for f in phrase_filters:
        if f not in seen_f:
            seen_f.add(f)
            unique_filters.append(f)
        if len(unique_filters) >= 12:
            break

    if unique_filters:
        conditions = " OR ".join(["LOWER(text) LIKE ?" for _ in unique_filters])
        params = [f"%{f}%" for f in unique_filters]
    else:
        # Fallback: sig word search
        conditions = " OR ".join(["LOWER(text) LIKE ?" for _ in sig[:6]])
        params = [f"%{w}%" for w in sig[:6]]
    params.append(tid)

    try:
        rows = conn.execute(
            f"SELECT * FROM verses WHERE ({conditions}) AND translation_id=? LIMIT 200",
            params
        ).fetchall()
    except Exception as e:
        print(f"search error: {e}")
        return []

    # ── Pre-compute query n-grams (2-5) ──
    query_ngrams = {}
    for n in (5, 4, 3, 2):
        if len(all_words) >= n:
            query_ngrams[n] = set(_ngrams(all_words, n))

    # ── Score candidates ──
    results = []
    sig_set = set(sig)
    for row in rows:
        verse_text  = row["text"].lower()
        verse_words = re.findall(r'[a-z]+', verse_text)
        verse_set   = set(verse_words)

        # Signal 1: weighted n-gram phrase match (primary)
        phrase_score = 0.0
        total_weight = 0.0
        for n, weight in ((5, 5.0), (4, 3.0), (3, 1.5), (2, 0.5)):
            if n not in query_ngrams or len(verse_words) < n:
                continue
            verse_ngrams = set(_ngrams(verse_words, n))
            matched  = len(query_ngrams[n] & verse_ngrams)
            possible = len(query_ngrams[n])
            phrase_score += weight * (matched / max(possible, 1))
            total_weight += weight
        if total_weight > 0:
            phrase_score /= total_weight

        # Signal 2: significant word overlap
        verse_sig = set(_sig_words(row["text"]))
        sig_score = len(sig_set & verse_sig) / max(len(sig_set), 1)

        # Signal 3: total word coverage
        all_score = len(all_words_set & verse_set) / max(len(all_words_set), 1)

        score = (phrase_score * 0.75) + (sig_score * 0.15) + (all_score * 0.10)
        score = min(score, 1.0)

        if score > 0.05:
            results.append({
                "book_name":   row["book_name"],
                "chapter":     row["chapter"],
                "verse":       row["verse"],
                "text":        row["text"],
                "reference":   f"{row['book_name']} {row['chapter']}:{row['verse']}",
                "translation": translation,
                "score":       round(score, 3),
            })

    results.sort(key=lambda r: r["score"], reverse=True)
    seen, deduped = set(), []
    for r in results:
        if r["reference"] not in seen:
            seen.add(r["reference"])
            deduped.append(r)
    if deduped:
        print(f"[SEARCH] '{t[:60]}' → {len(deduped)} results, top: {deduped[0]['reference']} ({deduped[0]['score']})")
    else:
        print(f"[SEARCH] '{t[:60]}' → no results")
    return deduped[:limit]

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

            elif action == "speech_transcription":
                text = msg.get("text", "").strip()
                final = msg.get("final", False)
                if text:
                    print(f"[SPEECH] {'Final' if final else 'Interim'}: {text}")
                    await broadcast(json.dumps({"type": "transcription", "text": text, "final": final}))
                    if final and len(text) > 3:
                        ref = detect_verse_ref(text)
                        if ref:
                            book, ch, vs = ref
                            v = lookup_verse(conn, book, ch, vs, active_translation)
                            if v:
                                v["type"]       = "verse_detected"
                                v["source"]     = "direct"
                                v["confidence"] = 1.0
                                print(f"[SPEECH] ✅ Verse: {v['reference']}")
                                await broadcast(json.dumps(v))
                        if not ref and len(text) > 10:
                            results = search_quote(conn, text, active_translation, 5)
                            if results:
                                top = results[0]
                                if top["score"] >= 0.70:
                                    # Very high confidence — auto-display
                                    top["type"]       = "verse_detected"
                                    top["source"]     = "quote"
                                    top["confidence"] = top["score"]
                                    print(f"[SPEECH] ✅ Auto-display ({top['score']*100:.0f}%): {top['reference']}")
                                    await broadcast(json.dumps(top))
                                elif top["score"] >= 0.2:
                                    # Show candidates for presenter to choose
                                    print(f"[SPEECH] 📝 Candidates ({len(results)}): top={top['score']*100:.0f}%")
                                    await broadcast(json.dumps({"type": "candidates", "candidates": results}))

            elif action == "search_quote":
                text  = msg.get("text", "")
                limit = msg.get("limit", 5)
                results = search_quote(conn, text, active_translation, limit)
                print(f"[QUOTE] '{text[:50]}' -> {len(results)} results, top={results[0]['score'] if results else 0}")
                if results:
                    # Always show candidates so presenter can choose — never auto-display for manual quote search
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
    # Normalize spoken number words
    t = re.sub(r'\b(first|one)\b', '1', t)
    t = re.sub(r'\b(second|two)\b', '2', t)
    t = re.sub(r'\b(third|three)\b', '3', t)
    # Normalize "chapter X" -> just X, "verse X" -> :X
    t = re.sub(r'\bchapter\s+', '', t)
    t = re.sub(r'\bverse\s+', ':', t)
    # Normalize colon with surrounding spaces — "1 : 1" -> "1:1"
    t = re.sub(r'\s*:\s*', ':', t)
    # Collapse multiple spaces
    t = re.sub(r'  +', ' ', t)

    # Pattern 1: "Book Chapter:Verse" with space — e.g. "John 3:16", "1 Corinthians 13:4"
    m = re.search(r'((?:[123]\s)?[a-z]+(?:\s(?:of\s)?[a-z]+)?)\s+(\d+):(\d+)', t)
    # Pattern 2: "BookChapter:Verse" no space — e.g. "exo1:1", "gen1:1", "1cor13:4"
    if not m:
        m = re.search(r'((?:[123])?[a-z]+)(\d+):(\d+)', t)
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

def _is_poor_transcription(text):
    """Filter out poor quality transcriptions that cause false positives."""
    text_lower = text.lower().strip()
    
    # Skip very short or empty transcriptions
    if len(text_lower) < 3:
        return True
    
    # Skip if it's mostly music notation - be less aggressive
    music_count = text_lower.count("♪") + text_lower.count("♫")
    if music_count > 3:
        return True
    
    # Only filter obvious non-speech content
    if text_lower.startswith("(") and text_lower.endswith(")"):
        if "music" in text_lower or "singing" in text_lower:
            return True
    
    return False

def _is_non_bible_content(text):
    """Check if text is likely not bible content."""
    text_lower = text.lower().strip()
    
    # Only filter obvious non-bible content
    obvious_non_bible = [
        "video", "youtube", "subscribe", "like", "share",
        "camera", "recording", "live stream", "broadcast",
    ]
    
    for indicator in obvious_non_bible:
        if indicator in text_lower:
            return True
    
    return False

async def whisper_loop():
    global active_translation
    if not os.path.exists(MODEL):
        print(f"[WHISPER] Model not found: {MODEL}")
        print(f"[WHISPER] Audio transcription disabled. Manual lookup still works.")
        return

    print("[WHISPER] Starting whisper-stream...")
    print(f"[WHISPER] Model path: {MODEL}")
    try:
        proc = await asyncio.create_subprocess_exec(
            "whisper-stream",
            "--model", MODEL,
            "--language", "en",
            "--step", "3000",     # 3 second chunks for reliability
            "--length", "5000",   # 5 second windows for balance
            "--keep", "1000",     # 1 second overlap for continuity
            "--threads", "2",     # Fewer threads for stability
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        print("[WHISPER] whisper-stream running (PID: {})".format(proc.pid))
        print("[WHISPER] Waiting for audio...")
    except Exception as e:
        print(f"[WHISPER] Failed to start whisper-stream: {e}")
        print("[WHISPER] Make sure whisper-stream is installed and accessible")
        return

    conn = get_db()
    try:
        audio_buffer = []
        last_detection = 0
        
        async def read_stderr():
            """Read stderr to monitor whisper status"""
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                err = line.decode("utf-8", errors="replace").strip()
                if err and not err.startswith("whisper"):
                    print(f"[WHISPER-STDERR] {err}")
        
        # Start stderr reader in background
        asyncio.create_task(read_stderr())
        
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            raw = line.decode("utf-8", errors="replace")
            cleaned = raw.replace("\x1b[2K", "").replace("\x1b[1G", "").replace("\x1b[0m", "").strip()
            
            # Skip control messages and empty lines
            if not cleaned or cleaned.startswith("[") or cleaned.startswith("whisper") or cleaned.startswith("ggml") or cleaned.startswith("main:"):
                continue
            
            # Add to buffer for context
            audio_buffer.append(cleaned)
            if len(audio_buffer) > 5:
                audio_buffer.pop(0)
            
            print(f"[WHISPER] Heard: {cleaned}")
            
            # Filter out poor quality transcriptions
            if _is_poor_transcription(cleaned):
                print(f"[WHISPER] 🚫 Skipping poor transcription: {cleaned}")
                continue
            
            # Check for verse references in current and buffer
            ref = detect_verse_ref(cleaned)
            if not ref:
                # Check in buffer context (combine last few phrases)
                combined = " ".join(audio_buffer[-3:])
                ref = detect_verse_ref(combined)
            
            if ref:
                book, ch, vs = ref
                v = lookup_verse(conn, book, ch, vs, active_translation)
                if v:
                    v["type"]       = "verse_detected"
                    v["source"]     = "direct"
                    v["confidence"] = 1.0
                    print(f"[WHISPER] ✅ Detected: {v['reference']}")
                    await broadcast(json.dumps(v))
                    last_detection = asyncio.get_event_loop().time()
                else:
                    print(f"[WHISPER] ❌ Reference found but not in DB: {book} {ch}:{vs}")
            
            # Check for scripture quotes (partial passages) - more sensitive
            if cleaned and len(cleaned.strip()) > 8:  # Check shorter phrases too
                # Skip if it contains obvious non-bible indicators
                if _is_non_bible_content(cleaned):
                    print(f"[WHISPER] 🚫 Skipping non-bible content: {cleaned}")
                    continue
                    
                # Use buffer for better context
                quote_text = " ".join(audio_buffer[-2:]) if len(audio_buffer) > 1 else cleaned
                results = search_quote(conn, quote_text, active_translation, 5)
                if results:
                    top = results[0]
                    # Lower threshold for auto-display to be more sensitive
                    if top.score >= 0.4:
                        # Auto-display medium confidence matches
                        v = {
                            "type": "verse_detected",
                            "source": "quote",
                            "confidence": top.score,
                            "book_name": top.verse.book_name,
                            "chapter": top.verse.chapter,
                            "verse": top.verse.verse,
                            "text": top.verse.text,
                            "reference": top.verse.reference(),
                            "translation": active_translation,
                        }
                        print(f"[WHISPER] ✅ Quote match ({top.score*100:.0f}%): {v['reference']}")
                        await broadcast(json.dumps(v))
                    elif top.score >= 0.2:
                        # Show candidates for lower confidence
                        candidates = [{"reference": r.verse.reference(), "translation": active_translation,
                                     "book_name": r.verse.book_name, "chapter": r.verse.chapter,
                                     "verse": r.verse.verse, "text": r.verse.text, "score": r.score} 
                                    for r in results]
                        await broadcast(json.dumps({"type": "candidates", "candidates": candidates}))
                        print(f"[WHISPER] 📝 Quote candidates: {len(candidates)} matches")
            
            # Send live transcription updates to show it's working
            if cleaned and len(cleaned) > 3:
                await broadcast(json.dumps({
                    "type": "transcription",
                    "text": cleaned
                }))
                
    except Exception as e:
        print(f"[WHISPER] error: {e}")
    finally:
        conn.close()
        if 'proc' in locals():
            proc.terminate()
            await proc.wait()
            print("[WHISPER] whisper-stream stopped")

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
    print(f"  Model:    {MODEL} {'(Whisper model found)' if os.path.exists(MODEL) else '(Whisper model not bundled — using browser Web Speech API)'}")
    print(f"  Web UI:   http://localhost:{HTTP_PORT}")
    print(f"  WS:       ws://localhost:{WS_PORT}")
    print("=" * 56)

    # Free ports from any previous run
    free_ports()

    # HTTP in background thread
    t = threading.Thread(target=run_http, daemon=True)
    t.start()
    print(f"[HTTP] Serving on http://localhost:{HTTP_PORT}")

    # WebSocket server
    async with websockets.serve(handle_client, "0.0.0.0", WS_PORT, reuse_address=True):
        print(f"[WS]   Listening on ws://localhost:{WS_PORT}")
        print()
        print(">>> Open http://localhost:8080 in your browser <<<")
        print()

        # Whisper disabled — using Web Speech API in browser instead
        # asyncio.create_task(whisper_loop())
        print("[INFO] Using Web Speech API (browser-native transcription)")

        # Run forever
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
