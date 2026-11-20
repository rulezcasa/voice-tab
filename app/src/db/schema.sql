-- Tab schema (SingleStore). Re-runnable: drops and recreates everything.
-- Statements are separated by semicolons at line end; keep semicolons out of comments.

DROP VIEW IF EXISTS balances;
DROP TABLE IF EXISTS audit_events;  -- removed table, dropped if an old database still has it
DROP TABLE IF EXISTS expense_shares;
DROP TABLE IF EXISTS expenses;
DROP TABLE IF EXISTS utterances;    -- removed table, dropped if an old database still has it
DROP TABLE IF EXISTS group_members;
DROP TABLE IF EXISTS groups_;
DROP TABLE IF EXISTS people;

-- ---------- Ledger ----------

CREATE TABLE people (
  id         BIGINT AUTO_INCREMENT PRIMARY KEY,
  name       VARCHAR(100) NOT NULL,
  is_me      BOOLEAN DEFAULT FALSE,          -- the account owner
  aliases    JSON,                           -- ["Nik"]
  embedding  VECTOR(1024)                    -- bge-m3 of name + aliases
);

CREATE TABLE groups_ (
  id         BIGINT AUTO_INCREMENT PRIMARY KEY,
  name       VARCHAR(100) NOT NULL,          -- "Apt 4B"
  aliases    JSON,                           -- ["roommates","roomies","flatmates"]
  embedding  VECTOR(1024)
);

CREATE TABLE group_members (
  group_id   BIGINT NOT NULL,
  person_id  BIGINT NOT NULL,
  PRIMARY KEY (group_id, person_id)
);

CREATE TABLE expenses (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  created_at    DATETIME(6) DEFAULT NOW(6),
  spent_on      DATE NOT NULL,
  amount        DECIMAL(10,2) NOT NULL,
  currency      CHAR(3) DEFAULT 'USD',
  description   VARCHAR(255),                -- the user's own words ("tomato")
  merchant      VARCHAR(120),
  category      VARCHAR(40),                 -- fixed list in src/core/expenses/categories.py, 'settlement' = repayment
  group_id      BIGINT NULL,                 -- NULL = personal
  status        VARCHAR(20) DEFAULT 'logged',-- logged | needs_clarification | failed
  is_demo       BOOLEAN DEFAULT FALSE,       -- seeded demo data
  embedding     VECTOR(1024),                -- bge-m3 of "description · category · merchant"
  FULLTEXT USING VERSION 2 (description, merchant)
);

-- Every expense has share rows, personal ones too (me: paid = owed = amount).
-- So "how much did I spend" = SUM(owed) for me, excluding settlements.
CREATE TABLE expense_shares (
  expense_id  BIGINT NOT NULL,
  person_id   BIGINT NOT NULL,
  paid        DECIMAL(10,2) NOT NULL DEFAULT 0,
  owed        DECIMAL(10,2) NOT NULL DEFAULT 0,
  PRIMARY KEY (expense_id, person_id)
);

-- Balances are computed, never stored. Positive = owed money, negative = owes.
-- Settlements are included on purpose: they bring balances back to 0.
CREATE VIEW balances AS
  SELECT s.person_id, p.name, SUM(s.paid - s.owed) AS net
  FROM expense_shares s JOIN people p ON p.id = s.person_id
  GROUP BY s.person_id, p.name;
