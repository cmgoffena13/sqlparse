MODEL (
  name fake.subscriptions,
  kind FULL,
  grain subscription_id
);

WITH subscription_details AS (
  SELECT
    1 AS subscription_id,
    10.0 AS amount,
    TRUE AS cancel_at_period_end,
    'active' AS current_status,
    'a@example.com' AS email,
    'u1' AS userId
), j_agg AS (
  SELECT
    email,
    userId,
    ARRAY_AGG(
      STRUCT(
        subscription_id,
        amount,
        cancel_at_period_end,
        current_status
      )
    ) AS All_Subscriptions
  FROM subscription_details
  GROUP BY
    email,
    userId
)
SELECT
  j.email,
  j.userId,
  j.All_Subscriptions
FROM j_agg AS j;
