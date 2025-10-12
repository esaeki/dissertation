SELECT
  100.00 * SUM(IF(p.p_type LIKE 'PROMO%', l.l_extendedprice * (1 - l.l_discount), 0)) / SUM(l.l_extendedprice * (1 - l.l_discount)) AS promo_revenue
FROM
  `saeki_dissertation.lineitem` l
JOIN
  `saeki_dissertation.part` p
  ON l.l_partkey = p.p_partkey
WHERE
  l.l_shipdate >= DATE '1995-09-01'
  AND l.l_shipdate < DATE '1995-10-01';
