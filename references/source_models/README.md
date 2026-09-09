# Finite-source rupture models — reference only

Published finite-source rupture models gathered for a handful of events.

**Not used by the showcase site.** The site draws a single schematic *surface
rupture trace* per event, taken from the USGS ComCat source model
(`scripts/import_reference_tables.py`): the along-strike extent of the USGS
finite-fault slip model where one exists, otherwise a magnitude-scaled line
through the epicentre along nodal plane 1. These files are kept as reference in
case a higher-fidelity model is wanted later.

| file | event | format / source |
|---|---|---|
| `s1995KOBEJA02SEKI.fsp.txt` | 1995 Kobe | SRCMOD FSP (Sekiguchi et al.) |
| `s1999CHICHI01JOHN.fsp.txt` | 1999 Chi-Chi | SRCMOD FSP (Johnson et al.) |
| `s2016KUMAMO02ASAN.fsp.txt` | 2016 Kumamoto mainshock | SRCMOD FSP (Asano & Iwata) |
| `s2018IBURIH01ASAN.fsp` | 2018 Hokkaido E. Iburi | SRCMOD FSP (Asano & Iwata) |
| `2016_KUMAMO_MAIN_02ASAN.mat` / `_FORE_01ASAN.mat` | 2016 Kumamoto main / foreshock | SRCMOD MATLAB |
| `2016_Meinong_sourcemodel.fig` | 2016 Meinong | MATLAB figure |
| `2018_Hualien_source_model_SJL.txt` | 2018 Hualien | Lee et al. |
| `2023_Turkey_source_model_M78.txt` / `_M75.txt` | 2023 Kahramanmaraş doublet | regional inversion |

`.fsp` = SRCMOD ASCII (header + subfault lat/lon/depth/slip/rake grid).
