SELECT o.o_orderdate, SUM(l.l_extendedprice) AS total_price
FROM `saeki_dissertation.orders` o
JOIN `saeki_dissertation.lineitem` l
ON o.o_orderkey = l.l_orderkey
GROUP BY o.o_orderdate
