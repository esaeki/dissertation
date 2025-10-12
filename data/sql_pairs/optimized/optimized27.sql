SELECT
l_returnflag,
l_linestatus,
SUM(l_quantity) AS sum_qty,
SAFE_DIVIDE(SUM(l_discount), COUNT(l_discount)) AS avg_discount
FROM
`saeki_dissertation.lineitem`
GROUP BY
l_returnflag, l_linestatus
