#!/usr/bin/env python3
"""
RCCG COM Bible-lite — Local Web Server
Serves the web UI + WebSocket for live transcription, manual lookup, and quote search.
Run:  python3 serve.py
Open:  http://localhost:8080
"""
import asyncio, json, os, re, signal, sqlite3, subprocess, sys, threading, socket, queue, time
import difflib
from http.server import HTTPServer, SimpleHTTPRequestHandler

try:
    import websockets
except ImportError:
    print("Installing websockets...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets", "--quiet"])
    import websockets

try:
    import vosk
    import sounddevice as sd
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False

# When bundled with PyInstaller (onefile), resources are extracted to sys._MEIPASS.
# When running as a plain script, use the directory of this file.
_BASE = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
DB_PATH   = os.path.join(_BASE, "data", "rhema.db")
MODEL     = os.path.join(_BASE, "models", "ggml-base.en.bin")
VOSK_MODEL = os.path.join(_BASE, "models", "vosk-model-en-us-0.22-lgraph")
WEB_DIR   = os.path.join(_BASE, "web-ui")
HTTP_PORT = 8080
WS_PORT   = 8765

# Vosk speech recognition state
vosk_running = False
vosk_listening = False
vosk_queue = queue.Queue()
main_loop = None


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

# ─── Vosk speech recognition ─────────────────────────────────────────────────

def start_vosk():
    global vosk_listening
    if not VOSK_AVAILABLE:
        print("[VOSK] vosk/sounddevice not installed")
        return False
    if not os.path.exists(VOSK_MODEL):
        print(f"[VOSK] Model not found: {VOSK_MODEL}")
        return False
    vosk_listening = True
    print("[VOSK] Listening started")
    return True

def stop_vosk():
    global vosk_listening
    vosk_listening = False
    # drain the audio queue
    while not vosk_queue.empty():
        try:
            vosk_queue.get_nowait()
        except queue.Empty:
            break
    print("[VOSK] Listening stopped")

def vosk_worker():
    global vosk_running, vosk_listening
    if not VOSK_AVAILABLE:
        print("[VOSK] vosk/sounddevice not installed — speech disabled")
        return
    if not os.path.exists(VOSK_MODEL):
        print(f"[VOSK] Model not found: {VOSK_MODEL} — speech disabled")
        return

    try:
        model = vosk.Model(VOSK_MODEL)
    except Exception as e:
        print(f"[VOSK] Failed to load model: {e}")
        return

    samplerate = 16000
    blocksize = 4000

    def audio_callback(indata, frames, time, status):
        if vosk_listening:
            vosk_queue.put(bytes(indata))

    try:
        with sd.RawInputStream(samplerate=samplerate, blocksize=blocksize, dtype='int16',
                               channels=1, callback=audio_callback):
            rec = vosk.KaldiRecognizer(model, samplerate)
            print("[VOSK] Ready")
            vosk_running = True
            while vosk_running:
                if not vosk_listening:
                    # drain queue while paused
                    while not vosk_queue.empty():
                        try:
                            vosk_queue.get_nowait()
                        except queue.Empty:
                            break
                    time.sleep(0.05)
                    continue

                try:
                    data = vosk_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    text = result.get('text', '').strip()
                    if text:
                        print(f"[VOSK] Final: {text}")
                        if main_loop:
                            asyncio.run_coroutine_threadsafe(
                                broadcast(json.dumps({"type": "speech_transcription", "text": text, "final": True})),
                                main_loop
                            )
                else:
                    partial = json.loads(rec.PartialResult())
                    text = partial.get('partial', '').strip()
                    if text:
                        if main_loop:
                            asyncio.run_coroutine_threadsafe(
                                broadcast(json.dumps({"type": "speech_transcription", "text": text, "final": False})),
                                main_loop
                            )
    except Exception as e:
        print(f"[VOSK] error: {e}")
        vosk_running = False

# ─── Speech text normalization ───────────────────────────────────────────────

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100,
}

