MODEL (
  name fake.unnest_ids,
  kind FULL
);

SELECT
  i AS product_id,
  1 AS price
FROM UNNEST(GENERATE_ARRAY(1, 3)) AS i;
