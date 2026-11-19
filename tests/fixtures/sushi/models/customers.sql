MODEL (
  name sushi.customers,
  kind FULL
);

WITH CTE AS (
  SELECT
    s.customer_id,
    o.customer_id,
    s.status
  FROM raw.customers AS s
  JOIN raw.orders AS o
    ON s.customer_id = o.customer_id
)
SELECT
  customer_id,
  status
FROM CTE