def _parse_number_words(words):
    """Parse a sequence of number words into a list of integers.

    Builds valid English numbers greedily from left to right, e.g.:
      'twenty three' -> [23], 'three sixteen' -> [3, 16],
      'one hundred twenty three' -> [123].
    This keeps chapter and verse numbers separate when spoken without a marker.
    """
    UNITS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine"}
    TEENS = {"ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
             "sixteen", "seventeen", "eighteen", "nineteen"}
    TENS = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}
    HUNDRED = "hundred"

    numbers = []
    i = 0
    while i < len(words):
        w = words[i]
        if w in UNITS or w in TEENS:
            total = NUMBER_WORDS[w]
            i += 1
            # Optional: ... hundred [tens [unit]] (e.g. one hundred twenty three)
            if i < len(words) and words[i] == HUNDRED:
                total *= 100
                i += 1
                if i < len(words) and words[i] in TENS:
                    total += NUMBER_WORDS[words[i]]
                    i += 1
                    if i < len(words) and (words[i] in UNITS or words[i] in TEENS):
                        total += NUMBER_WORDS[words[i]]
                        i += 1
                elif i < len(words) and (words[i] in UNITS or words[i] in TEENS):
                    total += NUMBER_WORDS[words[i]]
                    i += 1
            numbers.append(total)
        elif w in TENS:
            total = NUMBER_WORDS[w]
            i += 1
            if i < len(words) and (words[i] in UNITS or words[i] in TEENS):
                total += NUMBER_WORDS[words[i]]
                i += 1
            numbers.append(total)
        elif w == HUNDRED:
            numbers.append(100)
            i += 1
        else:
            return None
    return numbers

def _replace_number_word_sequences(text):
    """Find sequences of number words and replace each with digits."""
    words = text.split()
    result = []
    buffer = []
    for word in words:
        clean = re.sub(r'[^a-zA-Z\-]', '', word).lower()
        if '-' in clean and all(part in NUMBER_WORDS for part in clean.split('-')):
            # Hyphenated number word (e.g. "twenty-three")
            buffer.extend(clean.split('-'))
        elif clean in NUMBER_WORDS:
            buffer.append(clean)
        else:
            if buffer:
                nums = _parse_number_words(buffer)
                if nums is not None:
                    result.extend(str(n) for n in nums)
                else:
                    result.extend(buffer)
                buffer = []
            result.append(word)
    if buffer:
        nums = _parse_number_words(buffer)
        if nums is not None:
            result.extend(str(n) for n in nums)
        else:
            result.extend(buffer)
    return ' '.join(result)

