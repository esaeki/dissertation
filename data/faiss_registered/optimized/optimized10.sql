WITH l_filtered AS (
  SELECT l_orderkey
  FROM `saeki_dissertation.lineitem`
  WHERE l_commitdate < l_receiptdate
)
SELECT o.o_orderpriority, COUNT(*) AS order_count
FROM `saeki_dissertation.orders` o
JOIN l_filtered l
  ON o.o_orderkey = l.l_orderkey
GROUP BY o.o_orderpriority
