SELECT
  o_orderpriority,
  order_count
FROM (
  SELECT
    o_orderpriority,
    COUNT(*) AS order_count
  FROM `saeki_dissertation.orders`
  GROUP BY o_orderpriority
)
WHERE
  order_count > 10
