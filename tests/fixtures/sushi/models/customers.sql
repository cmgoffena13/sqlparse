MODEL (
  name sushi.customers,
  kind FULL
);

SELECT
  customer_id,
  status
FROM raw.customers
