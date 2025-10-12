SELECT l_returnflag, l_linestatus, COUNT(*) AS cnt
FROM (
  SELECT *
  FROM `saeki_dissertation.lineitem`
  WHERE l_shipdate >= DATE '1995-01-01'
) t
GROUP BY l_returnflag, l_linestatus;
