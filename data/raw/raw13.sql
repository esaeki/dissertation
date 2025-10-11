SELECT COUNT(*) AS cnt
FROM `saeki_dissertation.lineitem`
WHERE l_receiptdate BETWEEN DATE '1994-01-01' AND DATE '1994-12-31';
