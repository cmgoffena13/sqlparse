MODEL (
  name sushi.customers,
  kind FULL,
  audits [not_null_customer_id]
);

JINJA_QUERY_BEGIN;
WITH CTE AS (
  SELECT
    s.customer_id,
    o.customer_id,
    s.status,
    o.amount_cents
  FROM raw.customers AS s
  JOIN raw.orders AS o
    ON s.customer_id = o.customer_id
)
SELECT
  customer_id,
  {{ cents_to_dollars('amount_cents') }} AS amount,
  status
FROM CTE
JINJA_END;
