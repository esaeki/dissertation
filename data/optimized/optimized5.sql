SELECT o_custkey, order_cnt
FROM (
  SELECT o_custkey, COUNT(*) AS order_cnt
  FROM `saeki_dissertation.orders`
  GROUP BY o_custkey
)
WHERE order_cnt > 5
