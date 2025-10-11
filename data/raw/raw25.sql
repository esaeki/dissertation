SELECT o_orderkey,
SUM(o_totalprice) OVER (PARTITION BY o_custkey) AS s1,
AVG(o_totalprice) OVER (PARTITION BY o_custkey) AS a1
FROM `saeki_dissertation.orders`
