SELECT o_orderkey, o_custkey
FROM `saeki_dissertation.orders`
WHERE o_orderdate >= DATE '1995-01-01'
QUALIFY ROW_NUMBER() OVER (PARTITION BY o_custkey ORDER BY o_orderdate DESC) = 1
