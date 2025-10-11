SELECT COUNT(*) AS cnt
FROM `saeki_dissertation.lineitem`
WHERE l_receiptdate >= DATE '1994-01-01'
  AND l_receiptdate <  DATE '1995-01-01';
