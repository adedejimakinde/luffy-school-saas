-- clone_schema_v2(source, dest): as v1, but keeping every index and constraint
-- NAME.
--
-- v1 used `LIKE ... INCLUDING ALL` for everything, which is fast and wrong here.
-- Postgres regenerates index names from the table and column rather than copying
-- them, and it does the same for the indexes backing PRIMARY KEY and UNIQUE
-- constraints. So `one_card_per_student_per_release` comes out of a v1 clone as
-- `results_releasedcard_sheet_id_student_membership_id_version_key`.
--
-- That is not cosmetic in this repository. Constraint violations are asserted
-- **by name** in the results tests, precisely so that a bare `IntegrityError`
-- cannot pass for the constraint under test, and `NoIndexIsBuiltTwiceTests`
-- reads index names straight out of `information_schema`. A test database built
-- by v1 would fail those tests — and, worse, any test that caught an
-- `IntegrityError` without checking the name would keep passing while asserting
-- something different from what it says.
--
-- So v2 excludes indexes and constraints from LIKE and replays them from the
-- catalogue with their own names and definitions.

CREATE OR REPLACE FUNCTION clone_schema_v2(source_schema text, dest_schema text)
RETURNS void AS $$
DECLARE
  r           record;
  new_default text;
BEGIN
  EXECUTE format('CREATE SCHEMA %I', dest_schema);

  FOR r IN
    SELECT c.relname
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = source_schema AND c.relkind = 'S'
  LOOP
    EXECUTE format('CREATE SEQUENCE %I.%I', dest_schema, r.relname);
  END LOOP;

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

  -- `django_migrations` is the one table whose ROWS have to come along.
  -- Everything else is deliberately copied empty — a test wants a new school,
  -- not a copy of one — but this table is not data, it is the record of which
  -- migrations the schema has had. Cloned empty, the schema is structurally
  -- complete and yet reads as never migrated: the next `migrate_schemas` would
  -- try to apply all of them again and fail on tables that already exist. The
  -- sequence is moved with it so the next insert does not collide.
  IF EXISTS (
    SELECT 1 FROM pg_tables
    WHERE schemaname = source_schema AND tablename = 'django_migrations'
  ) THEN
    EXECUTE format(
      'INSERT INTO %I.django_migrations (id, app, name, applied) '
      'SELECT id, app, name, applied FROM %I.django_migrations',
      dest_schema, source_schema
    );
    EXECUTE format(
      'SELECT setval(pg_get_serial_sequence(''%I.django_migrations'', ''id''), '
      'COALESCE((SELECT max(id) FROM %I.django_migrations), 1))',
      dest_schema, dest_schema
    );
  END IF;

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
END;
$$ LANGUAGE plpgsql;
