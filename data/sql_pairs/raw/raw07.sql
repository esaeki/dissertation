SELECT
  l_returnflag,
  COUNT(CASE WHEN l_shipmode = 'AIR' THEN 1 END) AS air_cnt
FROM `saeki_dissertation.lineitem`
GROUP BY l_returnflag
