SELECT
  l_returnflag,
  SUM(IF(l_shipmode = 'AIR', 1, 0)) AS air_cnt
FROM `saeki_dissertation.lineitem`
GROUP BY l_returnflag
