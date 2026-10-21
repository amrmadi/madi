# SisFall — Falls Detection Dataset

> Status: **downloaded and used.** The fall-detection model in
> `ai/fall_detection/` is trained on this dataset. The archive and the trained
> model file are **git-ignored** and are **not** in this repository.

This document exists so that anyone re-running the training pipeline knows
exactly what the data is, where it came from, and how it was interpreted. The
technical details below are the ones the code actually implements, taken from
`ai/fall_detection/preprocess.py` — if this document and that module ever
disagree, **the module is the contract** and this file is the bug.

---

## 1. Identity

| Field | Value |
|---|---|
| **Name** | SisFall: Falls Detection Dataset |
| **Kind** | Publicly released research dataset (falls + activities of daily living) |
| **Canonical citation** | *"SisFall: Falls Detection Dataset"*, 2014 — the research group behind the dataset. **To verify** the exact group name and the exact form of the citation from the `Readme.txt` shipped inside the archive; the project's rule is to write *verify* rather than invent a name. |
| **Peer-reviewed description** | Sucerquia, A.; López, J. D.; Vargas-Bonilla, J. F. — *"SisFall: A Fall and Movement Dataset"*, **Sensors**, 2017. This paper describes the dataset and the same research group; it is the citable source if the 2014 release note cannot be retrieved. |
| **Source URL** | Canonical dataset page: `http://projects.sil.si/index.php/en/sisfall` — **To verify**: the exact URL used for the copy that was downloaded here, and the current download link (the page has moved between hosts over the years). |
| **Licence** | **To be confirmed with the authors before any redistribution.** See §2. |
| **Version / date** | The 2014 public release, as cited above. The archive carries no version file; treat "2014 release" as the version identifier. |
| **Size** | **232,407,821 bytes** — the size recorded by the download run in the top-level [README](../../README.md#datasets) ("SisFall has been downloaded (232,407,821 bytes, integrity verified)"). |
| **Checksum (SHA-256)** | **To verify.** No checksum is recorded anywhere in this repository yet. Compute it before re-downloading and write it here: <br>`Get-FileHash .\data\raw\SisFall_dataset.zip -Algorithm SHA256` |
| **Used by** | `ai/fall_detection/` (`preprocess.py` → training script → `predictor.py`), exposed through `ai/registry.py` as the `fall_detection` predictor. |

> **Working-tree note.** The archive itself is not here, by design — the whole
> `data/` tree is git-ignored and does not exist in a fresh clone. The training
> script `ai/fall_detection/train.py` and the module's own
> `ai/fall_detection/README.md` **are** present, so the commands in §9 run
> against real code; they simply have no data to read until the archive is
> downloaded to `data/raw/SisFall_dataset.zip`.

---

## 2. Licence — read before redistributing anything

**The licence must be confirmed with the authors before this dataset (or any
part of it) is redistributed, republished, or shared outside this project.**

What is known:

- The dataset is offered publicly for research use.
- The exact redistribution terms are **not stated in this repository**, and the
  dataset page has moved hosts over the years, so the terms that apply today
  have not been captured here.

What is done regardless of the outcome:

- **The archive is never committed to this repository.** `data/raw/**` is
  excluded by `.gitignore`, so the archive cannot leak into a commit by
  accident.
- **The trained model is never committed either.** Model artefacts under
  `ai/**/models/` are excluded by `.gitignore`, so the model cannot be used to
  reconstruct the dataset either.
- Anyone who needs the data downloads it from the publisher and confirms the
  terms themselves.

---

## 3. Local location

| What | Path | Committed? |
|---|---|---|
| Downloaded archive | `data/raw/SisFall_dataset.zip` | ❌ **No** — `data/raw/**` is git-ignored |
| Extracted recordings | `data/raw/SisFall_dataset/` (created by unzipping; never edit the originals) | ❌ **No** |
| Derived feature tables | `data/processed/` | ❌ **No** — `data/processed/**` is git-ignored |
| Trained model artefacts | `ai/models/fall_detection/` | ❌ **No** — `ai/**/models/` is git-ignored |

`data/raw/` is the **write-once** area: the downloaded archive is never edited
in place, so the checksum in §1 stays meaningful.

---

## 4. Format

| Property | Value |
|---|---|
| Container | ZIP (`SisFall_dataset.zip`) |
| Inner layout | Everything under a single top-level `SisFall_dataset/` folder. The archive also contains a `Readme.txt` describing the collection, and AppleDouble `._*` entries, which are **metadata, not data**. **To verify**: the exact sub-folder layout inside the archive — list it with `Expand-Archive` and record it here. |
| File type | Plain text, one recording per file |
| Row format | **9 comma-separated integer fields per row, terminated by `;`** — for example `-138,15,36, ...;`. Trailing `;` is stripped before parsing; rows that do not hold exactly nine integers are **skipped**, not coerced, so a mis-parsed row can never become a fake acceleration spike. |
| Encoding | Read as `latin-1` (the files are not UTF-8-clean). |
| Line endings | CRLF in the original files. |

### File naming convention

```
F01_SA01_R01.txt     ← a fall recording
D02_SA01_R01.txt     ← a daily-activity (ADL) recording
```

| Part | Meaning |
|---|---|
| `F` / `D` | **Fall** / **Daily activity** — the label, taken from the file name |
| `01`, `02` | Activity type code (which fall or which ADL was performed) |
| `SA01` / `SE06` | **Subject code**: `S` + cohort letter + number. `A` = adult, `E` = elderly. |
| `R01` | Run number — the repetition of the same activity by the same subject |
| `.txt` | Plain text |

> **Subject codes are directory-level names too.** The cohort prefix in a
> filename is `S` + `A`/`E` + the number, so `SA01` is an adult subject and
> `SE06` is an elderly one. `ai/fall_detection/preprocess.py` parses this with
> the regular expression `([DF])(\d{2})_S([AE])(\d{2})_R(\d{2})\.txt` and
> raises `ValueError` for anything that does not match — a mis-named file is
> caught instead of being assigned to the wrong subject, which would silently
> corrupt the subject-wise split.

---

## 5. Sensors

| Property | Value |
|---|---|
| Sampling rate | **200 Hz** (one sample every 5 ms) |
| Sensor used | **ADXL345 accelerometer** — columns **1–3** of each row |
| Configuration | **±16 g range, 13-bit resolution** |
| Raw representation | **ADC integer counts**, not physical units |
| Conversion | `acceleration [g] = (2 × Range) / (2 ** Resolution) × AD` → **32 / 8192 g per ADC count** (0.00390625 g/count) |
| Other sensors in the file | Columns 4–9 carry additional channels (including a gyroscope) and are **ignored** by this project |

The conversion is not optional. Without it, a threshold or a coefficient has the
units "ADC counts", and the same model cannot be applied to any other sensor.
In code the factor is a single named constant, `ADXL345_G_PER_ADC_BIT`, and
`counts_to_g()` is unit-tested against the Readme's formula rather than being
buried inside the parser.

---

## 6. Labels, preprocessing and features

### 6.1 Labels

| Label | Source | Meaning |
|---|---|---|
| `1` | Filename starts with `F` | Fall recording — contains **exactly one** fall |
| `0` | Filename starts with `D` | ADL recording — contains **no falls** |

| Recording type | Duration | Falls inside |
|---|---|---|
| ADL (`D..`) | 10 s – 180 s | none |
| Fall (`F..`) | 15 s (3,000 rows) | exactly one |

A whole ADL recording is **not** treated as one sample. Comparing a 180-second
file with a 15-second file would confuse "long recording" with "activity", so
everything is cut into fixed-length windows first, with the **same** window
length and stride for both classes — neither class gets an easier shape.

### 6.2 Windowing

| Property | Value |
|---|---|
| Window length | **400 rows = 2.0 s** at 200 Hz |
| Stride | **200 rows = 1.0 s** (**50 % overlap**) |
| Trailing remainder | Dropped — a 0.2 s fragment is not a fall candidate |

2 s is short enough to localise a fall inside a long ADL file and long enough
to contain the impact plus the stillness that follows it. The 50 % overlap
produces more windows from a handful of falls, which is the main defence
against this dataset's severe class imbalance.

### 6.3 Features — 40 per window

Ten time-domain statistics are computed for **each of four signals**: the three
axes (`x`, `y`, `z`) and the **vector magnitude** `sqrt(x² + y² + z²)`.

| # | Statistic | Meaning |
|---|---|---|
| 1 | `mean` | average level |
| 2 | `std` | variability |
| 3 | `min` | lowest value |
| 4 | `max` | highest value (the impact peak) |
| 5 | `median` | robust centre |
| 6 | `iqr` | interquartile range (75th − 25th percentile) |
| 7 | `rms` | root-mean-square |
| 8 | `range` | `max − min` |
| 9 | `mean_abs_diff` | mean absolute difference between consecutive samples |
| 10 | `zero_crossings` | sign changes of the mean-centred signal |

**4 signals × 10 statistics = 40 features.** The feature **order** is part of
the contract: the trained model stores it, and serving must produce the same
columns. The magnitude is included because it is invariant to how the device is
rotated on the body — exactly the variation a real deployment has and the lab
does not.

### 6.4 Scaling

A per-feature standardiser (`mean`, `scale`) is fitted **on the training rows
only**. Fitting it on everything would let the test set's mean and variance
leak into training; the code makes that mistake awkward to write by accident
(`fit_scaler` only accepts training rows) and a feature with zero variance gets
`scale = 1.0` so it cannot divide by zero.

---

## 7. How it is split

**By subject, never by row.** This is the single most important correctness
property of the whole pipeline: if windows from one person land in both train
and test, the model has effectively been tested on people it has already
memorised, and the score becomes meaningless.

| Property | Value |
|---|---|
| Unit of the split | **Subject code** (`SA01`, `SE06`, …), never a row or a window |
| Method | Deterministic shuffle of the sorted subject list, then take the first `round(n × test_fraction)` |
| Default test fraction | **0.25** (`split_subjects(..., test_fraction=0.25)`) |
| Seed | **20260101** — fixed, so a rerun reproduces the reported metrics exactly |
| Subject list | Derived **from the archive itself**, not hard-coded, so the split cannot drift away from the data that is actually there |
| Cohort reporting | Adult and elderly results are reported separately, because they are not equally supported |

The training script then:

1. streams recordings straight out of the zip (no need to extract ~230 MB);
2. builds windows and features per recording;
3. fits the scaler on the **training** windows only;
4. trains the classifier and evaluates it on the **unseen test subjects**.

### Measured result

The top-level [README](../../README.md#what-actually-works-today) records the
fall-detection model as **F1 0.80 on 6 unseen adult subjects** (SisFall). The
detailed metrics — including the weaker elderly result — are published in
`ai/fall_detection/README.md`, the path the top-level README points at.

> Two facts about that number must travel with it:
> 1. It was measured on **adult** subjects only.
> 2. The elderly result rests on **one** subject (see §8) and must be labelled
>    as such wherever it appears.

---

## 8. Limitations

These are not caveats for the sake of it. Each one constrains what the trained
model may be claimed to do.

| # | Limitation | What it means |
|---|---|---|
| 1 | **Severe class imbalance** | Many ADL recordings against far fewer falls. A model that answered "no fall" every time would already score well on accuracy, which is why the reported figure is F1 for the fall class, and why the window overlap exists. |
| 2 | **Only one elderly subject simulates falls** | Any elderly result rests on a **single subject** and must be labelled that way. It is evidence that the pipeline runs on the elderly cohort — it is not evidence that the model works on elderly people in general. |
| 3 | **Lab conditions, not deployment** | Fallen simulations on a controlled protocol, a fixed sensor position, and known activity types. A real deployment has different sensor placement, different clothing, soft and slow falls, walking aids, and activities nobody scripted. The measured F1 **does not transfer** to a home without further validation. |
| 4 | **Simulated falls, not real ones** | The volunteers performed the falls. That is a controlled, repeatable protocol; it is not the same as an accidental fall. |
| 5 | **Only the ADXL345 is used** | Columns 4–9 (including the gyroscope) are ignored, so the model is an accelerometer-only model. |
| 6 | **The archive is not committed** | A fresh clone has no data. The model must be retrained locally before the API can answer anything, and until then the predictor reports `is_ready: false` and `metrics: null`. |
| 7 | **The trained model is not committed** | Same reason: model artefacts are git-ignored. The model is reproducible from the data, but the data must be re-downloaded first. |
| 8 | **Result provenance is research data** | Every prediction derived from this dataset is flagged `is_simulated: true` and carries `source="imported_dataset"`. It can never be shown as a resident's own reading. |

---

## 9. Reproducing it

```powershell
# 1. Download the archive from the publisher and place it at:
#    data\raw\SisFall_dataset.zip
#    (it is git-ignored; never commit it)

# 2. Record the checksum in §1 of this file, so the next download is comparable:
Get-FileHash .\data\raw\SisFall_dataset.zip -Algorithm SHA256

# 3. Train (writes artefacts to ai/models/fall_detection/, also git-ignored):
.\.venv\Scripts\python.exe -m ai.fall_detection.train
```

The training run prints the measured precision / recall / F1 for the fall class
— **including the worse elderly result** — and writes them next to the model.
Skipping this step is fine: everything else in the project works, and the AI
endpoints will report the model as unavailable rather than inventing a
prediction.

---

## 10. See also

- [Datasets index](README.md) — the template and the rules.
- [UP-Fall](up-fall.md) — the dataset this one replaced, and why.
- [`ai/fall_detection/preprocess.py`](../../ai/fall_detection/preprocess.py) —
  the authoritative implementation of everything in §4–§7.
- [`ai/fall_detection/README.md`](../../ai/fall_detection/README.md) — the
  module's own report of the measured metrics.
- [Architecture](../architecture.md) — where the AI layer sits.
- [API contract](../api-contract.md) — how a prediction reaches the frontend.
