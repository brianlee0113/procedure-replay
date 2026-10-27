# ProcedureReplay evaluation (dev set)

Run 2026-10-27T10:02, timestamp tolerance ±5s, review runs 1,2,3, variant: default, headline: vote.

- **Detected 4/9  (target ≥5/6)**
- **False flags 0/2  (target 0/2)**
- Extra flags on flawed videos 3

| variant | detected | false flags | extra flags on flawed |
|---|---|---|---|
| run 1 | 4/9 | 0/2 | 3 |
| run 1 first pass | 4/9 | 0/2 | 6 |
| run 2 | 3/9 | 0/2 | 3 |
| run 2 first pass | 4/9 | 1/2 | 3 |
| run 3 | 5/9 | 0/2 | 3 |
| run 3 first pass | 6/9 | 1/2 | 4 |
| vote | 4/9 | 0/2 | 3 |
| vote first pass | 6/9 | 1/2 | 3 |

Per video:

| video | run 1 | run 1 first pass | run 2 | run 2 first pass | run 3 | run 3 first pass | vote | vote first pass |
|---|---|---|---|---|---|---|---|---|
| 22_u17_r03_c_02__swap_252.4-308.3_308.5-371.2 | detected | detected | detected | detected | detected | detected | detected | detected |
| 07_u16_r04_c_01__swap_21.7-36.5_42.4-45.4 | missed | missed | missed | missed | missed | missed | missed | missed |
| cc4d_22_24__swap_1506.6-1529.2_1536.6-1572.9 | missed | missed | detected | detected | detected | detected | detected | detected |
| 22_u15_r03_c_03 | clean | clean | clean | clean | clean | clean | clean | clean |
| 07_u17_r03_c_01 | clean | clean | clean | FALSE FLAG | clean | FALSE FLAG | clean | FALSE FLAG |
| 22_u15_r03_c_02__cut_72.5-81.9 | missed | missed | missed | missed | missed | missed | missed | missed |
| 22_u16_r03_c_02__cut_54.8-68.2 | missed | missed | missed | missed | missed | missed | missed | missed |
| 22_u01_r07_c_02__cut_97.2-112.8 | detected | detected | missed | missed | missed | detected | missed | detected |
| 07_u15_r04_c_01__cut_5.8-15.6 | missed | missed | missed | detected | detected | detected | missed | detected |
| 07_u02_r03_c_01__cut_2.7-14.9 | detected | detected | detected | detected | detected | detected | detected | detected |
| cc4d_22_24__cut_380.9-451.7 | detected | detected | missed | missed | detected | detected | detected | detected |

Headline (vote) details:

| video | task | injected | status | flags | extra | hit | note |
|---|---|---|---|---|---|---|---|
| 22_u17_r03_c_02__swap_252.4-308.3_308.5-371.2 | pc_repair | swap step 8,9 @ 252.4–371.2s | detected | 1 | 0 | out_of_order step 8 @ 317.0s |  |
| 07_u16_r04_c_01__swap_21.7-36.5_42.4-45.4 | drill_bit | swap step 3,4 @ 21.74–45.44s | missed | 2 | 2 |  |  |
| cc4d_22_24__swap_1506.6-1529.2_1536.6-1572.9 | home_cooking | swap step 10,12 @ 1506.63–1572.92s | detected | 1 | 0 | out_of_order step 12 @ 1537.0s |  |
| 22_u15_r03_c_03 | pc_repair | none | clean | 0 | 0 |  |  |
| 07_u17_r03_c_01 | drill_bit | none | clean | 0 | 0 |  |  |
| 22_u15_r03_c_02__cut_72.5-81.9 | pc_repair | cut step 5 @ 72.51s | missed | 1 | 1 |  |  |
| 22_u16_r03_c_02__cut_54.8-68.2 | pc_repair | cut step 6 @ 54.78s | missed | 0 | 0 |  |  |
| 22_u01_r07_c_02__cut_97.2-112.8 | pc_repair | cut step 2 @ 97.16s | missed | 0 | 0 |  |  |
| 07_u15_r04_c_01__cut_5.8-15.6 | drill_bit | cut step 2 @ 5.75s | missed | 0 | 0 |  |  |
| 07_u02_r03_c_01__cut_2.7-14.9 | drill_bit | cut step 1 @ 2.65s | detected | 1 | 0 | missing step 1 @ 3.0s |  |
| cc4d_22_24__cut_380.9-451.7 | home_cooking | cut step 6 @ 380.91s | detected | 1 | 0 | missing step 6 @ 413.0s |  |
