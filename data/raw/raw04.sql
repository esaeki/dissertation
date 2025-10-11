SELECT COUNT(*) AS cnt
FROM `saeki_dissertation.lineitem`
WHERE EXTRACT(YEAR FROM l_shipdate) = 1994
