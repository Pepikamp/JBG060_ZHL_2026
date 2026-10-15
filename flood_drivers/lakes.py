"""Robust reader for the Lake Victoria / Kyoga altimetry text files (hydroweb format).

The course loader keeps only lines that start with a hard-coded list of satellite missions and then drops
every row with any missing value, which in practice throws away everything after 2002. Here a line counts
as data if it has >= 15 fields and an 8-digit date (YYYYMMDD) in field 3; only the height must be valid.
"""
import re

import numpy as np
import pandas as pd

BAD = {"999.99", "99.999", "9999.99", "9999.999", "99999.999"}


def read_altimetry_txt(path):
    rows = []
    with open(path, "r", encoding="latin-1") as f:
        for line in f:
            t = line.split()
            if len(t) >= 15 and re.fullmatch(r"\d{8}", t[2]):
                rows.append((t[0], t[2], t[14], t[5]))
    df = pd.DataFrame(rows, columns=["mission", "date", "height_egm2008", "height_wrt_ref"])
    if df.empty:
        raise ValueError(f"no data lines recognised in {path}")
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    for c in ("height_egm2008", "height_wrt_ref"):
        df[c] = pd.to_numeric(df[c].where(~df[c].isin(BAD)), errors="coerce")
    df = df.dropna(subset=["date", "height_egm2008"]).set_index("date").sort_index()
    print(f"    {path.name}: {len(df)} rows {df.index.min().date()}..{df.index.max().date()}")
    print("    rows per mission:", df["mission"].value_counts().to_dict())
    return df
