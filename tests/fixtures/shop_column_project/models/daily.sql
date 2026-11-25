MODEL (
  name shop.daily,
  kind FULL
);

SELECT
  event_date_et,
  customer_id
FROM shop.orders_clean;
