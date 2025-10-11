SELECT c.c_custkey
FROM `saeki_dissertation.customer` c
WHERE EXISTS (
  SELECT 1
  FROM `saeki_dissertation.orders` o
  WHERE o.o_custkey = c.c_custkey
)
