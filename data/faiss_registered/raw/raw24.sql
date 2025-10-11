SELECT o_orderkey, o_custkey,
ROW_NUMBER() OVER (PARTITION BY o_custkey ORDER BY o_orderdate DESC) AS rn
FROM `saeki_dissertation.orders`
WHERE o_orderdate >= DATE '1995-01-01'