def normalize_speech_text(text):
    """Normalize spoken text so verse detection works with number words and common mishearings."""
    t = text.lower()
    # Strip common spoken prefixes that break book name matching
    t = re.sub(r'\bthe\s+book\s+of\s+', '', t)
    t = re.sub(r'\bbook\s+of\s+', '', t)
    t = re.sub(r'\bthe\s+epistle\s+(of|to)\s+(the\s+)?', '', t)
    # Strip leading 'the' before a book name (e.g. 'the Psalms 116:14')
    t = re.sub(r'^the\s+', '', t)
    t = re.sub(r'\bfirst\s+', '1 ', t)
    t = re.sub(r'\bsecond\s+', '2 ', t)
    t = re.sub(r'\bthird\s+', '3 ', t)
    # Remove filler 'and' between number words (e.g. 'one hundred and sixteen' -> 'one hundred sixteen')
    t = re.sub(r'\bhundred\s+and\s+', 'hundred ', t)
    # Normalize % as colon (browser sometimes transcribes chapter:verse as '2%11' or '2% 11')
    t = re.sub(r'(\d)\s*%\s*(\d)', r'\1:\2', t)   # "2%11" or "2% 11" -> "2:11"
    t = re.sub(r'%\s*(\d)', r':\1', t)             # "%11" -> ":11"
    t = re.sub(r'(\d)\s*%', r'\1', t)              # trailing "2%" -> "2" (chapter only, verse follows)
    # Common book-name / biblical term mishearings from Vosk small model
    t = re.sub(r'\bjon\b', 'john', t)
    t = re.sub(r'\bjn\b', 'john', t)
    t = re.sub(r'\bgen\b', 'genesis', t)
    t = re.sub(r'\bexo\b', 'exodus', t)
    t = re.sub(r'\bps\b', 'psalms', t)
    t = re.sub(r'\bpsalm\b', 'psalms', t)
    t = re.sub(r'\bprov\b', 'proverbs', t)
    t = re.sub(r'\beccl\b', 'ecclesiastes', t)
    t = re.sub(r'\bsos\b', 'song of solomon', t)
    t = re.sub(r'\bisa\b', 'isaiah', t)
    t = re.sub(r'\bjer\b', 'jeremiah', t)
    t = re.sub(r'\blam\b', 'lamentations', t)
    t = re.sub(r'\bezek\b', 'ezekiel', t)
    t = re.sub(r'\bdan\b', 'daniel', t)
    t = re.sub(r'\bhos\b', 'hosea', t)
    t = re.sub(r'\bjoel\b', 'joel', t)
    t = re.sub(r'\bamos\b', 'amos', t)
    t = re.sub(r'\boba\b', 'obadiah', t)
    t = re.sub(r'\bmic\b', 'micah', t)
    t = re.sub(r'\bnah\b', 'nahum', t)
    t = re.sub(r'\bzeph\b', 'zephaniah', t)
    t = re.sub(r'\bhag\b', 'haggai', t)
    t = re.sub(r'\bzech\b', 'zechariah', t)
    t = re.sub(r'\bmal\b', 'malachi', t)
    t = re.sub(r'\bmatt\b', 'matthew', t)
    t = re.sub(r'\bmark\b', 'mark', t)
    t = re.sub(r'\bluke\b', 'luke', t)
    t = re.sub(r'\bacts\b', 'acts', t)
    t = re.sub(r'\brom\b', 'romans', t)
    t = re.sub(r'\b gal\b', ' galatians', t)
    t = re.sub(r'\beph\b', 'ephesians', t)
    t = re.sub(r'\bphil\b', 'philippians', t)
    t = re.sub(r'\bcol\b', 'colossians', t)
    t = re.sub(r'\bheb\b', 'hebrews', t)
    t = re.sub(r'\bjas\b', 'james', t)
    t = re.sub(r'\bjud\b', 'jude', t)
    t = re.sub(r'\brev\b', 'revelation', t)
    # Convert spoken reference markers to punctuation before number parsing so
    # chapter and verse numbers don't combine across the boundary.
    # NOTE: keep the word 'chapter' so cross-utterance context can distinguish
    # 'chapter 5' from a bare number. detect_verse_ref strips it later.
    t = re.sub(r'\bverse\s+', ':', t)
    t = re.sub(r'\bverses?\s+', ':', t)
    # Common mishearings in loud halls: 'versus' -> 'verse', 'chapters' -> 'chapter'
    t = re.sub(r'\bversus\b', 'verse', t)
    t = re.sub(r'\bchapters\b', 'chapter', t)
    # Convert spoken number-word sequences to digits (e.g. "twenty three" -> "23")
    t = _replace_number_word_sequences(t)
    # Remove "and" between chapter/verse digits (e.g. "58 and 11" -> "58 11")
    t = re.sub(r'(\d)\s+and\s+(\d)', r'\1 \2', t)
    return t

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

def _extract_book_names(text):
    """Return canonical book names found in the query text."""
    found = []
    t = text.lower()
    # Multi-word books first to avoid matching '1' separately from '1 Corinthians'
    for canon in sorted(CANONICAL_BOOKS, key=lambda x: -len(x)):
        if canon.lower() in t:
            found.append(canon)
            t = t.replace(canon.lower(), '')  # avoid double counting
    return found

_QUOTE_CACHE = {}
_QUOTE_CACHE_MAX = 200

