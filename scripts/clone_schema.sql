-- clone_schema(source, dest): copy a fully-migrated tenant schema's *structure*.
--
-- Prototype for the suite's real cost: ~1.65s of CREATE SCHEMA + migrate_schemas
-- per tenant, about 1,479 times per run. The bet is that copying an
-- already-migrated schema is much cheaper than replaying every migration into
-- an empty one.
--
-- Structure only, no rows. A test wants an empty school, not a copy of one.
--
-- `CREATE TABLE ... (LIKE x INCLUDING ALL)` carries columns, types, NOT NULL,
-- defaults, CHECK constraints, primary keys, unique constraints, indexes,
-- comments, storage and generated columns. It does **not** carry:
--
--   * foreign keys      — added in a second pass, once every table exists, with
--                         intra-schema references repointed at `dest`;
--   * sequence identity — a `bigserial` column's default is
--                         `nextval('source.t_id_seq')`, and copying it verbatim
--                         would leave every cloned school drawing ids from the
--                         template's sequence. Repointed explicitly.
--
-- Index *names* are the known risk and the prototype measures it rather than
-- assuming: `INCLUDING INDEXES` regenerates names from the table name rather
-- than copying them, and this project has a test that reads index names out of
-- `information_schema`.

CREATE OR REPLACE FUNCTION clone_schema(source_schema text, dest_schema text)
RETURNS void AS $$
DECLARE
  r          record;
  new_default text;
BEGIN
  EXECUTE format('CREATE SCHEMA %I', dest_schema);

  -- 1. Sequences, bare. Values are irrelevant: a cloned schema starts empty, so
  --    every sequence starts where a freshly migrated one would.
  FOR r IN
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = source_schema AND c.relkind = 'S'
  LOOP
    EXECUTE format('CREATE SEQUENCE %I.%I', dest_schema, r.relname);
  END LOOP;

  -- 2. Tables, with everything LIKE will carry.
  FOR r IN
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = source_schema AND c.relkind = 'r'
    ORDER BY c.relname
  LOOP
    EXECUTE format(
      'CREATE TABLE %I.%I (LIKE %I.%I INCLUDING ALL)',
      dest_schema, r.relname, source_schema, r.relname
    );
  END LOOP;

  -- 3. Repoint sequence-backed defaults at this schema's own sequences.
  --    Without this every cloned school shares the template's id sequence —
  --    which would still *work*, and would quietly make ids globally unique
  --    across schools, hiding exactly the per-schema-sequence assumptions a
  --    tenant test is there to prove.
  FOR r IN
    SELECT c.relname AS tbl, a.attname AS col,
           pg_get_expr(d.adbin, d.adrelid) AS def
    FROM pg_attrdef d
    JOIN pg_class c      ON c.oid = d.adrelid
    JOIN pg_namespace n  ON n.oid = c.relnamespace
    JOIN pg_attribute a  ON a.attrelid = c.oid AND a.attnum = d.adnum
    WHERE n.nspname = dest_schema
      AND pg_get_expr(d.adbin, d.adrelid) LIKE 'nextval(%'
  LOOP
    new_default := replace(
      r.def,
      quote_ident(source_schema) || '.',
      quote_ident(dest_schema) || '.'
    );
    -- `pg_get_expr` omits quotes on a lower-case identifier, so try both forms.
    new_default := replace(new_default, source_schema || '.', dest_schema || '.');
    EXECUTE format(
      'ALTER TABLE %I.%I ALTER COLUMN %I SET DEFAULT %s',
      dest_schema, r.tbl, r.col, new_default
    );
  END LOOP;

  -- 4. Tie each sequence to its column, so DROP SCHEMA CASCADE and DROP TABLE
  --    behave the way they do on a migrated schema.
  FOR r IN
    SELECT c.relname AS tbl, a.attname AS col, s.relname AS seq
    FROM pg_class s
    JOIN pg_namespace n   ON n.oid = s.relnamespace
    JOIN pg_depend dep    ON dep.objid = s.oid AND dep.deptype = 'a'
    JOIN pg_class c       ON c.oid = dep.refobjid
    JOIN pg_attribute a   ON a.attrelid = c.oid AND a.attnum = dep.refobjsubid
    WHERE n.nspname = source_schema AND s.relkind = 'S'
  LOOP
    EXECUTE format(
      'ALTER SEQUENCE %I.%I OWNED BY %I.%I.%I',
      dest_schema, r.seq, dest_schema, r.tbl, r.col
    );
  END LOOP;

  -- 5. Foreign keys, last, because they need every table to exist. A reference
  --    into the *source* schema is rewritten to this one; a reference into
  --    `public` is left alone, which is what a shared table requires.
  FOR r IN
    SELECT c.relname AS tbl, con.conname AS name,
           pg_get_constraintdef(con.oid) AS def
    FROM pg_constraint con
    JOIN pg_class c     ON c.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = source_schema AND con.contype = 'f'
  LOOP
    EXECUTE format(
      'ALTER TABLE %I.%I ADD CONSTRAINT %I %s',
      dest_schema, r.tbl, r.name,
      replace(
        replace(r.def,
                ' REFERENCES ' || quote_ident(source_schema) || '.',
                ' REFERENCES ' || quote_ident(dest_schema) || '.'),
        ' REFERENCES ' || source_schema || '.',
        ' REFERENCES ' || dest_schema || '.'
      )
    );
  END LOOP;
END;
$$ LANGUAGE plpgsql;
