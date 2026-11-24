MODEL (
  name sushi.union_from_cte,
  kind FULL
);

WITH base AS (
  SELECT
    customer_id
  FROM raw.customers
), combined AS (
  SELECT
    customer_id AS id
  FROM base
  UNION ALL
  SELECT
    customer_id AS id
  FROM base
)
SELECT
  c.id
FROM combined AS c
