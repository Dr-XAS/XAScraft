# XAScraft — 三元素实测 demo

在 XAScraft 点击 **Load demo cases**：一次加入 3 个文件夹、9 条谱线。独立版默认选中 NiO transmission 并打开已保存的 EXAFS 拟合曲线、参数和告警；NiO 双模式数据仍默认勾选，便于切回谱线对比。

| 文件夹 | 数据 | 适合展示 |
| --- | --- | --- |
| Ni | NiO transmission + fluorescence，来自指定附件同一扫描 | 模式对比、独立归一化、XANES/EXAFS 差异 |
| Cu | Cu₂O、CuO，以及各自真实测得的 Cu foil | 氧化物与金属对比、实测参考关联 |
| Fe | FeO、Fe₃O₄、Fe₂O₃ | 氧化物近边与局域结构差异 |

`.dat` 是 energy_eV / mu 两列，可单独导入；`originals/` 保留仪器/XDI原文件。
NiO transmission = ln(I0/It)；fluorescence = NiKa ROI / I0。导出保留原生能量网格，没有平滑、对齐、重采样或截断。

`manifest.json` 记录来源、数据库 ID、列映射、原始文件和导出 SHA-256、初始处理参数。运行时不依赖数据库或网络。若使用独立 ZIP，其中 `XAScraft_three_element_demo.json` 可通过 Open project 导入并恢复三个文件夹。

注意：NiO 荧光未做额外死时间/自吸收校正；Cu 高 k 有共同窄特征，初始 FT kmax 为 11.5 Å⁻¹、AUTOBK kmax 为 12 Å⁻¹以保留完整 taper；Fe 的测量日期不同，没有应用额外能量校准。FT 峰位未经相移校正，不直接代表键长。

自动 v3 初筛受原生采样约束，综合分保持 unavailable，不通过插值或调整阈值补分。选择结合来源核实、曲线检查和实际处理结果。完整说明见仓库 `docs/curated-demo-cases.md`。

## NiO transmission 的 EXAFS 模型与拟合结果

选择 **NiO · transmission → EXAFS fitting**，可直接查看已保存的拟合结果，也可编辑预装的 Ni K-edge FEFF 模型。结构为 Bunsenite NiO（AMCSD 0011371）；`Ni/feff/` 保留 CIF、FEFF 输入、原始日志、5 条路径及模型/结果档案。

默认启用 Ni–O（R_eff 2.0842 Å，N=6）和 Ni–Ni（2.9475 Å，N=12），另有两条多重散射和一条外层 Ni–O 路径供选择。初始拟合范围为 k=3–11.5 Å⁻¹、R=1–3 Å、kweight=2。两个壳层分别使用 ΔR/σ²，共用 amplitude/ΔE0，加载时不会自动拟合。可选路径的固定 ΔR/σ² 仅为起点，启用前需检查参数与范围。

FEFF 原始半径告警与输入原子范围不一致，已完整保留在模型来源信息及 `feff.log`；未将其隐藏。模型只附加给 transmission，fluorescence 不变。

预存结果来自已经完成并检查的那次两壳层拟合：R-factor=1.58%、reduced χ²≈226，Ni–O=2.0724 Å、Ni–Ni=2.9608 Å。加载只恢复曲线、拟合参数、误差、相关性和历史，不重新优化。原始告警全部保留；`Demo review:` 告警补充高 reduced χ²、ΔE₀–键长相关性、未校准 S₀²/固定配位数及两壳层范围限制。编辑区保留原始起始值，实际拟合参数见结果报告。

保存并重新打开 JSON/PRJ 后结果仍在。原始输入指纹、计算时间和来源保留；处理参数改变而导致 χ(k) 改变时，旧结果会标记为过期，不会伪装成重新拟合的结果。
