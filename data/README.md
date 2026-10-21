# Data directory

This directory holds the datasets and the files derived from them.

```
data/
    raw/        datasets exactly as they arrived (never edited)
    processed/  cleaned, joined, feature-ready copies
    sample/     small excerpts safe to commit and to use in demos
```

## Why the three subdirectories exist

The distinction is not cosmetic. A raw dataset is the evidence; a processed
copy is a claim derived from that evidence. Mixing them means a re-run of the
pipeline can silently change the thing you are comparing against, and there is
no way to prove afterwards what the original file actually contained.

| Directory     | May be committed? | May be edited? | Rule |
|---------------|------------------|----------------|------|
| `raw/`        | no                | never          | write-once; if a file is wrong, replace it and re-run the pipeline |
| `processed/`  | no                | yes            | always regenerated from `raw/`, never hand-edited |
| `sample/`     | yes               | yes            | small excerpts only; no resident data, no full datasets |

## What is in the repository today

Nothing. `raw/`, `processed/` and `sample/` contain only `.gitkeep` files so
that the directory structure survives a clone.

The `.gitignore` rules for this repository exclude the contents of
`data/raw/**` and `data/processed/**`:

```
data/raw/**
data/processed/**
```

`data/sample/**` is *not* excluded, because a small, deliberately anonymised
excerpt is exactly what a reviewer needs in order to run the pipeline.

## Rules for anything that does land here

1. **No resident data.** No file in this directory may contain data about a
   real, identifiable person. Demo data must be obviously synthetic.
2. **No personal data in a public dataset either.** A public research dataset
   still contains real volunteers; that is why the raw files are git-ignored
   even though the dataset itself is public. See
   `docs/datasets/` for the provenance of each one.
3. **Keep the raw copy.** If a download script is re-run, it must write to a
   new file rather than overwrite the old one, or the "raw" copy stops being
   raw.
4. **Record the provenance.** Any file added to `sample/` must say where it
   came from: the dataset name, the URL, the licence and the date it was
   taken. A file without provenance is not usable evidence.

## Why nothing is downloaded automatically

The AI package must stay importable with nothing installed and must not
reach the network at import time. `ai/base.py` and `ai/registry.py` therefore
report `is_ready: false` and `metrics: null` until a model has actually been
trained, and `python tools/verify_no_model_path.py` checks that they keep
reporting that honestly.

The same principle applies here: the datasets are documented in
`docs/datasets/` *before* they are downloaded, and the download is a
deliberate, manual step — not something a test run triggers.
