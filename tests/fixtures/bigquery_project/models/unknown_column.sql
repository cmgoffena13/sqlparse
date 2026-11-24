MODEL (
  name fake.unknown_column,
  kind FULL
);

SELECT
  p.product_id,
  p.missing_col
FROM fake.products AS p
