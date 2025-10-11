SELECT
  l_orderkey,
  SUM(l_extendedprice * (1 - l_discount)) AS revenue,
  o_orderdate,
  o_shippriority
FROM
  `saeki_dissertation.customer` c
JOIN
  `saeki_dissertation.orders` o
  ON c.c_custkey = o.o_custkey
JOIN
  `saeki_dissertation.lineitem` l
  ON l.l_orderkey = o.o_orderkey
WHERE
  c.c_mktsegment = 'BUILDING'
  AND o.o_orderdate < DATE '1995-03-15'
  AND l.l_shipdate > DATE '1995-03-15'
GROUP BY
  l_orderkey, o_orderdate, o_shippriority
ORDER BY
  revenue DESC, o_orderdate
LIMIT 10;
