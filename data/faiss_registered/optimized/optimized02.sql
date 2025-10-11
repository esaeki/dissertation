SELECT o_orderdate, COUNT(*) AS cnt
FROM `saeki_dissertation.orders`
WHERE o_orderdate >= DATE '1993-01-01'
  AND o_orderdate <  DATE '1994-01-01'
GROUP BY o_orderdate
