SELECT o_orderkey, s1,
SAFE_DIVIDE(s1, c1) AS a1
FROM (
SELECT o_orderkey, o_custkey,
SUM(o_totalprice) OVER (PARTITION BY o_custkey) AS s1,
COUNT(o_totalprice) OVER (PARTITION BY o_custkey) AS c1
FROM `saeki_dissertation.orders`
)
