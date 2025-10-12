SELECT COUNT(*) AS cnt
FROM `saeki_dissertation.orders` o
JOIN (
  SELECT * FROM `saeki_dissertation.customer` WHERE c_acctbal > 0
) c
ON o.o_custkey = c.c_custkey
