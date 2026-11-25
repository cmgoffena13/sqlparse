MODEL (
  name shop.orders_clean,
  kind FULL
);

SELECT
  id,
  user_id AS customer_id,
  event_date AS event_date_et,
  'order_placed' AS event,
  CASE
    WHEN event = 'order_placed' THEN event_data_article_section
    ELSE NULL
  END AS article_section
FROM ext_shop.orders
WHERE
  event = 'order_placed'
  AND event_date IS NOT NULL;
