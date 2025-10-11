SELECT o_orderdate, COUNT(*) AS cnt
FROM `saeki_dissertation.orders`
WHERE CAST(o_orderdate AS STRING) LIKE '1993%'
GROUP BY o_orderdate
