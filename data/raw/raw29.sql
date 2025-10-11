WITH agg AS ( 
SELECT 
l_returnflag, 
l_linestatus, 
l_quantity, 
l_discount 
FROM 
`saeki_dissertation.lineitem` 
) 
SELECT 
l_returnflag, 
l_linestatus, 
SUM(l_quantity) AS sum_qty, 
SUM(l_discount) / COUNT(*) AS avg_discount, 
COUNT(*) AS cnt 
FROM 
agg 
GROUP BY 
l_returnflag, 
l_linestatus 
ORDER BY 
l_returnflag, 
l_linestatus
