WITH filtered_lineitem AS (
  SELECT l_orderkey
  FROM `saeki_dissertation.lineitem`
  WHERE l_commitdate < l_receiptdate
),
aggregated AS (
  SELECT
    o.o_orderpriority,
    COUNT(*) AS order_count
  FROM
    `saeki_dissertation.orders` o
  JOIN
    filtered_lineitem l
  ON
    o.o_orderkey = l.l_orderkey
  GROUP BY
    o.o_orderpriority
)

SELECT *
FROM aggregated
WHERE order_count > 100
