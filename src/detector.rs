use regex::Regex;

static TRANSLATIONS: &[&str] = &[
    "KJV", "NIV", "ESV", "NASB", "NKJV", "NLT", "AMP",
    "MSG", "CSB", "RSV", "NRSV", "CEV", "GNT", "NET",
];

static BOOK_ALIASES: &[(&str, &str)] = &[
    // Old Testament
    ("genesis", "Genesis"), ("gen", "Genesis"),
    ("exodus", "Exodus"), ("exo", "Exodus"), ("exod", "Exodus"),
    ("leviticus", "Leviticus"), ("lev", "Leviticus"),
    ("numbers", "Numbers"), ("num", "Numbers"),
    ("deuteronomy", "Deuteronomy"), ("deut", "Deuteronomy"), ("deu", "Deuteronomy"),
    ("joshua", "Joshua"), ("josh", "Joshua"),
    ("judges", "Judges"), ("judg", "Judges"),
    ("ruth", "Ruth"),
    ("1 samuel", "1 Samuel"), ("1samuel", "1 Samuel"), ("1sam", "1 Samuel"),
    ("2 samuel", "2 Samuel"), ("2samuel", "2 Samuel"), ("2sam", "2 Samuel"),
    ("1 kings", "1 Kings"), ("1kings", "1 Kings"), ("1kgs", "1 Kings"),
    ("2 kings", "2 Kings"), ("2kings", "2 Kings"), ("2kgs", "2 Kings"),
    ("1 chronicles", "1 Chronicles"), ("1chron", "1 Chronicles"), ("1chr", "1 Chronicles"),
    ("2 chronicles", "2 Chronicles"), ("2chron", "2 Chronicles"), ("2chr", "2 Chronicles"),
    ("ezra", "Ezra"),
    ("nehemiah", "Nehemiah"), ("neh", "Nehemiah"),
    ("esther", "Esther"), ("esth", "Esther"),
    ("job", "Job"),
    ("psalms", "Psalms"), ("psalm", "Psalms"), ("psa", "Psalms"), ("ps", "Psalms"),
    ("proverbs", "Proverbs"), ("prov", "Proverbs"), ("pro", "Proverbs"),
    ("ecclesiastes", "Ecclesiastes"), ("eccl", "Ecclesiastes"), ("ecc", "Ecclesiastes"),
    ("song of solomon", "Song of Solomon"), ("song of songs", "Song of Solomon"), ("sos", "Song of Solomon"), ("song", "Song of Solomon"),
    ("isaiah", "Isaiah"), ("isa", "Isaiah"),
    ("jeremiah", "Jeremiah"), ("jer", "Jeremiah"),
    ("lamentations", "Lamentations"), ("lam", "Lamentations"),
    ("ezekiel", "Ezekiel"), ("ezek", "Ezekiel"), ("eze", "Ezekiel"),
    ("daniel", "Daniel"), ("dan", "Daniel"),
    ("hosea", "Hosea"), ("hos", "Hosea"),
    ("joel", "Joel"),
    ("amos", "Amos"),
    ("obadiah", "Obadiah"), ("obad", "Obadiah"),
    ("jonah", "Jonah"), ("jon", "Jonah"),
    ("micah", "Micah"), ("mic", "Micah"),
    ("nahum", "Nahum"), ("nah", "Nahum"),
    ("habakkuk", "Habakkuk"), ("hab", "Habakkuk"),
    ("zephaniah", "Zephaniah"), ("zeph", "Zephaniah"),
    ("haggai", "Haggai"), ("hag", "Haggai"),
    ("zechariah", "Zechariah"), ("zech", "Zechariah"),
    ("malachi", "Malachi"), ("mal", "Malachi"),
    // New Testament
    ("matthew", "Matthew"), ("matt", "Matthew"), ("mat", "Matthew"),
    ("mark", "Mark"), ("mar", "Mark"),
    ("luke", "Luke"), ("luk", "Luke"),
    ("john", "John"), ("joh", "John"),
    ("acts", "Acts"), ("act", "Acts"),
    ("romans", "Romans"), ("rom", "Romans"),
    ("1 corinthians", "1 Corinthians"), ("1corinthians", "1 Corinthians"), ("1cor", "1 Corinthians"),
    ("2 corinthians", "2 Corinthians"), ("2corinthians", "2 Corinthians"), ("2cor", "2 Corinthians"),
    ("galatians", "Galatians"), ("gal", "Galatians"),
    ("ephesians", "Ephesians"), ("eph", "Ephesians"),
    ("philippians", "Philippians"), ("phil", "Philippians"), ("php", "Philippians"),
    ("colossians", "Colossians"), ("col", "Colossians"),
    ("1 thessalonians", "1 Thessalonians"), ("1thess", "1 Thessalonians"), ("1th", "1 Thessalonians"),
    ("2 thessalonians", "2 Thessalonians"), ("2thess", "2 Thessalonians"), ("2th", "2 Thessalonians"),
    ("1 timothy", "1 Timothy"), ("1tim", "1 Timothy"), ("1ti", "1 Timothy"),
    ("2 timothy", "2 Timothy"), ("2tim", "2 Timothy"), ("2ti", "2 Timothy"),
    ("titus", "Titus"), ("tit", "Titus"),
    ("philemon", "Philemon"), ("phlm", "Philemon"),
    ("hebrews", "Hebrews"), ("heb", "Hebrews"),
    ("james", "James"), ("jas", "James"),
    ("1 peter", "1 Peter"), ("1pet", "1 Peter"), ("1pe", "1 Peter"),
    ("2 peter", "2 Peter"), ("2pet", "2 Peter"), ("2pe", "2 Peter"),
    ("1 john", "1 John"), ("1joh", "1 John"), ("1jn", "1 John"),
    ("2 john", "2 John"), ("2joh", "2 John"), ("2jn", "2 John"),
    ("3 john", "3 John"), ("3joh", "3 John"), ("3jn", "3 John"),
    ("jude", "Jude"),
    ("revelation", "Revelation"), ("rev", "Revelation"),
];

