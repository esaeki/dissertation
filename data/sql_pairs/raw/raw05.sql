SELECT o_custkey, COUNT(*) AS order_cnt
FROM `saeki_dissertation.orders`
GROUP BY o_custkey
HAVING COUNT(*) > 5
