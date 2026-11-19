MODEL (
  name sushi.customer_orders,
  kind FULL
);

SELECT
  customers.customer_id AS customer_id,
  customers.status AS status,
  orders.order_id AS order_id
FROM sushi.customers AS customers
JOIN sushi.orders AS orders
  ON customers.customer_id = orders.customer_id
WHERE customers.status = 'active'
GROUP BY
  customers.customer_id,
  customers.status,
  orders.order_id
