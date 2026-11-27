MODEL (
  name sushi.macro_cte,
  kind VIEW
);

WITH classified AS (
  @classify_touches(touches, touch_id)
),
other AS (
  SELECT 1 AS x
)
SELECT *
FROM classified;
