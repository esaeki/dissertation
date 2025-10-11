SELECT ps_suppkey, COUNT(*) AS cnt
FROM `saeki_dissertation.partsupp`
WHERE ps_supplycost NOT BETWEEN 50 AND 150
GROUP BY ps_suppkey
ORDER BY cnt DESC
