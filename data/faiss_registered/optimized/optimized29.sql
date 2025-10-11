SELECT
l_returnflag,
l_linestatus,
SUM(l_quantity) AS sum_qty,
AVG(l_discount) AS avg_discount,
COUNT(*) AS cnt
FROM
`saeki_dissertation.lineitem`
GROUP BY
l_returnflag,
l_linestatus
ORDER BY
l_returnflag,
l_linestatus
