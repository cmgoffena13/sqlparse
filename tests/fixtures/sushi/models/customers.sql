MODEL (
  name sushi.customers,
  kind FULL
);

JINJA_QUERY_BEGIN;
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
  {{ cents_to_dollars('customer_id') }} AS amount,
  status
FROM CTE
JINJA_END;
