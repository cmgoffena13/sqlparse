MODEL (
  name sushi.orders,
  kind INCREMENTAL_BY_TIME_RANGE (
    time_column order_id
  ),
  depends_on [raw.orders]
);

SELECT
  order_id,
  customer_id
FROM sushi.customers AS customers
JOIN raw.orders AS orders
  ON customers.customer_id = orders.customer_id
