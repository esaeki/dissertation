SELECT
  n.n_name AS nation,
  EXTRACT(YEAR FROM o.o_orderdate) AS o_year,
  SUM(l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity) AS sum_profit
FROM
  `saeki_dissertation.lineitem` AS l
JOIN `saeki_dissertation.orders`    AS o  ON o.o_orderkey   = l.l_orderkey
JOIN `saeki_dissertation.partsupp`  AS ps ON ps.ps_partkey  = l.l_partkey
                                         AND ps.ps_suppkey  = l.l_suppkey
JOIN `saeki_dissertation.part`      AS p  ON p.p_partkey    = l.l_partkey
JOIN `saeki_dissertation.supplier`  AS s  ON s.s_suppkey    = l.l_suppkey
JOIN `saeki_dissertation.nation`    AS n  ON n.n_nationkey  = s.s_nationkey
WHERE
  p.p_name LIKE '%green%'
GROUP BY
  nation, o_year
ORDER BY
  nation, o_year;
