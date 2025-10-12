SELECT DISTINCT c_custkey
FROM (
  SELECT c_custkey FROM `saeki_dissertation.customer`
  UNION ALL
  SELECT c_custkey FROM `saeki_dissertation.customer`
);
