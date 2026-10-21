# UCI HAR — Human Activity Recognition Using Smartphones

> Status: **planned — NOT downloaded, NOT used.**
> No model uses this dataset yet. The planned consumer, `ai/activity_recognition/`,
> exists **only as a documented placeholder** (`__init__.py` + `README.md`) —
> there is no `preprocess.py`, no `train.py` and no `predictor.py` — so the API
> answers activity-recognition requests with **HTTP 503** and code
> `MODEL_NOT_LOADED`.

This document exists because the dataset is a **planned dependency**, and a
planned dependency still needs its licence, its size, and its shape written down
*before* somebody spends an evening downloading it. It was written first, as
[CONTRIBUTING.md](../../CONTRIBUTING.md) task **T1** requires. Nothing here
reports a measured result, because there is no model and no measurement.

---

## 1. Identity

| Field | Value |
|---|---|
| **Name** | Human Activity Recognition Using Smartphones (UCI HAR) |
| **Repository** | UCI Machine Learning Repository — dataset id **240** |
| **Kind** | Publicly released research dataset (smartphone inertial sensors + manual activity labels) |
| **Citation** | Reyes-Ortiz, J.; Anguita, D.; Ghio, A.; Oneto, L.; Parra, X. (2013). *Human Activity Recognition Using Smartphones* [Dataset]. UCI Machine Learning Repository. <https://doi.org/10.24432/C54S4K> |
| **Introductory paper** | Anguita, D.; Ghio, A.; Oneto, L.; Parra, X.; Reyes-Ortiz, J. L. (2013). *A Public Domain Dataset for Human Activity Recognition using Smartphones*. ESANN 2013. |
| **Source URL** | `https://archive.ics.uci.edu/dataset/240/human+activity+recognition+using+smartphones` |
| **Licence** | The repository lists **CC BY 4.0** for this dataset. **To verify:** the precise terms and the attribution wording that will apply to anything this project redistributes — re-read the licence section on the dataset page before redistributing, and keep the required credit with the citation in §1. |
| **Version / date** | Donated **12 September 2012**; the repository page is the current release. An **updated** variant ("Smartphone-Based Recognition of Human Activities and Postural Transitions") also exists, which additionally contains the raw inertial signals and postural-transition labels — see §6. |
| **Size** | The repository page lists the archive `UCI HAR Dataset.zip` as **58.2 MB**. **To verify:** the exact byte size of the copy actually downloaded, recorded here once it is fetched. |
| **Checksum (SHA-256)** | **To verify** — no download has happened, so there is nothing to hash. Compute it on download: <br>`Get-FileHash .\data\raw\UCI HAR Dataset.zip -Algorithm SHA256` |
| **Used by** | **Nothing yet.** The planned consumer is `ai/activity_recognition/` (see §7). |

---

## 2. What the dataset contains

| Property | Value |
|---|---|
| **Volunteers** | **30** (subject ids **1–30**), age bracket 19–48 |
| **Device** | Samsung Galaxy S II, worn on the waist |
| **Sensors** | 3-axial accelerometer (linear acceleration) + 3-axial gyroscope (angular velocity), sampled at a constant **50 Hz** |
| **Channels** | **9** — `body_acc` x/y/z, `body_gyro` x/y/z, `total_acc` x/y/z |
| **Activities** | **6** — `WALKING`, `WALKING_UPSTAIRS`, `WALKING_DOWNSTAIRS`, `SITTING`, `STANDING`, `LAYING` |
| **Labelling** | The experiments were video-recorded and the data labelled manually from the video |
| **Instances** | **10,299** annotated windows |
| **Window shape** | **2.56 s** wide, **128 readings** per window, **50 % overlap** |
| **Features per instance** | **561** time- and frequency-domain variables, plus the activity label and the subject id |
| **Pre-processing done by the publisher** | Noise filtering, then a **Butterworth low-pass filter (0.3 Hz)** separating body acceleration from the gravity component; gravity is assumed to be low-frequency only |
| **Split** | Random partition of the **volunteers**: **70 % → training, 30 % → test**. The two sets are disjoint by person. |

### Coverage against this project's activity vocabulary

The application vocabulary in `ai/base.py` is
`walking · standing · sitting · lying · eating · sleeping · toileting · unknown`.

| UCI HAR class | Maps to | Note |
|---|---|---|
| `WALKING` | `walking` | direct |
| `WALKING_UPSTAIRS` | `walking` | direct (a climbing variant) |
| `WALKING_DOWNSTAIRS` | `walking` | direct (a descending variant) |
| `STANDING` | `standing` | direct |
| `SITTING` | `sitting` | direct |
| `LAYING` | `lying` | direct |
| — | `eating`, `sleeping`, `toileting` | **no counterpart in UCI HAR** |

So this dataset covers **four** of the eight labels the application knows. The
remaining labels would have to stay `unknown`, or come from another source.
That is a scoping decision to make before training, not after.

---

## 3. Why this is a reasonable choice

