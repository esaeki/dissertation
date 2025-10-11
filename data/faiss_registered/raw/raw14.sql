SELECT COUNT(*) AS cnt
FROM `saeki_dissertation.customer`
WHERE CASE WHEN c_mktsegment = 'AUTOMOBILE' THEN TRUE ELSE FALSE END;
