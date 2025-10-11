SELECT SUM(x.order_cnt) AS total_orders
FROM (
  SELECT o_custkey, COUNT(*) AS order_cnt
  FROM `saeki_dissertation.orders`
  GROUP BY o_custkey
) AS x
