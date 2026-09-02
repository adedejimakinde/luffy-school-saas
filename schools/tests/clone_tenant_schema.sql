-- clone_tenant_schema(source, dest): copy a migrated tenant schema, faithfully.
--
-- The suite's cost is not its assertions, it is `CREATE SCHEMA` plus
-- `migrate_schemas` once per test method — ~1.65s, about 1,479 times a run.
-- This copies an already-migrated schema instead, which is the same structure
-- for a fraction of the time.
--
-- ## Faithful is the whole requirement
--
-- A fast clone that is not the same schema is worth less than nothing: it makes
-- the suite quick and its guarantees imaginary. An earlier draft of this
-- function copied tables, indexes and constraints and stopped there. Against a
-- real migrated schema it produced **0 of 13 triggers, 0 of 13 functions and 0
-- seeded rows** — every `append_only` guarantee silently absent, every school
-- starting with no traits, no scale and no grade bands. Its own structural
-- check compared index and constraint names, so it reported success.
--
-- Four things therefore come across that a `LIKE` clone does not bring:
--
--   * **rows** — every table, not just `django_migrations`. The source is a
--     pristine freshly-migrated schema, so everything in it is exactly what a
--     new school starts with: the traits, the rating scale and the grade bands
--     that `results.0006` and `results.0015` seed. Copying wholesale rather
--     than naming those tables means a seed added next year arrives by itself.
--   * **sequence positions** — `django_migrations` had this alone before; every
--     sequence needs it, or the first insert into a seeded table collides.
--   * **functions**, then **triggers**, in that order. These are the
--     append-only rules. Missing, a test that asserts a released row cannot be
--     changed does not fail loudly — the write simply succeeds.
--   * **index and constraint NAMES.** `LIKE ... INCLUDING ALL` regenerates them
--     from table and column, so `one_card_per_student_per_release` comes back
--     as `results_releasedcard_sheet_id_student_membership_id_version_key`.
--     This repository asserts constraint violations by name, precisely so a
--     bare `IntegrityError` cannot pass for the constraint under test, and
--     `NoIndexIsBuiltTwiceTests` reads index names out of `information_schema`.
--
-- `schools/tests/test_tenant_template.py` compares a clone against a freshly
-- migrated schema on all of it and fails on any difference. That test is the
-- reason this function can be trusted; nothing else holds it.

CREATE OR REPLACE FUNCTION clone_tenant_schema(source_schema text, dest_schema text)
RETURNS void AS $$
DECLARE
  r           record;
  new_default text;
  saved_path  text;
