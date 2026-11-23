MODEL (
  name sushi.union_cte,
  kind FULL
);

WITH cte AS (
  SELECT customer_id FROM raw.customers
  UNION ALL
  SELECT customer_id FROM raw.orders
)
SELECT customer_id
FROM cte
WHERE customer_id IS NOT NULL;
