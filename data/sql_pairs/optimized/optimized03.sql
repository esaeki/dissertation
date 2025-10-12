SELECT n_name, COUNT(*) AS cnt
FROM `saeki_dissertation.nation`
WHERE n_name IN ('JAPAN','CHINA','INDIA')
GROUP BY n_name
