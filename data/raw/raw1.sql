SELECT ps_suppkey, COUNT(*) AS cnt
FROM `saeki_dissertation.partsupp`
WHERE ps_supplycost < 50 OR ps_supplycost > 150
GROUP BY ps_suppkey
ORDER BY COUNT(*) DESC