BEGIN
  EXECUTE format('CREATE SCHEMA %I', dest_schema);

  -- Columns, types, NOT NULL, defaults, comments — but no indexes and no
  -- constraints, both of which are replayed by name below.
  FOR r IN
    SELECT c.relname
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = source_schema AND c.relkind = 'r'
    ORDER BY c.relname
  LOOP
    EXECUTE format(
      'CREATE TABLE %I.%I (LIKE %I.%I INCLUDING DEFAULTS INCLUDING GENERATED '
      'INCLUDING IDENTITY INCLUDING STORAGE INCLUDING COMMENTS)',
      dest_schema, r.relname, source_schema, r.relname
    );
  END LOOP;

  -- Any sequence the tables did not bring with them. Django's AutoField is an
  -- identity column on PostgreSQL, so `INCLUDING IDENTITY` above already made
  -- most of these and named them exactly as the source names them. Creating
  -- them ahead of the tables instead produced both: the manual
  -- `academics_term_id_seq` and, because that name was taken, an identity
  -- sequence called `academics_term_id_seq1` — 54 sequences against the
  -- source's 27. This loop is what remains for a plain `serial` or a sequence
  -- a migration made by hand.
  FOR r IN
    SELECT c.relname
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = source_schema AND c.relkind = 'S'
      AND NOT EXISTS (
        SELECT 1 FROM pg_class dc JOIN pg_namespace dn ON dn.oid = dc.relnamespace
        WHERE dn.nspname = dest_schema AND dc.relname = c.relname
      )
  LOOP
    EXECUTE format('CREATE SEQUENCE %I.%I', dest_schema, r.relname);
  END LOOP;

  -- Sequence-backed defaults, repointed at this schema's own sequences.
  FOR r IN
    SELECT c.relname AS tbl, a.attname AS col,
           pg_get_expr(d.adbin, d.adrelid) AS def
    FROM pg_attrdef d
    JOIN pg_class c     ON c.oid = d.adrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = d.adnum
    WHERE n.nspname = dest_schema
      AND pg_get_expr(d.adbin, d.adrelid) LIKE 'nextval(%'
  LOOP
    new_default := replace(r.def, quote_ident(source_schema) || '.',
                                  quote_ident(dest_schema) || '.');
    new_default := replace(new_default, source_schema || '.', dest_schema || '.');
    EXECUTE format('ALTER TABLE %I.%I ALTER COLUMN %I SET DEFAULT %s',
                   dest_schema, r.tbl, r.col, new_default);
  END LOOP;

  FOR r IN
    SELECT c.relname AS tbl, a.attname AS col, s.relname AS seq
    FROM pg_class s
    JOIN pg_namespace n ON n.oid = s.relnamespace
    JOIN pg_depend dep  ON dep.objid = s.oid AND dep.deptype = 'a'
    JOIN pg_class c     ON c.oid = dep.refobjid
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = dep.refobjsubid
    WHERE n.nspname = source_schema AND s.relkind = 'S'
  LOOP
    EXECUTE format('ALTER SEQUENCE %I.%I OWNED BY %I.%I.%I',
                   dest_schema, r.seq, dest_schema, r.tbl, r.col);
  END LOOP;

  -- Rows, before any constraint or trigger exists to have an opinion about
  -- them. `django_migrations` is not data but the record of which migrations
  -- this schema has had; cloned empty it would read as never migrated. The
  -- seeded tables are data, and a school is meant to start with them.
  FOR r IN
    SELECT c.relname
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = source_schema AND c.relkind = 'r'
    ORDER BY c.relname
  LOOP
    EXECUTE format('INSERT INTO %I.%I SELECT * FROM %I.%I',
                   dest_schema, r.relname, source_schema, r.relname);
  END LOOP;

  -- Every sequence's position, so the first insert after the clone does not
  -- collide with a seeded row.
  FOR r IN
    SELECT c.relname
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = source_schema AND c.relkind = 'S'
  LOOP
    EXECUTE format(
      'SELECT setval(%L, s.last_value, s.is_called) FROM %I.%I s',
      quote_ident(dest_schema) || '.' || quote_ident(r.relname),
      source_schema, r.relname
    );
  END LOOP;

  -- CHECK, then PRIMARY KEY and UNIQUE — by name. Ordered so that the unique
  -- indexes a foreign key may need exist before the foreign keys are added.
  FOR r IN
    SELECT c.relname AS tbl, con.conname AS name,
           pg_get_constraintdef(con.oid) AS def, con.contype
    FROM pg_constraint con
    JOIN pg_class c     ON c.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = source_schema AND con.contype IN ('c', 'p', 'u')
    ORDER BY CASE con.contype WHEN 'c' THEN 1 WHEN 'p' THEN 2 ELSE 3 END
  LOOP
    EXECUTE format('ALTER TABLE %I.%I ADD CONSTRAINT %I %s',
                   dest_schema, r.tbl, r.name, r.def);
  END LOOP;

  -- Indexes that do not back a constraint — the plain btrees Django's
  -- `db_index=True` and `Meta.indexes` produce. Those that do back one arrived
  -- with their constraint above and must not be built twice.
  FOR r IN
    SELECT i.indexname AS name, i.indexdef AS def
    FROM pg_indexes i
    WHERE i.schemaname = source_schema
      AND NOT EXISTS (
        SELECT 1
        FROM pg_constraint con
        JOIN pg_class ic ON ic.oid = con.conindid
        JOIN pg_namespace n ON n.oid = con.connamespace
        WHERE n.nspname = source_schema AND ic.relname = i.indexname
      )
  LOOP
    EXECUTE replace(r.def,
                    ' ON ' || quote_ident(source_schema) || '.',
                    ' ON ' || quote_ident(dest_schema) || '.');
  END LOOP;

  FOR r IN
    SELECT c.relname AS tbl, con.conname AS name,
           pg_get_constraintdef(con.oid) AS def
    FROM pg_constraint con
    JOIN pg_class c     ON c.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = source_schema AND con.contype = 'f'
  LOOP
    EXECUTE format('ALTER TABLE %I.%I ADD CONSTRAINT %I %s',
                   dest_schema, r.tbl, r.name,
                   replace(
                     replace(r.def,
                             ' REFERENCES ' || quote_ident(source_schema) || '.',
                             ' REFERENCES ' || quote_ident(dest_schema) || '.'),
                     ' REFERENCES ' || source_schema || '.',
                     ' REFERENCES ' || dest_schema || '.'));
  END LOOP;

  -- Functions before triggers, because a trigger names the function it runs.
  -- `pg_get_functiondef` qualifies the name it emits with the source schema;
  -- these bodies are unqualified and rely on `search_path`, but rewriting the
  -- whole definition covers any that are not.
  --
  -- `search_path` has to point at the new schema while they are created.
  -- `check_function_bodies` compiles a PL/pgSQL body at CREATE time and
  -- resolves the tables it names, and these bodies name them unqualified —
  -- `gradebook_score`, not `st_marys.gradebook_score` — exactly as the
  -- migration wrote them, because at run time django_tenants has already put
  -- the tenant on the path. Created from `public` they fail to compile with
  -- `relation "gradebook_score" does not exist`, which is a resolution failure
  -- rather than anything wrong with the function.
  saved_path := current_setting('search_path');
  PERFORM set_config('search_path', quote_ident(dest_schema) || ', public', true);

  FOR r IN
    SELECT pg_get_functiondef(p.oid) AS def
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = source_schema
  LOOP
    EXECUTE replace(r.def, quote_ident(source_schema) || '.',
                           quote_ident(dest_schema) || '.');
  END LOOP;

  -- The append-only rules themselves. `tgisinternal` excludes the triggers
  -- Postgres creates to enforce foreign keys, which arrived with the
  -- constraints above and would be built twice by name here.
  FOR r IN
    SELECT pg_get_triggerdef(t.oid) AS def
    FROM pg_trigger t
    JOIN pg_class c     ON c.oid = t.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = source_schema AND NOT t.tgisinternal
  LOOP
    EXECUTE replace(r.def, quote_ident(source_schema) || '.',
                           quote_ident(dest_schema) || '.');
  END LOOP;

  PERFORM set_config('search_path', saved_path, true);
END;
$$ LANGUAGE plpgsql;
