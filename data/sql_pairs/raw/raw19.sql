SELECT
  COUNT(CASE WHEN l_discount < 0.05 THEN 1 END) AS small_discount,
  COUNT(CASE WHEN l_discount >= 0.05 THEN 1 END) AS large_discount
FROM
  `saeki_dissertation.lineitem`
