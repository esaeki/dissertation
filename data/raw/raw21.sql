SELECT
  o_orderpriority,
  COUNT(*) AS order_count
FROM
  `saeki_dissertation.orders`
GROUP BY
  o_orderpriority
HAVING
  COUNT(*) > 10
