WITH l_agg AS (
SELECT l_orderkey, SUM(l_extendedprice) AS sum_price
FROM `saeki_dissertation.lineitem`
GROUP BY l_orderkey
)
SELECT o.o_orderdate, SUM(l_agg.sum_price) AS total_price
FROM `saeki_dissertation.orders` o
JOIN l_agg
ON o.o_orderkey = l_agg.l_orderkey
GROUP BY o.o_orderdate