def search_quote(conn, text, translation, limit=5):
    """
    Phrase-first quote search:
    1. Build SQL using distinctive 3-word phrases (trigrams) as LIKE filters — 
       this fetches verses containing the actual spoken phrases, not just words.
    2. Score fetched candidates by n-gram overlap.
    3. Boost candidates whose book name appears in the query.
    4. Return ranked list so presenter can choose.
    Results are cached so repeated interim transcripts don't re-run the SQL.
    """
    t = text.lower().strip()
    cache_key = (t, translation, limit)
    if cache_key in _QUOTE_CACHE:
        return _QUOTE_CACHE[cache_key]
    all_words = re.findall(r'[a-z]+', t)
    if not all_words:
        return []
    all_words_set = set(all_words)
    sig = _sig_words(t)
    tid = get_translation_id(conn, translation)
    book_names_in_query = _extract_book_names(t)

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

        # Signal 4: book-name boost (strong signal in noisy halls when book is clear)
        if book_names_in_query and row["book_name"] in book_names_in_query:
            score = min(score + 0.35, 1.0)

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
    out = deduped[:limit]
    if len(_QUOTE_CACHE) >= _QUOTE_CACHE_MAX:
        _QUOTE_CACHE.pop(next(iter(_QUOTE_CACHE)))
    _QUOTE_CACHE[cache_key] = out
    return out

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
    last_book_context = None    # book name carried across utterance boundaries
    last_chapter_context = None # chapter number carried across utterance boundaries
    last_detected_ref = None    # suppress duplicate auto-display spam
    conn = get_db()
    print(f"[WS] client connected ({len(broadcast_clients)} total)")
    try:
        # Send init
        trans = get_translations(conn)
        vosk_available = VOSK_AVAILABLE and os.path.exists(VOSK_MODEL)
        print(f"[WS] init: vosk_available={vosk_available} BASE={_BASE} MODEL_EXISTS={os.path.exists(VOSK_MODEL)}")
        await ws.send(json.dumps({
            "type": "init",
            "translation": active_translation,
            "translations": trans,
            "vosk_available": vosk_available,
            "debug_base": _BASE,
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

            elif action == "start_mic":
                if not (VOSK_AVAILABLE and os.path.exists(VOSK_MODEL)):
                    await ws.send(json.dumps({
                        "type": "mic_status",
                        "listening": False,
                        "error": "Vosk model is not available in this build. Use Web Speech API or install the offline build."
                    }))
                else:
                    ok = start_vosk()
                    await broadcast(json.dumps({"type": "mic_status", "listening": ok}))

            elif action == "stop_mic":
                stop_vosk()
                await broadcast(json.dumps({"type": "mic_status", "listening": False}))

            elif action == "speech_transcription":
                text = msg.get("text", "").strip()
                final = msg.get("final", False)
                # All alternatives from Web Speech API (helps in noisy rooms)
                alternatives = msg.get("alternatives", [text])
                if text and text not in alternatives:
                    alternatives.insert(0, text)
                if text:
                    print(f"[SPEECH] {'Final' if final else 'Interim'}: {text}" +
                          (f" (+{len(alternatives)-1} alts)" if len(alternatives) > 1 else ""))
                    await broadcast(json.dumps({"type": "transcription", "text": text, "final": final}))

                    # Build an ORDERED list of candidate strings. The primary
                    # transcript (alternatives[0]) is tried before lower-ranked
                    # Web Speech alternatives so a garbage alternative can't
                    # hijack a clean primary (e.g. 'Genesis chapter 5' vs
                    # alt 'Genesis chapter 2 5' -> wrongly Genesis 2:5).
                    if len(alternatives) > 1:
                        print(f"[SPEECH] alts: {alternatives[1:3]}")
                    candidate_strings = []
                    def _add_cand(c):
                        if c and c not in candidate_strings:
                            candidate_strings.append(c)
                    for alt in alternatives[:3]:
                        _add_cand(alt)
                        norm = normalize_speech_text(alt).strip()
                        # Cross-utterance: chapter/verse numbers with book context
                        if last_book_context:
                            # "chapter N verse M" -> "book N:M" (verse marker becomes ':')
                            m = re.match(r'^(?:chapter\s+)?(\d+)\s+(\d+)$', norm)
                            if m:
                                _add_cand(f"{last_book_context} {m.group(1)}:{m.group(2)}")
                            # "chapter N verse M" / "chapter:N verse M" / "1:5" -> "book 1:5"
                            m_colon = re.match(r'^(?:chapter\s+)?(\d+)\s*:\s*(\d+)$', norm)
                            if m_colon:
                                _add_cand(f"{last_book_context} {m_colon.group(1)}:{m_colon.group(2)}")
                            # "chapter N" only or bare number
                            m_ch = re.match(r'^(?:chapter\s+)?(\d+)$', norm)
                            if m_ch and not last_chapter_context:
                                _add_cand(f"{last_book_context} {m_ch.group(1)}:1")
                            # "verse N" only (normalized to ':N')
                            if last_chapter_context:
                                m_vs = re.match(r'^:\s*(\d+)$', norm)
                                if m_vs:
                                    _add_cand(f"{last_book_context} {last_chapter_context}:{m_vs.group(1)}")
                        # Cross-utterance: bare "N:M" or "N M" prepended with last book
                        if last_book_context:
                            if re.match(r'^\d+\s*:\s*\d+', norm):
                                _add_cand(f"{last_book_context} {alt}")
                            elif re.match(r'^\d+\s+\d+$', norm):
                                _add_cand(f"{last_book_context} {alt}")

                    # Try candidates in priority order (primary transcript first)
                    detected_ref = None
                    detected_source = None
                    for cand in candidate_strings:
                        if not cand or len(cand) < 4:
                            continue
                        ref = detect_verse_ref(cand)
                        if ref:
                            book, ch, vs = ref
                            v = lookup_verse(conn, book, ch, vs, active_translation)
                            if v:
                                detected_ref = v
                                detected_source = "direct"
                                break

                    # Update context memory from the original transcript (not just candidates)
                    BOOK_WORDS = r'(?:[123]\s+)?(?:philippians|ephesians|colossians|galatians|corinthians|thessalonians|thess|timothy|hebrews|romans|genesis|exodus|leviticus|numbers|deuteronomy|joshua|judges|ruth|samuel|kings|chronicles|ezra|nehemiah|esther|job|psalms|psalm|proverbs|ecclesiastes|isaiah|jeremiah|lamentations|ezekiel|daniel|hosea|joel|amos|obadiah|jonah|micah|nahum|habakkuk|zephaniah|haggai|zechariah|malachi|matthew|mark|luke|john|acts|revelation|titus|philemon|james|peter|jude)'
                    for alt in alternatives[:3]:
                        norm = normalize_speech_text(alt).strip()
                        # Book + chapter + verse
                        bk_match = re.search(r'\b((?:[123]\s+)?[a-z]+(?:\s[a-z]+)?)\s+(\d+)[:\s](\d+)', norm)
                        if bk_match:
                            candidate_book = resolve_book_name(bk_match.group(1))
                            if candidate_book:
                                last_book_context = candidate_book
                                last_chapter_context = int(bk_match.group(2))
                                break
                        # Book + chapter only (e.g. "John 5" or "John chapter 5")
                        bk_ch = re.search(r'\b(' + BOOK_WORDS + r')\s+(?:chapter\s+)?(\d+)\s*$', norm)
                        if bk_ch:
                            candidate_book = resolve_book_name(bk_ch.group(1))
                            if candidate_book:
                                last_book_context = candidate_book
                                last_chapter_context = int(bk_ch.group(2))
                                print(f"[SPEECH] 📑 Book+chapter context: {last_book_context} {last_chapter_context}")
                                break
                        # Book only (e.g. "the book of Joshua", "1 Thessalonians")
                        bk_only = re.search(r'\b(' + BOOK_WORDS + r')\b', norm)
                        if bk_only:
                            candidate_book = resolve_book_name(bk_only.group(1))
                            if candidate_book:
                                if candidate_book != last_book_context:
                                    # New book spoken — reset stale chapter context
                                    last_chapter_context = None
                                last_book_context = candidate_book
                                print(f"[SPEECH] 📖 Book context set: {last_book_context}")
                                break
                        # Explicit "chapter N" ALWAYS updates chapter context (even if stale)
                        ch_explicit = re.search(r'\bchapter\s+(\d+)\b', norm)
                        if ch_explicit and last_book_context:
                            last_chapter_context = int(ch_explicit.group(1))
                            print(f"[SPEECH] 📑 Chapter context set: {last_book_context} {last_chapter_context}")
                            break
                        # Bare number sets chapter only when none is known yet
                        ch_only = re.match(r'^(\d+)$', norm)
                        if ch_only and last_book_context and not last_chapter_context:
                            last_chapter_context = int(ch_only.group(1))
                            print(f"[SPEECH] 📑 Chapter context set: {last_book_context} {last_chapter_context}")
                            break
                        # Verse only (e.g. "verse 5" normalized to ":5")
                        vs_only = re.match(r'^:\s*(\d+)$', norm)
                        if vs_only and last_book_context and last_chapter_context:
                            print(f"[SPEECH] 📜 Verse context: {last_book_context} {last_chapter_context}:{vs_only.group(1)}")
                            break

                    # Broadcast direct detection if found and not a duplicate
                    if detected_ref:
                        ref_key = f"{detected_ref['reference']}"
                        if ref_key == last_detected_ref:
                            print(f"[SPEECH] ⏭ Already displayed {ref_key}, skipping duplicate")
                        else:
                            detected_ref["type"]       = "verse_detected"
                            detected_ref["source"]     = detected_source
                            detected_ref["confidence"] = 1.0
                            print(f"[SPEECH] ✅ Verse: {detected_ref['reference']}")
                            await broadcast(json.dumps(detected_ref))
                            last_detected_ref = ref_key
                    else:
                        # Quote matching across all alternatives if no direct ref found
                        best_results = None
                        best_score = 0.0
                        for alt_text in alternatives:
                            if not alt_text or len(alt_text) <= 8:
                                continue
                            results = search_quote(conn, alt_text, active_translation, 5)
                            if results and results[0]["score"] > best_score:
                                best_score = results[0]["score"]
                                best_results = results
                        if best_results:
                            top = best_results[0]
                            ref_key = top["reference"]
                            # Lower thresholds for noisy halls
                            auto_threshold = 0.75 if final else 0.85
                            if top["score"] >= auto_threshold:
                                if ref_key == last_detected_ref:
                                    print(f"[SPEECH] ⏭ Already displayed {ref_key}, skipping duplicate")
                                else:
                                    top["type"]       = "verse_detected"
                                    top["source"]     = "quote"
                                    top["confidence"] = top["score"]
                                    print(f"[SPEECH] ✅ Auto-display ({top['score']*100:.0f}%): {top['reference']}")
                                    await broadcast(json.dumps(top))
                                    last_detected_ref = ref_key
                            elif top["score"] >= 0.15:
                                print(f"[SPEECH] 📝 Candidates ({len(best_results)}): top={top['score']*100:.0f}%")
                                await broadcast(json.dumps({"type": "candidates", "candidates": best_results}))

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
    "i said": "Isaiah", "i say": "Isaiah",
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
    "thess": "1 Thessalonians", "thessalonians": "1 Thessalonians",
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

# Common mishearings of book names from accents/diction (browser speech API)
BOOK_MISHEARINGS = {
    "some": "Psalms", "sum": "Psalms", "sums": "Psalms", "palms": "Psalms",
    "psalm": "Psalms", "salm": "Psalms", "sam": "Psalms", "song": "Psalms",
    "solms": "Psalms", "psalms": "Psalms",
    "jean": "John", "june": "John", "joan": "John", "don": "John",
    "mathew": "Matthew", "matthews": "Matthew", "matthew's": "Matthew",
    "loop": "Luke", "look": "Luke", "luck": "Luke",
    "mac": "Mark", "march": "Mark",
    "romance": "Romans", "roman": "Romans",
    "jeans": "Genesis", "generous": "Genesis",
    "exit": "Exodus", "exiles": "Exodus",
    "proverb": "Proverbs", "proverbial": "Proverbs",
    "i say": "Isaiah", "i said": "Isaiah", "a zaya": "Isaiah", "isiah": "Isaiah",
    "jerry maya": "Jeremiah", "jeremy": "Jeremiah",
    "daniels": "Daniel", "denial": "Daniel",
    "osea": "Hosea", "jose": "Hosea", "hose": "Hosea",
    "reservation": "Revelation", "revelations": "Revelation",
    "fill": "Philippians", "philippines": "Philippians", "filipinos": "Philippians",
    "collisions": "Colossians", "galoshes": "Galatians", "glaciers": "Galatians",
    "if he sins": "Ephesians", "officians": "Ephesians",
    "acts": "Acts", "axe": "Acts", "ax": "Acts",
    "jute": "Jude", "dude": "Jude",
    "aim": "Amos", "famous": "Amos",
    "jobe": "Job", "jobs": "Job",
    "ruth's": "Ruth", "root": "Ruth", "roof": "Ruth",
    "esta": "Esther", "easter": "Esther",
    "hebrew": "Hebrews", "hebrews'": "Hebrews",
    "titles": "Titus", "tightest": "Titus",
    "peters": "1 Peter", "pizza": "1 Peter",
    "numbers": "Numbers", "number": "Numbers",
    "do to run a me": "Deuteronomy", "due to run": "Deuteronomy",
}

_ALL_BOOK_KEYS = None
def fuzzy_book_name(raw):
    """Infer a book from a misheard word when chapter+verse context is present.
    Uses a mishearing dictionary first, then fuzzy string similarity against
    canonical names and aliases."""
    global _ALL_BOOK_KEYS
    key = raw.lower().strip()
    if not key or key.isdigit():
        return None
    # Known mishearing?
    if key in BOOK_MISHEARINGS:
        return BOOK_MISHEARINGS[key]
    # Numbered prefix e.g. "1 pizza" -> try tail against mishearings
    mnum = re.match(r'^([123])\s+(.+)$', key)
    if mnum and mnum.group(2) in BOOK_MISHEARINGS:
        base = BOOK_MISHEARINGS[mnum.group(2)]
        numbered = f"{mnum.group(1)} {base}"
        if numbered in CANONICAL_BOOKS:
            return numbered
        return base
    # Fuzzy similarity against canonical names and aliases
    if _ALL_BOOK_KEYS is None:
        _ALL_BOOK_KEYS = {c.lower(): c for c in CANONICAL_BOOKS}
        for alias, canon in BOOK_ALIASES.items():
            if len(alias) >= 4:  # short abbreviations fuzzy-match too easily
                _ALL_BOOK_KEYS.setdefault(alias, canon)
    matches = difflib.get_close_matches(key, _ALL_BOOK_KEYS.keys(), n=1, cutoff=0.75)
    if matches:
        return _ALL_BOOK_KEYS[matches[0]]
    return None

def detect_verse_ref(text):
    """Detect a Bible verse reference from spoken or typed text."""
    t = normalize_speech_text(text).strip()
    # Normalize spoken ordinals
    t = re.sub(r'\bfirst\b', '1', t)
    t = re.sub(r'\bsecond\b', '2', t)
    t = re.sub(r'\bthird\b', '3', t)
    # Normalize "verse X" -> :X
    t = re.sub(r'\bverse\s+', ':', t)
    # Normalize colon with surrounding spaces — "1 : 1" -> "1:1"
    t = re.sub(r'\s*:\s*', ':', t)
    # Collapse multiple spaces
    t = re.sub(r'  +', ' ', t)

    # Single-chapter books that have no chapter number when spoken
    SINGLE_CHAPTER_BOOKS = {'obadiah', 'philemon', 'jude', '2 john', '3 john', 'ii john', 'iii john'}

    # Pattern 0: explicit "Book chapter N" with NO verse — project verse 1
    m0 = re.search(r'((?:[123]\s)?[a-z]+(?:\s(?:of\s)?[a-z]+)?)\s+chapter\s+(\d+)(?!\s*[:\d])', t)
    if m0:
        book = resolve_book_name(m0.group(1).strip())
        if book:
            return book, int(m0.group(2)), 1

    # Strip the chapter keyword now that explicit chapter-only was handled
    t = re.sub(r'\bchapter\s+', '', t)

    # Pattern 1: "Book Chapter:Verse" with space — e.g. "John 3:16", "1 Corinthians 13:4"
    m = re.search(r'((?:[123]\s)?[a-z]+(?:\s(?:of\s)?[a-z]+)?)\s+(\d+):(\d+)', t)
    # Pattern 2: "BookChapter:Verse" no space — e.g. "exo1:1", "gen1:1", "1cor13:4"
    if not m:
        m = re.search(r'((?:[123])?[a-z]+)(\d+):(\d+)', t)
    # Pattern 3: spoken "book chapter verse" — e.g. "genesis 1 1"
    if not m:
        m = re.search(r'((?:[123]\s)?[a-z]+(?:\s(?:of\s)?[a-z]+)?)\s+(\d+)\s+(\d+)', t)

    if m:
        raw_book = m.group(1).strip()
        chapter  = int(m.group(2))
        verse    = int(m.group(3))
        book = resolve_book_name(raw_book)
        if book:
            return book, chapter, verse
        # Chapter+verse present is a strong signal this IS a reference —
        # infer the book from mishearings/accents (e.g. "some 23:1" -> Psalms)
        book = fuzzy_book_name(raw_book)
        if book:
            print(f"[DETECT] 🔊 Fuzzy book: '{raw_book}' -> {book}")
            return book, chapter, verse
        # Multi-word capture may include leading noise ("and he said some 23:1")
        # — retry with just the last word before the numbers
        last_word = raw_book.split()[-1]
        if last_word != raw_book:
            book = resolve_book_name(last_word) or fuzzy_book_name(last_word)
            if book:
                print(f"[DETECT] 🔊 Fuzzy book (last word): '{last_word}' -> {book}")
                return book, chapter, verse

    # Pattern 4: single-chapter book "Book :Verse" or "Book verse N" (no chapter spoken)
    m4 = re.search(r'((?:[123]\s)?[a-z]+)\s*:(\d+)', t)
    if m4:
        raw_book = m4.group(1).strip()
        if raw_book in SINGLE_CHAPTER_BOOKS:
            book = resolve_book_name(raw_book)
            if book:
                return book, 1, int(m4.group(2))

    return None

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
    print(f"  Model:    {MODEL} {'(Whisper model found)' if os.path.exists(MODEL) else '(Whisper model not bundled — using Vosk offline speech recognition)'}")
    print(f"  Web UI:   http://localhost:{HTTP_PORT}")
    print(f"  WS:       ws://localhost:{WS_PORT}")
    print("=" * 56)

    # Free ports from any previous run
    free_ports()

    # HTTP in background thread
    t = threading.Thread(target=run_http, daemon=True)
    t.start()
    print(f"[HTTP] Serving on http://localhost:{HTTP_PORT}")

    # Capture the asyncio loop for Vosk to schedule broadcasts from its thread
    global main_loop
    main_loop = asyncio.get_running_loop()

    # Start Vosk offline speech recognition worker in a background thread
    vosk_thread = threading.Thread(target=vosk_worker, daemon=True)
    vosk_thread.start()

    # WebSocket server
    async with websockets.serve(handle_client, "0.0.0.0", WS_PORT, reuse_address=True):
        print(f"[WS]   Listening on ws://localhost:{WS_PORT}")
        print()
        print(">>> Open http://localhost:8080 in your browser <<<")
        print()

        print("[INFO] Using Vosk offline speech recognition")

        # Run forever
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
