MODEL (
  name sushi.customer_status,
  kind FULL,
  description 'Nested CTE chain over raw customers'
);

WITH base AS (
  SELECT
    customer_id,
    status
  FROM raw.customers
),
filtered AS (
  SELECT
    customer_id,
    status
  FROM base
  WHERE status = 'active'
)
SELECT
  customer_id,
  status
FROM filtered
