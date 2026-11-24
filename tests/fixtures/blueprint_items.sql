MODEL (
  name @customer.bp_items,
  kind FULL,
  blueprints (
    (customer := bp1, field_a := 1),
    (customer := bp2, field_a := 2)
  )
);

SELECT
  @field_a AS value;