- **It is the canonical benchmark** for wearable activity recognition. A result
  on UCI HAR is comparable with published work, which matters for a project
  whose evaluation has to be honest.
- **The labels are human-assigned** from video, not inferred, so the ground
  truth is not the model that produced it.
- **It is small enough to be practical** — tens of megabytes, against the
  ~812 GB that made [UP-Fall](up-fall.md) unusable.
- **The subject-wise split already exists**, so the leakage that would ruin the
  evaluation (windows from one person in both train and test) is avoidable by
  construction.
- **The signal is close to what this project would deploy**: a triaxial
  accelerometer on the body, which is also what the fall-detection pipeline in
  `ai/fall_detection/` already consumes.

### Where it is a weaker fit

- Volunteers are **19–48 years old** — this project monitors elderly residents.
  The fall-detection model already has to declare that its elderly result rests
  on a single subject; the same caution applies here, from the start.
- The activities are **staged** in a laboratory, with a phone on the waist.
- The phone is carried by the person; the care home's residents may not carry
  one at all, which raises the question of where the sensor would live.

---

## 4. Planned preprocessing

Not written yet. The intended pipeline, mirroring `ai/fall_detection/`:

1. **Parse** the raw inertial signal files (`body_acc`, `body_gyro`,
   `total_acc`), keeping the subject id and the activity label per window.
2. **Window** the continuous signal into fixed-length segments with a stated
   overlap, and recompute features from the signal rather than reusing the
   publisher's 561-feature table — the feature set must match what the
   application can compute at inference time.
3. **Extract per-signal features** with the same statistics the fall-detection
   pipeline uses (`ai/fall_detection/preprocess.py` → mean, std, min, max,
   median, iqr, rms, range, mean_abs_diff, zero_crossings, plus the vector
   magnitude), so both models share one feature vocabulary and one code path.
4. **Normalise** with a scaler **fitted on the training rows only**. Fitting it
   on everything would leak the test set's mean and variance — the same mistake
   the fall-detection module goes out of its way to make impossible.
5. **Split by subject**, using the publisher's disjoint train/test volunteers,
   and report metrics on the held-out subjects only.

> Everything in this section is a plan. It has not been run, so it has no
> numbers attached to it.

---

## 5. Local location

| What | Path | Committed? |
|---|---|---|
| Downloaded archive | `data/raw/UCI HAR Dataset.zip` (name **To verify** — keep the publisher's filename) | ❌ **No** — `data/raw/**` is git-ignored |
| Extracted data | `data/raw/UCI HAR Dataset/` | ❌ **No** |
| Derived features | `data/processed/` | ❌ **No** — `data/processed/**` is git-ignored |
| Trained model artefacts | `ai/models/activity_recognition/` | ❌ **No** — `ai/**/models/` is git-ignored |

---

## 6. Open questions before downloading

| # | Question | Status |
|---|---|---|
| 1 | The publisher's window size (2.56 s / 128 readings) or a window matched to the fall-detection pipeline (2 s / 400 rows at 200 Hz)? | **To decide** |
| 2 | Use the standard archive, or the updated variant with the **raw inertial signals**? The updated variant is more useful for a from-scratch pipeline but is a different download. | **To decide** |
| 3 | Confirm the licence terms and the attribution wording. | **To verify** |
| 4 | Record the exact archive size in bytes and its SHA-256. | **To verify** |
| 5 | Which of the four uncovered application labels (`eating`, `sleeping`, `toileting`) are in scope, and from which source? | **To decide** |

---

## 7. What will consume it

| Item | State |
|---|---|
| `ai/activity_recognition/` (preprocess → train → predictor) | **Placeholder only.** The package exists with `__init__.py` and a `README.md` that states the plan; `preprocess.py`, `train.py` and `predictor.py` do **not** exist yet. It should follow the structure of `ai/fall_detection/` exactly. |
| `ai/registry.py` | The `activity_recognition` predictor is already registered and is currently an `UnavailablePredictor`. |
| API today | `GET /api/v1/ai/predictors` reports `is_ready: false` for activity recognition. `POST /api/v1/ai/predictors/activity_recognition/check` returns **HTTP 503** with code **`MODEL_NOT_LOADED`**. |
| API after training | The predictor becomes a real one. Every result it produces carries `source="imported_dataset"` and therefore `is_simulated: true`, so a research-data prediction can never be presented as a resident's own reading. |

This is the API's honest "not available yet" behaviour, and it is deliberate:
an activity classifier that returned a plausible-looking label with no model
behind it would be worse than one that says it cannot answer.

---

## 8. See also

- [Datasets index](README.md) — the index and the rules.
- [CASAS](casas.md) — the planned dataset for behavioural analysis.
- [SisFall](sisfall.md) — the dataset that **is** used, and the template for how this file should read once it is.
- [`ai/activity_recognition/README.md`](../../ai/activity_recognition/README.md) — the module's own statement of the plan and of what is missing.
- [CONTRIBUTING.md](../../CONTRIBUTING.md#open-tasks) — task **T1**, which this dataset serves.
