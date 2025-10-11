SELECT
SUM(l_discounted_price) AS revenue
FROM (
SELECT
l_extendedprice * l_discount AS l_discounted_price
FROM
`saeki_dissertation.lineitem`
WHERE
l_shipdate >= DATE '1994-01-01'
AND l_shipdate < DATE '1995-01-01'
)
