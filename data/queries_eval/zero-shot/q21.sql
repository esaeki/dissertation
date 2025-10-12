SELECT
  s.s_name,
  COUNT(*) AS numwait
FROM
  `saeki_dissertation.supplier` AS s
JOIN `saeki_dissertation.lineitem` AS l1
  ON s.s_suppkey = l1.l_suppkey
JOIN `saeki_dissertation.orders` AS o
  ON o.o_orderkey = l1.l_orderkey
JOIN `saeki_dissertation.nation` AS n
  ON n.n_nationkey = s.s_nationkey
WHERE
  o.o_orderstatus = 'F'
  AND l1.l_receiptdate > l1.l_commitdate
  AND EXISTS (
    SELECT 1
    FROM `saeki_dissertation.lineitem` AS l2
    WHERE l2.l_orderkey = l1.l_orderkey
      AND l2.l_suppkey <> l1.l_suppkey
  )
  AND NOT EXISTS (
    SELECT 1
    FROM `saeki_dissertation.lineitem` AS l3
    WHERE l3.l_orderkey = l1.l_orderkey
      AND l3.l_suppkey <> l1.l_suppkey
      AND l3.l_receiptdate > l3.l_commitdate
  )
  AND n.n_name = 'SAUDI ARABIA'
GROUP BY
  s.s_name
ORDER BY
  numwait DESC, s.s_name
LIMIT 100;
