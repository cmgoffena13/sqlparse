MODEL (
  name marketing.checkout,
  kind FULL
);

WITH marketing_views AS (
  SELECT DISTINCT
    b.id,
    DATE(b.event_date_et) AS event_date_et
  FROM marketing.page_views AS b
  LEFT JOIN marketing.first_purchase AS fp
    ON DATE(b.event_date_et) = DATE(fp.event_date_et)
)
SELECT
  id,
  event_date_et
FROM marketing_views
