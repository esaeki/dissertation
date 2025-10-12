SELECT c.c_custkey
FROM `saeki_dissertation.customer` c
JOIN `saeki_dissertation.orders` o
  ON c.c_custkey = o.o_custkey
GROUP BY c.c_custkey
