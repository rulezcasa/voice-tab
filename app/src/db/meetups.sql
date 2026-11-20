-- Meetup tables + planning columns. Run right AFTER schema.sql (schema.sql recreates people/expenses,
-- so the ALTERs below always apply to fresh tables). Person 1 may fold this into schema.sql instead.
-- Statements are separated by semicolons at line end; keep semicolons out of comments.

DROP TABLE IF EXISTS meetup_votes;
DROP TABLE IF EXISTS meetup_options;
DROP TABLE IF EXISTS meetups;
DROP TABLE IF EXISTS venues;
DROP TABLE IF EXISTS availability;

-- Private planning profile. Only src/core/people/personal_agent.py reads these columns.
ALTER TABLE people ADD COLUMN home_lat DOUBLE;
ALTER TABLE people ADD COLUMN home_lng DOUBLE;
ALTER TABLE people ADD COLUMN meetup_budget DECIMAL(10,2);
ALTER TABLE people ADD COLUMN max_radius_mi DOUBLE;
ALTER TABLE people ADD COLUMN max_travel_min INT;
ALTER TABLE people ADD COLUMN travel_mode VARCHAR(10);
ALTER TABLE people ADD COLUMN interests JSON;

-- Shared expenses at a confirmed meetup point to it (NULL = not at a meetup).
ALTER TABLE expenses ADD COLUMN meetup_id BIGINT NULL;

-- Private busy blocks (local time). busy_label is never read by the planner or the agent.
CREATE TABLE availability (
  id         BIGINT AUTO_INCREMENT PRIMARY KEY,
  person_id  BIGINT NOT NULL,
  starts_at  DATETIME NOT NULL,
  ends_at    DATETIME NOT NULL,
  busy_label VARCHAR(100)
);

CREATE TABLE venues (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  name        VARCHAR(120) NOT NULL,
  kind        VARCHAR(40) NOT NULL,          -- bowling, cafe, ramen, park, escape_room, bar, ...
  lat         DOUBLE NOT NULL,
  lng         DOUBLE NOT NULL,
  price_pp    DECIMAL(10,2) NOT NULL DEFAULT 0,
  parking     DECIMAL(10,2) NOT NULL DEFAULT 0,
  indoor      BOOLEAN NOT NULL DEFAULT TRUE,
  description VARCHAR(255),
  embedding   VECTOR(1024)                   -- bge-m3 of "name · kind · description"
);

CREATE TABLE meetups (
  id         BIGINT AUTO_INCREMENT PRIMARY KEY,
  group_id   BIGINT NOT NULL,
  title      VARCHAR(120),
  status     VARCHAR(20) NOT NULL DEFAULT 'voting',   -- voting | agreed | confirmed | cancelled
  venue_id   BIGINT NULL,
  starts_at  DATETIME NULL,
  ends_at    DATETIME NULL,
  created_at DATETIME(6) DEFAULT NOW(6)
);

CREATE TABLE meetup_options (
  meetup_id  BIGINT NOT NULL,
  option_no  INT NOT NULL,
  venue_id   BIGINT NOT NULL,
  starts_at  DATETIME NOT NULL,
  ends_at    DATETIME NOT NULL,
  per_person JSON,
  weather    JSON,
  score      DOUBLE,
  why        VARCHAR(500),
  PRIMARY KEY (meetup_id, option_no)
);

CREATE TABLE meetup_votes (
  meetup_id  BIGINT NOT NULL,
  person_id  BIGINT NOT NULL,
  option_no  INT NOT NULL,
  PRIMARY KEY (meetup_id, person_id)
);
