MODEL (
  name sushi.customers,
  kind FULL,
  audits [not_null_customer_id],
  description 'Customer grain with order amounts'
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
  customer_id, -- Customer identifier
  {{ cents_to_dollars('amount_cents') }} AS amount, /* Order amount in dollars */
  status -- Customer status
FROM CTE
JINJA_END;
