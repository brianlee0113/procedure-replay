# ProcedureReplay evaluation (test set)

Run 2026-10-27T01:59, timestamp tolerance ±5s.

- **Detected 3/6  (target ≥5/6)**
- **False flags 1/2  (target 0/2)**

| video | task | injected | status | flags | hit | note |
|---|---|---|---|---|---|---|
| 22_u14_r03_c_01__cut_99.9-116.6 | pc_repair | cut step 3 @ 99.93s | detected | 2 | missing step 3 @ 121.0s |  |
| 22_u15_r03_c_01__cut_59.4-66.3 | pc_repair | cut step 5 @ 59.41s | missed | 0 |  |  |
| 22_u16_r03_c_01__swap_137.1-157.8_161.2-237.9 | pc_repair | swap step 7,8 @ 137.06–237.87s | detected | 1 | out_of_order step 7 @ 217.5s |  |
| 07_u14_r04_c_01__cut_8.2-16.7 | drill_bit | cut step 2 @ 8.21s | missed | 0 |  |  |
| cc4d_22_6__cut_244.8-284.2 | home_cooking | cut step 7 @ 244.83s | detected | 2 | missing step 7 @ 271.0s |  |
| cc4d_22_13__swap_250.4-280.4_320.3-343.5 | home_cooking | swap step 7,8 @ 250.44–343.5s | missed | 0 |  |  |
| 22_u01_r07_c_01 | pc_repair | none | FALSE FLAG | 1 |  |  |
| cc4d_22_4 | home_cooking | none | clean | 0 |  |  |
