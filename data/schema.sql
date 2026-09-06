-- entities: one row per distinct real-world thing
-- (paper, person, insight, repo, job, track_update, action_item)
CREATE TABLE IF NOT EXISTS entities (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  one_liner TEXT,
  summary TEXT,
  raw_url TEXT,
  tags TEXT,               -- json array
  extra TEXT,               -- json object, type-specific fields
  novelty_score REAL NOT NULL DEFAULT 0.5,
  first_seen_date TEXT NOT NULL,
  last_seen_date TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entities_rank ON entities (novelty_score DESC, last_seen_date DESC);
CREATE INDEX IF NOT EXISTS idx_entities_url ON entities (raw_url);
CREATE INDEX IF NOT EXISTS idx_entities_type_title ON entities (type, title);

-- mentions: every time an entity is referenced, across days/sections/documents
CREATE TABLE IF NOT EXISTS mentions (
  id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL REFERENCES entities(id),
  date TEXT NOT NULL,
  source_agent TEXT NOT NULL,   -- chatgpt | hermes
  source_section TEXT,
  context_snippet TEXT
);

CREATE INDEX IF NOT EXISTS idx_mentions_entity ON mentions (entity_id);
CREATE INDEX IF NOT EXISTS idx_mentions_date ON mentions (date);

-- todos: personal task tracker fed manually or from feed cards
CREATE TABLE IF NOT EXISTS todos (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  notes TEXT,
  source_entity_id TEXT REFERENCES entities(id),
  status TEXT NOT NULL DEFAULT 'added',   -- added | committed | done
  added_at TEXT NOT NULL,
  due_date TEXT,
  committed_at TEXT,
  done_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_todos_status ON todos (status);

CREATE TABLE IF NOT EXISTS entity_views (
  id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL REFERENCES entities(id),
  viewed_at TEXT NOT NULL,
  duration_ms INTEGER NOT NULL,
  context TEXT NOT NULL              -- 'card' | 'detail'
);

CREATE INDEX IF NOT EXISTS idx_entity_views_entity ON entity_views (entity_id);

CREATE TABLE IF NOT EXISTS entity_interactions (
  id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL REFERENCES entities(id),
  action TEXT NOT NULL,              -- 'open_detail' | 'open_source' | 'add_todo'
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entity_interactions_entity ON entity_interactions (entity_id);

CREATE TABLE IF NOT EXISTS todo_comments (
  id TEXT PRIMARY KEY,
  todo_id TEXT NOT NULL REFERENCES todos(id),
  body TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_todo_comments_todo ON todo_comments (todo_id);

CREATE TABLE IF NOT EXISTS weekly_summaries (
  id TEXT PRIMARY KEY,
  generated_at TEXT NOT NULL,
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  summary TEXT NOT NULL
);
