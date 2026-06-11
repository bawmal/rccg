use rusqlite::{Connection, Result, params};
use std::path::Path;

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Verse {
    pub id: i64,
    pub translation_id: i64,
    pub book_number: i64,
    pub book_name: String,
    pub chapter: i64,
    pub verse: i64,
    pub text: String,
}

impl Verse {
    pub fn reference(&self) -> String {
        format!("{} {}:{}", self.book_name, self.chapter, self.verse)
    }
}

#[derive(Debug)]
pub struct SearchResult {
    pub verse: Verse,
    pub score: f64,
}

pub fn open_db(path: &Path) -> Result<Connection, Box<dyn std::error::Error>> {
    let conn = Connection::open(path)?;
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")?;
    // Build FTS5 index if it doesn't exist
    conn.execute_batch("
        CREATE VIRTUAL TABLE IF NOT EXISTS verses_fts USING fts5(
            text,
            book_name UNINDEXED,
            chapter UNINDEXED,
            verse_num UNINDEXED,
            translation_abbr UNINDEXED,
            content=verses,
            content_rowid=id
        );
    ").ok(); // OK if already exists
    Ok(conn)
}

pub fn lookup_verse(conn: &Connection, reference: &str, translation: &str) -> Result<Option<Verse>> {
    // Parse "Book Chapter:Verse" e.g. "John 3:16" or "1 Corinthians 13:4"
    let parts: Vec<&str> = reference.rsplitn(2, ' ').collect();
    if parts.len() < 2 { return Ok(None); }
    let chapter_verse = parts[0];
    let book_part = parts[1];
    let cv: Vec<&str> = chapter_verse.splitn(2, ':').collect();
    if cv.len() < 2 { return Ok(None); }
    let chapter: i64 = cv[0].parse().unwrap_or(0);
    let verse_num: i64 = cv[1].parse().unwrap_or(0);
    if chapter == 0 || verse_num == 0 { return Ok(None); }

    let result = conn.query_row(
        "SELECT v.id, v.translation_id, v.book_number, v.book_name, v.chapter, v.verse, v.text
         FROM verses v
         JOIN translations t ON v.translation_id = t.id
         WHERE (LOWER(v.book_name) = LOWER(?1) OR LOWER(v.book_abbreviation) = LOWER(?1))
           AND v.chapter = ?2
           AND v.verse = ?3
           AND UPPER(t.abbreviation) = UPPER(?4)
         LIMIT 1",
        params![book_part, chapter, verse_num, translation],
        |row| Ok(Verse {
            id: row.get(0)?,
            translation_id: row.get(1)?,
            book_number: row.get(2)?,
            book_name: row.get(3)?,
            chapter: row.get(4)?,
            verse: row.get(5)?,
            text: row.get(6)?,
        }),
    );

    match result {
        Ok(v) => Ok(Some(v)),
        Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
        Err(e) => Err(e),
    }
}

pub fn search_verses(conn: &Connection, query: &str, translation: &str, limit: usize) -> Result<Vec<SearchResult>> {
    if query.split_whitespace().count() < 4 {
        return Ok(vec![]);
    }

    // Clean query for FTS - remove punctuation, use LIKE for portability
    let words: Vec<&str> = query.split_whitespace()
        .filter(|w| w.len() > 3)
        .take(6)
        .collect();

    if words.is_empty() {
        return Ok(vec![]);
    }

    // Build a LIKE query checking each significant word
    let like_conditions: Vec<String> = words.iter()
        .map(|w| format!("LOWER(v.text) LIKE LOWER('%{}%')", w.replace('\'', "''")))
        .collect();

    let sql = format!(
        "SELECT v.id, v.translation_id, v.book_number, v.book_name, v.chapter, v.verse, v.text,
                ({}) AS match_count
         FROM verses v
         JOIN translations t ON v.translation_id = t.id
         WHERE UPPER(t.abbreviation) = UPPER(?1)
           AND ({})
         ORDER BY match_count DESC
         LIMIT ?2",
        like_conditions.iter().map(|c| format!("CASE WHEN {} THEN 1 ELSE 0 END", c)).collect::<Vec<_>>().join(" + "),
        like_conditions.join(" OR ")
    );

    let mut stmt = conn.prepare(&sql)?;
    let total_words = words.len() as f64;

    let results = stmt.query_map(params![translation, limit as i64], |row| {
        let match_count: i64 = row.get(7)?;
        Ok(SearchResult {
            verse: Verse {
                id: row.get(0)?,
                translation_id: row.get(1)?,
                book_number: row.get(2)?,
                book_name: row.get(3)?,
                chapter: row.get(4)?,
                verse: row.get(5)?,
                text: row.get(6)?,
            },
            score: match_count as f64 / total_words,
        })
    })?
    .filter_map(|r| r.ok())
    .filter(|r| r.score > 0.3)
    .collect();

    Ok(results)
}

pub fn get_translations(conn: &Connection) -> Result<Vec<(String, String)>> {
    let mut stmt = conn.prepare("SELECT abbreviation, title FROM translations ORDER BY id")?;
    let results = stmt.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
    })?
    .filter_map(|r| r.ok())
    .collect();
    Ok(results)
}

pub fn get_verse_by_ref(conn: &Connection, book_name: &str, chapter: i64, verse: i64, translation: &str) -> Result<Option<Verse>> {
    let result = conn.query_row(
        "SELECT v.id, v.translation_id, v.book_number, v.book_name, v.chapter, v.verse, v.text
         FROM verses v
         JOIN translations t ON v.translation_id = t.id
         WHERE (LOWER(v.book_name) = LOWER(?1) OR LOWER(v.book_abbreviation) = LOWER(?1))
           AND v.chapter = ?2 AND v.verse = ?3
           AND UPPER(t.abbreviation) = UPPER(?4)
         LIMIT 1",
        params![book_name, chapter, verse, translation],
        |row| Ok(Verse {
            id: row.get(0)?,
            translation_id: row.get(1)?,
            book_number: row.get(2)?,
            book_name: row.get(3)?,
            chapter: row.get(4)?,
            verse: row.get(5)?,
            text: row.get(6)?,
        }),
    );
    match result {
        Ok(v) => Ok(Some(v)),
        Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
        Err(e) => Err(e),
    }
}
