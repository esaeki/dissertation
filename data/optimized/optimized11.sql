WITH customer_filtered AS (
  SELECT c_custkey
  FROM `saeki_dissertation.customer`
  WHERE c_acctbal > 0
)
SELECT COUNT(*) AS cnt
FROM `saeki_dissertation.orders` o
JOIN customer_filtered c
ON o.o_custkey = c.c_custkey
