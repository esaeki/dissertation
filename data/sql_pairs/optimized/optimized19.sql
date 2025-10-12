SELECT
  SUM(IF(l_discount < 0.05, 1, 0)) AS small_discount,
  SUM(IF(l_discount >= 0.05, 1, 0)) AS large_discount
FROM
  `saeki_dissertation.lineitem`
