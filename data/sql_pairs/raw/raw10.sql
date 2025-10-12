SELECT o.o_orderpriority, COUNT(*) AS order_count
FROM `saeki_dissertation.orders` o
JOIN `saeki_dissertation.lineitem` l
  ON o.o_orderkey = l.l_orderkey
WHERE l.l_commitdate < l.l_receiptdate
GROUP BY o.o_orderpriority
