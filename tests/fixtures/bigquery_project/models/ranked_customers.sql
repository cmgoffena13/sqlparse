MODEL (
  name fake.ranked_customers,
  kind FULL
);

WITH customers AS (
  SELECT
    1 AS customer_id,
    'active' AS status
)
SELECT
  customer_id,
  status
FROM customers
QUALIFY
  ROW_NUMBER() OVER (
    PARTITION BY customers.customer_id
    ORDER BY customers.status
  ) = 1;
