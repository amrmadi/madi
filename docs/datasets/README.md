# ElderLife AI — Datasets

> Status: **index + template.** This folder documents every public research
> dataset the project has considered, uses, or plans to use.
> Each dataset has its own file; the index below is the entry point.

This document exists because a dataset is a **dependency with consequences**, and
the consequences are easy to forget. Which sensor? Which licence? Was it split
by *person* or by *row*? What happens if the archive is re-downloaded next year?
A dataset that is not written down becomes an undocumented assumption, and an
undocumented assumption in a graduation project is usually wrong.

So the rule is simple: **a dataset is documented here BEFORE it is downloaded or
used.** The file is written first, the download comes second, and the file is
updated with what actually happened.

---

## 1. The rules these documents exist to enforce

These come from [CONTRIBUTING.md](../../CONTRIBUTING.md#project-rules-you-must-follow)
and are repeated here because they decide what a dataset document must contain.

1. **Public research data is kept strictly separate from application user
   records.** Research volunteers and ElderLife AI residents are different
   people, and their records must never be joined. The database enforces this
   with separate `dataset_registry` / `dataset_files` tables that have no
   foreign key to `elderly_profiles` or `users` — see
   [erd.md](../erd.md).
2. **Datasets are git-ignored and never committed.** They live under
   `data/raw/` and `data/processed/`, both of which `.gitignore` excludes. Only
   the *documentation* is in this repository.
3. **A result derived from a research dataset is flagged `is_simulated: true`.**
   Data recorded from unrelated volunteers is not a measurement of a resident,
   so the API must never be able to present it as one. The rule is enforced in
   code in `ai/base.py` (`_BaseResult.is_simulated`) and covered by tests.
4. **Trained model artefacts are git-ignored too.** A model can always be
   recreated by re-running training; a 232 MB archive cannot be recreated by
   memory alone, which is why the *source URL* and *size* are recorded here and
   why a *checksum* is required. Where the checksum is not yet known, the field
   says **"To verify"** — it is never invented, and filling it in is part of
   the checklist above, not an optional extra.
5. **No dataset is described as "used" unless it was actually downloaded and
   read by code.**

---

## 2. Index

| Dataset | File | Status | One-line status |
|---|---|---|---|
| **SisFall** | [sisfall.md](sisfall.md) | 🟩 Downloaded & used | Fall-detection model is **trained** on it; the archive is git-ignored, the model file is git-ignored. |
| **UP-Fall** | [up-fall.md](up-fall.md) | ⛔ Considered & rejected | **Not downloaded, not used.** Full distribution is ~812 GB — impractical here; kept only as a decision record. |
| **UCI HAR** | [uci-har.md](uci-har.md) | 🟨 Planned | **Not downloaded, not used.** The intended dataset for activity recognition (task T1). |
| **CASAS** | [casas.md](casas.md) | 🟨 Planned | **Not downloaded, not used.** The intended dataset for behavioural analysis (task T2). |

No other dataset is in scope. If someone proposes a fourth one, it gets a file
in this folder **before** it is downloaded.

### Where each dataset is used (or will be)

| Dataset | Consumed by | Code path |
|---|---|---|
| SisFall | fall detection | `ai/fall_detection/` (preprocess → train → predictor) — **built and trained** |
| UCI HAR | activity recognition | `ai/activity_recognition/` — **placeholder only** (`__init__.py` + `README.md`); no `preprocess.py` / `train.py` / `predictor.py` yet |
| CASAS | behavioural analysis | `ai/behavioral_analysis/` — **placeholder only** (`__init__.py` + `README.md`); no `preprocess.py` / `train.py` / `predictor.py` yet |
| UP-Fall | — | **nothing**. No model uses it. |

The dataset↔predictor mapping is also recorded in code, in
`ai/registry.py` (`PLANNED_DATASETS`), so the API can state a model's
provenance without reading this documentation at runtime.

---

## 3. Template — required fields for every dataset document

Copy this section into a new file in this folder and fill in **every** row.
If a field is not yet known, write **"To verify"** — never leave it blank and
never guess a number. A blank field reads as "nothing to say"; "To verify"
reads as "someone must check this", which is the truth.

| # | Field | What to write |
|---|---|---|
| 1 | **Name** | The dataset's own name, and any short form used in the code. |
| 2 | **Source URL** | The canonical download page, and the exact URL the archive was fetched from. |
| 3 | **Citation** | The canonical citation, with authors, title, venue, and year. |
| 4 | **Licence** | The licence the publisher states, who must be contacted to confirm it, and whether redistribution is allowed. |
| 5 | **Version / date** | The release or dataset version and its date, so "the latest" is never ambiguous. |
| 6 | **Size** | The archive size in bytes, and where that number came from. |
| 7 | **Checksum** | SHA-256 of the downloaded archive, with the command used to compute it. **Never invent a checksum.** |
| 8 | **Format** | Container (zip/tar), inner layout, file naming convention, and the encoding. |
| 9 | **Sensors / features** | What was measured, the sampling rate, the units, and the raw representation. |
| 10 | **Labels** | How a label is encoded, what the class names are, and where the label comes from (file name, annotation file, video, …). |
| 11 | **Preprocessing** | The exact conversion, windowing, feature extraction, and normalisation steps — in the order the code performs them. |
| 12 | **Split** | How train/test is divided. **By subject, never by row**, and the seed if it is randomised. |
| 13 | **Limitations** | Class imbalance, population coverage, lab-vs-field gap, and anything that makes a result weaker than it looks. |
| 14 | **Local location** | The path inside the working tree where the archive lives, and confirmation that it is git-ignored. |
| 15 | **Used by** | Which model/predictor consumes it, and which API endpoints expose the result. |
| 16 | **Honesty notes** | Which results are flagged `is_simulated: true`, and what a reader must not conclude from them. |

### Checklist before a dataset is downloaded

- [ ] The file for this dataset exists in `docs/datasets/` and every field above
      is filled in or explicitly marked **"To verify"**.
- [ ] The licence is confirmed with the publisher, and the confirmation is
      written down here.
- [ ] The download URL and the expected size are recorded, so a corrupt
      download is detected rather than silently used.
- [ ] The destination path is inside `data/raw/` and is covered by
      `.gitignore`.
- [ ] `dataset_registry` (if the dataset is registered in the database) has
      `is_downloaded`, `is_processed` and `is_used_for_training` set to the
      truth — all three default to `false`.

### Checklist before a dataset is used to train a model

- [ ] The split is **by subject**, and the subject lists are explicit in the code.
- [ ] The scaler / normaliser is fitted on the **training** rows only.
- [ ] The measured metrics — including the disappointing ones — are written
      next to the model, and any result that rests on a single subject says so.
- [ ] The model artefact is git-ignored, and the API reports
      `is_ready: false` when it is absent.
- [ ] Every result derived from the dataset is flagged `is_simulated: true`.

---

## 4. What is not done yet

- **Two of the four datasets have not been downloaded** (UCI HAR, CASAS), and
  one was deliberately rejected (UP-Fall). Only SisFall exists on disk, and it
  is not committed to this repository.
- **No document here reports a metric that was not measured.** Where a number
  would be needed but is not known yet, the field says **"To verify"**.
- **The `data/` folder is not part of this repository.** It is git-ignored, so a
  fresh clone has no `data/raw/`, no `data/processed/`, and no archives.
