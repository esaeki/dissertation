SELECT
  COUNT(*) AS cnt
FROM (
  SELECT 1
  FROM `saeki_dissertation.lineitem`
  WHERE
    l_shipmode IN ('AIR', 'REG AIR')
    AND l_commitdate < l_receiptdate
    AND l_shipdate < l_commitdate
    AND l_receiptdate BETWEEN DATE '1994-01-01' AND DATE '1994-12-31'
)