/// Detects a verse reference in spoken text.
/// Handles: "1 Chronicles 22:12", "first chronicles 22 12", "John 3 16", "Prov 31 verse 10"
pub fn detect_verse_reference(text: &str) -> Option<String> {
    let lower = text.to_lowercase();

    // Normalize spoken ordinals and verbal cues
    let normalized = lower
        .replace("first ", "1 ")
        .replace("second ", "2 ")
        .replace("third ", "3 ")
        .replace(" verse ", ":")
        .replace(" verses ", ":")
        .replace(" chapter ", " ")
        .replace(" colon ", ":")
        .replace(" and ", " ")
        // Spoken numbers → digits
        .replace("twenty ", "20 ")
        .replace("twenty-one ", "21 ")
        .replace("twenty-two ", "22 ")
        .replace("twenty-three ", "23 ")
        .replace("twenty-four ", "24 ")
        .replace("twenty-five ", "25 ")
        .replace("thirty ", "30 ")
        .replace("thirty-one ", "31 ")
        .replace("forty ", "40 ")
        .replace("fifty ", "50 ")
        .replace("sixty ", "60 ")
        .replace("seventy ", "70 ")
        .replace("eighty ", "80 ")
        .replace("ninety ", "90 ")
        .replace("one ", "1 ")
        .replace("two ", "2 ")
        .replace("three ", "3 ")
        .replace("four ", "4 ")
        .replace("five ", "5 ")
        .replace("six ", "6 ")
        .replace("seven ", "7 ")
        .replace("eight ", "8 ")
        .replace("nine ", "9 ")
        .replace("ten ", "10 ")
        .replace("eleven ", "11 ")
        .replace("twelve ", "12 ")
        .replace("thirteen ", "13 ")
        .replace("fourteen ", "14 ")
        .replace("fifteen ", "15 ")
        .replace("sixteen ", "16 ")
        .replace("seventeen ", "17 ")
        .replace("eighteen ", "18 ")
        .replace("nineteen ", "19 ");

    // Try longest possible book name match first (up to 4 words for "song of solomon" etc)
    // Pattern: optional digit prefix + 1-4 word book + chapter + optional colon/space + verse
    let re = Regex::new(
        r"(?i)((?:[123]\s)?(?:[a-z]+(?:\s(?:of\s)?[a-z]+){0,2}))\s+(\d{1,3})[:\s](\d{1,3})(?:\s|$|[^a-z])"
    ).ok()?;

    // Collect all candidate matches and try each
    for cap in re.captures_iter(&normalized) {
        let raw_book = cap[1].trim().to_lowercase();
        let chapter: i64 = cap[2].parse().unwrap_or(0);
        let verse: i64 = cap[3].parse().unwrap_or(0);
        if chapter == 0 || verse == 0 { continue; }

        // Try exact match, then progressively shorter book name substrings
        if let Some(canonical) = resolve_book(&raw_book) {
            return Some(format!("{} {}:{}", canonical, chapter, verse));
        }
        // Try just the last word(s) if multi-word didn't match
        let words: Vec<&str> = raw_book.split_whitespace().collect();
        for start in 1..words.len() {
            let sub = words[start..].join(" ");
            if let Some(canonical) = resolve_book(&sub) {
                return Some(format!("{} {}:{}", canonical, chapter, verse));
            }
        }
    }

    None
}

/// Detects a translation name spoken in text ("...in NKJV", "...NKJV version", "...King James")
pub fn detect_translation(text: &str) -> Option<String> {
    let upper = text.to_uppercase();

    for t in TRANSLATIONS {
        // Match exact abbreviation with word boundaries
        let pattern = format!(r"(?:^|\s|,){}(?:\s|$|,|\.)", t);
        if let Ok(re) = Regex::new(&pattern) {
            if re.is_match(&upper) {
                return Some(t.to_string());
            }
        }
    }

    // Spoken full names
    let lower = text.to_lowercase();
    if lower.contains("king james") { return Some("KJV".to_string()); }
    if lower.contains("new king james") { return Some("NKJV".to_string()); }
    if lower.contains("new international") { return Some("NIV".to_string()); }
    if lower.contains("english standard") { return Some("ESV".to_string()); }
    if lower.contains("new living") { return Some("NLT".to_string()); }
    if lower.contains("amplified") { return Some("AMP".to_string()); }
    if lower.contains("new american standard") { return Some("NASB".to_string()); }

    None
}

fn resolve_book(raw: &str) -> Option<&'static str> {
    let cleaned = raw.trim().to_lowercase();
    if cleaned.is_empty() { return None; }

    // Exact match first
    for (alias, canonical) in BOOK_ALIASES {
        if cleaned == *alias {
            return Some(canonical);
        }
    }
    // Prefix match (min 3 chars, alias must be at least as long as input)
    for (alias, canonical) in BOOK_ALIASES {
        if cleaned.len() >= 3 && alias.len() >= cleaned.len() && alias.starts_with(cleaned.as_str()) {
            return Some(canonical);
        }
    }
    // Suffix match for cases where whisper adds a leading word (e.g. "the chronicles")
    for (alias, canonical) in BOOK_ALIASES {
        if cleaned.len() >= 4 && cleaned.ends_with(*alias) {
            return Some(canonical);
        }
    }
    None
}
